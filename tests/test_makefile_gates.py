"""test_makefile_gates.py — the gate framework (Makefile.gates), this repo's own
tiers, and the seam between them.

Three things are held here. The Godot roster that opens Makefile.tiers is what
`install-runners` writes, and its `godot-check` target is how a consumer joins
the eight gates to `make check` (GDK_CHECKS): that target is run for real over
the committed clean Godot project, because a census over the file could not
prove it fires. Every gate-shaped target this repo's files define routes
through the capture library (`gdk_gate_capture` / `gdk_gate_verdict`), while
the compositions (`check`, `precommit`, `verify`) are Makefile.gates' alone and
are not redefined in the other two files — a census asked of the FILES, because
the thing that actually happens is somebody adding a target and forgetting the
helper. And the installables `install-gates` and `install-runners` write run
`make help`, `make check` and `make precommit` in a project with agentic-sdlc
NOT installed and no Godot binary: the fixture test at the bottom.
"""
from __future__ import annotations

import contextlib
import io
import os
import re
import shutil
import subprocess
import tomllib

import pytest

from support import REPO_ROOT

pytestmark = pytest.mark.skipif(shutil.which('make') is None or shutil.which('bash') is None,
                                reason='needs make and bash')

MAKEFILE = REPO_ROOT / 'Makefile'
# The tiers live on the seam Makefile.gates `-include`s; the census reads the
# three files this repo owns.
GATES = REPO_ROOT / 'Makefile.gates'
OWN_MAKEFILES = (MAKEFILE, GATES, REPO_ROOT / 'Makefile.tiers')
RUNNERS = REPO_ROOT / 'src' / 'godot_devkit' / 'godot' / 'installables'
RUNNER_CALL = re.compile(r'@bash \$\(GDK_RUNNERS_DIR\)/([a-z_]+\.sh)')
GODOT_GATES = ('uid', 'tres', 'props', 'defaults', 'rng', 'tres-comment', 'unit-disk', 'test-shape')
# Targets this repo's files define that are NOT gates: `integration-list`
# prints the roster — the list IS the output — `import-cache` rebuilds the
# engine's import cache, a tool with an outcome rather than a gate with a
# verdict, `gdk-precommit-retired` and the `gdk-tiers-*` notices are one line
# each, `help` prints the target list, and the compositions (`check`,
# `precommit`, `verify`, the deprecated `milestone`) print their members'
# verdicts and their own through the `gdk_composition` define.
COMPOSITIONS = ('check', 'precommit', 'verify', 'milestone')
NOT_A_GATE = {'integration-list', 'import-cache', 'gdk-precommit-retired', 'help',
              'gdk-tiers-none-precommit', 'gdk-tiers-none-verify',
              'gdk-tiers-skipped-verify', *COMPOSITIONS}


def make(*args: str, **env_extra: str) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    # Under `make test` the recipe's shell carries MAKELEVEL/MAKEFLAGS, and a
    # sub-make that inherits them announces 'Entering directory' ahead of the
    # one verdict line read here. The make under test is a top-level one.
    for leaked in ('MAKELEVEL', 'MAKEFLAGS', 'MFLAGS', 'VERBOSE'):
        env.pop(leaked, None)
    env.update(env_extra)
    return subprocess.run(['make', *args], cwd=REPO_ROOT,
                          text=True, capture_output=True, env=env)


def recipes() -> dict[str, str]:
    """Every target in the files this repo owns, mapped to its recipe body —
    asked of the file, because a second roster is a roster that goes stale."""
    return recipes_of(*OWN_MAKEFILES)


def recipes_of(*makefiles) -> dict[str, str]:
    found: dict[str, list[str]] = {}
    for makefile in makefiles:
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


def publishes_a_verdict(body: str) -> bool:
    """ONE verdict line — by the helper in the recipe, or inside the runner it
    hands off to (`@bash <runner>` and nothing else: the runner sources the
    library and publishes its own; derived from the runner's SOURCE, so a
    runner that stopped publishing would surface here)."""
    if 'gdk_gate_verdict' in body or '$(call gdk_gate,' in body:
        return True
    handoff = RUNNER_CALL.search(body)
    return (handoff is not None and (RUNNERS / handoff.group(1)).is_file()
            and 'gdk_gate_verdict' in (RUNNERS / handoff.group(1)).read_text(encoding='utf-8'))


