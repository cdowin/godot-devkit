"""test_hooks_payloads.py — the installed Claude Code hooks, fired at real
PreToolUse payloads.

test_install.py proves the install verbs and fires one block/allow pair per
hook; this file is the behavior matrix. Each hook is installed into an empty
temp repo — no library, no Makefile, nothing a consumer might lack — and RUN
against the JSON payload shape Claude Code actually delivers. Exit 0 is allow,
exit 2 is a BLOCK.

Every "pre-fix:" annotation below is a case that returned the WRONG verdict at
d76eeea, verified by firing the
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

cc-godot-sandbox.sh, second round (v0.18.1, found by a consumer): the segment
split ran `tr` over the whole line, INSIDE quotes as well, so a quoted `godot`
that happened to follow `;`, `(` or `)` became the next segment's command word
— `echo "foo; godot --headless"` and a commit message naming the guard were
both false-BLOCKED.
"""
from __future__ import annotations

import json
import os
import shutil
import struct
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


def fire_file(hook: Path, command: str) -> int:
    event = json.dumps({'tool_name': 'Bash',
                        'tool_input': {'command': command},
                        'cwd': str(hook.parent)})
    return subprocess.run(['bash', str(hook)], input=event,
                          text=True, capture_output=True).returncode


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
    'godot-devkit check all',              # this toolkit's own CLI — never a boot
    '$GODOT --version',                    # variable resolved, still query-only
    # A word inside QUOTES is data, never a command word. The naive `tr` split
    # cut inside quoted text, so a quoted `godot` that happened to follow an
    # operator character became the next segment's command word.
    # pre-fix: BLOCKED — the `;` inside the quoted string split the line
    'echo "foo; godot --headless"',
    # pre-fix: BLOCKED — `(` and `)` inside the commit message split the line
    'git commit -m "hooks: block (godot --headless) in command position"',
    # allowed pre-fix only by luck (the `:` after `)` became the command word);
    # pinned because it is the spelling the consumer reported
    'git commit -m "tools(dev): godot --headless is wrapper-only"',
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
    # pre-fix: a godot-NAMED variable in command position was allowed — the
    # `$` failed the command-word match (the arbitrary-name case stays the
    # hook's declared accepted gap)
    'GODOT=/Apps/Godot; $GODOT --headless',
    '"$GODOT" --headless --path .',
    '"${GODOT}" -e',
    '$GODOT --headless --path .',          # pre-fix: fast path missed ALL-CAPS
    # An unbalanced quote is unparseable, and unparseable input stays STRICT:
    # the quote-aware split refuses, the naive fallback still sees the boot.
    'echo "foo; godot --headless',
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


def test_sandbox_self_test_replays_its_own_corpus(hooks_repo):
    """The corpus shipped IN the hook is the one consumers wire into their
    gate. If it can go stale silently, it is decoration — so the devkit's own
    suite runs it, and a wrong verdict is proven to FAIL loudly rather than
    being swallowed by the hook's fail-open ERR trap."""
    hook = hooks_repo / SANDBOX
    ok = subprocess.run(['bash', str(hook), '--self-test'],
                        text=True, capture_output=True)
    assert ok.returncode == 0, ok.stdout + ok.stderr
    assert 'SELF-TEST OK' in ok.stdout

    broken = hooks_repo.parent / 'broken-sandbox.sh'
    broken.write_text(hook.read_text().replace(
        "\t'make parse'\n", "\t'make parse ; godot --headless'\n"))
    bad = subprocess.run(['bash', str(broken), '--self-test'],
                         text=True, capture_output=True)
    assert bad.returncode != 0
    assert 'FALSE POSITIVE' in bad.stderr


# --- cc-godot-sandbox: the OPTIONAL sourced-boot-function guard ---------------
# SANDBOX_FUNCTION ships EMPTY (the installable is consumer-agnostic); a
# consumer whose sandbox library boots the engine from a shell function names it
# in the project-config header. Empty must be inert, and armed must guard by
# COMMAND POSITION — the same rule the engine guard follows.
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


@pytest.mark.parametrize('command', [
    FUNCTION_NAME,                                  # typed after sourcing
    f'source ./sandbox-lib.sh && {FUNCTION_NAME}',  # sourced, then typed
    f'timeout 60 {FUNCTION_NAME}',                  # behind a wrapper word
])
def test_sandbox_blocks_the_named_boot_function(armed_sandbox, command):
    assert fire_file(armed_sandbox, command) == 2


@pytest.mark.parametrize('command', [
    f'grep -rn {FUNCTION_NAME} docs/',              # an argument, not a command
    f'echo "run it: ({FUNCTION_NAME}) by hand"',    # quoted: data
])
def test_the_named_boot_function_is_data_unless_it_is_the_command_word(
        armed_sandbox, command):
    assert fire_file(armed_sandbox, command) == 0


@pytest.mark.parametrize('command', [
    FUNCTION_NAME,
    f'source ./sandbox-lib.sh && {FUNCTION_NAME}',
])
def test_an_unset_sandbox_function_guards_nothing_and_still_fast_paths(
        hooks_repo, command):
    """Stock value = no such guard. The failure this pins is the OTHER
    direction: `*"$SANDBOX_FUNCTION"*` with an empty value matches every
    command on earth, which would retire the fast path for every consumer that
    left the stock value alone."""
    assert fire(hooks_repo, SANDBOX, command) == 0


def test_the_armed_corpus_grows_by_exactly_the_function_cases(armed_sandbox,
                                                              hooks_repo):
    def counts(hook: Path) -> str:
        run = subprocess.run(['bash', str(hook), '--self-test'],
                             text=True, capture_output=True)
        assert run.returncode == 0, run.stdout + run.stderr
        return run.stdout.split('—')[1].strip()

    assert counts(hooks_repo / SANDBOX) == '13 block / 16 allow case(s)'
    assert counts(armed_sandbox) == '15 block / 18 allow case(s)'


# --- cc-godot-sandbox: the STOCK gdk_ roster, guarded with no config ----------
# `install-runners` puts gdk_runners.sh in every consumer, so its
# boot-in-a-function is guarded out of the box — SANDBOX_FUNCTION above stays
# for a repo that ALSO carries a project-prefixed spelling. The pair below is
# the whole point: the function that BOOTS is blocked, the function that makes
# a run safe is not.
@pytest.mark.parametrize('command', [
    'gdk_rebuild_import_cache',                                  # typed
    'source tools/dev/gdk_runners.sh && gdk_rebuild_import_cache',
    'timeout 60 gdk_rebuild_import_cache',                       # behind a wrapper
])
def test_the_stock_roster_blocks_the_library_boot_function_unconfigured(
        hooks_repo, command):
    assert fire(hooks_repo, SANDBOX, command) == 2


@pytest.mark.parametrize('command', [
    # gdk_sandbox_home is the DOOR: it exports a sandboxed HOME and boots
    # nothing. A guard that blocked it would be teaching people to switch the
    # guard off, which is the one outcome this file exists to prevent.
    'source tools/dev/gdk_runners.sh && gdk_sandbox_home',
    'gdk_sandbox_home',
    'make import-cache',                                # the sanctioned target
    'grep -rn gdk_rebuild_import_cache docs/',          # an argument, not a command
    'echo "run it: (gdk_rebuild_import_cache) by hand"',
])
def test_the_stock_roster_never_blocks_the_sandbox_door_or_a_mention(
        hooks_repo, command):
    assert fire(hooks_repo, SANDBOX, command) == 0


