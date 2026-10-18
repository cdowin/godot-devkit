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
import json
import os
import re
import signal
import shutil
import subprocess
import sys
import textwrap
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from support import REPO_ROOT  # noqa: E402

from godot_devkit import __version__  # noqa: E402
from godot_devkit.core.project import load_config, repo_root  # noqa: E402
from godot_devkit.godot import install  # noqa: E402

pytestmark = pytest.mark.skipif(shutil.which('bash') is None,
                                reason='needs bash')

INSTALLABLES = REPO_ROOT / 'src' / 'godot_devkit' / 'godot' / 'installables'
LIBRARY = INSTALLABLES / 'gdk_runners.sh'
RUNNER = INSTALLABLES / 'import_cache.sh'
CAPTURE = INSTALLABLES / 'capture.sh'
UNIT = INSTALLABLES / 'unit.sh'
INTEGRATION = INSTALLABLES / 'integration.sh'
PARSE = INSTALLABLES / 'parse.sh'
SPOT = INSTALLABLES / 'spot.sh'
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


@pytest.fixture(autouse=True)
def isolated_engine_admission(tmp_path, monkeypatch):
    """Stub runners share a host within one case, never another case's host."""
    # Keep generated lease files outside fixtures that use tmp_path as a Git
    # root; otherwise --diff treats the test lease itself as a changed path.
    home = str(tmp_path.parent / f'{tmp_path.name}-engine-admission-home')
    monkeypatch.setenv('GDK_ENGINE_GATE_HOME', home)


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
    shutil.copy2(INSTALLABLES / 'gut_junit.py', root / 'tools' / 'dev' / 'runners/gut_junit.py')
    for runner in runners:
        shutil.copy2(runner, root / 'tools' / 'dev' / 'runners' / runner.name)
    if UNIT in runners:
        shutil.copy2(INSTALLABLES / 'gutconfig.json', root / '.gutconfig.json')
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


def _commit_all(root: Path) -> None:
    subprocess.run(['git', 'init', '-q', '-b', 'main'], cwd=root, check=True)
    (root / '.gitignore').write_text('.gate-reports/\n.headless-userdata/\n.godot/\n', encoding='utf-8')
    subprocess.run(['git', 'add', '-A'], cwd=root, check=True)
    subprocess.run([*GIT, 'commit', '-q', '-m', 'fixture'], cwd=root, check=True)


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
    for variable, runner in (('GDK_CAPTURE_REPORT_DIR', CAPTURE),):
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


# --- GUT's JUnit census, driven through stub engines -------------------------
def _gut_stub(suites: list[str], tests: int, *, png: bool = False, error: bool = False) -> str:
    cases = ''.join(f'<testsuite name="{name}" tests="1"><testcase name="ok"/></testsuite>'
                    for name in suites)
    xml = f'<testsuites tests="{tests}" failures="0">{cases}</testsuites>'
    lines = ['#!/usr/bin/env bash',
             'for arg in "$@"; do case "$arg" in -gjunit_xml_file=*) xml="${arg#*=}";; esac; done',
             'xml="${xml#res://}"', 'mkdir -p "$(dirname "$xml")"',
             f"printf '%s\\n' '{xml}' > \"$xml\""]
    if png:
        lines += ['mkdir -p .capture-reports', 'echo image > .capture-reports/eyes.png']
    if error:
        lines += ['echo "SCRIPT ERROR: Parse Error: bad script"']
    return '\n'.join(lines) + '\n'


def test_unit_reconciles_junit_scripts_and_rejects_zero_tests_and_engine_errors(tmp_path):
    root = tmp_path / 'repo'
    _project(root, UNIT)
    tier = root / 'tests/unit'
    tier.mkdir(parents=True)
    (tier / 'test_a.gd').write_text('extends GutTest\n', encoding='utf-8')
    stub = _stub_engine(tmp_path, _gut_stub(['tests/unit/test_a.gd'], 1))
    env = {'PATH': f'{stub}:/usr/bin:/bin:{Path(sys.executable).parent}',
           'HOME': str(tmp_path / 'home'),
           'GDK_ENGINE_GATE_HOME': os.environ['GDK_ENGINE_GATE_HOME']}

    def unit(*args: str):
        return subprocess.run(['bash', 'tools/dev/runners/unit.sh', *args], cwd=root,
                              text=True, capture_output=True, env=env)

    done = unit()
    assert done.returncode == 0 and '[UNIT] PASS (1 test(s), 1 script(s))' in done.stdout, done.stdout + done.stderr
    (stub / 'godot').write_text(_gut_stub(['tests/unit/test_a.gd.Inner'], 1), encoding='utf-8')
    done = unit()
    assert done.returncode == 0, done.stdout + done.stderr
    (stub / 'godot').write_text(_gut_stub(['tests/unit/test_a.gd'], 1), encoding='utf-8')
    (tier / 'test_b.gd').write_text('extends GutTest\n', encoding='utf-8')
    done = unit()
    assert done.returncode == 1 and 'script census mismatch' in done.stdout, done.stdout + done.stderr
    done = unit('-gtest', 'res://tests/unit/test_a.gd')
    assert done.returncode == 0, done.stdout + done.stderr
    (stub / 'godot').write_text(_gut_stub(['tests/unit/test_a.gd', 'tests/unit/test_b.gd'], 0), encoding='utf-8')
    done = unit()
    assert done.returncode == 1 and 'zero tests' in done.stdout, done.stdout + done.stderr
    (stub / 'godot').write_text(_gut_stub(['tests/unit/test_a.gd', 'tests/unit/test_b.gd'], 2, error=True), encoding='utf-8')
    done = unit()
    assert done.returncode == 1 and '[UNIT] FAIL' in done.stdout, done.stdout + done.stderr
    done = unit('-gtest=res://tests/unit/test_a.gd')
    assert done.returncode == 1  # engine error still fails a selected file
    (root / '.gutconfig.json').write_text(
        '{"dirs":["res://tests/unit"],"junit_xml_timestamp":true}', encoding='utf-8')
    done = unit()
    assert done.returncode == 2 and 'junit_xml_timestamp must be false' in done.stderr


def test_integration_uses_second_config_and_per_file_isolation(tmp_path):
    root = tmp_path / 'repo'
    _project(root, UNIT, INTEGRATION)
    tier = root / 'tests/integration'
    tier.mkdir(parents=True)
    (tier / 'test_world.gd').write_text('extends GutTest\n', encoding='utf-8')
    (root / '.gutconfig.integration.json').write_text(
        '{"dirs":["res://tests/integration"],"include_subdirs":true}', encoding='utf-8')
    stub = _stub_engine(tmp_path, _gut_stub(['tests/integration/test_world.gd'], 1))
    env = {'PATH': f'{stub}:/usr/bin:/bin:{Path(sys.executable).parent}',
           'HOME': str(tmp_path / 'home'),
           'GDK_ENGINE_GATE_HOME': os.environ['GDK_ENGINE_GATE_HOME']}
    done = subprocess.run(['bash', 'tools/dev/runners/integration.sh'], cwd=root,
                          text=True, capture_output=True, env=env)
    assert done.returncode == 0 and '[INTEGRATION] PASS' in done.stdout, done.stdout + done.stderr
    done = subprocess.run(['bash', 'tools/dev/runners/integration.sh'], cwd=root,
                          text=True, capture_output=True,
                          env={**env, 'GDK_INTEGRATION_PER_FILE': '1', 'GDK_JOBS': '2'})
    assert done.returncode == 0 and '[INTEGRATION] PASS (1 file(s))' in done.stdout, done.stdout + done.stderr


