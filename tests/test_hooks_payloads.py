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
    'godot-devkit check all',              # this toolkit's own CLI — never a boot
    '$GODOT --version',                    # variable resolved, still query-only
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
])
def test_sandbox_blocks_every_raw_boot_shape(hooks_repo, command):
    assert fire(hooks_repo, SANDBOX, command) == 2


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
