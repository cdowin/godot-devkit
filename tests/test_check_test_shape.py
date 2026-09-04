"""Tier 2 — `check test-shape`, ported from a consumer's shell scan.

A ratchet has exactly one interesting property and it is easy to get backwards:
a file ON the ledger at its current size must PASS, and the same file one line
bigger must FAIL. A gate that fails everything already over the cap gets turned
off on the day it lands, which is a gate that checks nothing.

The fixture is small and the cap is set per-case, because the number under test
is the RELATION between a file, the cap and its ledger entry — not 300.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import unittest
from unittest import mock

from support import REPO_ROOT, run_check, temp_repo

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


INSTALLABLES = REPO_ROOT / 'src' / 'godot_devkit' / 'repo' / 'installables'
INTEGRATION_RUNNER = INSTALLABLES / 'integration.sh'
MAKEFILE_DEVKIT = INSTALLABLES / 'Makefile.devkit'
RUNNER_REL = 'tools/dev/runners/integration.sh'
CAPTURE = 'tests/integration/thing_capture.gd'
SUPPORT_STUB = 'tests/integration/support/stub.gd'
KEEP_LIST = {'GDK_CAPTURE_GATE_RE': '^(thing_capture)$'}
# The two lines a consumer's Makefile is, per the README.
CONSUMER_MAKEFILE = 'DEVKIT_VERSION := v0.0.0\ninclude Makefile.devkit\n'


def _makefile(root, extra: str = '') -> None:
    """The consumer's Makefile: the pin, the include, and whatever it exports
    to its runners — which is where a keep-list lives, and why the roster is
    asked through `make integration-list` rather than `bash … --list`."""
    shutil.copy2(MAKEFILE_DEVKIT, root / 'Makefile.devkit')
    (root / 'Makefile').write_text(extra + CONSUMER_MAKEFILE, encoding='utf-8')


def _runner(root, rel: str = RUNNER_REL, exports: str = '') -> None:
    """The header rule is asked of the roster the integration runner boots,
    through the Makefile that includes the standard set — so a `header = true`
    repo carries both, the runner at the depth install-runners writes it."""
    target = root / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(INTEGRATION_RUNNER, target)
    _makefile(root, exports)


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
            _runner(root)
            code, out = run_check(test_shape)
        self.assertEqual(code, 1, out)
        self.assertIn(f'NO-HEADER  {SMALL}', out)
        self.assertIn('## Boots because: tests/unit/<path> cannot', out)

    def test_a_headed_scenario_passes(self) -> None:
        with temp_repo('test_shape_repo', only=[*BASE, 'systems/alpha/thing.gd',
                                                 'tests/unit/contract_test.gd']) as root:
            _scenario(root, HEADED, GOOD_HEADER)
            _config(root, HEADER_ON)
            _runner(root)
            code, out = run_check(test_shape)
        self.assertEqual(code, 0, out)
        self.assertIn('every one off the header ledger says why it boots', out)

    def test_the_ledger_exempts_an_existing_scenario(self) -> None:
        with temp_repo('test_shape_repo', only=SCENARIOS) as root:
            _config(root, HEADER_ON + f'header_ledger = ["{SMALL}", "{BIG}"]\n')
            _runner(root)
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
            _runner(root)
            code, out = run_check(test_shape)
        self.assertEqual(code, 1, out)
        self.assertIn(f'HEADED  {HEADED} — carries its header; drop it from '
                      f'[test_shape] header_ledger', out)

    def test_a_stale_ledger_entry_is_a_finding(self) -> None:
        with temp_repo('test_shape_repo', only=SCENARIOS) as root:
            _config(root, HEADER_ON + f'header_ledger = ["{SMALL}", "{BIG}", '
                    f'"tests/integration/gone.gd"]\n')
            _runner(root)
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
            _runner(root)
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
        # A doubled slash. `rstrip('/')` read `systems/alpha//` as a directory
        # that exists, and Path() collapsed `systems//alpha` to one that does —
        # the gate passed both, and the runner (which strips ONE slash and
        # compares strings) never selected on either.
        'systems/alpha//': 'carries an empty segment',
        'systems//alpha': 'carries an empty segment',
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
            _runner(root)
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
            _runner(root)
            code, out = run_check(test_shape)
        self.assertEqual(code, 1, out)
        self.assertIn('names no tests/ path', out)

    def test_an_empty_boots_because_is_refused(self) -> None:
        body = ('extends Node\n## Boots because:\n'
                '## covers: systems/alpha\nfunc run() -> void:\n\tpass\n')
        with temp_repo('test_shape_repo', only=[*BASE, 'systems/alpha/thing.gd']) as root:
            _scenario(root, HEADED, body)
            _config(root, HEADER_ON)
            _runner(root)
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
            _runner(root)
            with self.assertRaises(ConfigError):
                run_check(test_shape)


if __name__ == '__main__':
    unittest.main()


class TheHeaderRuleIsAskedOfTheRunnersRoster(unittest.TestCase):
    """One roster, and the runner owns it. The gate scanned `git ls-files`
    minus the infra basenames; the runner discovers with `find` minus
    support/, the capture tools and its keep-list — so the header rule was
    asked of a capture TOOL and a support stub `--diff` can never slice to.
    The gate now reads the roster from `integration.sh --list`, which is the
    one place the discovery rule (and a consumer's edits to it) lives."""

    ROSTER_REPO = [*BASE, 'systems/alpha/thing.gd', 'tests/unit/contract_test.gd']

    def test_a_capture_tool_and_a_support_stub_are_not_asked(self) -> None:
        with temp_repo('test_shape_repo', only=self.ROSTER_REPO) as root:
            _scenario(root, HEADED, GOOD_HEADER)
            _scenario(root, CAPTURE, 'extends Node\n')
            _scenario(root, SUPPORT_STUB, 'extends Node\n')
            _config(root, HEADER_ON)
            _runner(root)
            code, out = run_check(test_shape)
        self.assertEqual(code, 0, out)
        self.assertIn('1 the runner would boot', out)

    def test_a_keep_list_the_makefile_exports_reaches_the_roster(self) -> None:
        """The runner's own configuration decides — GDK_CAPTURE_GATE_RE makes
        a capture a gate, and then it is asked. That knob is a MAKEFILE
        export, so it reaches `--list` only through make: the gate's own
        process has no such variable here, and the capture must be asked
        regardless. Red at HEAD: `bash <runner> --list` from the gate's
        process saw no keep-list and PASSed over the capture."""
        with temp_repo('test_shape_repo', only=self.ROSTER_REPO) as root:
            _scenario(root, HEADED, GOOD_HEADER)
            _scenario(root, CAPTURE, 'extends Node\n')
            _scenario(root, SUPPORT_STUB, 'extends Node\n')
            _config(root, HEADER_ON)
            _runner(root, exports=('GDK_CAPTURE_GATE_RE := ^(thing_capture)$$\n'
                                   'export GDK_CAPTURE_GATE_RE\n'))
            with mock.patch.dict(os.environ, clear=False):
                os.environ.pop('GDK_CAPTURE_GATE_RE', None)
                code, out = run_check(test_shape)
        self.assertEqual(code, 1, out)
        self.assertIn(f'NO-HEADER  {CAPTURE}', out)
        self.assertIn('2 the runner would boot', out)
        self.assertNotIn(SUPPORT_STUB, out)

    def test_a_keep_list_in_the_gates_own_environment_never_reaches_the_roster(self) -> None:
        """The adversarial half of "the roster is the tree's": the SAME
        variable in the gate's own environment — a shell export, a parent
        make's leftovers — must change nothing, or the census is a function
        of who ran the gate (147 under make, 137 from the shim, measured).
        Red at HEAD: the env reached `--list` and the capture was asked."""
        with temp_repo('test_shape_repo', only=self.ROSTER_REPO) as root:
            _scenario(root, HEADED, GOOD_HEADER)
            _scenario(root, CAPTURE, 'extends Node\n')
            _config(root, HEADER_ON)
            _runner(root)
            with mock.patch.dict(os.environ, KEEP_LIST):
                code, out = run_check(test_shape)
        self.assertEqual(code, 0, out)
        self.assertIn('1 the runner would boot', out)
        self.assertNotIn(CAPTURE, out)

    def test_the_invoking_makes_flags_do_not_reach_the_roster(self) -> None:
        """A gate run under `make -n check` inherits MAKEFLAGS=n; a nested
        make that honoured it would print the recipe instead of running it,
        and the recipe text is not a roster. Stripped, so the answer is real."""
        with temp_repo('test_shape_repo', only=self.ROSTER_REPO) as root:
            _scenario(root, HEADED, GOOD_HEADER)
            _config(root, HEADER_ON)
            _runner(root)
            with mock.patch.dict(os.environ, {'MAKEFLAGS': 'n', 'MFLAGS': '-n'}):
                code, out = run_check(test_shape)
        self.assertEqual(code, 0, out)
        self.assertIn('1 the runner would boot', out)

    def test_a_makefile_without_the_target_is_a_config_error_naming_it(self) -> None:
        """A consumer on a Makefile.devkit from before the target, or a
        Makefile that never included one: exit 2, and the message names the
        target and where it comes from — never a roster guessed some other
        way. Red at HEAD: the gate never asked make, so this PASSed."""
        with temp_repo('test_shape_repo', only=self.ROSTER_REPO) as root:
            _scenario(root, HEADED, GOOD_HEADER)
            _config(root, HEADER_ON)
            _runner(root)
            (root / 'Makefile').write_text('all:\n\t@true\n', encoding='utf-8')
            code, out = run_check(test_shape)
        self.assertEqual(code, 2, out)
        self.assertIn('integration-list', out)
        self.assertIn('Makefile.devkit', out)

    def test_no_makefile_at_all_is_the_same_config_error(self) -> None:
        with temp_repo('test_shape_repo', only=self.ROSTER_REPO) as root:
            _scenario(root, HEADED, GOOD_HEADER)
            _config(root, HEADER_ON)
            _runner(root)
            (root / 'Makefile').unlink()
            (root / 'Makefile.devkit').unlink()
            code, out = run_check(test_shape)
        self.assertEqual(code, 2, out)
        self.assertIn('integration-list', out)

    def test_a_fail_with_the_header_on_prints_one_census_per_line(self) -> None:
        """A size finding is asked of the tracked tier minus infra (3 here:
        the headed scenario, the small one, the capture tool); a header
        finding of the roster (2: the capture tool is not booted). One
        sentence holding both — `2 finding(s) across 3 scenario(s)` beside a
        roster of 2 — was two censuses and neither number was the other's.
        Red at HEAD: the verdict line read `FAIL — 2 finding(s) across 3`."""
        with temp_repo('test_shape_repo', only=self.ROSTER_REPO) as root:
            _scenario(root, HEADED, GOOD_HEADER)          # 7 lines: over cap 3
            _scenario(root, SMALL, 'extends Node\n')       # 1 line, no header
            _scenario(root, CAPTURE, 'extends Node\n')     # tracked, not booted
            _config(root, '[test_shape]\ncap = 3\nheader = true\n')
            _runner(root)
            code, out = run_check(test_shape)
        self.assertEqual(code, 1, out)
        self.assertIn('[check:test-shape] FAIL — 2 finding(s)\n', out)
        self.assertIn('  size: 1 finding(s) across 3 scenario(s) under '
                      'tests/integration/\n', out)
        self.assertIn('  header: 1 finding(s) across 2 the runner would boot\n',
                      out)
        self.assertNotIn('finding(s) across 3 scenario(s)\n', out)

    def test_a_fail_with_the_header_off_keeps_the_one_census_line(self) -> None:
        """The header-off consumer's line shape is untouched: one census, the
        tracked tier, on the verdict line as before."""
        with temp_repo('test_shape_repo', only=SCENARIOS) as root:
            _config(root, CAP_5)
            code, out = run_check(test_shape)
        self.assertEqual(code, 1, out)
        self.assertIn('FAIL — 1 finding(s) across 2 scenario(s)\n', out)
        self.assertNotIn('size:', out)

    def test_a_ledger_line_naming_a_file_the_runner_does_not_boot_is_stale(self) -> None:
        """The ledger only shrinks: a line for a capture tool is a debt that
        was never owed, and it hides the real count."""
        with temp_repo('test_shape_repo', only=self.ROSTER_REPO) as root:
            _scenario(root, HEADED, GOOD_HEADER)
            _scenario(root, CAPTURE, 'extends Node\n')
            _config(root, HEADER_ON + f'header_ledger = ["{CAPTURE}"]\n')
            _runner(root)
            code, out = run_check(test_shape)
        self.assertEqual(code, 1, out)
        self.assertIn(f'STALE  {CAPTURE}', out)

    def test_header_true_with_no_runner_is_a_config_error_naming_the_path(self) -> None:
        with temp_repo('test_shape_repo', only=self.ROSTER_REPO) as root:
            _scenario(root, HEADED, GOOD_HEADER)
            _config(root, HEADER_ON)
            code, out = run_check(test_shape)
        self.assertEqual(code, 2, out)
        self.assertIn(RUNNER_REL, out)
        self.assertIn('install-runners', out)

    def test_an_older_runner_that_answers_no_list_is_a_config_error_naming_the_remedy(self) -> None:
        with temp_repo('test_shape_repo', only=self.ROSTER_REPO) as root:
            _scenario(root, HEADED, GOOD_HEADER)
            _config(root, HEADER_ON)
            old = root / RUNNER_REL
            old.parent.mkdir(parents=True)
            old.write_text('#!/usr/bin/env bash\necho "unknown flag" >&2; exit 2\n',
                           encoding='utf-8')
            _makefile(root)
            code, out = run_check(test_shape)
        self.assertEqual(code, 2, out)
        self.assertIn('--force', out)
        # The runner's OWN exit came back through make's `Error 2` line —
        # not make's exit 2 for any failed recipe, which would read "boots
        # nothing" and a runner that boots nothing the same.
        self.assertIn('exited 2', out)

    def test_a_runner_that_boots_nothing_is_a_fail_not_a_pass_over_nothing(self) -> None:
        """A tracked tier of one capture tool: the cap census is 1, the roster
        is 0. Rule 4 — a header rule asked of nothing must say so."""
        with temp_repo('test_shape_repo', only=self.ROSTER_REPO) as root:
            _scenario(root, CAPTURE, 'extends Node\n')
            _config(root, HEADER_ON)
            _runner(root)
            code, out = run_check(test_shape)
        self.assertEqual(code, 1, out)
        self.assertIn('boots NOTHING', out)

    def test_the_runner_path_is_configurable_and_repo_relative(self) -> None:
        elsewhere = 'ci/dev/runners/integration.sh'
        with temp_repo('test_shape_repo', only=self.ROSTER_REPO) as root:
            _scenario(root, HEADED, GOOD_HEADER)
            _config(root, HEADER_ON + f'runner = "{elsewhere}"\n')
            _runner(root, elsewhere)
            code, out = run_check(test_shape)
        self.assertEqual(code, 0, out)

    def test_a_runner_path_outside_the_repo_is_refused(self) -> None:
        # A TOML literal string (single quotes), so the backslash reaches the
        # gate as a backslash rather than failing the parse.
        for bad in ('/usr/bin/env', '../integration.sh', 'tools/../../x.sh', '',
                    'tools//x.sh', 'tools\\x.sh'):
            with self.subTest(runner=bad):
                with temp_repo('test_shape_repo', only=self.ROSTER_REPO) as root:
                    _scenario(root, HEADED, GOOD_HEADER)
                    _config(root, HEADER_ON + f"runner = '{bad}'\n")
                    _runner(root)
                    with self.assertRaises(ConfigError):
                        run_check(test_shape)
