#!/usr/bin/env python3
"""refs.py — reference-AWARE symbol search across .gd/.tscn/.tres.

grep can't tell a type-ref from a string/comment match. This finds every
REAL usage of a `class_name`, method, signal, or a `.gd`/`.tscn`/`.tres`
path/uid, grouped by kind: definitions, typed refs, call/emit sites,
preload/load, scene resource refs. Comment-stripped (the capability-scan
doctrine: everything after the first `#` on a line is dropped before
matching — pragmatic, not string-literal-aware). Pure parse — never writes,
never boots Godot.

    make refs NAME=<symbol>
    python3 tools/dev/introspect/refs.py <symbol> [--tests]
"""
from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from pathlib import Path

from godot_devkit.tscn import parse, _basename
from godot_devkit.project import repo_root, load_config

# --- Scope -------------------------------------------------------------------
REPO_ROOT = repo_root()
ALWAYS_EXCLUDED = ('.git/', '.godot/', '.claude/worktrees/', 'pm/roadmap/zz_archive/', 'addons/')
GD_GLOB = '*.gd'
SCENE_GLOBS = ('*.tscn', '*.tres')

# --- Typed-ref grammar (word-boundary, comment-stripped) ---------------------
TYPED_REF_KEYWORDS = ('extends', 'is', 'as')


@dataclass
class Hit:
    kind: str
    path: str
    line: int
    text: str


def _relpath(path: Path) -> str:
    return str(path.relative_to(REPO_ROOT))


def _is_excluded(rel: str) -> bool:
    return any(rel.startswith(prefix) for prefix in ALWAYS_EXCLUDED)


def iter_files(glob: str, include_tests: bool) -> list[Path]:
    files = [p for p in REPO_ROOT.rglob(glob) if not _is_excluded(_relpath(p))]
    if not include_tests:
        files = [p for p in files if not _relpath(p).startswith('tests/')]
    return sorted(files)


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


def _call_emit_pattern(symbol: str) -> re.Pattern:
    word = re.escape(symbol)
    alternatives = [
        rf'\.{word}\(',              # .name(   — method call
        rf'\b{word}\.emit\(',        # name.emit(
        rf'\.connect\(\s*{word}\b',  # .connect(name
    ]
    return re.compile('|'.join(alternatives))


def _definition_pattern(symbol: str) -> re.Pattern:
    word = re.escape(symbol)
    alternatives = [
        rf'\bfunc\s+{word}\s*\(',       # func name(   — method/signal-handler definition
        rf'\bclass_name\s+{word}\b',    # class_name Sym  — the class's own declaration
        rf'\bsignal\s+{word}\b',        # signal name  — the signal's own declaration
    ]
    return re.compile('|'.join(alternatives))


PRELOAD_LOAD = re.compile(r'(?:preload|load)\(\s*"([^"]+)"\s*\)')


def scan_gd_files(symbol: str, files: list[Path]) -> dict[str, list[Hit]]:
    """One pass per `.gd` file, feeding all four line-based scan kinds at
    once (definitions / typed refs / call-emit / preload-load) — the four
    kinds used to each re-read + re-split every file independently, a 4x
    redundant-I/O cost with no benefit (they all want the same comment-
    stripped lines)."""
    definition_pattern = _definition_pattern(symbol)
    typed_ref_pattern = _typed_ref_pattern(symbol)
    call_emit_pattern = _call_emit_pattern(symbol)
    needle = symbol.lower()

    hits: dict[str, list[Hit]] = {'definition': [], 'typed_ref': [], 'call_emit': [], 'preload_load': []}
    for path in files:
        rel = _relpath(path)
        for lineno, raw in enumerate(path.read_text(encoding='utf-8', errors='replace').split('\n'), 1):
            stripped = strip_comment(raw)
            if not stripped:
                continue
            text = stripped.strip()
            if definition_pattern.search(stripped):
                hits['definition'].append(Hit('definition', rel, lineno, text))
            if typed_ref_pattern.search(stripped):
                hits['typed_ref'].append(Hit('typed_ref', rel, lineno, text))
            if call_emit_pattern.search(stripped):
                hits['call_emit'].append(Hit('call_emit', rel, lineno, text))
            for match in PRELOAD_LOAD.finditer(stripped):
                target = match.group(1)
                if needle in _basename(target).lower() or symbol == target:
                    hits['preload_load'].append(Hit('preload_load', rel, lineno, text))
    return hits


def scan_scene_refs(symbol: str, files: list[Path]) -> list[Hit]:
    needle = symbol.lower()
    hits: list[Hit] = []
    for path in files:
        try:
            sections = parse(str(path))
        except OSError:
            continue
        for section in sections:
            if section.kind == 'ext_resource':
                target = section.attrs.get('path') or ''
                uid = section.attrs.get('uid') or ''
                if needle in _basename(target).lower() or symbol == uid:
                    kind = section.attrs.get('type', '?')
                    hits.append(Hit('scene_ref', _relpath(path), 0,
                                    f'ext_resource[{section.attrs.get("id", "?")}] {kind}  {target or uid}'))
            elif section.kind == 'sub_resource' and section.attrs.get('type', '').lower() == needle:
                hits.append(Hit('scene_ref', _relpath(path), 0,
                                f'sub_resource[{section.attrs.get("id", "?")}] {section.attrs.get("type")}'))
    return hits


SECTION_TITLES = (
    ('definitions', 'definition'),
    ('typed refs', 'typed_ref'),
    ('call / emit sites', 'call_emit'),
    ('preload / load', 'preload_load'),
    ('scene resource refs (.tscn/.tres)', 'scene_ref'),
)


def run(symbol: str, include_tests: bool) -> int:
    gd_files = iter_files(GD_GLOB, include_tests)
    scene_files: list[Path] = []
    for glob in SCENE_GLOBS:
        scene_files.extend(iter_files(glob, include_tests))
    scene_files.sort()

    hits_by_kind = scan_gd_files(symbol, gd_files)
    hits_by_kind['scene_ref'] = scan_scene_refs(symbol, scene_files)

    total = 0
    print(f'# refs: {symbol}')
    for title, kind in SECTION_TITLES:
        hits = hits_by_kind[kind]
        total += len(hits)
        if not hits:
            continue
        print(f'\n## {title} ({len(hits)})')
        for hit in hits:
            location = f'{hit.path}:{hit.line}' if hit.line else hit.path
            print(f'  {location}  {hit.text}')

    if total == 0:
        print('\n(no references found)')
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('symbol', help='a class_name / method / signal, or a .gd/.tscn/.tres filename/uid')
    parser.add_argument('--tests', action='store_true', help='include tests/ in the scan (excluded by default)')
    args = parser.parse_args(argv)
    return run(args.symbol, args.tests)


if __name__ == '__main__':
    raise SystemExit(main())
