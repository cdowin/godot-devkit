"""Tier 2 — `check test-shape`, ported from a consumer's shell scan.

A ratchet has exactly one interesting property and it is easy to get backwards:
a file ON the ledger at its current size must PASS, and the same file one line
bigger must FAIL. A gate that fails everything already over the cap gets turned
off on the day it lands, which is a gate that checks nothing.

The fixture is small and the cap is set per-case, because the number under test
is the RELATION between a file, the cap and its ledger entry — not 300.
"""
from __future__ import annotations

import unittest

from support import run_check, temp_repo

from godot_devkit.core.config import ConfigError
from godot_devkit.godot.checks import test_shape

BASE = ['project.godot']
SCENARIOS = [*BASE, 'tests/integration/big_scenario.gd',
             'tests/integration/small_scenario.gd']
WITH_INFRA = [*SCENARIOS, 'tests/integration/support/scenario_base.gd']
WHOLE_SUITE = [*WITH_INFRA, 'tests/unit/contract_test.gd']
BIG = 'tests/integration/big_scenario.gd'
BIG_LINES = 10
CAP_5 = '[test_shape]\ncap = 5\n'


def _config(root, body: str) -> None:
    (root / 'devkit.toml').write_text(body, encoding='utf-8')


class TheCap(unittest.TestCase):
    def test_a_new_over_cap_scenario_fails_and_prints_its_ledger_line(self) -> None:
        with temp_repo('test_shape_repo', only=SCENARIOS) as root:
            _config(root, CAP_5)
            code, out = run_check(test_shape)
        self.assertEqual(code, 1, out)
        self.assertIn(f'OVERCAP  {BIG} — {BIG_LINES} lines (cap 5', out)
        self.assertIn(f'"{BIG}" = {BIG_LINES}', out)

    def test_a_scenario_under_the_cap_passes(self) -> None:
        with temp_repo('test_shape_repo', only=SCENARIOS) as root:
            _config(root, '[test_shape]\ncap = 50\n')
            code, out = run_check(test_shape)
        self.assertEqual(code, 0, out)
        self.assertIn('none over the 50-line cap', out)

    def test_the_shared_harness_is_excluded_by_name(self) -> None:
        """Infra boots once per scenario whatever its size, and is where
        duplication is supposed to MOVE TO — pricing it as a scenario prices a
        shared helper above the copies it replaced."""
        with temp_repo('test_shape_repo', only=WITH_INFRA) as root:
            _config(root, CAP_5 + 'infra = ["scenario_base.gd"]\n')
            code, out = run_check(test_shape)
        self.assertEqual(code, 1, out)
        self.assertNotIn('scenario_base.gd', out)
        self.assertEqual(out.count('OVERCAP'), 1, out)


class TheRatchet(unittest.TestCase):
    def test_a_ledgered_file_at_its_recorded_size_passes(self) -> None:
        with temp_repo('test_shape_repo', only=SCENARIOS) as root:
            _config(root, CAP_5 + f'ledger = {{ "{BIG}" = {BIG_LINES} }}\n')
            code, out = run_check(test_shape)
        self.assertEqual(code, 0, out)
        self.assertIn('debt ledger: 1 scenario(s) over cap', out)

    def test_the_same_file_one_line_bigger_fails(self) -> None:
        with temp_repo('test_shape_repo', only=SCENARIOS) as root:
            _config(root, CAP_5 + f'ledger = {{ "{BIG}" = {BIG_LINES - 1} }}\n')
            code, out = run_check(test_shape)
        self.assertEqual(code, 1, out)
        self.assertIn(f'GREW  {BIG} — {BIG_LINES} lines, ledger ceiling '
                      f'{BIG_LINES - 1}', out)


class TheTierBalance(unittest.TestCase):
    def test_the_share_is_reported_and_is_not_itself_a_finding(self) -> None:
        with temp_repo('test_shape_repo', only=WHOLE_SUITE) as root:
            _config(root, '[test_shape]\ncap = 50\ninfra = ["scenario_base.gd"]\n')
            code, out = run_check(test_shape)
        self.assertEqual(code, 0, out)
        # 32, not 12: the balance counts the whole tier INCLUDING the shared
        # harness the cap excludes — infra boots with every scenario, so it is
        # part of what the tier costs.
        self.assertIn('tier balance: unit 30 / tests/integration 32', out)
        self.assertIn('51% of the suite', out)


class RefusesRatherThanGuesses(unittest.TestCase):
    def test_a_root_holding_no_scenarios_fails_loudly(self) -> None:
        with temp_repo('test_shape_repo', only=SCENARIOS) as root:
            _config(root, '[test_shape]\nscenario_root = "tests/nowhere"\n')
            code, out = run_check(test_shape)
        self.assertEqual(code, 1, out)
        self.assertIn('scenario_root/infra', out)

    def test_an_infra_list_that_eats_the_census_fails_loudly(self) -> None:
        with temp_repo('test_shape_repo', only=SCENARIOS) as root:
            _config(root, CAP_5 + 'infra = ["big_scenario.gd", "small_scenario.gd"]\n')
            code, out = run_check(test_shape)
        self.assertEqual(code, 1, out)
        self.assertIn('scanned 0 of 2 tracked', out)

    def test_a_non_integer_cap_is_refused(self) -> None:
        with temp_repo('test_shape_repo', only=SCENARIOS) as root:
            _config(root, '[test_shape]\ncap = "300"\n')
            with self.assertRaises(ConfigError):
                run_check(test_shape)

    def test_a_non_integer_ledger_ceiling_is_refused(self) -> None:
        with temp_repo('test_shape_repo', only=SCENARIOS) as root:
            _config(root, CAP_5 + f'ledger = {{ "{BIG}" = "big" }}\n')
            with self.assertRaises(ConfigError) as caught:
                run_check(test_shape)
        self.assertIn('must be an integer', str(caught.exception))

    def test_a_true_ledger_ceiling_is_refused_rather_than_read_as_one(self) -> None:
        """`true` is an `int` in Python — a bool ceiling would silently mean 1
        and fail every file on the ledger."""
        with temp_repo('test_shape_repo', only=SCENARIOS) as root:
            _config(root, CAP_5 + f'ledger = {{ "{BIG}" = true }}\n')
            with self.assertRaises(ConfigError):
                run_check(test_shape)


if __name__ == '__main__':
    unittest.main()
