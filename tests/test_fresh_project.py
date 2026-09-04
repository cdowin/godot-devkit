"""test_fresh_project.py — the milestone's ship criterion, as a gate.

THE FRESH GAME: an empty Godot 4 project, `godot-devkit init`, and then the
standard targets work with zero hand edits. This file is that sentence made
runnable — one fixture project, built from a `project.godot` and an icon, and
every claim below asked of it rather than of a hand-written stand-in.

WHAT IT CAN AND CANNOT PROVE. Godot cannot boot in this package's CI, so the
ENGINE-backed half is `make -n`: parse the whole Makefile, resolve the target,
expand its recipe, run NOTHING. That catches every way the include and the
installed runners can fail to line up — a target naming a runner the install
does not write, a variable the include never declares, a recipe that will not
expand — and it cannot catch a runner that expands fine and fails on contact
with the engine. The real boot is `make smoke` (tools/consumer_smoke.py), which
carries the fresh-project probe that runs the real `make doctor` and the real
`make check` where Godot is on PATH, and says so loudly where it is not.

`make check` IS run for real here, and that is not a hedge — the gate roster is
pure parse and boots nothing, so a dry run of it was never the best this file
could do. Dry-running it is what shipped a `compile_sweep.gd` with no `.uid`
sidecar: `make -n precommit` expands recipes and reaches no verdict, while
`check uid` CHECK 3 had a live finding about a real installed file on every
freshly-`init`'d project. What the run asserts is the honest half of the ship
criterion — that nothing the INSTALL wrote is a finding. The three Godot-file
gates still redden over the 0-file census a project with no scene in it
genuinely has; that is the stock roster being wrong for a blank repo, named in
the seed devkit.toml and narrowed there in one line, and not something `init`
can or should fix.

A DRY RUN THAT EXECUTES IS NOT A DRY RUN. `make -n` runs any recipe line
holding the literal `$(MAKE)`, so `check`'s sub-make is spelled `$${MAKE:-make}`
— and the census below proves it: nothing is written, no report directory
appears, and the stock uvx `DEVKIT` is never resolved (which would reach the
network from a target that promised to run nothing).
"""
from __future__ import annotations

import contextlib
import hashlib
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from support import REPO_ROOT  # noqa: E402

sys.path.insert(0, str(REPO_ROOT / 'src'))
from godot_devkit.repo import install  # noqa: E402

pytestmark = pytest.mark.skipif(shutil.which('make') is None
                                or shutil.which('bash') is None
                                or shutil.which('git') is None,
                                reason='needs make, bash and git')

PROJECT_GODOT = ('config_version=5\n\n[application]\n\n'
                 'config/name="Fresh"\nconfig/version="0.1.0"\n'
                 'config/features=PackedStringArray("4.6")\n')
ICON = '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16"/>\n'

# The standard set is 28 targets. The NUMBER is asserted, not just the list: a
# target quietly dropped from the include would otherwise shrink the sweep and
# still pass it, which is this package's cardinal sin wearing a green tick.
STANDARD_COUNT = 28  # +integration-list (0.23.0): the roster, asked by check test-shape
DOCUMENTED = re.compile(r'^([a-z][a-z0-9-]*):.*?## ', re.MULTILINE)

# What a target needs on the command line to be asked for at all.
ARGS_FOR = {'scenario': ['NAME=smoke'], 'capture': ['NAME=shot'],
            'refs': ['NAME=Player'], 'scene': ['FILE=main.tscn'],
            'scene-diff': ['FILE=main.tscn']}


