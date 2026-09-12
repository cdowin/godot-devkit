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
BOOTS = '## Boots because: tests/unit/contract_test.gd cannot.'
COVERS = '## covers: systems/alpha'

INSTALLABLES = REPO_ROOT / 'src' / 'godot_devkit' / 'godot' / 'installables'
INTEGRATION_RUNNER = INSTALLABLES / 'integration.sh'
RUNNER_REL = 'tools/dev/runners/integration.sh'
CAPTURE = 'tests/integration/thing_capture.gd'
SUPPORT_STUB = 'tests/integration/support/stub.gd'
KEEP_LIST = {'GDK_CAPTURE_GATE_RE': '^(thing_capture)$'}
# The consumer's Makefile: the two pins and the include. The include is
# agentic-sdlc's (its v0.2.0 `install-gates` output, vendored under
# tests/fixtures/ — rule 8) and it `-include`s the tier file `install-runners`
# writes, which is where `integration-list` lives.
CONSUMER_MAKEFILE = ('DEVKIT_VERSION := v0.0.0\nGODOT_DEVKIT_VERSION := v0.0.0\n'
                     'include Makefile.devkit\n')
INCLUDE = REPO_ROOT / 'tests' / 'fixtures' / 'agentic_sdlc' / 'Makefile.devkit'
TIERS = INSTALLABLES / 'Makefile.tiers'
ROSTER_REPO = [*BASE, 'systems/alpha/thing.gd', 'tests/unit/contract_test.gd']
STUB = 'extends Node\n'


def _makefile(root, extra: str = '') -> None:
    """The consumer's Makefile: the pins, the include, and whatever it exports
    to its runners — which is where a keep-list lives, and why the roster is
    asked through `make integration-list` rather than `bash … --list`."""
    shutil.copy2(INCLUDE, root / 'Makefile.devkit')
    shutil.copy2(TIERS, root / 'Makefile.tiers')
    (root / 'Makefile').write_text(extra + CONSUMER_MAKEFILE, encoding='utf-8')


def _runner(root, rel: str = RUNNER_REL, exports: str = '') -> None:
    """The header rule is asked of the roster the integration runner boots,
    through the Makefile that includes the standard set — so a `header = true`
    repo carries both, the runner at the depth install-runners writes it."""
    target = root / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(INTEGRATION_RUNNER, target)
    _makefile(root, exports)


def _old_runner(root) -> None:
    """A runner from before `--list`, under the current Makefile."""
    old = root / RUNNER_REL
    old.parent.mkdir(parents=True)
    old.write_text('#!/usr/bin/env bash\necho "unknown flag" >&2; exit 2\n',
                   encoding='utf-8')
    _makefile(root)


def _gate(only=SCENARIOS, config=CAP_5, scenarios=(), runner=None, exports='',
          prepare=None) -> tuple[int, str]:
    """One run of the gate in a throwaway repo: `scenarios` are (rel, body)
    pairs written AND staged (the gate scans `git ls-files`, so an unstaged
    file is invisible to it), `runner` is where the integration runner is
    installed (with the consumer Makefile), `prepare` is the repo's last
    word before the gate runs."""
    with temp_repo('test_shape_repo', only=only) as root:
        for rel, body in scenarios:
            (root / rel).parent.mkdir(parents=True, exist_ok=True)
            (root / rel).write_text(body, encoding='utf-8')
            subprocess.run(['git', 'add', rel], cwd=root, check=True)
        (root / 'devkit.toml').write_text(config, encoding='utf-8')
        if runner:
            _runner(root, runner, exports)
        if prepare:
            prepare(root)
        return run_check(test_shape)


def _body(*header: str, tail: str = '\tpass\n') -> str:
    """A scenario whose leading comment block is `header`, line by line."""
    return ('extends Node\n' + ''.join(f'{line}\n' for line in header)
            + 'func run() -> void:\n' + tail)