def test_capture_runs_one_headed_gut_file_and_requires_a_fresh_png(tmp_path):
    root = tmp_path / 'repo'
    _project(root, CAPTURE)
    test = root / 'tests/capture/test_eyes.gd'
    test.parent.mkdir(parents=True)
    test.write_text('extends GutTest\n', encoding='utf-8')
    stub = _stub_engine(tmp_path, _gut_stub(['tests/capture/test_eyes.gd'], 1, png=True))
    env = {'PATH': f'{stub}:/usr/bin:/bin:{Path(sys.executable).parent}',
           'HOME': str(tmp_path / 'home'),
           'GDK_ENGINE_GATE_HOME': os.environ['GDK_ENGINE_GATE_HOME']}
    def capture(extra=None):
        return subprocess.run(['bash', 'tools/dev/runners/capture.sh', 'eyes'],
                              cwd=root, text=True, capture_output=True, env={**env, **(extra or {})})
    for extra in ({}, {'CAPTURE_VISIBLE': '1'}):
        done = capture(extra)
        assert done.returncode == 0 and '[CAPTURE] PASS' in done.stdout, done.stdout + done.stderr
    (stub / 'godot').write_text(_gut_stub(['tests/capture/test_eyes.gd'], 1), encoding='utf-8')
    done = capture()
    assert done.returncode == 1 and '[CAPTURE] FAIL' in done.stdout, done.stdout + done.stderr
    assert (root / '.capture-reports/previous/eyes.png').is_file()


# --- parse.sh: one engine run, driven through the RUNNER ---------------------
def test_parse_imports_then_compiles_and_fails_on_engine_errors(tmp_path):
    root = tmp_path / 'repo'
    _project(root, PARSE)
    starts = tmp_path / 'starts.log'
    stub = _stub_engine(tmp_path, '#!/usr/bin/env bash\n'
                        'echo "$*" >> "$GDK_STUB_LOG"\n'
                        'case "$*" in *--import*) echo "Godot Engine ready";; '
                        '*) echo "SWEEP_RESULT 1 1";; esac\n')
    env = {'PATH': f'{stub}:/usr/bin:/bin:{Path(sys.executable).parent}',
           'HOME': str(tmp_path / 'home'), 'GDK_RECEIPTS': '0',
           'GDK_STUB_LOG': str(starts),
           'GDK_ENGINE_GATE_HOME': os.environ['GDK_ENGINE_GATE_HOME']}
    def parse():
        return subprocess.run(['bash', 'tools/dev/runners/parse.sh'], cwd=root,
                              text=True, capture_output=True, env=env)
    done = parse()
    assert done.returncode == 0, done.stdout + done.stderr
    assert starts.read_text(encoding='utf-8').splitlines() == [
        '--path . --headless --import',
        '--path . --headless -s res://tools/dev/runners/compile_sweep.gd']
    (stub / 'godot').write_text('#!/usr/bin/env bash\n'
                                'case "$*" in *--import*) exit 0;; esac\n'
                                'echo "SWEEP_FAIL res://bad.gd"\necho "SWEEP_RESULT 0 1"\n', encoding='utf-8')
    done = parse()
    assert done.returncode == 1 and 'compiled 0/1' in done.stdout, done.stdout + done.stderr
    (stub / 'godot').write_text('#!/usr/bin/env bash\necho "SCRIPT ERROR: bad script"\n', encoding='utf-8')
    done = parse()
    assert done.returncode == 1, done.stdout + done.stderr


GDLINT_STUB = ('#!/usr/bin/env bash\necho "lint $*" >> "$GDK_STUB_LOG"\n'
               'for f; do case "$f" in *bad*) echo "$f:1: Error: bad name"; exit 1 ;; esac; done\n'
               'echo "Success: no problems found"\n')
SWEEP_STUB = ('#!/usr/bin/env bash\necho "boot $*" >> "$GDK_STUB_LOG"\n'
              'n=0; after=0; for a; do [ "$after" = 1 ] && n=$((n + 1)); [ "$a" = -- ] && after=1; done\n'
              'echo "SWEEP_RESULT $n $n"\n')


def test_lint_runs_one_gdlint_per_dir_and_its_receipt_ignores_a_resource_edit(tmp_path):
    """#50. The lint receipt keyed on the whole tree, so a .tres edit re-linted
    every script; it keys on *.gd and the gdlint config now. gdlint is
    single-threaded, so each scan dir is its own gdlint, run in parallel; the
    transcript keeps scan-dir order, and one dir's finding fails the gate."""
    root = tmp_path / 'repo'
    _project(root, INSTALLABLES / 'lint.sh')
    for name in ('autoloads', 'systems'):
        (root / name).mkdir()
        (root / name / 'a.gd').write_text('extends Node\n', encoding='utf-8')
    (root / 'data').mkdir()
    (root / 'data' / 'x.tres').write_text('[gd_resource format=3]\n', encoding='utf-8')
    _commit_all(root)
    stub = tmp_path / 'bin'
    stub.mkdir()
    (stub / 'gdlint').write_text(GDLINT_STUB, encoding='utf-8')
    (stub / 'gdlint').chmod(0o755)
    log = tmp_path / 'stub.log'
    env = {'PATH': f'{stub}:/usr/bin:/bin', 'HOME': str(tmp_path / 'home'),
           'GDK_STUB_LOG': str(log)}

    def lint() -> subprocess.CompletedProcess:
        return subprocess.run(['bash', 'tools/dev/runners/lint.sh'], cwd=root, text=True,
                              capture_output=True, env=env)

    def calls() -> list[str]:
        return sorted(log.read_text(encoding='utf-8').splitlines()) if log.exists() else []

    done = lint()
    assert done.returncode == 0, done.stdout + done.stderr
    assert '[LINT] PASS (2 source dir(s): autoloads systems)' in done.stdout, done.stdout
    assert calls() == ['lint autoloads', 'lint autoloads/a.gd', 'lint systems'], calls()

    (root / 'data' / 'x.tres').write_text('[gd_resource format=3]\n; edited\n', encoding='utf-8')
    done = lint()
    assert done.returncode == 0 and '; reused — receipt' in done.stdout, done.stdout + done.stderr
    assert len(calls()) == 3, f'a .tres edit re-linted: {calls()}'

    for config in ('gdlintrc', '.gdlintrc'):
        (root / config).write_text('max-line-length: 100\n', encoding='utf-8')
        before = len(calls())
        done = lint()
        assert done.returncode == 0 and 'reused' not in done.stdout, done.stdout
        assert len(calls()) == before + 3, f'a {config} edit reused the receipt: {calls()}'

    (root / 'systems' / 'bad.gd').write_text('extends Node\n', encoding='utf-8')
    subprocess.run(['git', 'add', '-A'], cwd=root, check=True)
    (stub / 'gdlint').write_text(GDLINT_STUB.replace(
        'for f; do', 'for f; do case "$f" in systems) echo "$f/bad.gd:1: Error: bad name"; '
        'echo "Failure: 1 problem found"; exit 1 ;; esac; done\nfor f; do'), encoding='utf-8')
    done = lint()
    assert done.returncode == 1, done.stdout + done.stderr
    assert 'systems/bad.gd:1: Error: bad name' in done.stdout, done.stdout
    assert '[LINT] FAIL (exit 1) — 2 source dir(s): autoloads systems' in done.stdout, done.stdout
    transcript = (root / '.gate-reports' / 'lint.log').read_text(encoding='utf-8')
    assert transcript.index('Success: no problems found') < transcript.index('systems/bad.gd'), \
        transcript
    env['GDK_LINT_JOBS'] = 'many'
    done = lint()
    assert done.returncode == 2 and 'GDK_LINT_JOBS' in done.stderr, done.stdout + done.stderr


