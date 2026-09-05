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

import contextlib
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from support import REPO_ROOT, run_check  # noqa: E402

sys.path.insert(0, str(REPO_ROOT / 'src'))
from godot_devkit.core.project import load_config, repo_root  # noqa: E402
from godot_devkit.repo import install  # noqa: E402
from godot_devkit.repo.checks import hooks as check_hooks  # noqa: E402

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


# --- verify.yml: the Godot toolchain, keyed off the project -------------------
# 0.24.0/bugs/ci-verify-installs-no-godot: the shipped verify.yml was this
# package's OWN CI shape — checkout, uv, `make milestone` — and a consumer's
# `make milestone` boots the engine and shells out to gdlint and shellcheck. One
# file has to be right in both trees, so the toolchain steps carry
# `if: hashFiles('project.godot') != ''` and the engine version is READ from
# project.godot instead of written twice.

VERIFY = 'ci-verify.yml'
GODOT_GUARD = "hashFiles('project.godot') != ''"
# `core.hooksPath` is repo-LOCAL git config: nothing tracked carries it and a
# fresh `actions/checkout` has never had it set, so a repo that runs `check
# hooks` in its full gate is UNARMED on every CI run however armed the
# developer's tree is. The arming step is guarded the same way the engine steps
# are — a repo with no `tools/setup-hooks.sh` has no corpus to arm.
HOOKS_GUARD = "hashFiles('tools/setup-hooks.sh') != ''"
ARM_STEP = 'Arm the tracked git hooks'
KNOWN_GUARDS = ('', GODOT_GUARD, HOOKS_GUARD, 'failure()')
# The `config/features` line a real Godot 4 project carries, verbatim from the
# consumer whose hand edit this fix promotes. The engine line is the FIRST
# entry; the patch level is nowhere in the file, which is why it is the knob.
CONSUMER_FEATURES = 'config/features=PackedStringArray("4.6", "Forward Plus")\n'


def steps_of(text: str) -> list[tuple[str, str, str]]:
    """(label, guard, script) for every step of the job, in order.

    The same indentation reader the rest of this file uses: a step is a `- ` at
    the list's indent, its keys sit one level in, and a `run:` body is deeper
    still — read as SCRIPT, never as structure, so a case can EXECUTE what the
    file says instead of restating it. A blank line inside a body is dropped,
    which is a no-op line in a shell script and a no-op here.
    """
    lines = text.splitlines()
    at = next(i for i, line in enumerate(lines) if line.strip() == 'steps:')
    blocks: list[list[str]] = []
    step_indent: int | None = None
    for line in lines[at + 1:]:
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip(' '))
        if step_indent is None:
            step_indent = indent
        if indent < step_indent:
            break
        if indent == step_indent and line.lstrip().startswith('- '):
            blocks.append([])
        if blocks:
            blocks[-1].append(line)
    assert blocks and step_indent is not None, 'the step list is empty'
    out = []
    for block in blocks:
        keys: dict[str, str] = {}
        script: list[str] = []
        in_script = False
        for number, line in enumerate(block):
            indent = len(line) - len(line.lstrip(' '))
            if number == 0:
                body_line = line.lstrip()[2:]
            elif in_script and indent > step_indent + 2:
                script.append(line[step_indent + 4:])
                continue
            elif indent == step_indent + 2 and not line.lstrip().startswith('#'):
                in_script = False
                body_line = line.lstrip()
            else:
                continue
            key, _, value = body_line.partition(':')
            key, value = key.strip(), value.strip()
            keys.setdefault(key, value)
            if key == 'run':
                in_script = value in BLOCK_SCALAR
                if not in_script:
                    script.append(value)
        out.append((keys.get('name') or keys.get('uses', '?'),
                    keys.get('if', ''), '\n'.join(script)))
    return out


