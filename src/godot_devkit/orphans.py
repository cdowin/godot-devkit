#!/usr/bin/env python3
"""orphans.py — possible-orphan detector for .gd/.tscn/.tres.

Dead-file cleanup, done statically — a `.gd`/`.tscn`/`.tres` with zero
inbound references is a candidate for deletion. "Inbound
reference" covers preload/load + scene ext_resource AND a `class_name`'s
global addressability (extends/typed-ref/`.new()`/`sub_resource type=`,
none of which need a preload). Entry points (autoloads, every `res://` path
project.godot itself references, tests/, auto-discovered data/**.tres,
one-shot `tools/` CLI scripts) are excluded so they don't drown the signal.
A file whose stem (or auto-discovery parent dir) appears as a bare string
elsewhere is downgraded to a low-confidence caveat instead of a hard orphan
claim — a dynamic string-path load can't be proven statically. Only
git-known files are scanned (tracked + untracked-but-not-ignored) —
runtime artifacts (`.godot/`, headless sandbox dirs, `__pycache__/`) never
enter the corpus. Pure parse — never writes, never boots Godot.

    make orphans
    python3 tools/dev/introspect/orphans.py [--tests]
"""
from __future__ import annotations

import argparse
import re
import subprocess
from pathlib import Path

from godot_devkit.tscn import parse, parse_text, _basename
from godot_devkit.project import repo_root, load_config

# --- Scope -------------------------------------------------------------------
REPO_ROOT = repo_root()
VENDORED_EXCLUDED = ('addons/',)  # excluded from the whole scan (corpus + candidates) — not ours
CANDIDATE_GLOBS = ('*.gd', '*.tscn', '*.tres')
# tools/ scripts are one-shot `godot --script <path>` CLI entry points, run
# directly rather than loaded through the game's preload graph — never a
# candidate, but still SCANNED as part of the reference corpus (a preload()
# inside a tools/ script still counts as a real reference to its target).
PERMANENT_CANDIDATE_EXCLUDED_DIRS = ('tools/',)
CANDIDATE_EXCLUDED_DIRS = ('tests/', 'data/')  # auto-discovered / entry-point dirs — toggle with --tests
# Godot's own root-level implicit-load convention — auto-applied by fixed
# filename with no project.godot setting to point at it, so it can never
# show up as a static ref.
GODOT_CONVENTION_FILES = ('default_bus_layout.tres',)
PROJECT_GODOT = 'project.godot'
RES_PATH = re.compile(r'res://[^"\s]+')

PRELOAD_LOAD = re.compile(r'(?:preload|load)\(\s*"([^"]+)"\s*\)')
QUOTED_STRING = re.compile(r'"([^"]+)"')
CLASS_NAME_DECL = re.compile(r'^class_name\s+(\w+)', re.MULTILINE)


def tracked_files() -> list[str]:
    """Every git-known path, repo-relative: tracked + untracked-but-not-
    ignored (so a brand-new file from the current slice is still visible,
    before its first commit) — the runtime/build-artifact exclusion for
    free either way (.godot/, headless sandbox dirs, __pycache__, … are
    all gitignored)."""
    result = subprocess.run(
        ['git', 'ls-files', '--cached', '--others', '--exclude-standard'],
        cwd=REPO_ROOT, capture_output=True, text=True, check=True)
    return result.stdout.splitlines()


def _is_vendored(rel: str) -> bool:
    return any(rel.startswith(prefix) for prefix in VENDORED_EXCLUDED)


def is_candidate(rel: str) -> bool:
    excluded_dirs = PERMANENT_CANDIDATE_EXCLUDED_DIRS + CANDIDATE_EXCLUDED_DIRS
    return not any(rel.startswith(prefix) for prefix in excluded_dirs)


def iter_repo_files(all_tracked: list[str], glob_suffix: str) -> list[str]:
    return sorted(rel for rel in all_tracked if rel.endswith(glob_suffix) and not _is_vendored(rel))


