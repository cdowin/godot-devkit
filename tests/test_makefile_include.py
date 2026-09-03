"""test_makefile_include.py — Makefile.devkit: the standard target set.

A consumer's Makefile is two lines plus its own targets; everything else is
this installable. So the contract under test is:

  * the standard target set is EXACTLY the declared one, and every target
    parses and dry-runs on a fixture project that holds nothing but a
    project.godot;
  * `help` lists the standard set AND the project's own, from one grep;
  * `check` is the devkit gates followed by `[gates] extra` — read once,
    through the CLI, and a bad value STOPS the gate rather than narrowing it;
  * the quiet convention holds per target, cross-checked against the runners
    themselves rather than against a memory of which ones publish.

`make -n` is the whole engine story here: nothing in this file boots Godot,
and the dry runs are asserted to stay dry — which is why the sub-make in
`check` is not spelled `$(MAKE)`.
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
                                or shutil.which('bash') is None,
                                reason='needs make and bash')

INCLUDE = REPO_ROOT / 'src/godot_devkit/repo/installables/Makefile.devkit'
INSTALLABLES = INCLUDE.parent

# The standard set, spelled out so this file READS as the contract. It is
# cross-checked against the include below, so it cannot become a second roster
# that quietly disagrees.
STANDARD = (
    'help', 'doctor',
    'parse', 'lint', 'warnings',
    'unit', 'integration', 'integration-all', 'integration-diff', 'scenario',
    'smoke', 'capture', 'import-cache',
    'refs', 'scene', 'scene-diff', 'orphans', 'autoloads', 'pm',
    'pm-scan', 'uid-scan', 'hermetic-scan',
    'hooks-self-test', 'runners-self-test',
    'check', 'precommit', 'milestone',
)

# Which targets publish their verdict THEMSELVES, from inside the runner they
# call — so wrapping them again here would bury it in a log. Asserted against
# the runner sources, not against this comment.
SELF_PUBLISHING = {'parse': 'parse.sh', 'lint': 'lint.sh',
                   'warnings': 'warnings.sh', 'unit': 'unit.sh'}
# Which targets wrap their tool here, because the tool has no verdict of its
# own: the devkit CLI gates, the pure-shell scans, the scenario family and the
# aggregate. The scenario family joined this list in 0.20.0 (MINOR-2): those
# five streamed whatever their runner printed and IGNORED `VERBOSE` — none of
# the three runners has a streaming path this file can reach — while the
# include's header, `help`'s footer and the README all promised it worked.
WRAPPED = ('uid-scan', 'pm-scan', 'hermetic-scan', 'hooks-self-test',
           'runners-self-test', 'check',
           'integration', 'integration-all', 'integration-diff', 'scenario',
           'smoke', 'capture')
# Everything else is not a gate: `help` and `doctor` are reports, the read
# verbs ARE their output, and the compositions print nothing beyond their
# members' verdicts.
NOT_A_GATE = set(STANDARD) - set(SELF_PUBLISHING) - set(WRAPPED)

# What each target needs on the command line to be asked for at all.
ARGS_FOR = {'scenario': ['NAME=boot_to_hub'], 'capture': ['NAME=hub_capture'],
            'refs': ['NAME=Player'], 'scene': ['FILE=scenes/hub.tscn'],
            'scene-diff': ['FILE=scenes/hub.tscn']}

PROJECT_MAKEFILE = (
    'DEVKIT_VERSION := v0.0.0-fixture\n'
    'include Makefile.devkit\n'
    '\n'
    'my-scan: ## a gate this project owns\n'
    '\t@echo "[my-scan] PASS" && touch .my-scan-ran\n'
)
# `check all` is stubbed (its roster is not this file's subject and every real
# gate would report a 0-file census on a fixture); `gates-extra` is the REAL
# verb, reading the fixture's own devkit.toml.
DEVKIT_STUB = """#!/usr/bin/env bash
case "$1" in
  check)       echo "[check:stub] PASS — stubbed for the fixture" ;;
  gates-extra) shift; exec env PYTHONPATH="{src}" python3 -m godot_devkit.cli \\
                    gates-extra "$@" ;;
  *)           echo "stub: unexpected $*" >&2; exit 2 ;;