class TheCap(unittest.TestCase):
    def test_a_new_over_cap_scenario_fails_and_prints_its_ledger_line(self) -> None:
        code, out = _gate(SCENARIOS, CAP_5)
        self.assertEqual(code, 1, out)
        self.assertIn(f'OVERCAP  {BIG} — {BIG_LINES} lines (cap 5', out)
        self.assertIn(f'"{BIG}" = {BIG_LINES}', out)
        # The header-off consumer's line shape: one census, the tracked tier,
        # on the verdict line.
        self.assertIn('FAIL — 1 finding(s) across 2 scenario(s)\n', out)
        self.assertNotIn('size:', out)

    def test_a_suite_under_the_cap_passes_and_reports_the_tier_balance(self) -> None:
        code, out = _gate(WHOLE_SUITE, '[test_shape]\ncap = 50\ninfra = ["scenario_base.gd"]\n')
        self.assertEqual(code, 0, out)
        self.assertIn('none over the 50-line cap', out)
        # 32, not 12: the balance counts the whole tier INCLUDING the shared
        # harness the cap excludes — infra boots with every scenario, so it is
        # part of what the tier costs.
        self.assertIn('tier balance: unit 30 / tests/integration 32', out)
        self.assertIn('51% of the suite', out)
        # Stock config asks nothing of a headerless scenario: the header is opt-in.
        self.assertNotIn('NO-HEADER', out)
        self.assertNotIn('header ledger', out)

    def test_the_shared_harness_is_excluded_by_name(self) -> None:
        # Infra boots once per scenario whatever its size, and is where
        # duplication is supposed to MOVE TO — pricing it as a scenario prices
        # a shared helper above the copies it replaced.
        code, out = _gate(WITH_INFRA, CAP_5 + 'infra = ["scenario_base.gd"]\n')
        self.assertEqual(code, 1, out)
        self.assertNotIn('scenario_base.gd', out)
        self.assertEqual(out.count('OVERCAP'), 1, out)

    def test_help_calls_the_cap_readability_and_names_boots_as_the_cost(self) -> None:
        """#8. A consumer that followed the cap faithfully split its files, and
        a split adds a boot: the gate pushed the tier slower while it read as
        the tier's cost control. `check test-shape --help` prints this
        docstring (cli._run_check), so the docstring IS the help, asked here
        at the cheapest altitude."""
        doc = test_shape.__doc__ or ''
        self.assertIn('READABILITY gate', doc)
        self.assertIn('WHAT THIS DOES NOT GOVERN: COST', doc)
        self.assertIn('BOOTS census', doc)
        self.assertIn('`[tests] cases`', doc)


class TheRatchet(unittest.TestCase):
    def test_a_ledgered_file_passes_at_its_size_and_fails_one_line_bigger(self) -> None:
        code, out = _gate(SCENARIOS, CAP_5 + f'ledger = {{ "{BIG}" = {BIG_LINES} }}\n')
        self.assertEqual(code, 0, out)
        self.assertIn('debt ledger: 1 scenario(s) over cap', out)
        code, out = _gate(SCENARIOS, CAP_5 + f'ledger = {{ "{BIG}" = {BIG_LINES - 1} }}\n')
        self.assertEqual(code, 1, out)
        self.assertIn(f'GREW  {BIG} — {BIG_LINES} lines, ledger ceiling '
                      f'{BIG_LINES - 1}', out)


