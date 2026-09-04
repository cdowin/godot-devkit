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
import json
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
# The set both consumers run on a push. verify.yml is the one this repo itself
# carries; the other three read `config/version` out of a project.godot, which
# a stdlib Python package does not have — see the self-hosting test below.
WORKFLOWS = (WORKFLOW,
             '.github/workflows/uid-guard.yml',
             '.github/workflows/semver-gate.yml',
             '.github/workflows/auto-tag.yml')
AGENTS = ('.claude/agents/verification-reviewer.md',
          '.claude/agents/verification-builder.md',
          '.claude/agents/architect.md',
          '.claude/agents/po.md',
          '.claude/agents/developer.md',
          '.claude/agents/reviewer.md',
          '.claude/agents/milestone-reviewer.md',
          '.claude/agents/simplifier.md',
          '.claude/agents/test-writer.md',
          '.claude/agents/tech-writer.md',
          '.claude/agents/changelog-writer.md',
          '.claude/agents/doc-hygiene.md',
          '.claude/agents/pm-operator.md')
# The verification pair carries the review/build CONTRACT and predates the
# roster; the rest are the base ROSTER — generalized from the two consumers,
# each carrying model/effort frontmatter and an editable project-config
# section. The split matters below: the contract tests pin the pair's
# sentences, the roster tests pin the parameterization story.
ROSTER = AGENTS[2:]
HOOKS = ('tools/hooks/cc-commit-pathspec.sh',
         'tools/hooks/cc-godot-sandbox.sh',
         'tools/hooks/cc-stop-gate.sh',
         'tools/hooks/cc-write-confine.sh',
         # The two ledger couriers (0.22.0). They guard nothing; they carry a
         # stop event's transcript path to `pm ledger record` and exit 0.
         'tools/hooks/cc-ledger-subagent.sh',
         'tools/hooks/cc-ledger-session.sh',
         'tools/hooks/pre-push',
         'tools/hooks/prepare-commit-msg',
         'tools/dev/agent-worktree.sh',
         'tools/dev/checks/doctor.sh',
         'tools/setup-hooks.sh')
RUNNERS = ('tools/dev/gdk_runners.sh',
           'tools/dev/runners/import_cache.sh',
           'tools/dev/runners/parse.sh',
           'tools/dev/runners/compile_sweep.gd',
           'tools/dev/runners/compile_sweep.gd.uid',
           'tools/dev/runners/lint.sh',
           'tools/dev/runners/warnings.sh',
           'tools/dev/runners/unit.sh',
           'tools/dev/runners/scenario.sh',
           'tools/dev/runners/integration.sh',
           'tools/dev/runners/capture.sh',
           'tools/dev/runners/hermetic_run_scan.sh',
           'Makefile.devkit')
DESTINATIONS = {'install-ci': WORKFLOWS,
                'install-agents': AGENTS,
                'install-hooks': HOOKS,
                'install-runners': RUNNERS}
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


# --- the report and the disk are one thing ------------------------------------
@pytest.mark.parametrize('command', ('install-agents', 'install-hooks'))
def test_a_collision_on_a_LATER_entry_withholds_that_file_and_nothing_else(
        command):
    """The defect this replaced: `install-agents` wrote the reviewer, THEN
    refused on the builder, and reported `nothing was written` about a repo
    that now held one of the two files. The claim was the bug — not the write.

    A collision is the operator's own file, deliberately theirs, and it
    withholds ITS destination; the entries with nothing in their way land, and
    the run reports exactly what it did. The whole-plan decision is proven
    where it belongs, on a DEFECT (below): that one still writes nothing."""
    rels = DESTINATIONS[command]
    mine = 'my own version, deliberately\n'
    with repo({rels[-1]: mine}) as root:
        code, out = refuse(command)
        assert code == 1, out
        for earlier in rels[:-1]:
            assert (root / earlier).is_file(), (
                f'{earlier} was withheld by a collision on {rels[-1]}')
            assert f'wrote {earlier}' in out, out
        assert (root / rels[-1]).read_text(encoding='utf-8') == mine
        assert rels[-1] in out, out
        assert f'wrote {rels[-1]}' not in out, out
        assert 'nothing was written' not in out, out