def test_the_block_message_names_the_function_that_matched(hooks_repo):
    """Two rosters feed one guard, so the message has to name the entry that
    actually matched — a block that names the OTHER roster's function sends
    the agent to a door that does not exist."""
    event = json.dumps({'tool_name': 'Bash',
                        'tool_input': {'command': 'gdk_rebuild_import_cache'},
                        'cwd': str(hooks_repo)})
    done = subprocess.run(['bash', str(hooks_repo / SANDBOX)], input=event,
                          text=True, capture_output=True)
    assert done.returncode == 2
    assert '`gdk_rebuild_import_cache`' in done.stderr, done.stderr
    assert 'make import-cache' in done.stderr, done.stderr
    assert 'gdk_runners.sh' in done.stderr, done.stderr


# =============================================================================
# The 0.16.0 corpus: cc-stop-gate, cc-write-confine, pre-push,
# prepare-commit-msg, agent-worktree, doctor — installed into temp repos and
# RUN, the same way the two hooks above are proven. The git hooks and tools are
# exercised through REAL git operations (push, commit, worktree), not by
# feeding them synthetic argv.
# =============================================================================

STOP_GATE = 'tools/hooks/cc-stop-gate.sh'
CONFINE = 'tools/hooks/cc-write-confine.sh'
WORKTREE = 'tools/dev/agent-worktree.sh'
DOCTOR = 'tools/dev/checks/doctor.sh'
# One shipped git hook, by name: the doctor cases below replace it with
# something git cannot exec.
A_GIT_HOOK = 'pre-push'
MARKER = '.agent-scope'

# The corpus reads DEVKIT_AGENT_SCOPE; a test machine that happens to export
# it would flip every trunk/agent distinction below.
CLEAN_ENV = {k: v for k, v in os.environ.items() if k != 'DEVKIT_AGENT_SCOPE'}


def corpus_repo(parent: Path, name: str = 'repo') -> Path:
    """A git repo with the full corpus installed, armed, committed, and one
    commit on `main` — the smallest tree every scenario below can build on."""
    root = parent / name
    root.mkdir()
    subprocess.run(['git', 'init', '-q', '-b', 'main'], cwd=root, check=True)
    subprocess.run(['git', 'config', 'user.email', 't@t'], cwd=root, check=True)
    subprocess.run(['git', 'config', 'user.name', 'T'], cwd=root, check=True)
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
    armed = subprocess.run(['bash', 'tools/setup-hooks.sh'], cwd=root,
                           capture_output=True, text=True)
    assert armed.returncode == 0, armed.stderr
    subprocess.run(['git', 'add', '-A'], cwd=root, check=True)
    subprocess.run(['git', 'commit', '-q', '-m', 'install corpus'],
                   cwd=root, check=True, env=CLEAN_ENV)
    return root


def git(root: Path, *argv: str) -> subprocess.CompletedProcess:
    return subprocess.run(['git', *argv], cwd=root, capture_output=True,
                          text=True, env=CLEAN_ENV)


def write_makefile(root: Path, check_ok: bool) -> None:
    body = '@true' if check_ok else '@exit 1'
    (root / 'Makefile').write_text(
        f'check:\n\t{body}\nunit:\n\t@true\n', encoding='utf-8')


# --- cc-stop-gate: agent-only, red blocks, green allows -----------------------
def fire_stop(root: Path, cwd: Path | None = None,
              stop_hook_active: bool = False) -> subprocess.CompletedProcess:
    event = json.dumps({'cwd': str(cwd or root),
                        'stop_hook_active': stop_hook_active})
    return subprocess.run(['bash', str(root / STOP_GATE)], input=event,
                          text=True, capture_output=True, env=CLEAN_ENV)


def test_stop_gate_never_gates_the_trunk_session(tmp_path):
    """THE load-bearing safety property: no marker + no env = no gate, even
    over a gate that would be red — a false trigger would wedge the
    orchestrator every turn."""
    root = corpus_repo(tmp_path)
    write_makefile(root, check_ok=False)
    assert fire_stop(root).returncode == 0


def test_stop_gate_blocks_an_agent_stop_while_the_gate_is_red(tmp_path):
    root = corpus_repo(tmp_path)
    (root / MARKER).write_text('branch=feat/x\nbase=main\n', encoding='utf-8')
    write_makefile(root, check_ok=False)
    done = fire_stop(root)
    assert done.returncode == 2
    assert 'BLOCKED (Stop gate)' in done.stderr


def test_stop_gate_allows_an_agent_stop_once_the_gate_is_green(tmp_path):
    root = corpus_repo(tmp_path)
    (root / MARKER).write_text('branch=feat/x\nbase=main\n', encoding='utf-8')
    write_makefile(root, check_ok=True)
    assert fire_stop(root).returncode == 0


def test_stop_gate_does_not_loop_on_its_own_block(tmp_path):
    """stop_hook_active means Claude Code is already continuing because of a
    prior block — blocking again would gate-loop forever."""
    root = corpus_repo(tmp_path)
    (root / MARKER).write_text('branch=feat/x\nbase=main\n', encoding='utf-8')
    write_makefile(root, check_ok=False)
    assert fire_stop(root, stop_hook_active=True).returncode == 0


def test_stop_gate_fails_open_without_a_makefile_and_on_garbage(tmp_path):
    """Installed ahead of the dev loop (no Makefile yet), the gate must not
    wedge every agent stop; fed garbage it must not wedge the session."""
    root = corpus_repo(tmp_path)
    (root / MARKER).write_text('branch=feat/x\nbase=main\n', encoding='utf-8')
    assert fire_stop(root).returncode == 0    # marker set, but no Makefile
    garbage = subprocess.run(['bash', str(root / STOP_GATE)],
                             input='not json {{{', text=True,
                             capture_output=True, cwd=root, env=CLEAN_ENV)
    assert garbage.returncode == 0


# --- cc-write-confine: cross-repo blocked, everything legitimate passes -------
def fire_confine(hook_root: Path, target: Path | str, cwd: Path,
                 env: dict | None = None) -> subprocess.CompletedProcess:
    event = json.dumps({'tool_name': 'Write',
                        'tool_input': {'file_path': str(target)},
                        'cwd': str(cwd)})
    return subprocess.run(['bash', str(hook_root / CONFINE)], input=event,
                          text=True, capture_output=True,
                          env=env or CLEAN_ENV)


def plain_repo(parent: Path, name: str) -> Path:
    other = parent / name
    other.mkdir()
    subprocess.run(['git', 'init', '-q', '-b', 'main'], cwd=other, check=True)
    return other


def test_confine_blocks_a_write_into_a_different_repository(tmp_path):
    ours = corpus_repo(tmp_path)
    theirs = plain_repo(tmp_path, 'theirs')
    done = fire_confine(ours, theirs / 'stomped.txt', cwd=ours)
    assert done.returncode == 2
    assert 'BLOCKED (write-confinement)' in done.stderr


def test_confine_allows_a_write_inside_the_session_repo(tmp_path):
    ours = corpus_repo(tmp_path)
    assert fire_confine(ours, ours / 'sub/new.txt', cwd=ours).returncode == 0