class RefusesRatherThanGuesses(unittest.TestCase):
    """Exit 2 is a config mistake; exit 1 is drift. One row per config
    reader the gate goes through (`number`, `number_table`, `flag`,
    `str_tuple`) and one per grammar class `runner_path_defect` refuses."""

    BAD_CONFIG = (
        ('[test_shape]\ncap = "300"\n', 'must be an integer'),
        # `true` is an `int` in Python — a bool ceiling would silently mean 1
        # and fail every file on the ledger.
        (CAP_5 + f'ledger = {{ "{BIG}" = true }}\n', 'must be an integer'),
        ('[test_shape]\nheader = "yes"\n', 'header'),
        (HEADER_ON + f'header_ledger = "{SMALL}"\n', 'must be a list of strings'),
        # A TOML literal string (single quotes), so the backslash reaches the
        # gate as a backslash rather than failing the parse.
        *((HEADER_ON + f"runner = '{bad}'\n", '[test_shape] runner')
          for bad in ('/usr/bin/env', '../integration.sh', 'tools/../../x.sh', '',
                      'tools//x.sh', 'tools\\x.sh')),
    )

    def test_an_infra_list_that_eats_the_census_fails_loudly(self) -> None:
        code, out = _gate(SCENARIOS, CAP_5 + 'infra = ["big_scenario.gd", "small_scenario.gd"]\n')
        self.assertEqual(code, 1, out)
        self.assertIn('scanned 0 of 2 tracked', out)
        self.assertIn('scenario_root/infra', out)

    def test_a_bad_config_value_is_refused_not_read_as_a_finding(self) -> None:
        for body, reason in self.BAD_CONFIG:
            with self.subTest(config=body), self.assertRaises(ConfigError) as caught:
                _gate(SCENARIOS, body)
            self.assertIn(reason, str(caught.exception))


class TheHeaderRule(unittest.TestCase):
    def test_an_unledgered_scenario_with_no_header_fails(self) -> None:
        code, out = _gate(SCENARIOS, HEADER_ON, runner=RUNNER_REL)
        self.assertEqual(code, 1, out)
        self.assertIn(f'NO-HEADER  {SMALL}', out)
        self.assertIn('## Boots because: tests/unit/<path> cannot', out)

    def test_a_headed_scenario_passes_and_a_capture_tool_and_a_support_stub_are_not_asked(self) -> None:
        # One roster, and the runner owns it: `find` minus support/, the
        # capture tools and its keep-list — so a capture TOOL and a support
        # stub `--diff` can never slice to are not asked. The runner lives
        # where `[test_shape] runner` says, repo-relative.
        code, out = _gate(ROSTER_REPO, HEADER_ON + 'runner = "ci/dev/runners/integration.sh"\n',
                          [(HEADED, GOOD_HEADER), (CAPTURE, STUB), (SUPPORT_STUB, STUB)],
                          runner='ci/dev/runners/integration.sh')
        self.assertEqual(code, 0, out)
        self.assertIn('every one off the header ledger says why it boots', out)
        self.assertIn('1 the runner would boot', out)

    def test_the_ledger_exempts_an_existing_scenario(self) -> None:
        code, out = _gate(SCENARIOS, HEADER_ON + f'header_ledger = ["{SMALL}", "{BIG}"]\n',
                          runner=RUNNER_REL)
        self.assertEqual(code, 0, out)
        self.assertIn('header ledger: 2 scenario(s) yet to say why they boot', out)

    def test_a_ledgered_scenario_that_grew_a_header_names_the_line_to_drop(self) -> None:
        # The ratchet's other direction: the ledger only shrinks, and a file
        # that answered the question must leave it — otherwise the ledger is
        # a permission list that never empties. Answered means BOTH lines: a
        # `covers:` alone (the runner's --diff already slices by it) is held.
        covers_only = GOOD_HEADER.replace(BOOTS.split(' cannot')[0], '## Note:')
        code, out = _gate(ROSTER_REPO, HEADER_ON + f'header_ledger = ["{HEADED}"]\n',
                          [(HEADED, covers_only)], runner=RUNNER_REL)
        self.assertEqual(code, 0, out)
        self.assertNotIn('HEADED', out)
        code, out = _gate(ROSTER_REPO, HEADER_ON + f'header_ledger = ["{HEADED}"]\n',
                          [(HEADED, GOOD_HEADER)], runner=RUNNER_REL)
        self.assertEqual(code, 1, out)
        self.assertIn(f'HEADED  {HEADED} — carries its header; drop it from '
                      f'[test_shape] header_ledger', out)

    def test_a_ledger_line_naming_a_file_the_runner_does_not_boot_is_stale(self) -> None:
        # The ledger only shrinks: a line for a capture tool is a debt that
        # was never owed, and it hides the real count. Stale is ledger minus
        # ROSTER — a tracked file the runner never boots, or one that is gone.
        code, out = _gate(ROSTER_REPO, HEADER_ON + f'header_ledger = ["{CAPTURE}"]\n',
                          [(HEADED, GOOD_HEADER), (CAPTURE, STUB)], runner=RUNNER_REL)
        self.assertEqual(code, 1, out)
        self.assertIn(f'STALE  {CAPTURE}', out)


