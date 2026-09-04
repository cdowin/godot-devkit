"""test_runners_installable.py — the shell runners, RUN rather than read.

`gdk_runners.sh` is the library every Godot-booting gate in a consumer routes
through, and `import_cache.sh` is the one runner that ships with it. Neither is
Python and neither can boot an engine here, so the contract is proven the way
the hook corpus is: each script carries a `--self-test`, and this file drives
it through a subprocess and holds it to its published shape.

Two things this file adds on top of firing the corpus:

  - it MUTATES the verdict format and re-runs, so "the self-test passes" is
    evidence rather than a claim. A corpus that cannot fail is a green light
    wired to nothing.
  - it exercises the verdict line and its log path END TO END — sourcing the
    library into a scratch cwd and running a fake gate through
    gate_log -> gate_capture -> gate_verdict. That line shape is grepped by
    consumer Makefiles, so it is contract (CLAUDE.md rule 6), not cosmetics.

The runner's own boot path is deliberately NOT exercised: it needs Godot, and
this package never boots one (rule 2). What is exercised is everything the
runner owns around the boot — its argument surface and its outcome check,
which is written as a pure function over the filesystem exactly so it can be
fired at fake files.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from support import REPO_ROOT  # noqa: E402

from godot_devkit.repo import install  # noqa: E402

pytestmark = pytest.mark.skipif(shutil.which('bash') is None,
                                reason='needs bash')

INSTALLABLES = REPO_ROOT / 'src' / 'godot_devkit' / 'repo' / 'installables'
LIBRARY = INSTALLABLES / 'gdk_runners.sh'
RUNNER = INSTALLABLES / 'import_cache.sh'
# Every shell runner install-runners ships. Each one carries --help and
# --self-test, and the argument surface below is fired at all of them: a runner
# added to the plan and not here would be a runner nothing holds to the shape.
SCRIPTS = tuple(INSTALLABLES / name
                for name, _rel in install.PLANS['install-runners']
                if name.endswith('.sh'))

# The one line shape a consumer greps. Changing it is a minor bump at least.
VERDICT = '[PARSE] PASS (2 files) — full log: .gate-reports/parse.log'


def run(*argv: str, cwd: Path | None = None) -> subprocess.CompletedProcess:
    # The installed CI exports VERBOSE=1 for the whole `make milestone` step,
    # and the quiet-by-default cases below are asked of the DEFAULT — VERBOSE
    # unset. A case that wants the stream sets it in its own env.
    env = {k: v for k, v in os.environ.items() if k != 'VERBOSE'}
    return subprocess.run(['bash', *argv], cwd=cwd, text=True,
                          capture_output=True, env=env)


# --- the corpora, fired ------------------------------------------------------
@pytest.mark.parametrize('script', SCRIPTS, ids=lambda p: p.stem)
def test_the_self_test_corpus_passes_and_reports_its_case_count(script):
    done = run(str(script), '--self-test')
    assert done.returncode == 0, done.stdout + done.stderr
    assert 'SELF-TEST OK' in done.stdout, done.stdout
    count = done.stdout.split('—')[1].split('case')[0].strip()
    assert int(count) > 0, f'a corpus of {count} cases proves nothing'


def test_the_library_corpus_FAILS_when_the_verdict_shape_is_broken(tmp_path):
    """Rule 4, applied to the corpus itself: a self-test that cannot go red is
    a false PASS with extra steps. Swap the em dash for a hyphen — the one
    byte a consumer's grep would feel — and the corpus must catch it."""
    mutant = tmp_path / 'gdk_runners.sh'
    mutant.write_text(
        LIBRARY.read_text(encoding='utf-8')
        .replace("'[%s] %s — full log: %s\\n'", "'[%s] %s - full log: %s\\n'"),
        encoding='utf-8')
    done = run(str(mutant), '--self-test')
    assert done.returncode == 1, done.stdout + done.stderr
    assert 'SELF-TEST FAIL' in done.stderr, done.stderr
    assert 'the verdict line shape' in done.stderr, done.stderr


# --- the verdict line and its log, end to end --------------------------------
def test_a_gate_prints_one_verdict_line_naming_a_log_that_holds_the_stream(tmp_path):
    script = tmp_path / 'gate.sh'
    script.write_text(
        f'set -uo pipefail\n'
        f'source "{LIBRARY}"\n'
        'log="$(gdk_gate_log parse)"\n'
        'gdk_gate_capture "$log" -- printf "boot line\\nsweep line\\n"\n'
        'gdk_gate_verdict PARSE "PASS (2 files)" "$log"\n',
        encoding='utf-8')

    done = run(str(script), cwd=tmp_path)
    assert done.returncode == 0, done.stdout + done.stderr
    assert done.stdout.splitlines() == [VERDICT], done.stdout

    log = tmp_path / '.gate-reports' / 'parse.log'
    assert log.exists(), 'the verdict named a log that was never written'
    assert log.read_text(encoding='utf-8') == 'boot line\nsweep line\n'


def test_an_ambient_verbose_does_not_turn_the_quiet_case_loud(tmp_path, monkeypatch):
    """The installed CI (`ci-verify.yml`) exports VERBOSE=1 for the whole
    `make milestone` step, and this suite runs inside it. The quiet case
    above is asked of the DEFAULT, so it must hold whatever the caller's
    environment happens to say — red on every CI run before the helper
    dropped the variable, green under bare pytest on a Mac."""
    monkeypatch.setenv('VERBOSE', '1')
    test_a_gate_prints_one_verdict_line_naming_a_log_that_holds_the_stream(tmp_path)


@pytest.mark.parametrize('script', SCRIPTS, ids=lambda p: p.stem)
def test_a_self_test_verdict_is_one_line_whatever_the_ambient_verbose_says(script):
    """A corpus proves both settings on its own pinned cases; the value the
    caller exports is not one of them. The library's cap case inherited it and
    streamed its eight bytes INTO the verdict line — `01234567[gdk-runners]
    SELF-TEST OK …` — which is what `make runners-self-test VERBOSE=1`, and so
    the installed CI, then read as the verdict."""
    done = subprocess.run(['bash', str(script), '--self-test'], text=True,
                          capture_output=True,
                          env=dict(os.environ, VERBOSE='1'))
    assert done.returncode == 0, done.stdout + done.stderr
    lines = done.stdout.splitlines()
    assert len(lines) == 1, done.stdout
    assert re.match(r'^\[[A-Za-z][A-Za-z-]*\] SELF-TEST OK — \d+ case\(s\)$',
                    lines[0]), lines[0]


def test_verbose_streams_the_same_transcript_the_log_holds(tmp_path):
    """VERBOSE is the escape hatch the quiet default is only safe because of:
    it must add the stream, not replace the verdict or skip the file."""
    script = tmp_path / 'gate.sh'
    script.write_text(
        f'set -uo pipefail\n'
        f'source "{LIBRARY}"\n'
        'log="$(gdk_gate_log parse)"\n'
        'gdk_gate_capture "$log" -- printf "boot line\\n"\n'
        'gdk_gate_verdict PARSE "PASS (2 files)" "$log"\n',
        encoding='utf-8')

    done = subprocess.run(['bash', str(script)], cwd=tmp_path, text=True,
                          capture_output=True, env={'PATH': '/usr/bin:/bin',
                                                    'VERBOSE': '1'})
    assert done.returncode == 0, done.stdout + done.stderr
    assert done.stdout.splitlines() == ['boot line', VERDICT], done.stdout
    assert (tmp_path / '.gate-reports' / 'parse.log').read_text(
        encoding='utf-8') == 'boot line\n'


