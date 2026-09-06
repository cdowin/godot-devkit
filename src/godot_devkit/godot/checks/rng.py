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
"""
from __future__ import annotations

import re

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
BARE_DRAW_RE = re.compile(r'(?<![.\w])(?:randi_range|randf_range|randi|randf)\s*\(')


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


def scan_text(text: str, path: str) -> list[Hit]:
    """Every bare-RNG / `randomize()` call in one GDScript source."""
    hits: list[Hit] = []
    func = FILE_SCOPE
    for lineno, raw in enumerate(text.split('\n'), start=1):
        declaration = FUNC_RE.match(raw)
        if declaration:
            func = declaration.group(1)
        if DOC_COMMENT_RE.match(raw):
            continue
        code = code_only(raw)
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

    findings: list[str] = []
    matched = set()
    for hit in hits:
        if hit.key in allowed:
            matched.add(hit.key)
            continue
        findings.append(f'  BARE-RNG  {hit}')
    # CHECK 3 — reported in the SAME run as CHECK 1/2, never after an early
    # exit: two findings classes are two things to fix, and a gate that reveals
    # the second only once you have fixed the first costs a round trip.
    for key in sorted(set(allowed) - matched):
        findings.append(f'  STALE  {key} — no longer matches a bare-RNG call; '
                        f'drop it from [{SECTION}] allowlist')

    if findings:
        for finding in findings:
            print(finding)
        print(f'\n{TAG} FAIL — {len(findings)} finding(s) across '
              f'{len(scanned)} script(s) under {", ".join(roots)}')
        print('  A run-scoped draw comes from a generator the caller owns, '
              'seeded from the run seed.')
        print(f'  Cosmetic-only randomness is a carve-out: name it in '
              f'[{SECTION}] allowlist WITH a reason.')
        print('  An allowlist that outlives its violations is a place to hide '
              'things — prune it.')
        return 1

    print(f'{TAG} PASS — {len(scanned)} script(s) under {", ".join(roots)} draw '
          f'from an owned RNG; {len(allowed)} allowlisted site(s), each with a reason')
    return 0
