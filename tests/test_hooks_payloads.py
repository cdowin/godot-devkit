"""test_hooks_payloads.py — the installed engine-boot guard, fired at real
PreToolUse payloads.

test_runners_installable.py proves the install verb; this file is the
behavior matrix of the one Claude Code hook it writes, `cc-godot-sandbox.sh`.
The hook is installed into an empty temp repo — no library, no Makefile,
nothing a consumer might lack — and RUN against the JSON payload shape Claude
Code actually delivers. Exit 0 is allow, exit 2 is a BLOCK. (The rest of the
hook corpus — the commit guard, the stop gate, the write confinement, the
ledger couriers — is agentic-sdlc's, and so is its matrix.)

The hook carries its own `--self-test` corpus, and that corpus is what a
consumer wires into its gate — so it is replayed here, its counts are held,
and a wrong verdict is proven to redden it. The rows below are the shapes the
shipped corpus does NOT hold: each is a payload that returned the WRONG
verdict once (the "pre-fix:" annotations, verified by firing the HEAD copy of
the hook at that exact payload before the fix landed), and a row the corpus
already replays is not repeated at a second altitude.

cc-godot-sandbox.sh — the flag roster missed `-e` (short `--editor`), every
positional project boot (`godot main.tscn`, `godot .`, bare `godot` — all real
boots against the real user://), and a ` --help` substring anywhere in the
segment waved a genuine boot through. `${CMD%%<<*}` also truncated at `<<<`,
so a herestring hid any boot typed after it.

cc-godot-sandbox.sh, second round (v0.18.1, found by a consumer): the segment
split ran `tr` over the whole line, INSIDE quotes as well, so a quoted `godot`
that happened to follow `;`, `(` or `)` became the next segment's command word
— those spellings are in the shipped corpus now.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from support import REPO_ROOT  # noqa: E402

sys.path.insert(0, str(REPO_ROOT / 'src'))
from godot_devkit.core.project import load_config, repo_root  # noqa: E402
from godot_devkit.godot import install  # noqa: E402

pytestmark = pytest.mark.skipif(shutil.which('bash') is None,
                                reason='needs bash')

SANDBOX = 'tools/hooks/cc-godot-sandbox.sh'


@pytest.fixture(scope='module')
def hooks_repo(tmp_path_factory) -> Path:
    """One empty repo with the runners installed; every case fires against it.
    The hook is read-only over the tree, so sharing one install is safe."""
    root = tmp_path_factory.mktemp('hooks') / 'repo'
    root.mkdir()
    subprocess.run(['git', 'init', '-q'], cwd=root, check=True)
    previous = Path.cwd()
    os.chdir(root)
    repo_root.cache_clear()
    load_config.cache_clear()
    try:
        assert install.main([]) == 0
    finally:
        os.chdir(previous)
        repo_root.cache_clear()
        load_config.cache_clear()
    return root


def fire_file(hook: Path, command: str) -> subprocess.CompletedProcess:
    event = json.dumps({'tool_name': 'Bash',
                        'tool_input': {'command': command},
                        'cwd': str(hook.parent)})
    return subprocess.run(['bash', str(hook)], input=event,
                          text=True, capture_output=True)


def fire(root: Path, hook: str, command: str) -> int:
    return fire_file(root / hook, command).returncode


def self_test(hook: Path) -> subprocess.CompletedProcess:
    return subprocess.run(['bash', str(hook), '--self-test'],
                          text=True, capture_output=True)


# --- the shipped corpus, replayed and held to being able to fail ------------
def test_sandbox_self_test_replays_its_own_corpus_and_a_wrong_verdict_reddens_it(
        hooks_repo):
    """The corpus shipped IN the hook is the one consumers wire into their
    gate. If it can go stale silently, it is decoration — so the devkit's own
    suite runs it, holds its case count (a dropped case is a ratchet slipping),
    and proves a wrong verdict FAILS loudly rather than being swallowed by the
    hook's fail-open ERR trap."""
    hook = hooks_repo / SANDBOX
    ok = self_test(hook)
    assert ok.returncode == 0, ok.stdout + ok.stderr
    assert ok.stdout.split('—')[1].strip() == '13 block / 16 allow case(s)', ok.stdout

    broken = hooks_repo.parent / 'broken-sandbox.sh'
    broken.write_text(hook.read_text().replace(
        "\t'make parse'\n", "\t'make parse ; godot --headless'\n"))
    bad = self_test(broken)
    assert bad.returncode != 0
    assert 'FALSE POSITIVE' in bad.stderr


# --- cc-godot-sandbox: allowed shapes the shipped corpus does not hold --------
@pytest.mark.parametrize('command', [
    'godot --help',                        # boots nothing, prints, exits
    'godot -h',                            # the short spelling of the same
    'echo godot is not booting here',      # godot as data, not command word
    'grep -c godot <<<"$notes"',           # herestring alone: no boot follows
    '$GODOT --version',                    # variable resolved, still query-only
])
def test_sandbox_allows_queries_and_data(hooks_repo, command):
    assert fire(hooks_repo, SANDBOX, command) == 0


