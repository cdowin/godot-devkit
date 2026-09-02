"""test_ci_workflows.py — the workflow SET `install-ci` writes.

Four files, devkit-owned: verify.yml (the full gate), uid-guard.yml,
semver-gate.yml, auto-tag.yml. All three of the latter were forked in both
consumers and drifted — on a project name, and on which fix each fork got —
which is the evidence this verb exists on.

NO YAML PARSER IS AVAILABLE, and that is said out loud rather than worked
around: this package is stdlib-only forever (rule 1), and the stdlib has no
YAML reader. So the structural assertions below run on a MINIMAL indentation
reader written here — enough to answer "is this the shape a workflow has",
never enough to claim "GitHub will accept this". The claims it CAN make are
the ones that catch the real defects: a tab in the indentation, a job with no
steps, an unpinned action, a `${{` that never closes, a project name that came
along for the ride, and — the one only this repo can check — a `make` target
the include does not define.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from support import REPO_ROOT  # noqa: E402

sys.path.insert(0, str(REPO_ROOT / 'src'))
from godot_devkit.repo import install  # noqa: E402

INCLUDE = REPO_ROOT / 'src/godot_devkit/repo/installables/Makefile.devkit'
WORKFLOWS = tuple((name, rel) for name, rel in install.PLANS['install-ci'])
# The four the feature names. Spelled out so this file reads as the contract,
# and cross-checked against the plan so it cannot become a second roster.
EXPECTED = ('.github/workflows/verify.yml',
            '.github/workflows/uid-guard.yml',
            '.github/workflows/semver-gate.yml',
            '.github/workflows/auto-tag.yml')

KEY = re.compile(r'^(\s*)(?:- )?([A-Za-z_][A-Za-z0-9_.-]*):(?:\s+(.*))?$')
BLOCK_SCALAR = ('|', '>', '|-', '>-', '|+', '>+')
TOP_LEVEL_REQUIRED = {'name', 'on', 'jobs'}
TOP_LEVEL_ALLOWED = TOP_LEVEL_REQUIRED | {'permissions', 'env', 'concurrency',
                                          'defaults', 'run-name'}


def nodes(text: str) -> list[tuple[int, str, str]]:
    """(indent, key, inline value) for every mapping key OUTSIDE a block scalar.

    A `run: |` body is arbitrary shell that can hold anything, `key: value`
    included, so its lines are skipped by indentation rather than read as
    structure. That skip is the difference between a reader and a grep.
    """
    out: list[tuple[int, str, str]] = []
    skip_below: int | None = None
    for raw in text.splitlines():
        if not raw.strip() or raw.lstrip().startswith('#'):
            continue
        indent = len(raw) - len(raw.lstrip(' '))
        if skip_below is not None:
            if indent > skip_below:
                continue
            skip_below = None
        match = KEY.match(raw)
        if match is None:
            continue
        value = (match.group(3) or '').strip()
        if value in BLOCK_SCALAR:
            skip_below = indent
        out.append((indent, match.group(2), value))
    return out


def body(name: str) -> str:
    return install.body_of(name)


@pytest.fixture(params=WORKFLOWS, ids=[rel.split('/')[-1] for _, rel in WORKFLOWS])
def workflow(request):
    name, rel = request.param
    return rel, body(name)


# --- the set ------------------------------------------------------------------
def test_install_ci_writes_exactly_the_four_declared_workflows():
    assert tuple(rel for _, rel in WORKFLOWS) == EXPECTED


def test_the_verb_writes_the_whole_set_and_a_diff_round_trips_clean(tmp_path):
    """Install onto a fixture, then `--diff` it: every file reports current and
    nothing prints a hunk. A payload that does not round-trip through its own
    installer is a payload nobody can re-install."""
    import contextlib
    import io
    import os
    import subprocess
    from godot_devkit.core.project import load_config, repo_root

    root = tmp_path / 'game'
    root.mkdir()
    (root / 'project.godot').write_text('config_version=5\n', encoding='utf-8')
    subprocess.run(['git', 'init', '-q'], cwd=root, check=True)
    previous = Path.cwd()
    os.chdir(root)
    repo_root.cache_clear()
    load_config.cache_clear()
    try:
        wrote = io.StringIO()
        with contextlib.redirect_stdout(wrote):
            assert install.main('install-ci', []) == 0
        diffed = io.StringIO()
        with contextlib.redirect_stdout(diffed):
            assert install.main('install-ci', ['--diff']) == 0
    finally:
        os.chdir(previous)
        repo_root.cache_clear()
        load_config.cache_clear()
    for rel in EXPECTED:
        assert (root / rel).is_file(), f'{rel} was not written'
        assert f'wrote {rel}' in wrote.getvalue()
        assert f'{rel} already current' in diffed.getvalue()
    assert '@@' not in diffed.getvalue(), diffed.getvalue()


# --- structure (a minimal reader; the stdlib has no YAML parser) ---------------
def test_the_indentation_holds_no_tabs(workflow):
    """YAML forbids a tab in indentation outright, and a tabbed workflow fails
    at GitHub with a parse error nobody can reproduce locally."""
    rel, text = workflow
    for number, line in enumerate(text.splitlines(), 1):
        leading = line[:len(line) - len(line.lstrip())]
        assert '\t' not in leading, f'{rel}:{number} indents with a tab'


def test_the_top_level_keys_are_a_workflows(workflow):
    rel, text = workflow
    top = [key for indent, key, _ in nodes(text) if indent == 0]
    assert len(top) == len(set(top)), f'{rel} declares a top-level key twice: {top}'
    assert TOP_LEVEL_REQUIRED <= set(top), (
        f'{rel} is missing {sorted(TOP_LEVEL_REQUIRED - set(top))}')
    assert set(top) <= TOP_LEVEL_ALLOWED, (
        f'{rel} declares {sorted(set(top) - TOP_LEVEL_ALLOWED)} at the top level')


def test_every_job_has_a_runner_and_steps(workflow):
    rel, text = workflow
    parsed = nodes(text)
    start = next(i for i, (indent, key, _) in enumerate(parsed)
                 if indent == 0 and key == 'jobs')
    jobs: dict[str, set[str]] = {}
    current = None
    for indent, key, _ in parsed[start + 1:]:
        if indent == 0:
            break
        if indent == 2:
            current = key
            jobs[current] = set()
        elif indent == 4 and current is not None:
            jobs[current].add(key)
    assert jobs, f'{rel} declares no job at all'
    for job, keys in jobs.items():
        assert 'runs-on' in keys, f'{rel}: job {job} has no runs-on'
        assert 'steps' in keys, f'{rel}: job {job} has no steps'


def test_every_action_is_pinned_to_a_major_version(workflow):
    """An unpinned `uses:` is a third party changing this repo's gate without a
    commit here."""
    rel, text = workflow
    used = re.findall(r'^\s*(?:- )?uses:\s*(\S+)', text, re.M)
    assert used, f'{rel} uses no action at all — is the step list intact?'
    for action in used:
        assert re.match(r'^[\w.-]+/[\w.-]+@v\d+$', action), (
            f'{rel} uses {action}, which is not pinned to a major version tag')


def test_every_expression_closes(workflow):
    rel, text = workflow
    assert text.count('${{') == text.count('}}'), (
        f'{rel} has an unbalanced ${{{{ … }}}} expression')


def test_the_file_says_it_was_generated_and_who_owns_it_after(workflow):
    rel, text = workflow
    assert text.startswith('# GENERATED by godot-devkit'), rel
    assert '--force' in text and '--diff' in text, (
        f'{rel} does not tell its reader how to re-install over it')
    assert text.endswith('\n'), f'{rel} has no trailing newline'


# --- generic, and consistent with the include --------------------------------
def test_no_workflow_names_a_consumer_project(workflow):
    """The bulk of the drift between the two forks was the project name in the
    title, and it is what made them look like different files."""
    rel, text = workflow
    for name in ('nullbound', 'trail', 'appalachian', 'core-1'):
        assert name not in text.lower(), f'{rel} names {name}'


def test_every_make_target_a_workflow_runs_is_one_the_include_defines():
    """The defect only this repo can catch: CI calling a target the standard
    set dropped. A red run in a consumer's CI is the alternative."""
    declared = set(re.findall(r'^([a-z][a-z0-9-]*):.*?## ',
                              INCLUDE.read_text(encoding='utf-8'), re.M))
    assert declared, 'the include declared no targets — the census collapsed'
    called: set[str] = set()
    for name, _ in WORKFLOWS:
        called.update(re.findall(r'^\s*(?:- )?run: make ([a-z][a-z0-9-]*)\s*$',
                                 body(name), re.M))
    assert called, 'no workflow runs a make target — the census collapsed'
    assert called <= declared, (
        f'CI runs {sorted(called - declared)}, which Makefile.devkit does not '
        f'define')
