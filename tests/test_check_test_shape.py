"""Tier 2 — `check test-shape`, ported from a consumer's shell scan.

A ratchet has exactly one interesting property and it is easy to get backwards:
a file ON the ledger at its current size must PASS, and the same file one line
bigger must FAIL. A gate that fails everything already over the cap gets turned
off on the day it lands, which is a gate that checks nothing.

The fixture is small and the cap is set per-case, because the number under test
is the RELATION between a file, the cap and its ledger entry — not 300.
"""
from __future__ import annotations

import subprocess
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


# --- the header: a scenario says why it boots and what it covers ------------
# Opt-in (`header = true`); the existing tier enters `header_ledger` and
# ratchets out as it is touched. The interesting relations: an unledgered
# scenario with no header FAILS, a headed one PASSES, a ledgered one that grew
# a header is a finding naming the ledger line to drop, and every hostile
# `covers:` entry is refused rather than read as a prefix of nothing.
HEADED = 'tests/integration/headed_scenario.gd'
SMALL = 'tests/integration/small_scenario.gd'
HEADER_ON = '[test_shape]\ncap = 50\nheader = true\n'
GOOD_HEADER = ('extends "res://tests/integration/support/scenario_base.gd"\n'
               '\n'
               '## Boots because: tests/unit/contract_test.gd cannot drive the '
               'live flow without a boot.\n'
               '## covers: systems/alpha, tests/unit/contract_test.gd\n'
               '\n'
               'func run() -> void:\n\tpass\n')


def _scenario(root, rel: str, body: str) -> None:
    """Write a scenario into the temp repo and stage it — the gate scans
    `git ls-files`, so an unstaged file is invisible to it."""
    target = root / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(body, encoding='utf-8')
    subprocess.run(['git', 'add', rel], cwd=root, check=True)


class TheHeaderIsOptIn(unittest.TestCase):
    def test_stock_config_asks_nothing_of_a_headerless_scenario(self) -> None:
        with temp_repo('test_shape_repo', only=SCENARIOS) as root:
            _config(root, '[test_shape]\ncap = 50\n')
            code, out = run_check(test_shape)
        self.assertEqual(code, 0, out)
        self.assertNotIn('NO-HEADER', out)
        self.assertNotIn('header ledger', out)


class TheHeaderRule(unittest.TestCase):
    def test_an_unledgered_scenario_with_no_header_fails(self) -> None:
        with temp_repo('test_shape_repo', only=SCENARIOS) as root:
            _config(root, HEADER_ON)
            code, out = run_check(test_shape)
        self.assertEqual(code, 1, out)
        self.assertIn(f'NO-HEADER  {SMALL}', out)
        self.assertIn('## Boots because: tests/unit/<path> cannot', out)

    def test_a_headed_scenario_passes(self) -> None:
        with temp_repo('test_shape_repo', only=[*BASE, 'systems/alpha/thing.gd',
                                                 'tests/unit/contract_test.gd']) as root:
            _scenario(root, HEADED, GOOD_HEADER)
            _config(root, HEADER_ON)
            code, out = run_check(test_shape)
        self.assertEqual(code, 0, out)
        self.assertIn('every one off the header ledger says why it boots', out)

    def test_the_ledger_exempts_an_existing_scenario(self) -> None:
        with temp_repo('test_shape_repo', only=SCENARIOS) as root:
            _config(root, HEADER_ON + f'header_ledger = ["{SMALL}", "{BIG}"]\n')
            code, out = run_check(test_shape)
        self.assertEqual(code, 0, out)
        self.assertIn('header ledger: 2 scenario(s) yet to say why they boot', out)

    def test_a_ledgered_scenario_that_grew_a_header_names_the_line_to_drop(self) -> None:
        """The ratchet's other direction: the ledger only shrinks, and a file
        that answered the question must leave it — otherwise the ledger is a
        permission list that never empties."""
        with temp_repo('test_shape_repo', only=[*BASE, 'systems/alpha/thing.gd',
                                                 'tests/unit/contract_test.gd']) as root:
            _scenario(root, HEADED, GOOD_HEADER)
            _config(root, HEADER_ON + f'header_ledger = ["{HEADED}"]\n')
            code, out = run_check(test_shape)
        self.assertEqual(code, 1, out)
        self.assertIn(f'HEADED  {HEADED} — carries its header; drop it from '
                      f'[test_shape] header_ledger', out)

    def test_a_stale_ledger_entry_is_a_finding(self) -> None:
        with temp_repo('test_shape_repo', only=SCENARIOS) as root:
            _config(root, HEADER_ON + f'header_ledger = ["{SMALL}", "{BIG}", '
                    f'"tests/integration/gone.gd"]\n')
            code, out = run_check(test_shape)
        self.assertEqual(code, 1, out)
        self.assertIn('STALE  tests/integration/gone.gd', out)

    def test_a_covers_line_below_the_first_statement_is_prose(self) -> None:
        """The header is the leading comment block. A declaration inside the
        body is what the runner would never read, so the gate must not either
        — or the two disagree on what a scenario covers."""
        body = ('extends Node\n## Boots because: tests/unit/contract_test.gd '
                'cannot.\nfunc run() -> void:\n\t## covers: systems/alpha\n\tpass\n')
        with temp_repo('test_shape_repo', only=[*BASE, 'systems/alpha/thing.gd',
                                                 'tests/unit/contract_test.gd']) as root:
            _scenario(root, HEADED, body)
            _config(root, HEADER_ON)
            code, out = run_check(test_shape)
        self.assertEqual(code, 1, out)
        self.assertIn(f'HEADER  {HEADED} — no `## covers:` line', out)