def test_godot_check_runs_the_eight_gates_and_is_what_make_check_carries(tmp_path):
    """`godot-devkit check all` over the committed clean Godot project: one
    `[GODOT]` verdict line, nothing else on stdout, and the transcript says all
    eight ran. GDK_CHECKS is how `make check` picks it up, so the joining is
    asserted of the Makefile."""
    reports = tmp_path / 'reports'
    done = make('godot-check', GDK_GATE_REPORT_DIR=str(reports))
    assert done.returncode == 0, done.stdout + done.stderr
    assert done.stdout.splitlines() == [
        f'[GODOT] {len(GODOT_GATES)} check(s) PASS — full log: {reports / "godot-check.log"}'
    ], done.stdout
    transcript = (reports / 'godot-check.log').read_text(encoding='utf-8')
    assert all(f'[check:{gate}] PASS' in transcript for gate in GODOT_GATES), transcript
    assert re.search(r'^GDK_CHECKS\s*:=.*\bgodot-check\b', MAKEFILE.read_text(encoding='utf-8'), re.M), (
        '`make check` no longer carries the Godot roster: GDK_CHECKS in the Makefile')


def test_every_gate_routes_through_the_shipped_helper_and_the_compositions_stay_the_includes():
    bodies = recipes()
    gates = {name: body for name, body in bodies.items() if body.strip() and name not in NOT_A_GATE}
    assert len(gates) >= 5, f'census collapsed to {sorted(gates)} — a parse that finds no ' \
                            'targets would pass this file vacuously'
    loud = sorted(name for name, body in gates.items() if not publishes_a_verdict(body))
    assert not loud, (f'{loud} print whatever their tool prints instead of one verdict line; '
                      'route them through $(call gdk_gate,...) or gdk_gate_verdict')
    # A composition WITH A RECIPE in the Makefile or Makefile.tiers, or a local
    # `define gate`, would be the fork of Makefile.gates that GDK_CHECKS exists
    # to make unnecessary — one under which the shipped helpers could regress
    # unseen. A prerequisite-only rule (`precommit: gdk-precommit-retired`)
    # adds to the include's target and replaces nothing.
    for makefile in (MAKEFILE, REPO_ROOT / 'Makefile.tiers'):
        forked = sorted(name for name in (*COMPOSITIONS, 'help') if recipes_of(makefile).get(name, '').strip())
        assert not forked, f'{forked} redefined outside Makefile.gates, in {makefile.name}'
    assert 'include Makefile.gates' in MAKEFILE.read_text(encoding='utf-8')
    assert (REPO_ROOT / 'tools/dev/gdk_gate.sh').exists()
    for makefile in OWN_MAKEFILES:
        assert 'define gate\n' not in makefile.read_text(encoding='utf-8'), makefile.name


# --- the installables, run: no agentic-sdlc, no Godot binary ------------------
# `install-gates` and `install-runners` write Makefile.gates, gdk_gate.sh and
# the runners into a copy of the committed clean Godot project. The game's
# Makefile lists one dummy gate in GDK_CHECKS and replaces the Godot tiers with
# one dummy tier, so nothing here boots an engine; what is under test is the
# framework (`help`, `check`, `precommit`, `verify`, the `milestone` alias).
# Run in CI as part of the suite: it needs only make, bash and git.
FIXTURE = REPO_ROOT / 'tests' / 'fixtures' / 'godot_project'
GAME_MAKEFILE = """\
GDK_CHECKS := dummy
GODOT_DEVKIT := true
include Makefile.gates

dummy:
\t$(call gdk_gate,dummy,DUMMY,$(GDK_SUM_TAIL),sh -c 'echo "[dummy] ran"; exit $(DUMMY_EXIT)')

tier-a:
\t@echo tier-a ran

DUMMY_EXIT ?= 0
GDK_PRECOMMIT_TIERS := tier-a
GDK_VERIFY_TIERS := tier-a
"""