esac
"""


@contextlib.contextmanager
def project(config: str = '', makefile: str = PROJECT_MAKEFILE):
    """A fixture Godot project carrying the include and nothing else."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / 'game'
        root.mkdir()
        (root / 'project.godot').write_text('config_version=5\n', encoding='utf-8')
        # The whole install-runners payload, at its stock layout: the include
        # SOURCES the library, so a fixture carrying only the Makefile would
        # prove the targets parse and nothing about whether they run.
        for name, rel in install.PLANS['install-runners']:
            target = root / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(install.body_of(name), encoding='utf-8')
        (root / 'Makefile').write_text(makefile, encoding='utf-8')
        if config:
            (root / 'devkit.toml').write_text(config, encoding='utf-8')
        (root / 'devkit-stub').write_text(
            DEVKIT_STUB.format(src=REPO_ROOT / 'src'), encoding='utf-8')
        subprocess.run(['git', 'init', '-q'], cwd=root, check=True)
        yield root


def make(root: Path, *args: str, **env_extra: str) -> subprocess.CompletedProcess:
    env = dict(os.environ, **env_extra)
    # Under `make test` the recipe's shell carries MAKELEVEL/MAKEFLAGS, and a
    # sub-make that inherits them announces 'Entering directory' ahead of the
    # one verdict line these tests read. The make under test is a top-level one.
    for leaked in ('MAKELEVEL', 'MAKEFLAGS', 'MFLAGS'):
        env.pop(leaked, None)
    return subprocess.run(['make', *args], cwd=root, text=True,
                          capture_output=True, env=env, timeout=120)


def stubbed(root: Path) -> str:
    return f'DEVKIT=bash {root}/devkit-stub'


def declared_targets() -> list[str]:
    """Every documented target in the include, asked of the file."""
    pattern = re.compile(r'^([a-z][a-z0-9-]*):.*?## ')
    return [m.group(1) for m in
            (pattern.match(line) for line
             in INCLUDE.read_text(encoding='utf-8').splitlines()) if m]


def recipes() -> dict[str, str]:
    found: dict[str, list[str]] = {}
    current = None
    for line in INCLUDE.read_text(encoding='utf-8').splitlines():
        if line.startswith('\t'):
            if current is not None:
                found[current].append(line)
            continue
        match = re.match(r'^([a-z][a-z0-9-]*):(?!=)', line)
        current = match.group(1) if match else None
        if current is not None:
            found.setdefault(current, [])
    return {name: '\n'.join(body) for name, body in found.items()}


# --- the set ------------------------------------------------------------------
def test_the_include_declares_exactly_the_standard_set():
    """A target added to the include and not to STANDARD would never be dry-run
    below; one removed would leave the parametrization asking for a target that
    no longer exists. The roster is asked of the FILE."""
    declared = declared_targets()
    assert len(declared) == len(set(declared)), f'declared twice: {declared}'
    assert sorted(declared) == sorted(STANDARD)


@pytest.mark.parametrize('target', STANDARD)
def test_make_n_succeeds_for_every_standard_target(target):
    """Parse the whole Makefile, resolve the target, expand its recipe — with
    the STOCK `DEVKIT` (uvx), because a dry run that reached the network would
    be a dry run in name only."""
    with project() as root:
        done = make(root, '-n', target, *ARGS_FOR.get(target, []))
    assert done.returncode == 0, done.stdout + done.stderr


def test_a_dry_run_of_check_runs_nothing_at_all():
    """`make -n` executes any recipe line holding the literal `$(MAKE)`. The
    sub-make that runs `[gates] extra` is therefore spelled `$${MAKE:-make}`,
    and this is the assertion that keeps it that way: the project gate must not
    fire, and neither must the stub."""
    with project('[gates]\nextra = ["my-scan"]\n') as root:
        done = make(root, '-n', 'check', stubbed(root))
        assert done.returncode == 0, done.stdout + done.stderr
        assert not (root / '.my-scan-ran').exists(), done.stdout


def test_help_lists_the_standard_set_and_the_projects_own():
    with project() as root:
        done = make(root, 'help')
    assert done.returncode == 0, done.stdout + done.stderr
    # The roster is colourized; the names live between the escapes.
    plain = re.sub(r'\x1b\[[0-9;]*m', '', done.stdout)
    listed = {m.group(1) for m in
              re.finditer(r'^  ([a-z][a-z0-9-]*) +\S', plain, re.M)}
    assert set(STANDARD) <= listed, (
        f'missing from `make help`: {sorted(set(STANDARD) - listed)}')
    assert 'my-scan' in listed, "the project's own target is not listed"
    assert 'a gate this project owns' in plain