def test_every_collision_is_named_in_one_refusal():
    """Two collisions, one run: an operator must not have to re-install to
    discover the next file they need to move aside — and the sentence about
    the disk is built from the disk, not asserted."""
    with repo({AGENTS[0]: 'mine\n', AGENTS[1]: 'mine too\n'}) as root:
        code, message = refuse('install-agents')
        for rel in AGENTS[:2]:
            assert rel in message, message
            assert (root / rel).read_text(encoding='utf-8').startswith('mine')
        for rel in AGENTS[2:]:
            assert (root / rel).is_file(), rel
    assert code == 1
    assert 'nothing was written' not in message, message
    assert f'{len(AGENTS) - 2} file(s) with nothing in the way' in message


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
        # Withheld, not overwritten — and the entries with nothing in their
        # way still land, which is what makes the exit code the only signal a
        # replacement was held back.
        assert (root / AGENTS[1]).read_bytes() == b'\xff\xfe\x00not utf-8'
        assert (root / AGENTS[0]).is_file(), out
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


def test_every_roster_agent_carries_model_and_an_editable_config_section():
    """The roster's two load-bearing deliveries, pinned per file.

    `model:` is the frontmatter field doing proven work (the tiering table
    exists because of it), so every roster agent must declare one — and the
    `effort:` key ships with its unverified-caveat comment attached, because
    a misspelled or unsupported frontmatter key is silently ignored and a
    caveat that lives only in a doc never reaches the installed file.

    Project-specific content is parameterized the way the hook corpus does
    it: a clearly-marked project-config section the consumer edits after
    install. The marker is the contract — a rewrite that drops it drops the
    whole parameterization story. The verification pair is exempt: it
    predates the roster and deliberately carries neither.
    """
    by_rel = {rel: name for name, rel in install.PLANS['install-agents']}
    with repo() as root:
        assert run('install-agents')[0] == 0
        for rel in ROSTER:
            body = (root / rel).read_text(encoding='utf-8')
            head = body.split('---', 2)[1]
            assert '\nmodel: ' in head, f'{rel} declares no model:'
            assert '\neffort: ' in head, f'{rel} declares no effort:'
            assert 'UNVERIFIED' in head, (
                f'{rel} dropped the effort-is-unverified caveat')
            assert 'GENERATED by godot-devkit' in body, rel
            assert '## Project config (yours to edit after install)' in body, (
                f'{rel} carries no editable project-config section')
        for rel in AGENTS[:2]:
            head = (root / rel).read_text(encoding='utf-8').split('---', 2)[1]
            assert 'model:' not in head, f'{rel} grew a model: it never had'


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
                 'tools/hooks/cc-ledger-subagent.sh',
                 'tools/hooks/cc-ledger-session.sh',
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
def test_this_repo_carries_what_install_ci_produces():
    """The shape ships here first, and stays byte-current.

    A copy edited in place is the fork-by-copy these verbs exist to prevent,
    and it would be invisible — the file still looks like the one that was
    installed. Edit the source under installables/ and re-install.

    PARTIAL, and decided the same way `install-agents` is: verify.yml runs
    `make milestone`, which this repo has, so it MUST be present and current.
    The other three read `config/version` out of a project.godot — this package
    has neither, versions in pyproject.toml, and bumps at CLOSE rather than at
    merge. Installing them here would be three workflows guarding a flow this
    repo does not run — the reasoning that kept `install-hooks` un-self-hosted
    until 0.23.0 gave its corpus a job here (the ledger couriers; the hook
    headers are then this repo's `project config`, edited on purpose). What is
    carried must be current; what is absent is legitimately absent.
    """
    repo_root.cache_clear()
    load_config.cache_clear()
    previous = Path.cwd()
    os.chdir(REPO_ROOT)
    try:
        present = [rel for _, rel in install.PLANS['install-ci']
                   if (REPO_ROOT / rel).is_file()]
        assert WORKFLOW in present, (
            f'{WORKFLOW} is not present in this repo — the one workflow it '
            f'self-hosts, and the floor this test would otherwise pass over')
        code, out = run('install-ci', '--diff')
        assert code == 0, out
        stale = [rel for rel in present if f'{rel} already current' not in out]
        assert not stale, (
            f'not byte-current in this repo: {stale}\n{out}')
    finally:
        os.chdir(previous)
        repo_root.cache_clear()
        load_config.cache_clear()