# A gdlint that behaves like gdtoolkit on a fresh machine: it checks for its
# grammar-cache dir, then creates it. The window between check and create is
# widened so two concurrent first runs always collide, and the loser fails the
# way the real one does ("File exists").
CACHING_GDLINT_STUB = ('#!/usr/bin/env bash\n'
                       'if [ ! -d "$GDK_STUB_CACHE" ]; then\n'
                       '  sleep 0.5\n'
                       '  mkdir "$GDK_STUB_CACHE" 2>/dev/null || { '
                       'echo "Cannot open file \'$1\': File exists"; exit 1; }\n'
                       'fi\n'
                       'echo "Success: no problems found"\n')


def test_lint_warms_the_gdlint_cache_once_before_the_parallel_fanout(tmp_path):
    """#73. gdtoolkit checks for its cache dir and then makedirs it, so on a
    fresh machine (every CI runner) two parallel gdlints race and the loser
    fails with "File exists". lint.sh runs gdlint once, serially, before the
    fan-out, so the cache exists by the time the parallel runs start."""
    root = tmp_path / 'repo'
    _project(root, INSTALLABLES / 'lint.sh')
    for name in ('autoloads', 'systems'):
        (root / name).mkdir()
        (root / name / 'a.gd').write_text('extends Node\n', encoding='utf-8')
    _commit_all(root)
    stub = tmp_path / 'bin'
    stub.mkdir()
    (stub / 'gdlint').write_text(CACHING_GDLINT_STUB, encoding='utf-8')
    (stub / 'gdlint').chmod(0o755)
    env = {'PATH': f'{stub}:/usr/bin:/bin', 'HOME': str(tmp_path / 'home'),
           'GDK_STUB_CACHE': str(tmp_path / 'gdlint-cache'), 'GDK_LINT_JOBS': '2'}
    done = subprocess.run(['bash', 'tools/dev/runners/lint.sh'], cwd=root, text=True,
                          capture_output=True, env=env)
    assert done.returncode == 0, done.stdout + done.stderr
    assert '[LINT] PASS (2 source dir(s): autoloads systems)' in done.stdout, done.stdout


def test_spot_checks_only_the_changed_scripts_and_a_scene_only_change_passes_census_0(tmp_path):
    """gdk#45. The builder's check reads the .gd files that differ from the
    merge base with BASE — committed on the branch and untracked alike — and
    nothing else. No changed .gd is a PASS that says `census 0` and names the
    base. The same change again is a receipt; a lint finding is exit 1."""
    root = tmp_path / 'repo'
    _project(root, SPOT)
    (root / 'systems').mkdir()
    (root / 'systems' / 'old.gd').write_text('extends Node\n', encoding='utf-8')
    _commit_all(root)
    stub = _stub_engine(tmp_path, SWEEP_STUB)
    (stub / 'gdlint').write_text(GDLINT_STUB, encoding='utf-8')
    (stub / 'gdlint').chmod(0o755)
    log = tmp_path / 'stub.log'
    env = {'PATH': f'{stub}:/usr/bin:/bin', 'HOME': str(tmp_path / 'home'),
           'GDK_STUB_LOG': str(log)}

    def spot(**extra: str) -> subprocess.CompletedProcess:
        return subprocess.run(['bash', 'tools/dev/runners/spot.sh'], cwd=root, text=True,
                              capture_output=True, env={**env, **extra})

    subprocess.run(['git', 'checkout', '-q', '-b', 'feat/x'], cwd=root, check=True)
    (root / 'scenes').mkdir()
    (root / 'scenes' / 'main.tscn').write_text('[gd_scene format=3]\n', encoding='utf-8')
    done = spot()
    assert done.returncode == 0, done.stdout + done.stderr
    assert '[SPOT] PASS — census 0: no .gd changed vs merge-base ' in done.stdout, done.stdout
    assert 'with main' in done.stdout, done.stdout
    assert not log.exists(), 'a scene-only change ran the linter or the engine'

    (root / 'systems' / 'a.gd').write_text('extends Node\n', encoding='utf-8')
    subprocess.run(['git', 'add', '-A'], cwd=root, check=True)
    subprocess.run([*GIT, 'commit', '-q', '-m', 'a'], cwd=root, check=True)
    (root / 'systems' / 'b.gd').write_text('extends Node\n', encoding='utf-8')
    done = spot()
    assert done.returncode == 0, done.stdout + done.stderr
    assert '[SPOT] PASS (2 changed .gd vs merge-base ' in done.stdout, done.stdout
    assert log.read_text(encoding='utf-8').splitlines() == [
        'lint systems/a.gd systems/b.gd',
        'boot --path . --headless -s res://tools/dev/runners/compile_sweep.gd -- '
        'res://systems/a.gd res://systems/b.gd']
    done = spot()
    assert done.returncode == 0 and '; reused — receipt' in done.stdout, done.stdout + done.stderr
    assert len(log.read_text(encoding='utf-8').splitlines()) == 2, 'a reused run linted or booted'

    (root / 'systems' / 'bad.gd').write_text('extends Node\n', encoding='utf-8')
    done = spot()
    assert done.returncode == 1, done.stdout + done.stderr
    assert '[SPOT] FAIL (lint)' in done.stdout, done.stdout
    done = spot(GDK_SPOT_BASE='no-such-branch')
    assert done.returncode == 2 and 'no merge base' in done.stderr, done.stdout + done.stderr


