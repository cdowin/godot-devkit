"""Check the size of tracked GUT integration scripts without booting Godot.

This opt-in readability gate counts every tracked .gd file under
`[test_shape] integration_root`. New files over `cap` fail. Existing debt
may enter `ledger` at its current wc -l size, but must not grow. A smaller
file must lower its ceiling; one at or below the cap leaves the ledger.
The unit/integration line balance is informational, without a ratio limit.

The integration runner and GUT own runtime discovery and execution. This
gate reads tracked source only.
"""
from __future__ import annotations

from pathlib import Path

from godot_devkit.core.config import (ConfigError, config_section, number,
                                      number_table, repo_path_defect, text)
from godot_devkit.core.project import git_lines, repo_root

SECTION = 'test_shape'
TAG = '[check:test-shape]'
SUFFIX = '.gd'
DEFAULT_INTEGRATION_ROOT = 'tests/integration'
DEFAULT_UNIT_ROOT = 'tests/unit'
DEFAULT_CAP = 300
OLD_KEYS = {
    'scenario_root': 'rename it to integration_root',
    'runner': 'remove it; GUT runs integration tests',
    'header': 'remove it; GUT tests need no custom header',
    'header_ledger': 'remove it; the header rule was retired',
    'infra': 'remove it; all tracked integration scripts count',
}


def _root_path(sect: dict, key: str, fallback: str) -> str:
    rel = text(sect, SECTION, key, fallback)
    why = repo_path_defect(rel)
    if why:
        raise ConfigError(f'[{SECTION}] {key} {why}: {rel!r}')
    return rel


def _tracked_scripts(root: str) -> list[str]:
    # The slash excludes a sibling whose name merely shares the prefix.
    return sorted(rel for rel in git_lines('ls-files', '--', f'{root}/')
                  if rel.endswith(SUFFIX))


def _measure(repo: Path, rels: list[str]) -> tuple[dict[str, int], list[str]]:
    sizes: dict[str, int] = {}
    unreadable: list[str] = []
    for rel in rels:
        try:
            sizes[rel] = (repo / rel).read_text(
                encoding='utf-8', errors='replace').count('\n')
        except OSError:
            unreadable.append(rel)
    return sizes, unreadable


def run() -> int:
    sect = config_section(SECTION)
    for key, migration in OLD_KEYS.items():
        if key in sect:
            raise ConfigError(f'[{SECTION}] {key} was removed in 4.0; {migration}')

    integration_root = _root_path(sect, 'integration_root',
                                  DEFAULT_INTEGRATION_ROOT)
    unit_root = _root_path(sect, 'unit_root', DEFAULT_UNIT_ROOT)
    cap = number(sect, SECTION, 'cap', DEFAULT_CAP)
    if cap < 1:
        raise ConfigError(f'[{SECTION}] cap must be positive, got {cap}')
    ledger = number_table(sect, SECTION, 'ledger', {})
    for rel, ceiling in ledger.items():
        why = repo_path_defect(rel)
        if why or not rel.startswith(f'{integration_root}/') or not rel.endswith(SUFFIX):
            raise ConfigError(f'[{SECTION}] ledger entry {rel!r} must be a .gd '
                              f'file under {integration_root}/'
                              + (f' ({why})' if why else ''))
        if ceiling < 1:
            raise ConfigError(f'[{SECTION}] ledger.{rel!r} must be positive')

    root = repo_root()
    tracked = _tracked_scripts(integration_root)
    if not tracked:
        print(f'{TAG} FAIL — scanned 0 tracked *{SUFFIX} under '
              f'{integration_root}/; check [{SECTION}] integration_root')
        return 1

    sizes, unreadable = _measure(root, tracked)
    findings = [f'  UNREADABLE  {rel} — tracked but not readable on disk'
                for rel in unreadable]
    for rel in tracked:
        if rel not in sizes:
            continue
        lines = sizes[rel]
        ceiling = ledger.get(rel)
        if ceiling is None:
            if lines > cap:
                findings.append(f'  OVERCAP  {rel} — {lines} lines (cap {cap}, '
                                f'not on the [{SECTION}] ledger)')
        elif lines > ceiling:
            findings.append(f'  GREW  {rel} — {lines} lines, ledger ceiling '
                            f'{ceiling}')
        elif lines <= cap:
            findings.append(f'  PAID  {rel} — {lines} lines at or below cap '
                            f'{cap}; remove it from [{SECTION}] ledger')
        elif lines < ceiling:
            findings.append(f'  SHRUNK  {rel} — {lines} lines, ledger ceiling '
                            f'{ceiling}; lower the ceiling to {lines}')
    for rel in sorted(ledger.keys() - sizes.keys()):
        if rel not in unreadable:
            findings.append(f'  STALE  {rel} — on [{SECTION}] ledger but not a '
                            'tracked integration script; remove it')

    unit_sizes, _ = _measure(root, _tracked_scripts(unit_root))
    unit_lines = sum(unit_sizes.values())
    integration_lines = sum(sizes.values())
    total = unit_lines + integration_lines
    if total:
        share = 100 * integration_lines // total
        print(f'  tier balance: unit {unit_lines} / {integration_root} '
              f'{integration_lines} — integration is {share}% of the suite')
    print(f'  census: {len(sizes)} of {len(tracked)} tracked *{SUFFIX} '
          f'under {integration_root}/ read')
    print(f'  debt ledger: {len(ledger)} integration script(s) — this number '
          'should only shrink')

    if findings:
        for finding in findings:
            print(finding)
        print(f'\n{TAG} FAIL — {len(findings)} finding(s) across '
              f'{len(tracked)} tracked integration script(s)')
        for rel in tracked:
            if rel in sizes and sizes[rel] > cap and (
                    rel not in ledger or sizes[rel] != ledger[rel]):
                print(f'      "{rel}" = {sizes[rel]}')
        return 1

    print(f'{TAG} PASS — {len(tracked)} tracked integration script(s) under '
          f'{integration_root}/, none over the {cap}-line cap or its ledger '
          'ceiling')
    return 0