class TheHeaderRefusalMatrix(unittest.TestCase):
    """Every claim the docstring makes about a covers entry — repo-relative,
    no `..`, no scheme, no glob, no whitespace, EXISTS — gets the input that
    attacks it. Each must be a finding, never a silent prefix of nothing."""

    HOSTILE_COVERS = {
        '/abs/systems/alpha': 'is absolute',
        '../escape': 'carries a dot segment',
        'systems/../alpha': 'carries a dot segment',
        './systems/alpha': 'carries a dot segment',
        'res://systems/alpha': 'carries a scheme',
        'systems/*': 'carries a glob',
        'systems/alph?': 'carries a glob',
        'systems/[a]lpha': 'carries a glob',
        'systems\\alpha': 'carries a backslash',
        'systems/al pha': 'carries whitespace',
        'systems/nowhere': 'is not in the tree',
        'a' * 201: 'is longer than 200 characters',
    }

    def _run(self, covers_value: str) -> tuple[int, str]:
        body = ('extends Node\n'
                '## Boots because: tests/unit/contract_test.gd cannot.\n'
                f'## covers: {covers_value}\n'
                'func run() -> void:\n\tpass\n')
        with temp_repo('test_shape_repo', only=[*BASE, 'systems/alpha/thing.gd',
                                                 'tests/unit/contract_test.gd']) as root:
            _scenario(root, HEADED, body)
            _config(root, HEADER_ON)
            return run_check(test_shape)

    def test_every_hostile_covers_entry_is_refused(self) -> None:
        for entry, reason in self.HOSTILE_COVERS.items():
            with self.subTest(entry=entry):
                code, out = self._run(f'systems/alpha, {entry}')
                self.assertEqual(code, 1, out)
                self.assertIn(reason, out)

    def test_an_empty_entry_between_commas_is_refused(self) -> None:
        code, out = self._run('systems/alpha, , tests/unit/contract_test.gd')
        self.assertEqual(code, 1, out)
        self.assertIn('covers `` is empty', out)

    def test_a_covers_line_declaring_nothing_is_refused(self) -> None:
        code, out = self._run('')
        self.assertEqual(code, 1, out)
        self.assertIn('is empty', out)

    def test_a_boots_because_that_names_no_test_is_refused(self) -> None:
        body = ('extends Node\n## Boots because: it just does.\n'
                '## covers: systems/alpha\nfunc run() -> void:\n\tpass\n')
        with temp_repo('test_shape_repo', only=[*BASE, 'systems/alpha/thing.gd']) as root:
            _scenario(root, HEADED, body)
            _config(root, HEADER_ON)
            code, out = run_check(test_shape)
        self.assertEqual(code, 1, out)
        self.assertIn('names no tests/ path', out)

    def test_an_empty_boots_because_is_refused(self) -> None:
        body = ('extends Node\n## Boots because:\n'
                '## covers: systems/alpha\nfunc run() -> void:\n\tpass\n')
        with temp_repo('test_shape_repo', only=[*BASE, 'systems/alpha/thing.gd']) as root:
            _scenario(root, HEADED, body)
            _config(root, HEADER_ON)
            code, out = run_check(test_shape)
        self.assertEqual(code, 1, out)
        self.assertIn('says nothing', out)


class TheHeaderConfigIsRefusedRatherThanGuessed(unittest.TestCase):
    def test_a_string_header_flag_is_refused(self) -> None:
        with temp_repo('test_shape_repo', only=SCENARIOS) as root:
            _config(root, '[test_shape]\nheader = "yes"\n')
            with self.assertRaises(ConfigError):
                run_check(test_shape)

    def test_a_bare_string_header_ledger_is_refused_not_iterated(self) -> None:
        with temp_repo('test_shape_repo', only=SCENARIOS) as root:
            _config(root, HEADER_ON + f'header_ledger = "{SMALL}"\n')
            with self.assertRaises(ConfigError):
                run_check(test_shape)


if __name__ == '__main__':
    unittest.main()