def test_confine_allows_a_non_repo_target(tmp_path):
    """A scratchpad / tmp / dotfile write is not the cross-tree collision this
    hook guards; blocking it just pushes the agent to Bash heredocs, which the
    hook cannot see anyway."""
    ours = corpus_repo(tmp_path)
    outside = tmp_path / 'scratch'
    outside.mkdir()
    assert fire_confine(ours, outside / 'notes.md', cwd=ours).returncode == 0


def test_confine_allows_the_auto_memory_store_by_path_shape(tmp_path):
    ours = corpus_repo(tmp_path)
    memory = '/somewhere/.claude/projects/p/memory/notes.md'
    assert fire_confine(ours, memory, cwd=ours).returncode == 0


def test_confine_allows_a_sibling_worktree_of_the_same_repo(tmp_path):
    """The dispatched-subagent case: the Agent tool reports the PARENT
    session's cwd, so a worktree-scoped agent's every edit lands 'outside' the
    session tree — same repository must therefore be the boundary, not same
    worktree. One consumer fork fixed this; the other still blocks it."""
    ours = corpus_repo(tmp_path)
    wt = tmp_path / 'wt'
    done = git(ours, 'worktree', 'add', '-b', 'feat/side', str(wt), 'main')
    assert done.returncode == 0, done.stderr
    assert fire_confine(ours, wt / 'edited.txt', cwd=ours).returncode == 0


def test_confine_honors_a_granted_extra_root_exactly(tmp_path):
    ours = corpus_repo(tmp_path)
    theirs = plain_repo(tmp_path, 'theirs')
    grants = ours / 'tools/hooks/extra-write-roots.local'
    grants.write_text(f'# temporary grant\n{theirs}\n', encoding='utf-8')
    assert fire_confine(ours, theirs / 'ok.txt', cwd=ours).returncode == 0
    # The grant is the named toplevel, not a prefix family.
    evil = plain_repo(tmp_path, 'theirs-evil')
    assert fire_confine(ours, evil / 'no.txt', cwd=ours).returncode == 2


def test_confine_scope_env_pins_the_allowed_toplevel(tmp_path):
    ours = corpus_repo(tmp_path)
    theirs = plain_repo(tmp_path, 'theirs')
    pinned = dict(CLEAN_ENV, DEVKIT_AGENT_SCOPE=str(ours))
    outside = tmp_path / 'elsewhere'
    outside.mkdir()
    assert fire_confine(ours, ours / 'mine.txt', cwd=outside,
                        env=pinned).returncode == 0
    assert fire_confine(ours, theirs / 'not-mine.txt', cwd=outside,
                        env=pinned).returncode == 2


def test_confine_fails_open_on_garbage_and_non_write_tools(tmp_path):
    ours = corpus_repo(tmp_path)
    garbage = subprocess.run(['bash', str(ours / CONFINE)],
                             input='not json {{{', text=True,
                             capture_output=True, env=CLEAN_ENV)
    assert garbage.returncode == 0
    event = json.dumps({'tool_name': 'Bash',
                        'tool_input': {'command': 'echo hi'},
                        'cwd': str(ours)})
    bash_tool = subprocess.run(['bash', str(ours / CONFINE)], input=event,
                               text=True, capture_output=True, env=CLEAN_ENV)
    assert bash_tool.returncode == 0


# --- pre-push: main blocked, gate scoped, exact branch match ------------------
def with_origin(root: Path, parent: Path) -> Path:
    origin = parent / 'origin.git'
    subprocess.run(['git', 'init', '-q', '--bare', str(origin)], check=True)
    assert git(root, 'remote', 'add', 'origin', str(origin)).returncode == 0
    return origin


def origin_heads(origin: Path) -> str:
    return subprocess.run(['git', 'show-ref'], cwd=origin, capture_output=True,
                          text=True).stdout


def test_pre_push_blocks_a_direct_push_to_main_and_nothing_lands(tmp_path):
    root = corpus_repo(tmp_path)
    origin = with_origin(root, tmp_path)
    done = git(root, 'push', 'origin', 'main')
    assert done.returncode != 0
    assert 'Direct push to main' in done.stderr
    assert origin_heads(origin).strip() == ''


def test_pre_push_lets_a_green_gate_push_land(tmp_path):
    root = corpus_repo(tmp_path)
    origin = with_origin(root, tmp_path)
    write_makefile(root, check_ok=True)
    assert git(root, 'checkout', '-q', '-b', 'staging').returncode == 0
    done = git(root, 'push', 'origin', 'staging')
    assert done.returncode == 0, done.stderr
    assert 'refs/heads/staging' in origin_heads(origin)


def test_pre_push_blocks_a_red_gate_push_before_it_lands(tmp_path):
    root = corpus_repo(tmp_path)
    origin = with_origin(root, tmp_path)
    write_makefile(root, check_ok=False)
    assert git(root, 'checkout', '-q', '-b', 'staging').returncode == 0
    done = git(root, 'push', 'origin', 'staging')
    assert done.returncode != 0
    assert 'pre-push gate' in done.stderr
    assert 'refs/heads/staging' not in origin_heads(origin)


def test_pre_push_skips_the_gate_for_agent_worktrees(tmp_path):
    """The agent's Stop hook already gates every finish; paying the same gate
    again per push doubles the cost. Red gate + marker must still push."""
    root = corpus_repo(tmp_path)
    origin = with_origin(root, tmp_path)
    write_makefile(root, check_ok=False)
    (root / MARKER).write_text('branch=feat/x\nbase=main\n', encoding='utf-8')
    assert git(root, 'checkout', '-q', '-b', 'feat/x').returncode == 0
    done = git(root, 'push', 'origin', 'feat/x')
    assert done.returncode == 0, done.stderr
    assert 'refs/heads/feat/x' in origin_heads(origin)


def test_pre_push_matches_the_protected_branch_exactly(tmp_path):
    """Both consumer forks grep for the substring refs/heads/main, which also
    blocks refs/heads/maintenance. The shipped hook matches the whole name."""
    root = corpus_repo(tmp_path)
    origin = with_origin(root, tmp_path)
    write_makefile(root, check_ok=True)
    assert git(root, 'checkout', '-q', '-b', 'maintenance').returncode == 0
    done = git(root, 'push', 'origin', 'maintenance')
    assert done.returncode == 0, done.stderr
    assert 'refs/heads/maintenance' in origin_heads(origin)


def test_pre_push_fails_open_without_a_makefile_but_still_guards_main(tmp_path):
    """Stage 1 (push-safety) always runs; stage 2 (the gate) cannot run in a
    repo with no dev loop yet and must not block every push meanwhile."""
    root = corpus_repo(tmp_path)
    origin = with_origin(root, tmp_path)
    assert git(root, 'checkout', '-q', '-b', 'staging').returncode == 0
    assert git(root, 'push', 'origin', 'staging').returncode == 0
    assert 'refs/heads/staging' in origin_heads(origin)
    assert git(root, 'checkout', '-q', 'main').returncode == 0
    assert git(root, 'push', 'origin', 'main').returncode != 0


def test_pre_push_does_not_gate_a_tag_only_push(tmp_path):
    root = corpus_repo(tmp_path)
    with_origin(root, tmp_path)
    write_makefile(root, check_ok=False)   # a red gate that must not run
    assert git(root, 'tag', 'v0').returncode == 0
    done = git(root, 'push', 'origin', 'v0')
    assert done.returncode == 0, done.stderr


