"""test_runners_installable.py — the shell runners, RUN rather than read, and
the one verb that installs them.

Every shipped script carries a `--self-test` corpus, and that corpus is the
proof of everything a pure function can prove: the verdict line shape and its
VERBOSE stream, the report-dir guard's grammar, the `--system` / `--diff` /
`covers` grammars, the GUT totals parser, the argument surface. This file
fires each corpus once and MUTATES one to show a corpus can go red. The rest
is what no corpus reaches — the main flow that only runs through a spawned
runner against a stub engine (unit.sh's reconciliation, scenario.sh's
cold-cache ladder, integration.sh's fan-out and its slice against a git repo)
— and the install verb, in-process. Rule 9: each case is a branch nothing
cheaper reaches, proven at one altitude.

The runner's own boot path is deliberately NOT exercised: it needs Godot, and
this package never boots one (rule 2).
"""
from __future__ import annotations

import contextlib
import io
import os
import re
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from support import REPO_ROOT  # noqa: E402

from godot_devkit.core.project import load_config, repo_root  # noqa: E402
from godot_devkit.godot import install  # noqa: E402

pytestmark = pytest.mark.skipif(shutil.which('bash') is None,
                                reason='needs bash')

INSTALLABLES = REPO_ROOT / 'src' / 'godot_devkit' / 'godot' / 'installables'
LIBRARY = INSTALLABLES / 'gdk_runners.sh'
RUNNER = INSTALLABLES / 'import_cache.sh'
SCENARIO = INSTALLABLES / 'scenario.sh'
CAPTURE = INSTALLABLES / 'capture.sh'
UNIT = INSTALLABLES / 'unit.sh'
INTEGRATION = INSTALLABLES / 'integration.sh'
# Every shell RUNNER install-runners ships — the library and what lands under
# tools/dev/. A runner added to the plan and not here would be a runner nothing
# holds to the shape. The engine-boot guard ships on the same plan but is a
# Claude Code hook; tests/test_hooks_payloads.py is its matrix.
SCRIPTS = tuple(INSTALLABLES / name
                for name, rel in install.PLAN
                if name.endswith('.sh') and rel.startswith('tools/dev/'))
GIT = ['git', '-c', 'user.name=t', '-c', 'user.email=t@t', '-c', 'commit.gpgsign=false']
# The library BOUNDS every engine run and refuses outright without a timeout
# binary, and macOS ships neither `timeout` nor `gtimeout`; every stub engine
# below ships this beside it so the fixtures are hermetic.
TIMEOUT_STUB = '#!/usr/bin/env bash\nshift 2\nexec "$@"\n'


def run(*argv: str, cwd: Path | None = None) -> subprocess.CompletedProcess:
    # The installed CI exports VERBOSE=1 for the whole `make milestone` step,
    # and the quiet-by-default cases are asked of the DEFAULT — VERBOSE unset.
    env = {k: v for k, v in os.environ.items() if k != 'VERBOSE'}
    return subprocess.run(['bash', *argv], cwd=cwd, text=True,
                          capture_output=True, env=env)


# --- the corpora, fired ------------------------------------------------------
def test_every_corpus_passes_as_one_verdict_line_and_a_mutant_library_fails_its_own(tmp_path):
    """Each corpus is fired once, under an exported VERBOSE=1: the installed
    CI exports it for the whole `make milestone` step, and a corpus proves
    both settings on its own pinned cases — the value the caller exports is
    not one of them. The library's cap case once inherited it and streamed
    its eight bytes INTO the verdict line, which is what `make
    runners-self-test VERBOSE=1` then read as the verdict. So: exit 0, ONE
    line, the published shape, a count above zero. And the one argument row
    the corpora do not hold: an EMPTY argument is not "no argument" — it once
    passed off a downstream "library not found" as the argument check.
    Rule 4, applied to the corpus itself: a self-test that cannot go red is a
    false PASS with extra steps, so a MUTANT library — the verdict's em dash
    swapped for a hyphen, the one byte a consumer's grep would feel — runs
    beside the real ones and must fail on that case. Twelve processes, run at
    once and read in order: the slowest is the tier's wall clock."""
    mutant = tmp_path / 'gdk_runners.sh'
    mutant.write_text(
        LIBRARY.read_text(encoding='utf-8')
        .replace("'[%s] %s — full log: %s\\n'", "'[%s] %s - full log: %s\\n'"),
        encoding='utf-8')

    def fire(script: Path) -> subprocess.CompletedProcess:
        return subprocess.run(['bash', str(script), '--self-test'], text=True,
                              capture_output=True, env=dict(os.environ, VERBOSE='1'))
    with ThreadPoolExecutor(len(SCRIPTS) + 1) as pool:
        broken = pool.submit(fire, mutant)
        fired = list(pool.map(fire, SCRIPTS))
    for script, done in zip(SCRIPTS, fired):
        assert done.returncode == 0, f'{script.name}: {done.stdout}{done.stderr}'
        lines = done.stdout.splitlines()
        assert len(lines) == 1, f'{script.name}: {done.stdout}'
        assert re.match(r'^\[[A-Za-z][A-Za-z-]*\] SELF-TEST OK — \d+ case\(s\)$',
                        lines[0]), lines[0]
        count = lines[0].split('—')[1].split('case')[0].strip()
        assert int(count) > 0, f'{script.name}: a corpus of {count} cases proves nothing'
        done = run(str(script), '')
        assert done.returncode == 2, f'{script.name}: {done.stdout}{done.stderr}'
        assert '--help' in done.stdout + done.stderr, done.stdout + done.stderr
    done = broken.result()
    assert done.returncode == 1, done.stdout + done.stderr
    assert 'SELF-TEST FAIL' in done.stderr, done.stderr
    assert 'the verdict line shape' in done.stderr, done.stderr