# --- the argument surface: what each script REFUSES --------------------------
@pytest.mark.parametrize('script', SCRIPTS, ids=lambda p: p.stem)
@pytest.mark.parametrize('argv', [
    ('--nope',),                 # an unknown verb
    ('-x',),                     # an unknown short flag
    ('--self-test', 'extra'),    # a known verb with an argument it does not take
    ('--help', '--self-test'),   # two verbs
    ('',),                       # an empty argument is not "no argument"
], ids=['unknown', 'short', 'verb-plus-extra', 'two-verbs', 'empty'])
def test_an_argument_neither_script_takes_is_refused_as_a_usage_error(script, argv):
    done = run(str(script), *argv)
    assert done.returncode == 2, (
        f'{script.name} {argv} -> {done.returncode}\n{done.stdout}{done.stderr}')
    # Exit 2 for the RIGHT reason: a refusal names the remedy. Without this the
    # empty-argument case passed off a downstream "library not found" as the
    # argument check working.
    assert '--help' in done.stdout + done.stderr, done.stdout + done.stderr


@pytest.mark.parametrize('script', SCRIPTS, ids=lambda p: p.stem)
def test_help_exits_zero_and_names_the_script(script):
    done = run(str(script), '--help')
    assert done.returncode == 0, done.stdout + done.stderr
    assert script.name in done.stdout, done.stdout


def test_the_runner_refuses_when_the_library_is_not_where_it_was_installed(tmp_path):
    """The runner sources the library by a configured relative path. A repo
    that moved one and not the other must be told, not left to run a rebuild
    with no sandbox — that is the incident the runner exists to prevent."""
    runner = tmp_path / 'import_cache.sh'
    shutil.copy2(RUNNER, runner)
    done = subprocess.run(['bash', str(runner)], cwd=tmp_path, text=True,
                          capture_output=True,
                          env={'PATH': '/usr/bin:/bin',
                               'GDK_RUNNERS_LIB': 'nowhere/gdk_runners.sh'})
    assert done.returncode == 2, done.stdout + done.stderr
    assert 'gdk_runners.sh not found' in done.stderr, done.stderr


# --- the 0.19.0 release review's findings, each pinned ------------------------
# The shell-side findings are cases in the scripts' own --self-test corpora
# (fired above). These three are not reachable from bash: two live in the
# Python install verb, and one is the runner refusing a repo it cannot serve.
def test_the_runner_refuses_a_root_that_is_not_a_godot_project(tmp_path):
    """MINOR-6. `REPO_ROOT_FROM_HERE` is a hardcoded depth: installed anywhere
    else it resolves to an arbitrary ancestor, and the run used to mint a
    sandbox there and boot `--path .` in it — reporting the failure as "the
    import pass hit the bound", which sends the reader to raise a timeout that
    was never the problem. The usage text promises exit 2 for an unusable repo;
    this is the path that produces it."""
    root = tmp_path / 'repo'
    (root / 'tools' / 'dev' / 'runners').mkdir(parents=True)
    shutil.copy2(LIBRARY, root / 'tools' / 'dev' / 'gdk_runners.sh')
    runner = root / 'tools' / 'dev' / 'runners' / 'import_cache.sh'
    shutil.copy2(RUNNER, runner)

    done = subprocess.run(['bash', str(runner)], cwd=root, text=True,
                          capture_output=True, env={'PATH': '/usr/bin:/bin'})
    assert done.returncode == 2, done.stdout + done.stderr
    assert 'not a Godot project' in done.stderr, done.stderr
    assert 'REPO_ROOT_FROM_HERE' in done.stderr, done.stderr
    # And it refused BEFORE minting anything: a sandbox in a directory that is
    # not the project is the residue this refusal exists to prevent.
    assert not (root / '.headless-userdata').exists()


def test_a_godot_project_at_the_root_gets_past_that_refusal(tmp_path):
    """The other half of the same claim: the guard must not refuse a repo it
    was installed into correctly. With a stub `godot` that writes nothing the
    run reaches its own outcome check and fails there (exit 1) — a different
    verdict, which is the point."""
    root = tmp_path / 'repo'
    (root / 'tools' / 'dev' / 'runners').mkdir(parents=True)
    (root / 'project.godot').write_text('config_version=5\n', encoding='utf-8')
    shutil.copy2(LIBRARY, root / 'tools' / 'dev' / 'gdk_runners.sh')
    runner = root / 'tools' / 'dev' / 'runners' / 'import_cache.sh'
    shutil.copy2(RUNNER, runner)
    stub = tmp_path / 'bin'
    stub.mkdir()
    (stub / 'godot').write_text('#!/bin/sh\nexit 0\n', encoding='utf-8')
    (stub / 'godot').chmod(0o755)

    done = subprocess.run(['bash', str(runner)], cwd=root, text=True,
                          capture_output=True,
                          env={'PATH': f'{stub}:/usr/bin:/bin'})
    assert done.returncode == 1, done.stdout + done.stderr
    assert 'not a Godot project' not in done.stderr, done.stderr
    assert 'did not refresh the cache' in done.stdout, done.stdout


# --- the report dir a runner aims rm -rf at ----------------------------------
# MINOR-1. `scenario.sh` reaps entries out of GDK_SCENARIO_REPORT_DIR and
# `capture.sh` `rm -rf`s GDK_CAPTURE_REPORT_DIR whole, and both took the name
# on trust: `GDK_SCENARIO_REPORT_DIR=.` deleted a probe repo — `.git` included
# — BEFORE the boot, and `GDK_CAPTURE_REPORT_DIR=tests` emptied `tests/`. The
# scenario docstring's "a mis-set dir cannot aim rm elsewhere" was false of the
# dir itself, which is the claim worth attacking.
SCENARIO = INSTALLABLES / 'scenario.sh'
CAPTURE = INSTALLABLES / 'capture.sh'
REPORT_DIR_RUNNERS = {'scenario.sh': ('GDK_SCENARIO_REPORT_DIR', SCENARIO),
                      'capture.sh': ('GDK_CAPTURE_REPORT_DIR', CAPTURE)}


def _report_dir_fixture(tmp_path: Path, runner: Path) -> tuple[Path, set[str]]:
    """A git repo with real tracked content, and the runner at stock depth."""
    root = tmp_path / 'repo'
    (root / 'tools' / 'dev' / 'runners').mkdir(parents=True)
    (root / 'project.godot').write_text('config_version=5\n', encoding='utf-8')
    (root / 'tests').mkdir()
    (root / 'tests' / 'keep.gd').write_text('extends Node\n', encoding='utf-8')
    shutil.copy2(LIBRARY, root / 'tools' / 'dev' / 'gdk_runners.sh')
    shutil.copy2(runner, root / 'tools' / 'dev' / 'runners' / runner.name)
    subprocess.run(['git', 'init', '-q'], cwd=root, check=True)
    subprocess.run(['git', 'add', '-A'], cwd=root, check=True,
                   capture_output=True)
    before = {p.relative_to(root).as_posix() for p in root.rglob('*')}
    return root, before