# --- prepare-commit-msg: agents stamped, the human never -----------------------
def last_message(root: Path) -> str:
    return git(root, 'log', '-1', '--format=%B').stdout


def test_prepare_commit_msg_stamps_agent_commits(tmp_path):
    root = corpus_repo(tmp_path)
    (root / MARKER).write_text('branch=feat/x\nbase=main\n', encoding='utf-8')
    assert git(root, 'commit', '-q', '--allow-empty',
               '-m', 'feat: x').returncode == 0
    assert 'Co-Authored-By: Claude' in last_message(root)


def test_prepare_commit_msg_never_stamps_the_trunk(tmp_path):
    """The MUST-NEVER property: the human's own commits stay theirs."""
    root = corpus_repo(tmp_path)
    assert git(root, 'commit', '-q', '--allow-empty',
               '-m', 'docs: mine').returncode == 0
    assert 'Co-Authored-By' not in last_message(root)


def test_prepare_commit_msg_is_idempotent(tmp_path):
    root = corpus_repo(tmp_path)
    (root / MARKER).write_text('branch=feat/x\nbase=main\n', encoding='utf-8')
    already = ('feat: x\n\n'
               'Co-Authored-By: Claude <noreply@anthropic.com>')
    assert git(root, 'commit', '-q', '--allow-empty',
               '-m', already).returncode == 0
    assert last_message(root).count('Co-Authored-By') == 1


# --- agent-worktree: create, refuse-dirty, keep-unmerged, teardown ------------
def worktree(root: Path, *argv: str) -> subprocess.CompletedProcess:
    return subprocess.run(['bash', str(root / WORKTREE), *argv], cwd=root,
                          capture_output=True, text=True, env=CLEAN_ENV)


def test_worktree_new_creates_branch_marker_and_prints_the_path(tmp_path):
    root = corpus_repo(tmp_path)
    assert git(root, 'branch', 'staging').returncode == 0
    done = worktree(root, 'new', 'sluga')
    assert done.returncode == 0, done.stderr
    path = Path(done.stdout.strip())
    assert path == root / '.claude/worktrees/sluga'
    marker = (path / MARKER).read_text(encoding='utf-8')
    assert 'branch=feat/sluga' in marker
    assert 'base=staging' in marker
    assert git(path, 'branch', '--show-current').stdout.strip() == 'feat/sluga'


def test_worktree_done_refuses_while_work_is_uncommitted(tmp_path):
    """The property the tool exists for: teardown must never eat work. The
    planted marker itself must NOT count as dirt — only real files do."""
    root = corpus_repo(tmp_path)
    assert git(root, 'branch', 'staging').returncode == 0
    path = Path(worktree(root, 'new', 'dirty').stdout.strip())
    (path / 'half-done.gd').write_text('# wip\n', encoding='utf-8')
    done = worktree(root, 'done', 'dirty')
    assert done.returncode != 0
    assert 'REFUSING' in done.stderr
    assert path.is_dir()
    (path / 'half-done.gd').unlink()
    assert worktree(root, 'done', 'dirty').returncode == 0, 'marker read as dirt'
    assert not path.exists()


def test_worktree_done_keeps_an_unmerged_branch_and_deletes_a_merged_one(
        tmp_path):
    root = corpus_repo(tmp_path)
    assert git(root, 'branch', 'staging').returncode == 0
    path = Path(worktree(root, 'new', 'keeper').stdout.strip())
    (path / 'landed.gd').write_text('# done\n', encoding='utf-8')
    assert git(path, 'add', 'landed.gd').returncode == 0
    assert git(path, 'commit', '-q', '-m', 'feat: landed',
               '--', 'landed.gd').returncode == 0
    done = worktree(root, 'done', 'keeper')
    assert done.returncode == 0, done.stderr
    assert 'NOT merged' in done.stderr
    assert git(root, 'show-ref', '--verify',
               'refs/heads/feat/keeper').returncode == 0, 'commits were lost'
    # Merge it, re-run done: now the branch goes too.
    assert git(root, 'checkout', '-q', 'staging').returncode == 0
    assert git(root, 'merge', '-q', 'feat/keeper').returncode == 0
    assert git(root, 'branch', '-d', 'feat/keeper').returncode == 0


def test_worktree_new_bases_off_the_building_milestones_branch(tmp_path):
    """The devkit PM tree is the source for the integration branch: a
    milestone declaring `branch:` while `building` is where agents branch
    from, not the trunk — basing off the trunk strands the agent behind every
    commit the milestone already landed."""
    root = corpus_repo(tmp_path)
    assert git(root, 'branch', 'staging').returncode == 0
    assert git(root, 'branch', 'feat/integration').returncode == 0
    milestone = root / 'pm/roadmap/0.1.0-thing/milestone.md'
    milestone.parent.mkdir(parents=True)
    milestone.write_text('---\nid: "0.1.0"\nstatus: building\n'
                         'branch: feat/integration\n---\n', encoding='utf-8')
    done = worktree(root, 'new', 'based')
    assert done.returncode == 0, done.stderr
    marker = (Path(done.stdout.strip()) / MARKER).read_text(encoding='utf-8')
    assert 'base=feat/integration' in marker


# --- doctor: self-heals the hook wiring, reds on a missing critical dep -------
def doctor_env(stub_bin: Path) -> dict:
    """A deterministic PATH: the stubs + the system dirs (git, make, awk) —
    whatever godot/gdlint/uv the HOST has must not decide a test."""
    return dict(CLEAN_ENV, PATH=f'{stub_bin}:/usr/bin:/bin')


def stub_tools(parent: Path, *names: str) -> Path:
    stub_bin = parent / 'stub-bin'
    stub_bin.mkdir(parents=True, exist_ok=True)
    versions = {'godot': '4.6.stable.official',
                'gdlint': 'gdlint 4.3.1',
                'uv': 'uv 0.5.0',
                'shellcheck': 'version: 0.11.0'}
    for name in names:
        tool = stub_bin / name
        tool.write_text(f'#!/bin/sh\necho "{versions[name]}"\n',
                        encoding='utf-8')
        tool.chmod(0o755)
    return stub_bin


def run_doctor(root: Path, stub_bin: Path) -> subprocess.CompletedProcess:
    return subprocess.run(['bash', str(root / DOCTOR)], cwd=root,
                          capture_output=True, text=True,
                          env=doctor_env(stub_bin))


def ready_repo(tmp_path: Path) -> tuple[Path, Path]:
    """Corpus repo + every critical dep satisfied: stubs on PATH, GUT entry
    present, hooks armed (setup-hooks), hooksPath deliberately UNSET so the
    self-heal has something to do."""
    root = corpus_repo(tmp_path)
    gut = root / 'addons/gut/gut_cmdln.gd'
    gut.parent.mkdir(parents=True)
    gut.write_text('# GUT\n', encoding='utf-8')
    subprocess.run(['git', 'config', '--unset', 'core.hooksPath'], cwd=root,
                   check=True)
    return root, stub_tools(tmp_path, 'godot', 'gdlint', 'uv', 'shellcheck')


