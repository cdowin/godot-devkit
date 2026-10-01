#!/usr/bin/env python3
"""refs.py — reference-AWARE symbol search across .gd/.tscn/.tres.

grep can't tell a type-ref from a string/comment match. This finds every
REAL usage of a `class_name`, method, signal, or a `.gd`/`.tscn`/`.tres`
path/uid, grouped by kind: definitions, typed refs, call/emit sites,
preload/load, scene resource refs — and, in a bucket of its own, the TEXTUAL
signal hits the typed index cannot resolve (`entity.died.connect(` on an
untyped `entity`, `emit_signal(&"died")`, `connect("died", …)`). Those are
not proven references, and they are not nothing either: a zero verdict prints
only when BOTH buckets are empty, because zero is the answer that gets a
signal deleted (#19). `refs --retarget` never acts on a dynamic hit.
It also indexes what Godot itself wires, which no `.gd` line spells: a
`[connection signal=… method=…]` in a scene (typed, `scene connections`), and
an autoload NAME from `project.godot [autoload]`, indexed like a `class_name`
(its `project.godot` entry the definition, the name as a bare identifier
anywhere in code a typed ref, and a `"/root/Name"` node-path string a dynamic
hit). A `class_name` is a global the same way: its bare identifier in code —
`Player.new()`, `Player.CONST`, `var p := Player` — is a typed ref. A signal or handler named as an argument — `is_connected("sig"`,
`has_signal("sig"`, `Signal(obj, "sig"` — is a dynamic hit; a bare handler
in `is_connected(…, h)` / `disconnect(…, h)` is a call site.
Comment-stripped (the capability-scan
doctrine: everything after the first `#` on a line is dropped before
matching — pragmatic, not string-literal-aware). Pure parse — never writes,
never boots Godot.

    make refs NAME=<symbol>
    python3 tools/dev/introspect/refs.py <symbol> [--tests]

devkit.toml: [refs] exclude_prefixes = [".git/", ".godot/", "addons/", ...]
             (replaces the stock exclusion list wholesale)
"""
from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path

from godot_devkit.godot.format.tscn import parse, basename
from godot_devkit.godot.read.autoloads import PROJECT_GODOT, Refusal, list_autoloads
from godot_devkit.core.project import repo_root
from godot_devkit.core import walk
from godot_devkit.core.walk import Kind, SkipReason
from godot_devkit.core.config import ConfigError, config_section, str_tuple

# --- Scope -------------------------------------------------------------------
CONFIG_SECTION = 'refs'
DEFAULT_EXCLUDE = ('.git/', '.godot/', '.claude/worktrees/', 'pm/roadmap/zz_archive/', 'addons/')
GD_GLOB = '*.gd'
SCENE_GLOBS = ('*.tscn', '*.tres')

# --- Typed-ref grammar (word-boundary, comment-stripped) ---------------------
TYPED_REF_KEYWORDS = ('extends', 'is', 'as')

# --- Bucket kinds: a Hit's `kind`, one per report section ---------------------
DEFINITION_KIND = 'definition'
TYPED_REF_KIND = 'typed_ref'
CALL_EMIT_KIND = 'call_emit'
PRELOAD_LOAD_KIND = 'preload_load'
SCENE_REF_KIND = 'scene_ref'
SCENE_CONNECTION_KIND = 'scene_connection'
DYNAMIC_KIND = 'dynamic'


class EmptySymbol(Exception):
    """No symbol to search for. Exit 2 — a usage error, never a scan."""


@dataclass
class Hit:
    kind: str
    path: str
    line: int
    text: str


def _relpath(root: Path, path: Path) -> str:
    return str(path.relative_to(root))


def exclude_prefixes() -> tuple[str, ...]:
    """The `[refs] exclude_prefixes` scope, guarded — one key, one scope,
    shared by `refs` and `refs --retarget` (write side) so the two can never
    disagree about what the refs family looks at."""
    return str_tuple(config_section(CONFIG_SECTION), CONFIG_SECTION,
                     'exclude_prefixes', DEFAULT_EXCLUDE)


