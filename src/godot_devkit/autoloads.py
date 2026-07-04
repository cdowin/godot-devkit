#!/usr/bin/env python3
"""autoloads.py — autoload census + suffix/heuristic cross-check.

A live check on an autoload naming contract: the suffix
carries the semantic, so a data-lookup must NOT be a *Manager and a stateful
lifecycle owner must NOT be a *Registry. This parses `project.godot
[autoload]`, then for each autoload compares two independent signals:

  * the NAME suffix — the *declared* class (EDIT SUFFIX_EXPECT below to
    match your project's vocabulary):
      Registry  read-only data lookup (no signals)
      Manager   stateful service that owns state + emits signals
      Tracker   passive observer: subscribes to signals, emits none of its own
      Store     append-only disk-backed window (no signals)
      Service   stateful query owner: scalar/boolean answers, no signals
  * a source HEURISTIC — declares a signal → emits (Manager-like); connects
    to others without declaring its own → relays (Tracker-like); neither →
    inert (Registry/Store/Service-like).

When the two disagree (a *Service that emits, a *Manager with no signal) the
row is flagged for review. Each script's path is also cross-checked against
the expected layout (EDIT EXPECTED_PREFIXES below to match your project). Pure parse — never writes, never boots Godot.

    make autoloads
    python3 tools/dev/introspect/autoloads.py
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path

from godot_devkit.tscn import parse_text, _strip_quotes
from godot_devkit.project import repo_root, load_config

# --- Scope -------------------------------------------------------------------
REPO_ROOT = repo_root()
PROJECT_GODOT = 'project.godot'
EXPECTED_PREFIXES = (
    'autoloads/core/', 'autoloads/sim/', 'autoloads/input/',
    'autoloads/presentation/', 'autoloads/observation/', 'autoloads/persistence/',
)

SIGNAL_DECL = re.compile(r'^signal\s+\w+', re.MULTILINE)
CONNECT_CALL = re.compile(r'\.connect\(')

# --- Heuristic buckets (from the source) -------------------------------------
EMITS = 'emits'    # declares a signal — Manager-like
RELAYS = 'relays'  # connects to others, declares none — Tracker-like
INERT = 'inert'    # neither — Registry/Store/Service-like

# --- Declared classes (the name-suffix vocabulary) --- PROJECT CONFIG SURFACE:
# edit SUFFIX_EXPECT + EXPECTED_PREFIXES to your project's conventions. -------
# Each suffix maps to the set of heuristic buckets consistent with its contract.
SUFFIX_EXPECT: dict[str, set[str]] = {
    'Manager': {EMITS},
    'Tracker': {RELAYS},
    'Registry': {INERT},
    'Store': {INERT},
    'Service': {INERT},
}
NO_SUFFIX = '(no recognized suffix)'

# devkit.toml overrides ([autoloads] suffixes = {Manager = "emits", ...},
# expected_prefixes = ["autoloads/", ...]) replace the defaults above.
_CFG = load_config().get('autoloads', {})
if _CFG.get('suffixes'):
    SUFFIX_EXPECT = {k: {v} if isinstance(v, str) else set(v)
                     for k, v in _CFG['suffixes'].items()}
if _CFG.get('expected_prefixes'):
    EXPECTED_PREFIXES = tuple(_CFG['expected_prefixes'])


def list_autoloads() -> list[tuple[str, str]]:
    """[(Name, res://path), …] in project.godot declaration order."""
    text = (REPO_ROOT / PROJECT_GODOT).read_text(encoding='utf-8', errors='replace')
    sections = parse_text(text)
    entries: list[tuple[str, str]] = []
    for section in sections:
        if section.kind != 'autoload':
            continue
        for name, value in section.props:
            res_path = _strip_quotes(value).lstrip('*')
            entries.append((name, res_path.removeprefix('res://')))
    return entries


def heuristic(text: str) -> str:
    if SIGNAL_DECL.search(text):
        return EMITS
    return RELAYS if CONNECT_CALL.search(text) else INERT


def name_suffix(name: str) -> str:
    for suffix in SUFFIX_EXPECT:
        if name.endswith(suffix):
            return suffix
    return NO_SUFFIX


def suffix_note(suffix: str, bucket: str) -> str | None:
    """Flag when the declared suffix and the source heuristic disagree."""
    if suffix == NO_SUFFIX:
        return None
    expected = SUFFIX_EXPECT[suffix]
    if bucket in expected:
        return None
    want = '/'.join(sorted(expected))
    return f'{suffix} suffix expects {want}, source looks {bucket}'


def layout_note(rel_path: str) -> str | None:
    if any(rel_path.startswith(prefix) for prefix in EXPECTED_PREFIXES):
        return None
    return 'non-standard location (expected under autoloads/<scope>/)'


def census() -> list[dict]:
    rows: list[dict] = []
    for name, rel_path in list_autoloads():
        full_path = REPO_ROOT / rel_path
        try:
            text = full_path.read_text(encoding='utf-8', errors='replace')
        except OSError:
            rows.append({'name': name, 'path': rel_path, 'suffix': name_suffix(name),
                         'bucket': '?', 'suffix_note': None, 'layout': 'FILE NOT FOUND'})
            continue
        bucket = heuristic(text)
        suffix = name_suffix(name)
        rows.append({
            'name': name, 'path': rel_path, 'suffix': suffix, 'bucket': bucket,
            'suffix_note': suffix_note(suffix, bucket), 'layout': layout_note(rel_path),
        })
    return rows


def _flags(row: dict) -> str:
    notes = [n for n in (row['suffix_note'], row['layout']) if n]
    return f'  [{"; ".join(notes)}]' if notes else ''


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.parse_args(argv)

    rows = census()
    groups: dict[str, list[dict]] = {}
    for row in rows:
        groups.setdefault(row['suffix'], []).append(row)

    print(f'# autoload census ({len(rows)})')
    order = list(SUFFIX_EXPECT.keys()) + [NO_SUFFIX]
    for suffix in order:
        group = groups.get(suffix, [])
        if not group:
            continue
        print(f'\n## {suffix} ({len(group)})')
        for row in group:
            print(f'  {row["name"]}  {row["path"]}  <{row["bucket"]}>{_flags(row)}')

    mismatches = [r for r in rows if r['suffix_note'] or r['layout']]
    if mismatches:
        print(f'\n# {len(mismatches)} flagged for review '
              f'(the suffix carries the semantic — a data-lookup must not be a '
              f'*Manager, a stateful lifecycle owner must not be a *Registry)')
        for row in mismatches:
            notes = [n for n in (row['suffix_note'], row['layout']) if n]
            print(f'  {row["name"]}: {"; ".join(notes)}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
