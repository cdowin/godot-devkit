"""rng.py — check rng: run-scoped code draws from an RNG it OWNS.

A seeded run is reproducible only if every draw it makes comes from a stream
derived from its seed. `randi()` / `randf()` / `randi_range()` / `randf_range()`
called unqualified are the GLOBAL generator, and `randomize()` re-seeds from
entropy — on an instance RNG that is strictly worse than doing it globally,
because the result then LOOKS derived. `rng.randf()` on a generator you own is
the point of the gate, not a violation of it.

Three checks, each a distinct failure mode:

  CHECK 1  an UNQUALIFIED global draw — no `.` and no identifier character
           immediately before the call.
  CHECK 2  `randomize()` in ANY spelling, bare or on an instance.
  CHECK 3  every allowlist entry still matches a real violation. A stale entry
           is a place to hide things, so it is a finding too.

SCOPE is `[rng] roots` and it is meant to be NARROW. Scanning a whole game
drowns the signal in menu shimmer and cosmetic jitter; the roots that hold
run-scoped randomness are the roots worth gating, and widening them is not a
free improvement.

A DECLARATION is not a call: a seeded-stream owner that exposes the draw API
under the engine's names (`func randf() -> float:`) is the thing the gate asks
for, so the `func <name>` head of a line is never matched (#30). And inside a
script that DECLARES one of those names, an unqualified call to it is a call to
the script's OWN method, not the global generator — so that is not a hit
either. The shadow is scoped per class body: a script's own `func randf()`
does not reach into a `class Inner:` block, nor an inner class's out of it. A
script that declares none of them is judged exactly as before.

HONEST SCOPE: matching is per line, after quoted strings and a trailing `#`
comment are stripped, with `##` doc-comment lines skipped whole — a call NAMED
in prose is not a call. A call split across a line break slips through.

devkit.toml:

    [rng]
    roots = ["systems/progression", "resources/loot"]
    # key: `<path>:<enclosing func>`, value: the REASON. Function granularity,
    # not line numbers — a name survives edits above it, while a new bare call
    # in a different function of a listed file still trips the gate.
    allowlist = { "systems/hazards/wormhole_visual.gd:_ready" = "cosmetic pulse phase" }
    # Existing debt, per file at its CURRENT count of bare-RNG lines — the
    # adoption step before the allowlist's reasoned carve-outs. Held and counted
    # on a BASELINED line; a file past its entry fails, and an entry above what
    # is left fails until lowered — it only shrinks.
    baseline = { "systems/progression/loot_roll.gd" = 4 }
"""
from __future__ import annotations

import re

from godot_devkit.core.baseline import read_baseline
from godot_devkit.core.config import ConfigError, config_section, str_tuple, str_tuple_table
from godot_devkit.core.project import git_lines, repo_root
from godot_devkit.godot.index.gdscript import code_only

SECTION = 'rng'
TAG = '[check:rng]'
SUFFIX = '.gd'
# The whole tree. A repo narrows this; a repo that does not gets every tracked
# script, which is loud rather than silent — the direction rule 4 asks for.
DEFAULT_ROOTS = ('.',)
# The key grammar: `<path>:<func>`. A key with no separator can never match a
# hit, so it would report as permanently stale — a config typo wearing a
# finding's clothes. Refused at exit 2 instead.
KEY_SEPARATOR = ':'
FILE_SCOPE = '<file-scope>'