def test_engine_gate_conflicts_fast_and_descendants_keep_host_lease_after_home_sandbox(tmp_path):
    """The lock is host-scoped and descriptor-backed: a second gate with
    GDK_ENGINE_GATE_WAIT=0 fails immediately with owner context, while sourced
    descendants still validate the captured host path after HOME has become a
    per-run sandbox."""
    home = tmp_path / 'host-home'
    lib = LIBRARY
    owner = subprocess.Popen(
        ['bash', '-c', 'source "$1"; gdk_engine_gate_run integration -- bash -c '
         '"source \\\"$1\\\"; HOME=/tmp/sandbox; '
         'gdk_engine_gate_held || exit 41; echo ready; sleep 20"', '_', str(lib)],
        text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True,
        env=dict(os.environ, GDK_ENGINE_GATE_SLOTS='1', HOME=str(home)))
    try:
        assert owner.stdout is not None
        assert owner.stdout.readline().strip() == 'ready'
        competing = subprocess.run(
            ['bash', '-c', 'source "$1"; gdk_engine_gate_run parse -- true', '_', str(lib)],
            text=True, capture_output=True,
            env=dict(os.environ, GDK_ENGINE_GATE_SLOTS='1', HOME=str(home), GDK_ENGINE_GATE_WAIT='0'))
        assert competing.returncode == 75, competing.stdout + competing.stderr
        assert 'engine gate busy' in competing.stderr, competing.stderr
        assert 'integration' in competing.stderr, competing.stderr
    finally:
        os.killpg(owner.pid, signal.SIGTERM)
        owner.wait(timeout=5)
    released = subprocess.run(
        ['bash', '-c', 'source "$1"; gdk_engine_gate_run after-crash -- true', '_', str(lib)],
        text=True, capture_output=True, env=dict(os.environ, GDK_ENGINE_GATE_SLOTS='1', HOME=str(home)))
    assert released.returncode == 0, released.stdout + released.stderr


def test_engine_gate_is_a_counted_lease_weighted_per_run(tmp_path):
    """#47: one exclusive lock made a 0.4 s unit slice wait 17-191 s behind a
    peer lane. With 3 slots, a run of weight 2 leaves room for a weight-1 run
    beside it, which starts at once; a third run finds no slot and names both
    owners; `all` asks for every slot. A weight above the count is the count,
    and a bad count or weight is exit 2 before anything runs."""
    home = tmp_path / 'counted-home'
    env = dict(os.environ, HOME=str(home), GDK_ENGINE_GATE_SLOTS='3')

    def gate(check: str, weight: str, cmd: str, **extra: str):
        return ['bash', '-c', f'source "$1"; gdk_engine_gate_run {check} -- bash -c "{cmd}"',
                '_', str(LIBRARY)], {**env, 'GDK_ENGINE_GATE_WEIGHT': weight, **extra}

    argv, owner_env = gate('integration', '2', 'echo ready; sleep 20')
    owner = subprocess.Popen(argv, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             start_new_session=True, env=owner_env)
    second = None
    try:
        assert owner.stdout is not None
        assert owner.stdout.readline().strip() == 'ready'
        argv, second_env = gate('unit', '1', 'echo ready; sleep 20', GDK_ENGINE_GATE_WAIT='0')
        second = subprocess.Popen(argv, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                  start_new_session=True, env=second_env)
        assert second.stdout is not None
        assert second.stdout.readline().strip() == 'ready', 'a weight-1 run waited beside weight 2 of 3'
        argv, third_env = gate('parse', '1', 'true', GDK_ENGINE_GATE_WAIT='0')
        third = subprocess.run(argv, text=True, capture_output=True, env=third_env)
        assert third.returncode == 75, third.stdout + third.stderr
        assert 'engine gate busy' in third.stderr, third.stderr
        assert 'holds check integration (2 slots)' in third.stderr, third.stderr
        assert 'holds check unit' in third.stderr, third.stderr
    finally:
        for proc in (owner, second):
            if proc is not None and proc.poll() is None:
                os.killpg(proc.pid, signal.SIGTERM)
            if proc is not None:
                proc.wait(timeout=5)
    for weight in ('all', '9'):
        argv, solo_env = gate('integration', weight, 'true', GDK_ENGINE_GATE_WAIT='0')
        done = subprocess.run(argv, text=True, capture_output=True, env=solo_env)
        assert done.returncode == 0, f'{weight}: {done.stdout}{done.stderr}'
    for name, value in (('GDK_ENGINE_GATE_SLOTS', '0'), ('GDK_ENGINE_GATE_WEIGHT', 'two')):
        argv, bad_env = gate('parse', '1', 'touch ran', **{name: value})
        done = subprocess.run(argv, cwd=tmp_path, text=True, capture_output=True, env=bad_env)
        assert done.returncode == 2 and name in done.stderr, done.stdout + done.stderr
        assert not (tmp_path / 'ran').exists(), f'a bad {name} still ran the command'


def test_engine_gate_queues_until_the_owner_releases(tmp_path):
    """#41: by default a second gate waits for the lease, says so once, and
    runs when the owner exits; it never exits 75 while the bound holds."""
    home = tmp_path / 'queue-home'
    owner = subprocess.Popen(
        ['bash', '-c', 'source "$1"; gdk_engine_gate_run integration -- '
         'bash -c "echo ready; sleep 1"', '_', str(LIBRARY)],
        text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True,
        env=dict(os.environ, GDK_ENGINE_GATE_SLOTS='1', HOME=str(home)))
    try:
        assert owner.stdout is not None
        assert owner.stdout.readline().strip() == 'ready'
        queued = subprocess.run(
            ['bash', '-c', 'source "$1"; gdk_engine_gate_run parse -- true', '_', str(LIBRARY)],
            text=True, capture_output=True, timeout=30,
            env=dict(os.environ, GDK_ENGINE_GATE_SLOTS='1', HOME=str(home), GDK_ENGINE_GATE_WAIT='20'))
        assert queued.returncode == 0, queued.stdout + queued.stderr
        assert 'waits up to 20 s' in queued.stderr, queued.stderr
        assert 'admitted parse' in queued.stderr, queued.stderr
    finally:
        owner.wait(timeout=10)


