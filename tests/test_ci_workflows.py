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


# --- semver-gate: the compare step, RUN ---------------------------------------
# The structural reader above cannot say what a `run:` body does, so this runs
# it: the "Compare versions" step's script, under bash, against a scratch PM
# tree, with the same env the workflow gives it. Every claim the gate makes —
# any-length compare, a non-numeric refusal, a done milestone's id or a hotfix
# and NOTHING else — is one row here, and a false PASS is the row that fails.

def _compare_step_script() -> str:
    text = body('ci-semver-gate.yml')
    lines = text.splitlines()
    start = next(i for i, line in enumerate(lines)
                 if line.strip() == '- name: Compare versions')
    run_at = next(i for i in range(start, len(lines))
                  if lines[i].strip() == 'run: |')
    indent = len(lines[run_at]) - len(lines[run_at].lstrip(' '))
    out = []
    for line in lines[run_at + 1:]:
        if line.strip() and (len(line) - len(line.lstrip(' '))) <= indent:
            break
        out.append(line[indent + 2:] if line.strip() else '')
    return '\n'.join(out) + '\n'


def _milestone(root: Path, mid: str, status: str, quote: str = '"',
               body: str = '') -> None:
    mdir = root / 'pm/roadmap' / f'{mid}-m'
    mdir.mkdir(parents=True)
    (mdir / 'milestone.md').write_text(
        f'---\nid: {quote}{mid}{quote}\nname: M\nstatus: {status}\n---\n{body}',
        encoding='utf-8')


@pytest.mark.parametrize('main, pr, done, building, ok, why', [
    ('0.90.3',   '0.90.3.1',   (),          ('0.90.3.2',), True,  'hotfix 1 on main'),
    ('0.90.3.1', '0.90.3.2',   ('0.90.3.2',), (),          True,  'done milestone 0.90.3.2'),
    ('0.16',     '0.16.1',     ('0.16.1',),  (),           True,  'done milestone 0.16.1'),
    ('0.90.3.1', '0.90.3.1.1', (),          ('0.90.4',),  True,  'hotfix 1 on main'),
    ('0.90.2',   '0.90.3',     ('0.90.2',),  ('0.90.3',),  False, "whose status is 'building', not done"),
    ('0.90.3',   '0.90.4',     (),          ('0.90.4',),  False, "whose status is 'building', not done"),
    ('0.90.3',   '0.90.3',     (),          (),           False, 'Version must increase'),
    ('0.90.3',   '0.90.2',     ('0.90.2',),  (),           False, 'Version must increase'),
    ('0.90.3',   '0.90.3a',    (),          (),           False, 'Non-numeric version component'),
    ('0.90.3',   '0.90.3.1a',  (),          (),           False, 'Non-numeric version component'),
    ('1.0',      '1.0.0',      ('1.0.0',),   (),           False, 'Version must increase'),
    # The finding that made the first cut of this rule NOT RELEASE-SAFE: a
    # BUILDING milestone whose id is main + one integer read as a hotfix.
    ('0.90.3',   '0.90.3.2',   (),          ('0.90.3.2',), False, "whose status is 'building', not done"),
    ('0.90.3',   '0.90.3.01',  ('0.90.2',),  (),           False, 'neither the id of a done milestone'),
])
def test_the_compare_step_admits_a_done_milestone_or_a_hotfix_and_nothing_else(
        tmp_path, main, pr, done, building, ok, why):
    """PR #56 on the consumer that motivated this: the 0.90.2 release reached
    main wearing 0.90.3 — the NEXT milestone's bump-at-start had landed before
    the close merged — and the three-field gate waved it through. Row 5 is
    that PR, and it is refused."""
    import subprocess
    for mid in done:
        _milestone(tmp_path, mid, 'done')
    for mid in building:
        _milestone(tmp_path, mid, 'building')
    (tmp_path / 'pm/roadmap').mkdir(parents=True, exist_ok=True)
    script = tmp_path / 'compare.sh'
    script.write_text(_compare_step_script(), encoding='utf-8')
    proc = subprocess.run(['bash', str(script)], cwd=tmp_path, capture_output=True,
                          text=True, env={'PATH': '/usr/bin:/bin', 'PR': pr,
                                          'MAIN': main, 'PM_ROADMAP': 'pm/roadmap'})
    assert (proc.returncode == 0) is ok, proc.stdout + proc.stderr
    assert why in proc.stdout + proc.stderr, proc.stdout + proc.stderr


def test_the_compare_step_reads_only_the_frontmatter_and_either_quote_style(tmp_path):
    """A `status: done` line in a milestone's BODY (a schema example) must not
    vouch for the file, and a single-quoted id is the same id."""
    import subprocess
    _milestone(tmp_path, '0.93', 'planning', body='\nSchema example:\n\nstatus: done\n')
    _milestone(tmp_path, '0.98', 'done', quote="'")
    script = tmp_path / 'compare.sh'
    script.write_text(_compare_step_script(), encoding='utf-8')
    def run(pr):
        return subprocess.run(['bash', str(script)], cwd=tmp_path, capture_output=True,
                              text=True, env={'PATH': '/usr/bin:/bin', 'PR': pr,
                                              'MAIN': '0.90', 'PM_ROADMAP': 'pm/roadmap'})
    refused = run('0.93')
    assert refused.returncode == 1 and "whose status is 'planning'" in refused.stdout, refused.stdout
    admitted = run('0.98')
    assert admitted.returncode == 0 and 'done milestone 0.98' in admitted.stdout, admitted.stdout


@pytest.mark.parametrize('roadmap, why', [
    ('nope', 'is not a directory'),
    ('pm/roadmap', 'scanned nothing'),
])
def test_the_compare_step_refuses_when_it_scanned_no_milestone(tmp_path, roadmap, why):
    """Rule 4: a hotfix-shaped PR over an absent or empty roadmap is not OK —
    the building-milestone refusal only exists if the tree was read."""
    import subprocess
    (tmp_path / 'pm/roadmap').mkdir(parents=True)
    script = tmp_path / 'compare.sh'
    script.write_text(_compare_step_script(), encoding='utf-8')
    proc = subprocess.run(['bash', str(script)], cwd=tmp_path, capture_output=True,
                          text=True, env={'PATH': '/usr/bin:/bin', 'PR': '0.8.1',
                                          'MAIN': '0.8', 'PM_ROADMAP': roadmap})
    assert proc.returncode == 1 and why in proc.stdout, proc.stdout + proc.stderr


def test_the_compare_step_ignores_an_unclosed_fence_and_strips_trailing_space(tmp_path):
    import subprocess
    mdir = tmp_path / 'pm/roadmap/0.9-m'; mdir.mkdir(parents=True)
    (mdir / 'milestone.md').write_text('---\nid: "0.9"\nname: x\nfoo\n\nstatus: done\n',
                                       encoding='utf-8')
    _milestone(tmp_path, '0.8', 'done   ', quote='')
    script = tmp_path / 'compare.sh'
    script.write_text(_compare_step_script(), encoding='utf-8')
    def run(pr):
        return subprocess.run(['bash', str(script)], cwd=tmp_path, capture_output=True,
                              text=True, env={'PATH': '/usr/bin:/bin', 'PR': pr,
                                              'MAIN': '0.7', 'PM_ROADMAP': 'pm/roadmap'})
    unclosed = run('0.9')
    assert unclosed.returncode == 1 and 'neither the id of a done milestone' in unclosed.stdout, unclosed.stdout
    padded = run('0.8')
    assert padded.returncode == 0 and 'done milestone 0.8' in padded.stdout, padded.stdout
