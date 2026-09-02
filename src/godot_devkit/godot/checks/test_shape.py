"""test_shape.py — check test-shape: the expensive test tier stays the SMALL one.

A two-tier suite says unit is the bulk and integration is the few. Nothing
holds it there: measured on one consumer, integration had grown to 60% of the
suite with six scenarios over 800 lines each — the rule was written, agreed,
and simply not binding. A big scenario is expensive in a way a big unit file is
not, because it boots a process: a 1000-line scenario is a unit suite wearing a
scenario's clothes, paying full boot cost to assert what needs no boot.

A RATCHET, not a big bang. Failing every over-cap file the day the gate lands
just means the gate gets switched off. Every file already over the cap is
recorded in `[test_shape] ledger` at its CURRENT size, and the gate fails only
when a file GROWS past its recorded ceiling or a NEW file crosses the cap. The
ledger is a DEBT LEDGER: its length is the metric, and it should only shrink.

  CHECK 1  no scenario off the ledger exceeds `[test_shape] cap` lines.
  CHECK 2  no scenario on the ledger exceeds its recorded ceiling.

HONEST SCOPE: this counts lines. It cannot tell a 900-line scenario that
genuinely needs a boot from one that should have been ten unit tests — that
judgement stays with the reviewer. What it does is stop the tier drifting
further out of shape while nobody is looking. The tier-balance line it prints
is the number it exists to move, and is informational: a share is not a
finding, because there is no honest threshold to fail it at.

Read-only, like every gate but `check uid --fix`: a file over the cap prints
the ledger line to paste, rather than the gate editing the config that governs
it.

devkit.toml:

    [test_shape]
    scenario_root = "tests/integration"
    unit_root = "tests/unit"
    cap = 300
    infra = ["scenario_base.gd", "scenario_runner.gd"]
    ledger = { "tests/integration/approach/approach_contracts.gd" = 956 }
"""
from __future__ import annotations

from godot_devkit.core.config import (config_section, number, number_table,
                                      str_tuple, text)
from godot_devkit.core.project import git_lines, repo_root

SECTION = 'test_shape'
TAG = '[check:test-shape]'
SUFFIX = '.gd'
DEFAULT_SCENARIO_ROOT = 'tests/integration'
DEFAULT_UNIT_ROOT = 'tests/unit'
DEFAULT_CAP = 300
# Nothing by default. The tier's shared harness — a scenario base class, a
# lifecycle runner — boots once per scenario whatever its size and is where
# duplication is supposed to MOVE TO; measuring it as a scenario prices a
# shared helper above the hundred copies of it that it replaced. Which files
# those are is the project's fact, so the project names them.
DEFAULT_INFRA: tuple[str, ...] = ()
PERCENT = 100


def line_count(text_body: str) -> int:
    """Lines, counted as `wc -l` counts them — newlines, not fragments.

    The ledger's numbers were measured with `wc -l`; a different definition
    here would redden every entry on adoption day.
    """
    return text_body.count('\n')


def _measure(root, rels: list[str]) -> dict[str, int]:
    sizes: dict[str, int] = {}
    for rel in rels:
        try:
            sizes[rel] = line_count((root / rel).read_text(encoding='utf-8',
                                                           errors='replace'))
        except OSError:
            continue
    return sizes


def run() -> int:
    sect = config_section(SECTION)
    scenario_root = text(sect, SECTION, 'scenario_root', DEFAULT_SCENARIO_ROOT)
    unit_root = text(sect, SECTION, 'unit_root', DEFAULT_UNIT_ROOT)
    cap = number(sect, SECTION, 'cap', DEFAULT_CAP)
    infra = str_tuple(sect, SECTION, 'infra', DEFAULT_INFRA)
    ledger = number_table(sect, SECTION, 'ledger', {})
    root = repo_root()

    tracked = [rel for rel in git_lines('ls-files', '--', scenario_root)
               if rel.endswith(SUFFIX)]
    scanned = [rel for rel in tracked if rel.rsplit('/', 1)[-1] not in infra]
    if not scanned:
        # Rule 4 — a gate that scanned nothing must say so, and name which of
        # the two reasons applies.
        print(f'{TAG} FAIL — scanned 0 of {len(tracked)} tracked *{SUFFIX} '
              f'under {scenario_root}/; check [{SECTION}] scenario_root/infra')
        return 1

    sizes = _measure(root, scanned)
    findings: list[str] = []
    for rel in sorted(sizes):
        lines = sizes[rel]
        ceiling = ledger.get(rel)
        if ceiling is not None:
            if lines > ceiling:
                findings.append(f'  GREW  {rel} — {lines} lines, ledger '
                                f'ceiling {ceiling}')
        elif lines > cap:
            findings.append(f'  OVERCAP  {rel} — {lines} lines (cap {cap}, not '
                            f'on the [{SECTION}] ledger)')

    unit_lines = sum(_measure(root, [rel for rel
                                     in git_lines('ls-files', '--', unit_root)
                                     if rel.endswith(SUFFIX)]).values())
    # The BALANCE counts the whole tier, infra included — the shared harness
    # boots with every scenario, so it is part of what the tier costs. Only the
    # CAP excludes it, and for the opposite reason: a helper that replaced a
    # hundred copies of itself must not be priced as a scenario.
    scenario_lines = sum(_measure(root, tracked).values())
    total = unit_lines + scenario_lines
    if total:
        share = PERCENT * scenario_lines // total
        print(f'  tier balance: unit {unit_lines} / {scenario_root} '
              f'{scenario_lines} — the booting tier is {share}% of the suite')
    print(f'  debt ledger: {len(ledger)} scenario(s) over cap — this number '
          f'should only shrink')

    if findings:
        for finding in findings:
            print(finding)
        print(f'\n{TAG} FAIL — {len(findings)} finding(s) across '
              f'{len(scanned)} scenario(s)')
        print(f'  A scenario over {cap} lines is usually a unit suite wearing a '
              f"scenario's clothes:")
        print('  assert the contract in the no-boot tier and keep the scenario '
              'to the use case.')
        print(f'  If the size is genuinely earned, record it in [{SECTION}] '
              f'ledger and say why in the commit:')
        for rel in sorted(sizes):
            if any(rel in finding for finding in findings):
                print(f'      "{rel}" = {sizes[rel]}')
        return 1

    print(f'{TAG} PASS — {len(scanned)} scenario(s) under {scenario_root}/, '
          f'none over the {cap}-line cap or its ledger ceiling')
    return 0