def test_this_repo_carries_the_roles_it_runs_byte_current():
    """PARTIAL-roster self-hosting, decided with the roster.

    This package runs its own SDLC with the verification pair; the
    game-shaped roles (developer with an engine-expertise brief, po writing
    against scene tooling, test-writer's two-tier boot split) have nothing to
    act on in a stdlib Python repo — the same reasoning that keeps
    `install-hooks` un-self-hosted. So the contract is conditional, not
    total: the verification pair MUST be present, and any plan destination
    this repo carries MUST be byte-current with its installable. A local
    `.claude/agents/` file that shadows a roster name with edited content is
    the invisible fork-by-copy; a role this repo does not run is legitimately
    absent.
    """
    present: list[str] = []
    for name, rel in install.PLANS['install-agents']:
        target = REPO_ROOT / rel
        if target.is_file():
            present.append(rel)
            assert (target.read_text(encoding='utf-8')
                    == install.body_of(name)), (
                f'{rel} differs from installables/{name} — edit the source '
                f'under installables/ and re-install with --force')
    # The floor: a repo that stops carrying the pair has stopped self-hosting
    # the verbs it ships, and this test would otherwise pass vacuously.
    for rel in AGENTS[:2]:
        assert rel in present, f'{rel} is not present in this repo'


def test_every_installable_on_disk_is_reachable_through_a_verb():
    """A payload no verb names is a file that ships in the wheel, drifts, and
    is discovered by nobody. Asked of the directory, not of a second list.

    `init` names three of them — the project-owned seeds — and it is a verb
    like the rest, so its table joins the union rather than being carved out.
    """
    from godot_devkit.core import walk
    from godot_devkit.core.walk import Kind
    from godot_devkit.repo import init
    found = walk.children(REPO_ROOT / 'src/godot_devkit/repo/installables',
                          Kind.FILE)
    on_disk = {p.name for p in found.kept}
    named = {name for entries in install.PLANS.values()
             for name, _ in entries} | {name for name, _ in init.SEEDS}
    assert on_disk == named, (
        f'unreachable: {sorted(on_disk - named)}; '
        f'missing: {sorted(named - on_disk)}')


# --- the exec bit: a script is written RUNNABLE -------------------------------
# 0.20.0 MAJOR-1, and the 0.19.0 NIT it subsumes. The runners used to be
# written -rw-r--r-- and the next step told the operator to `chmod +x` them.
# `integration.sh`'s fan-out did not read that paragraph: it exec'd
# `scenario.sh` directly, so every scenario on every `init`'d project exited
# 126 and the FAILURES block printed the scenario name with nothing under it.
# The mode is now part of the write, in `core.apply`, which owns every
# mutation this package makes.
def _mode(target: Path) -> int:
    return target.stat().st_mode & 0o777


@pytest.mark.parametrize('command', VERBS)
def test_every_shell_installable_is_written_executable(command):
    """Every `.sh` this verb writes is runnable, and nothing else's mode moved.

    Asked of the DESTINATION suffix, per verb, so a `.sh` added to any plan
    tomorrow is covered the day it lands.
    """
    with repo() as root:
        code, out = run(command)
        assert code == 0, out
        scripts = [rel for rel in DESTINATIONS[command] if rel.endswith('.sh')]
        others = [rel for rel in DESTINATIONS[command] if not rel.endswith('.sh')]
        not_runnable = [rel for rel in scripts
                        if not os.access(root / rel, os.X_OK)]
        runnable = [rel for rel in others if os.access(root / rel, os.X_OK)]
    assert not not_runnable, (
        f'{command} wrote {not_runnable} without an execute bit — a caller '
        f'exec\'ing one gets 126, and `Permission denied` is a diagnosis no '
        f'gate summary matches')
    assert not runnable, (
        f'{command} made {runnable} executable; only `.sh` is a script here')