@pytest.mark.parametrize('name', sorted(REPORT_DIR_RUNNERS), ids=lambda n: n)
# An EMPTY value is deliberately absent: every runner reads
# `${GDK_X:-<default>}`, so an exported empty string takes the default and
# never reaches the guard. The library's own corpus covers the empty argument.
@pytest.mark.parametrize('value', ['.', '..', 'tests', '/tmp/gdk-probe'],
                         ids=['dot', 'dotdot', 'a-tracked-dir', 'absolute'])
def test_a_mis_set_report_dir_is_refused_before_anything_is_removed(tmp_path,
                                                                   name, value):
    variable, source = REPORT_DIR_RUNNERS[name]
    root, before = _report_dir_fixture(tmp_path, source)
    done = subprocess.run(['bash', f'tools/dev/runners/{name}', 'smoke'],
                          cwd=root, text=True, capture_output=True,
                          env={'PATH': '/usr/bin:/bin', variable: value,
                               'HOME': str(tmp_path / 'home')})
    after = {p.relative_to(root).as_posix() for p in root.rglob('*')}
    assert done.returncode == 2, done.stdout + done.stderr
    assert variable in done.stderr, done.stderr
    assert after == before, f'the refusal still touched the tree: {before ^ after}'


@pytest.mark.parametrize('name', sorted(REPORT_DIR_RUNNERS), ids=lambda n: n)
def test_the_stock_report_dir_is_not_refused(tmp_path, name):
    """The guard must not refuse the configuration every consumer runs. With
    no engine the run fails LATER and differently, which is the point."""
    _variable, source = REPORT_DIR_RUNNERS[name]
    root, _before = _report_dir_fixture(tmp_path, source)
    done = subprocess.run(['bash', f'tools/dev/runners/{name}', 'smoke'],
                          cwd=root, text=True, capture_output=True,
                          env={'PATH': '/usr/bin:/bin',
                               'HOME': str(tmp_path / 'home')})
    assert 'REPORT_DIR' not in done.stderr, done.stderr


# --- unit.sh's coverage gate, driven through the RUNNER ----------------------
# The self-test corpus proves the two parsers. The BRANCH that reconciles them
# is main-flow, and nothing exercised it: a mutant deleting the count-mismatch
# check survived the whole suite, and the 0/0 case was a documented PASS. Both
# need the runner run end to end, which needs an engine — so a stub prints the
# GUT transcript and unit.sh does everything else for real.
UNIT = INSTALLABLES / 'unit.sh'
GUT_TRANSCRIPT = ('#!/usr/bin/env bash\n'
                  'echo "Running tests..."\n'
                  'echo "Totals"\n'
                  'echo "Scripts        {scripts}"\n'
                  'echo "Tests          {scripts}"\n'
                  'exit {code}\n')


def _unit_fixture(tmp_path: Path, tier: dict[str, int], *,
                  scripts_ran: int, gut_exit: int = 0) -> tuple[Path, dict]:
    """A Godot project carrying unit.sh, a tier of empty test scripts, and a
    `godot` that prints a GUT totals block claiming `scripts_ran`."""
    root = tmp_path / 'repo'
    (root / 'tools' / 'dev' / 'runners').mkdir(parents=True)
    (root / 'project.godot').write_text('config_version=5\n', encoding='utf-8')
    shutil.copy2(LIBRARY, root / 'tools' / 'dev' / 'gdk_runners.sh')
    shutil.copy2(UNIT, root / 'tools' / 'dev' / 'runners' / 'unit.sh')
    for slice_name, count in tier.items():
        directory = root / 'tests' / 'unit' / slice_name
        directory.mkdir(parents=True)
        for index in range(count):
            (directory / f'test_{index}.gd').write_text('', encoding='utf-8')
    stub = tmp_path / 'bin'
    stub.mkdir()
    (stub / 'godot').write_text(
        GUT_TRANSCRIPT.format(scripts=scripts_ran, code=gut_exit),
        encoding='utf-8')
    # `timeout` too: the library BOUNDS every engine run and refuses outright
    # without one, and macOS ships neither `timeout` nor `gtimeout`. A stub
    # keeps the fixture hermetic — the bound is not what these cases are about,
    # and a skip on the host's coreutils would take the coverage gate with it.
    (stub / 'timeout').write_text('#!/usr/bin/env bash\nshift 2\nexec "$@"\n',
                                  encoding='utf-8')
    for name in ('godot', 'timeout'):
        (stub / name).chmod(0o755)
    return (root / 'tools' / 'dev' / 'runners' / 'unit.sh',
            {'PATH': f'{stub}:/usr/bin:/bin', 'HOME': str(tmp_path / 'home')})


def _run_unit(runner: Path, env: dict, *argv: str) -> subprocess.CompletedProcess:
    return subprocess.run(['bash', str(runner), *argv], cwd=runner.parents[2],
                          text=True, capture_output=True, env=env)


def test_a_full_census_that_reconciles_is_the_pass_this_gate_is_for(tmp_path):
    """The control. Without it the two failures below could be satisfied by a
    runner that fails on everything."""
    runner, env = _unit_fixture(tmp_path, {'stats': 2}, scripts_ran=2)
    done = _run_unit(runner, env)
    assert done.returncode == 0, done.stdout + done.stderr
    assert '[UNIT] PASS (2/2 scripts loaded' in done.stdout, done.stdout


def test_a_count_mismatch_fails_instead_of_passing_the_scripts_gut_dropped(tmp_path):
    """MINOR-6b / mutant M5. GUT logs `Ignoring script ... because it does not
    extend GutTest` for a script that will not PARSE and then omits it from the
    totals, so the run prints "All tests passed!" and exits 0. The count
    comparison is the only thing that sees it — and no test named the branch,
    so deleting it survived the suite."""
    runner, env = _unit_fixture(tmp_path, {'stats': 3}, scripts_ran=2)
    done = _run_unit(runner, env)
    assert done.returncode == 1, done.stdout + done.stderr
    assert '3 test script(s) on disk, 2 run' in done.stdout, done.stdout
    assert 'COVERAGE FAIL (script count mismatch)' in done.stdout, done.stdout


@pytest.mark.parametrize('argv,tier', [
    (('typo',), {'stats': 2}),   # a slice that does not exist
    ((), {}),                    # a tier root holding nothing
], ids=['typod-slice', 'empty-tier'])
def test_an_empty_census_fails_and_names_what_it_looked_in(tmp_path, argv, tier):
    """MAJOR-2. `DISK_SCRIPTS=0` reconciled with GUT's unconditional
    `Totals -> Scripts 0` and the gate printed
    `PASS (0/0 scripts loaded - full coverage)`, exit 0 — rule 4's cardinal
    sin, on the tier a consumer slices by hand every day."""
    runner, env = _unit_fixture(tmp_path, tier, scripts_ran=0)
    done = _run_unit(runner, env, *argv)
    assert done.returncode == 1, done.stdout + done.stderr
    assert 'full coverage' not in done.stdout, done.stdout
    assert 'COVERAGE FAIL (0 test scripts found)' in done.stdout, done.stdout
    # It names the DIRECTORIES it scanned, because the repair is one of two
    # spellings and a verdict that does not name them chooses neither.
    expected = 'tests/unit/typo' if argv else 'tests/unit'
    assert expected in done.stdout, done.stdout