# --- what a runner refuses BEFORE it touches the tree -----------------------
def _project(root: Path, *runners: Path, godot: bool = True) -> None:
    """`root` at the stock layout: the library, `runners` beside it, and a
    project.godot unless told otherwise."""
    (root / 'tools' / 'dev' / 'runners').mkdir(parents=True)
    shutil.copy2(LIBRARY, root / 'tools' / 'dev' / 'gdk_runners.sh')
    for runner in runners:
        shutil.copy2(runner, root / 'tools' / 'dev' / 'runners' / runner.name)
    if godot:
        (root / 'project.godot').write_text('config_version=5\n', encoding='utf-8')


def _stub_engine(tmp_path: Path, body: str) -> Path:
    """A `godot` on PATH that runs `body`, and the timeout beside it."""
    stub = tmp_path / 'bin'
    stub.mkdir()
    (stub / 'godot').write_text(body, encoding='utf-8')
    (stub / 'timeout').write_text(TIMEOUT_STUB, encoding='utf-8')
    for name in ('godot', 'timeout'):
        (stub / name).chmod(0o755)
    return stub


def test_the_runner_refuses_a_root_that_is_not_a_godot_project_and_admits_one(tmp_path):
    """MINOR-6. `REPO_ROOT_FROM_HERE` is a hardcoded depth: installed anywhere
    else it resolves to an arbitrary ancestor, and the run used to mint a
    sandbox there and boot `--path .` in it — reporting the failure as "the
    import pass hit the bound", which sends the reader to raise a timeout that
    was never the problem. It refuses BEFORE minting anything. The other half:
    a repo it was installed into correctly gets past the guard — with a stub
    `godot` that writes nothing the run reaches its own outcome check and
    fails THERE (exit 1), a different verdict, which is the point."""
    root = tmp_path / 'repo'
    _project(root, RUNNER, godot=False)
    done = subprocess.run(['bash', 'tools/dev/runners/import_cache.sh'], cwd=root,
                          text=True, capture_output=True, env={'PATH': '/usr/bin:/bin'})
    assert done.returncode == 2, done.stdout + done.stderr
    assert 'not a Godot project' in done.stderr, done.stderr
    assert 'REPO_ROOT_FROM_HERE' in done.stderr, done.stderr
    assert not (root / '.headless-userdata').exists()

    (root / 'project.godot').write_text('config_version=5\n', encoding='utf-8')
    stub = _stub_engine(tmp_path, '#!/bin/sh\nexit 0\n')
    done = subprocess.run(['bash', 'tools/dev/runners/import_cache.sh'], cwd=root,
                          text=True, capture_output=True,
                          env={'PATH': f'{stub}:/usr/bin:/bin'})
    assert done.returncode == 1, done.stdout + done.stderr
    assert 'not a Godot project' not in done.stderr, done.stderr
    assert 'did not refresh the cache' in done.stdout, done.stdout


def test_a_mis_set_report_dir_is_refused_before_anything_is_removed(tmp_path):
    """MINOR-1. `scenario.sh` reaps entries out of GDK_SCENARIO_REPORT_DIR and
    `capture.sh` `rm -rf`s GDK_CAPTURE_REPORT_DIR whole, and both took the
    name on trust: `GDK_SCENARIO_REPORT_DIR=.` deleted a probe repo — `.git`
    included — BEFORE the boot. The guard's grammar is the library's corpus
    (`gdk_report_dir_defect`); this is each runner CALLING it before the rm,
    and not refusing the stock dir every consumer runs (with no engine the
    stock run fails LATER and differently)."""
    for variable, runner in (('GDK_SCENARIO_REPORT_DIR', SCENARIO),
                             ('GDK_CAPTURE_REPORT_DIR', CAPTURE)):
        root = tmp_path / runner.stem
        _project(root, runner)
        (root / 'tests').mkdir()
        (root / 'tests' / 'keep.gd').write_text('extends Node\n', encoding='utf-8')
        subprocess.run(['git', 'init', '-q'], cwd=root, check=True)
        subprocess.run(['git', 'add', '-A'], cwd=root, check=True, capture_output=True)
        before = {p.relative_to(root).as_posix() for p in root.rglob('*')}
        env = {'PATH': '/usr/bin:/bin', 'HOME': str(tmp_path / 'home')}
        done = subprocess.run(['bash', f'tools/dev/runners/{runner.name}', 'smoke'],
                              cwd=root, text=True, capture_output=True,
                              env={**env, variable: '.'})
        after = {p.relative_to(root).as_posix() for p in root.rglob('*')}
        assert done.returncode == 2, f'{runner.name}: {done.stdout}{done.stderr}'
        assert variable in done.stderr, done.stderr
        assert after == before, f'the refusal still touched the tree: {before ^ after}'
        done = subprocess.run(['bash', f'tools/dev/runners/{runner.name}', 'smoke'],
                              cwd=root, text=True, capture_output=True, env=env)
        assert 'REPORT_DIR' not in done.stderr, f'{runner.name}: {done.stderr}'


# --- unit.sh's coverage gate, driven through the RUNNER ----------------------
# The gate framework's library as this repo's pin installed it: the one a
# consumer's `install-gates` puts beside gdk_runners.sh, and the owner of the
# ledger row. Its recorder is GDK_LEDGER_CMD, stood in for by a script that
# writes down what it was asked to file.
GATE_LIB = REPO_ROOT / 'tools' / 'dev' / 'gdk_gate.sh'
ROW = re.compile(r'^pm ledger record --gate (\S+) --verdict (\S+) '
                 r'--duration-ms \d+(?: --census (\d+))?$')


def _recorder(tmp_path: Path, ledger: Path) -> Path:
    recorder = tmp_path / 'recorder.sh'
    recorder.write_text(f'printf "%s\\n" "$*" >> "{ledger}"\n', encoding='utf-8')
    return recorder


def _rows(ledger: Path) -> list[tuple[str, str, str]]:
    """(gate, verdict, census) per filed row; a line of any other shape fails."""
    lines = ledger.read_text(encoding='utf-8').splitlines() if ledger.exists() else []
    rows = [ROW.match(line) for line in lines]
    assert all(rows), lines
    return [(m.group(1), m.group(2), m.group(3) or '') for m in rows]