def entry_points() -> set[str]:
    """Every res:// path project.godot itself references — autoload scripts,
    the main scene, default_bus_layout, boot splash, … — never candidates.
    (A `res://` substring match is enough to cover autoloads' `"*res://…"`
    leading-asterisk form too, so one generic pass covers every section.)"""
    text = (REPO_ROOT / PROJECT_GODOT).read_text(encoding='utf-8', errors='replace')
    sections = parse_text(text)
    entries: set[str] = set()
    for section in sections:
        for _key, value in section.props:
            for match in RES_PATH.finditer(value):
                entries.add(match.group(0).removeprefix('res://'))
    return entries


def build_static_refs(all_tracked: list[str]) -> set[str]:
    """Basenames the repo statically references: preload/load literal paths
    (.gd) + ext_resource path (.tscn/.tres)."""
    refs: set[str] = set()
    for rel in iter_repo_files(all_tracked, '.gd'):
        text = (REPO_ROOT / rel).read_text(encoding='utf-8', errors='replace')
        for match in PRELOAD_LOAD.finditer(text):
            refs.add(_basename(match.group(1)))
    for suffix in ('.tscn', '.tres'):
        for rel in iter_repo_files(all_tracked, suffix):
            try:
                sections = parse(str(REPO_ROOT / rel))
            except OSError:
                continue
            for section in sections:
                if section.kind == 'ext_resource':
                    target = section.attrs.get('path')
                    if target:
                        refs.add(_basename(target))
    return refs


def class_name_by_file(all_tracked: list[str]) -> dict[str, str]:
    """rel path -> its own `class_name` (only files that declare one)."""
    owners: dict[str, str] = {}
    for rel in iter_repo_files(all_tracked, '.gd'):
        text = (REPO_ROOT / rel).read_text(encoding='utf-8', errors='replace')
        match = CLASS_NAME_DECL.search(text)
        if match:
            owners[rel] = match.group(1)
    return owners


def build_class_name_refs(all_tracked: list[str], class_names: set[str]) -> dict[str, set[str]]:
    """class_name -> the set of files that mention it as a whole word (comment-
    stripped) — a Godot `class_name` is globally addressable, so a subclass
    (`extends Foo`), typed ref (`: Foo`), instantiation (`Foo.new()`), or a
    `.tscn`/`.tres` inline `sub_resource type="Foo"` needs no preload/load at
    all. Deliberately loose (any whole-word mention, not kind-specific like
    refs.py) — orphans.py only needs the boolean 'is this used anywhere'."""
    if not class_names:
        return {}
    word_pattern = re.compile(r'\b(' + '|'.join(re.escape(n) for n in class_names) + r')\b')
    mentions: dict[str, set[str]] = {name: set() for name in class_names}

    for rel in iter_repo_files(all_tracked, '.gd'):
        text = (REPO_ROOT / rel).read_text(encoding='utf-8', errors='replace')
        for lineno_text in text.split('\n'):
            stripped = lineno_text.split('#', 1)[0]
            for match in word_pattern.finditer(stripped):
                mentions[match.group(1)].add(rel)

    for suffix in ('.tscn', '.tres'):
        for rel in iter_repo_files(all_tracked, suffix):
            try:
                sections = parse(str(REPO_ROOT / rel))
            except OSError:
                continue
            for section in sections:
                if section.kind == 'sub_resource':
                    kind = section.attrs.get('type')
                    if kind in mentions:
                        mentions[kind].add(rel)
    return mentions


def build_stem_mentions(all_tracked: list[str], stems: set[str]) -> set[str]:
    """Stems that appear as a bare quoted string ANYWHERE in the repo — a
    low-confidence signal the file may be loaded by a dynamic string-path
    (e.g. `load(dir + "%s_effect.gd" % name)`)."""
    mentioned: set[str] = set()
    remaining = set(stems)
    for suffix in ('.gd', '.tscn', '.tres'):
        if not remaining:
            break
        for rel in iter_repo_files(all_tracked, suffix):
            text = (REPO_ROOT / rel).read_text(encoding='utf-8', errors='replace')
            for match in QUOTED_STRING.finditer(text):
                literal = match.group(1)
                found = {stem for stem in remaining if stem in literal}
                if found:
                    mentioned |= found
                    remaining -= found
    return mentioned