# --- scenario.sh's cold-cache recovery, driven through the RUNNER ------------
# 0.24.0/bugs/import-cache-rebuild-does-not-repair-a-stale-uid-index. In a
# consumer, 147 of 147 scenarios FAILED on the `invalid UID … using text path
# instead` sweep while every one of them printed its own
# `[SCENARIO] <name> PASS steps=N errors=0`. The recovery detected the class
# precisely and then applied a remedy that cannot work: an import pass against
# an EXISTING .godot/ mints sidecars for files that are NEW, and does not
# rebuild the uid index for tracked files already missing from it. Measured
# three times in that tree — including once after deleting uid_cache.bin alone
# — 1780 entries and the same 56 missing every time; `rm -rf .godot` then a
# rebuild gave 1822 in 21 s. So the runner retried the same failure once per
# scenario, 147 times.
#
# The stub below IS that distinction, and it is the whole fixture: its rebuild
# branch rewrites the cache file and leaves `.godot/stale` alone, so only a run
# that REMOVES the directory can clear it. Nothing here boots an engine.
STALE_MARKER = '.godot/stale'
SCENARIO_STUB = """#!/usr/bin/env bash
case " $* " in
	*" --editor "*)
		echo rebuild >> "$GDK_STUB_LOG"
		mkdir -p .godot && : > .godot/uid_cache.bin
		exit 0 ;;
esac
echo boot >> "$GDK_STUB_LOG"
{warn}
echo "[SCENARIO] alpha {result} steps=1 errors=0"
exit 0
"""
UID_WARNING = ('echo \'WARNING: invalid UID "uid://cabc" - using text path'
               ' instead: res://alpha.gd\'')
# The repairable tree: the warning stops exactly when the directory goes.
WARN_WHILE_STALE = f'if [ -f {STALE_MARKER} ]; then {UID_WARNING}; fi'
# The tree no remedy repairs — what proves the ladder has a last rung.
WARN_ALWAYS = UID_WARNING
# What rung 2 says before it removes anything.
REMOVAL_NOTICE = 'REMOVING .godot/'


def _scenario_fixture(tmp_path: Path, warn: str,
                      result: str = 'PASS') -> tuple[Path, dict, Path]:
    """A Godot project carrying scenario.sh at stock depth, a `.godot` whose
    index is stale, and a `godot` that reports the uid class per `warn`."""
    root = tmp_path / 'repo'
    (root / 'tools' / 'dev' / 'runners').mkdir(parents=True)
    (root / 'tests' / 'integration').mkdir(parents=True)
    (root / 'tests' / 'integration' / 'alpha.gd').write_text('extends Node\n',
                                                             encoding='utf-8')
    (root / 'project.godot').write_text('config_version=5\n', encoding='utf-8')
    shutil.copy2(LIBRARY, root / 'tools' / 'dev' / 'gdk_runners.sh')
    shutil.copy2(SCENARIO, root / 'tools' / 'dev' / 'runners' / 'scenario.sh')
    (root / '.godot').mkdir()
    (root / '.godot' / 'uid_cache.bin').write_text('', encoding='utf-8')
    (root / STALE_MARKER).write_text('56 tracked sidecars missing\n',
                                     encoding='utf-8')

    stub = tmp_path / 'bin'
    stub.mkdir()
    (stub / 'godot').write_text(
        SCENARIO_STUB.format(warn=warn, result=result), encoding='utf-8')
    # See _unit_fixture: the library BOUNDS every engine run and refuses
    # outright without a timeout binary, and macOS ships neither.
    (stub / 'timeout').write_text('#!/usr/bin/env bash\nshift 2\nexec "$@"\n',
                                  encoding='utf-8')
    for name in ('godot', 'timeout'):
        (stub / name).chmod(0o755)

    log = tmp_path / 'stub.log'
    log.write_text('', encoding='utf-8')
    env = {'PATH': f'{stub}:/usr/bin:/bin', 'HOME': str(tmp_path / 'home'),
           'GDK_STUB_LOG': str(log)}
    return root, env, log


def _run_scenario(root: Path, env: dict, *argv: str,
                  merged: bool = False) -> subprocess.CompletedProcess:
    return subprocess.run(
        ['bash', 'tools/dev/runners/scenario.sh', *argv, 'alpha'], cwd=root,
        text=True, env=env, stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT if merged else subprocess.PIPE)


def _engine_runs(log: Path) -> tuple[int, int]:
    """(boots, rebuilds) — every engine invocation the run actually made."""
    lines = log.read_text(encoding='utf-8').split()
    return lines.count('boot'), lines.count('rebuild')


def test_a_stale_uid_index_survives_the_rebuild_and_the_run_removes_the_cache(tmp_path):
    """The bug, end to end. Rung 1 rebuilds and changes nothing; rung 2 removes
    `.godot/` and rebuilds, and the third boot is clean. Before the escalation
    the run stopped after rung 1 and reported FAIL over a scenario that had
    passed twice."""
    root, env, log = _scenario_fixture(tmp_path, WARN_WHILE_STALE)
    done = _run_scenario(root, env)
    assert done.returncode == 0, done.stdout + done.stderr
    assert '[SCENARIO] alpha PASS' in done.stdout, done.stdout
    assert _engine_runs(log) == (3, 2), done.stdout + done.stderr
    assert not (root / STALE_MARKER).exists(), 'the stale index was left in place'
    assert done.stderr.count(REMOVAL_NOTICE) == 1, done.stderr


def test_the_run_says_it_is_removing_the_cache_before_the_retry_it_enables(tmp_path):
    """`rm -rf .godot` throws away a local editor's state, so it is announced,
    and the announcement is not a report written afterwards: it precedes the
    boot it makes possible. `--verbose` puts the notice and the transcript on
    one stream, in the order they happened."""
    root, env, _log = _scenario_fixture(tmp_path, WARN_WHILE_STALE)
    done = _run_scenario(root, env, '--verbose', merged=True)
    assert done.returncode == 0, done.stdout
    stream = done.stdout
    assert REMOVAL_NOTICE in stream, stream
    assert stream.index(REMOVAL_NOTICE) < stream.rindex('[SCENARIO] alpha PASS'), stream


def test_the_escalation_is_bounded_at_two_remedies_and_the_third_failure_is_final(tmp_path):
    """A tree neither remedy repairs must cost exactly two remedies. The ladder
    is straight-line code, never a loop — a retry re-evaluating its own
    condition would boot the engine forever on a tree that is really broken."""
    root, env, log = _scenario_fixture(tmp_path, WARN_ALWAYS)
    done = _run_scenario(root, env)
    assert done.returncode == 1, done.stdout + done.stderr
    assert _engine_runs(log) == (3, 2), done.stdout + done.stderr
    assert 'FAIL — engine-level errors' in done.stdout, done.stdout
    # Announced once, and the failure that followed did not un-announce it: a
    # notice a reader only sees when the repair WORKED is a notice about
    # nothing.
    assert done.stderr.count(REMOVAL_NOTICE) == 1, done.stderr