@contextlib.contextmanager
def initialized_project():
    """An empty Godot 4 project with `godot-devkit init` run in it, once."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / 'game'
        root.mkdir()
        (root / 'project.godot').write_text(PROJECT_GODOT, encoding='utf-8')
        (root / 'icon.svg').write_text(ICON, encoding='utf-8')
        subprocess.run(['git', 'init', '-q'], cwd=root, check=True)
        done = subprocess.run(
            [sys.executable, '-m', 'godot_devkit.cli', 'init'],
            cwd=root, capture_output=True, text=True,
            env={**os.environ, 'PYTHONPATH': str(REPO_ROOT / 'src')})
        assert done.returncode == 0, done.stdout + done.stderr
        yield root


def make(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(['make', *args], cwd=root, text=True,
                          capture_output=True, env=dict(os.environ),
                          timeout=120)


def standard_targets(root: Path) -> list[str]:
    """The documented target set, asked of the INSTALLED include."""
    body = (root / 'Makefile.devkit').read_text(encoding='utf-8')
    return DOCUMENTED.findall(body)


def files(root: Path) -> set[str]:
    return {p.relative_to(root).as_posix() for p in root.rglob('*')
            if p.is_file() and not p.relative_to(root).as_posix().startswith('.git/')}


# --- the ship criterion -------------------------------------------------------
def test_the_installed_include_carries_the_whole_standard_set():
    with initialized_project() as root:
        targets = standard_targets(root)
    assert len(targets) == len(set(targets)) == STANDARD_COUNT, targets
    # The four the ship criterion names by hand, so a rename cannot pass by
    # keeping the count.
    for named in ('doctor', 'precommit', 'milestone', 'check'):
        assert named in targets, f'{named} is not in the standard set'


def test_make_n_succeeds_for_every_standard_target_with_zero_hand_edits():
    """One project, every target, in one fixture: standing up 27 of them would
    cost 27 inits and prove the same thing 27 times."""
    with initialized_project() as root:
        before = files(root)
        failures = []
        for target in standard_targets(root):
            done = make(root, '-n', target, *ARGS_FOR.get(target, []))
            if done.returncode != 0:
                failures.append(f'--- make -n {target}\n{done.stdout}{done.stderr}')
        default = make(root, '-n')
        after = files(root)
    assert not failures, '\n'.join(failures)
    assert default.returncode == 0, default.stdout + default.stderr
    assert after == before, f'a dry run WROTE: {sorted(after ^ before)}'
    assert not (root / '.gate-reports').exists()


@pytest.mark.parametrize('target', ['doctor', 'precommit'])
def test_the_two_targets_the_ship_criterion_names(target):
    """Named separately from the sweep because these two ARE the criterion —
    a sweep that silently stopped covering them would still be green."""
    with initialized_project() as root:
        done = make(root, '-n', target)
    assert done.returncode == 0, done.stdout + done.stderr


# --- `make check`, RUN --------------------------------------------------------
# A verdict line reads `[check:<gate>] FAIL — …`, and on a blank project there
# are exactly two kinds: a finding about a file the INSTALL wrote (this
# package's problem, and the class that shipped a sidecar-less
# compile_sweep.gd), and a 0-file census over a file kind a project with no
# scene in it does not have (the stock roster being wrong for a blank repo —
# the seed devkit.toml says so in those words and narrows it in one line).
VERDICT_RE = re.compile(r'^\[check:([a-z-]+)\] (PASS|FAIL) — (.*)$', re.MULTILINE)
EMPTY_CENSUS = 'scanned 0 of 0 tracked'
# What a blank Godot project holds nothing of. Spelled out, so a gate JOINING
# this set is a decision somebody makes here rather than a silent widening.
GATES_WITH_NOTHING_TO_SCAN = {'uid', 'tres', 'props'}


def committed(root: Path) -> None:
    """Every gate resolves its scope through `git ls-files`, so an uncommitted
    tree is a 0-file census for ALL of them and the run would prove nothing."""
    subprocess.run(['git', 'add', '-A'], cwd=root, check=True,
                   capture_output=True)
    subprocess.run(['git', '-c', 'user.email=t@example.com',
                    '-c', 'user.name=t', 'commit', '-qm', 'init', '--', '.'],
                   cwd=root, check=True, capture_output=True)


def working_tree_devkit() -> str:
    """`make check` resolves `DEVKIT` to `uvx --from git+…@<pin>` — the
    RELEASED tag, over the network. Overriding it on the command line is how
    this package verifies itself against source (CLAUDE.md: never a cached
    wheel), and it is not a hand edit to the project."""
    return (f'DEVKIT=env PYTHONPATH={REPO_ROOT / "src"} '
            f'{sys.executable} -m godot_devkit.cli')


def check_verdicts(root: Path) -> list[tuple[str, str, str]]:
    """(gate, PASS|FAIL, detail) for every gate `make check` actually ran."""
    committed(root)
    make(root, 'check', working_tree_devkit())
    transcript = (root / '.gate-reports' / 'check.log').read_text(
        encoding='utf-8')
    verdicts = VERDICT_RE.findall(transcript)
    assert verdicts, f'no gate verdict in the transcript:\n{transcript}'
    return verdicts


def test_nothing_the_install_wrote_is_a_check_finding():
    """The ship criterion's real half, run rather than dry-run."""
    with initialized_project() as root:
        verdicts = check_verdicts(root)
    ours = [(gate, detail) for gate, outcome, detail in verdicts
            if outcome == 'FAIL' and EMPTY_CENSUS not in detail]
    assert not ours, (
        'a gate reported a finding about a file `init` wrote:\n'
        + '\n'.join(f'  [check:{g}] {d}' for g, d in ours))