@pytest.fixture
def game(tmp_path):
    """The fixture project, as a git repo, with both installers run in it."""
    root = tmp_path / 'game'
    shutil.copytree(FIXTURE, root)
    subprocess.run(['git', 'init', '-q'], cwd=root, check=True)
    (root / 'Makefile').write_text(GAME_MAKEFILE, encoding='utf-8')
    from godot_devkit.godot import install
    previous = os.getcwd()
    os.chdir(root)
    from godot_devkit.core.project import load_config, repo_root
    repo_root.cache_clear()
    load_config.cache_clear()
    try:
        for verb in (install.main_gates, install.main):
            with contextlib.redirect_stdout(io.StringIO()):
                assert verb([]) == 0
    finally:
        os.chdir(previous)
    from godot_devkit.core.project import load_config, repo_root
    repo_root.cache_clear()
    load_config.cache_clear()
    return root


def game_make(root, *args: str, **env_extra: str) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items()
           if k not in ('MAKELEVEL', 'MAKEFLAGS', 'MFLAGS', 'VERBOSE', 'GDK_CHECKS')}
    env.update(env_extra)
    return subprocess.run(['make', *args], cwd=root, text=True, capture_output=True, env=env)


def test_the_installed_gates_run_with_neither_agentic_sdlc_nor_godot(game):
    assert (game / 'Makefile.gates').is_file() and (game / 'tools/dev/gdk_gate.sh').is_file()
    assert not (game / 'devkit.toml').exists() and not (game / 'uv.lock').exists()

    done = game_make(game, 'help')
    assert done.returncode == 0, done.stdout + done.stderr
    plain = re.sub(r'\x1b\[[0-9;]*m', '', done.stdout)
    for target in ('check', 'precommit', 'verify', 'milestone'):
        assert re.search(rf'^  {target}\s', plain, re.M), (target, plain)
    assert 'agentic' not in plain.lower()
    assert 'check runs: shell dummy' in plain, plain

    done = game_make(game, 'check')
    assert done.returncode == 0, done.stdout + done.stderr
    lines = done.stdout.splitlines()
    assert lines[-1] == '[CHECK] PASS — 2 gate(s)', done.stdout
    assert any(l.startswith('[SHELL] PASS (0 scripts)') for l in lines), done.stdout
    assert any(l.startswith('[DUMMY] ran') or l.startswith('[DUMMY]') for l in lines), done.stdout
    assert (game / '.gate-reports' / 'dummy.log').is_file()

    done = game_make(game, 'precommit')
    assert done.returncode == 0, done.stdout + done.stderr
    assert 'tier-a ran' in done.stdout and '[CHECK] PASS — 2 gate(s)' in done.stdout, done.stdout

    done = game_make(game, 'verify')
    assert done.returncode == 0, done.stdout + done.stderr
    assert 'tier-a ran' in done.stdout, done.stdout

    # GDK_VERIFY_SKIP leaves a tier out, and says so. Asked of the tier file
    # `install-runners` wrote, with the game's own tier override removed
    # (`make -n`: no engine boots).
    (game / 'Makefile').write_text(GAME_MAKEFILE.split('GDK_PRECOMMIT_TIERS := tier-a')[0],
                                   encoding='utf-8')
    done = game_make(game, 'verify', '-n', GDK_VERIFY_SKIP='unit')
    assert done.returncode == 0, done.stdout + done.stderr
    assert '[TIERS] verify skips [unit]' in done.stdout, done.stdout
    assert 'unit' not in re.search(r'check ([^\n"]*)', done.stdout.split('${MAKE:-make}')[1]).group(1).split(), done.stdout

    # `milestone` is a deprecated alias of `verify`: the same goals.
    done = game_make(game, 'milestone', '-n')
    assert done.returncode == 0, done.stdout + done.stderr
    assert '${MAKE:-make} check parse lint warnings unit integration-all' in done.stdout, done.stdout