def test_a_genuinely_failing_scenario_is_never_retried_and_never_costs_a_remedy(tmp_path):
    """The conjunct that keeps the recovery from papering over real failures.
    No PASS line means the tree is not what is broken, so nothing is rebuilt,
    nothing is removed, and the run fails on its first boot."""
    root, env, log = _scenario_fixture(tmp_path, WARN_ALWAYS, result='FAIL')
    done = _run_scenario(root, env)
    assert done.returncode == 1, done.stdout + done.stderr
    assert _engine_runs(log) == (1, 0), done.stdout + done.stderr
    assert REMOVAL_NOTICE not in done.stderr, done.stderr
    assert (root / STALE_MARKER).exists(), 'a failing scenario cost the cache'


def test_a_sweep_reports_the_removal_instead_of_doing_it_to_its_peers(tmp_path):
    """integration.sh runs N scenarios in ONE tree. Removing `.godot/` under
    peers that are mid-boot turns one cache defect into a scatter of failures
    that look like real ones — the read-side cardinal sin, manufactured by the
    recovery itself. Inside a sweep the run names the repair instead of
    performing it, and the tree it would not touch is still there."""
    root, env, log = _scenario_fixture(tmp_path, WARN_WHILE_STALE)
    done = subprocess.run(
        ['bash', 'tools/dev/runners/scenario.sh', 'alpha'], cwd=root,
        text=True, capture_output=True, env=dict(env, GDK_SCENARIO_IN_SWEEP='1'))
    assert done.returncode == 1, done.stdout + done.stderr
    assert _engine_runs(log) == (2, 1), done.stdout + done.stderr
    assert (root / STALE_MARKER).exists(), 'a sweep removed a shared cache'
    assert REMOVAL_NOTICE not in done.stderr, done.stderr
    assert 'rm -rf .godot' in done.stderr, done.stderr


# --- the fan-out: integration.sh CALLS scenario.sh --------------------------
INTEGRATION = INSTALLABLES / 'integration.sh'
# What the fan-out prints when every job came back 0. Both halves are asserted:
# the count, and that nothing was quietly dropped.
SWEEP_SUMMARY = '[INTEGRATION] SUMMARY: 2 passed, 0 failed (of 2)'


def _fanout_fixture(tmp_path: Path, mode: int) -> Path:
    """A repo holding integration.sh at its stock depth and a stand-in
    scenario runner at `mode`. No engine anywhere: the stand-in IS the
    scenario, so what is exercised is the one thing the fan-out owns — how it
    invokes the runner beside it."""
    runners = tmp_path / 'tools' / 'dev' / 'runners'
    runners.mkdir(parents=True)
    (tmp_path / 'project.godot').write_text('config_version=5\n', encoding='utf-8')
    shutil.copy2(INTEGRATION, runners / 'integration.sh')
    stub = runners / 'stub_scenario.sh'
    stub.write_text('#!/usr/bin/env bash\n'
                    'echo "[SCENARIO] $1 PASS"\n', encoding='utf-8')
    stub.chmod(mode)
    return runners / 'integration.sh'


@pytest.mark.parametrize('mode', [0o644, 0o755], ids=['no-exec-bit', 'executable'])
def test_the_fan_out_runs_a_scenario_runner_that_carries_no_exec_bit(tmp_path,
                                                                    mode):
    """MAJOR-1. `install-runners` wrote every runner -rw-r--r--, and this one
    caller exec'd `$SCENARIO_SH` directly — so every scenario on every
    `init`'d project came back 126 and `make smoke` / `integration` were red
    with an EMPTY diagnosis. The runner is invoked as `bash <path>`, which is
    the spelling Makefile.devkit and the install verb's next step both name,
    and it is what makes the sweep independent of a checkout's mode bits."""
    runner = _fanout_fixture(tmp_path, mode)
    done = subprocess.run(['bash', str(runner), 'alpha', 'beta'],
                          cwd=tmp_path, text=True, capture_output=True,
                          env={'PATH': '/usr/bin:/bin', 'GDK_JOBS': '2',
                               'GDK_SCENARIO_RUNNER': 'stub_scenario.sh'})
    assert done.returncode == 0, done.stdout + done.stderr
    assert SWEEP_SUMMARY in done.stdout, done.stdout
    assert 'Permission denied' not in done.stdout + done.stderr


def test_a_failing_scenario_with_no_summary_line_still_gets_a_diagnosis(tmp_path):
    """The other half of MAJOR-1: `Permission denied` matched nothing in
    FAILURE_SUMMARY_RE, so the FAILURES block printed the scenario name and
    then nothing at all. A transcript the summary patterns cannot read is the
    case a reader needs the MOST — the failures that never got far enough to
    report themselves."""
    runner = _fanout_fixture(tmp_path, 0o755)
    stub = runner.parent / 'stub_scenario.sh'
    stub.write_text('#!/usr/bin/env bash\n'
                    'echo "some engine noise nothing matches"\n'
                    'exit 1\n', encoding='utf-8')
    done = subprocess.run(['bash', str(runner), 'alpha'],
                          cwd=tmp_path, text=True, capture_output=True,
                          env={'PATH': '/usr/bin:/bin',
                               'GDK_SCENARIO_RUNNER': 'stub_scenario.sh'})
    assert done.returncode == 1, done.stdout + done.stderr
    assert '--- alpha ---' in done.stdout, done.stdout
    assert 'some engine noise nothing matches' in done.stdout, (
        'the FAILURES block named the scenario and said nothing about it')


def test_the_fan_out_tells_every_job_it_has_peers(tmp_path):
    """The sweep guard in scenario.sh is only as good as the one caller that
    sets the marker: a fan-out that forgot would have every job removing the
    `.godot` the others are booting in. Asserted through the REAL fan-out,
    because the marker lives inside a single-quoted xargs body — the place a
    plausible edit silently stops running (an apostrophe in a comment there
    ended the string and broke the whole sweep, once)."""
    runner = _fanout_fixture(tmp_path, 0o755)
    stub = runner.parent / 'stub_scenario.sh'
    stub.write_text('#!/usr/bin/env bash\n'
                    'echo "${GDK_SCENARIO_IN_SWEEP:-unset}" > "$PWD/sweep.txt"\n'
                    'echo "[SCENARIO] $1 PASS"\n', encoding='utf-8')
    done = subprocess.run(['bash', str(runner), 'alpha'], cwd=tmp_path,
                          text=True, capture_output=True,
                          env={'PATH': '/usr/bin:/bin',
                               'GDK_SCENARIO_RUNNER': 'stub_scenario.sh'})
    assert done.returncode == 0, done.stdout + done.stderr
    marker = tmp_path / 'sweep.txt'
    assert marker.exists(), done.stdout + done.stderr
    assert marker.read_text(encoding='utf-8').strip() == '1', marker.read_text()


@pytest.mark.skipif(shutil.which('shellcheck') is None,
                    reason='needs shellcheck')