def test_bounded_env_godot_command_is_leased_and_invalid_cache_lease_refuses(tmp_path):
    """Scenario's env-prefixed engine command is serialized; a forged or
    stale inherited descriptor refuses cache rebuild before invoking Godot."""
    home = tmp_path / 'lease-home'
    bin_dir = tmp_path / 'bin'
    bin_dir.mkdir()
    godot = bin_dir / 'godot'
    godot.write_text('#!/bin/sh\necho boot >> "$GDK_BOOT_LOG"\nsleep 5\n', encoding='utf-8')
    godot.chmod(0o755)
    timeout = bin_dir / 'timeout'
    timeout.write_text(TIMEOUT_STUB, encoding='utf-8')
    timeout.chmod(0o755)
    ready = tmp_path / 'ready'
    owner = subprocess.Popen(
        ['bash', '-c', 'source "$1"; GDK_TIMEOUT="$2"; GDK_GODOT="$3"; export GDK_TIMEOUT GDK_GODOT; '
         'gdk_run_bounded 20 -- env GDK_GODOT="$GDK_GODOT" "$GDK_GODOT"; echo "$?" > "$4"',
         '_', str(LIBRARY), str(timeout), str(godot), str(ready)],
        cwd=tmp_path, start_new_session=True,
        env=dict(os.environ, GDK_ENGINE_GATE_SLOTS='1', HOME=str(home), GDK_BOOT_LOG=str(tmp_path / 'boots')))
    try:
        deadline = time.monotonic() + 5
        while not (tmp_path / 'boots').exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        competing = subprocess.run(
            ['bash', '-c', 'source "$1"; GDK_TIMEOUT="$2"; GDK_GODOT="$3"; export GDK_TIMEOUT GDK_GODOT; '
             'gdk_run_bounded 20 -- env GDK_GODOT="$GDK_GODOT" "$GDK_GODOT"',
             '_', str(LIBRARY), str(timeout), str(godot)], cwd=tmp_path,
            text=True, capture_output=True,
            env=dict(os.environ, GDK_ENGINE_GATE_SLOTS='1', HOME=str(home), GDK_BOOT_LOG=str(tmp_path / 'boots'),
                     GDK_ENGINE_GATE_WAIT='0'))
        assert competing.returncode == 75, competing.stdout + competing.stderr
        assert 'engine gate busy' in competing.stderr, competing.stderr
    finally:
        os.killpg(owner.pid, signal.SIGTERM) if owner.poll() is None else None
        owner.wait(timeout=5)
    marker = tmp_path / 'marker'
    refused = subprocess.run(
        ['bash', '-c', 'source "$1"; GDK_TIMEOUT="$2"; GDK_GODOT="$3"; '
         'GDK_ENGINE_GATE_FD=999999 GDK_ENGINE_GATE_OWNER_PID=1 gdk_rebuild_import_cache 2; '
         'echo "$?" > "$4"', '_', str(LIBRARY), str(timeout), str(godot), str(marker)],
        cwd=tmp_path, text=True, capture_output=True,
        env=dict(os.environ, GDK_ENGINE_GATE_SLOTS='1', HOME=str(home), GDK_BOOT_LOG=str(tmp_path / 'boots')))
    assert 'invalid inherited engine lease' in refused.stderr, refused.stderr
    assert marker.read_text(encoding='utf-8').strip() == '2'


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


# --- the install verb: whole-file writes, once ---------------------------------
# The verb's contract is the one every installer this package ever shipped
# had: write each file once, refuse a differing destination by name (`--force`
# replaces it whole), `--diff` prints and writes nothing, a second run is a
# no-op, every `.sh` lands executable. The include the written tier file
# composes under is this package's own `install-gates` output (Makefile.gates),
# so the composition is proven on every machine with agentic-sdlc NOT installed.
CONSUMER_MAKEFILE = ('GDK_CHECKS := godot-check\n'
                     'GODOT_DEVKIT_VERSION := v0.25.0\n'
                     'include Makefile.gates\n')
# The roster, by destination — pinned rather than read off the plan, because a
# file dropped from the plan is a file a consumer silently stops getting.
DESTINATIONS = {
    'tools/dev/gdk_runners.sh',
    'tools/dev/runners/import_cache.sh', 'tools/dev/runners/parse.sh',
    'tools/dev/runners/compile_sweep.gd', 'tools/dev/runners/compile_sweep.gd.uid',
    'tools/dev/runners/lint.sh', 'tools/dev/runners/spot.sh',
    'tools/dev/runners/unit.sh', 'tools/dev/runners/gut_junit.py',
    '.gutconfig.json', '.gutconfig.integration.json',
    'tests/integration/integration_test_template.gd',
    'tests/integration/measure_test_template.gd',
    'tools/dev/runners/integration.sh', 'tools/dev/runners/capture.sh',
    'tools/dev/runners/hermetic_run_scan.sh',
    'tools/hooks/cc-godot-sandbox.sh',
    '.github/actions/godot-toolchain/action.yml',
    '.github/workflows/release.yml',
    'Makefile.tiers',
}
HOOK_ENTRY = '"command": "bash tools/hooks/cc-godot-sandbox.sh"'
TOOLCHAIN = '.github/actions/godot-toolchain/action.yml'
RELEASE = '.github/workflows/release.yml'
TOOLCHAIN_STEP = '- uses: ./.github/actions/godot-toolchain'
# Retired in 1.3.0: no longer written, never deleted, named on every run.
UID_GUARD = '.github/workflows/uid-guard.yml'
# The Godot targets the story names, the builder's `spot`, and the one
# GDK_CHECKS names.
GODOT_TARGETS = ('parse', 'lint', 'spot', 'unit', 'integration',
                 'capture', 'import', 'hermetic-scan', 'godot-check')