FUNC_RE = re.compile(r'^\s*(?:static\s+)?func\s+([A-Za-z_]\w*)')
DOC_COMMENT_RE = re.compile(r'^\s*##')
RANDOMIZE_RE = re.compile(r'randomize\s*\(')
# `(?<![.\w])` is the whole of CHECK 1: `rng.randf(` and `my_randf(` are not
# the global generator, and neither is a match.
DRAW_NAMES = ('randi_range', 'randf_range', 'randi', 'randf')
BARE_DRAW_RE = re.compile(rf'(?<![.\w])(?:{"|".join(DRAW_NAMES)})\s*\(')
# The names a script can shadow with its own `func`: every draw, and
# `randomize` (whose QUALIFIED spellings stay CHECK 2's either way).
SHADOWABLE = frozenset((*DRAW_NAMES, 'randomize'))
# The `func <name>` head of a declaration line — blanked before matching, so a
# one-line body after it (`func f(): return randf()`) is still judged.
FUNC_HEAD_RE = re.compile(r'^\s*(?:static\s+)?func\s+[A-Za-z_]\w*')
# A `class <Name>:` header whose body is the indented block below it. The
# trailing `:` with nothing after it is what makes a body; `class_name` is not
# a match (`class` must be followed by whitespace).
CLASS_RE = re.compile(r'^(\s*)class\s+[A-Za-z_]\w*\b[^:]*:\s*$')


class Hit:
    """One bare-RNG call: where it is, and which function encloses it."""

    __slots__ = ('path', 'lineno', 'func', 'code')

    def __init__(self, path: str, lineno: int, func: str, code: str) -> None:
        self.path, self.lineno, self.func, self.code = path, lineno, func, code

    @property
    def key(self) -> str:
        """The allowlist key this hit would be silenced by."""
        return f'{self.path}{KEY_SEPARATOR}{self.func}'

    def __str__(self) -> str:
        return f'{self.path}:{self.lineno}:{self.func}:{self.code.strip()}'


def _indent(code: str) -> int:
    return len(code) - len(code.lstrip())


def _scopes(lines: list[str]) -> list[int]:
    """The class body each line sits in: 0 is the script, n the n-th `class`.

    A body is the indented block under a `class <Name>:` header, closed by the
    first code line at or left of the header's indentation; a blank or
    comment-only line closes nothing. The header itself sits in the outer scope.
    """
    scope_of: list[int] = []
    stack = [(-1, 0)]  # (header indent, scope id)
    opened = 0
    for raw in lines:
        code = code_only(raw)
        if code.strip():
            while len(stack) > 1 and _indent(code) <= stack[-1][0]:
                stack.pop()
        scope_of.append(stack[-1][1])
        header = CLASS_RE.match(code)
        if header:
            opened += 1
            stack.append((len(header.group(1)), opened))
    return scope_of


def _own_calls(lines: list[str], scope_of: list[int]) -> dict[int, re.Pattern]:
    """Per scope, the pattern of unqualified calls to that scope's OWN methods.

    A `func randf()` shadows the global only inside the body that declares it,
    at that body's member indentation: a script's column-0 `func` does not
    reach into `class Inner:`, and an inner class's `func` does not reach out.
    """
    member: dict[int, int] = {0: 0}
    names: dict[int, set[str]] = {}
    for raw, scope in zip(lines, scope_of):
        code = code_only(raw)
        if not code.strip():
            continue
        indent = member.setdefault(scope, _indent(code))
        declaration = FUNC_RE.match(code)
        if declaration and _indent(code) == indent:
            names.setdefault(scope, set()).add(declaration.group(1))
    out: dict[int, re.Pattern] = {}
    for scope, declared in names.items():
        own = sorted(declared & SHADOWABLE)
        if own:
            out[scope] = re.compile(rf'(?<![.\w])(?:{"|".join(own)})\s*\(')
    return out


def scan_text(text: str, path: str) -> list[Hit]:
    """Every bare-RNG / `randomize()` call in one GDScript source."""
    hits: list[Hit] = []
    func = FILE_SCOPE
    lines = text.split('\n')
    scope_of = _scopes(lines)
    own_call = _own_calls(lines, scope_of)
    for lineno, raw in enumerate(lines, start=1):
        declaration = FUNC_RE.match(raw)
        if declaration:
            func = declaration.group(1)
        if DOC_COMMENT_RE.match(raw):
            continue
        code = code_only(raw)
        if declaration:
            code = FUNC_HEAD_RE.sub('', code, count=1)
        shadow = own_call.get(scope_of[lineno - 1])
        if shadow:
            code = shadow.sub('', code)
        # One line is one hit however many spellings it holds: `rng.randomize()`
        # matches CHECK 2 and not CHECK 1, and reporting a line twice would
        # inflate the count a consumer reads as "how much is broken".
        if RANDOMIZE_RE.search(code) or BARE_DRAW_RE.search(code):
            hits.append(Hit(path, lineno, func, raw))
    return hits