# --- cc-godot-sandbox: blocked shapes the shipped corpus does not hold --------
@pytest.mark.parametrize('command', [
    'godot --editor',
    'godot -e',                            # pre-fix: allowed (short --editor)
    'godot main.tscn',                     # pre-fix: allowed (bare scene boot)
    'godot .',                             # pre-fix: allowed (bare path boot)
    'godot /path/to/project',              # pre-fix: allowed
    'cd proj && godot',                    # pre-fix: allowed
    # pre-fix: ${CMD%%<<*} truncated at the herestring and hid the boot
    'grep godot <<<"$x"; godot --headless --path .',
    # pre-fix: a " --help" substring anywhere waved a real boot through
    'godot --headless --script tool.gd -- --help',
    # pre-fix: a godot-NAMED variable in command position was allowed — the
    # `$` failed the command-word match (the arbitrary-name case stays the
    # hook's declared accepted gap)
    'GODOT=/Apps/Godot; $GODOT --headless',
])
def test_sandbox_blocks_every_raw_boot_shape(hooks_repo, command):
    assert fire(hooks_repo, SANDBOX, command) == 2


def test_a_line_past_the_split_bound_still_blocks_a_boot(hooks_repo):
    """The quote-aware walk is bounded (SPLIT_MAX_CHARS) because a 36KB line
    carrying 4,000 operators took 12s in it — a hook that stalls the session is
    its own kind of broken. The bound's escape hatch must be the STRICT split,
    never 'allow': over the bound the guard is exactly what it was before the
    quoting fix."""
    over = 'echo "pad ' + 'x' * 9000 + '" ; godot --headless'
    assert len(over) > 8192
    assert fire(hooks_repo, SANDBOX, over) == 2


# --- cc-godot-sandbox: the OPTIONAL sourced-boot-function guard ---------------
# SANDBOX_FUNCTION ships EMPTY (the installable is consumer-agnostic); a
# consumer whose sandbox library boots the engine from a shell function names it
# in the project-config header. Empty must be inert, and armed must guard by
# COMMAND POSITION — the same rule the engine guard follows. Armed, the hook's
# own corpus grows by the function cases (typed, sourced-then-typed; named as
# an argument, quoted), so the armed corpus is replayed rather than repeated.
FUNCTION_NAME = 'proj_rebuild_import_cache'


@pytest.fixture(scope='module')
def armed_sandbox(hooks_repo) -> Path:
    armed = hooks_repo.parent / 'armed-sandbox.sh'
    armed.write_text((hooks_repo / SANDBOX).read_text()
                     .replace("SANDBOX_FUNCTION=''",
                              f"SANDBOX_FUNCTION='{FUNCTION_NAME}'", 1)
                     .replace("SANDBOX_FUNCTION_TARGET=''",
                              "SANDBOX_FUNCTION_TARGET='make import-cache'", 1))
    return armed


def test_the_armed_corpus_passes_and_grows_by_exactly_the_function_cases(armed_sandbox):
    done = self_test(armed_sandbox)
    assert done.returncode == 0, done.stdout + done.stderr
    assert done.stdout.split('—')[1].strip() == '15 block / 18 allow case(s)', done.stdout


def test_the_named_boot_function_is_blocked_behind_a_wrapper_word(armed_sandbox):
    # The one armed shape the corpus does not hold: the guard is by command
    # position, and a wrapper word in front of the function is still a boot.
    assert fire_file(armed_sandbox, f'timeout 60 {FUNCTION_NAME}').returncode == 2


def test_an_unset_sandbox_function_guards_nothing_and_still_fast_paths(hooks_repo):
    """Stock value = no such guard. The failure this pins is the OTHER
    direction: `*"$SANDBOX_FUNCTION"*` with an empty value matches every
    command on earth, which would retire the fast path for every consumer that
    left the stock value alone."""
    assert fire(hooks_repo, SANDBOX, FUNCTION_NAME) == 0


# --- cc-godot-sandbox: the STOCK gdk_ roster, guarded with no config ----------
# `install-runners` puts gdk_runners.sh in every consumer, so its
# boot-in-a-function is guarded out of the box — SANDBOX_FUNCTION above stays
# for a repo that ALSO carries a project-prefixed spelling. The typed and the
# sourced-then-typed spellings, the sanctioned target, the mention and the
# sourced door are the shipped corpus's; these two are the shapes it lacks.
def test_the_stock_roster_blocks_the_library_boot_function_behind_a_wrapper(hooks_repo):
    assert fire(hooks_repo, SANDBOX, 'timeout 60 gdk_rebuild_import_cache') == 2


def test_the_stock_roster_never_blocks_the_sandbox_door_typed_bare(hooks_repo):
    # gdk_sandbox_home is the DOOR: it exports a sandboxed HOME and boots
    # nothing. A guard that blocked it would be teaching people to switch the
    # guard off, which is the one outcome this file exists to prevent.
    assert fire(hooks_repo, SANDBOX, 'gdk_sandbox_home') == 0


def test_the_block_message_names_the_function_that_matched(hooks_repo):
    """Two rosters feed one guard, so the message has to name the entry that
    actually matched — a block that names the OTHER roster's function sends
    the agent to a door that does not exist."""
    done = fire_file(hooks_repo / SANDBOX, 'gdk_rebuild_import_cache')
    assert done.returncode == 2
    assert '`gdk_rebuild_import_cache`' in done.stderr, done.stderr
    assert 'make import-cache' in done.stderr, done.stderr
    assert 'gdk_runners.sh' in done.stderr, done.stderr