GUT_TRANSCRIPT = ('#!/usr/bin/env bash\n'
                  'echo "Running tests..."\n'
                  'echo "Totals"\n'
                  'echo "Scripts        {scripts}"\n'
                  'echo "Tests          {scripts}"\n'
                  'exit 0\n')


def test_unit_passes_a_reconciled_census_and_fails_a_mismatch_or_an_empty_one(tmp_path):
    """The self-test corpus proves the two parsers. The BRANCH that reconciles
    them is main-flow, and nothing exercised it: a mutant deleting the
    count-mismatch check survived the whole suite (MINOR-6b — GUT drops a
    script that will not parse from its totals and prints "All tests
    passed!"), and `DISK_SCRIPTS=0` reconciled with GUT's unconditional
    `Scripts 0` into `PASS (0/0 scripts loaded - full coverage)` (MAJOR-2,
    rule 4's sin on the tier a consumer slices by hand every day). A stub
    prints the GUT transcript and unit.sh does everything else for real; the
    reconciled run is the control the two failures are measured against.

    #7/#8, on the same three runs: each files ONE ledger row through the
    gate framework's own library (the pin's gdk_gate.sh, beside the runner
    library where `install-gates` puts it) with the outcome the runner NAMED
    and GUT's test count as the census. The mismatch is the case that bites:
    GUT exits 0 there, so a verdict read off the exit code would file PASS."""
    root = tmp_path / 'repo'
    _project(root, UNIT)
    shutil.copy2(GATE_LIB, root / 'tools' / 'dev' / 'gdk_gate.sh')
    tier = root / 'tests' / 'unit' / 'stats'
    tier.mkdir(parents=True)
    for index in range(2):
        (tier / f'test_{index}.gd').write_text('', encoding='utf-8')
    stub = _stub_engine(tmp_path, GUT_TRANSCRIPT.format(scripts=2))
    ledger = tmp_path / 'ledger.txt'
    env = {'PATH': f'{stub}:/usr/bin:/bin:{Path(sys.executable).parent}',
           'HOME': str(tmp_path / 'home'),
           'GDK_LEDGER_CMD': f'bash {_recorder(tmp_path, ledger)}'}

    def unit(*argv: str) -> subprocess.CompletedProcess:
        return subprocess.run(['bash', 'tools/dev/runners/unit.sh', *argv], cwd=root,
                              text=True, capture_output=True, env=env)

    done = unit()
    assert done.returncode == 0, done.stdout + done.stderr
    assert '[UNIT] PASS (2/2 scripts loaded' in done.stdout.splitlines()[-1], done.stdout
    assert _rows(ledger) == [('unit', 'PASS', '2')], done.stderr

    (tier / 'test_2.gd').write_text('', encoding='utf-8')
    done = unit()
    assert done.returncode == 1, done.stdout + done.stderr
    assert '3 test script(s) on disk, 2 run' in done.stdout, done.stdout
    assert 'COVERAGE FAIL (script count mismatch)' in done.stdout, done.stdout
    assert _rows(ledger)[1:] == [('unit', 'FAIL', '2')], done.stderr

    (stub / 'godot').write_text(GUT_TRANSCRIPT.format(scripts=0), encoding='utf-8')
    done = unit('typo')
    assert done.returncode == 1, done.stdout + done.stderr
    assert 'full coverage' not in done.stdout, done.stdout
    assert 'COVERAGE FAIL (0 test scripts found)' in done.stdout, done.stdout
    # It names the DIRECTORY it scanned: the repair is one of two spellings
    # and a verdict that does not name it chooses neither.
    assert 'tests/unit/typo' in done.stdout, done.stdout
    assert [row[1] for row in _rows(ledger)] == ['PASS', 'FAIL', 'FAIL'], _rows(ledger)


# --- scenario.sh's cold-cache recovery, driven through the RUNNER ------------
# 0.24.0/bugs/import-cache-rebuild-does-not-repair-a-stale-uid-index. In a
# consumer, 147 of 147 scenarios FAILED on the `invalid UID … using text path
# instead` sweep while every one of them printed its own PASS line. The
# recovery detected the class precisely and then applied a remedy that cannot
# work: an import pass against an EXISTING .godot/ does not rebuild the uid
# index for tracked files already missing from it; `rm -rf .godot` then a
# rebuild does. The stub below IS that distinction: its rebuild branch
# rewrites the cache file and leaves `.godot/stale` alone, so only a run that
# REMOVES the directory can clear it. Nothing here boots an engine.
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
    _project(root, SCENARIO)
    (root / 'tests' / 'integration').mkdir(parents=True)
    (root / 'tests' / 'integration' / 'alpha.gd').write_text('extends Node\n',
                                                             encoding='utf-8')
    (root / '.godot').mkdir()
    (root / '.godot' / 'uid_cache.bin').write_text('', encoding='utf-8')
    (root / STALE_MARKER).write_text('56 tracked sidecars missing\n',
                                     encoding='utf-8')
    stub = _stub_engine(tmp_path, SCENARIO_STUB.format(warn=warn, result=result))
    log = tmp_path / 'stub.log'
    log.write_text('', encoding='utf-8')
    env = {'PATH': f'{stub}:/usr/bin:/bin', 'HOME': str(tmp_path / 'home'),
           'GDK_STUB_LOG': str(log)}
    return root, env, log


def _run_scenario(root: Path, env: dict) -> subprocess.CompletedProcess:
    return subprocess.run(['bash', 'tools/dev/runners/scenario.sh', 'alpha'],
                          cwd=root, text=True, capture_output=True, env=env)


def _engine_runs(log: Path) -> tuple[int, int]:
    """(boots, rebuilds) — every engine invocation the run actually made."""
    lines = log.read_text(encoding='utf-8').split()
    return lines.count('boot'), lines.count('rebuild')