@contextlib.contextmanager
def consumer_repo(tmp_path: Path, makefile: bool = False):
    """An empty git repo, cwd'd into with the config caches cleared; with
    `makefile`, the consumer's three lines and the gate framework
    `install-gates` writes."""
    root = tmp_path / 'repo'
    root.mkdir()
    subprocess.run(['git', 'init', '-q'], cwd=root, check=True)
    if makefile:
        (root / 'Makefile').write_text(CONSUMER_MAKEFILE, encoding='utf-8')
    previous = Path.cwd()
    os.chdir(root)
    repo_root.cache_clear()
    load_config.cache_clear()
    if makefile:
        with contextlib.redirect_stdout(io.StringIO()):
            assert install.main_gates([]) == 0
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
        assert install.CONTEXT_BLOCK in out and 'godot-native-first' in out
        assert not (root / 'CLAUDE.md').exists() and not (root / 'AGENTS.md').exists()
        for rel in DESTINATIONS:
            assert (root / rel).is_file(), f'{rel} was not written'
            assert f'[install] wrote {rel}' in out, out
            if rel.endswith('.sh'):
                assert os.access(root / rel, os.X_OK), f'{rel} is not executable'
        for name, rel in install.PLAN:
            assert (root / rel).read_text(encoding='utf-8') == install.body_of(name)
        # The CI toolchain (#26): a composite action with the three inputs at
        # the laptop's versions, gated on the import's class cache — and the
        # retired uid-guard workflow is not written.
        action = (root / TOOLCHAIN).read_text(encoding='utf-8')
        for needle in ('using: composite', '  godot-patch:\n',
                       'default: "4.5.0"', 'default: "0.11.0"',
                       'gdlint --version',
                       'test -f .godot/global_script_class_cache.cfg',
                       # A preinstalled engine skips setup-godot (#80); shellcheck
                       # follows the runner's arch (#79); `import: false` keeps the
                       # class-cache assert.
                       '  godot-root:\n', "if: steps.preinstalled.outputs.found != 'true'",
                       'shellcheck-v$v.linux.$a.tar.xz', '  import:\n',
                       'IMPORT: ${{ inputs.import }}'):
            assert needle in action, needle
        assert 'linux.x86_64.tar.xz' not in action
        godot_patch = action.split('  godot-patch:\n', 1)[1].split('\n  gdtoolkit', 1)[0]
        assert 'required: true' in godot_patch and 'default' not in godot_patch
        # The release workflow (#85): both triggers, the preset matrix from the
        # config job, an export and an upload, and no cache or artifact delete.
        release = (root / RELEASE).read_text(encoding='utf-8')
        for needle in ('workflow_dispatch', 'tag:', 'fromJSON(needs.config.outputs.presets)',
                       'fromJSON(needs.config.outputs.gates)', 'fromJSON(needs.config.outputs.gate_timeout)',
                       'fail-fast: true', "needs.config.outputs.gates != '[]'", 'GATE: ${{ matrix.gate }}',
                       '--export-release', 'gh release upload', 'contents: write',
                       # The tag-last order (#89): export uploads artifacts, release downloads
                       # them, needs export, and creates the tag at the sha.
                       'actions/upload-artifact@v4', 'actions/download-artifact@v4',
                       'merge-multiple: true', '--target', 'needs: [config, gate, export]',
                       'needs.export.result == \'success\'', 'sha:'):
            assert needle in release, needle
        export_job = release.split('\n  export:\n', 1)[1].split('\n  release:\n', 1)[0]
        assert 'gh release' not in export_job and 'upload-artifact' in export_job
        for banned in ('actions/caches', 'DELETE', 'actions: write'):
            assert banned not in release, banned
        # The config heredoc, run on its own against a sample repo: the stock
        # defaults (presets from export_presets.cfg, a gate from the Makefile)
        # and a [release] override, proven once here rather than per job.
        heredoc = re.split(r'\n[ ]+PY\n', release.split("python3 - <<'PY'\n", 1)[1], maxsplit=1)[0]
        script = textwrap.dedent(heredoc + '\n')
        (root / 'project.godot').write_text(
            'config/features=PackedStringArray("4.7", "GL Compatibility")\n', encoding='utf-8')
        (root / 'export_presets.cfg').write_text(
            '[preset.0]\nname="Linux"\nexport_path="build/linux/g.x86_64"\n[preset.0.options]\n'
            'name="no"\n[preset.1]\nname="Windows Desktop"\nexport_path="build/win/g.exe"\n',
            encoding='utf-8')
        (root / 'Makefile').write_text('verify:\n\t@true\n', encoding='utf-8')

        def read_config(toml: str) -> dict[str, str]:
            (root / 'godot-devkit.toml').write_text(toml, encoding='utf-8')
            sink = root / 'gh_output'
            sink.unlink(missing_ok=True)
            done = subprocess.run([sys.executable, '-c', script], cwd=root, text=True,
                                  capture_output=True,
                                  env={**os.environ, 'GITHUB_OUTPUT': str(sink),
                                       'GITHUB_REPOSITORY': 'o/game'})
            if done.returncode:
                return {'error': done.stdout}
            return dict(line.split('=', 1) for line in sink.read_text().splitlines())

        assert 'godot_patch' in read_config('')['error']
        got = read_config('[release]\ngodot_patch = "2"\n')
        assert json.loads(got['presets']) == [
            {'name': 'Linux', 'preset': 'Linux', 'output': 'build/linux/g.x86_64', 'archive': 'tar.gz'},
            {'name': 'Windows Desktop', 'preset': 'Windows Desktop', 'output': 'build/win/g.exe',
             'archive': 'zip'}]
        assert (got['gates'], got['gate_timeout'], got['title'], got['godot_version'],
                got['before_export']) == ('["verify"]', '30', 'game', '4.7.2', '[]')
        got = read_config('[release]\ngodot_patch = "2"\ngate = ""\ngate_timeout = 90\ntitle = "Game"\n'
                          'before_export = ["make assets"]\n[[release.presets]]\n'
                          'preset = "Linux"\narchive = "zip"\n')
        assert (got['gates'], got['gate_timeout'], got['title'], got['before_export']) == \
            ('[]', '90', 'Game', '["make assets"]')
        assert json.loads(got['presets']) == [
            {'name': 'Linux', 'preset': 'Linux', 'output': 'build/linux/g.x86_64', 'archive': 'zip'}]
        # Each gate entry is one parallel job: a string, or a list joined by spaces.
        got = read_config('[release]\ngodot_patch = "2"\ngate = ["gates-self-test", '
                          '["check", "parse"], "integration"]\n')
        assert json.loads(got['gates']) == ['gates-self-test', 'check parse', 'integration']
        assert 'gate_timeout' in read_config('[release]\ngodot_patch = "2"\ngate_timeout = 0\n')['error']
        assert 'gate_timeout' in read_config('[release]\ngodot_patch = "2"\ngate_timeout = "5"\n')['error']
        assert 'both or neither' in read_config('[release]\ngodot_patch = "2"\nversion_file = "v"\n')['error']
        (root / 'godot-devkit.toml').unlink()
        (root / 'export_presets.cfg').unlink()
        (root / 'project.godot').unlink()
        (root / 'Makefile').unlink()
        (root / 'gh_output').unlink(missing_ok=True)
        assert not (root / UID_GUARD).exists()
        assert TOOLCHAIN_STEP in out and 'retired' not in out, out
        # The locked shape (#38), pasteable whole: the running version, from
        # this kit's index ONLY.
        assert f'\n{install.PYPROJECT_BLOCK}\n' in out, out
        for needle in (f'dev = ["godot-devkit=={__version__}"]', 'explicit = true',
                       'url = "https://cdowin.github.io/godot-devkit/simple/"',
                       'godot-devkit = { index = "cdowin" }'):
            assert needle in install.PYPROJECT_BLOCK, needle
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


@pytest.mark.parametrize('toml, says', [
    # The roster names `uid`: `check uid` runs in `make check` once GDK_CHECKS
    # (a Makefile variable this verb cannot read) names `godot-check`.
    ('[roster]\nchecks = ["uid"]\n', 'is safe to delete once it does'),
    # The stock roster leaves `uid` out (opt-in since 4.0), and so does any roster not naming it.
    ('', '`[roster] checks` leaves `uid` out'),
    ('[roster]\nchecks = ["tres"]\n', '`[roster] checks` leaves `uid` out'),
])
def test_a_retired_destination_is_kept_and_named(tmp_path, toml, says):
    """uid-guard.yml is the consumer's file after the write: a run leaves it
    byte-for-byte and names it retired, every run, written or not — and says
    it is safe to delete ONLY when `check uid` is in the repo's gate."""
    with consumer_repo(tmp_path) as root:
        if toml:
            (root / 'godot-devkit.toml').write_text(toml, encoding='utf-8')
        guard = root / UID_GUARD
        guard.parent.mkdir(parents=True)
        guard.write_text('name: UID Guard\n', encoding='utf-8')
        for _ in range(2):
            code, out, err = run_install()
            assert code == 0, out + err
            line = next(l for l in out.splitlines()
                        if l.startswith(f'[install] retired: {UID_GUARD}'))
            assert says in line, line
            assert ('safe to delete' in line) == ('safe' in says), line
            assert guard.read_text(encoding='utf-8') == 'name: UID Guard\n'