class TheHeaderRefusalMatrix(unittest.TestCase):
    """Every claim the docstring makes about a covers entry — repo-relative,
    no `..`, no scheme, no glob, no whitespace, EXISTS — gets the input that
    attacks it; so do the other grammar classes of the header (an empty
    entry, a `Boots because:` naming no test, a `covers:` below the first
    statement). Each must be a finding, never a silent prefix of nothing."""

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
    HOSTILE_HEADERS = (
        *((_body(BOOTS, f'## covers: systems/alpha, {entry}'), reason)
          for entry, reason in HOSTILE_COVERS.items()),
        (_body(BOOTS, '## covers: systems/alpha, , tests/unit/contract_test.gd'),
         'covers `` is empty'),
        (_body(BOOTS, '## covers: '), 'is empty'),
        (_body('## Boots because: it just does.', COVERS), 'names no tests/ path'),
        (_body('## Boots because:', COVERS), 'says nothing'),
        # The header is the leading comment block. A declaration inside the
        # body is what the runner would never read, so the gate must not
        # either — or the two disagree on what a scenario covers.
        (_body(BOOTS, tail='\t## covers: systems/alpha\n\tpass\n'),
         f'HEADER  {HEADED} — no `## covers:` line'),
    )

    def test_every_hostile_header_is_refused(self) -> None:
        for body, reason in self.HOSTILE_HEADERS:
            code, out = _gate(ROSTER_REPO, HEADER_ON, [(HEADED, body)], runner=RUNNER_REL)
            self.assertEqual(code, 1, out)
            self.assertIn(reason, out)


