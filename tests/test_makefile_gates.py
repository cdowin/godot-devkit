"""test_makefile_gates.py — this repo's own targets are quiet, and stay quiet.

The devkit is the first consumer of the library it ships: every gate-shaped
target in the Makefile routes through `gdk_gate_capture` / `gdk_gate_verdict`
out of `installables/gdk_runners.sh`, so the default output is ONE verdict line
naming `.gate-reports/<target>.log`.

That is a contract, not a preference. Before it, an agent running the full gate
here had to invent `… | grep -E "MATRIX|check:doc\\]|check:pm\\] (PASS|FAIL)|
passed|failed" | tail -8` — five output shapes, guessed at, per session.

Two kinds of case, and the split is deliberate: the gate SHAPE is exercised for
REAL — `pyunit` run against a stand-in pytest that prints the summary line and
runs nothing, so the capture, the verdict and the failure excerpt are behavior
rather than a claim — while every target is held by a census over the
Makefile itself. Running the whole suite inside the suite is not a test, and a
census asked of the FILE catches the thing that actually happens: somebody adds
a target and forgets the helper.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from support import REPO_ROOT  # noqa: E402

pytestmark = pytest.mark.skipif(shutil.which('make') is None
                                or shutil.which('bash') is None,
                                reason='needs make and bash')

MAKEFILE = REPO_ROOT / 'Makefile'
# The tiers live on the seam Makefile.devkit `-include`s; the census below
# reads both files this repo owns. Makefile.devkit itself is the pinned
# kit's, held current by `agentic-sdlc adopt`, and is not this file's to census.
OWN_MAKEFILES = (MAKEFILE, REPO_ROOT / 'Makefile.tiers')
# Makefile.tiers opens with the Godot roster `install-runners` writes (held
# byte-current by tests/test_runners_installable.py); its runners live here.
RUNNERS = REPO_ROOT / 'src' / 'godot_devkit' / 'godot' / 'installables'
RUNNER_CALL = re.compile(r'@bash \$\(GDK_RUNNERS_DIR\)/([a-z_]+\.sh)')

# `help`, `pm`, `check`, `precommit` and `milestone` come from the include and
# never appear in the files censused. Two targets this repo's files define
# are NOT gates: `integration-list` prints the roster — the list IS the
# output, and a verdict line would be a line `check test-shape` had to skip —
# and `import-cache` rebuilds the engine's import cache, a tool with an
# outcome rather than a gate with a verdict.
NOT_A_GATE = {'integration-list', 'import-cache'}

# A stand-in pytest: prints the one summary line the tier's `SUM_PYTEST` reads
# back, runs nothing. `GDK_STANDIN_FAIL` makes it red the way pytest is red —
# a `FAILED` line the gate's failure excerpt has to surface, then a non-zero
# exit. The recipe under test is the REAL `pyunit` recipe; only the interpreter
# behind `PYTEST=` is swapped, the same way the matrix cases swap `UV=`.
PYTEST_STANDIN = """\
#!/usr/bin/env bash
echo "stand-in pytest ran with: $*"
if [ -n "${GDK_STANDIN_FAIL:-}" ]; then
  echo "FAILED tests/test_stand_in.py::test_red - assert False"
  echo "1 failed, 2 passed in 0.01s"
  exit 1