def test_the_exec_bit_does_not_widen_who_may_read_the_file():
    """`chmod +x`, not `chmod 755`. The execute bit joins the classes that can
    already read the file — widening a 0600 destination to world-readable is a
    permission decision no install verb was asked to make."""
    with repo() as root:
        target = root / 'tools/dev/runners/parse.sh'
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text('stale\n', encoding='utf-8')
        target.chmod(0o600)
        code, out = run('install-runners', '--force')
        assert code == 0, out
        assert _mode(target) == 0o700, oct(_mode(target))


def test_a_byte_current_script_missing_the_bit_is_repaired_not_reported_current():
    """The consumer this fix exists for already ran the old verb: their files
    are byte-identical and 0644. A re-run that reported them `already current`
    would leave every one of them broken forever."""
    with repo() as root:
        code, out = run('install-runners')
        assert code == 0, out
        target = root / 'tools/dev/runners/scenario.sh'
        target.chmod(0o644)

        code, out = run('install-runners')
        assert code == 0, out
        assert os.access(target, os.X_OK), 'the re-run left it unrunnable'
        assert 'wrote tools/dev/runners/scenario.sh' in out, out

        # …and it converges: the run after that has nothing left to do.
        code, out = run('install-runners')
        assert code == 0, out
        assert 'already current' in out and 'wrote ' not in out, out


def test_install_runners_next_step_no_longer_asks_for_a_chmod():
    """The 0.19.0 NIT was closed by DOCUMENTING the missing bit. It is closed
    now by writing it, and a paragraph still asking for the chmod would send an
    operator to repair something the verb just did."""
    with repo():
        code, out = run('install-runners')
    assert code == 0, out
    assert 'chmod +x' not in out, out
    assert 'EXECUTABLE' in out, out


# --- install-hooks prints the settings.json entries that FIRE the hooks -------
# A git hook runs because `tools/setup-hooks.sh` points core.hooksPath at the
# directory. A Claude Code hook runs because `.claude/settings.json` names it,
# and nothing else does — so an install that wrote eleven files and said
# nothing about registration left six guards on disk and none of them armed.
# The block is PRINTED rather than written: settings.json is hand-maintained,
# carries permissions/env/MCP entries this package knows nothing about, and
# these verbs write a whole file or refuse.
CC_HOOKS = tuple(rel for rel in HOOKS if rel.startswith('tools/hooks/cc-'))
ASYNC_HOOKS = ('tools/hooks/cc-ledger-subagent.sh',
               'tools/hooks/cc-ledger-session.sh')


def test_install_hooks_prints_the_settings_entries_that_fire_every_cc_hook():
    """Every installed Claude Code hook is named in the snippet, and the
    snippet parses as JSON — a block an operator has to repair before pasting
    is a block they will hand-write instead, which is the fork this verb
    exists to prevent."""
    with repo():
        code, out = run('install-hooks')
        assert code == 0, out
        assert '.claude/settings.json' in out, out
        opened = out.index('{\n  "hooks"')
        block = json.loads(out[opened:out.rindex('}') + 1])
        commands = [entry['command']
                    for event in block['hooks'].values()
                    for group in event for entry in group['hooks']]
        for rel in CC_HOOKS:
            assert any(rel in command for command in commands), (
                f'{rel} is installed but no settings entry fires it\n{out}')


def test_the_two_ledger_couriers_are_registered_async_and_unmatched():
    """`async` is the whole reason a Stop hook may parse a transcript at all
    (D4): the orchestrator must not wait for it. And neither courier carries a
    matcher — every dispatch costs something, so a roster of agent types here
    would silently stop measuring the day a repo adds one."""
    with repo():
        code, out = run('install-hooks')
        assert code == 0, out
        block = json.loads(out[out.index('{\n  "hooks"'):out.rindex('}') + 1])
        wired = {}
        for event, groups in block['hooks'].items():
            for group in groups:
                for entry in group['hooks']:
                    for rel in ASYNC_HOOKS:
                        if rel in entry['command']:
                            wired[rel] = (event, group.get('matcher'), entry)
        assert set(wired) == set(ASYNC_HOOKS), wired
        subagent_event, subagent_matcher, subagent = wired[ASYNC_HOOKS[0]]
        session_event, session_matcher, session = wired[ASYNC_HOOKS[1]]
        assert subagent_event == 'SubagentStop', wired
        assert session_event == 'Stop', wired
        assert subagent_matcher is None and session_matcher is None, wired
        assert subagent['async'] is True and session['async'] is True, wired