def iter_files(root: Path, exclude: tuple[str, ...], glob: str,
               include_tests: bool) -> walk.Walk:
    """The walk, not its kept half. `run()` merges these and prints ONE census
    off the result: before 0.25.0's review each caller ended `list(found.kept)`,
    which dropped the skipped half on the floor, and an `exclude_prefixes` that
    ate the tree printed `(no references found)` — byte-identical to a symbol
    with genuinely no references (rule 4)."""
    def _is_excluded(path: Path) -> bool:
        return any(_relpath(root, path).startswith(prefix) for prefix in exclude)

    found = walk.descendants(root, Kind.ANY, pattern=glob).filter(
        lambda p: not _is_excluded(p), SkipReason.EXCLUDED_PATH)
    if not include_tests:
        found = found.filter(lambda p: not _relpath(root, p).startswith('tests/'),
                             SkipReason.EXCLUDED_PATH)
    return found


def strip_comment(line: str) -> str:
    """The capability-scan doctrine: drop everything from the first `#` on —
    pragmatic, not string-literal-aware (matches the project's own gate)."""
    return line.split('#', 1)[0]


def _typed_ref_pattern(symbol: str) -> re.Pattern:
    word = re.escape(symbol)
    alternatives = [
        rf':\s*{word}\b',            # : Sym  (typed var/param/return)
        rf'->\s*{word}\b',           # -> Sym (typed return)
        rf'\bArray\[{word}\]',       # Array[Sym]
        rf'\bDictionary\[.*{word}.*\]',  # Dictionary[..., Sym]
    ]
    alternatives += [rf'\b{kw}\s+{word}\b' for kw in TYPED_REF_KEYWORDS]
    return re.compile('|'.join(alternatives))


def _global_pattern(symbol: str) -> re.Pattern:
    """A GLOBAL name — a `project.godot [autoload]` NAME or a `class_name` —
    which a script reaches with no type annotation to anchor on: `Name.method(`,
    `Name.new()`, `Name.CONST`, `var g = Name`, `if Name:`. The bare identifier
    anywhere in code is the reference. Not after `.` (a member), nor after `/`,
    `$` or `%` (a node path — `"/root/Name"` is the dynamic bucket's). Only a
    global gets this arm: on any other symbol a bare `name` is far more often
    a variable than a type."""
    return re.compile(rf'(?<![\w./$%]){re.escape(symbol)}\b')


def _class_name_pattern(symbol: str) -> re.Pattern:
    return re.compile(rf'\bclass_name\s+{re.escape(symbol)}\b')


def _global_use(global_pattern: re.Pattern, definition_pattern: re.Pattern,
                stripped: str) -> bool:
    """A bare use of the global on this line, outside its own declaration —
    `class_name Player` is the definition, counted once, never a typed ref."""
    declared = [m.span() for m in definition_pattern.finditer(stripped)]
    return any(not any(start <= m.start() < end for start, end in declared)
               for m in global_pattern.finditer(stripped))


def _call_emit_pattern(symbol: str) -> re.Pattern:
    word = re.escape(symbol)
    alternatives = [
        rf'\.{word}\(',              # .name(   — method call
        rf'\b{word}\.emit\(',        # name.emit(
        rf'(?<![\w.]){word}\.(?:connect|disconnect)\(',  # name.connect( — receiverless (self); a dotted receiver is the dynamic bucket's
        rf'\.connect\(\s*{word}\b',  # .connect(name
        # is_connected(…, name) / disconnect(…, name) — the handler, bare, as
        # the callable argument (Object's two-argument form, or Signal's one)
        rf'\b(?:is_connected|disconnect)\(\s*(?:[^,()]*,\s*)?{word}\b(?!\s*\()',
    ]
    return re.compile('|'.join(alternatives))


def _bare_call_pattern(symbol: str) -> re.Pattern:
    """`name(` with no receiver — the SAME-FILE call, which is how GDScript
    spells a call to a method of `self`.

    Every call-site alternative required a `.` before the name, so a method
    called only from within its own script read as zero references — and zero
    references is the answer that gets a method deleted. The lookbehind keeps
    `other.name(` out (the dotted arm already owns it, and one line counts
    once), and `_on_name(` out — `\b` alone would not, since `_` is a word
    character on the wrong side of the boundary.

    The DEFINITION line matches this too (`func name(` is `name(`), so the
    caller excludes it — see `scan_gd_files`.
    """
    return re.compile(rf'(?<![\w.]){re.escape(symbol)}\s*\(')