def would_run(text: str, *, project_godot: bool,
              setup_hooks: bool = True) -> list[str]:
    """The step labels GitHub schedules on a green run, with/without the files.

    An `if:` this reader does not know is REFUSED rather than assumed to run:
    a future edit to some other guard fails here instead of quietly listing a
    step that would skip.
    """
    present = {GODOT_GUARD: project_godot, HOOKS_GUARD: setup_hooks}
    out = []
    for label, guard, _ in steps_of(text):
        assert guard in KNOWN_GUARDS, f'{label}: unreadable guard {guard!r}'
        if guard == 'failure()':
            continue
        if guard and not present[guard]:
            continue
        out.append(label)
    return out


def test_a_godot_project_gets_the_engine_and_the_linters_before_the_gate():
    """The defect, stated as the fix: a tree with a project.godot installs an
    engine and the two linters `make milestone` shells out to, and installs
    them BEFORE the gate that needs them."""
    ran = would_run(body(VERIFY), project_godot=True)
    engine = [i for i, label in enumerate(ran) if 'setup-godot' in label]
    linters = [i for i, label in enumerate(ran)
               if 'gdlint' in label.lower() and 'shellcheck' in label.lower()]
    gate = [i for i, label in enumerate(ran) if label == 'make milestone']
    assert engine, f'no Godot engine step in a Godot project: {ran}'
    assert linters, f'no gdlint + shellcheck step in a Godot project: {ran}'
    assert gate, f'the full gate step vanished: {ran}'
    assert max(engine + linters) < min(gate), (
        f'the toolchain is installed after the gate that needs it: {ran}')


def test_a_tree_with_no_project_godot_still_runs_the_gate_on_uv_alone():
    """This package installs this file into ITSELF, and has no engine in it.
    The list is asserted whole: a new unguarded step here is a step every
    non-Godot consumer pays for."""
    assert would_run(body(VERIFY), project_godot=False) == [
        'actions/checkout@v4', ARM_STEP, 'astral-sh/setup-uv@v5',
        'make milestone']
    # And a tree with neither file is back to the three-step run: both
    # additions this release makes are guarded, neither is a tax on a repo
    # that ships neither.
    assert would_run(body(VERIFY), project_godot=False,
                     setup_hooks=False) == [
        'actions/checkout@v4', 'astral-sh/setup-uv@v5', 'make milestone']


def test_the_checkout_is_ARMED_before_the_gate_that_asks_whether_it_is():
    """A checkout is not a developer's tree.

    `core.hooksPath` is repo-local git config; `actions/checkout` produces a
    tree that has never had it set, so a repo whose full gate runs `check
    hooks` was red on EVERY clean run — the gate reporting a true fact about
    the runner, and the release protocol unable to complete because of it.
    The same shape as the engine steps: the gate assumes a prepared tree, and
    preparing it is what the steps ahead of it are for.
    """
    ran = would_run(body(VERIFY), project_godot=True)
    assert ARM_STEP in ran, f'nothing arms the checkout: {ran}'
    assert ran.index(ARM_STEP) < ran.index('make milestone'), (
        f'the checkout is armed after the gate that reads it: {ran}')
    script = next(s for label, _, s in steps_of(body(VERIFY))
                  if label == ARM_STEP)
    assert script.strip() == 'bash tools/setup-hooks.sh', script


