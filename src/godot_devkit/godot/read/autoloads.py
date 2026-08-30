#!/usr/bin/env python3
"""autoloads.py — autoload census + suffix/heuristic cross-check.

A live check on an autoload naming contract: the suffix
carries the semantic, so a data-lookup must NOT be a *Manager and a stateful
lifecycle owner must NOT be a *Registry. This parses `project.godot
[autoload]`, then for each autoload compares two independent signals:

  * the NAME suffix — the *declared* class (override the vocabulary via
    `[autoloads] suffixes` in devkit.toml):
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
the expected layout (`[autoloads] expected_prefixes` in devkit.toml). Pure
parse — never writes, never boots Godot.

    make autoloads
    python3 tools/dev/introspect/autoloads.py

devkit.toml: [autoloads] suffixes = { Manager = "emits", Store = ["inert"] }
                         expected_prefixes = ["autoloads/", ...]
             (each value replaces its default wholesale; a suffix maps to the
              bucket(s) — emits / relays / inert — consistent with its contract)
"""
from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path

from godot_devkit.godot.format.tscn import parse_text, _strip_quotes
from godot_devkit.core.project import repo_root
from godot_devkit.core.config import (
    ConfigError,
    config_section,
    str_tuple,
    str_tuple_table,
)

# --- Scope -------------------------------------------------------------------
CONFIG_SECTION = 'autoloads'
PROJECT_GODOT = 'project.godot'
DEFAULT_EXPECTED_PREFIXES = (
    'autoloads/core/', 'autoloads/sim/', 'autoloads/input/',
    'autoloads/presentation/', 'autoloads/observation/', 'autoloads/persistence/',
)

SIGNAL_DECL = re.compile(r'^signal\s+\w+', re.MULTILINE)
CONNECT_CALL = re.compile(r'\.connect\(')

# --- Heuristic buckets (from the source) -------------------------------------
EMITS = 'emits'    # declares a signal — Manager-like
RELAYS = 'relays'  # connects to others, declares none — Tracker-like
INERT = 'inert'    # neither — Registry/Store/Service-like
BUCKETS = (EMITS, RELAYS, INERT)

# --- Declared classes (the name-suffix vocabulary) ---------------------------
# Each suffix maps to the set of heuristic buckets consistent with its
# contract; `[autoloads] suffixes` in devkit.toml replaces this wholesale.
DEFAULT_SUFFIXES: dict[str, tuple[str, ...]] = {
    'Manager': (EMITS,),
    'Tracker': (RELAYS,),
    'Registry': (INERT,),
    'Store': (INERT,),
    'Service': (INERT,),
}
NO_SUFFIX = '(no recognized suffix)'


@dataclass(frozen=True)
class Settings:
    """The resolved `[autoloads]` config — loaded at CALL time, never at
    import: a bad devkit.toml value must be exit 2, not a traceback while
    `cli.py` is still importing modules."""
    suffix_expect: dict[str, set[str]]
    expected_prefixes: tuple[str, ...]


class Refusal(Exception):
    """This tree cannot be censused — say why and exit 2, never traceback."""


def load_settings() -> Settings:
    sect = config_section(CONFIG_SECTION)
    prefixes = str_tuple(sect, CONFIG_SECTION, 'expected_prefixes',
                         DEFAULT_EXPECTED_PREFIXES)
    suffixes = str_tuple_table(sect, CONFIG_SECTION, 'suffixes', DEFAULT_SUFFIXES)
    for suffix, buckets in suffixes.items():
        unknown = [b for b in buckets if b not in BUCKETS]
        if unknown:
            raise ConfigError(
                f'[{CONFIG_SECTION}] suffixes.{suffix} names unknown bucket(s) '
                f'{", ".join(unknown)} — known buckets are {" ".join(BUCKETS)}')
    return Settings({k: set(v) for k, v in suffixes.items()}, prefixes)


def list_autoloads(root: Path) -> list[tuple[str, str]]:
    """[(Name, res://path), …] in project.godot declaration order."""
    try:
        text = (root / PROJECT_GODOT).read_text(encoding='utf-8', errors='replace')
    except OSError as err:
        raise Refusal(
            f'cannot read {PROJECT_GODOT} at {root} — run from inside a '
            f'Godot repo ({err})') from err
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


def name_suffix(name: str, settings: Settings) -> str:
    for suffix in settings.suffix_expect:
        if name.endswith(suffix):
            return suffix
    return NO_SUFFIX


def suffix_note(suffix: str, bucket: str, settings: Settings) -> str | None:
    """Flag when the declared suffix and the source heuristic disagree."""
    if suffix == NO_SUFFIX:
        return None
    expected = settings.suffix_expect[suffix]
    if bucket in expected:
        return None
    want = '/'.join(sorted(expected))
    return f'{suffix} suffix expects {want}, source looks {bucket}'


def layout_note(rel_path: str, settings: Settings) -> str | None:
    if any(rel_path.startswith(prefix) for prefix in settings.expected_prefixes):
        return None
    return 'non-standard location (expected under autoloads/<scope>/)'


def census(root: Path, settings: Settings) -> list[dict]:
    rows: list[dict] = []
    for name, rel_path in list_autoloads(root):
        full_path = root / rel_path
        try:
            text = full_path.read_text(encoding='utf-8', errors='replace')
        except OSError:
            rows.append({'name': name, 'path': rel_path,
                         'suffix': name_suffix(name, settings),
                         'bucket': '?', 'suffix_note': None, 'layout': 'FILE NOT FOUND'})
            continue
        bucket = heuristic(text)
        suffix = name_suffix(name, settings)
        rows.append({
            'name': name, 'path': rel_path, 'suffix': suffix, 'bucket': bucket,
            'suffix_note': suffix_note(suffix, bucket, settings),
            'layout': layout_note(rel_path, settings),
        })
    return rows


def _flags(row: dict) -> str:
    notes = [n for n in (row['suffix_note'], row['layout']) if n]
    return f'  [{"; ".join(notes)}]' if notes else ''


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.parse_args(argv)

    try:
        settings = load_settings()
        rows = census(repo_root(), settings)
    except (ConfigError, Refusal) as err:
        print(f'godot-devkit: {err}', file=sys.stderr)
        return 2
    groups: dict[str, list[dict]] = {}
    for row in rows:
        groups.setdefault(row['suffix'], []).append(row)

    print(f'# autoload census ({len(rows)})')
    order = list(settings.suffix_expect.keys()) + [NO_SUFFIX]
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