def test_doctor_passes_a_ready_toolchain_and_heals_the_hook_wiring(tmp_path):
    root, stub_bin = ready_repo(tmp_path)
    done = run_doctor(root, stub_bin)
    assert done.returncode == 0, done.stdout
    assert '[DOCTOR] PASS' in done.stdout
    healed = git(root, 'config', 'core.hooksPath').stdout.strip()
    assert healed == 'tools/hooks', 'doctor did not self-heal core.hooksPath'


def test_doctor_reds_when_a_critical_dep_is_missing(tmp_path):
    root, _ = ready_repo(tmp_path)
    without_godot = stub_tools(tmp_path / 'partial', 'gdlint', 'uv')
    done = run_doctor(root, without_godot)
    assert done.returncode == 1
    assert 'godot not on PATH' in done.stdout
    assert '[DOCTOR] FAIL' in done.stdout


def test_doctor_reds_on_a_disarmed_hook_whatever_its_name(tmp_path):
    """core.hooksPath skips a non-executable hook in silence, and the census
    is asked of the DIRECTORY — a hook invented after the doctor shipped is
    still covered, which is what a hardcoded roster can never promise."""
    root, stub_bin = ready_repo(tmp_path)
    invented = root / 'tools/hooks/cc-invented-later.sh'
    invented.write_text('#!/usr/bin/env bash\nexit 0\n', encoding='utf-8')
    invented.chmod(0o644)
    done = run_doctor(root, stub_bin)
    assert done.returncode == 1
    assert 'cc-invented-later.sh not executable' in done.stdout


@pytest.mark.parametrize('shape', ['directory', 'broken symlink'])
def test_doctor_reds_on_an_entry_git_cannot_exec_at_all(tmp_path, shape):
    """The other way a guard dies: not a lost exec bit but a name git tries
    and cannot start. doctor skipped these on `[ -f ]`, so its census read
    SMALLER than the directory with no line saying so — the same defect
    `check hooks` carried, and two shipped surfaces agreeing on the wrong
    answer is worse than one."""
    root, stub_bin = ready_repo(tmp_path)
    dead = root / 'tools/hooks' / A_GIT_HOOK
    dead.unlink()
    if shape == 'directory':
        dead.mkdir()
    else:
        dead.symlink_to('../../gone/somewhere.sh')
    done = run_doctor(root, stub_bin)
    assert done.returncode == 1, done.stdout
    assert f'tracked hook {A_GIT_HOOK} is not a regular file' in done.stdout, done.stdout
    assert '[DOCTOR] FAIL' in done.stdout


def test_doctor_still_warns_rather_than_reds_on_an_EMPTY_corpus(tmp_path):
    """The one thing the `-f` skip was load-bearing for: an unmatched glob is
    the literal pattern, and a census that turned THAT into a finding would be
    a gate reddening on nothing. `no tracked hooks` is still the answer."""
    root, stub_bin = ready_repo(tmp_path)
    for entry in (root / 'tools/hooks').iterdir():
        entry.unlink()
    done = run_doctor(root, stub_bin)
    assert 'no tracked hooks under tools/hooks/' in done.stdout, done.stdout
    assert 'is not a regular file' not in done.stdout, done.stdout


# --- fail-open posture, both PreToolUse hooks ---------------------------------
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


# =============================================================================
# The 0.22.0 corpus: cc-ledger-subagent (SubagentStop) and cc-ledger-session
# (Stop) — the two couriers, installed into a temp repo that has a REAL PM
# tree and a Makefile whose `pm` target runs this source tree's CLI, then fired
# at the exact JSON Claude Code delivers.
#
# The assertion is always the same pair, because it is the whole contract: what
# landed in the milestone's ledger.jsonl, and that the hook exited 0 either
# way. A hook that blocks a stop is broken even when it is right, and a hook
# that invents a row is broken even when it exits 0.
# =============================================================================

LEDGER_SUBAGENT = 'tools/hooks/cc-ledger-subagent.sh'
LEDGER_SESSION = 'tools/hooks/cc-ledger-session.sh'
TRANSCRIPTS = Path(__file__).parent / 'fixtures' / 'transcripts'
DISPATCH_JSONL = TRANSCRIPTS / 'subagent-dispatch.jsonl'
SESSION_JSONL = TRANSCRIPTS / 'main-session.jsonl'
LEDGER_REL = 'pm/roadmap/0.1-demo/ledger.jsonl'

# The ids the payloads below carry. Spelled once so a test asserting they were
# COPIED cannot accidentally assert against a value the verb derived.
PAYLOAD_SESSION_ID = '11111111-2222-3333-4444-555555555555'
PAYLOAD_AGENT_ID = 'ag-0c097f0217026051'
PAYLOAD_AGENT_TYPE = 'developer'

# `.PHONY: pm` is load-bearing, not decoration: a PM tree IS a `pm/` directory
# at the repo root, so an un-phony `pm` target is one make calls up to date —
# the vehicle would exit 0, print nothing, and write no row. Both hooks say so
# in their config header; this Makefile is the proof it matters.
PM_MAKEFILE = ('.PHONY: pm\n'
               'pm:\n'
               '\t@PYTHONPATH={src} {python} -m godot_devkit.cli pm $(ARGS)\n')

FRONTMATTER = {
    'pm/roadmap/0.1-demo/milestone.md':
        {'id': '"0.1"', 'name': 'Demo', 'status': 'building'},
    'pm/roadmap/0.1-demo/features/alpha/feature.md':
        {'id': '0.1/alpha', 'milestone': '"0.1"', 'name': 'Alpha',
         'status': 'building', 'reviewed': ''},
    'pm/roadmap/0.1-demo/features/alpha/stories/s0.md':
        {'id': '0.1/alpha/s0', 'feature': '0.1/alpha', 'milestone': '"0.1"',
         'name': 'S0', 'status': 'building'},
}


def ledger_repo(tmp_path: Path, name: str = 'repo',
                with_makefile: bool = True, shell: str | None = None) -> Path:
    """The corpus installed into a repo with one `building` milestone.

    Deliberately built by hand rather than through `pm new`: the hooks are the
    thing under test, and a scaffolder failure here would read as a hook
    failure.

    `shell` pins the Makefile's recipe shell. Unset is the stock consumer —
    make's default `/bin/sh`, which on macOS is bash and therefore forgiving of
    a bash-only spelling. A vehicle that names dash is the honest one.
    """
    root = corpus_repo(tmp_path, name)
    for rel, front in FRONTMATTER.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        body = ['---'] + [f'{k}: {v}' for k, v in front.items()] + ['---', '', 'x', '']
        path.write_text('\n'.join(body), encoding='utf-8')
    if with_makefile:
        prologue = f'SHELL := {shell}\n' if shell else ''
        (root / 'Makefile').write_text(
            prologue + PM_MAKEFILE.format(src=REPO_ROOT / 'src',
                                          python=sys.executable),
            encoding='utf-8')
    return root


def subagent_event(root: Path, transcript: Path | str | None = DISPATCH_JSONL,
                   **over) -> dict:
    """The SubagentStop payload, every documented key present."""
    event = {
        'session_id': PAYLOAD_SESSION_ID,
        'transcript_path': str(SESSION_JSONL),
        'cwd': str(root),
        'permission_mode': 'acceptEdits',
        'hook_event_name': 'SubagentStop',
        'stop_hook_active': False,
        'agent_id': PAYLOAD_AGENT_ID,
        'agent_type': PAYLOAD_AGENT_TYPE,
        'agent_transcript_path': str(transcript) if transcript else None,
        # Never read — the agent's narration, the one source this SDLC refuses
        # to trust. It is on the payload so a test can prove it is ignored.
        'last_assistant_message': 'I used about 12000 tokens and 4 tools.',
        'background_tasks': [],
        'session_crons': [],
    }
    event.update(over)
    return {k: v for k, v in event.items() if v is not None}