# --- check: the devkit gates, then the project's own --------------------------
def test_check_runs_the_devkit_gates_and_then_the_projects_own():
    with project('[gates]\nextra = ["my-scan"]\n') as root:
        done = make(root, 'check', stubbed(root))
        assert done.returncode == 0, done.stdout + done.stderr
        assert (root / '.my-scan-ran').exists(), (
            f'[gates] extra never ran:\n{done.stdout}{done.stderr}')
        assert (root / '.gate-reports' / 'check.log').is_file()
    verdicts = [ln for ln in done.stdout.splitlines() if ln.startswith('[CHECK]')]
    assert len(verdicts) == 1, done.stdout
    assert 'full log: .gate-reports/check.log' in verdicts[0]
    assert '[my-scan] PASS' in done.stdout


def test_check_with_no_extras_is_just_the_devkit_gates():
    with project() as root:
        done = make(root, 'check', stubbed(root))
        assert done.returncode == 0, done.stdout + done.stderr
        assert not (root / '.my-scan-ran').exists()
    assert done.stdout.startswith('[CHECK]'), done.stdout


def test_verbose_streams_the_transcript_and_still_ends_with_the_verdict():
    with project() as root:
        done = make(root, 'check', stubbed(root), VERBOSE='1')
    assert done.returncode == 0, done.stdout + done.stderr
    assert '[check:stub] PASS' in done.stdout
    assert done.stdout.strip().splitlines()[-1].startswith('[CHECK]')


# MINOR-2: `make scenario|smoke|integration|integration-all|capture VERBOSE=1`
# printed exactly what `VERBOSE=0` did. The runner is reached with no engine
# on PATH, so it fails — which is the useful shape here: a FAILING gate is
# where a reader most needs the transcript, and both halves of the convention
# have to hold on it.
VERBOSE_TARGETS = [
    pytest.param('scenario', ['NAME=smoke'], 'SCENARIO', id='scenario'),
    pytest.param('smoke', [], 'SMOKE', id='smoke'),
    pytest.param('integration', [], 'INTEGRATION', id='integration'),
    pytest.param('integration-all', [], 'INTEGRATION', id='integration-all'),
    pytest.param('integration-diff', [], 'INTEGRATION', id='integration-diff'),
    pytest.param('capture', ['NAME=shot'], 'CAPTURE', id='capture'),
]


@pytest.mark.parametrize('target,args,tag', VERBOSE_TARGETS)
def test_the_scenario_family_is_quiet_by_default_and_streams_on_verbose(
        target, args, tag):
    with project() as root:
        quiet = make(root, target, *args, stubbed(root), PATH='/usr/bin:/bin')
        loud = make(root, target, *args, stubbed(root), PATH='/usr/bin:/bin',
                    VERBOSE='1')
        log = root / '.gate-reports' / f'{target}.log'
        transcript = log.read_text(encoding='utf-8')
    verdict = f'[{tag}] '
    quiet_lines = [ln for ln in quiet.stdout.splitlines() if ln.strip()]
    assert quiet_lines and quiet_lines[-1].startswith(verdict), quiet.stdout
    assert f'full log: .gate-reports/{target}.log' in quiet_lines[-1]
    assert transcript, f'the verdict named a log that holds nothing'
    # VERBOSE ADDS the stream; it never replaces the verdict or skips the file.
    loud_lines = [ln for ln in loud.stdout.splitlines() if ln.strip()]
    assert loud_lines[-1].startswith(verdict), loud.stdout
    assert len(loud_lines) > len(quiet_lines), (
        f'VERBOSE=1 printed no more than the quiet run:\n{loud.stdout}')
    for line in transcript.splitlines():
        if line.strip():
            assert line in loud.stdout, (
                f'VERBOSE=1 did not stream what the log holds: {line!r}')


def test_a_failing_devkit_gate_shows_what_broke_and_stops_before_the_extras():
    with project('[gates]\nextra = ["my-scan"]\n') as root:
        done = make(root, 'check', f'DEVKIT=bash {root}/no-such-stub')
        assert done.returncode != 0
        assert not (root / '.my-scan-ran').exists(), (
            'a red devkit gate still ran the project gates')
    verdict = [ln for ln in done.stdout.splitlines() if ln.startswith('[CHECK]')]
    assert len(verdict) == 1 and 'FAIL' in verdict[0], done.stdout


def test_a_bad_gates_extra_stops_check_instead_of_narrowing_it():
    """The cardinal sin, with a config file in front of it: a value make cannot
    use must never read as "no extra gates"."""
    with project('[gates]\nextra = ["my scan"]\n') as root:
        done = make(root, 'check', stubbed(root))
        assert done.returncode == 2, done.stdout + done.stderr
        assert not (root / '.my-scan-ran').exists()
    assert 'not make targets' in done.stderr, done.stderr