@pytest.mark.skipif(shutil.which('bash') is None, reason='needs bash')
@pytest.mark.parametrize('rel', ASYNC_HOOKS)
def test_the_installed_ledger_couriers_are_executable_and_replay_their_corpus(
        rel):
    """Installed, armed by the write itself, and PROVEN by their own
    `--self-test` — the same contract cc-godot-sandbox.sh carries."""
    with repo() as root:
        assert run('install-hooks')[0] == 0
        target = root / rel
        assert target.stat().st_mode & 0o111, f'{rel} is not executable'
        done = subprocess.run(['bash', str(target), '--self-test'],
                              capture_output=True, text=True, cwd=root)
        assert done.returncode == 0, done.stdout + done.stderr
        assert 'SELF-TEST OK' in done.stdout, done.stdout


# --- a collision withholds ITS file, and a header-only one is named as one ----
# The v0.23.0 adoption defect, from both consumers: four hooks differed ONLY
# inside the `project config` header the file invites them to edit, so the two
# hooks that release ADDED — pure additions, nothing in their way — could not be
# installed at all. The way through was `--force` and then re-editing four files
# by hand, or copying two files out of a uv cache. The whole-plan DECISION
# stands; what a collision withholds is that file.
SHELL_OPEN = ("# --- project config (yours to edit after install — the file "
              "is your repo's) --")
SHELL_CLOSE = '# ' + '-' * 77
MD_OPEN = '## Project config (yours to edit after install)'


def header_edited(text: str, line: str = 'MY_PROJECT_SAYS=1') -> str:
    """`text` with `line` inserted INSIDE its project-config block — the edit
    the block exists to invite.

    Finds the OPENING marker on its own and inserts straight after it: a
    fixture built with the production span finder would prove nothing about
    the production span finder.
    """
    lines = text.splitlines(keepends=True)
    for index, one in enumerate(lines):
        if MD_OPEN in one:
            return ''.join(lines[:index + 1] + [f'\n{line}\n'] +
                           lines[index + 1:])
        if 'project config (yours to edit after install' in one:
            return ''.join(lines[:index + 1] + [f'{line}\n'] +
                           lines[index + 1:])
    raise AssertionError('no project-config block to edit')


HEADER_EDITED_HOOKS = ('tools/hooks/cc-godot-sandbox.sh',
                       'tools/hooks/cc-stop-gate.sh',
                       'tools/hooks/pre-push',
                       'tools/hooks/prepare-commit-msg')


def a_consumer_mid_adoption(root: Path) -> dict[str, str]:
    """The corpus installed, four headers edited, the two couriers not yet
    there — nullbound and trail on the day they adopted v0.23.0. Returns the
    edited text of each file, to be compared byte for byte afterwards."""
    assert run('install-hooks')[0] == 0
    mine = {}
    for rel in HEADER_EDITED_HOOKS:
        target = root / rel
        mine[rel] = header_edited(target.read_text(encoding='utf-8'))
        target.write_text(mine[rel], encoding='utf-8')
    for rel in ASYNC_HOOKS:
        (root / rel).unlink()
    return mine


def test_a_new_hook_lands_on_a_consumer_whose_headers_are_edited():
    """The bug, whole: the couriers land, the four headers survive byte for
    byte, and the run exits 1 naming the files it withheld."""
    with repo() as root:
        mine = a_consumer_mid_adoption(root)
        code, out = refuse('install-hooks')
        assert code == 1, out
        for rel in ASYNC_HOOKS:
            assert (root / rel).is_file(), f'{rel} did not land\n{out}'
            assert (root / rel).read_text(encoding='utf-8') == install.body_of(
                Path(rel).name), rel
            assert f'wrote {rel}' in out, out
        for rel, text in mine.items():
            assert (root / rel).read_text(encoding='utf-8') == text, (
                f'{rel} was overwritten by a run that did not say so')
            assert rel in out, f'{rel} was withheld and not named\n{out}'