class TheHeaderRuleIsAskedOfTheRunnersRoster(unittest.TestCase):
    """One roster, and the runner owns it. The gate scanned `git ls-files`
    minus the infra basenames; the runner discovers with `find` minus
    support/, the capture tools and its keep-list — so the header rule was
    asked of a capture TOOL and a support stub `--diff` can never slice to.
    The gate now reads the roster from `integration.sh --list`, which is the
    one place the discovery rule (and a consumer's edits to it) lives."""

    # Each row is one branch of `runner_roster` that cannot answer: exit 2,
    # naming the remedy, never a roster guessed some other way and never PASS.
    # (runner to install, the repo's last word, phrases the refusal names)
    ROSTER_UNAVAILABLE = (
        # `header = true` with no runner file at all.
        (None, None, (RUNNER_REL, 'install-runners')),
        # A Makefile without the target — a consumer on a tier file from
        # before it, or one that never included one.
        (RUNNER_REL, lambda root: (root / 'Makefile').write_text('all:\n\t@true\n', encoding='utf-8'),
         ('integration-list', 'Makefile.tiers')),
        # An older runner that answers no `--list`: its OWN exit came back
        # through make's `Error 2` line — not make's exit 2 for any failed
        # recipe, which would read "boots nothing" the same.
        (None, _old_runner, ('--force', 'exited 2')),
        # `integration-list` answered exit 0 with a blank stdout — a target
        # that never asked the runner. Returning [] read `roster: 0
        # scenario(s)` then PASS `(0 the runner would boot)`: a PASS over
        # nothing, which the module promises it refuses.
        (RUNNER_REL, lambda root: (root / 'Makefile').write_text('integration-list:\n\t@true\n', encoding='utf-8'),
         ('integration-list', 'printed NOTHING')),
    )

    def test_a_keep_list_the_makefile_exports_reaches_the_roster(self) -> None:
        # The runner's own configuration decides — GDK_CAPTURE_GATE_RE makes
        # a capture a gate, and then it is asked. That knob is a MAKEFILE
        # export, so it reaches `--list` only through make: the gate's own
        # process has no such variable here, and the capture must be asked
        # regardless. Red at HEAD: `bash <runner> --list` from the gate's
        # process saw no keep-list and PASSed over the capture.
        with mock.patch.dict(os.environ, clear=False):
            os.environ.pop('GDK_CAPTURE_GATE_RE', None)
            code, out = _gate(ROSTER_REPO, HEADER_ON,
                              [(HEADED, GOOD_HEADER), (CAPTURE, STUB), (SUPPORT_STUB, STUB)],
                              runner=RUNNER_REL,
                              exports=('GDK_CAPTURE_GATE_RE := ^(thing_capture)$$\n'
                                       'export GDK_CAPTURE_GATE_RE\n'))
        self.assertEqual(code, 1, out)
        self.assertIn(f'NO-HEADER  {CAPTURE}', out)
        self.assertIn('2 the runner would boot', out)
        self.assertNotIn(SUPPORT_STUB, out)

    def test_the_gates_own_environment_never_reaches_the_roster(self) -> None:
        # The adversarial half of "the roster is the tree's": the SAME
        # keep-list variable in the gate's own environment — a shell export,
        # a parent make's leftovers — must change nothing, or the census is a
        # function of who ran the gate (147 under make, 137 from the shim,
        # measured). And a gate run under `make -n check` inherits
        # MAKEFLAGS=n; a nested make that honoured it would print the recipe
        # instead of running it, and the recipe text is not a roster. Both
        # stripped, so the answer is real.
        with mock.patch.dict(os.environ, {**KEEP_LIST, 'MAKEFLAGS': 'n', 'MFLAGS': '-n'}):
            code, out = _gate(ROSTER_REPO, HEADER_ON, [(HEADED, GOOD_HEADER), (CAPTURE, STUB)],
                              runner=RUNNER_REL)
        self.assertEqual(code, 0, out)
        self.assertIn('1 the runner would boot', out)
        self.assertNotIn(CAPTURE, out)

    def test_a_roster_that_cannot_be_asked_is_a_config_error_naming_the_remedy(self) -> None:
        for runner, prepare, phrases in self.ROSTER_UNAVAILABLE:
            code, out = _gate(ROSTER_REPO, HEADER_ON, [(HEADED, GOOD_HEADER)],
                              runner=runner, prepare=prepare)
            self.assertEqual(code, 2, (phrases, out))
            for phrase in phrases:
                self.assertIn(phrase, out)
            self.assertNotIn('PASS', out)

    def test_a_runner_that_boots_nothing_is_a_fail_not_a_pass_over_nothing(self) -> None:
        # A tracked tier of one capture tool: the cap census is 1, the roster
        # is 0. Rule 4 — a header rule asked of nothing must say so.
        code, out = _gate(ROSTER_REPO, HEADER_ON, [(CAPTURE, STUB)], runner=RUNNER_REL)
        self.assertEqual(code, 1, out)
        self.assertIn('boots NOTHING', out)

    def test_a_fail_with_the_header_on_prints_one_census_per_line(self) -> None:
        # A size finding is asked of the tracked tier minus infra (3 here:
        # the headed scenario at 7 lines over cap 3, the small one at 1 line
        # with no header, the capture tool — tracked, not booted); a header
        # finding of the roster (2: the capture tool is not booted). One
        # sentence holding both — `2 finding(s) across 3 scenario(s)` beside
        # a roster of 2 — was two censuses and neither number was the other's.
        # Red at HEAD: the verdict line read `FAIL — 2 finding(s) across 3`.
        code, out = _gate(ROSTER_REPO, '[test_shape]\ncap = 3\nheader = true\n',
                          [(HEADED, GOOD_HEADER), (SMALL, STUB), (CAPTURE, STUB)],
                          runner=RUNNER_REL)
        self.assertEqual(code, 1, out)
        self.assertIn('[check:test-shape] FAIL — 2 finding(s)\n', out)
        self.assertIn('  size: 1 finding(s) across 3 scenario(s) under '
                      'tests/integration/\n', out)
        self.assertIn('  header: 1 finding(s) across 2 the runner would boot\n',
                      out)
        self.assertNotIn('finding(s) across 3 scenario(s)\n', out)