def test_the_gates_that_do_apply_to_a_blank_project_pass():
    """The other direction: the assertion above must not be satisfiable by a
    roster on which everything reports an empty census. `doc` and `shell` read
    what `init` actually wrote, and both have to be green on it."""
    with initialized_project() as root:
        verdicts = check_verdicts(root)
    applicable = {gate: outcome for gate, outcome, _ in verdicts
                  if gate not in GATES_WITH_NOTHING_TO_SCAN}
    assert applicable, f'every gate on the roster scanned nothing: {verdicts}'
    assert set(applicable.values()) == {'PASS'}, applicable


def test_help_lists_the_standard_set_on_a_project_that_added_nothing():
    with initialized_project() as root:
        expected = standard_targets(root)
        done = make(root, 'help')
    assert done.returncode == 0, done.stdout + done.stderr
    plain = re.sub(r'\x1b\[[0-9;]*m', '', done.stdout)
    listed = {m.group(1) for m in
              re.finditer(r'^  ([a-z][a-z0-9-]*) +\S', plain, re.M)}
    assert set(expected) <= listed, (
        f'missing from `make help`: {sorted(set(expected) - listed)}')


def test_a_project_gate_joins_check_through_devkit_toml_not_a_fork():
    """The extension path, on a REAL init'd tree: the project appends its own
    target to its own Makefile and names it in the config `init` wrote."""
    with initialized_project() as root:
        makefile = root / 'Makefile'
        makefile.write_text(
            makefile.read_text(encoding='utf-8')
            + '\nmy-scan: ## a gate this project owns\n\t@echo "[my-scan] PASS"\n',
            encoding='utf-8')
        config = root / 'devkit.toml'
        config.write_text(config.read_text(encoding='utf-8')
                          + '\n[gates]\nextra = ["my-scan"]\n', encoding='utf-8')
        listed = make(root, 'help')
        roster = subprocess.run(
            [sys.executable, '-m', 'godot_devkit.cli', 'gates-extra'],
            cwd=root, capture_output=True, text=True,
            env={**os.environ, 'PYTHONPATH': str(REPO_ROOT / 'src')})
    assert 'my-scan' in listed.stdout, listed.stdout
    assert 'a gate this project owns' in listed.stdout
    assert roster.returncode == 0, roster.stdout + roster.stderr
    assert roster.stdout.split() == ['my-scan'], roster.stdout


# --- the hook census: doctor's count, the install roster, and the smoke probe -
# `make smoke`'s fresh-project probe asserts that the number of hooks doctor
# reports armed equals the number `install-hooks` ships. It carried that number
# as the literal `TRACKED_HOOKS = 6`, and the two 0.22.0 ledger couriers turned
# it into `FAIL  make doctor: hook census  8 tracked hook(s) armed, 6
# installed` on the day they landed — a red smoke run about a roster, not about
# behaviour. doctor.sh itself was never wrong: it counts what is IN
# tools/hooks/ precisely so a hook added after it was written is still covered.
# The literal was the only roster in the loop, so it is now derived, and these
# two tests are the reason it cannot come back: the census is proven HERE, in
# the suite, instead of first in a gate that needs two consumer checkouts.
HOOKS_DIR = 'tools/hooks'
DOCTOR_ARMED = re.compile(r'tracked hook \S+ present \+ executable')


def installed_hook_roster() -> list[str]:
    """What `install-hooks` puts under tools/hooks/, minus doctor's own
    exclusions (`_*` sourced libraries, `*.local` config drop-ins)."""
    return [rel for _, rel in install.PLANS['install-hooks']
            if rel.startswith(f'{HOOKS_DIR}/')
            and not Path(rel).name.startswith('_')
            and not rel.endswith('.local')]


