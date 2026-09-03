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

# The standard set is 27 targets. The NUMBER is asserted, not just the list: a
# target quietly dropped from the include would otherwise shrink the sweep and
# still pass it, which is this package's cardinal sin wearing a green tick.
STANDARD_COUNT = 27
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
    sys.path.insert(0, str(REPO_ROOT / 'tools'))
    import consumer_smoke                                       # noqa: PLC0415
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
