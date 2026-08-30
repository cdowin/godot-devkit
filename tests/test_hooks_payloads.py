"""test_hooks_payloads.py — the installed Claude Code hooks, fired at real
PreToolUse payloads.

test_install.py proves the install verbs and fires one block/allow pair per
hook; this file is the behavior matrix. Each hook is installed into an empty
temp repo — no library, no Makefile, nothing a consumer might lack — and RUN
against the JSON payload shape Claude Code actually delivers. Exit 0 is allow,
exit 2 is a BLOCK.

Every "pre-fix:" annotation below is a case that returned the WRONG verdict at
d76eeea (the 2026-08-30 fresh-eyes audit reproductions), verified by firing the
HEAD copies of the hooks against these exact payloads before the fix landed:

cc-commit-pathspec.sh — `--pathspec-from-file` (both spellings) IS naming
paths, but the space spelling was consumed as an argument-taking flag without
setting the pathspec verdict, and the `=` spelling fell into the generic
`--*=*` skip: both false-BLOCKED, the one false-positive class the hook's own
header promises must not exist.

cc-godot-sandbox.sh — the flag roster missed `-e` (short `--editor`), every
positional project boot (`godot main.tscn`, `godot .`, bare `godot` — all real
boots against the real user://), and a ` --help` substring anywhere in the
segment waved a genuine boot through. `${CMD%%<<*}` also truncated at `<<<`,
so a herestring hid any boot typed after it.
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
from godot_devkit.repo import install  # noqa: E402

pytestmark = pytest.mark.skipif(shutil.which('bash') is None,
                                reason='needs bash')

SANDBOX = 'tools/hooks/cc-godot-sandbox.sh'
PATHSPEC = 'tools/hooks/cc-commit-pathspec.sh'


@pytest.fixture(scope='module')
def hooks_repo(tmp_path_factory) -> Path:
    """One empty repo with the hooks installed; every case fires against it.
    The hooks are read-only over the tree, so sharing one install is safe."""
    root = tmp_path_factory.mktemp('hooks') / 'repo'
    root.mkdir()
    subprocess.run(['git', 'init', '-q'], cwd=root, check=True)
    previous = Path.cwd()
    os.chdir(root)
    repo_root.cache_clear()
    load_config.cache_clear()
    try:
        assert install.main('install-hooks', []) == 0
    finally:
        os.chdir(previous)
        repo_root.cache_clear()
        load_config.cache_clear()
    return root


def fire(root: Path, hook: str, command: str) -> int:
    event = json.dumps({'tool_name': 'Bash',
                        'tool_input': {'command': command},
                        'cwd': str(root)})
    return subprocess.run(['bash', str(root / hook)], input=event,
                          text=True, capture_output=True).returncode


# --- cc-commit-pathspec: --pathspec-from-file IS a pathspec -------------------
@pytest.mark.parametrize('command', [
    # pre-fix: all four false-BLOCKED (exit 2)
    'git commit --pathspec-from-file list.txt',
    'git commit --pathspec-from-file=list.txt -m "msg"',
    'git commit -m "fix: x" --pathspec-from-file list.txt',
    'git commit --pathspec-from-file=- -m "msg"',
])
def test_pathspec_from_file_names_paths_and_is_allowed(hooks_repo, command):
    assert fire(hooks_repo, PATHSPEC, command) == 0


@pytest.mark.parametrize('command', [
    'git commit -m "fix: x" -- a.py',      # explicit `--` pathspec
    'git commit -m "fix: x" a.py',         # bare path argument
    'git commit --amend',                  # exempt: another rule's territory
    'git commit --dry-run',                # exempt: writes nothing
    'git status',                          # not a commit at all
])
def test_pathspec_existing_exemptions_survive_the_fix(hooks_repo, command):
    assert fire(hooks_repo, PATHSPEC, command) == 0


@pytest.mark.parametrize('command', [
    'git commit -m "fix: x"',
    'git commit -am "sweep"',
    'git commit --all -m "sweep"',
])
def test_pathspec_a_pathless_commit_still_blocks(hooks_repo, command):
    assert fire(hooks_repo, PATHSPEC, command) == 2


# --- cc-godot-sandbox: allowed matrix -----------------------------------------
@pytest.mark.parametrize('command', [
    'godot --version',                     # boots nothing, prints, exits
    'godot --help',
    'godot -h',
    'command -v godot',                    # resolves the binary, runs nothing
    'make unit SYS=combat',                # the wrapper path — never godot
    'make smoke',                          # in command position for the hook
    'echo godot is not booting here',      # godot as data, not command word
    # heredoc body is data: writing a doc that QUOTES a boot is not a boot
    "cat > notes.md <<'EOF'\ngodot --headless --path .\nEOF",
    'grep -c godot <<<"$notes"',           # herestring alone: no boot follows
])
def test_sandbox_allows_queries_wrappers_and_data(hooks_repo, command):
    assert fire(hooks_repo, SANDBOX, command) == 0


# --- cc-godot-sandbox: blocked matrix -----------------------------------------
@pytest.mark.parametrize('command', [
    'godot --headless --path .',           # the original roster, kept
    'godot --editor',
    '/Applications/Godot.app/Contents/MacOS/Godot --editor',
    'godot -e',                            # pre-fix: allowed (short --editor)
    'godot main.tscn',                     # pre-fix: allowed (bare scene boot)
    'godot scenes/world/hub.tscn',         # pre-fix: allowed
    'godot .',                             # pre-fix: allowed (bare path boot)
    'godot /path/to/project',              # pre-fix: allowed
    'godot',                               # pre-fix: allowed (project manager)
    'timeout 60 godot -e',                 # pre-fix: allowed (via wrapper)
    'cd proj && godot',                    # pre-fix: allowed
    # pre-fix: ${CMD%%<<*} truncated at the herestring and hid the boot
    'grep godot <<<"$x"; godot --headless --path .',
    # pre-fix: a " --help" substring anywhere waved a real boot through
    'godot --headless --script tool.gd -- --help',
])
def test_sandbox_blocks_every_raw_boot_shape(hooks_repo, command):
    assert fire(hooks_repo, SANDBOX, command) == 2


# --- fail-open posture, both hooks --------------------------------------------
@pytest.mark.parametrize('hook', [SANDBOX, PATHSPEC])
def test_a_hook_fed_garbage_or_another_tool_fails_open(hooks_repo, hook):
    """A broken hook must never wedge the session: unparseable stdin and a
    non-Bash tool event both allow, even when the payload mentions the very
    thing the hook exists to block."""
    garbage = subprocess.run(['bash', str(hooks_repo / hook)],
                             input='not json {{{ godot commit',
                             text=True, capture_output=True)
    assert garbage.returncode == 0
    event = json.dumps({'tool_name': 'Write',
                        'tool_input': {'command':
                                       'godot -e; git commit -m x'},
                        'cwd': str(hooks_repo)})
    other = subprocess.run(['bash', str(hooks_repo / hook)], input=event,
                           text=True, capture_output=True)
    assert other.returncode == 0