def test_the_smoke_probes_hook_census_is_derived_from_the_install_roster():
    """The number `make smoke` compares against must BE the roster, not a copy
    of it. A copy is only ever correct until the next hook."""
    consumer_smoke = smoke_harness()
    assert consumer_smoke.TRACKED_HOOKS == len(installed_hook_roster()), (
        f'consumer_smoke.TRACKED_HOOKS = {consumer_smoke.TRACKED_HOOKS} but '
        f'install-hooks ships {len(installed_hook_roster())} hooks under '
        f'{HOOKS_DIR}/: {installed_hook_roster()}')


def test_doctor_arms_and_reports_every_hook_the_install_verb_ships():
    """The coupling itself, on a real `init`'d tree: doctor's census is asked
    of the DIRECTORY, so it must come back equal to the roster that filled it.
    This is the assertion `make smoke` makes with two consumer checkouts and a
    host toolchain; making it here means a new hook can never be discovered by
    the gate first."""
    roster = installed_hook_roster()
    with initialized_project() as root:
        armed = subprocess.run(['bash', 'tools/setup-hooks.sh'], cwd=root,
                               capture_output=True, text=True)
        assert armed.returncode == 0, armed.stderr
        done = subprocess.run(['bash', 'tools/dev/checks/doctor.sh'], cwd=root,
                              capture_output=True, text=True,
                              env=dict(os.environ))
        for rel in roster:
            assert (root / rel).is_file(), f'{rel} was not installed'
        reported = DOCTOR_ARMED.findall(done.stdout)
    assert len(reported) == len(roster), (
        f'doctor reports {len(reported)} armed hook(s), install-hooks ships '
        f'{len(roster)}: {roster}\n{done.stdout}')
    for rel in roster:
        assert any(Path(rel).name in row for row in reported), (
            f'{rel} is installed and armed but doctor never named it\n'
            f'{done.stdout}')


# --- the smoke's release-runners worktree -------------------------------------
# `make smoke` used to run the working tree's `check all` IN PLACE against the
# runners each consumer's PIN had installed — the combination a consumer
# occupies for the minutes between a pin bump and `install-runners --force`,
# and never the one a release ships. v0.23.0 walked into it: `check test-shape`
# asks its roster through `make integration-list`, nullbound had opted into the
# header rule, its installed `Makefile.devkit` predated the target, and the
# smoke was red on a consumer state the release's own adoption note says to
# leave. The fix at the time was to advance the fixture by hand ahead of the
# pin, which is a procedure, not a gate.
#
# The smoke now installs the working tree's runners into a throwaway `git
# worktree` of the consumer and runs the gates there. Everything below is
# proven against a SCRATCH git repo standing in for a consumer, so it holds on
# CI where no consumer is checked out — and so the two live checkouts are never
# what discovers a defect in the mechanism that writes to them.
SCRATCH_PROJECT_GODOT = ('config_version=5\n\n[application]\n\n'
                         'config/name="Scratch"\nconfig/version="0.1.0"\n')
# `include Makefile.devkit` is the consumer's half of install-runners, and the
# include refuses without a pin above it.
SCRATCH_MAKEFILE = 'DEVKIT_VERSION := v0.0.0\ninclude Makefile.devkit\n'
# `test-shape` alone, because it is the ONE gate in the roster that reaches
# back through the consumer's own Makefile into the installed runner — which is
# exactly the coupling the in-place run could not see.
SCRATCH_DEVKIT_TOML = (
    '[checks]\nall = ["test-shape"]\n\n'
    '[test_shape]\nscenario_root = "tests/integration"\n'
    'unit_root = "tests/unit"\nheader = true\n'
    'runner = "tools/dev/runners/integration.sh"\n')
SCRATCH_SCENARIO = ('## Boots because: tests/unit/boot_test.gd cannot start '
                    'the engine\n## covers: tools/dev\n\nextends Node\n')
