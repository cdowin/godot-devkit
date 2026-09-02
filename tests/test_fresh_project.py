"""test_fresh_project.py — the milestone's ship criterion, as a gate.

THE FRESH GAME: an empty Godot 4 project, `godot-devkit init`, and then the
standard targets work with zero hand edits. This file is that sentence made
runnable — one fixture project, built from a `project.godot` and an icon, and
every claim below asked of it rather than of a hand-written stand-in.

WHAT IT CAN AND CANNOT PROVE. Godot cannot boot in this package's CI, so the
engine-backed half is `make -n`: parse the whole Makefile, resolve the target,
expand its recipe, run NOTHING. That catches every way the include and the
installed runners can fail to line up — a target naming a runner the install
does not write, a variable the include never declares, a recipe that will not
expand — and it cannot catch a runner that expands fine and fails on contact
with the engine. The real boot is `make smoke` (tools/consumer_smoke.py), which
carries the fresh-project probe that runs the real `make doctor` where Godot is
on PATH, and says so loudly where it is not.

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

pytestmark = pytest.mark.skipif(shutil.which('make') is None
                                or shutil.which('bash') is None
                                or shutil.which('git') is None,
                                reason='needs make, bash and git')

PROJECT_GODOT = ('config_version=5\n\n[application]\n\n'
                 'config/name="Fresh"\nconfig/version="0.1.0"\n'
                 'config/features=PackedStringArray("4.6")\n')
ICON = '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16"/>\n'

# The standard set is 26 targets. The NUMBER is asserted, not just the list: a
# target quietly dropped from the include would otherwise shrink the sweep and
# still pass it, which is this package's cardinal sin wearing a green tick.
STANDARD_COUNT = 26
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
    """One project, every target, in one fixture: standing up 26 of them would
    cost 26 inits and prove the same thing 26 times."""
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
