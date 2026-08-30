"""test_install.py — the install-* verbs, and the one property they all rest on.

An install verb writes a file. Once. If the destination is there and differs it
refuses, names the path and names `--force`; `--diff` shows what would change
and writes nothing. There is no manifest, no drift tracking and no merge — the
whole relationship is those four sentences, and each one is a test below.

The property that is not obvious from the verb's description is ATOMICITY: an
install either happens whole or does not happen. A refusal raised mid-plan left
a half-installed repo behind and still claimed nothing was written.

The hook installables carry one more: they are STANDALONE. The forked copies in
both consumers `source tools/hooks/_scope.sh` for a project-name-prefixed JSON
reader; a `source` of a file a fresh project does not have fails OPEN, and a
guard that fails open is a guard that is not there. So the tests below install
into an empty repo with no library of any kind and RUN the hooks.
"""
from __future__ import annotations

import contextlib
import io
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from support import REPO_ROOT  # noqa: E402

sys.path.insert(0, str(REPO_ROOT / 'src'))
from godot_devkit.core.project import load_config, repo_root  # noqa: E402
from godot_devkit.repo import install  # noqa: E402


@contextlib.contextmanager
def repo(files: dict[str, str] | None = None):
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / 'repo'
        root.mkdir()
        for rel, body in (files or {}).items():
            target = root / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(body, encoding='utf-8')
        subprocess.run(['git', 'init', '-q'], cwd=root, check=True)
        previous = Path.cwd()
        os.chdir(root)
        repo_root.cache_clear()
        load_config.cache_clear()
        try:
            yield root
        finally:
            os.chdir(previous)
            repo_root.cache_clear()
            load_config.cache_clear()


def run(command: str, *argv: str) -> tuple[int, str]:
    """Exit code + STDOUT."""
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        code = install.main(command, list(argv))
    return code, buffer.getvalue()


def refuse(command: str, *argv: str) -> tuple[int, str]:
    """Exit code + both streams, for the runs that print their refusal."""
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer), contextlib.redirect_stderr(buffer):
        code = install.main(command, list(argv))
    return code, buffer.getvalue()


WORKFLOW = '.github/workflows/verify.yml'
AGENTS = ('.claude/agents/verification-reviewer.md',
          '.claude/agents/verification-builder.md')
HOOKS = ('tools/hooks/cc-commit-pathspec.sh',
         'tools/hooks/cc-godot-sandbox.sh',
         'tools/hooks/cc-stop-gate.sh',
         'tools/hooks/cc-write-confine.sh',
         'tools/hooks/pre-push',
         'tools/hooks/prepare-commit-msg',
         'tools/dev/agent-worktree.sh',
         'tools/dev/checks/doctor.sh',
         'tools/setup-hooks.sh')
DESTINATIONS = {'install-ci': (WORKFLOW,),
                'install-agents': AGENTS,
                'install-hooks': HOOKS}
VERBS = tuple(DESTINATIONS)
# The table above is spelled out so a test READS as the contract, but it is
# not allowed to become a second roster: a verb added to PLANS and not here
# would be a verb every parametrized test below silently skips.
assert {verb: tuple(rel for _, rel in entries)
        for verb, entries in install.PLANS.items()} == DESTINATIONS


# --- the four sentences, once per verb ---------------------------------------
@pytest.mark.parametrize('command', VERBS)
def test_the_verb_writes_its_files_and_a_second_run_is_a_no_op(command):
    with repo() as root:
        code, out = run(command)
        assert code == 0, out
        bodies = {rel: (root / rel).read_text(encoding='utf-8')
                  for rel in DESTINATIONS[command]}
        assert all(bodies.values()), 'a destination was written empty'
        code, out = run(command)
        assert code == 0, out
        assert out.count('already current') == len(DESTINATIONS[command]), out
        assert {rel: (root / rel).read_text(encoding='utf-8')
                for rel in DESTINATIONS[command]} == bodies