def test_an_addition_beside_a_withheld_replacement_still_exits_1():
    """The exit code carries the withholding, and only the exit code can: a
    caller that reads it alone must never be told the roster is on disk when
    one of it is the operator's own file.

    Both halves in one assertion path on purpose — `code == 1` alone is what
    the defect already did, by writing nothing at all. What has to be true
    TOGETHER is that the additions landed AND the run still exits 1. Exit 0
    here is this bug in a new shape."""
    with repo() as root:
        a_consumer_mid_adoption(root)
        code, out = refuse('install-hooks')
        assert [rel for rel in ASYNC_HOOKS if (root / rel).is_file()] == list(
            ASYNC_HOOKS), out
        assert code == 1, f'additions landed and the run exited {code}\n{out}'
        # And once the collision is gone, the same command is a clean 0 — the
        # non-zero is about the withholding, not about the run having spoken.
        for rel in HEADER_EDITED_HOOKS:
            (root / rel).write_text(
                install.body_of(Path(rel).name), encoding='utf-8')
        assert refuse('install-hooks')[0] == 0


def test_a_partial_run_never_claims_nothing_was_written():
    """The claim and the disk are one thing. `nothing was written` over a repo
    that gained two files is the defect `core.apply` exists to end."""
    with repo() as root:
        a_consumer_mid_adoption(root)
        code, out = refuse('install-hooks')
        assert code == 1, out
        assert 'nothing was written' not in out, out
        wrote = {line.split('wrote ', 1)[1].strip()
                 for line in out.splitlines() if '] wrote ' in line}
        assert wrote == set(ASYNC_HOOKS), out
        for rel in HOOKS:
            assert (root / rel).is_file(), rel


def test_a_header_only_collision_is_reported_as_one():
    """The report an operator can act on: the rest of the file is byte-current,
    so the repair is to do nothing — not --force and four re-edits."""
    with repo() as root:
        a_consumer_mid_adoption(root)
        code, out = refuse('install-hooks')
        assert code == 1, out
        assert out.count(install.HEADER_ONLY_NOTE) == len(
            HEADER_EDITED_HOOKS), out
        assert 'byte-current' in out, out
        assert '--force would replace the header too' in out, out


def test_a_body_difference_is_not_reported_as_a_header_only_one():
    """The predicate is only allowed to be wrong in one direction. An edit
    OUTSIDE the block is a plain collision, and saying `byte-current` about it
    would send an operator past a real change."""
    rel = 'tools/hooks/pre-push'
    with repo() as root:
        assert run('install-hooks')[0] == 0
        target = root / rel
        target.write_text(
            target.read_text(encoding='utf-8') + '\n# my own trailer\n',
            encoding='utf-8')
        code, out = refuse('install-hooks')
        assert code == 1, out
        assert rel in out, out
        assert install.HEADER_ONLY_NOTE not in out, out
        assert 'byte-current' not in out, out


def test_an_edit_in_the_header_AND_the_body_is_a_plain_collision():
    rel = 'tools/hooks/cc-stop-gate.sh'
    with repo() as root:
        assert run('install-hooks')[0] == 0
        target = root / rel
        target.write_text(
            header_edited(target.read_text(encoding='utf-8')) + '# also this\n',
            encoding='utf-8')
        code, out = refuse('install-hooks')
        assert code == 1, out
        assert rel in out and install.HEADER_ONLY_NOTE not in out, out


def test_a_consumer_who_edited_the_marker_itself_gets_a_plain_collision():
    """The markers are the installable's, not the block's contents. A file
    whose shape this can no longer read is reported as what it is."""
    rel = 'tools/hooks/pre-push'
    with repo() as root:
        assert run('install-hooks')[0] == 0
        target = root / rel
        target.write_text(
            target.read_text(encoding='utf-8').replace(
                'project config (yours to edit after install', 'MY CONFIG ('),
            encoding='utf-8')
        code, out = refuse('install-hooks')
        assert code == 1, out
        assert rel in out and install.HEADER_ONLY_NOTE not in out, out


def test_diff_names_a_header_only_difference_before_the_hunks():
    """--diff is where the operator looks first, and where this bug started:
    two additions, five `already current`, and four diffs that said nothing
    about being only the header."""
    with repo() as root:
        mine = a_consumer_mid_adoption(root)
        code, out = run('install-hooks', '--diff')
        assert code == 0, out
        for rel in mine:
            assert f'{rel} differs ONLY inside its project-config header' in out
            assert f'--- a/{rel}' in out, out
        for rel in ASYNC_HOOKS:
            assert f'{rel} does not exist' in out, out
        # Reading is not writing: the couriers are still absent afterwards.
        for rel in ASYNC_HOOKS:
            assert not (root / rel).exists(), rel