@pytest.mark.parametrize('toml, safe', [('', True), ('[roster]\nchecks = ["uid"]\n', False)])
def test_a_stale_warnings_runner_is_kept_and_named_retired(tmp_path, toml, safe):
    """warnings.sh became `check warnings`: the old runner is no longer written,
    never deleted, and named on every run that finds it."""
    with consumer_repo(tmp_path) as root:
        if toml:
            (root / 'godot-devkit.toml').write_text(toml, encoding='utf-8')
        old = root / 'tools/dev/runners/warnings.sh'
        old.parent.mkdir(parents=True)
        old.write_text('echo old\n', encoding='utf-8')
        code, out, err = run_install()
        assert code == 0, out + err
        line = next(l for l in out.splitlines()
                    if l.startswith('[install] retired: tools/dev/runners/warnings.sh'))
        assert '`check warnings`' in line and ('safe to delete' in line) is safe, line
        assert old.read_text(encoding='utf-8') == 'echo old\n'


@pytest.mark.parametrize('toml', [
    # MN4: a malformed value — a bare string is refused, never iterated.
    '[roster]\nchecks = "uid"\n',
    # #28: an unknown gate. The retired line had its own fallback and said
    # "safe to delete" over a value `check all` refuses at exit 2.
    '[roster]\nchecks = ["uid", "tress"]\n',
])
def test_a_roster_check_all_refuses_is_exit_2_before_any_write(tmp_path, toml):
    with consumer_repo(tmp_path) as root:
        (root / 'godot-devkit.toml').write_text(toml, encoding='utf-8')
        (root / UID_GUARD).parent.mkdir(parents=True)
        (root / UID_GUARD).write_text('name: UID Guard\n', encoding='utf-8')
        with pytest.raises(install.ConfigError) as refused:
            install.all_roster()
        code, out, err = run_install()
        assert code == 2, out + err
        assert str(refused.value) in err and 'nothing was written' in err, err
        assert _snapshot(root) == {}, 'a config refusal wrote'


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
    """The seam, end to end: the include `install-gates` wrote `-include`s the
    tier file this verb wrote, reads its two lists, and `precommit` / `verify`
    name every tier — `make -n`, so nothing boots. The include refuses a tier
    no makefile defines at parse time, so exit 0 here is the whole claim.
    The retired `milestone` alias is not a target."""
    with consumer_repo(tmp_path, makefile=True) as root:
        assert run_install()[0] == 0
        declared: set[str] = set()
        for composition, var in (('precommit', 'GDK_PRECOMMIT_TIERS'),
                                 ('verify', 'GDK_VERIFY_TIERS')):
            tiers = _tiers(var)
            assert tiers, f'{var} is empty'
            declared.update(tiers)
            done = _make_n(root, composition)
            assert done.returncode == 0, done.stdout + done.stderr
            # The sub-make is spelled `${MAKE:-make}` so `-n` runs nothing;
            # the goals after it are the composition.
            assert f'{{MAKE:-make}} check {" ".join(tiers)}' in done.stdout, done.stdout
            # 2.0.0: `precommit` is check + spot and says it is retired, once.
            assert done.stdout.count('[PRECOMMIT] retired') == (composition == 'precommit'), done.stdout
        done = _make_n(root, 'milestone')
        assert done.returncode != 0, done.stdout + done.stderr
        # Every declared tier and every named Godot target is a goal make
        # resolves — `integration-diff` / `integration-all` are the slices
        # the compositions run, `integration` the one a hand takes ARGS to.
        for target in sorted(declared | set(GODOT_TARGETS)):
            done = _make_n(root, target)
            assert done.returncode == 0, f'{target}: {done.stdout}{done.stderr}'


LEGACY_RUN = 'uvx --from "git+https://github.com/cdowin/godot-devkit@v0.25.0" godot-devkit check all'
# A uv.lock whose packages are (some of) these; the kit's entry is what makes
# the tree locked.
OTHER_PACKAGE = '[[package]]\nname = "gdtoolkit"\nversion = "4.3.0"\n'
KIT_PACKAGE = ('[[package]]\nname = "godot-devkit"\nversion = "1.4.0"\n'
               'source = { registry = "https://cdowin.github.io/godot-devkit/simple/" }\n')


@pytest.mark.skipif(shutil.which('make') is None, reason='needs make')
@pytest.mark.parametrize('pin, lock, caller, runs, says', [
    # 1. The caller's GODOT_DEVKIT wins over everything, both pins included.
    (True, True, True, 'my-devkit check all', None),
    # 2. The locked shape: uv.lock names the kit, no Makefile pin.
    (False, True, False, 'uv run --frozen godot-devkit check all', None),
    # 3. The legacy pin, as in 1.3.0 — a lock that names other packages and a
    #    venv holding the kit change nothing and warn nothing.
    (True, False, False, LEGACY_RUN, None),
    # 4. Both pins: the legacy pin still runs (a minor forces no edit), warned.
    (True, True, False, LEGACY_RUN, 'Delete the GODOT_DEVKIT_VERSION line'),
    # 5. Neither: refused, the locked shape named first — a .venv binary with
    #    no lock naming the kit is not a pin.
    (False, False, False, None, 'not pinned — lock it'),
], ids=['caller', 'locked', 'legacy-pin', 'both', 'neither'])
def test_the_tiers_resolve_godot_devkit_in_one_order(tmp_path, pin, lock, caller, runs, says):
    """#38: which godot-devkit `godot-check` runs, decided by the written
    Makefile.tiers at parse time — `make -n`, so nothing runs. Every case
    carries a stale .venv/bin/godot-devkit: the LOCK decides, never the venv."""
    with consumer_repo(tmp_path, makefile=True) as root:
        assert run_install()[0] == 0
        if not pin:
            (root / 'Makefile').write_text(
                CONSUMER_MAKEFILE.replace('GODOT_DEVKIT_VERSION := v0.25.0\n', ''),
                encoding='utf-8')
        (root / 'uv.lock').write_text(
            'version = 1\n\n' + OTHER_PACKAGE + ('\n' + KIT_PACKAGE if lock else ''),
            encoding='utf-8')
        (root / '.venv' / 'bin').mkdir(parents=True)
        (root / '.venv' / 'bin' / 'godot-devkit').write_text('#!/bin/sh\n', encoding='utf-8')
        done = _make_n(root, 'godot-check', *(['GODOT_DEVKIT=my-devkit'] if caller else []))
        if runs is None:
            assert done.returncode != 0 and says in done.stderr, done.stderr
            assert done.stdout == '', done.stdout
            return
        assert done.returncode == 0, done.stderr
        assert f' {runs};' in done.stdout or f' {runs}\n' in done.stdout, done.stdout
        if says:
            assert done.stderr.count(says) == 1, done.stderr
        else:
            assert 'pinned twice' not in done.stderr, done.stderr


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


