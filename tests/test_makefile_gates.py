"""test_makefile_gates.py — this repo's own tiers, on the seam the pinned include reads.

Two things here are this repo's, and both are held. The Godot roster that
opens Makefile.tiers is what `install-runners` writes, and its `godot-check`
target is how a consumer joins the eight gates to `make check` (`[gates]
extra`): that target is run for real over the committed clean Godot project,
because a census over the file could not prove it fires. Below the roster are
the Python tiers, and the one with a failure mode of its own is `matrix`: an
interpreter list in which nobody runs the `shell` slice would print PASS over
a suite that never ran (rule 4), so WHICH command each interpreter was handed
is proven against a stand-in `uv`, and a floor outside the matrix is refused
by name before anything is spawned.

The capture library (`gdk_gate_capture` / `gdk_gate_verdict`) is agentic-sdlc's,
installed beside the include and proven there. This file holds only that every
gate-shaped target of this repo's routes through it, and that the compositions
(`check`, `precommit`, `milestone`) are the include's and not redefined here —
a census asked of the FILES, because the thing that actually happens is
somebody adding a target and forgetting the helper.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tomllib
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
GODOT_GATES = ('uid', 'tres', 'props', 'defaults', 'rng', 'tres-comment',
               'unit-disk', 'test-shape')

# `help`, `pm`, `check`, `precommit` and `milestone` come from the include and
# never appear in the files censused. Two targets this repo's files define
# are NOT gates: `integration-list` prints the roster — the list IS the
# output, and a verdict line would be a line `check test-shape` had to skip —
# and `import-cache` rebuilds the engine's import cache, a tool with an
# outcome rather than a gate with a verdict.
NOT_A_GATE = {'integration-list', 'import-cache'}


def make(*args: str, **env_extra: str) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    # Under `make test` the recipe's shell carries MAKELEVEL/MAKEFLAGS, and a
    # sub-make that inherits them announces 'Entering directory' ahead of the
    # one verdict line these tests read. The make under test is a top-level
    # one, and the default it speaks of is VERBOSE UNSET, whatever the
    # environment the suite was started from exports.
    for leaked in ('MAKELEVEL', 'MAKEFLAGS', 'MFLAGS', 'VERBOSE'):
        env.pop(leaked, None)
    env.update(env_extra)
    # `GDK_LEDGER_CMD=` (empty) on the command line beats the include's `?=`
    # and the library files no cost row: a matrix run against a stand-in `uv`
    # is not a measurement, and a row saying `matrix PASS 0.3s` in the
    # milestone's ledger is exactly the lie `check budget` would then grade.
    return subprocess.run(['make', *args, 'GDK_LEDGER_CMD='], cwd=REPO_ROOT,
                          text=True, capture_output=True, env=env)


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


# --- the Godot roster's gate, run for real -----------------------------------
def test_godot_check_runs_the_eight_gates_and_is_what_make_check_carries(tmp_path):
    """`godot-check` is Makefile.tiers' target — `install-runners` writes it —
    and `godot-devkit check all` over the committed clean Godot project is
    what it runs: one `[GODOT]` verdict line, nothing else on stdout, and the
    transcript says all eight ran. `[gates] extra` is how this repo's `make
    check` picks it up; that seam is the pinned include's, so the joining is
    asserted of devkit.toml rather than by running the other kit's roster."""
    reports = tmp_path / 'reports'
    done = make('godot-check', GDK_GATE_REPORT_DIR=str(reports))
    assert done.returncode == 0, done.stdout + done.stderr
    assert done.stdout.splitlines() == [
        f'[GODOT] {len(GODOT_GATES)} check(s) PASS — full log: '
        f'{reports / "godot-check.log"}'], done.stdout
    transcript = (reports / 'godot-check.log').read_text(encoding='utf-8')
    for gate in GODOT_GATES:
        assert f'[check:{gate}] PASS' in transcript, gate

    config = tomllib.loads((REPO_ROOT / 'devkit.toml').read_text(encoding='utf-8'))
    assert 'godot-check' in config['gates']['extra'], (
        '`make check` no longer carries the Godot roster: [gates] extra is '
        f'{config["gates"].get("extra")}')


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


def test_the_compositions_and_the_capture_library_are_the_pinned_includes():
    """`check`, `precommit` and `milestone` are Makefile.devkit's — the pinned
    kit's, composed from GDK_PRECOMMIT_TIERS / GDK_MILESTONE_TIERS — and so
    are the capture helpers, installed beside it. A same-named target, or a
    local `define gate`, in a file this repo owns would be the fork of the
    include that `[gates] extra` and the tier seam exist to make unnecessary,
    and one under which the shipped helpers could regress with this repo's
    own targets still green."""
    bodies = recipes()
    forked = sorted(name for name in ('check', 'precommit', 'milestone', 'pm', 'help')
                    if name in bodies)
    assert not forked, f'{forked} redefined outside Makefile.devkit'
    assert 'include Makefile.devkit' in MAKEFILE.read_text(encoding='utf-8')
    assert (REPO_ROOT / 'tools/dev/gdk_gate.sh').exists()
    tiers = (REPO_ROOT / 'Makefile.tiers').read_text(encoding='utf-8')
    for name in ('GDK_PRECOMMIT_TIERS', 'GDK_MILESTONE_TIERS'):
        assert re.search(rf'^{name}\s*:?=', tiers, re.M), (
            f'Makefile.tiers no longer declares {name}')
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
    """Most of this suite's wall clock is `subprocess`, and a spawn is not
    something a Python version changes. One interpreter runs all of it; the
    others run the part an interpreter can break. The floor is set to the
    SECOND listed on purpose: the rule is `== PY_FLOOR`, and a recipe that
    simply gave the first iteration the full pass would be green on this
    repo's own defaults."""
    floor, versions = '3.12', ['3.11', '3.12', '3.13']
    done, rows = matrix_run(tmp_path, f'PY_FLOOR={floor}',
                            f'PY_MATRIX={" ".join(versions)}')
    assert done.returncode == 0, done.stdout + done.stderr

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


# --- the refusal: no configuration silently skips the full pass --------------
# Three rows, one per way the comparison could be written wrong: an exact
# mismatch (the floor bumped and the matrix not), a floor that is a PREFIX of
# a listed version (what a substring match accepts), and a glob for a roster
# (what a `case` pattern accepts). The other spellings of "not listed" — an
# empty floor, an empty matrix, a suffix — reach the same branch by the same
# comparison and add no failure mode.
@pytest.mark.parametrize('why, floor, versions', [
    ('the floor was bumped and the matrix was not', '3.99', '3.11 3.12 3.13 3.14'),
    ('a floor that is only a PREFIX of a listed version', '3.1', '3.11 3.12'),
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