SCRATCH_UNIT = 'extends Node\n'
ROSTER_TARGET = 'integration-list'
STALE_RUNNER = 'tools/dev/runners/parse.sh'
HEADER_EDIT = ('GDK_UNIT_TEST_ROOT="${GDK_UNIT_TEST_ROOT:-tests/unit}"',
               'GDK_UNIT_TEST_ROOT="${GDK_UNIT_TEST_ROOT:-tests/units}"')
HEADER_EDITED_RUNNER = 'tools/dev/runners/unit.sh'
INCLUDE = 'Makefile.devkit'
GIT_DIR_PREFIX = '.git/'


def smoke_harness():
    """`tools/consumer_smoke.py`. It is a tool, not a package module, so the
    import needs the path — one spelling of that, here, for every test that
    reaches it."""
    sys.path.insert(0, str(REPO_ROOT / 'tools'))
    import consumer_smoke                                       # noqa: PLC0415
    return consumer_smoke


def stale_include(root: Path) -> None:
    """Delete `integration-list` from the INSTALLED Makefile.devkit — v0.23.0's
    consumer state exactly: runners that predate the target the working tree's
    `check test-shape` asks its roster through."""
    body, kept, dropping = (root / INCLUDE).read_text(encoding='utf-8'), [], False
    for line in body.split('\n'):
        if line.startswith(f'{ROSTER_TARGET}:'):
            dropping = True
            continue
        if dropping:
            dropping = bool(line.strip())
            continue
        kept.append(line)
    # …and out of the .PHONY roster, or make answers the missing target with a
    # silent exit 0 instead of "no rule to make target".
    text = '\n'.join(kept).replace(f' {ROSTER_TARGET}', '')
    assert f'{ROSTER_TARGET}:' not in text, 'the target survived the edit'
    (root / INCLUDE).write_text(text, encoding='utf-8')


def runner_is_a_directory(root: Path) -> None:
    """A destination the installer CANNOT write, committed so the worktree
    checkout materialises it. Nothing else in this suite can make an install
    fail from inside a worktree the smoke creates itself."""
    target = root / STALE_RUNNER
    target.unlink()
    target.mkdir()
    (target / 'kept.txt').write_text('not a runner\n', encoding='utf-8')


def edited_header(root: Path) -> None:
    """m1's shape: a runner differing from the installable ONLY inside its
    editable `project config` block. Without --force this refuses the roster;
    the smoke passes --force precisely so a consumer that edited its headers
    is not a red smoke run every time."""
    target = root / HEADER_EDITED_RUNNER
    body = target.read_text(encoding='utf-8')
    assert HEADER_EDIT[0] in body, 'the header line this edits is gone'
    target.write_text(body.replace(*HEADER_EDIT), encoding='utf-8')
    assert install.header_only_difference(
        target.read_text(encoding='utf-8'),
        install.body_of(Path(HEADER_EDITED_RUNNER).name)), (
        'the fixture is not m1 shape — the difference left the config block')


@contextlib.contextmanager
def scratch_consumer(damage=None):
    """A committed git repo standing in for a consumer: the runners installed,
    a Makefile that includes them, and one scenario for `check test-shape` to
    grade. `damage` is applied before the commit — the consumer state under
    test, in the tree the worktree will carry."""
    harness = smoke_harness()
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / 'consumer'
        root.mkdir()
        (root / 'project.godot').write_text(SCRATCH_PROJECT_GODOT,
                                            encoding='utf-8')
        subprocess.run(['git', 'init', '-q'], cwd=root, check=True)
        code, out = harness.devkit(root, 'install-runners')
        assert code == 0, out
        (root / 'Makefile').write_text(SCRATCH_MAKEFILE, encoding='utf-8')
        (root / 'devkit.toml').write_text(SCRATCH_DEVKIT_TOML, encoding='utf-8')
        for rel, body in (('tests/integration/boot.gd', SCRATCH_SCENARIO),
                          ('tests/unit/boot_test.gd', SCRATCH_UNIT)):
            (root / rel).parent.mkdir(parents=True, exist_ok=True)
            (root / rel).write_text(body, encoding='utf-8')
        if damage is not None:
            damage(root)
        committed(root)
        yield root