def session_event(root: Path, transcript: Path | str | None = SESSION_JSONL,
                  **over) -> dict:
    """The Stop payload — no agent_id, no agent_type, no agent transcript."""
    event = {
        'session_id': PAYLOAD_SESSION_ID,
        'transcript_path': str(transcript) if transcript else None,
        'cwd': str(root),
        'permission_mode': 'acceptEdits',
        'hook_event_name': 'Stop',
        'stop_hook_active': False,
        'last_assistant_message': 'Done.',
        'background_tasks': [],
        'session_crons': [],
    }
    event.update(over)
    return {k: v for k, v in event.items() if v is not None}


def fire_ledger(root: Path, hook: str, event: dict | str,
                env: dict | None = None) -> subprocess.CompletedProcess:
    payload = event if isinstance(event, str) else json.dumps(event)
    return subprocess.run(['bash', str(root / hook)], input=payload, text=True,
                          capture_output=True, cwd=root, env=env or CLEAN_ENV)


def ledger_rows(root: Path) -> list[dict]:
    path = root / LEDGER_REL
    if not path.is_file():
        return []
    return [json.loads(line)
            for line in path.read_text(encoding='utf-8').splitlines() if line]


# --- cc-ledger-subagent: the dispatch row -------------------------------------
def test_a_subagent_stop_payload_records_exactly_one_dispatch_row(tmp_path):
    """The ship criterion, end to end: the event Claude Code delivers goes in,
    one `dispatch` row comes out, and every id on it was COPIED from the
    payload rather than derived from the transcript."""
    root = ledger_repo(tmp_path)
    done = fire_ledger(root, LEDGER_SUBAGENT, subagent_event(root))
    assert done.returncode == 0, done.stderr
    rows = ledger_rows(root)
    assert len(rows) == 1, rows
    row = rows[0]
    assert row['kind'] == 'dispatch'
    assert row['agent_type'] == PAYLOAD_AGENT_TYPE
    assert row['agent_id'] == PAYLOAD_AGENT_ID
    assert row['session_id'] == PAYLOAD_SESSION_ID
    # The transcript it was handed is the AGENT's, not the session's: the two
    # differ, and a hook reading `transcript_path` here would file the
    # orchestrator's totals as a dispatch.
    assert row['tools'] == {'Bash': 22, 'Write': 1}, row
    # D3: the tree's live state, verbatim, at the instant of the row.
    assert row['tree']['stories_wip'] == ['0.1/alpha/s0'], row


def test_the_subagent_hook_never_reads_the_agents_own_narration(tmp_path):
    """`last_assistant_message` claims 12000 tokens and 4 tools; the row must
    carry the transcript's numbers and none of the agent's."""
    root = ledger_repo(tmp_path)
    assert fire_ledger(root, LEDGER_SUBAGENT,
                       subagent_event(root)).returncode == 0
    row = ledger_rows(root)[0]
    assert row['tool_calls'] == 23, row
    assert row['usage']['output'] == 5829, row


# --- cc-ledger-session: the session row ---------------------------------------
def test_a_stop_payload_records_exactly_one_session_row(tmp_path):
    root = ledger_repo(tmp_path)
    done = fire_ledger(root, LEDGER_SESSION, session_event(root))
    assert done.returncode == 0, done.stderr
    rows = ledger_rows(root)
    assert len(rows) == 1, rows
    assert rows[0]['kind'] == 'session'
    assert rows[0]['session_id'] == PAYLOAD_SESSION_ID
    # A Stop event has no agent, so the row carries neither agent field —
    # absent, never an empty string standing in for one.
    assert 'agent_id' not in rows[0], rows[0]
    assert 'agent_type' not in rows[0], rows[0]


# --- the fail-open matrix: no row, exit 0, and it SAYS SO ----------------------
@pytest.mark.parametrize('hook,event', [
    (LEDGER_SUBAGENT, 'agent_transcript_path'),
    (LEDGER_SESSION, 'transcript_path'),
])
def test_a_payload_with_no_transcript_path_writes_no_row_and_says_why(
        tmp_path, hook, event):
    """An older Claude Code, or an event shape that carries no path. No row —
    and never an invented one — but the operator must be able to find out why
    the ledger is empty."""
    root = ledger_repo(tmp_path)
    build = subagent_event if hook == LEDGER_SUBAGENT else session_event
    done = fire_ledger(root, hook, build(root, transcript=None))
    assert done.returncode == 0
    assert ledger_rows(root) == []
    assert f'carries no {event}' in done.stderr, done.stderr
    assert len(done.stderr.strip().splitlines()) == 1, done.stderr


@pytest.mark.parametrize('hook', [LEDGER_SUBAGENT, LEDGER_SESSION])
def test_a_payload_that_is_not_json_writes_no_row_and_says_why(tmp_path, hook):
    root = ledger_repo(tmp_path)
    done = fire_ledger(root, hook, 'not json {{{')
    assert done.returncode == 0
    assert ledger_rows(root) == []
    assert 'not JSON this hook can read' in done.stderr, done.stderr


@pytest.mark.parametrize('hook', [LEDGER_SUBAGENT, LEDGER_SESSION])
def test_a_repo_with_no_makefile_writes_no_row_and_says_why(tmp_path, hook):
    """Installed ahead of the dev loop there is no vehicle to reach the verb
    through. Fail OPEN, out loud — and never pretend a row was written."""
    root = ledger_repo(tmp_path, with_makefile=False)
    build = subagent_event if hook == LEDGER_SUBAGENT else session_event
    done = fire_ledger(root, hook, build(root))
    assert done.returncode == 0
    assert ledger_rows(root) == []
    assert 'has no Makefile' in done.stderr, done.stderr


@pytest.mark.parametrize('hook', [LEDGER_SUBAGENT, LEDGER_SESSION])
def test_a_tilde_prefixed_transcript_path_is_expanded(tmp_path, hook):
    """Claude Code may deliver `~/.claude/projects/…`. The shell does not
    expand a tilde that arrives inside a variable, so the hook must — an
    unexpanded one reaches the verb as a relative path that is not a file, and
    the row is silently lost."""
    home = tmp_path / 'home'
    home.mkdir()
    source = DISPATCH_JSONL if hook == LEDGER_SUBAGENT else SESSION_JSONL
    shutil.copy(source, home / 'transcript.jsonl')
    root = ledger_repo(tmp_path)
    build = subagent_event if hook == LEDGER_SUBAGENT else session_event
    done = fire_ledger(root, hook, build(root, transcript='~/transcript.jsonl'),
                       env={**CLEAN_ENV, 'HOME': str(home)})
    assert done.returncode == 0, done.stderr
    assert len(ledger_rows(root)) == 1, done.stderr