fi
echo "3 passed in 0.01s"
"""
STANDIN_RAN = 'stand-in pytest ran with:'


def make(*args: str, **env_extra: str) -> subprocess.CompletedProcess:
    import os
    env = dict(os.environ)
    # Under `make test` the recipe's shell carries MAKELEVEL/MAKEFLAGS, and a
    # sub-make that inherits them announces 'Entering directory' ahead of the
    # one verdict line these tests read. The make under test is a top-level one.
    # VERBOSE is the same shape one layer up: the installed CI exports it for
    # the whole `make milestone` step, so under it every "quiet by default"
    # run below streamed — green under bare pytest, red where CI runs it. The
    # default these tests speak of is VERBOSE UNSET; a case that wants the
    # stream passes VERBOSE='1' explicitly.
    for leaked in ('MAKELEVEL', 'MAKEFLAGS', 'MFLAGS', 'VERBOSE'):
        env.pop(leaked, None)
    env.update(env_extra)
    return subprocess.run(['make', *args], cwd=REPO_ROOT, text=True,
                          capture_output=True, env=env)


def recipes() -> dict[str, str]:
    """Every target in the Makefile mapped to its recipe body.

    Asked of the file rather than of a list in this test: a second roster is
    a roster that goes stale, and the whole point is to catch a target nobody
    remembered to tell this file about.
    """
    found: dict[str, list[str]] = {}
    for makefile in OWN_MAKEFILES:
        current = None
        for line in makefile.read_text(encoding='utf-8').splitlines():
            if line.startswith('\t'):
                if current is not None:
                    found[current].append(line)
                continue
            match = re.match(r'^([a-z][a-z0-9_-]*):(?!=)', line)
            current = match.group(1) if match else None
            if current is not None:
                found.setdefault(current, [])
    return {name: '\n'.join(body) for name, body in found.items()}


# --- the behavior, on the tier every edit runs, behind a stand-in ------------
def unit_run(tmp_path: Path, *args: str, **env_extra: str
             ) -> tuple[subprocess.CompletedProcess, Path, re.Pattern]:
    """`make pyunit` with the stand-in behind PYTEST, logging under tmp_path.

    The report dir is redirected on purpose: this suite runs INSIDE `make
    pyunit`, whose transcript is `.gate-reports/pyunit.log`, and a nested run
    into the same slot would truncate the outer gate's log and hand its
    summary the stand-in's `3 passed`. Returns the run, the log, and the
    verdict shape.
    """
    standin = tmp_path / 'pytest-standin'
    standin.write_text(PYTEST_STANDIN, encoding='utf-8')
    standin.chmod(0o755)
    reports = tmp_path / 'reports'
    done = make('pyunit', f'PYTEST={standin}', *args,
                GDK_GATE_REPORT_DIR=str(reports), **env_extra)
    log = reports / 'pyunit.log'
    verdict = re.compile(rf'^\[PYUNIT\] .+ — full log: {re.escape(str(log))}$')
    return done, log, verdict


def test_a_gate_prints_exactly_one_verdict_line_naming_its_log(tmp_path):
    done, log, verdict = unit_run(tmp_path)
    assert done.returncode == 0, done.stdout + done.stderr
    lines = done.stdout.splitlines()
    assert len(lines) == 1, done.stdout
    assert verdict.match(lines[0]), lines[0]
    assert '3 passed' in lines[0], lines[0]

    assert log.exists(), 'the verdict named a log that was never written'
    assert STANDIN_RAN in log.read_text(encoding='utf-8'), (
        'the transcript the verdict points at does not hold the run')


def test_an_ambient_verbose_does_not_turn_the_quiet_run_loud(tmp_path, monkeypatch):
    """The installed CI exports VERBOSE=1 for the whole `make milestone` step,
    and this suite runs inside it: the static gate printed seven lines there
    and one under bare pytest. The default the case above speaks of is VERBOSE
    UNSET, whatever the environment the suite was started from says."""
    monkeypatch.setenv('VERBOSE', '1')
    test_a_gate_prints_exactly_one_verdict_line_naming_its_log(tmp_path)


def test_verbose_streams_the_transcript_and_still_ends_with_the_verdict(tmp_path):
    done, _, verdict = unit_run(tmp_path, VERBOSE='1')
    assert done.returncode == 0, done.stdout + done.stderr
    lines = done.stdout.splitlines()
    assert len(lines) > 1, 'VERBOSE=1 printed no more than the verdict'
    assert STANDIN_RAN in done.stdout
    assert verdict.match(lines[-1]), lines[-1]


def test_a_failing_gate_shows_what_broke_and_exits_nonzero(tmp_path):
    """The quiet default is only safe if a FAILURE is still legible without
    going to find the log. A verdict alone would have made every red run a
    two-step."""
    done, _, verdict = unit_run(tmp_path, GDK_STANDIN_FAIL='1')
    assert done.returncode != 0
    assert 'FAILED tests/test_stand_in.py::test_red' in done.stdout, (
        done.stdout + done.stderr)
    lines = [ln for ln in done.stdout.splitlines() if ln.startswith('[PYUNIT]')]
    assert len(lines) == 1, done.stdout
    assert verdict.match(lines[0]), lines[0]
    assert 'FAIL' in lines[0] and '1 failed' in lines[0], lines[0]


# --- the census: no target gets to stay loud ---------------------------------
def publishes_a_verdict(body: str) -> bool:
    """Whether this recipe ends in ONE verdict line — by the helper in the
    recipe, or inside the runner it hands off to.

    parse, lint, warnings, unit and import-cache are `@bash <runner>` and
    nothing else: the runner sources the library and publishes its own
    verdict, and wrapping it again would file that verdict in a log nobody
    opens. Derived from the runner's SOURCE rather than allowlisted by name,
    so a runner that stopped publishing would surface here.
    """
    if 'gdk_gate_verdict' in body or '$(call gdk_gate,' in body:
        return True
    handoff = RUNNER_CALL.search(body)
    if handoff is None:
        return False
    runner = RUNNERS / handoff.group(1)
    return runner.is_file() and 'gdk_gate_verdict' in runner.read_text(
        encoding='utf-8')


def test_every_gate_shaped_target_routes_through_the_shipped_helper():
    bodies = recipes()
    gates = {name: body for name, body in bodies.items()
             if body.strip() and name not in NOT_A_GATE}
    assert len(gates) >= 5, (
        f'census collapsed to {sorted(gates)} — a parse that finds no targets '
        f'would pass this file vacuously')
    loud = sorted(name for name, body in gates.items()
                  if not publishes_a_verdict(body))
    assert not loud, (
        f'{loud} print whatever their tool prints instead of one verdict line; '
        f'route them through $(call gdk_gate,...) or gdk_gate_verdict')


def test_the_compositions_are_the_includes_and_not_redefined_here():
    """`check`, `precommit` and `milestone` are Makefile.devkit's — the pinned
    kit's, composed from GDK_PRECOMMIT_TIERS / GDK_MILESTONE_TIERS. A same-named
    target in a file this repo owns would be the fork of the include that
    `[gates] extra` and the tier seam exist to make unnecessary."""
    bodies = recipes()
    forked = sorted(name for name in ('check', 'precommit', 'milestone', 'pm', 'help')
                    if name in bodies)
    assert not forked, f'{forked} redefined outside Makefile.devkit'
    tiers = (REPO_ROOT / 'Makefile.tiers').read_text(encoding='utf-8')
    for name in ('GDK_PRECOMMIT_TIERS', 'GDK_MILESTONE_TIERS'):
        assert re.search(rf'^{name}\s*:?=', tiers, re.M), (
            f'Makefile.tiers no longer declares {name}')


def test_the_makefile_sources_the_shipped_library_not_a_copy():
    """The capture helpers are the pinned kit's, installed beside the include —
    a local `define gate` would let the shipped ones regress with this repo's
    own targets still green."""
    assert 'include Makefile.devkit' in MAKEFILE.read_text(encoding='utf-8')
    assert (REPO_ROOT / 'tools/dev/gdk_gate.sh').exists()
    for makefile in OWN_MAKEFILES:
        assert 'define gate' not in makefile.read_text(encoding='utf-8'), (
            f'{makefile.name} carries its own capture define')


# --- the matrix: which interpreter was handed which command ------------------
# `make matrix` is four real interpreters and a quarter of an hour, so the
# recipe is proven against a STAND-IN `uv` that records the argv it was handed
# and exits 0. The question here is not whether pytest passes on 3.13 — the
# matrix itself answers that — it is WHICH COMMAND each interpreter got, and
# that is the one thing a census over the Makefile text cannot answer. `-m "not
# shell"` has to survive make's expansion, a backslash-continued recipe line and
# the shell's word splitting as ONE argv element; a grep for the string in the
# recipe body would pass just as happily on a recipe that hands pytest `-m not`
# and a positional path called `shell`.
#
# PY_FLOOR / PY_MATRIX are operator configuration, not untrusted input: the
# refusal rows below are the plausible MISTAKE (bumping one without the other,
# a floor that is a prefix of a listed version), not shell injection through a
# make variable, which no recipe in this file survives and none pretends to.
UV_RECORDER = """\
#!/usr/bin/env python3
"a stand-in `uv`: record the argv, run nothing, exit 0."
import json
import os
import sys