def test_a_consumer_sourcing_the_library_shellchecks_clean(tmp_path):
    """A consumer's `shellcheck -x` follows the `source` and lints the library
    INLINE, so anything the library does to a name it also publishes lands as a
    finding in the consumer's file. The library's own self-test used to assign
    HOME, GDK_PROJECT_FILE and GDK_LOG_CAP_BYTES inside subshells, and every
    consumer script that later READ one of the three got SC2031 on a line its
    author wrote correctly — three sites in one adoption, each repaired with a
    local disable comment. The self-test scopes those values to a child process
    instead. This is the fixture that keeps it that way."""
    dev = tmp_path / 'tools' / 'dev'
    (dev / 'runners').mkdir(parents=True)
    shutil.copy2(LIBRARY, dev / 'gdk_runners.sh')
    consumer = dev / 'runners' / 'consumer.sh'
    consumer.write_text(
        '#!/usr/bin/env bash\n'
        'set -uo pipefail\n'
        '# shellcheck source=../gdk_runners.sh\n'
        'source "$(dirname "${BASH_SOURCE[0]}")/../gdk_runners.sh"\n'
        'gdk_sandbox_home\n'
        'echo "home $HOME cap $GDK_LOG_CAP_BYTES project $GDK_PROJECT_FILE"\n'
        'echo "engine $GDK_GODOT timeout $GDK_TIMEOUT"\n',
        encoding='utf-8')

    # cwd is the script's directory so `source=../gdk_runners.sh` resolves.
    done = subprocess.run(['shellcheck', '-x', consumer.name],
                          cwd=consumer.parent, text=True, capture_output=True)
    assert done.returncode == 0, done.stdout + done.stderr


@pytest.mark.skipif(shutil.which('shellcheck') is None,
                    reason='needs shellcheck')
@pytest.mark.parametrize('script', SCRIPTS, ids=lambda p: p.stem)
def test_every_shipped_runner_shellchecks_clean(script):
    """`shellcheck -x` on the installables themselves. They land in consumer
    trees whose own `check shell` gate runs over tools/ — a finding shipped
    from here reddens somebody else's commit gate."""
    done = subprocess.run(['shellcheck', '-x', script.name],
                          cwd=script.parent, text=True, capture_output=True)
    assert done.returncode == 0, done.stdout + done.stderr


# The two repos these runners were extracted FROM. A project name surviving in
# an installable is a fork wearing a library's name: the next consumer reads it
# as configuration it must match, and the fix that reaches one repo stops
# reaching the other. Word-bounded, so `trailing` is prose and `trail` is not.
CONSUMER_NAMES = (r'\bnullbound\b', r'\bNULLBOUND\b', r'\btrail\b', r'\bTRAIL\b')


@pytest.mark.parametrize('name', [name for name, _rel
                                  in install.PLANS['install-runners']],
                         ids=lambda n: n)
def test_no_installable_names_the_consumer_it_was_extracted_from(name):
    body = (INSTALLABLES / name).read_text(encoding='utf-8')
    hits = {pattern: [line for line in body.splitlines()
                      if re.search(pattern, line)]
            for pattern in CONSUMER_NAMES}
    assert not any(hits.values()), {k: v for k, v in hits.items() if v}


# --- the slice: --system is a DIRECTORY, --diff is what the change covers ----
# Two consumer bugs in one matcher. `--system <x>` matched a scenario NAME
# prefix: `--system threads` found nothing in tests/integration/threads/ (the
# files are thread_*.gd) and two agents in a row concluded the system had no
# coverage, while a typo'd prefix could quietly under-select. And a scenario
# declared nothing about what it covered, so the per-change gate was a guess
# (smoke) and the honest gate was the whole tier. The self-test corpus proves
# the pure functions; these prove the CLI end to end against a git repo and a
# stand-in scenario runner, booting nothing.
COVERS_HEADER = ('extends "res://tests/integration/scenario_base.gd"\n\n'
                 '## Boots because: tests/unit/alpha/test_alpha.gd cannot drive '
                 'the live flow.\n'
                 '## covers: systems/alpha\n\n'
                 'func run() -> void:\n\tpass\n')
UNDECLARED_BODY = 'extends "res://tests/integration/scenario_base.gd"\n\nfunc run() -> void:\n\tpass\n'
SLICE_ENV = {'PATH': '/usr/bin:/bin', 'GDK_JOBS': '2',
             'GDK_SCENARIO_RUNNER': 'stub_scenario.sh'}


def _slice_fixture(tmp_path: Path, git_root: Path | None = None) -> Path:
    """A git repo at the stock layout: a declared scenario in alpha/, an
    undeclared one in beta/, a directory holding only a capture tool, the
    smoke scenario, and the system the declared one covers — committed, so a
    diff against HEAD is empty until the test touches something.

    `git_root` puts the git toplevel ABOVE the project (a monorepo's game/);
    stock is the project root itself."""
    git_root = git_root or tmp_path
    tmp_path.mkdir(parents=True, exist_ok=True)
    runner = _fanout_fixture(tmp_path, 0o755)
    # The fan-out files each job's output under its own log, so the stand-in
    # records what it was asked to run where the test can read it.
    (runner.parent / 'stub_scenario.sh').write_text(
        '#!/usr/bin/env bash\n'
        f'echo "$1" >> "{tmp_path / "ran.txt"}"\n'
        'echo "[SCENARIO] $1 PASS"\n', encoding='utf-8')
    tier = tmp_path / 'tests' / 'integration'
    for rel, body in (('alpha/alpha_flow.gd', COVERS_HEADER),
                      ('beta/beta_flow.gd', UNDECLARED_BODY),
                      ('tools_only/eyes_capture.gd', UNDECLARED_BODY),
                      ('smoke.gd', UNDECLARED_BODY),
                      ('scenario_base.gd', 'extends Node\n')):
        (tier / rel).parent.mkdir(parents=True, exist_ok=True)
        (tier / rel).write_text(body, encoding='utf-8')
    (tmp_path / 'systems' / 'alpha').mkdir(parents=True)
    (tmp_path / 'systems' / 'alpha' / 'thing.gd').write_text('extends Node\n', encoding='utf-8')
    (tmp_path / 'tests' / 'support').mkdir()
    (tmp_path / 'tests' / 'support' / 'fixture.gd').write_text('extends Node\n', encoding='utf-8')
    git = ['git', '-c', 'user.name=t', '-c', 'user.email=t@t', '-c', 'commit.gpgsign=false']
    subprocess.run(['git', 'init', '-q'], cwd=git_root, check=True)
    subprocess.run(['git', 'add', '-A'], cwd=git_root, check=True)
    subprocess.run([*git, 'commit', '-q', '-m', 'fixture'], cwd=git_root, check=True)
    return runner