# --- the vehicle's shell is not this hook's ------------------------------------
# `make` runs a recipe under `/bin/sh` unless the Makefile says otherwise, and a
# hand-rolled consumer Makefile may say dash. Every word the courier spells INTO
# `ARGS=` is parsed by that shell, so a value spelled as a bash literal is a
# value the vehicle may not decode. The couriers used `printf %q`, which is
# BASH's quoting: a non-ASCII path comes back as `$'…'`, dash keeps the `$` as
# text, the verb refuses "is not a file" at exit 2 — and this hook always exits
# 0, so the row is lost with nothing red anywhere
# (0.24.0/bugs/courier-path-quoting-needs-a-bash-shell).
#
# There is a SECOND dimension, and it is why this was invisible: `printf %q` is
# LOCALE-sensitive. Under `LC_ALL=en_US.UTF-8` bash 3.2 calls `é` printable and
# emits it bare, so the same courier, the same path and the same dash vehicle
# record the row perfectly — while under `C`/`POSIX`, or with the locale simply
# unset, it emits `$'…'` and the row is lost. A hook is spawned by an app, a
# daemon or a CI runner, none of which promise a UTF-8 locale, so `C` is the
# honest vehicle and it is pinned rather than inherited: a case whose verdict
# depends on the runner's locale is a case that proves nothing on the day it
# passes. (`uv run` exports `LC_CTYPE=C.UTF-8`, and it hid this entirely.)
VEHICLE_ENV = {'LC_ALL': 'C'}

# The directories below are the matrix. Every one is a legal name a transcript
# could sit under, and every one must land its row under a vehicle that is not
# bash. `café` is the case that was silently lost; the other six are the rest of
# the grammar the transport now has to be indifferent to, including a newline,
# which no spelling into a make command-line variable can survive at all.
DASH = shutil.which('dash') or '/bin/dash'
needs_dash = pytest.mark.skipif(
    not Path(DASH).exists(),
    reason='needs a POSIX shell that is not bash (dash) to be a real vehicle')

HOSTILE_DIRS = [
    pytest.param('café', id='non-ascii'),
    pytest.param('a b', id='space'),
    pytest.param("it's", id='apostrophe'),
    pytest.param('$HOME', id='dollar'),
    pytest.param('back`tick', id='backtick'),
    pytest.param('semi;colon', id='semicolon'),
    pytest.param('two\nlines', id='newline'),
]


@needs_dash
@pytest.mark.parametrize('hook', [LEDGER_SUBAGENT, LEDGER_SESSION])
@pytest.mark.parametrize('directory', HOSTILE_DIRS)
def test_a_hostile_transcript_path_still_records_under_a_dash_vehicle(
        tmp_path, hook, directory):
    """Both couriers, because the transport is duplicated in both files and
    "fixed in one of them" is the failure mode a duplicated fix has."""
    root = ledger_repo(tmp_path, shell=DASH)
    holder = tmp_path / 'transcripts' / directory
    holder.mkdir(parents=True)
    transcript = holder / 't.jsonl'
    shutil.copy(DISPATCH_JSONL if hook == LEDGER_SUBAGENT else SESSION_JSONL,
                transcript)
    build = subagent_event if hook == LEDGER_SUBAGENT else session_event
    done = fire_ledger(root, hook, build(root, transcript=transcript),
                       env={**CLEAN_ENV, **VEHICLE_ENV})
    assert done.returncode == 0, done.stderr
    rows = ledger_rows(root)
    # The verb refuses a `--from-transcript` that is not a file, so a row at
    # all proves the vehicle handed it THIS path byte-exact; the numbers prove
    # it read the file rather than inventing one.
    assert len(rows) == 1, f'no row landed. the vehicle said: {done.stderr}'
    assert rows[0]['tool_calls'] > 0, rows[0]


@needs_dash
@pytest.mark.parametrize('hook', [LEDGER_SUBAGENT, LEDGER_SESSION])
def test_a_dash_vehicle_carries_no_value_inside_the_args_word(tmp_path, hook):
    """The mechanism, not just the outcome: `ARGS=` must hold FIXED words only.

    A courier that merely quoted better would still pass the case above on
    every path somebody thought to list. What removes the class is that the
    path is not in the string at all — so the assertion is on the string.
    """
    root = ledger_repo(tmp_path, shell=DASH)
    holder = tmp_path / 'café dir'
    holder.mkdir()
    transcript = holder / 't.jsonl'
    shutil.copy(DISPATCH_JSONL if hook == LEDGER_SUBAGENT else SESSION_JSONL,
                transcript)
    # A vehicle that echoes the ARGS it was handed, verbatim and UNEXPANDED —
    # single quotes in the recipe, so the recipe shell reads the words rather
    # than resolving them. make expands `$(ARGS)` inside them regardless, which
    # is the whole reason a `'` in ARGS would be a defect of its own.
    (root / 'Makefile').write_text(
        f"SHELL := {DASH}\n.PHONY: pm\npm:\n\t@printf %s '$(ARGS)'\n",
        encoding='utf-8')
    build = subagent_event if hook == LEDGER_SUBAGENT else session_event
    done = fire_ledger(root, hook, build(root, transcript=transcript),
                       env={**CLEAN_ENV, **VEHICLE_ENV})
    assert done.returncode == 0, done.stderr
    args = done.stderr
    assert 'café' not in args, f'the path is spelled into ARGS: {args}'
    assert '303' not in args, f'the path is spelled into ARGS: {args}'
    assert '"$GDK_LEDGER_TRANSCRIPT"' in args, args


@pytest.mark.parametrize('hook', [LEDGER_SUBAGENT, LEDGER_SESSION])
def test_a_refusal_from_the_verb_is_passed_through_and_still_exits_0(
        tmp_path, hook):
    """`--from-transcript <not a file>` is a refusal the VERB owns. The hook
    neither pre-empts it nor swallows it: the sentence reaches the hook log
    and the stop is not blocked."""
    root = ledger_repo(tmp_path)
    build = subagent_event if hook == LEDGER_SUBAGENT else session_event
    done = fire_ledger(root, hook, build(root, transcript='/nope/absent.jsonl'))
    assert done.returncode == 0
    assert ledger_rows(root) == []
    assert 'is not a file' in done.stderr, done.stderr


@pytest.mark.parametrize('hook', [LEDGER_SUBAGENT, LEDGER_SESSION])
def test_the_ledger_hooks_replay_their_own_corpus(tmp_path, hook):
    """`--self-test` is the shipped proof, and it must pass as INSTALLED."""
    root = ledger_repo(tmp_path)
    done = subprocess.run(['bash', str(root / hook), '--self-test'],
                          capture_output=True, text=True, cwd=root,
                          env=CLEAN_ENV)
    assert done.returncode == 0, done.stdout + done.stderr
    assert 'SELF-TEST OK' in done.stdout, done.stdout


# --- doctor: the uid index against the sidecars the repo tracks ---------------
# 0.24.0/bugs/import-cache-rebuild-does-not-repair-a-stale-uid-index. A
# consumer ran 147 scenarios against a `.godot` whose uid index had lost 56
# tracked sidecars: every scenario printed its own PASS and every one of them
# was FAILED by the runner's engine-noise sweep, and the runner's remedy — an
# import pass against the EXISTING directory — cannot put those entries back.
# The runner now escalates (test_runners_installable.py); this is the cheaper
# half, which says so in one line BEFORE a 147-scenario sweep instead of after.
#
# The fixture writes a REAL uid_cache.bin layout — u32 count, then per entry a
# u64 id, a u32 length and the raw path — because what the check does is search
# that binary, and a text stand-in would prove the search against a file the
# engine never writes.
def fake_uid_cache(paths: tuple[str, ...], *, uid: int | None = None) -> bytes:
    body = struct.pack('<I', len(paths))
    for index, path in enumerate(paths):
        raw = path.encode('utf-8')
        ident = uid if uid is not None else 0x7F00000000000000 + index
        body += struct.pack('<QI', ident, len(raw)) + raw
    return body


