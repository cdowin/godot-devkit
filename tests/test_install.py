"""test_install.py — the install-* verbs, and the property that makes CI safe.

The workflow's whole value is that it is IDENTICAL everywhere — what it runs is
the project's `verify` role, so there is nothing in the file to drift. That is
an assertion, not a promise: `test_workflow_is_identical_across_repos` diffs two
renders and allows exactly one line to differ.
"""
from __future__ import annotations

import contextlib
import io
import os
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from support import REPO_ROOT  # noqa: E402

sys.path.insert(0, str(REPO_ROOT / 'src'))
from godot_devkit import __version__  # noqa: E402
from godot_devkit.core.project import load_config, repo_root  # noqa: E402
from godot_devkit.repo import install  # noqa: E402

SELF_PYPROJECT = '[project]\nname = "godot-devkit"\nversion = "0.0.0"\n'
CONSUMER_PYPROJECT = '[project]\nname = "some-game"\n'


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
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        code = install.main(command, list(argv))
    return code, buffer.getvalue()


WORKFLOW = '.github/workflows/verify.yml'


def test_install_ci_writes_the_workflow_and_is_idempotent():
    with repo() as root:
        code, out = run('install-ci')
        assert code == 0, out
        body = (root / WORKFLOW).read_text(encoding='utf-8')
        assert 'godot-devkit task verify' in body
        code, out = run('install-ci')
        assert code == 0
        assert 'already current' in out
        assert (root / WORKFLOW).read_text(encoding='utf-8') == body


def test_a_consumer_gets_a_version_pin_and_the_toolkit_itself_gets_the_tree():
    """The one substituted value, and why it differs in exactly one repo.

    A consumer's CI must pin the devkit it was set up with. This package's own
    CI must NOT: a self-hosted gate running the last release has never seen the
    change in front of it.
    """
    with repo({'pyproject.toml': CONSUMER_PYPROJECT}) as root:
        run('install-ci')
        body = (root / WORKFLOW).read_text(encoding='utf-8')
    assert f'DEVKIT: git+https://github.com/cdowin/godot-devkit@v{__version__}' in body

    with repo({'pyproject.toml': SELF_PYPROJECT}) as root:
        run('install-ci')
        assert 'DEVKIT: .' in (root / WORKFLOW).read_text(encoding='utf-8')


def test_workflow_is_identical_across_repos_but_for_the_source_line():
    with repo({'pyproject.toml': CONSUMER_PYPROJECT}) as root:
        run('install-ci')
        consumer = (root / WORKFLOW).read_text(encoding='utf-8').splitlines()
    with repo({'pyproject.toml': SELF_PYPROJECT}) as root:
        run('install-ci')
        mine = (root / WORKFLOW).read_text(encoding='utf-8').splitlines()
    differing = [a for a, b in zip(consumer, mine) if a != b]
    assert len(consumer) == len(mine)
    assert len(differing) == 1, differing
    assert differing[0].strip().startswith('DEVKIT:')


def test_it_refuses_to_clobber_a_file_it_did_not_generate():
    mine = 'name: verify\njobs: {}\n'
    with repo({WORKFLOW: mine}) as root:
        code, _ = run('install-ci')
        assert code == 1
        assert (root / WORKFLOW).read_text(encoding='utf-8') == mine
        code, _ = run('install-ci', '--force')
        assert code == 0
        assert (root / WORKFLOW).read_text(encoding='utf-8') != mine


def test_an_unknown_flag_is_a_usage_error():
    with repo():
        code, _ = run('install-ci', '--yolo')
        assert code == 2


AGENTS = ('.claude/agents/verification-reviewer.md',
          '.claude/agents/verification-builder.md')


def test_install_agents_writes_both_contracts_and_is_idempotent():
    with repo() as root:
        code, out = run('install-agents')
        assert code == 0, out
        bodies = [(root / rel).read_text(encoding='utf-8') for rel in AGENTS]
        code, out = run('install-agents')
        assert code == 0 and out.count('already current') == 2
        assert [(root / rel).read_text(encoding='utf-8')
                for rel in AGENTS] == bodies


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
    """The two lines the whole contract exists to deliver, pinned.

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
        for gate in ('doc', 'agents'):
            proc = subprocess.run(
                [sys.executable, '-m', 'godot_devkit.cli', 'check', gate],
                cwd=root, capture_output=True, text=True,
                env={**os.environ, 'PYTHONPATH': str(REPO_ROOT / 'src')})
            assert proc.returncode == 0, (
                f'the installed contract fails `check {gate}` on install day:\n'
                f'{proc.stdout}{proc.stderr}')


def test_install_agents_refuses_to_clobber_a_hand_written_definition():
    mine = '---\nname: verification-reviewer\n---\nmy own contract\n'
    with repo({AGENTS[0]: mine}) as root:
        code, _ = run('install-agents')
        assert code == 1
        assert (root / AGENTS[0]).read_text(encoding='utf-8') == mine


def test_this_repo_carries_every_installed_file_unmodified():
    """Self-hosting: the shape ships here first, and stays byte-current.

    A workflow or a contract edited in place is the fork-by-copy these verbs
    exist to prevent, and it would be invisible — the file still looks like the
    one that was installed. Edit the source under installables/ and re-install.
    """
    repo_root.cache_clear()
    load_config.cache_clear()
    previous = Path.cwd()
    os.chdir(REPO_ROOT)
    try:
        for command in install.PLANS:
            code, out = run(command)
            assert code == 0, out
            assert out.count('already current') == len(install.PLANS[command]), \
                f'{command} is not byte-current in this repo:\n{out}'
    finally:
        os.chdir(previous)
        repo_root.cache_clear()
        load_config.cache_clear()