def test_a_stale_uid_index_survives_the_rebuild_and_the_run_removes_the_cache(tmp_path):
    """The bug, end to end. Rung 1 rebuilds and changes nothing; rung 2 removes
    `.godot/` and rebuilds, and the third boot is clean. Before the escalation
    the run stopped after rung 1 and reported FAIL over a scenario that had
    passed twice. `rm -rf .godot` throws away a local editor's state, so it is
    announced — once."""
    root, env, log = _scenario_fixture(tmp_path, WARN_WHILE_STALE)
    done = _run_scenario(root, env)
    assert done.returncode == 0, done.stdout + done.stderr
    assert '[SCENARIO] alpha PASS' in done.stdout, done.stdout
    assert _engine_runs(log) == (3, 2), done.stdout + done.stderr
    assert not (root / STALE_MARKER).exists(), 'the stale index was left in place'
    assert done.stderr.count(REMOVAL_NOTICE) == 1, done.stderr


def test_the_escalation_is_bounded_at_two_remedies_and_the_third_failure_is_final(tmp_path):
    """A tree neither remedy repairs must cost exactly two remedies. The ladder
    is straight-line code, never a loop — a retry re-evaluating its own
    condition would boot the engine forever on a tree that is really broken.
    Announced once, and the failure that followed did not un-announce it."""
    root, env, log = _scenario_fixture(tmp_path, WARN_ALWAYS)
    done = _run_scenario(root, env)
    assert done.returncode == 1, done.stdout + done.stderr
    assert _engine_runs(log) == (3, 2), done.stdout + done.stderr
    assert 'FAIL — engine-level errors' in done.stdout, done.stdout
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
    done = _run_scenario(root, dict(env, GDK_SCENARIO_IN_SWEEP='1'))
    assert done.returncode == 1, done.stdout + done.stderr
    assert _engine_runs(log) == (2, 1), done.stdout + done.stderr
    assert (root / STALE_MARKER).exists(), 'a sweep removed a shared cache'
    assert REMOVAL_NOTICE not in done.stderr, done.stderr
    assert 'rm -rf .godot' in done.stderr, done.stderr


# --- the fan-out: integration.sh CALLS scenario.sh --------------------------
# What the fan-out prints when every job came back 0. Both halves are asserted:
# the count, and that nothing was quietly dropped.
SWEEP_SUMMARY = '[INTEGRATION] SUMMARY: 2 passed, 0 failed (of 2)'
FANOUT_ENV = {'PATH': '/usr/bin:/bin', 'GDK_JOBS': '2',
              'GDK_SCENARIO_RUNNER': 'stub_scenario.sh'}


def _fanout_fixture(tmp_path: Path, stub_body: str, mode: int = 0o755) -> Path:
    """A repo holding integration.sh at its stock depth and a stand-in
    scenario runner at `mode`. No engine anywhere: the stand-in IS the
    scenario, so what is exercised is the one thing the fan-out owns — how it
    invokes the runner beside it."""
    runners = tmp_path / 'tools' / 'dev' / 'runners'
    runners.mkdir(parents=True)
    (tmp_path / 'project.godot').write_text('config_version=5\n', encoding='utf-8')
    shutil.copy2(INTEGRATION, runners / 'integration.sh')
    stub = runners / 'stub_scenario.sh'
    stub.write_text('#!/usr/bin/env bash\n' + stub_body, encoding='utf-8')
    stub.chmod(mode)
    return runners / 'integration.sh'


def test_the_fan_out_runs_a_runner_with_no_exec_bit_and_tells_every_job_it_has_peers(tmp_path):
    """MAJOR-1. `install-runners` wrote every runner -rw-r--r--, and this one
    caller exec'd `$SCENARIO_SH` directly — so every scenario on every
    `init`'d project came back 126. The runner is invoked as `bash <path>`,
    which is what makes the sweep independent of a checkout's mode bits. And
    the sweep guard in scenario.sh is only as good as the one caller that
    sets the marker: asserted through the REAL fan-out, because the marker
    lives inside a single-quoted xargs body — the place a plausible edit
    silently stops running (an apostrophe in a comment there ended the string
    and broke the whole sweep, once).

    #8, on the same sweep: the run reports its BOOTS — one per scenario file,
    the tier's real cost unit — and the census command the installed
    Makefile.tiers passes `gdk_gate` reads that count back off the transcript,
    so the `gate` row `[tests] cases` grades carries it."""
    runner = _fanout_fixture(
        tmp_path, 'echo "${GDK_SCENARIO_IN_SWEEP:-unset}" > "$PWD/sweep.txt"\n'
                  'echo "[SCENARIO] $1 PASS"\n', mode=0o644)
    done = subprocess.run(['bash', str(runner), 'alpha', 'beta'], cwd=tmp_path,
                          text=True, capture_output=True, env=FANOUT_ENV)
    assert done.returncode == 0, done.stdout + done.stderr
    assert done.stdout.splitlines()[-1] == SWEEP_SUMMARY, done.stdout
    assert 'Permission denied' not in done.stdout + done.stderr
    marker = tmp_path / 'sweep.txt'
    assert marker.exists(), done.stdout + done.stderr
    assert marker.read_text(encoding='utf-8').strip() == '1', marker.read_text()
    assert re.search(r'^\[INTEGRATION\] BOOTS: 2 scenario\(s\) booted, \d+\.\ds CPU, '
                     r'\d+\.\d\ds per boot$', done.stdout, re.M), done.stdout
    census = re.search(r'^GDK_CENSUS_BOOTS := (.*)$', install.body_of('Makefile.tiers'), re.M)
    assert census, 'Makefile.tiers no longer declares the scenario tiers\' census'
    log = tmp_path / 'integration.log'
    log.write_text(done.stdout, encoding='utf-8')
    read = subprocess.run(['bash', '-c', 'log="$1"; ' + census.group(1).replace('$$', '$'),
                           '_', str(log)], text=True, capture_output=True)
    assert read.stdout == '2\n', read.stdout + read.stderr