def _definition_pattern(symbol: str) -> re.Pattern:
    word = re.escape(symbol)
    alternatives = [
        rf'\bfunc\s+{word}\s*\(',       # func name(   — method/signal-handler definition
        rf'\bclass_name\s+{word}\b',    # class_name Sym  — the class's own declaration
        rf'\bsignal\s+{word}\b',        # signal name  — the signal's own declaration
    ]
    return re.compile('|'.join(alternatives))


def _dynamic_pattern(symbol: str, autoload: bool = False) -> re.Pattern:
    """A signal reached through a receiver the index cannot type — the
    textual spellings, owned by no typed arm. `<expr>.name.connect(` is the
    live-subscriber shape on an untyped parameter; the string forms name the
    signal as data. `autoload`: an autoload reached by its node path,
    `get_node("/root/Name")` / `$"/root/Name"` — a string, never typed."""
    word = re.escape(symbol)
    alternatives = [
        rf'\.{word}\.(?:connect|disconnect|emit)\(',       # expr.name.connect(
        rf'\bemit_signal\(\s*&?["\']{word}["\']',          # emit_signal(&"name"
        rf'\b(?:dis)?connect\(\s*&?["\']{word}["\']',       # connect("name" / disconnect("name"
        rf'\b(?:is_connected|has_signal|has_user_signal)\(\s*&?["\']{word}["\']',  # has_signal("name"
        rf'\bSignal\(.*?,\s*&?["\']{word}["\']',          # Signal(obj, "name"
    ]
    if autoload:
        alternatives.append(rf'["\']/root/{word}\b')         # get_node("/root/Name"
    return re.compile('|'.join(alternatives))


PRELOAD_LOAD = re.compile(r'(?:preload|load)\(\s*"([^"]+)"\s*\)')


def typed_spans(symbol: str, stripped: str, global_name: bool = False) -> set[tuple[int, int]]:
    """The `(start, end)` of every `symbol` token the typed arms claim on one
    comment-stripped `.gd` line — the definition, typed-ref and call/emit
    grammar `scan_gd_files` counts the line by, down to the token. What
    `refs --rename` may rewrite is exactly this set, so the read side and the
    write side can never disagree about what a reference is. `global_name`:
    the symbol is an autoload or a `class_name` — see `_global_pattern`."""
    token = re.compile(rf'(?<!\w){re.escape(symbol)}(?!\w)')
    tokens = [(m.start(), m.end()) for m in token.finditer(stripped)]
    spans: set[tuple[int, int]] = set()
    patterns = [_definition_pattern(symbol), _typed_ref_pattern(symbol),
                _call_emit_pattern(symbol), _bare_call_pattern(symbol)]
    if global_name:
        patterns.append(_global_pattern(symbol))
    for pattern in patterns:
        for match in pattern.finditer(stripped):
            spans.update(t for t in tokens
                         if match.start() <= t[0] and t[1] <= match.end())
    return spans