with open(os.environ['GDK_ARGV_LOG'], 'a', encoding='utf-8') as handle:
    handle.write(json.dumps(sys.argv[1:]) + '\\n')
"""


def declared(name: str) -> str:
    """A `?=` default read out of the Makefile, like `recipes()` reads bodies.

    Asked of the file for the same reason: a second copy of PY_FLOOR in this
    test is a copy that goes stale, and the interesting failure is the Makefile
    changing under a test that still asserts last month's value.
    """
    match = re.search(rf'^{name}\s*\?=\s*(.*?)\s*$',
                      MAKEFILE.read_text(encoding='utf-8'), re.M)
    assert match, f'{name} is no longer declared in the Makefile'
    return match.group(1)


def pytest_argv(argv: list[str]) -> list[str]:
    """What pytest itself was handed: everything after `-m pytest`.

    The split matters — `python -m pytest` puts a `-m` in the argv that has
    nothing to do with marker selection, and a naive `'-m' in argv` reads it.
    """
    for i in range(len(argv) - 1):
        if argv[i] == '-m' and argv[i + 1] == 'pytest':
            return argv[i + 2:]
    raise AssertionError(f'no `-m pytest` in the recorded argv: {argv}')


def interpreter_of(argv: list[str]) -> str:
    """The `--python <version>` this `uv run` was given."""
    return argv[argv.index('--python') + 1]


def marker_of(argv: list[str]) -> str | None:
    """The marker expression pytest was given, as ONE argv element, or None."""
    args = pytest_argv(argv)
    return args[args.index('-m') + 1] if '-m' in args else None


def matrix_run(tmp_path: Path, *args: str) -> tuple[subprocess.CompletedProcess,
                                                    list[list[str]]]:
    """`make matrix` against the recording stand-in. Returns (proc, argv rows)."""
    recorder = tmp_path / 'uv-recorder'
    recorder.write_text(UV_RECORDER, encoding='utf-8')
    recorder.chmod(0o755)
    argv_log = tmp_path / 'argv.jsonl'
    reports = tmp_path / 'reports'
    done = make('matrix', f'UV={recorder}', *args,
                GDK_ARGV_LOG=str(argv_log), GDK_GATE_REPORT_DIR=str(reports))
    rows = ([json.loads(line) for line in
             argv_log.read_text(encoding='utf-8').splitlines()]
            if argv_log.exists() else [])
    return done, rows


def test_the_floor_is_handed_the_whole_suite_and_the_others_not_shell(tmp_path):
    """~85% of this suite's wall clock is `subprocess`, and a spawn is not
    something a Python version changes. One interpreter runs all of it; the
    others run the part an interpreter can break."""
    done, rows = matrix_run(tmp_path)
    assert done.returncode == 0, done.stdout + done.stderr
    floor, versions = declared('PY_FLOOR'), declared('PY_MATRIX').split()

    assert [interpreter_of(row) for row in rows] == versions, (
        f'the matrix ran {[interpreter_of(r) for r in rows]}, not {versions}')
    full = [interpreter_of(row) for row in rows if marker_of(row) is None]
    assert full == [floor], (
        f'{full} were handed the whole suite; exactly the floor ({floor}) '
        f'should be. Two full passes waste the minutes this exists to save; '
        f'none means the shell slice ran nowhere.')
    for row in rows:
        version = interpreter_of(row)
        if version == floor:
            continue
        assert marker_of(row) == 'not shell', (
            f'python {version} was handed {pytest_argv(row)} — the marker '
            f'expression must arrive as one argv element, or pytest reads '
            f'`shell` as a path and collects nothing')


def test_the_floor_is_the_declared_one_not_merely_the_first_listed(tmp_path):
    """The rule is `== PY_FLOOR`, and a recipe that just gave the first
    iteration the full pass would be green on this repo's own defaults."""
    done, rows = matrix_run(tmp_path, 'PY_FLOOR=3.12', 'PY_MATRIX=3.11 3.12 3.13')
    assert done.returncode == 0, done.stdout + done.stderr
    assert [interpreter_of(row) for row in rows] == ['3.11', '3.12', '3.13']
    assert [interpreter_of(r) for r in rows if marker_of(r) is None] == ['3.12']