def test_receipt_keys_on_inputs_not_prose_and_is_shared_by_worktrees(tmp_path):
    """A PASS receipt covers the same content in any worktree of the clone; a
    code edit re-keys it, a docs/ or pm/ edit and a commit do not."""
    repo = tmp_path / 'repo'
    repo.mkdir()
    git = ['git', '-c', 'user.name=t', '-c', 'user.email=t@t', '-C', str(repo)]
    subprocess.run([*git, 'init', '-q'], check=True)
    (repo / 'game.gd').write_text('extends Node\n', encoding='utf-8')
    (repo / 'docs').mkdir()
    (repo / 'docs' / 'a.md').write_text('a\n', encoding='utf-8')
    env = dict(os.environ, GDK_GODOT='no-such-godot')
    env.pop('GDK_RECEIPTS', None)

    def lib(snippet, where=repo):
        return subprocess.run(['bash', '-c', 'source "$1"; ' + snippet, '_', str(LIBRARY)],
                              cwd=where, text=True, capture_output=True, env=env)

    key = lib('gdk_receipt_key unit world').stdout.strip()
    assert len(key) == 40
    assert lib(f'gdk_receipt_hit unit {key}').returncode == 1
    wrote = lib(f'gdk_receipt_write unit {key} "[UNIT] PASS (1/1)" world')
    assert wrote.returncode == 0, wrote.stderr
    # A hit tells a gate wrapper it measured nothing: the file
    # GDK_GATE_UNMEASURED names exists afterwards (gdk#44).
    unmeasured = tmp_path / 'unmeasured'
    env['GDK_GATE_UNMEASURED'] = str(unmeasured)
    hit = lib(f'gdk_receipt_hit unit {key}')
    assert hit.returncode == 0 and '[UNIT] PASS (1/1); reused — receipt' in hit.stdout
    assert unmeasured.exists(), 'a hit left the wrapper to file a cost row'
    del env['GDK_GATE_UNMEASURED']
    # A path a runner names joins the key, even inside an excluded directory.
    env['GDK_RECEIPT_PATHS'] = 'docs/a.md'
    covered = lib('gdk_receipt_key unit world').stdout.strip()
    assert len(covered) == 40 and covered != key
    (repo / 'docs' / 'a.md').write_text('b\n', encoding='utf-8')
    assert lib('gdk_receipt_key unit world').stdout.strip() != covered, 'a covered path moved no key'
    del env['GDK_RECEIPT_PATHS']
    # Prose and a commit move no input.
    subprocess.run([*git, 'add', '-A'], check=True)
    subprocess.run([*git, 'commit', '-qm', 'x'], check=True)
    assert lib('gdk_receipt_key unit world').stdout.strip() == key
    # Another slice is another key; a code edit is a new key.
    assert lib('gdk_receipt_key unit combat').stdout.strip() != key
    # A worktree of the same clone sees the receipt.
    wt = tmp_path / 'wt'
    subprocess.run([*git, 'worktree', 'add', '-q', str(wt)], check=True)
    assert lib('gdk_receipt_key unit world', wt).stdout.strip() == key
    assert lib(f'gdk_receipt_hit unit {key}', wt).returncode == 0
    (repo / 'game.gd').write_text('extends Node2D\n', encoding='utf-8')
    assert lib('gdk_receipt_key unit world').stdout.strip() != key
    # Off means off.
    env['GDK_RECEIPTS'] = '0'
    assert lib('gdk_receipt_key unit world').returncode == 1


# --- install-gates: the framework's two files ---------------------------------
GATES_DESTINATIONS = {'Makefile.gates', 'tools/dev/gdk_gate.sh'}


def run_install_gates(*flags: str) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = install.main_gates(list(flags))
    return code, out.getvalue(), err.getvalue()


def test_install_gates_writes_its_two_files_once_and_a_second_run_is_a_no_op(tmp_path):
    with consumer_repo(tmp_path) as root:
        code, out, err = run_install_gates()
        assert code == 0, out + err
        for rel in sorted(GATES_DESTINATIONS):
            assert f'[install] wrote {rel}' in out, out
        assert not (root / 'Makefile.tiers').exists(), 'install-gates wrote a runner file'
        assert (root / 'Makefile.gates').read_text(encoding='utf-8') == install.body_of('Makefile.gates')
        assert os.access(root / 'tools/dev/gdk_gate.sh', os.X_OK), 'the library landed without its mode'
        before = {rel: (root / rel).read_bytes() for rel in GATES_DESTINATIONS}
        code, out, err = run_install_gates()
        assert code == 0 and 'wrote' not in out, out + err
        assert out.count('already current') == 2, out
        assert before == {rel: (root / rel).read_bytes() for rel in GATES_DESTINATIONS}


def test_install_gates_refuses_a_differing_file_by_name_and_force_replaces_it(tmp_path):
    with consumer_repo(tmp_path) as root:
        run_install_gates()
        gates = root / 'Makefile.gates'
        gates.write_text(gates.read_text(encoding='utf-8') + '\n# mine\n', encoding='utf-8')
        edited = gates.read_bytes()
        code, out, err = run_install_gates()
        assert code == 1, out + err
        assert 'Makefile.gates exists and differs' in err and 'install-gates' in err, err
        assert gates.read_bytes() == edited, 'a refusal wrote'
        code, out, _ = run_install_gates('--diff')
        assert code == 0 and '-# mine' in out, out
        assert gates.read_bytes() == edited, 'a --diff wrote'
        assert run_install_gates('--force')[0] == 0
        assert gates.read_text(encoding='utf-8') == install.body_of('Makefile.gates')


def test_install_gates_rejects_an_unknown_flag_and_names_itself(tmp_path):
    with consumer_repo(tmp_path):
        code, out, err = run_install_gates('--nope')
        assert code == 2 and 'godot-devkit install-gates: unknown flag' in err, err
        assert 'usage: godot-devkit install-gates' in err, err


def test_the_cli_routes_install_gates_and_no_longer_calls_the_old_verbs_agentic_sdlcs(tmp_path):
    from godot_devkit import cli
    with consumer_repo(tmp_path) as root:
        with contextlib.redirect_stdout(io.StringIO()):
            assert cli.main(['install-gates']) == 0
        assert (root / 'Makefile.gates').is_file()
        for verb in ('install-ci', 'install-agents', 'install-hooks', 'install-sdlc'):
            err = io.StringIO()
            with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
                assert cli.main([verb]) == 2
            assert f'unknown command {verb!r}' in err.getvalue(), err.getvalue()