@contextlib.contextmanager
def a_fresh_checkout():
    """A repo as `actions/checkout` hands one over: the corpus tracked and on
    disk, and NO repo-local git config, because none is tracked and the runner
    has never run anything in it."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / 'checkout'
        root.mkdir()
        subprocess.run(['git', 'init', '-q', '-b', 'main'], cwd=root, check=True)
        previous = Path.cwd()
        os.chdir(root)
        repo_root.cache_clear()
        load_config.cache_clear()
        try:
            assert install.main('install-hooks', []) == 0
            yield root
        finally:
            os.chdir(previous)
            repo_root.cache_clear()
            load_config.cache_clear()


def test_running_the_workflows_own_steps_is_what_turns_the_gate_green():
    """The defect end to end, in a checkout rather than in the file's shape.

    The scripts are READ OUT of the workflow and executed, so a step that stops
    arming — or arms with something that does not work — reds here. `make
    milestone` is the step under test and is not run.
    """
    with a_fresh_checkout() as root:
        assert not subprocess.run(
            ['git', 'config', '--get', 'core.hooksPath'], cwd=root,
            capture_output=True, text=True).stdout.strip(), (
                'a fresh checkout came with core.hooksPath already set')
        unarmed, said = run_check(check_hooks)
        assert unarmed == 1 and 'UNARMED' in said, said

        for label, guard, script in steps_of(body(VERIFY)):
            if not script or label == 'make milestone':
                continue
            assert guard in KNOWN_GUARDS, f'{label}: unreadable guard {guard!r}'
            if guard == HOOKS_GUARD and not (root / 'tools/setup-hooks.sh').exists():
                continue
            if guard in (GODOT_GUARD, 'failure()'):
                continue
            done = subprocess.run(['bash', '-c', script], cwd=root,
                                  capture_output=True, text=True)
            assert done.returncode == 0, f'{label}: {done.stderr}'

        assert subprocess.run(
            ['git', 'config', '--get', 'core.hooksPath'], cwd=root,
            capture_output=True, text=True).stdout.strip() == check_hooks.HOOKS_DIR
        armed, said = run_check(check_hooks)
    assert armed == 0, said
    assert '[check:hooks] PASS' in said, said


def test_the_engine_version_is_derived_and_only_the_patch_is_written_down():
    """No `version: "4.6.2"` anywhere: a hard-coded engine line is a second
    copy of a fact project.godot already carries, and the copy is the one that
    goes stale. The patch level is the one knob, and it is at the head."""
    text = body(VERIFY)
    head = text.split('jobs:')[0]
    assert re.search(r'^env:$', head, re.M), 'no project-config env block at the head'
    assert re.search(r'^  GODOT_PATCH: "\d+"$', head, re.M), (
        'GODOT_PATCH is not a numeric knob at the head of the file')
    hardcoded = re.findall(r'^\s*version:\s*[\'"]?(\d+\.\d+.*)$', text, re.M)
    assert not hardcoded, f'the engine version is written down here: {hardcoded}'


# --- verify.yml: the version-derivation step, RUN -----------------------------
# The structural reader cannot say what a `run:` body does, so this runs it —
# the same treatment the semver-gate compare step gets. Every row is a
# project.godot and a patch knob; a refusal must SAY what it refused and write
# no version at all, because a step that emits an empty version hands
# setup-godot a string nobody wrote.

def _version_step_script() -> str:
    text = body(VERIFY)
    lines = text.splitlines()
    start = next(i for i, line in enumerate(lines)
                 if line.strip().startswith('- name: Godot version'))
    run_at = next(i for i in range(start, len(lines))
                  if lines[i].strip() == 'run: |')
    indent = len(lines[run_at]) - len(lines[run_at].lstrip(' '))
    out = []
    for line in lines[run_at + 1:]:
        if line.strip() and (len(line) - len(line.lstrip(' '))) <= indent:
            break
        out.append(line[indent + 2:] if line.strip() else '')
    return '\n'.join(out) + '\n'


def _run_version_step(tmp_path: Path, project_godot: str | None, patch):
    import subprocess
    script = tmp_path / 'version.sh'
    script.write_text(_version_step_script(), encoding='utf-8')
    if project_godot is not None:
        (tmp_path / 'project.godot').write_text(project_godot, encoding='utf-8')
    out_file = tmp_path / 'github_output'
    out_file.write_text('', encoding='utf-8')
    env = {'PATH': '/usr/bin:/bin', 'GITHUB_OUTPUT': str(out_file)}
    if patch is not None:
        env['GODOT_PATCH'] = patch
    proc = subprocess.run(['bash', str(script)], cwd=tmp_path, capture_output=True,
                          text=True, env=env)
    return proc, out_file.read_text(encoding='utf-8')


HEADER = 'config_version=5\n\n[application]\n\nconfig/name="Fresh"\n'


@pytest.mark.parametrize('features, patch, expected', [
    (CONSUMER_FEATURES, '2', '4.6.2'),
    # The fixture `godot-devkit init` is proven against: one entry, no renderer.
    ('config/features=PackedStringArray("4.6")\n', '0', '4.6.0'),
    # Not pinned to one engine line, and not pinned to entry ONE either.
    ('config/features=PackedStringArray("4.2", "GL Compatibility")\n', '2', '4.2.2'),
    ('config/features=PackedStringArray("Mobile", "4.3")\n', '11', '4.3.11'),
])
def test_the_step_derives_the_engine_line_from_config_features(
        tmp_path, features, patch, expected):
    proc, wrote = _run_version_step(tmp_path, HEADER + features, patch)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert wrote.strip() == f'version={expected}', wrote
    assert expected in proc.stdout, proc.stdout


@pytest.mark.parametrize('project_godot, patch, why', [
    (None, '2', 'no project.godot'),
    (HEADER, '2', 'config/features'),
    (HEADER + 'config/features=PackedStringArray()\n', '2', 'MAJOR.MINOR'),
    (HEADER + 'config/features=PackedStringArray("Forward Plus")\n', '2', 'MAJOR.MINOR'),
    (HEADER + 'config/features=PackedStringArray("4")\n', '2', 'MAJOR.MINOR'),
    (HEADER + 'config/features=PackedStringArray("4.6.1")\n', '2', 'MAJOR.MINOR'),
    (HEADER + 'config/features=PackedStringArray("v4.6")\n', '2', 'MAJOR.MINOR'),
    (HEADER + CONSUMER_FEATURES, '', 'patch'),
    (HEADER + CONSUMER_FEATURES, None, 'patch'),
    (HEADER + CONSUMER_FEATURES, '2.1', 'patch'),
    (HEADER + CONSUMER_FEATURES, 'latest', 'patch'),
    (HEADER + CONSUMER_FEATURES, '-1', 'patch'),
    (HEADER + CONSUMER_FEATURES, '2; rm -rf .', 'patch'),
])
def test_the_step_refuses_by_name_and_emits_no_version(
        tmp_path, project_godot, patch, why):
    """The refusal matrix. Each row must fail LOUDLY — naming what it could not
    read — and leave $GITHUB_OUTPUT empty, so nothing downstream receives a
    half-derived version string."""
    proc, wrote = _run_version_step(tmp_path, project_godot, patch)
    assert proc.returncode != 0, f'admitted it: {proc.stdout + proc.stderr}\n{wrote}'
    assert why in proc.stdout + proc.stderr, proc.stdout + proc.stderr
    assert wrote == '', f'a refusal still wrote a version: {wrote!r}'


@pytest.mark.parametrize('features, why', [
    # Authored on Windows: every line ends CRLF, and the CR sits where the
    # reader looks for the end of the line.
    (b'config/features=PackedStringArray("4.6", "Forward Plus")\r\n', 'CRLF'),
    (b'config/features=PackedStringArray( "4.6" , "Forward Plus" )\n', 'spacing'),
], ids=['crlf', 'spacing'])
def test_the_step_reads_a_project_godot_it_did_not_author(tmp_path, features, why):
    (tmp_path / 'project.godot').write_bytes(b'config_version=5\n' + features)
    proc, wrote = _run_version_step(tmp_path, None, '2')
    assert proc.returncode == 0, f'{why}: {proc.stdout + proc.stderr}'
    assert wrote.strip() == 'version=4.6.2', f'{why}: {wrote!r}'


@pytest.mark.parametrize('entry', [
    '"4.6"; touch pwned',
    '"$(touch pwned)", "4.6"',
    '"`touch pwned`", "4.6"',
    '"4.6", "$(touch pwned)"',
])
def test_a_hostile_config_features_is_never_executed(tmp_path, entry):
    """The step reads a file it did not write and echoes what it could not
    read. Both are expansions inside double quotes and neither is an `eval`, so
    a `config/features` carrying shell must stay a string — whether the row is
    admitted for its one numeric entry or refused for having none."""
    project = f'{HEADER}config/features=PackedStringArray({entry})\n'
    proc, wrote = _run_version_step(tmp_path, project, '2')
    assert not (tmp_path / 'pwned').exists(), (
        f'the step RAN it: {proc.stdout + proc.stderr}')
    assert wrote.strip() in ('', 'version=4.6.2'), wrote