def test_force_replaces_a_header_only_collision_whole_header_included():
    """The decision, pinned. The installer does NOT merge the block: a
    preserved consumer header carried onto a newer body is an older contract
    under a newer one, and this corpus reads its header under `set -u` behind
    a fail-open trap."""
    with repo() as root:
        mine = a_consumer_mid_adoption(root)
        code, out = run('install-hooks', '--force')
        assert code == 0, out
        for rel in mine:
            assert (root / rel).read_text(encoding='utf-8') == (
                install.body_of(Path(rel).name)), rel
            assert 'MY_PROJECT_SAYS' not in (
                root / rel).read_text(encoding='utf-8'), rel


def test_a_defect_refuses_the_whole_command_and_writes_no_addition():
    """A collision is the operator's decision about that file; a DEFECT is a
    destination the command cannot write at all, and its repair is the same for
    every entry. Nothing is written, so `nothing was written` is still true —
    and this is the case that keeps proving the plan is decided before the
    first byte."""
    with repo() as root:
        (root / 'tools/hooks').mkdir(parents=True)
        (root / 'tools/hooks/pre-push').mkdir()
        code, out = refuse('install-hooks')
        assert code == 1, out
        assert 'is a directory' in out and 'nothing was written' in out, out
        for rel in HOOKS:
            if rel != 'tools/hooks/pre-push':
                assert not (root / rel).exists(), (
                    f'{rel} was written past a defect')


def test_a_run_with_both_a_collision_and_a_defect_names_both():
    with repo() as root:
        assert run('install-hooks')[0] == 0
        target = root / 'tools/hooks/cc-stop-gate.sh'
        target.write_text(header_edited(target.read_text(encoding='utf-8')),
                          encoding='utf-8')
        doomed = root / 'tools/setup-hooks.sh'
        doomed.unlink()
        doomed.mkdir()
        code, out = refuse('install-hooks')
        assert code == 1, out
        assert 'tools/hooks/cc-stop-gate.sh' in out, out
        assert 'tools/setup-hooks.sh is a directory' in out, out
        assert 'nothing was written' in out, out


def test_collisions_with_no_additions_still_say_nothing_was_written():
    """The all-or-nothing sentence is not retired — it is CHECKED. A run whose
    only entries are current or colliding wrote nothing, and says so."""
    rel = 'tools/hooks/pre-push'
    with repo() as root:
        assert run('install-hooks')[0] == 0
        target = root / rel
        target.write_text(header_edited(target.read_text(encoding='utf-8')),
                          encoding='utf-8')
        code, out = refuse('install-hooks')
        assert code == 1, out
        assert 'nothing was written' in out, out
        assert '] wrote ' not in out, out


def test_every_config_headed_installable_reads_as_header_only_when_edited():
    """The grammar covers every block this package actually ships — shell and
    markdown — rather than the two files a test happened to pick."""
    checked = 0
    for command in ('install-hooks', 'install-agents', 'install-runners'):
        for name, rel in install.PLANS[command]:
            body = install.body_of(name)
            if install.config_block_span(body) is None:
                continue
            checked += 1
            assert install.header_only_difference(header_edited(body), body), (
                f'{rel} carries a block this cannot locate')
            assert not install.header_only_difference(body + 'trailing\n',
                                                      body), rel
    assert checked >= 25, f'only {checked} config-headed installables scanned'


# --- the predicate, against hostile pairs ------------------------------------
# `header_only_difference` is a claim that the REST of a file is byte-current,
# and an operator who believes it wrongly walks past a real change. Every case
# below is written to make it answer True when it must not.
STOCK = ('#!/usr/bin/env bash\n'
         '# what this hook is\n'
         'set -eu\n'
         '\n'
         f'{SHELL_OPEN}\n'
         '# the branch you protect\n'
         'BRANCH="main"\n'
         f'{SHELL_CLOSE}\n'
         'echo "$BRANCH"\n'
         'exit 0\n')
