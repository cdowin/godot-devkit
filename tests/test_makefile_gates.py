"""test_makefile_gates.py — this repo's own tiers, on the seam the pinned include reads.

Two things here are this repo's, and both are held. The Godot roster that
opens Makefile.tiers is what `install-runners` writes, and its `godot-check`
target is how a consumer joins the eight gates to `make check` (`[gates]
extra`): that target is run for real over the committed clean Godot project,
because a census over the file could not prove it fires. And every
gate-shaped target this repo's files define routes through the capture
library (`gdk_gate_capture` / `gdk_gate_verdict` — agentic-sdlc's, installed
beside the include and proven there), while the compositions (`check`,
`precommit`, `milestone`) stay the include's and are not redefined here — a
census asked of the FILES, because the thing that actually happens is
somebody adding a target and forgetting the helper.
"""
from __future__ import annotations

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
# The tiers live on the seam Makefile.devkit `-include`s; the census reads both
# files this repo owns. Makefile.devkit itself is the pinned kit's.
OWN_MAKEFILES = (MAKEFILE, REPO_ROOT / 'Makefile.tiers')
RUNNERS = REPO_ROOT / 'src' / 'godot_devkit' / 'godot' / 'installables'
RUNNER_CALL = re.compile(r'@bash \$\(GDK_RUNNERS_DIR\)/([a-z_]+\.sh)')
GODOT_GATES = ('uid', 'tres', 'props', 'defaults', 'rng', 'tres-comment', 'unit-disk', 'test-shape')
# Two targets this repo's files define are NOT gates: `integration-list`
# prints the roster — the list IS the output — and `import-cache` rebuilds the
# engine's import cache, a tool with an outcome rather than a gate with a verdict.
NOT_A_GATE = {'integration-list', 'import-cache'}


def make(*args: str, **env_extra: str) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    # Under `make test` the recipe's shell carries MAKELEVEL/MAKEFLAGS, and a
    # sub-make that inherits them announces 'Entering directory' ahead of the
    # one verdict line read here. The make under test is a top-level one.
    for leaked in ('MAKELEVEL', 'MAKEFLAGS', 'MFLAGS', 'VERBOSE'):
        env.pop(leaked, None)
    env.update(env_extra)
    # `GDK_LEDGER_CMD=` (empty) beats the include's `?=` so a test run files no
    # cost row in the milestone ledger `check budget` would then grade.
    return subprocess.run(['make', *args, 'GDK_LEDGER_CMD='], cwd=REPO_ROOT,
                          text=True, capture_output=True, env=env)


def recipes() -> dict[str, str]:
    """Every target in the files this repo owns, mapped to its recipe body —
    asked of the file, because a second roster is a roster that goes stale."""
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
    eight ran. `[gates] extra` is how `make check` picks it up; that seam is the
    pinned include's, so the joining is asserted of devkit.toml."""
    reports = tmp_path / 'reports'
    done = make('godot-check', GDK_GATE_REPORT_DIR=str(reports))
    assert done.returncode == 0, done.stdout + done.stderr
    assert done.stdout.splitlines() == [
        f'[GODOT] {len(GODOT_GATES)} check(s) PASS — full log: {reports / "godot-check.log"}'
    ], done.stdout
    transcript = (reports / 'godot-check.log').read_text(encoding='utf-8')
    assert all(f'[check:{gate}] PASS' in transcript for gate in GODOT_GATES), transcript
    config = tomllib.loads((REPO_ROOT / 'devkit.toml').read_text(encoding='utf-8'))
    assert 'godot-check' in config['gates']['extra'], (
        f'`make check` no longer carries the Godot roster: {config["gates"].get("extra")}')


def test_every_gate_routes_through_the_shipped_helper_and_the_compositions_stay_the_includes():
    bodies = recipes()
    gates = {name: body for name, body in bodies.items() if body.strip() and name not in NOT_A_GATE}
    assert len(gates) >= 5, f'census collapsed to {sorted(gates)} — a parse that finds no ' \
                            'targets would pass this file vacuously'
    loud = sorted(name for name, body in gates.items() if not publishes_a_verdict(body))
    assert not loud, (f'{loud} print whatever their tool prints instead of one verdict line; '
                      'route them through $(call gdk_gate,...) or gdk_gate_verdict')
    # A same-named target, or a local `define gate`, in a file this repo owns
    # would be the fork of the include that `[gates] extra` exists to make
    # unnecessary — one under which the shipped helpers could regress unseen.
    forked = sorted(name for name in ('check', 'precommit', 'milestone', 'pm', 'help')
                    if name in bodies)
    assert not forked, f'{forked} redefined outside Makefile.devkit'
    assert 'include Makefile.devkit' in MAKEFILE.read_text(encoding='utf-8')
    assert (REPO_ROOT / 'tools/dev/gdk_gate.sh').exists()
    for makefile in OWN_MAKEFILES:
        assert 'define gate' not in makefile.read_text(encoding='utf-8'), makefile.name