def test_a_floor_listed_twice_still_buys_exactly_one_full_pass(tmp_path):
    done, rows = matrix_run(tmp_path, 'PY_FLOOR=3.11', 'PY_MATRIX=3.11 3.11 3.12')
    assert done.returncode == 0, done.stdout + done.stderr
    assert len(rows) == 3
    assert [marker_of(row) for row in rows] == [None, 'not shell', 'not shell'], (
        'the FIRST occurrence of the floor takes the full pass; a repeat is '
        'another interpreter run, not a second full suite')


def test_the_transcript_says_what_each_interpreter_ran(tmp_path):
    """`matrix.log` is what a red run gets read for. A header that says only
    `=== python 3.13 ===` leaves the reader unable to tell a count that dropped
    because the slice skipped it from a count that dropped because tests
    vanished."""
    done, _ = matrix_run(tmp_path)
    assert done.returncode == 0, done.stdout + done.stderr
    transcript = (tmp_path / 'reports' / 'matrix.log').read_text(encoding='utf-8')
    floor = declared('PY_FLOOR')
    for version in declared('PY_MATRIX').split():
        ran = 'the whole suite' if version == floor else '-m "not shell"'
        assert f'=== python {version} ({ran}) ===' in transcript, transcript


def test_the_verdict_line_did_not_move(tmp_path):
    """The consumer-visible shape. CI reads this line and nothing else, so the
    slice is invisible from outside: same tag, same message, same log clause."""
    done, _ = matrix_run(tmp_path)
    assert done.returncode == 0, done.stdout + done.stderr
    lines = done.stdout.splitlines()
    assert len(lines) == 1, done.stdout
    assert lines[0] == (f'[MATRIX] PASS on {declared("PY_MATRIX")} '
                        f'— full log: {tmp_path / "reports" / "matrix.log"}')