def fingerprint(root: Path) -> dict[str, str]:
    """Every file outside .git/, by sha256.

    `git status --porcelain` cannot see an in-place edit to a tracked file that
    was put back, nor a mode flip, and "the consumer's checkout is untouched"
    is the claim this whole mechanism rests on: it adds a worktree to somebody
    else's live repo.
    """
    return {rel: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(root.rglob('*')) if path.is_file()
            for rel in [path.relative_to(root).as_posix()]
            if not rel.startswith(GIT_DIR_PREFIX)}


def rows_named(report, what: str) -> list[tuple[str, str]]:
    """(outcome, detail) for every row called `what` — a row reads
    `ok    <what>` / `FAIL  <what>`."""
    return [(verdict.split(maxsplit=1)[0], detail)
            for _, verdict, detail in report.rows
            if verdict.split(maxsplit=1)[1] == what]


@pytest.fixture(scope='module')
def smoked():
    """ONE full `smoke()` against a scratch consumer whose runners are behind
    the working tree, fingerprinted around the run. Module-scoped because the
    run is the expensive part and every claim below reads the same one."""
    with scratch_consumer(damage=stale_include) as root:
        harness = smoke_harness()
        report = harness.Report()
        before = (fingerprint(root), harness.git(root, 'status', '--porcelain'),
                  harness.git(root, 'worktree', 'list'))
        harness.smoke(root, report)
        after = (fingerprint(root), harness.git(root, 'status', '--porcelain'),
                 harness.git(root, 'worktree', 'list'))
        yield {'root': root, 'report': report, 'before': before, 'after': after}


def test_check_all_runs_against_the_release_runners_not_the_consumers(smoked):
    """v0.23.0, as a test. IN PLACE this consumer's `check all` cannot answer —
    its installed include has no `integration-list` — and through the worktree
    it is green, because the smoke put the working tree's runners there."""
    in_place, out = smoke_harness().devkit(smoked['root'], 'check', 'all')
    assert in_place == 2 and ROSTER_TARGET in out, (
        f'the fixture is not the state v0.23.0 hit: exit {in_place}\n{out}')
    assert rows_named(smoked['report'], 'check all') == [
        ('ok', 'exit 0 against the release\'s runners')], smoked['report'].rows


def test_the_row_says_how_many_files_the_release_is_ahead_by(smoked):
    outcome, detail = rows_named(smoked['report'], 'runners ahead')[0]
    assert outcome == 'ok', detail
    assert detail == f'1 file(s) ahead of the consumer\'s install: {INCLUDE}'


def test_the_consumers_checkout_is_byte_identical_before_and_after(smoked):
    files_before, porcelain_before, _ = smoked['before']
    files_after, porcelain_after, _ = smoked['after']
    changed = sorted(rel for rel in set(files_before) | set(files_after)
                     if files_before.get(rel) != files_after.get(rel))
    assert not changed, f'the smoke run WROTE to the consumer: {changed}'
    assert porcelain_after == porcelain_before
    assert len(files_before) > len(install.PLANS['install-runners']), (
        f'{len(files_before)} file(s) fingerprinted — the walk found nothing, '
        f'so "unchanged" would be true of an empty comparison')


def test_no_worktree_is_left_behind_in_the_consumer(smoked):
    _, _, before = smoked['before']
    _, _, after = smoked['after']
    assert after == before, f'`git worktree list` changed: {before} -> {after}'
    assert rows_named(smoked['report'], 'worktree list unchanged') == [
        ('ok', f'{len(before)} worktree(s), the same before and after')]


def test_a_consumer_already_current_is_zero_ahead_and_still_green():
    """The other side of the row: nothing to install is not a special case, and
    it must not read as "nothing was proven"."""
    harness = smoke_harness()
    with scratch_consumer() as root:
        report = harness.Report()
        harness.against_the_release_runners(root, report)
    assert rows_named(report, 'runners ahead') == [
        ('ok', '0 file(s) ahead of the consumer\'s install — the consumer is '
               'current with the working tree')], report.rows
    assert rows_named(report, 'check all')[0][0] == 'ok', report.rows


def test_a_header_edited_runner_is_not_a_refusal():
    """m1's shape, from the other side. Every runner ships an editable header;
    a smoke that refused on one would be red on every consumer that edited
    theirs, which is the pain m1 was filed about. --force overwrites it, the
    row counts it, and the gates still run."""
    harness = smoke_harness()
    with scratch_consumer(damage=edited_header) as root:
        report = harness.Report()
        harness.against_the_release_runners(root, report)
    assert rows_named(report, 'runners ahead') == [
        ('ok', f'1 file(s) ahead of the consumer\'s install: '
               f'{HEADER_EDITED_RUNNER}')], report.rows
    assert rows_named(report, 'check all')[0][0] == 'ok', report.rows