MD_STOCK = ('---\nname: x\n---\n'
            '\n'
            f'{MD_OPEN}\n'
            '\n```text\nproject: yours\n```\n'
            '\n## How you work\n'
            'the body\n')


def swap(text: str, old: str, new: str) -> str:
    assert old in text, f'{old!r} is not in the fixture'
    return text.replace(old, new)


HOSTILE = {
    'an edit inside the block':
        (swap(STOCK, 'BRANCH="main"', 'BRANCH="main staging"'), True),
    'a line added inside the block':
        (swap(STOCK, 'BRANCH="main"', 'BRANCH="main"\nEXTRA=1'), True),
    'the whole block emptied':
        (swap(STOCK, '# the branch you protect\nBRANCH="main"\n', ''), True),
    'a markdown block edited':
        (swap(MD_STOCK, 'project: yours', 'project: mine'), True),
    'an edit ABOVE the block':
        (swap(STOCK, '# what this hook is', '# what MY hook is'), False),
    'an edit BELOW the block':
        (swap(STOCK, 'echo "$BRANCH"', 'echo "$BRANCH" >&2'), False),
    'a line appended past the end':
        (STOCK + '# mine\n', False),
    'an edit in the header AND the body':
        (swap(swap(STOCK, 'BRANCH="main"', 'BRANCH="x"'), 'exit 0', 'exit 1'),
         False),
    'the opening marker rewritten':
        (swap(STOCK, 'project config (yours to edit after install', 'mine ('),
         False),
    'the closing marker deleted':
        (swap(STOCK, f'{SHELL_CLOSE}\n', ''), False),
    'a second rule line inside the block':
        (swap(STOCK, 'BRANCH="main"', f'{SHELL_CLOSE}\nBRANCH="main"'), False),
    'the block moved below the body':
        (swap(STOCK, f'{SHELL_OPEN}\n# the branch you protect\n'
                     f'BRANCH="main"\n{SHELL_CLOSE}\n', '')
         + f'{SHELL_OPEN}\n# the branch you protect\nBRANCH="main"\n'
           f'{SHELL_CLOSE}\n', False),
    'no block at all on the consumer side':
        ('#!/usr/bin/env bash\nmine, deliberately\n', False),
    'nothing but the block':
        (f'{SHELL_OPEN}\nBRANCH="main"\n{SHELL_CLOSE}\n', False),
    'an empty file':
        ('', False),
    'the trailing newline dropped':
        (STOCK.rstrip('\n'), False),
    'a markdown edit past the block':
        (swap(MD_STOCK, 'the body', 'MY body'), False),
    'the markdown heading rewritten':
        (swap(MD_STOCK, MD_OPEN, '## My config'), False),
}


@pytest.mark.parametrize('label', sorted(HOSTILE))
def test_header_only_difference_answers_the_hostile_pair(label):
    mine, expected = HOSTILE[label]
    stock = MD_STOCK if 'markdown' in label else STOCK
    assert install.header_only_difference(mine, stock) is expected, label


def test_the_predicate_needs_a_block_on_BOTH_sides():
    """A destination that carries a block and an installable that does not is
    not a header-only difference — there is no header on the side that would
    be written."""
    plain = 'no block here\n'
    assert install.header_only_difference(STOCK, plain) is False
    assert install.header_only_difference(plain, STOCK) is False
    assert install.header_only_difference(plain, plain) is False


def test_the_span_excludes_its_own_markers_and_stops_at_the_first_close():
    """Both ends are the installable's, not the consumer's: an edit that lands
    ON a marker is outside the span by construction."""
    lines = STOCK.splitlines()
    start, end = install.config_block_span(STOCK)
    assert lines[start - 1] == SHELL_OPEN, lines[start - 1]
    assert lines[end] == SHELL_CLOSE, lines[end]
    assert lines[start:end] == ['# the branch you protect', 'BRANCH="main"']
    # An unterminated block runs to the end of the file rather than to a
    # guessed boundary — and the pair test above proves that answers False.
    open_ended = swap(STOCK, f'{SHELL_CLOSE}\n', '')
    assert install.config_block_span(open_ended) == (
        5, len(open_ended.splitlines()))
    assert install.config_block_span('') is None
    assert install.config_block_span('nothing in here\n') is None
