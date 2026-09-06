"""test_hooks_payloads.py — the installed engine-boot guard, fired at real
PreToolUse payloads.

test_runners_installable.py proves the install verb; this file is the
behaviour of the one Claude Code hook it writes, `cc-godot-sandbox.sh`,
installed into an empty temp repo and RUN against the JSON payload shape
Claude Code delivers. Exit 0 is allow, exit 2 is a BLOCK.

The hook carries its own `--self-test` corpus, and that corpus is what a
consumer wires into its gate — so it is replayed here, its counts are held,
and a wrong verdict is proven to redden it. The rows below are the shapes the
shipped corpus does NOT hold, one per branch of the hook that the corpus never
reaches: the herestring rewrite (`${CMD%%<<*}` once truncated at `<<<` and hid
any boot typed after it), the split bound (a 36KB line took 12s in the
quote-aware walk; over the bound the guard falls back to the STRICT split,
never to allow), the OPTIONAL consumer-named boot function (stock value empty;
armed, the hook's own corpus grows by the function cases and is replayed
rather than repeated), and the block message, which has to name the roster
entry that actually matched.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from support import REPO_ROOT

pytestmark = pytest.mark.skipif(shutil.which('bash') is None, reason='needs bash')

SANDBOX = 'tools/hooks/cc-godot-sandbox.sh'


@pytest.fixture(scope='module')
def hook(tmp_path_factory) -> Path:
    # The guard, installed once into an empty repo — from source, never a
    # cached wheel; it is read-only over the tree, so every case fires against
    # the same install.
    root = tmp_path_factory.mktemp('hooks') / 'repo'
    root.mkdir()
    subprocess.run(['git', 'init', '-q'], cwd=root, check=True)
    subprocess.run([sys.executable, '-m', 'godot_devkit.cli', 'install-runners'], cwd=root,
                   check=True, env={**os.environ, 'PYTHONPATH': str(REPO_ROOT / 'src')})
    return root / SANDBOX


def fire(hook: Path, command: str) -> subprocess.CompletedProcess:
    event = json.dumps({'tool_name': 'Bash', 'tool_input': {'command': command},
                        'cwd': str(hook.parent)})
    return subprocess.run(['bash', str(hook)], input=event, text=True, capture_output=True)


def self_test(hook: Path) -> subprocess.CompletedProcess:
    return subprocess.run(['bash', str(hook), '--self-test'], text=True, capture_output=True)


def test_the_shipped_corpus_replays_and_a_wrong_verdict_reddens_it(hook):
    # The count is held because a dropped case is a ratchet slipping; the
    # broken copy proves a wrong verdict FAILS loudly rather than being
    # swallowed by the hook's fail-open ERR trap.
    ok = self_test(hook)
    assert ok.returncode == 0, ok.stdout + ok.stderr
    assert ok.stdout.split('—')[1].strip() == '13 block / 16 allow case(s)', ok.stdout
    broken = hook.parent / 'broken-sandbox.sh'
    broken.write_text(hook.read_text().replace("\t'make parse'\n",
                                               "\t'make parse ; godot --headless'\n"))
    bad = self_test(broken)
    assert bad.returncode != 0 and 'FALSE POSITIVE' in bad.stderr, bad.stdout + bad.stderr


def test_a_herestring_is_not_a_heredoc(hook):
    assert fire(hook, 'grep -c godot <<<"$notes"').returncode == 0       # no boot follows
    assert fire(hook, 'grep godot <<<"$x"; godot --headless --path .').returncode == 2


def test_a_line_past_the_split_bound_still_blocks_a_boot(hook):
    over = 'echo "pad ' + 'x' * 9000 + '" ; godot --headless'
    assert len(over) > 8192
    assert fire(hook, over).returncode == 2


def test_the_armed_corpus_passes_and_grows_by_exactly_the_function_cases(hook):
    # A consumer whose sandbox library boots the engine from a shell function
    # names it in the project-config header; armed, the guard is by COMMAND
    # POSITION, the same rule the engine guard follows.
    armed = hook.parent / 'armed-sandbox.sh'
    armed.write_text(hook.read_text()
                     .replace("SANDBOX_FUNCTION=''", "SANDBOX_FUNCTION='proj_rebuild_import_cache'", 1)
                     .replace("SANDBOX_FUNCTION_TARGET=''", "SANDBOX_FUNCTION_TARGET='make import-cache'", 1))
    done = self_test(armed)
    assert done.returncode == 0, done.stdout + done.stderr
    assert done.stdout.split('—')[1].strip() == '15 block / 18 allow case(s)', done.stdout


def test_the_block_message_names_the_function_that_matched(hook):
    # Two rosters feed one guard: a block that names the OTHER roster's
    # function sends the agent to a door that does not exist.
    done = fire(hook, 'gdk_rebuild_import_cache')
    assert done.returncode == 2
    assert all(text in done.stderr for text in ('`gdk_rebuild_import_cache`', 'make import-cache',
                                                'gdk_runners.sh')), done.stderr