def _allowlist(sect: dict) -> dict[str, str]:
    """`{key: reason}` from `[rng] allowlist`, with the grammar enforced.

    The reason is DATA, not a comment above the entry: a carve-out nobody had
    to justify is a carve-out nobody will ever revisit.
    """
    raw = str_tuple_table(sect, SECTION, 'allowlist', {})
    out: dict[str, str] = {}
    for key, reasons in raw.items():
        if KEY_SEPARATOR not in key or not key.split(KEY_SEPARATOR)[0].strip():
            raise ConfigError(
                f'[{SECTION}] allowlist key {key!r} is not '
                f'"<path>{KEY_SEPARATOR}<enclosing func>" — a key that cannot '
                f'match a call would report as permanently stale')
        reason = ' '.join(r.strip() for r in reasons).strip()
        if not reason:
            raise ConfigError(
                f'[{SECTION}] allowlist entry {key!r} has no reason — write '
                f'{key!r} = "why this draw is allowed"')
        out[key] = reason
    return out


def run() -> int:
    sect = config_section(SECTION)
    roots = str_tuple(sect, SECTION, 'roots', DEFAULT_ROOTS)
    allowed = _allowlist(sect)
    baseline = read_baseline(sect, SECTION)
    root = repo_root()
    scanned = [rel for rel in git_lines('ls-files', '--', *roots)
               if rel.endswith(SUFFIX)]
    if not scanned:
        # Rule 4 — a gate that scanned nothing must say so. A wrong root is
        # indistinguishable from a clean tree, and that PASS is the most
        # dangerous output this package emits.
        print(f'{TAG} FAIL — no tracked *{SUFFIX} under '
              f'{", ".join(roots)}; check [{SECTION}] roots')
        return 1

    hits: list[Hit] = []
    for rel in scanned:
        try:
            text = (root / rel).read_text(encoding='utf-8', errors='replace')
        except OSError:
            continue
        hits.extend(scan_text(text, rel))

    bare: list[tuple[str, str]] = []
    matched = set()
    for hit in hits:
        if hit.key in allowed:
            matched.add(hit.key)
            continue
        bare.append((hit.path, f'  BARE-RNG  {hit}'))
    judged = baseline.judge(bare)
    findings = judged.open
    # CHECK 3 — reported in the SAME run as CHECK 1/2, never after an early
    # exit: two findings classes are two things to fix, and a gate that reveals
    # the second only once you have fixed the first costs a round trip.
    for key in sorted(set(allowed) - matched):
        findings.append(f'  STALE  {key} — no longer matches a bare-RNG call; '
                        f'drop it from [{SECTION}] allowlist')

    if findings:
        for finding in findings:
            print(finding)
        judged.report()
        print(f'\n{TAG} FAIL — {len(findings)} finding(s) across '
              f'{len(scanned)} script(s) under {", ".join(roots)}')
        print('  A run-scoped draw comes from a generator the caller owns, '
              'seeded from the run seed.')
        print(f'  Cosmetic-only randomness is a carve-out: name it in '
              f'[{SECTION}] allowlist WITH a reason.')
        print('  An allowlist that outlives its violations is a place to hide '
              'things — prune it.')
        return 1

    judged.report()
    if judged.failed:
        print(judged.verdict(TAG, f'{len(scanned)} script(s) under '
                                  f'{", ".join(roots)}'))
        return 1
    print(f'{TAG} PASS — {len(scanned)} script(s) under {", ".join(roots)} draw '
          f'from an owned RNG; {len(allowed)} allowlisted site(s), each with a reason')
    return 0