@pytest.mark.parametrize('command', VERBS)
def test_a_destination_that_differs_is_refused_and_the_refusal_names_force(
        command):
    """`--force` is the whole remedy vocabulary, so the refusal must say it:
    a refusal that names no repair sends the operator to the source."""
    first = DESTINATIONS[command][0]
    mine = 'my own version, deliberately\n'
    with repo({first: mine}) as root:
        code, out = refuse(command)
        assert code == 1, out
        assert first in out and '--force' in out, out
        assert (root / first).read_text(encoding='utf-8') == mine


@pytest.mark.parametrize('command', VERBS)
def test_force_overwrites_every_entry(command):
    """The whole-or-nothing decision must not have turned --force into a
    refusal: an explicit flag is documented to clobber."""
    mine = 'my own version, deliberately\n'
    with repo({rel: mine for rel in DESTINATIONS[command]}) as root:
        code, out = run(command, '--force')
        assert code == 0, out
        for name, rel in install.PLANS[command]:
            assert ((root / rel).read_text(encoding='utf-8')
                    == install.body_of(name)), rel


@pytest.mark.parametrize('command', VERBS)
def test_diff_prints_a_unified_diff_and_writes_nothing(command):
    first = DESTINATIONS[command][0]
    mine = 'my own version, deliberately\n'
    with repo({first: mine}) as root:
        code, out = run(command, '--diff')
        assert code == 0, out
        # A real unified diff of the DIFFERING file …
        assert f'--- a/{first}' in out and f'+++ b/{first}' in out, out
        assert '-my own version, deliberately' in out, out
        # … and the ABSENT ones named as additions rather than shown as noise.
        for rel in DESTINATIONS[command][1:]:
            assert f'{rel} does not exist' in out, out
        # Nothing on disk moved: the differing file is untouched and the
        # absent ones are still absent.
        assert (root / first).read_text(encoding='utf-8') == mine
        for rel in DESTINATIONS[command][1:]:
            assert not (root / rel).exists(), rel


@pytest.mark.parametrize('command', VERBS)
def test_diff_of_an_installed_tree_reports_current_and_shows_no_hunks(command):
    with repo() as root:
        assert run(command)[0] == 0
        code, out = run(command, '--diff')
        assert code == 0
        assert out.count('already current') == len(DESTINATIONS[command]), out
        assert '@@' not in out, out
        assert root.is_dir()


def test_an_unknown_flag_is_a_usage_error():
    with repo():
        code, _ = refuse('install-ci', '--yolo')
        assert code == 2


# --- the install is whole, or it does not happen ------------------------------
@pytest.mark.parametrize('command', ('install-agents', 'install-hooks'))
def test_a_collision_on_a_LATER_entry_writes_nothing_at_all(command):
    """The defect: `install-agents` wrote the reviewer, THEN refused on the
    builder, and reported `nothing was written` about a repo that now held one
    of the two files. Every collision is decided before the first byte."""
    rels = DESTINATIONS[command]
    mine = 'my own version, deliberately\n'
    with repo({rels[-1]: mine}) as root:
        code, out = refuse(command)
        assert code == 1, out
        for earlier in rels[:-1]:
            assert not (root / earlier).exists(), (
                f'{earlier} was written before {rels[-1]} was refused')
        assert (root / rels[-1]).read_text(encoding='utf-8') == mine
        assert 'wrote' not in out


def test_every_collision_is_named_in_one_refusal():
    """Two collisions, one run: an operator must not have to re-install to
    discover the next file they need to move aside."""
    with repo({AGENTS[0]: 'mine\n', AGENTS[1]: 'mine too\n'}) as root:
        code, message = refuse('install-agents')
    assert code == 1
    for rel in AGENTS:
        assert rel in message, message
    assert 'nothing was written' in message
    assert root.name


def test_a_destination_that_is_a_directory_is_a_refusal_not_a_traceback():
    with repo() as root:
        (root / AGENTS[1]).mkdir(parents=True)
        code, out = refuse('install-agents')
    assert code == 1, out
    assert 'is a directory' in out and AGENTS[1] in out, out
    assert 'nothing was written' in out, out
    assert not (root / AGENTS[0]).exists(), (
        'the FIRST entry was written before the SECOND was found unwritable')


@pytest.mark.skipif(hasattr(os, 'geteuid') and os.geteuid() == 0,
                    reason='root ignores the write bit, so there is no '
                           'read-only destination to refuse')