def test_a_failing_scenario_with_no_summary_line_still_gets_a_diagnosis(tmp_path):
    """The other half of MAJOR-1: `Permission denied` matched nothing in
    FAILURE_SUMMARY_RE, so the FAILURES block printed the scenario name and
    then nothing at all. A transcript the summary patterns cannot read is the
    case a reader needs the MOST."""
    runner = _fanout_fixture(tmp_path, 'echo "some engine noise nothing matches"\nexit 1\n')
    done = subprocess.run(['bash', str(runner), 'alpha'], cwd=tmp_path,
                          text=True, capture_output=True, env=FANOUT_ENV)
    assert done.returncode == 1, done.stdout + done.stderr
    assert '--- alpha ---' in done.stdout, done.stdout
    assert 'some engine noise nothing matches' in done.stdout, (
        'the FAILURES block named the scenario and said nothing about it')


@pytest.mark.skipif(shutil.which('shellcheck') is None, reason='needs shellcheck')
def test_every_shipped_runner_and_a_consumer_sourcing_the_library_shellcheck_clean(tmp_path):
    """`shellcheck -x` on the installables: they land in consumer trees whose
    own shell gate runs over tools/ (this repo's `check shell` scans tools/,
    not src/), so a finding shipped from here reddens somebody else's commit
    gate. And a consumer's `-x` follows the `source` and lints the library
    INLINE: the self-test once assigned HOME, GDK_PROJECT_FILE and
    GDK_LOG_CAP_BYTES inside subshells, and every consumer script that later
    READ one of the three got SC2031 on a line its author wrote correctly."""
    def lint(script: Path) -> subprocess.CompletedProcess:
        return subprocess.run(['shellcheck', '-x', script.name], cwd=script.parent,
                              text=True, capture_output=True)
    with ThreadPoolExecutor(len(SCRIPTS)) as pool:
        for script, done in zip(SCRIPTS, pool.map(lint, SCRIPTS)):
            assert done.returncode == 0, f'{script.name}: {done.stdout}{done.stderr}'
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
    done = subprocess.run(['shellcheck', '-x', consumer.name], cwd=consumer.parent,
                          text=True, capture_output=True)
    assert done.returncode == 0, done.stdout + done.stderr


# --- the slice: --system is a DIRECTORY, --diff is what the change covers ----
# The self-test corpus proves the pure functions (the three grammars, the
# multi-path awk). These prove the CLI end to end against a git repo and a
# stand-in scenario runner, booting nothing.
COVERS_HEADER = ('extends "res://tests/integration/scenario_base.gd"\n\n'
                 '## Boots because: tests/unit/alpha/test_alpha.gd cannot drive '
                 'the live flow.\n'
                 '## covers: systems/alpha\n\n'
                 'func run() -> void:\n\tpass\n')
UNDECLARED_BODY = 'extends "res://tests/integration/scenario_base.gd"\n\nfunc run() -> void:\n\tpass\n'
ROSTER = {'tests/integration/alpha/alpha_flow.gd', 'tests/integration/beta/beta_flow.gd',
          'tests/integration/smoke.gd'}


def _slice_fixture(tmp_path: Path, git_root: Path | None = None) -> Path:
    """A git repo at the stock layout: a declared scenario in alpha/, an
    undeclared one in beta/, a directory holding only a capture tool, the
    smoke scenario, and the system the declared one covers — committed, so a
    diff against HEAD is empty until the test touches something.

    `git_root` puts the git toplevel ABOVE the project (a monorepo's game/);
    stock is the project root itself."""
    git_root = git_root or tmp_path
    tmp_path.mkdir(parents=True, exist_ok=True)
    # The fan-out files each job's output under its own log, so the stand-in
    # records what it was asked to run where the test can read it.
    runner = _fanout_fixture(
        tmp_path, f'echo "$1" >> "{tmp_path / "ran.txt"}"\necho "[SCENARIO] $1 PASS"\n')
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
    subprocess.run(['git', 'init', '-q'], cwd=git_root, check=True)
    subprocess.run(['git', 'add', '-A'], cwd=git_root, check=True)
    subprocess.run([*GIT, 'commit', '-q', '-m', 'fixture'], cwd=git_root, check=True)
    return runner


def _slice(runner: Path, *argv: str, env: dict | None = None) -> subprocess.CompletedProcess:
    root = runner.parents[3]
    record = root / 'ran.txt'
    if record.exists():
        record.unlink()
    return subprocess.run(['bash', str(runner), *argv], cwd=root, text=True,
                          capture_output=True, env={**FANOUT_ENV, **(env or {})})


def _ran(done: subprocess.CompletedProcess) -> set[str]:
    """What the stand-in runner was asked to boot on THIS run — read from its
    own record, because the fan-out files every scenario's output under its
    own log."""
    record = Path(done.args[1]).parents[3] / 'ran.txt'
    if not record.exists():
        return set()
    return set(record.read_text(encoding='utf-8').split())


def _touch(path: Path, body: str = 'extends Node2D\n') -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding='utf-8')


def test_system_selects_the_directory_and_a_prefix_or_a_bad_ref_is_a_usage_error(tmp_path):
    """`--system <x>` once matched a scenario NAME prefix: `--system threads`
    found nothing in tests/integration/threads/ (the files are thread_*.gd)
    and two agents in a row concluded the system had no coverage, while a
    typo'd prefix could quietly under-select. A prefix is not a directory,
    and the refusal names the directories that exist. A ref naming no commit
    is refused the same way: nothing boots on a usage error."""
    runner = _slice_fixture(tmp_path)
    done = _slice(runner, '--system', 'beta')
    assert done.returncode == 0, done.stdout + done.stderr
    assert _ran(done) == {'beta_flow'}, done.stdout
    done = _slice(runner, '--system', 'alph')
    assert done.returncode == 2, done.stdout + done.stderr
    assert _ran(done) == set(), 'a prefix selected scenarios'
    assert "no directory 'alph'" in done.stderr, done.stderr
    assert 'alpha' in done.stderr and 'beta' in done.stderr, done.stderr
    done = _slice(runner, '--diff', 'no-such-ref')
    assert done.returncode == 2, done.stdout + done.stderr
    assert 'does not name a commit' in done.stderr, done.stderr
    assert _ran(done) == set()