def godot_repo(tmp_path: Path, sidecars: tuple[str, ...],
               indexed: tuple[str, ...], *, gdignore: tuple[str, ...] = (),
               cache: bool = True,
               uid: int | None = None) -> tuple[Path, Path]:
    """A ready corpus repo that is ALSO a Godot project: `sidecars` are tracked
    `.uid` files, `indexed` are the res:// paths the binary index names."""
    root, stub_bin = ready_repo(tmp_path)
    (root / 'project.godot').write_text('config_version=5\n', encoding='utf-8')
    for index, rel in enumerate(sidecars):
        sidecar = root / f'{rel}.uid'
        sidecar.parent.mkdir(parents=True, exist_ok=True)
        sidecar.write_text(f'uid://c{index}\n', encoding='utf-8')
        source = root / rel
        source.write_text('extends Node\n', encoding='utf-8')
    for directory in gdignore:
        (root / directory).mkdir(parents=True, exist_ok=True)
        (root / directory / '.gdignore').write_text('', encoding='utf-8')
    subprocess.run(['git', 'add', '-A'], cwd=root, check=True,
                   capture_output=True)
    if cache:
        (root / '.godot').mkdir(exist_ok=True)
        (root / '.godot' / 'uid_cache.bin').write_bytes(
            fake_uid_cache(indexed, uid=uid))
    return root, stub_bin


def test_doctor_reds_on_a_uid_index_missing_a_tracked_sidecar(tmp_path):
    """The 56-missing tree, in miniature. The line has to name the shortfall
    AND the only repair that works — a plain rebuild is what did not."""
    root, stub_bin = godot_repo(
        tmp_path, ('systems/alpha.gd', 'systems/beta.gd', 'shaders/glow.gdshader'),
        ('res://systems/alpha.gd', 'res://scenes/hub.tscn'))
    done = run_doctor(root, stub_bin)
    assert done.returncode == 1, done.stdout
    assert '2 of 3' in done.stdout, done.stdout
    assert 'rm -rf .godot' in done.stdout, done.stdout
    # It names what is missing: a count alone cannot be acted on.
    assert 'res://systems/beta.gd' in done.stdout, done.stdout
    assert '[DOCTOR] FAIL' in done.stdout, done.stdout


def test_doctor_passes_a_uid_index_that_covers_every_tracked_sidecar(tmp_path):
    """The control. Without it the case above is satisfied by a check that
    fails on every tree, which is the same as no check."""
    root, stub_bin = godot_repo(
        tmp_path, ('systems/alpha.gd', 'shaders/glow.gdshader'),
        ('res://systems/alpha.gd', 'res://shaders/glow.gdshader',
         'res://scenes/hub.tscn'))
    done = run_doctor(root, stub_bin)
    assert done.returncode == 0, done.stdout
    assert '2 tracked .uid sidecar' in done.stdout, done.stdout


def test_doctor_does_not_count_a_sidecar_the_editor_never_scans(tmp_path):
    """A directory carrying `.gdignore` is invisible to the editor filesystem,
    so nothing under it is ever indexed. Counting those would red a healthy
    tree — nullbound tracks two of them."""
    root, stub_bin = godot_repo(
        tmp_path, ('systems/alpha.gd', 'worktrees/scratch/copy.gd'),
        ('res://systems/alpha.gd',), gdignore=('worktrees',))
    done = run_doctor(root, stub_bin)
    assert done.returncode == 0, done.stdout
    assert '1 tracked .uid sidecar' in done.stdout, done.stdout


def test_doctor_never_claims_a_sidecar_a_longer_path_could_be_hiding(tmp_path):
    """The index is binary, so membership is a substring search — and
    `res://a/x.gd` is a substring of `res://a/x.gdshader`. A path that is a
    proper prefix of another expected path is therefore UNVERIFIABLE by that
    search, and is reported as unverifiable rather than counted as present.
    Both live consumers have zero such pairs; a check that is only usually
    exact is not a check."""
    root, stub_bin = godot_repo(
        tmp_path, ('a/x.gd', 'a/x.gdshader'), ('res://a/x.gdshader',))
    done = run_doctor(root, stub_bin)
    assert 'res://a/x.gd' in done.stdout, done.stdout
    assert 'unverifiable' in done.stdout, done.stdout
    # The census names what it actually checked, and x.gd is not in it.
    assert '1 tracked .uid sidecar' in done.stdout, done.stdout


def test_doctor_warns_rather_than_passing_when_there_is_no_import_cache(tmp_path):
    """A cold checkout has no `.godot/` at all. That is a fresh tree, not a
    broken one — but it must not read as 'the index is fine'."""
    root, stub_bin = godot_repo(tmp_path, ('systems/alpha.gd',), (),
                                cache=False)
    done = run_doctor(root, stub_bin)
    assert done.returncode == 0, done.stdout
    assert 'no .godot/uid_cache.bin' in done.stdout, done.stdout
    assert 'make import-cache' in done.stdout, done.stdout


def test_doctor_says_so_when_it_has_nothing_to_check_the_index_against(tmp_path):
    """Rule 4: a zero-file census that prints a pass is the read-side cardinal
    sin. Zero tracked sidecars is a real state of a fresh project, and the line
    says the number rather than implying coverage."""
    root, stub_bin = godot_repo(tmp_path, (), ('res://scenes/hub.tscn',))
    done = run_doctor(root, stub_bin)
    assert done.returncode == 0, done.stdout
    assert '0 tracked .uid sidecar' in done.stdout, done.stdout


def test_doctor_says_nothing_about_uids_in_a_repo_that_is_not_a_godot_project(tmp_path):
    """doctor ships to every repo that installs the hook corpus, and this
    package's own tree is not a Godot project. A check with no subject must be
    silent, not a warning nobody can act on."""
    root, stub_bin = ready_repo(tmp_path)
    done = run_doctor(root, stub_bin)
    assert done.returncode == 0, done.stdout
    assert 'uid' not in done.stdout.lower(), done.stdout


def test_doctor_finds_a_path_the_next_entrys_id_glued_printable_bytes_onto(tmp_path):
    """The extraction turns non-printable bytes into separators, so a path
    lands at the start of a token — but the bytes AFTER it are the next
    entry's 64-bit id, and roughly a third of those are printable ASCII. On a
    1800-entry cache that is hundreds of tokens carrying trailing junk, so
    membership is decided by PREFIX and never by equality. Here every id is
    0x4141… — eight `A`s glued to every path."""
    root, stub_bin = godot_repo(
        tmp_path, ('systems/alpha.gd',),
        ('res://systems/alpha.gd', 'res://scenes/hub.tscn'),
        uid=0x4141414141414141)
    done = run_doctor(root, stub_bin)
    assert done.returncode == 0, done.stdout
    assert 'uid index covers 1 tracked .uid sidecar' in done.stdout, done.stdout