def test_a_read_only_destination_is_a_refusal_that_writes_nothing():
    with repo() as root:
        assert run('install-agents')[0] == 0
        keep = (root / AGENTS[0]).read_text(encoding='utf-8')
        for rel in AGENTS:
            (root / rel).write_text('stale\n', encoding='utf-8')
        (root / AGENTS[1]).chmod(0o444)
        try:
            code, out = refuse('install-agents', '--force')
        finally:
            (root / AGENTS[1]).chmod(0o644)
        assert code == 1, out
        assert 'is not writable' in out, out
        # The first entry is the one that proves it: with --force it WOULD have
        # been rewritten, and a refusal decided up front leaves it alone.
        assert (root / AGENTS[0]).read_text(encoding='utf-8') == 'stale\n'
        assert keep


def test_a_non_utf8_destination_is_a_collision_and_force_overwrites_it():
    """Undecodable bytes cannot be compared with an installable, so the file is
    somebody else's — the same answer as any other differing file, not a
    crash."""
    with repo() as root:
        (root / AGENTS[1]).parent.mkdir(parents=True, exist_ok=True)
        (root / AGENTS[1]).write_bytes(b'\xff\xfe\x00not utf-8')
        code, out = refuse('install-agents')
        assert code == 1, out
        assert '--force' in out, out
        assert not (root / AGENTS[0]).exists(), out
        code, out = refuse('install-agents', '--diff')
        assert code == 0, out
        assert 'not text this can diff' in out, out
        code, out = refuse('install-agents', '--force')
        assert code == 0, out
        assert ((root / AGENTS[1]).read_text(encoding='utf-8')
                == install.body_of('verification-builder.md'))


# --- install-agents: what the contract is, and where it lands -----------------
def test_the_contract_ships_as_an_agent_definition_not_a_rule():
    """Measured, not assumed: a rules file never reaches a subagent's spawn
    context while its definition does. A contract written as a rule arrives
    nowhere, so the destination is part of the contract."""
    with repo() as root:
        run('install-agents')
        for rel in AGENTS:
            assert (root / rel).is_file()
            head = (root / rel).read_text(encoding='utf-8').splitlines()[:4]
            assert head[0] == '---'
            assert any(line.startswith('name: ') for line in head)
        assert not (root / '.claude' / 'rules').exists()


def test_the_load_bearing_sentences_survive_an_edit():
    """The lines the whole contract exists to deliver, pinned.

    If nothing else in the contract lands, these must — so a future trim that
    drops them fails here rather than being noticed a release later by their
    absence from a review that went badly.
    """
    with repo() as root:
        run('install-agents')
        reviewer = (root / AGENTS[0]).read_text(encoding='utf-8')
        builder = (root / AGENTS[1]).read_text(encoding='utf-8')
    assert 'Construct adversarial input and RUN it' in reviewer
    assert 'Never read a diff and reason about it' in reviewer
    assert 'FAILS against HEAD' in builder
    assert 'BEFORE and AFTER' in builder
    for body in (reviewer, builder):
        assert 'arrowing instead of reporting' in body
        assert 'token cost' in body


def test_the_installed_contracts_do_not_redden_a_consumers_gates():
    """Install day must be green. A contract that fails the gates it arrives
    beside gets deleted by the first person who runs them."""
    with repo({'devkit.toml': '[doc]\nscope = [".claude/agents/*.md"]\n'}) as root:
        run('install-agents')
        subprocess.run(['git', 'add', '-A'], cwd=root, check=True)
        # A SUBPROCESS on purpose. `check doc` binds its scope and its repo root
        # at import time, so reloading it in-process to see a temp repo leaves
        # the module pointing at a directory that no longer exists — and the
        # next test to import it inherits that. A gate run out-of-process cannot
        # contaminate the suite that runs it.
        proc = subprocess.run(
            [sys.executable, '-m', 'godot_devkit.cli', 'check', 'doc'],
            cwd=root, capture_output=True, text=True,
            env={**os.environ, 'PYTHONPATH': str(REPO_ROOT / 'src')})
        assert proc.returncode == 0, (
            'the installed contract fails `check doc` on install day:\n'
            f'{proc.stdout}{proc.stderr}')