def test_a_directory_holding_no_gate_is_a_FAIL_not_a_green_run_over_nothing(tmp_path):
    runner = _slice_fixture(tmp_path)
    done = _slice(runner, '--system', 'tools_only')
    assert done.returncode == 1, done.stdout + done.stderr
    assert 'EMPTY' in done.stderr, done.stderr
    assert '1 .gd file(s)' in done.stderr, done.stderr


def test_diff_slices_a_clean_tree_to_smoke_and_a_change_by_every_touched_path(tmp_path):
    """Three trees, one fixture. Clean: exactly smoke, which is what
    `precommit` runs on a clean tree. A touched path OUTSIDE every
    declaration: smoke alone — `systems/alphabet` is not under the prefix
    `systems/alpha`. Then the shape a real change has: several paths (BWK awk
    on macOS refuses a newline inside a `-v` string, so a two-path list once
    came back as an EMPTY slice reporting nothing undeclared — green over the
    wrong set), a touched undeclared scenario, and a NEW untracked one; every
    one of them runs, and the undeclared are REPORTED, not silently skipped."""
    runner = _slice_fixture(tmp_path)
    done = _slice(runner, '--diff', 'HEAD')
    assert done.returncode == 0, done.stdout + done.stderr
    assert _ran(done) == {'smoke'}, done.stdout
    assert '0 touched path(s)' in done.stdout, done.stdout

    _touch(tmp_path / 'systems' / 'alphabet' / 'x.gd')
    done = _slice(runner, '--diff', 'HEAD')
    assert done.returncode == 0, done.stdout + done.stderr
    assert _ran(done) == {'smoke'}, 'alphabet matched the prefix alpha'

    _touch(tmp_path / 'systems' / 'alpha' / 'thing.gd')
    _touch(tmp_path / 'README.md', '# touched too\n')
    _touch(tmp_path / 'tests' / 'integration' / 'beta' / 'beta_flow.gd', UNDECLARED_BODY + '\n')
    _touch(tmp_path / 'tests' / 'integration' / 'beta' / 'beta_new.gd', UNDECLARED_BODY)
    done = _slice(runner, '--diff', 'HEAD')
    assert done.returncode == 0, done.stdout + done.stderr
    assert _ran(done) == {'alpha_flow', 'beta_flow', 'beta_new', 'smoke'}, done.stdout
    assert '5 touched path(s)' in done.stdout, done.stdout
    assert 'UNDECLARED: 3 scenario(s)' in done.stdout, done.stdout
    assert '    beta_flow' in done.stdout and '    smoke' in done.stdout, done.stdout
    assert done.stdout.strip().endswith(
        '(of 4); slice of 5 touched path(s), 3 undeclared scenario(s) ride only --all'), done.stdout


def test_a_touched_piece_of_the_tiers_ground_selects_every_scenario(tmp_path):
    runner = _slice_fixture(tmp_path)
    _touch(tmp_path / 'tests' / 'support' / 'fixture.gd')
    done = _slice(runner, '--diff', 'HEAD')
    assert done.returncode == 0, done.stdout + done.stderr
    assert _ran(done) == {'alpha_flow', 'beta_flow', 'smoke'}, done.stdout
    assert "the tier's own ground" in done.stdout, done.stdout
    assert 'eyes_capture' not in done.stdout, 'a capture TOOL boots in the whole-tier slice'


def test_a_hostile_or_doubled_slash_covers_entry_selects_nothing_and_reads_as_undeclared(tmp_path):
    """The gate refuses the declaration; the runner must still not act on it.
    An absolute, `..`, glob or `res://` entry compared as a prefix of a touched
    path can match nothing git reports — proven, not assumed. And
    `systems/alpha//`: the gate once normalised it away and passed while the
    runner dropped ONE slash and compared `systems/alpha/` as a prefix, which
    `systems/alpha/thing.gd` is not — declared, never selected, and nothing
    said so. One grammar in both now: an empty segment is refused, so every
    one of these reads as UNDECLARED and is reported."""
    runner = _slice_fixture(tmp_path)
    _touch(tmp_path / 'tests' / 'integration' / 'alpha' / 'alpha_flow.gd',
           COVERS_HEADER.replace(
               '## covers: systems/alpha',
               '## covers: /systems, ../systems, systems/*, res://systems, systems/alpha//'))
    subprocess.run([*GIT, 'commit', '-q', '-am', 'hostile'], cwd=tmp_path, check=True)
    _touch(tmp_path / 'systems' / 'alpha' / 'thing.gd')
    done = _slice(runner, '--diff', 'HEAD')
    assert done.returncode == 0, done.stdout + done.stderr
    assert _ran(done) == {'smoke'}, done.stdout
    assert 'UNDECLARED: 3 scenario(s)' in done.stdout, done.stdout
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
    _touch(project / 'systems' / 'alpha' / 'thing.gd')
    _touch(tmp_path / 'README.md', '# outside the project\n')
    done = _slice(runner, '--diff', 'HEAD')
    assert done.returncode == 0, done.stdout + done.stderr
    assert _ran(done) == {'alpha_flow', 'smoke'}, done.stdout
    assert '1 touched path(s)' in done.stdout, done.stdout


def test_a_non_ascii_path_is_compared_literally_not_c_quoted(tmp_path):
    """Under core.quotePath=true (git's default) `git diff --name-only` prints
    `"systems/alpha/caf\\303\\251.gd"` — quotes and octal — which is a prefix
    of nothing. The runner must ask git for the bytes."""
    runner = _slice_fixture(tmp_path)
    subprocess.run(['git', 'config', 'core.quotePath', 'true'], cwd=tmp_path, check=True)
    _touch(tmp_path / 'systems' / 'alpha' / 'café.gd', 'extends Node\n')
    done = _slice(runner, '--diff', 'HEAD')
    assert done.returncode == 0, done.stdout + done.stderr
    assert _ran(done) == {'alpha_flow', 'smoke'}, done.stdout
    assert '1 touched path(s)' in done.stdout, done.stdout