# --- the refusal matrix: no configuration silently skips the full pass --------
@pytest.mark.parametrize('why, floor, versions', [
    ('the floor was bumped and the matrix was not', '3.99', '3.11 3.12 3.13 3.14'),
    ('an empty matrix has nowhere to run anything', '3.11', ''),
    ('an empty floor names no interpreter at all', '', '3.11 3.12'),
    ('a floor that is only a PREFIX of a listed version', '3.1', '3.11 3.12'),
    ('a floor that is only a SUFFIX of a listed version', '11', '3.11 3.12'),
    ('a floor glued to its neighbour', '3.11 3.12', '3.11 3.12'),
    ('a glob is not an interpreter roster', '3.11', '*'),
])
def test_a_floor_outside_the_matrix_is_refused_before_anything_runs(
        tmp_path, why, floor, versions):
    """The failure this whole change could introduce: a matrix in which nobody
    runs the `shell` slice, printing PASS over a suite that never ran. It is
    refused by name, ahead of the first interpreter, and NOTHING is spawned."""
    done, rows = matrix_run(tmp_path, f'PY_FLOOR={floor}', f'PY_MATRIX={versions}')
    assert done.returncode == 2, (
        f'{why}: exited {done.returncode}\n{done.stdout}{done.stderr}')
    assert rows == [], f'{why}: refused, but {len(rows)} interpreter(s) ran anyway'
    output = done.stdout + done.stderr
    assert f'PY_FLOOR "{floor}"' in output, f'{why}: the floor is unnamed\n{output}'
    assert f'PY_MATRIX "{versions}"' in output, f'{why}: the matrix is unnamed\n{output}'


def test_the_refusal_is_one_verdict_line_like_every_other_gate(tmp_path):
    done, _ = matrix_run(tmp_path, 'PY_FLOOR=3.99')
    lines = done.stdout.splitlines()
    assert len(lines) == 1, done.stdout
    assert lines[0].startswith('[MATRIX] '), lines[0]
    assert lines[0].endswith(f'— full log: {tmp_path / "reports" / "matrix.log"}')