# --- install-ci: one opinion, and the assumption said out loud ----------------
def test_the_workflow_runs_the_projects_full_gate_and_says_so():
    """No `[ci]` block, no emitter, no allowlist: the workflow the verb writes
    is the same one in every repo, and what it runs is a make target. The
    assumption is a COMMENT because a fresh project may not have the target,
    and a generator that went looking for one would be the ~180 lines of
    config DSL this verb exists without."""
    with repo() as root:
        assert run('install-ci')[0] == 0
        body = (root / WORKFLOW).read_text(encoding='utf-8')
    assert 'run: make milestone' in body
    assert 'ASSUMES `make milestone` is your full gate' in body
    assert 'actions/checkout@v4' in body and 'astral-sh/setup-uv@v5' in body
    # The cut config DSL, by the names it would reappear under.
    for gone in ('{ci_on}', '{ci_setup}', '{devkit_source}', '{version}'):
        assert gone not in body, gone


# --- install-hooks: canonical, and STANDALONE ---------------------------------
def test_the_hooks_carry_no_project_name_and_source_no_library():
    """The bulk of the divergence between the two forked copies was a
    project-name prefix on a shared library and its env var. One neutral name,
    defined where it is used: a hook that `source`s a library a fresh repo
    does not have fails OPEN, so the corpus ships every helper INLINE and the
    shared scope library ships as no file at all."""
    with repo() as root:
        assert run('install-hooks')[0] == 0
        for rel in HOOKS:
            body = (root / rel).read_text(encoding='utf-8')
            for banned in ('trail_', 'TRAIL_', 'nullbound', 'NULLBOUND',
                           '_scope.sh', 'source "'):
                assert banned not in body, f'{rel} carries {banned!r}'
        for rel in HOOKS[:2]:
            assert 'hook_json_field() {' in (
                root / rel).read_text(encoding='utf-8'), rel


CONFIG_HEADED = ('tools/hooks/cc-stop-gate.sh',
                 'tools/hooks/pre-push',
                 'tools/hooks/prepare-commit-msg',
                 'tools/dev/agent-worktree.sh',
                 'tools/dev/checks/doctor.sh')


def test_the_corpus_files_carry_an_editable_config_header():
    """Per-project variation is a config header the repo edits AFTER install,
    when the file is its own — never a fork of the source. The header marker
    is the contract; a rewrite that drops it drops the whole parameterization
    story."""
    with repo() as root:
        assert run('install-hooks')[0] == 0
        for rel in CONFIG_HEADED:
            body = (root / rel).read_text(encoding='utf-8')
            assert 'project config (yours to edit after install' in body, rel
        # The agent-context contract is one marker + one env var, spelled the
        # same in every file that reads it — a hook and the worktree tool
        # disagreeing on the marker name silently de-scopes the hook.
        for rel in ('tools/hooks/cc-stop-gate.sh', 'tools/hooks/pre-push',
                    'tools/hooks/prepare-commit-msg',
                    'tools/dev/agent-worktree.sh'):
            assert 'SCOPE_MARKER=".agent-scope"' in (
                root / rel).read_text(encoding='utf-8'), rel
        for rel in ('tools/hooks/cc-stop-gate.sh', 'tools/hooks/pre-push',
                    'tools/hooks/prepare-commit-msg',
                    'tools/hooks/cc-write-confine.sh'):
            assert 'DEVKIT_AGENT_SCOPE' in (
                root / rel).read_text(encoding='utf-8'), rel


