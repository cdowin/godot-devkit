"""test_makefile_gates.py — this repo's own targets are quiet, and stay quiet.

The devkit is the first consumer of the library it ships: every gate-shaped
target in the Makefile routes through `gdk_gate_capture` / `gdk_gate_verdict`
out of `installables/gdk_runners.sh`, so the default output is ONE verdict line
naming `.gate-reports/<target>.log`.

That is a contract, not a preference. Before it, an agent running the full gate
here had to invent `… | grep -E "MATRIX|smoke\\]|check:doc\\]|check:pm\\] (PASS|
FAIL)|passed|failed" | tail -8` — five output shapes, guessed at, per session.

Two kinds of case, and the split is deliberate: `gates` is exercised for REAL
(it runs in under a second, and behavior is the only proof that matters), while
the slow targets — `test`, `matrix`, `smoke` — are held by a census over the
Makefile itself. Running the whole suite inside the suite is not a test, and a
census asked of the FILE catches the thing that actually happens: somebody adds
a target and forgets the helper.
"""
from __future__ import annotations

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
VERDICT = re.compile(r'^\[GATES\] .+ — full log: \.gate-reports/gates\.log$')

# `help` prints the target roster and is not a gate; `precommit` and
# `milestone` are compositions whose members each print their own verdict.
NOT_A_GATE = {'help', 'precommit', 'milestone'}


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
    current = None
    for line in MAKEFILE.read_text(encoding='utf-8').splitlines():
        if line.startswith('\t'):
            if current is not None:
                found[current].append(line)
            continue
        match = re.match(r'^([a-z][a-z0-9_-]*):(?!=)', line)
        current = match.group(1) if match else None
        if current is not None:
            found.setdefault(current, [])
    return {name: '\n'.join(body) for name, body in found.items()}


# --- the behavior, on the one target fast enough to prove it -----------------
def test_a_gate_prints_exactly_one_verdict_line_naming_its_log():
    done = make('gates')
    assert done.returncode == 0, done.stdout + done.stderr
    lines = done.stdout.splitlines()
    assert len(lines) == 1, done.stdout
    assert VERDICT.match(lines[0]), lines[0]

    log = REPO_ROOT / '.gate-reports' / 'gates.log'
    assert log.exists(), 'the verdict named a log that was never written'
    assert '[check:doc]' in log.read_text(encoding='utf-8'), (
        'the transcript the verdict points at does not hold the run')


def test_an_ambient_verbose_does_not_turn_the_quiet_run_loud(monkeypatch):
    """The installed CI exports VERBOSE=1 for the whole `make milestone` step,
    and this suite runs inside it: `make gates` printed seven lines there and
    one under bare pytest. The default the case above speaks of is VERBOSE
    UNSET, whatever the environment the suite was started from says."""
    monkeypatch.setenv('VERBOSE', '1')
    test_a_gate_prints_exactly_one_verdict_line_naming_its_log()


def test_verbose_streams_the_transcript_and_still_ends_with_the_verdict():
    done = make('gates', VERBOSE='1')
    assert done.returncode == 0, done.stdout + done.stderr
    lines = done.stdout.splitlines()
    assert len(lines) > 1, 'VERBOSE=1 printed no more than the verdict'
    assert '[check:doc]' in done.stdout
    assert VERDICT.match(lines[-1]), lines[-1]


def test_a_failing_gate_shows_what_broke_and_exits_nonzero():
    """The quiet default is only safe if a FAILURE is still legible without
    going to find the log. A verdict alone would have made every red run a
    two-step."""
    devkit = f'env PYTHONPATH={REPO_ROOT}/src python3 -m godot_devkit.cli check nosuchcheck'
    done = make('gates', f'DEVKIT={devkit}')
    assert done.returncode != 0
    assert 'nosuchcheck' in done.stdout + done.stderr, done.stdout + done.stderr
    verdict = [ln for ln in done.stdout.splitlines() if ln.startswith('[GATES]')]
    assert len(verdict) == 1, done.stdout
    assert 'FAIL' in verdict[0], verdict[0]


# --- the census: no target gets to stay loud ---------------------------------
def test_every_gate_shaped_target_routes_through_the_shipped_helper():
    bodies = recipes()
    gates = {name: body for name, body in bodies.items()
             if body.strip() and name not in NOT_A_GATE}
    assert len(gates) >= 5, (
        f'census collapsed to {sorted(gates)} — a parse that finds no targets '
        f'would pass this file vacuously')
    loud = sorted(name for name, body in gates.items()
                  if 'gdk_gate_verdict' not in body and '$(call gate,' not in body)
    assert not loud, (
        f'{loud} print whatever their tool prints instead of one verdict line; '
        f'route them through $(call gate,...) or gdk_gate_verdict')


def test_the_compositions_add_no_output_of_their_own():
    """`milestone` is `gates matrix smoke` and nothing else: three verdict
    lines, one per member. A composition that echoed a banner would be the
    first line of the noise coming back."""
    bodies = recipes()
    for name in ('precommit', 'milestone'):
        assert bodies[name].strip() == '', f'{name} grew a recipe: {bodies[name]}'


def test_the_makefile_sources_the_shipped_library_not_a_copy():
    """Self-hosting is the point — a local fork of the helpers would let the
    shipped ones regress with this repo's own targets still green."""
    text = MAKEFILE.read_text(encoding='utf-8')
    assert 'src/godot_devkit/repo/installables/gdk_runners.sh' in text
    assert (REPO_ROOT / 'src/godot_devkit/repo/installables/gdk_runners.sh').exists()