def test_extra_naming_check_itself_is_refused_rather_than_recursing():
    """`extra = ["check"]` is a value the grammar CANNOT reject — it is a
    perfectly well-formed target name. The include catches it on re-entry, and
    so it also catches a project gate that runs `make check` two levels down."""
    with project('[gates]\nextra = ["check"]\n') as root:
        done = make(root, 'check', stubbed(root))
    assert done.returncode != 0
    assert 're-entered through [gates] extra' in done.stderr, done.stderr


# --- the quiet convention, cross-checked against the runners ------------------
@pytest.mark.parametrize('target,runner', SELF_PUBLISHING.items())
def test_a_runner_that_publishes_its_own_verdict_is_not_wrapped_twice(target,
                                                                     runner):
    body = recipes()[target]
    assert runner in body, f'{target} no longer calls {runner}'
    assert 'gdk_gate' not in body, (
        f'{target} wraps {runner}, which already publishes its own verdict — '
        f'the wrapper\'s summary would replace it and file the real one away')
    source = (INSTALLABLES / runner).read_text(encoding='utf-8')
    assert 'gdk_gate_verdict' in source, (
        f'{runner} stopped publishing a verdict — {target} must now wrap it')


@pytest.mark.parametrize('target', WRAPPED)
def test_a_tool_with_no_verdict_of_its_own_gets_one_here(target):
    body = recipes()[target]
    assert '$(call gdk_gate,' in body or 'gdk_gate_verdict' in body, (
        f'{target} prints whatever its tool prints instead of one verdict line')


def test_the_compositions_add_no_output_of_their_own():
    bodies = recipes()
    for name in ('precommit', 'milestone'):
        assert bodies[name].strip() == '', f'{name} grew a recipe: {bodies[name]}'


def test_every_target_is_phony():
    """None of these produce a file of their own name; a stray `check` file in
    a repo would otherwise silently disable the gate."""
    text = INCLUDE.read_text(encoding='utf-8')
    phony = re.search(r'^\.PHONY:((?:.*\\\n)*.*)$', text, re.M).group(1)
    assert set(phony.split()) - {'\\'} == set(STANDARD)


# --- runners-self-test: the one target whose recipe is hand-rolled ------------
def test_runners_self_test_proves_every_installed_runner_not_a_listed_two():
    """The corpus set is DERIVED from what is installed, so a runner landing
    tomorrow is proven the day it arrives. Real run — the self-tests boot
    nothing."""
    with project() as root:
        done = make(root, 'runners-self-test')
    assert done.returncode == 0, done.stdout + done.stderr
    verdict = done.stdout.strip()
    runners = sum(1 for _, rel in install.PLANS['install-runners']
                  if rel.startswith('tools/dev/runners/') and rel.endswith('.sh'))
    assert verdict.startswith(
        f'[RUNNERS] the library + {runners} runner corpora PASS'), (
        f'expected every installed runner ({runners}), got: {verdict}')


def test_an_empty_runner_census_fails_rather_than_reporting_nothing_wrong():
    """Rule 4: a gate that scanned nothing must say so, loudly. A repo that
    moved its runners without setting GDK_RUNNERS_DIR would otherwise get a
    green self-test over zero corpora."""
    with project() as root:
        for entry in (root / 'tools/dev/runners').iterdir():
            entry.unlink()
        done = make(root, 'runners-self-test')
    assert done.returncode == 2, done.stdout + done.stderr
    assert 'no runners under' in done.stdout, done.stdout
    assert 'install-runners' in done.stdout, done.stdout


# --- the file is generic ------------------------------------------------------
def test_the_include_names_no_consumer_project():
    text = INCLUDE.read_text(encoding='utf-8').lower()
    for name in ('nullbound', 'trail', 'appalachian'):
        assert name not in text, f'the include names {name}'


def test_a_missing_devkit_version_is_a_parse_error_naming_the_fix():
    with project(makefile='include Makefile.devkit\n') as root:
        done = make(root, 'help')
    assert done.returncode != 0
    assert 'DEVKIT_VERSION is not set' in done.stderr, done.stderr
    assert 'ABOVE `include Makefile.devkit`' in done.stderr, done.stderr


def test_the_pin_is_the_projects_and_reaches_the_cli():
    with project() as root:
        done = make(root, '-n', 'autoloads')
    assert 'v0.0.0-fixture' in done.stdout, done.stdout