def test_a_red_gate_fails_check_and_names_itself_and_the_rest_still_run(game):
    done = game_make(game, 'check', DUMMY_EXIT='3')
    assert done.returncode != 0, done.stdout
    assert done.stdout.splitlines()[-1] == '[CHECK] FAIL — 1 of 2 gate(s) failed: dummy', done.stdout
    assert '[SHELL] PASS' in done.stdout, 'a red gate must not stop the next one'
    # `verify` is red too, and its tier never runs on a red check.
    done = game_make(game, 'verify', DUMMY_EXIT='3')
    assert done.returncode != 0, done.stdout


@pytest.mark.skipif(shutil.which('shellcheck') is None, reason='needs shellcheck')
def test_the_shell_gate_runs_shellcheck_over_tracked_scripts_only(game):
    (game / 'ok.sh').write_text('#!/usr/bin/env bash\necho ok\n', encoding='utf-8')
    (game / 'bad.sh').write_text('#!/usr/bin/env bash\nrm $UNQUOTED\n', encoding='utf-8')
    done = game_make(game, 'shell')
    assert done.returncode == 0 and '(0 scripts)' in done.stdout, done.stdout  # untracked: not scanned
    subprocess.run(['git', 'add', 'ok.sh'], cwd=game, check=True)
    done = game_make(game, 'shell')
    assert done.returncode == 0 and '[SHELL] PASS (1 scripts)' in done.stdout, done.stdout
    subprocess.run(['git', 'add', 'bad.sh'], cwd=game, check=True)
    done = game_make(game, 'shell')
    assert done.returncode != 0 and '[SHELL] FAIL' in done.stdout, done.stdout


def test_a_missing_shellcheck_fails_the_shell_gate_when_a_script_is_tracked(game):
    (game / 'ok.sh').write_text('#!/usr/bin/env bash\necho ok\n', encoding='utf-8')
    subprocess.run(['git', 'add', 'ok.sh'], cwd=game, check=True)
    done = game_make(game, 'shell', GDK_SHELLCHECK='no-such-shellcheck-binary')
    assert done.returncode == 2, done.stdout + done.stderr
    assert 'is not on PATH' in done.stdout, done.stdout


def test_the_installables_are_the_repos_own_copies():
    """This repo is a consumer of its own installables: Makefile.gates and
    tools/dev/gdk_gate.sh are byte-for-byte what `install-gates` writes."""
    from godot_devkit.godot import install
    assert GATES.read_text(encoding='utf-8') == install.body_of('Makefile.gates')
    assert (REPO_ROOT / 'tools/dev/gdk_gate.sh').read_text(encoding='utf-8') == install.body_of('gdk_gate.sh')
    assert dict(install.GATES_PLAN) == {'Makefile.gates': 'Makefile.gates', 'gdk_gate.sh': 'tools/dev/gdk_gate.sh'}


def test_the_gate_library_corpus_passes():
    done = subprocess.run(['bash', str(REPO_ROOT / 'tools/dev/gdk_gate.sh'), '--self-test'],
                          text=True, capture_output=True, env={**os.environ, 'GDK_ST_SKIP_TIMING': '1'})
    assert done.returncode == 0, done.stdout + done.stderr
    assert 'SELF-TEST OK' in done.stdout, done.stdout


def test_integration_all_passes_gdk_shard_to_the_runner(game):
    """`make integration-all GDK_SHARD=i/n` is `integration.sh --all --shard i/n`;
    without it the recipe is the plain `--all` (`make -n`: no engine boots)."""
    (game / 'Makefile').write_text(GAME_MAKEFILE.split('GDK_PRECOMMIT_TIERS := tier-a')[0],
                                   encoding='utf-8')
    done = game_make(game, 'integration-all', '-n', GDK_SHARD='2/6')
    assert done.returncode == 0, done.stdout + done.stderr
    assert re.search(r'integration\.sh --all --shard 2/6\b', done.stdout), done.stdout
    done = game_make(game, 'integration-all', '-n')
    assert re.search(r'integration\.sh --all(?! --shard)', done.stdout), done.stdout