def scan_gd_files(root: Path, symbol: str, files: list[Path],
                  autoload: bool = False) -> dict[str, list[Hit]]:
    """One pass per `.gd` file, feeding all four line-based scan kinds at
    once (definitions / typed refs / call-emit / preload-load) — the four
    kinds used to each re-read + re-split every file independently, a 4x
    redundant-I/O cost with no benefit (they all want the same comment-
    stripped lines). `autoload`: the symbol is an autoload NAME. It and a
    symbol some scanned file declares as its `class_name` are GLOBALS — see
    `_global_pattern` — which is why every file is read before any is scanned.
    """
    definition_pattern = _definition_pattern(symbol)
    typed_ref_pattern = _typed_ref_pattern(symbol)
    call_emit_pattern = _call_emit_pattern(symbol)
    bare_call_pattern = _bare_call_pattern(symbol)
    dynamic_pattern = _dynamic_pattern(symbol, autoload)
    needle = symbol.lower()

    hits: dict[str, list[Hit]] = {DEFINITION_KIND: [], TYPED_REF_KIND: [], CALL_EMIT_KIND: [],
                                  PRELOAD_LOAD_KIND: [], DYNAMIC_KIND: []}
    texts = [(path, path.read_text(encoding='utf-8', errors='replace').split('\n'))
             for path in files]
    class_name_pattern = _class_name_pattern(symbol)
    global_pattern = _global_pattern(symbol) if autoload or any(
        class_name_pattern.search(strip_comment(raw))
        for _, lines in texts for raw in lines) else None
    for path, lines in texts:
        rel = _relpath(root, path)
        for lineno, raw in enumerate(lines, 1):
            stripped = strip_comment(raw)
            if not stripped:
                continue
            text = stripped.strip()
            defines = definition_pattern.search(stripped) is not None
            typed = defines
            if defines:
                hits[DEFINITION_KIND].append(Hit(DEFINITION_KIND, rel, lineno, text))
            if typed_ref_pattern.search(stripped) or (global_pattern is not None and _global_use(
                    global_pattern, definition_pattern, stripped)):
                typed = True
                hits[TYPED_REF_KIND].append(Hit(TYPED_REF_KIND, rel, lineno, text))
            # A receiverless `name(` is a call unless this line is where the
            # name is DECLARED — `func name(` and `signal name(` are the
            # declaration, counted once, in `definitions`. A dotted/emit/
            # connect site still counts on a declaration line (a one-line
            # `func f(): return other.f()` is a real call), so only the bare
            # arm defers.
            if call_emit_pattern.search(stripped) or (
                    not defines and bare_call_pattern.search(stripped)):
                typed = True
                hits[CALL_EMIT_KIND].append(Hit(CALL_EMIT_KIND, rel, lineno, text))
            for match in PRELOAD_LOAD.finditer(stripped):
                target = match.group(1)
                if needle in basename(target).lower() or symbol == target:
                    typed = True
                    hits[PRELOAD_LOAD_KIND].append(Hit(PRELOAD_LOAD_KIND, rel, lineno, text))
            # A line a typed bucket already counts is not counted again here:
            # one line is one reference, and the dynamic count must not
            # inflate a total a reader weighs a delete against.
            if not typed and dynamic_pattern.search(stripped):
                hits[DYNAMIC_KIND].append(Hit(DYNAMIC_KIND, rel, lineno, text))
    return hits


def scan_scene_refs(root: Path, symbol: str, files: list[Path]) -> dict[str, list[Hit]]:
    """Resource refs (`ext_resource` path/uid, `sub_resource` type) and the
    `[connection]` sections naming the symbol as their `signal=` or `method=`.
    A connection is the editor's wiring — no `.gd` line spells it — so a
    handler connected only there read as unreferenced, the verdict that gets
    it deleted and the connection broken at runtime. Read from the parsed
    sections, never a regex over the text."""
    needle = symbol.lower()
    hits: dict[str, list[Hit]] = {SCENE_REF_KIND: [], SCENE_CONNECTION_KIND: []}
    for path in files:
        try:
            sections = parse(str(path))
        except OSError:
            continue
        rel = _relpath(root, path)
        for section in sections:
            if section.kind == 'ext_resource':
                target = section.attrs.get('path') or ''
                uid = section.attrs.get('uid') or ''
                if needle in basename(target).lower() or symbol == uid:
                    kind = section.attrs.get('type', '?')
                    hits[SCENE_REF_KIND].append(Hit(
                        SCENE_REF_KIND, rel, 0,
                        f'ext_resource[{section.attrs.get("id", "?")}] {kind}  {target or uid}'))
            elif section.kind == 'sub_resource' and section.attrs.get('type', '').lower() == needle:
                hits[SCENE_REF_KIND].append(Hit(
                    SCENE_REF_KIND, rel, 0,
                    f'sub_resource[{section.attrs.get("id", "?")}] {section.attrs.get("type")}'))
            elif section.kind == 'connection' and symbol in (
                    section.attrs.get('signal'), section.attrs.get('method')):
                wiring = ' '.join(f'{key}={section.attrs.get(key, "?")}'
                                  for key in ('signal', 'from', 'to', 'method'))
                hits[SCENE_CONNECTION_KIND].append(Hit(
                    SCENE_CONNECTION_KIND, rel, section.header_line + 1, f'[connection] {wiring}'))
    return hits


def scan_autoloads(root: Path, symbol: str) -> list[Hit]:
    """The `project.godot [autoload]` entry declaring `symbol`, as its
    definition — an autoload's name is declared there, not by `class_name`.
    No readable `project.godot` is no autoload, never an error: `refs` works
    in a tree that is not a Godot project."""
    try:
        entries = list_autoloads(root)
    except Refusal:
        return []
    return [Hit(DEFINITION_KIND, PROJECT_GODOT, 0, f'[autoload] {name}  res://{res_path}')
            for name, res_path in entries if name == symbol]