def test_a_failing_install_is_a_red_row_naming_the_file_and_never_a_fallback():
    """A fallback to the in-place run would recreate the exact blind spot this
    mechanism exists to close, and it would look GREEN. So: the row is red, it
    names the destination, `check all` never ran, and what did not run is
    printed rather than left silent."""
    harness = smoke_harness()
    with scratch_consumer(damage=runner_is_a_directory) as root:
        report = harness.Report()
        harness.against_the_release_runners(root, report)
    outcome, detail = rows_named(report, 'runners ahead')[0]
    assert outcome == 'FAIL', detail
    assert STALE_RUNNER in detail and 'is a directory' in detail, detail
    assert report.failed >= 1
    assert rows_named(report, 'check all') == [], (
        'the run FELL BACK to the consumer\'s own runners after the install '
        f'failed: {report.rows}')
    assert any('does NOT fall back' in line for line in report.skipped), (
        f'nothing said what was not run: {report.skipped}')
    # …and the worktree still went away.
    assert rows_named(report, 'worktree list unchanged')[0][0] == 'ok', \
        report.rows


def test_an_uncommitted_runner_edit_is_not_a_census_disagreement():
    """The worktree carries HEAD, so the census grading the install is asked of
    the WORKTREE too. Asked of the checkout instead, a consumer mid-edit
    reports a file the install never saw and the row reddens over somebody
    else's work in progress — which is what both live consumers were doing
    the first time this ran."""
    harness = smoke_harness()
    with scratch_consumer() as root:
        edited = root / HEADER_EDITED_RUNNER
        edited.write_text(edited.read_text(encoding='utf-8')
                          .replace(*HEADER_EDIT), encoding='utf-8')
        assert harness.git(root, 'status', '--porcelain'), 'the edit did not land'
        report = harness.Report()
        harness.against_the_release_runners(root, report)
    assert rows_named(report, 'runners ahead') == [
        ('ok', '0 file(s) ahead of the consumer\'s install — the consumer is '
               'current with the working tree')], report.rows


# The `git worktree list` shapes the row has to tell apart. A live consumer
# produced the third one on the row's first real run — a peer agent committed
# in nullbound mid-smoke, the commit column moved, and a whole-line comparison
# called somebody else's commit a leaked worktree.
LISTED = '{path}  {sha} [{branch}]'
MAIN = LISTED.format(path='/repo', sha='aaaaaaa', branch='main')
MOVED = LISTED.format(path='/repo', sha='bbbbbbb', branch='main')
PEER_WORKTREE = LISTED.format(path='/elsewhere/peer', sha='ccccccc',
                              branch='peer')
OURS = Path('/tmp/gdk/wt')
LEAK = LISTED.format(path=OURS, sha='ddddddd', branch='detached HEAD')
FAILED_REMOVAL = subprocess.CompletedProcess(
    args=['git'], returncode=1, stdout='', stderr='fatal: it is dirty')


@pytest.mark.parametrize('after, clean, says', [
    pytest.param([MAIN], True, 'the same before and after', id='unchanged'),
    pytest.param([MAIN, LEAK], False, 'LEAKED', id='our worktree survived'),
    pytest.param([MAIN, PEER_WORKTREE], False, 'none of it is this run\'s',
                 id='a peer added one'),
    pytest.param([], False, 'left', id='the main checkout vanished'),
    pytest.param([MOVED], True, 'somebody committed under the run',
                 id='a peer committed mid-run'),
])
def test_the_worktree_row_tells_a_leak_from_somebody_elses_commit(after, clean,
                                                                  says):
    verdict, detail = smoke_harness().worktree_verdict(
        [MAIN], after, OURS, FAILED_REMOVAL)
    assert verdict is clean, detail
    assert says in detail, detail
    if not clean and 'LEAKED' in detail:
        # …and it names the removal that did not work, rather than retrying it.
        assert FAILED_REMOVAL.stderr in detail, detail