@pytest.mark.skipif(shutil.which('bash') is None, reason='needs bash')
def test_the_installed_hooks_run_and_block_what_they_exist_to_block():
    """Installed into an empty repo with no library of any kind, fed the real
    Claude Code PreToolUse payload shape. Exit 2 is a BLOCK; exit 0 is allow.

    Each guard is exercised in both directions, because a hook that blocks
    everything and a hook that is disarmed are equally broken and only the
    pair of assertions tells them apart.
    """
    payload = ('{{"tool_name": "Bash", "tool_input": {{"command": {cmd}}}, '
               '"cwd": "{cwd}"}}')

    def fire(hook: str, command: str, root: Path) -> int:
        import json
        event = payload.format(cmd=json.dumps(command), cwd=root)
        return subprocess.run(['bash', str(root / hook)], input=event,
                              text=True, capture_output=True).returncode

    with repo() as root:
        assert run('install-hooks')[0] == 0
        sandbox = 'tools/hooks/cc-godot-sandbox.sh'
        assert fire(sandbox, 'godot --headless --path .', root) == 2
        assert fire(sandbox, 'make unit SYS=combat', root) == 0
        pathspec = 'tools/hooks/cc-commit-pathspec.sh'
        assert fire(pathspec, 'git commit -m "fix: a thing"', root) == 2
        assert fire(pathspec, 'git commit -m "fix: a thing" -- one.py',
                    root) == 0


@pytest.mark.skipif(shutil.which('bash') is None, reason='needs bash')
def test_setup_hooks_arms_every_cc_hook_by_glob():
    """trail chmods `cc-*.sh` by glob, nullbound named two files; the glob is
    strictly better — it is tolerant of absence AND does not have to be edited
    when a hook is added. core.hooksPath skips a non-executable hook in
    silence, so a hook this misses is a guard nobody knows is off."""
    with repo() as root:
        assert run('install-hooks')[0] == 0
        for rel in HOOKS[:2]:
            (root / rel).chmod(0o644)
        (root / 'tools' / 'hooks' / 'cc-invented-later.sh').write_text(
            '#!/usr/bin/env bash\nexit 0\n', encoding='utf-8')
        done = subprocess.run(['bash', 'tools/setup-hooks.sh'], cwd=root,
                              capture_output=True, text=True)
        assert done.returncode == 0, done.stderr
        for rel in (*HOOKS[:2], 'tools/hooks/cc-invented-later.sh'):
            assert os.access(root / rel, os.X_OK), rel
        # The whole corpus is armed, not just the cc-* glob: the classic git
        # hooks (skipped by core.hooksPath in silence when unexecutable) and
        # the by-path tools.
        for rel in ('tools/hooks/pre-push', 'tools/hooks/prepare-commit-msg',
                    'tools/dev/agent-worktree.sh',
                    'tools/dev/checks/doctor.sh'):
            assert os.access(root / rel, os.X_OK), rel
        hooks_path = subprocess.run(
            ['git', 'config', 'core.hooksPath'], cwd=root,
            capture_output=True, text=True).stdout.strip()
        assert hooks_path == 'tools/hooks'


# --- self-hosting -------------------------------------------------------------
@pytest.mark.parametrize('command', ('install-agents', 'install-ci'))
def test_this_repo_carries_what_the_verb_produces(command):
    """The shape ships here first, and stays byte-current.

    A copy edited in place is the fork-by-copy these verbs exist to prevent,
    and it would be invisible — the file still looks like the one that was
    installed. Edit the source under installables/ and re-install.

    `install-hooks` is deliberately absent: this package holds no Godot tree
    and no shared-agent worktree, so installing a Godot-boot guard here would
    be a file with nothing to guard. It is covered instead by installing into
    a temp repo and RUNNING it, which is the stronger test anyway.
    """
    repo_root.cache_clear()
    load_config.cache_clear()
    previous = Path.cwd()
    os.chdir(REPO_ROOT)
    try:
        code, out = run(command)
        assert code == 0, out
        assert out.count('already current') == len(install.PLANS[command]), (
            f'{command} is not byte-current in this repo:\n{out}')
    finally:
        os.chdir(previous)
        repo_root.cache_clear()
        load_config.cache_clear()


def test_every_installable_on_disk_is_reachable_through_a_verb():
    """A payload no verb names is a file that ships in the wheel, drifts, and
    is discovered by nobody. Asked of the directory, not of a second list."""
    from godot_devkit.core import walk
    from godot_devkit.core.walk import Kind
    found = walk.children(REPO_ROOT / 'src/godot_devkit/repo/installables',
                          Kind.FILE)
    on_disk = {p.name for p in found.kept}
    named = {name for entries in install.PLANS.values()
             for name, _ in entries}
    assert on_disk == named, (
        f'unreachable: {sorted(on_disk - named)}; '
        f'missing: {sorted(named - on_disk)}')