def build_dir_mentions(all_tracked: list[str], dirs: set[str]) -> set[str]:
    """Parent dirs referenced as an EXACT `res://<dir>[/]` string literal
    (not a loose substring — else common top-level dirs like `resources/`
    would swallow the whole low-confidence bucket) — the directory-scan
    auto-discovery pattern (`DirAccess.open(dir)` + `load(dir + file_name)`,
    the same doctrine as the data/**.tres auto-discovery convention)."""
    exact_forms = {f'res://{d}': d for d in dirs} | {f'res://{d}/': d for d in dirs}
    mentioned: set[str] = set()
    for suffix in ('.gd', '.tscn', '.tres'):
        for rel in iter_repo_files(all_tracked, suffix):
            text = (REPO_ROOT / rel).read_text(encoding='utf-8', errors='replace')
            for match in QUOTED_STRING.finditer(text):
                hit_dir = exact_forms.get(match.group(1))
                if hit_dir:
                    mentioned.add(hit_dir)
    return mentioned


def find_orphans(include_tests: bool) -> tuple[list[str], list[str]]:
    all_tracked = tracked_files()
    entries = entry_points()
    static_refs = build_static_refs(all_tracked)
    class_owners = class_name_by_file(all_tracked)

    candidates: list[str] = []
    for suffix in ('.gd', '.tscn', '.tres'):
        for rel in iter_repo_files(all_tracked, suffix):
            if rel in entries or rel == PROJECT_GODOT or rel in GODOT_CONVENTION_FILES:
                continue
            if rel.startswith(PERMANENT_CANDIDATE_EXCLUDED_DIRS):
                continue
            if not include_tests and not is_candidate(rel):
                continue
            candidates.append(rel)

    unreferenced = [rel for rel in candidates if _basename(rel) not in static_refs]

    # A candidate with a class_name is used if its class is mentioned in ANY
    # OTHER file — extends/typed-ref/instantiation (.gd) or an inline
    # sub_resource type= (.tscn/.tres), no preload required.
    candidate_class_names = {class_owners[rel] for rel in unreferenced if rel in class_owners}
    class_refs = build_class_name_refs(all_tracked, candidate_class_names)
    unreferenced = [
        rel for rel in unreferenced
        if not (class_owners.get(rel) and class_refs.get(class_owners[rel], set()) - {rel})
    ]

    stem_by_rel = {rel: Path(rel).stem for rel in unreferenced}
    dir_by_rel = {rel: str(Path(rel).parent) for rel in unreferenced}
    mentioned_stems = build_stem_mentions(all_tracked, set(stem_by_rel.values()))
    mentioned_dirs = build_dir_mentions(all_tracked, set(dir_by_rel.values()))

    orphans: list[str] = []
    caveats: list[str] = []
    for rel in sorted(unreferenced):
        if stem_by_rel[rel] in mentioned_stems or dir_by_rel[rel] in mentioned_dirs:
            caveats.append(rel)
        else:
            orphans.append(rel)
    return orphans, caveats


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--tests', action='store_true',
                        help='also consider tests/ and data/ for orphan candidates (excluded by default)')
    args = parser.parse_args(argv)

    orphans, caveats = find_orphans(args.tests)

    print(f'# possible orphans ({len(orphans)})')
    for rel in orphans:
        print(f'  {rel}')

    if caveats:
        print(f'\n# low-confidence — stem appears in a string literal, may be loaded dynamically ({len(caveats)})')
        for rel in caveats:
            print(f'  {rel}')

    if not orphans and not caveats:
        print('(none found)')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