def _slice(runner: Path, *argv: str, env: dict | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(['bash', str(runner), *argv], cwd=runner.parents[3],
                          text=True, capture_output=True, env={**SLICE_ENV, **(env or {})})


def _ran(done: subprocess.CompletedProcess) -> set[str]:
    """What the stand-in runner was asked to boot — read from its own record,
    because the fan-out files every scenario's output under its own log."""
    root = Path(done.args[1]).parents[3]   # tools/dev/runners/<runner> -> the repo
    record = root / 'ran.txt'
    if not record.exists():
        return set()
    return set(record.read_text(encoding='utf-8').split())


def test_system_selects_the_directory_not_a_name_prefix(tmp_path):
    runner = _slice_fixture(tmp_path)
    done = _slice(runner, '--system', 'beta')
    assert done.returncode == 0, done.stdout + done.stderr
    assert _ran(done) == {'beta_flow'}, done.stdout


def test_a_name_prefix_that_is_not_a_directory_is_a_usage_error_naming_the_directories(tmp_path):
    """`--system alph` used to select alpha_flow by prefix; `--system thread`
    selected thread_*.gd out of threads/. A prefix is not a directory."""
    runner = _slice_fixture(tmp_path)
    done = _slice(runner, '--system', 'alph')
    assert done.returncode == 2, done.stdout + done.stderr
    assert _ran(done) == set(), 'a prefix selected scenarios'
    assert "no directory 'alph'" in done.stderr, done.stderr
    assert 'alpha' in done.stderr and 'beta' in done.stderr, done.stderr


def test_a_directory_holding_no_gate_is_a_FAIL_not_a_green_run_over_nothing(tmp_path):
    runner = _slice_fixture(tmp_path)
    done = _slice(runner, '--system', 'tools_only')
    assert done.returncode == 1, done.stdout + done.stderr
    assert 'EMPTY' in done.stderr, done.stderr
    assert '1 .gd file(s)' in done.stderr, done.stderr


@pytest.mark.parametrize('bad', ['', '..', '.', 'a/b', 'a\\b', '/abs', '*',
                                 'a b', '-x', 'a;b', 'a' * 65],
                         ids=['empty', 'dotdot', 'dot', 'slash', 'backslash',
                              'absolute', 'glob', 'space', 'dash', 'semicolon',
                              'over-long'])
def test_the_system_grammar_refuses_before_any_lookup(tmp_path, bad):
    runner = _slice_fixture(tmp_path)
    done = _slice(runner, '--system', bad)
    assert done.returncode == 2, done.stdout + done.stderr
    assert _ran(done) == set()


def test_a_clean_tree_slices_to_exactly_smoke(tmp_path):
    runner = _slice_fixture(tmp_path)
    done = _slice(runner, '--diff', 'HEAD')
    assert done.returncode == 0, done.stdout + done.stderr
    assert _ran(done) == {'smoke'}, done.stdout
    assert '0 touched path(s)' in done.stdout, done.stdout


def test_a_touched_covered_path_selects_the_declaring_scenario_plus_smoke(tmp_path):
    runner = _slice_fixture(tmp_path)
    (tmp_path / 'systems' / 'alpha' / 'thing.gd').write_text('extends Node2D\n', encoding='utf-8')
    done = _slice(runner, '--diff', 'HEAD')
    assert done.returncode == 0, done.stdout + done.stderr
    assert _ran(done) == {'alpha_flow', 'smoke'}, done.stdout
    # The undeclared scenario is REPORTED, not silently skipped — and not run.
    assert 'UNDECLARED: 2 scenario(s)' in done.stdout, done.stdout
    assert '    beta_flow' in done.stdout and '    smoke' in done.stdout, done.stdout
    assert done.stdout.strip().endswith(
        '(of 2); slice of 1 touched path(s), 2 undeclared scenario(s) ride only --all'), done.stdout


def test_a_diff_touching_several_paths_slices_by_every_one_of_them(tmp_path):
    """The shape a real change has: more than one path. BWK awk (macOS)
    refuses a newline inside a `-v` string, so a two-path list came back as
    an EMPTY slice reporting nothing undeclared — green over the wrong set."""
    runner = _slice_fixture(tmp_path)
    (tmp_path / 'systems' / 'alpha' / 'thing.gd').write_text('extends Node2D\n', encoding='utf-8')
    (tmp_path / 'README.md').write_text('# touched too\n', encoding='utf-8')
    (tmp_path / 'tests' / 'integration' / 'beta' / 'beta_flow.gd').write_text(
        UNDECLARED_BODY + '\n', encoding='utf-8')
    done = _slice(runner, '--diff', 'HEAD')
    assert done.returncode == 0, done.stdout + done.stderr
    assert _ran(done) == {'alpha_flow', 'beta_flow', 'smoke'}, done.stdout
    assert '3 touched path(s)' in done.stdout, done.stdout
    assert 'UNDECLARED: 2 scenario(s)' in done.stdout, done.stdout


def test_a_touched_path_outside_every_declaration_slices_to_smoke_alone(tmp_path):
    runner = _slice_fixture(tmp_path)
    (tmp_path / 'systems' / 'alphabet').mkdir()
    (tmp_path / 'systems' / 'alphabet' / 'x.gd').write_text('extends Node\n', encoding='utf-8')
    done = _slice(runner, '--diff', 'HEAD')
    assert done.returncode == 0, done.stdout + done.stderr
    assert _ran(done) == {'smoke'}, 'alphabet matched the prefix alpha'


def test_a_new_untracked_scenario_is_a_touched_scenario(tmp_path):
    runner = _slice_fixture(tmp_path)
    (tmp_path / 'tests' / 'integration' / 'beta' / 'beta_new.gd').write_text(
        UNDECLARED_BODY, encoding='utf-8')
    done = _slice(runner, '--diff', 'HEAD')
    assert done.returncode == 0, done.stdout + done.stderr
    assert _ran(done) == {'beta_new', 'smoke'}, done.stdout


def test_a_touched_piece_of_the_tiers_ground_selects_every_scenario(tmp_path):
    runner = _slice_fixture(tmp_path)
    (tmp_path / 'tests' / 'support' / 'fixture.gd').write_text('extends Node2D\n', encoding='utf-8')
    done = _slice(runner, '--diff', 'HEAD')
    assert done.returncode == 0, done.stdout + done.stderr
    assert _ran(done) == {'alpha_flow', 'beta_flow', 'smoke'}, done.stdout
    assert "the tier's own ground" in done.stdout, done.stdout
    assert 'eyes_capture' not in done.stdout, 'a capture TOOL boots in the whole-tier slice'


def test_a_ref_that_names_no_commit_is_a_usage_error(tmp_path):
    runner = _slice_fixture(tmp_path)
    done = _slice(runner, '--diff', 'no-such-ref')
    assert done.returncode == 2, done.stdout + done.stderr
    assert 'does not name a commit' in done.stderr, done.stderr
    assert _ran(done) == set()


@pytest.mark.parametrize('bad', ['', '-x', '--all', 'HEAD extra'],
                         ids=['empty', 'dash', 'flag', 'space'])
def test_the_ref_grammar_refuses_a_flag_or_whitespace(tmp_path, bad):
    runner = _slice_fixture(tmp_path)
    done = _slice(runner, '--diff', bad)
    assert done.returncode == 2, done.stdout + done.stderr
    assert _ran(done) == set()


def test_a_hostile_covers_entry_selects_nothing(tmp_path):
    """The gate refuses the declaration; the runner must still not act on it.
    An absolute or `..` entry compared as a prefix of a touched path can match
    nothing git reports — proven, not assumed."""
    runner = _slice_fixture(tmp_path)
    (tmp_path / 'tests' / 'integration' / 'alpha' / 'alpha_flow.gd').write_text(
        COVERS_HEADER.replace('## covers: systems/alpha',
                              '## covers: /systems, ../systems, systems/*, res://systems'),
        encoding='utf-8')
    git = ['git', '-c', 'user.name=t', '-c', 'user.email=t@t', '-c', 'commit.gpgsign=false']
    subprocess.run([*git, 'commit', '-q', '-am', 'hostile'], cwd=tmp_path, check=True)
    (tmp_path / 'systems' / 'alpha' / 'thing.gd').write_text('extends Node2D\n', encoding='utf-8')
    done = _slice(runner, '--diff', 'HEAD')
    assert done.returncode == 0, done.stdout + done.stderr
    assert _ran(done) == {'smoke'}, done.stdout
    assert '    alpha_flow' in done.stdout, 'a scenario whose every entry is refused is undeclared'


# --- the touched list is REPO_ROOT-relative and literal ----------------------
# `git diff --name-only` names a path relative to the git TOPLEVEL and C-quotes
# a non-ASCII one under core.quotePath (git's default), while a `## covers:`
# entry is REPO_ROOT-relative and literal. A Godot project below the toplevel
# (game/ in a monorepo) or a `café.gd` never matched anything, and `--diff`
# under-selected to smoke without a word.
def test_a_project_below_the_git_toplevel_slices_by_root_relative_paths(tmp_path):
    """game/ in a monorepo: git names the change `game/systems/alpha/thing.gd`;
    the scenario covers `systems/alpha`. A change OUTSIDE the project is not a
    touched path of the project — nothing repo-relative can name it."""
    project = tmp_path / 'game'
    runner = _slice_fixture(project, git_root=tmp_path)
    (project / 'systems' / 'alpha' / 'thing.gd').write_text('extends Node2D\n', encoding='utf-8')
    (tmp_path / 'README.md').write_text('# outside the project\n', encoding='utf-8')
    done = _slice(runner, '--diff', 'HEAD')
    assert done.returncode == 0, done.stdout + done.stderr
    assert _ran(done) == {'alpha_flow', 'smoke'}, done.stdout
    assert '1 touched path(s)' in done.stdout, done.stdout


def test_the_tiers_ground_is_ground_below_the_git_toplevel_too(tmp_path):
    """The substrate pattern is repo-relative as well; a toplevel-relative
    `game/tests/support/…` matched none of it and ran the wrong slice."""
    project = tmp_path / 'game'
    runner = _slice_fixture(project, git_root=tmp_path)
    (project / 'tests' / 'support' / 'fixture.gd').write_text('extends Node2D\n', encoding='utf-8')
    done = _slice(runner, '--diff', 'HEAD')
    assert done.returncode == 0, done.stdout + done.stderr
    assert _ran(done) == {'alpha_flow', 'beta_flow', 'smoke'}, done.stdout
    assert "the tier's own ground" in done.stdout, done.stdout


def test_a_non_ascii_path_is_compared_literally_not_c_quoted(tmp_path):
    """Under core.quotePath=true (git's default) `git diff --name-only` prints
    `"systems/alpha/caf\\303\\251.gd"` — quotes and octal — which is a prefix
    of nothing. The runner must ask git for the bytes."""
    runner = _slice_fixture(tmp_path)
    subprocess.run(['git', 'config', 'core.quotePath', 'true'], cwd=tmp_path, check=True)
    (tmp_path / 'systems' / 'alpha' / 'café.gd').write_text('extends Node\n', encoding='utf-8')
    done = _slice(runner, '--diff', 'HEAD')
    assert done.returncode == 0, done.stdout + done.stderr
    assert _ran(done) == {'alpha_flow', 'smoke'}, done.stdout
    assert '1 touched path(s)' in done.stdout, done.stdout


def test_a_doubled_slash_entry_is_undeclared_not_a_silent_never_match(tmp_path):
    """`## covers: systems/alpha//` — the gate normalised it away and passed;
    the runner dropped ONE slash and compared `systems/alpha/` as a prefix,
    which `systems/alpha/thing.gd` is not. The scenario was declared and
    never selected, and nothing said so. One grammar in both now: an empty
    segment is refused, so here it reads as UNDECLARED and is reported."""
    runner = _slice_fixture(tmp_path)
    (tmp_path / 'tests' / 'integration' / 'alpha' / 'alpha_flow.gd').write_text(
        COVERS_HEADER.replace('## covers: systems/alpha', '## covers: systems/alpha//'),
        encoding='utf-8')
    git = ['git', '-c', 'user.name=t', '-c', 'user.email=t@t', '-c', 'commit.gpgsign=false']
    subprocess.run([*git, 'commit', '-q', '-am', 'doubled'], cwd=tmp_path, check=True)
    (tmp_path / 'systems' / 'alpha' / 'thing.gd').write_text('extends Node2D\n', encoding='utf-8')
    done = _slice(runner, '--diff', 'HEAD')
    assert done.returncode == 0, done.stdout + done.stderr
    assert _ran(done) == {'smoke'}, done.stdout
    assert 'UNDECLARED: 3 scenario(s)' in done.stdout, done.stdout
    assert '    alpha_flow' in done.stdout, 'a doubled-slash entry read as a declaration that never matches'


# --- --list: the roster, owned here and read by the gate ---------------------
# `check test-shape` scanned `git ls-files` minus infra basenames while this
# runner discovers with find minus support/, the capture tools and its
# keep-list — two rosters, and the header rule was asked of files --diff can
# never slice to. The runner owns discovery (its config is in this file and in
# GDK_* env, where no TOML reader can see it), so it prints the roster and the
# gate asks.
ROSTER = {'tests/integration/alpha/alpha_flow.gd', 'tests/integration/beta/beta_flow.gd',
          'tests/integration/smoke.gd'}


def test_list_prints_the_roster_the_sweep_would_boot_and_boots_nothing(tmp_path):
    runner = _slice_fixture(tmp_path)
    done = _slice(runner, '--list')
    assert done.returncode == 0, done.stdout + done.stderr
    assert set(done.stdout.split('\n')) - {''} == ROSTER, done.stdout
    assert done.stdout.split('\n')[:-1] == sorted(ROSTER), 'the roster is sorted'
    assert _ran(done) == set(), 'listing the roster booted something'


def test_list_honours_the_runners_own_keep_list(tmp_path):
    runner = _slice_fixture(tmp_path)
    done = _slice(runner, '--list', env={'GDK_CAPTURE_GATE_RE': '^(eyes_capture)$'})
    assert done.returncode == 0, done.stdout + done.stderr
    assert set(done.stdout.split('\n')) - {''} == ROSTER | {'tests/integration/tools_only/eyes_capture.gd'}


def test_list_takes_no_argument(tmp_path):
    runner = _slice_fixture(tmp_path)
    done = _slice(runner, '--list', 'extra')
    assert done.returncode == 2, done.stdout + done.stderr
    assert _ran(done) == set()


def test_an_empty_roster_is_a_fail_naming_the_directory(tmp_path):
    runner = _slice_fixture(tmp_path)
    done = _slice(runner, '--list', env={'GDK_SCENARIO_SOURCE_DIR': 'tests/integration/tools_only'})
    assert done.returncode == 1, done.stdout + done.stderr
    assert 'EMPTY' in done.stderr and 'tests/integration/tools_only' in done.stderr, done.stderr
    assert done.stdout == ''
