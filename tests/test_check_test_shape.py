"""Focused contract tests for the pure tracked integration-size gate."""
from __future__ import annotations

import subprocess
import unittest

from support import run_check, temp_repo

from godot_devkit.core.config import ConfigError
from godot_devkit.godot.checks import test_shape

BIG = 'tests/integration/big.gd'
SMALL = 'tests/integration/small.gd'
UNIT = 'tests/unit/unit.gd'
SUPPORT = 'tests/integration/support/helper.gd'
FIVE_LINES = 'extends Node\nfunc a():\n\tpass\nfunc b():\n\tpass\n'
TWO_LINES = 'extends Node\npass\n'


def _gate(config: str, scripts: dict[str, str] | None = None,
          remove: str | None = None) -> tuple[int, str]:
    with temp_repo('test_shape_repo', only=['project.godot']) as root:
        for rel, body in (scripts or {BIG: FIVE_LINES, SMALL: TWO_LINES,
                                      UNIT: TWO_LINES}).items():
            target = root / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(body, encoding='utf-8')
            subprocess.run(['git', 'add', rel], cwd=root, check=True)
        (root / 'godot-devkit.toml').write_text(config, encoding='utf-8')
        if remove:
            (root / remove).unlink()
        return run_check(test_shape)


class TestShape(unittest.TestCase):
    def test_cap_prices_every_tracked_integration_script(self) -> None:
        config = '[test_shape]\ncap = 3\n'
        code, out = _gate(config, {BIG: FIVE_LINES, SMALL: TWO_LINES,
                                   SUPPORT: FIVE_LINES, UNIT: TWO_LINES})
        self.assertEqual(code, 1, out)
        self.assertIn(f'OVERCAP  {BIG} — 5 lines', out)
        self.assertIn(f'OVERCAP  {SUPPORT} — 5 lines', out)
        self.assertIn('census: 3 of 3 tracked *.gd', out)
        self.assertIn('tier balance: unit 2 / tests/integration 12', out)
        self.assertIn('FAIL — 2 finding(s) across 3 tracked', out)

    def test_ledger_accepts_current_ceiling_and_refuses_growth(self) -> None:
        config = f'[test_shape]\ncap = 3\nledger = {{ "{BIG}" = 5 }}\n'
        code, out = _gate(config)
        self.assertEqual(code, 0, out)
        self.assertIn('PASS — 2 tracked integration script(s)', out)
        code, out = _gate(config, {BIG: FIVE_LINES + 'pass\n', SMALL: TWO_LINES})
        self.assertEqual(code, 1, out)
        self.assertIn(f'GREW  {BIG} — 6 lines, ledger ceiling 5', out)

    def test_ledger_must_shrink_or_drop_paid_debt(self) -> None:
        code, out = _gate(f'[test_shape]\ncap = 3\nledger = {{ "{BIG}" = 7 }}\n')
        self.assertEqual(code, 1, out)
        self.assertIn(f'SHRUNK  {BIG} — 5 lines, ledger ceiling 7', out)
        code, out = _gate(f'[test_shape]\ncap = 5\nledger = {{ "{BIG}" = 5 }}\n')
        self.assertEqual(code, 1, out)
        self.assertIn(f'PAID  {BIG}', out)

    def test_stale_ledger_and_missing_tracked_file_fail(self) -> None:
        stale = 'tests/integration/gone.gd'
        code, out = _gate(f'[test_shape]\nledger = {{ "{stale}" = 10 }}\n')
        self.assertEqual(code, 1, out)
        self.assertIn(f'STALE  {stale}', out)
        code, out = _gate('[test_shape]\n', remove=BIG)
        self.assertEqual(code, 1, out)
        self.assertIn(f'UNREADABLE  {BIG}', out)
        self.assertIn('census: 1 of 2 tracked', out)

    def test_zero_census_is_a_finding(self) -> None:
        code, out = _gate('[test_shape]\n', {UNIT: TWO_LINES})
        self.assertEqual(code, 1, out)
        self.assertIn('scanned 0 tracked *.gd under tests/integration/', out)

    def test_old_keys_refuse_with_migration_and_bad_values_exit_two(self) -> None:
        obsolete = {
            'scenario_root = "tests/integration"': 'integration_root',
            'runner = "tools/dev/runners/integration.sh"': 'remove it',
            'header = true': 'remove it',
            'header_ledger = ["tests/integration/big.gd"]': 'remove it',
            'infra = ["helper.gd"]': 'remove it',
        }
        for old, migration in obsolete.items():
            with self.subTest(old=old), self.assertRaises(ConfigError) as caught:
                _gate(f'[test_shape]\n{old}\n')
            self.assertIn(migration, str(caught.exception))
        for bad in ('cap = "3"', 'cap = 0',
                    'integration_root = "../elsewhere"',
                    f'ledger = {{ "{BIG}" = true }}'):
            with self.subTest(bad=bad), self.assertRaises(ConfigError):
                _gate(f'[test_shape]\n{bad}\n')