def test_list_prints_the_sorted_roster_honours_the_keep_list_and_fails_on_an_empty_one(tmp_path):
    """`check test-shape` once scanned `git ls-files` minus infra basenames
    while this runner discovers with find minus support/, the capture tools
    and its keep-list — two rosters, and the header rule was asked of files
    --diff can never slice to. The runner owns discovery (its config is in
    this file and in GDK_* env, where no TOML reader can see it), so it prints
    the roster and the gate asks. A roster of ZERO is a FAIL naming the
    directory, never an empty page (rule 4)."""
    runner = _slice_fixture(tmp_path)
    done = _slice(runner, '--list')
    assert done.returncode == 0, done.stdout + done.stderr
    assert done.stdout.split('\n')[:-1] == sorted(ROSTER), done.stdout
    assert _ran(done) == set(), 'listing the roster booted something'
    done = _slice(runner, '--list', env={'GDK_CAPTURE_GATE_RE': '^(eyes_capture)$'})
    assert done.returncode == 0, done.stdout + done.stderr
    assert set(done.stdout.split('\n')) - {''} == ROSTER | {'tests/integration/tools_only/eyes_capture.gd'}
    done = _slice(runner, '--list', env={'GDK_SCENARIO_SOURCE_DIR': 'tests/integration/tools_only'})
    assert done.returncode == 1, done.stdout + done.stderr
    assert 'EMPTY' in done.stderr and 'tests/integration/tools_only' in done.stderr, done.stderr
    assert done.stdout == ''


# --- the install verb: whole-file writes, once ---------------------------------
# The verb's contract is the one every installer this package ever shipped
# had: write each file once, refuse a differing destination by name (`--force`
# replaces it whole), `--diff` prints and writes nothing, a second run is a
# no-op, every `.sh` lands executable. tests/fixtures/agentic_sdlc/
# Makefile.devkit is agentic-sdlc v0.2.0's `install-gates` output, VENDORED
# (rule 8): the include the written tier file composes under, held here so the
# composition is proven on every machine and never against a neighbouring
# checkout.
INCLUDE = REPO_ROOT / 'tests' / 'fixtures' / 'agentic_sdlc' / 'Makefile.devkit'
CONSUMER_MAKEFILE = ('DEVKIT_VERSION := v0.2.0\n'
                     'GODOT_DEVKIT_VERSION := v0.25.0\n'
                     'include Makefile.devkit\n')
# The roster, by destination — pinned rather than read off the plan, because a
# file dropped from the plan is a file a consumer silently stops getting.
DESTINATIONS = {
    'tools/dev/gdk_runners.sh',
    'tools/dev/runners/import_cache.sh', 'tools/dev/runners/parse.sh',
    'tools/dev/runners/compile_sweep.gd', 'tools/dev/runners/compile_sweep.gd.uid',
    'tools/dev/runners/lint.sh', 'tools/dev/runners/warnings.sh',
    'tools/dev/runners/unit.sh', 'tools/dev/runners/scenario.sh',
    'tools/dev/runners/integration.sh', 'tools/dev/runners/capture.sh',
    'tools/dev/runners/hermetic_run_scan.sh',
    'tools/hooks/cc-godot-sandbox.sh',
    '.github/workflows/uid-guard.yml',
    'Makefile.tiers',
}
HOOK_ENTRY = '"command": "bash tools/hooks/cc-godot-sandbox.sh"'
# The nine Godot targets the story names, plus the one `[gates] extra` names.
GODOT_TARGETS = ('parse', 'lint', 'warnings', 'unit', 'integration', 'scenario',
                 'capture', 'import-cache', 'hermetic-scan', 'godot-check')


@contextlib.contextmanager
def consumer_repo(tmp_path: Path, makefile: bool = False):
    """An empty git repo, cwd'd into with the config caches cleared; with
    `makefile`, the consumer's three lines and the vendored include."""
    root = tmp_path / 'repo'
    root.mkdir()
    subprocess.run(['git', 'init', '-q'], cwd=root, check=True)
    if makefile:
        shutil.copy2(INCLUDE, root / 'Makefile.devkit')
        (root / 'Makefile').write_text(CONSUMER_MAKEFILE, encoding='utf-8')
    previous = Path.cwd()
    os.chdir(root)
    repo_root.cache_clear()
    load_config.cache_clear()
    try:
        yield root
    finally:
        os.chdir(previous)
        repo_root.cache_clear()
        load_config.cache_clear()


def run_install(*flags: str) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = install.main(list(flags))
    return code, out.getvalue(), err.getvalue()


def _snapshot(root: Path) -> dict[str, bytes]:
    return {rel: (root / rel).read_bytes() for rel in DESTINATIONS
            if (root / rel).is_file()}


def test_the_plan_writes_its_files_once_and_prints_the_hook_entry(tmp_path):
    with consumer_repo(tmp_path) as root:
        code, _, err = run_install('--fast')
        assert code == 2 and 'unknown flag' in err, err
        assert _snapshot(root) == {}, 'a usage error wrote'

        code, out, err = run_install()
        assert code == 0, out + err
        assert {rel for _name, rel in install.PLAN} == DESTINATIONS
        for rel in DESTINATIONS:
            assert (root / rel).is_file(), f'{rel} was not written'
            assert f'[install] wrote {rel}' in out, out
            if rel.endswith('.sh'):
                assert os.access(root / rel, os.X_OK), f'{rel} is not executable'
        for name, rel in install.PLAN:
            assert (root / rel).read_text(encoding='utf-8') == install.body_of(name)
        # The registration step, pasteable and LAST on stdout.
        assert HOOK_ENTRY in out, out
        assert out.rstrip().endswith('}'), out[-200:]
        assert err == '', err

        # A second run is a no-op that says so, and changes no byte.
        before = _snapshot(root)
        code, out, err = run_install()
        assert code == 0, out + err
        assert 'wrote' not in out and HOOK_ENTRY not in out, out
        assert out.count('already current') == len(DESTINATIONS), out
        assert _snapshot(root) == before