SECTION_TITLES = (
    ('definitions', DEFINITION_KIND),
    ('typed refs', TYPED_REF_KIND),
    ('call / emit sites', CALL_EMIT_KIND),
    ('preload / load', PRELOAD_LOAD_KIND),
    ('scene resource refs (.tscn/.tres)', SCENE_REF_KIND),
    ('scene connections', SCENE_CONNECTION_KIND),
    ('dynamic (untyped receiver)', DYNAMIC_KIND),
)


@dataclass
class Scan:
    """One symbol's hits over the `refs` scope, with the walk behind them —
    the census a reader prints, and the files a writer re-reads."""
    searched: walk.Walk
    gd_files: list[Path]
    scene_files: list[Path]
    hits: dict[str, list[Hit]]
    global_name: bool     # an autoload or a `class_name` — see `_global_pattern`


def scan(root: Path, symbol: str, include_tests: bool) -> Scan:
    """Every hit of `symbol`, by kind — what `refs <symbol>` prints and what
    `refs --rename` rewrites or refuses on."""
    exclude = exclude_prefixes()
    gd_walk = iter_files(root, exclude, GD_GLOB, include_tests)
    scene_walk = walk.Walk(())
    for glob in SCENE_GLOBS:
        scene_walk = scene_walk.merge(iter_files(root, exclude, glob, include_tests))
    gd_files = list(gd_walk)
    scene_files = sorted(scene_walk)

    autoload_hits = scan_autoloads(root, symbol)
    hits_by_kind = scan_gd_files(root, symbol, gd_files, autoload=bool(autoload_hits))
    hits_by_kind[DEFINITION_KIND][:0] = autoload_hits
    hits_by_kind.update(scan_scene_refs(root, symbol, scene_files))
    class_name_pattern = _class_name_pattern(symbol)
    global_name = bool(autoload_hits) or any(
        class_name_pattern.search(hit.text) for hit in hits_by_kind[DEFINITION_KIND])
    return Scan(gd_walk.merge(scene_walk), gd_files, scene_files, hits_by_kind, global_name)


def run(symbol: str, include_tests: bool) -> int:
    if not symbol.strip():
        # Every pattern here is built around the symbol, so an empty one turns
        # each into a match-anything: `(?<![\w.])\s*\(` alone claimed 880 call
        # sites in a consumer. A census that large and that wrong is the read
        # side's cardinal sin — there is no scan whose answer this could be.
        raise EmptySymbol('a symbol is required — refs takes a class_name, a '
                          'method, a signal, or a .gd/.tscn/.tres path or uid, '
                          'never an empty or blank one')
    found = scan(repo_root(), symbol, include_tests)
    hits_by_kind = found.hits

    typed_total = 0
    print(f'# refs: {symbol}')
    # The census, before the hits: a scan narrowed to nothing must not read as
    # a symbol with no references. `census()` is the only way to get the number,
    # and it carries what the number left out.
    print(f'# {found.searched.census("file(s) searched")}')
    for title, kind in SECTION_TITLES:
        hits = hits_by_kind[kind]
        if kind != DYNAMIC_KIND:
            typed_total += len(hits)
        if not hits:
            continue
        print(f'\n## {title} ({len(hits)})')
        if kind == DYNAMIC_KIND:
            print('# textual hits on a receiver the index cannot type — not '
                  'proven references; `refs --retarget` does not act on these')
        for hit in hits:
            location = f'{hit.path}:{hit.line}' if hit.line else hit.path
            print(f'  {location}  {hit.text}')

    dynamic_total = len(hits_by_kind[DYNAMIC_KIND])
    if typed_total == 0 and dynamic_total == 0:
        print('\n(no references found)')
    elif typed_total == 0:
        print(f'\n(0 typed references; {dynamic_total} dynamic hit(s) above — '
              f'read each before calling the symbol unused)')
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('symbol', help='a class_name / method / signal, or a .gd/.tscn/.tres filename/uid')
    parser.add_argument('--tests', action='store_true', help='include tests/ in the scan (excluded by default)')
    args = parser.parse_args(argv)
    try:
        return run(args.symbol, args.tests)
    except (ConfigError, EmptySymbol) as err:
        # A devkit.toml mistake, or an argument that names nothing, is exit 2 —
        # never a traceback, never ignored, and never a scan run anyway.
        print(f'godot-devkit: {err}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