def test_diff_prints_and_writes_nothing(tmp_path):
    with consumer_repo(tmp_path) as root:
        code, out, err = run_install('--diff')
        assert code == 0, err
        assert _snapshot(root) == {}, 'a --diff wrote a file'
        assert out.count('does not exist — the whole file is an addition') == len(DESTINATIONS)

        run_install()
        tiers = root / 'Makefile.tiers'
        tiers.write_text(tiers.read_text(encoding='utf-8') + '\nmine: ; @true\n',
                         encoding='utf-8')
        before = _snapshot(root)
        code, out, _ = run_install('--diff')
        assert code == 0
        # a/ is what is on disk, b/ is what a run would write: the consumer's
        # own line shows as what the install would TAKE.
        assert '-mine: ; @true' in out, out
        assert out.count('already current') == len(DESTINATIONS) - 1, out
        assert _snapshot(root) == before, 'a --diff wrote a file'


def test_a_differing_destination_is_refused_by_name_and_force_replaces_it(tmp_path):
    """Two sentences for two edits. A body edit: refused by name, `--force`
    replaces it whole. An edit confined to the sandbox hook's `project config`
    block — the consumer's to edit — is a different sentence: the rest of the
    file is byte-current and there is nothing in it to take. Still exit 1 (the
    replacement WAS withheld), `--diff` says the same, and `--force` still
    takes the header too."""
    with consumer_repo(tmp_path) as root:
        run_install()
        parse = root / 'tools/dev/runners/parse.sh'
        parse.write_text(parse.read_text(encoding='utf-8') + '# mine\n',
                         encoding='utf-8')
        edited = parse.read_bytes()
        code, out, err = run_install()
        assert code == 1, out + err
        assert 'tools/dev/runners/parse.sh exists and differs' in err, err
        assert '--force' in err and 'nothing was written' in err, err
        assert parse.read_bytes() == edited, 'a refusal wrote'
        code, out, err = run_install('--force')
        assert code == 0, out + err
        assert '[install] wrote tools/dev/runners/parse.sh' in out, out
        assert parse.read_text(encoding='utf-8') == install.body_of('parse.sh')

        hook = root / 'tools/hooks/cc-godot-sandbox.sh'
        body = hook.read_text(encoding='utf-8')
        assert "SANDBOX_FUNCTION=''" in body
        hook.write_text(body.replace("SANDBOX_FUNCTION=''",
                                     "SANDBOX_FUNCTION='proj_boot'", 1),
                        encoding='utf-8')
        edited = hook.read_bytes()
        code, out, err = run_install()
        assert code == 1, out + err
        assert 'differs ONLY inside its project-config header' in err, err
        assert hook.read_bytes() == edited
        code, out, _ = run_install('--diff')
        assert code == 0
        assert 'differs ONLY inside its project-config header' in out, out
        assert "-SANDBOX_FUNCTION='proj_boot'" in out, out
        assert hook.read_bytes() == edited, 'a --diff wrote a file'
        assert run_install('--force')[0] == 0
        assert hook.read_text(encoding='utf-8') == install.body_of('cc-godot-sandbox.sh')


def _tiers(name: str) -> list[str]:
    """A tier list as the INSTALLABLE declares it."""
    match = re.search(rf'^{name}\s*:=(.*)$', install.body_of('Makefile.tiers'), re.M)
    assert match, f'Makefile.tiers no longer declares {name}'
    return match.group(1).split()


def _make_n(root: Path, *goals: str) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items()
           if k not in ('MAKELEVEL', 'MAKEFLAGS', 'MFLAGS', 'VERBOSE')}
    return subprocess.run(['make', '-n', *goals], cwd=root, text=True,
                          capture_output=True, env=env)


@pytest.mark.skipif(shutil.which('make') is None, reason='needs make')
def test_the_written_tiers_resolve_under_the_pinned_include(tmp_path):
    """The seam, end to end: agentic-sdlc's include `-include`s the tier file
    this verb wrote, reads its two lists, and `precommit` / `milestone` name
    every tier — `make -n`, so nothing boots. The include refuses a tier no
    makefile defines at parse time, so exit 0 here is the whole claim."""
    with consumer_repo(tmp_path, makefile=True) as root:
        assert run_install()[0] == 0
        declared: set[str] = set()
        for composition, var in (('precommit', 'GDK_PRECOMMIT_TIERS'),
                                 ('milestone', 'GDK_MILESTONE_TIERS')):
            tiers = _tiers(var)
            assert tiers, f'{var} is empty'
            declared.update(tiers)
            done = _make_n(root, composition)
            assert done.returncode == 0, done.stdout + done.stderr
            # The sub-make is spelled `${MAKE:-make}` so `-n` runs nothing;
            # the goals after it are the composition.
            assert f'{{MAKE:-make}} check {" ".join(tiers)}' in done.stdout, done.stdout
        # Every declared tier and every named Godot target is a goal make
        # resolves — `integration-diff` / `integration-all` are the slices
        # the compositions run, `integration` the one a hand takes ARGS to.
        for target in sorted(declared | set(GODOT_TARGETS)):
            done = _make_n(root, target)
            assert done.returncode == 0, f'{target}: {done.stdout}{done.stderr}'
        # `godot-check` is the pinned kit's `check all`, through the tag the
        # consumer's Makefile pins.
        done = _make_n(root, 'godot-check')
        assert 'godot-devkit@v0.25.0' in done.stdout and 'check all' in done.stdout, done.stdout


def test_this_repos_tier_file_starts_with_the_installable():
    """This repo's own Makefile.tiers is what `install-runners` writes
    (self-hosting — the seam is proven on the tree that ships it) followed by
    this repo's Python tiers. A byte of drift at the top is a fork of the
    installable wearing its name, so the prefix is held exactly."""
    own = (REPO_ROOT / 'Makefile.tiers').read_text(encoding='utf-8')
    installable = install.body_of('Makefile.tiers')
    assert own.startswith(installable), (
        'Makefile.tiers no longer opens with the installable byte for byte — '
        'edit the installable and re-compose, never the copy')
    assert 'pyunit:' in own[len(installable):], 'the Python tiers are gone'
