"""test_init_verb.py — `godot-devkit init` on a blank Godot 4 project.

The verb is a COMPOSITION, so the contract under test is what a composition
can get wrong:

  * the file set is EXACTLY the documented one — spelled literally below, so
    this file reads as the roster, and cross-checked against the tables the
    verbs actually carry so the literal cannot rot;
  * a second run writes NOTHING — proven by hashing every file before and
    after, not by reading the report, which is the thing that would lie;
  * `--diff` names drift on BOTH ownerships (a devkit-owned installable and a
    project-owned seed) and writes nothing;
  * `--force` respects the ownership split: it overwrites the installed files
    and does not touch devkit.toml / Makefile / CLAUDE.md / the PM tree;
  * the refusals are decided BEFORE the first byte — a directory that is not a
    Godot project, and one that is not a git repo, leave it empty.

Nothing here boots Godot. `init` runs OUT OF PROCESS, because it resolves the
repo root and the config through module-level caches that a same-process run
would leave pointing at a deleted temp directory.
"""
from __future__ import annotations

import contextlib
import hashlib
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from support import REPO_ROOT  # noqa: E402

sys.path.insert(0, str(REPO_ROOT / 'src'))
from godot_devkit import __version__  # noqa: E402
from godot_devkit.repo import init, install  # noqa: E402

PROJECT_GODOT = ('config_version=5\n\n[application]\n\n'
                 'config/name="Fresh"\nconfig/version="0.1.0"\n')
ICON = '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16"/>\n'

# THE ROSTER. Spelled out so this file states the contract; cross-checked
# against the verbs' own tables below so it cannot become a second list that
# quietly disagrees with what ships.
WRITES = (
    'devkit.toml',
    'pm/roadmap/ROADMAP.md',
    '.claude/rules/pm-execution.md',
    '.claude/skills/pm-operations/SKILL.md',
    'Makefile',
    'Makefile.devkit',
    'tools/dev/gdk_runners.sh',
    'tools/dev/runners/import_cache.sh',
    'tools/dev/runners/parse.sh',
    'tools/dev/runners/compile_sweep.gd',
    'tools/dev/runners/lint.sh',
    'tools/dev/runners/warnings.sh',
    'tools/dev/runners/unit.sh',
    'tools/dev/runners/scenario.sh',
    'tools/dev/runners/integration.sh',
    'tools/dev/runners/capture.sh',
    'tools/dev/runners/hermetic_run_scan.sh',
    'tools/hooks/cc-commit-pathspec.sh',
    'tools/hooks/cc-godot-sandbox.sh',
    'tools/hooks/cc-stop-gate.sh',
    'tools/hooks/cc-write-confine.sh',
    'tools/hooks/pre-push',
    'tools/hooks/prepare-commit-msg',
    'tools/dev/agent-worktree.sh',
    'tools/dev/checks/doctor.sh',
    'tools/setup-hooks.sh',
    '.claude/agents/verification-reviewer.md',
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
    '.claude/agents/pm-operator.md',
    '.github/workflows/verify.yml',
    '.github/workflows/uid-guard.yml',
    '.github/workflows/semver-gate.yml',
    '.github/workflows/auto-tag.yml',
    '.gitignore',
    'CLAUDE.md',
)
# What the fixture starts with — everything else present afterwards is init's.
PRE_EXISTING = ('project.godot', 'icon.svg')


@contextlib.contextmanager
def fresh_project(git: bool = True, files: dict[str, str] | None = None):
    """An empty Godot 4 project: a project.godot, an icon, and a git repo."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / 'game'
        root.mkdir()
        (root / 'project.godot').write_text(PROJECT_GODOT, encoding='utf-8')
        (root / 'icon.svg').write_text(ICON, encoding='utf-8')
        for rel, body in (files or {}).items():
            target = root / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(body, encoding='utf-8')
        if git:
            subprocess.run(['git', 'init', '-q'], cwd=root, check=True)
        yield root


def devkit(root: Path, *argv: str) -> subprocess.CompletedProcess:
    """The CLI, out of process, from SOURCE — never a cached wheel."""
    return subprocess.run(
        [sys.executable, '-m', 'godot_devkit.cli', *argv],
        cwd=root, capture_output=True, text=True,
        env={**os.environ, 'PYTHONPATH': str(REPO_ROOT / 'src')})


def census(root: Path) -> dict[str, str]:
    """Every file in the tree, git metadata excluded, as path -> content hash."""
    found: dict[str, str] = {}
    for path in root.rglob('*'):
        if not path.is_file():
            continue
        rel = path.relative_to(root).as_posix()
        if rel.startswith('.git/'):
            continue
        found[rel] = hashlib.sha256(path.read_bytes()).hexdigest()
    return found


# --- the file set -------------------------------------------------------------
def test_init_writes_exactly_the_documented_file_set():
    with fresh_project() as root:
        done = devkit(root, 'init')
        assert done.returncode == 0, done.stdout + done.stderr
        present = set(census(root))
    assert present == set(WRITES) | set(PRE_EXISTING), (
        f'unexpected: {sorted(present - set(WRITES) - set(PRE_EXISTING))}; '
        f'missing: {sorted(set(WRITES) - present)}')


def test_the_roster_above_is_what_the_verbs_actually_carry():
    """The literal roster cross-checked against the tables that ship, so an
    installable added to a plan without a line up there fails HERE rather than
    silently widening what `init` writes."""
    from_tables = {rel for entries in install.PLANS.values()
                   for _, rel in entries}
    from_tables |= {rel for _, rel in init.SEEDS}
    # The PM tree and .gitignore have no plan table — they are the two writes
    # init owns outright, and they are named here for exactly that reason.
    owned = {'pm/roadmap/ROADMAP.md', '.claude/rules/pm-execution.md',
             '.claude/skills/pm-operations/SKILL.md', '.gitignore'}
    assert set(WRITES) == from_tables | owned, (
        f'roster drift: {sorted(set(WRITES) ^ (from_tables | owned))}')


def test_the_makefile_pins_this_version_and_includes_the_standard_set():
    with fresh_project() as root:
        assert devkit(root, 'init').returncode == 0
        body = (root / 'Makefile').read_text(encoding='utf-8')
    assert f'DEVKIT_VERSION := v{__version__}' in body, body
    assert 'include Makefile.devkit' in body, body
    assert init.VERSION_PLACEHOLDER not in body, 'the pin was never substituted'


def test_the_config_template_carries_every_section_the_gates_read():
    """Commented out, at the stock default — a repo with no devkit.toml must
    behave byte-identically to one declaring the defaults, so the template
    starts inert and is a menu rather than an opinion."""
    body = init.seed_body(init.SEED_CONFIG[0])
    for section in ('checks', 'gates', 'uid', 'tres', 'props', 'defaults',
                    'doc', 'shell', 'repo_hygiene', 'pm', 'autoloads', 'refs',
                    'orphans', 'rng', 'tres_comment', 'unit_disk',
                    'test_shape'):
        assert f'# [{section}]' in body, f'[{section}] is not in the template'
    live = [ln for ln in body.splitlines()
            if ln.strip() and not ln.lstrip().startswith('#')]
    assert live == [], f'the template declares something: {live}'


def test_the_gitignore_entries_are_the_runners_own_defaults():
    """A shell default is not readable from Python, so it is PINNED here: each
    ignored directory must be the `GDK_*` default of the runner that writes
    it. A rename on either side fails this rather than silently committing a
    consumer's gate transcripts."""
    owners = {'.gate-reports/': ('gdk_runners.sh', 'GDK_GATE_REPORT_DIR'),
              '.headless-userdata/': ('gdk_runners.sh', 'GDK_SANDBOX_DIRNAME'),
              '.scenario-reports/': ('scenario.sh', 'GDK_SCENARIO_REPORT_DIR'),
              '.capture-reports/': ('capture.sh', 'GDK_CAPTURE_REPORT_DIR')}
    assert set(init.IGNORED) == set(owners)
    for entry, (runner, variable) in owners.items():
        body = install.body_of(runner)
        expected = f'{variable}="${{{variable}:-{entry.rstrip("/")}}}"'
        assert expected in body, (
            f'{runner} no longer defaults {variable} to {entry} '
            f'(looked for {expected})')


# --- idempotence --------------------------------------------------------------
def test_a_second_run_writes_nothing():
    with fresh_project() as root:
        assert devkit(root, 'init').returncode == 0
        before = census(root)
        done = devkit(root, 'init')
        after = census(root)
    assert done.returncode == 0, done.stdout + done.stderr
    changed = [rel for rel in before if before[rel] != after.get(rel)]
    assert not changed, f'a second run rewrote: {changed}'
    assert set(after) == set(before), (
        f'a second run added: {sorted(set(after) - set(before))}')
    assert 'wrote' not in done.stdout, done.stdout


def test_a_second_run_does_not_duplicate_the_gitignore_entries():
    with fresh_project(files={'.gitignore': '*.tmp\n'}) as root:
        assert devkit(root, 'init').returncode == 0
        assert devkit(root, 'init').returncode == 0
        body = (root / '.gitignore').read_text(encoding='utf-8')
    assert body.startswith('*.tmp\n'), 'the project\'s own entries were lost'
    for entry in init.IGNORED:
        assert body.count(entry) == 1, f'{entry} appears twice:\n{body}'


# --- --diff -------------------------------------------------------------------
def test_diff_names_drift_on_both_ownerships_and_writes_nothing():
    with fresh_project() as root:
        assert devkit(root, 'init').returncode == 0
        (root / 'tools/dev/checks/doctor.sh').write_text(
            '#!/usr/bin/env bash\necho mine\n', encoding='utf-8')
        (root / 'CLAUDE.md').write_text('# mine\n', encoding='utf-8')
        before = census(root)
        done = devkit(root, 'init', '--diff')
        after = census(root)
    assert done.returncode == 0, done.stdout + done.stderr
    assert before == after, '--diff wrote something'
    assert 'a/tools/dev/checks/doctor.sh' in done.stdout, done.stdout
    assert 'a/CLAUDE.md' in done.stdout, done.stdout
    # Everything else is reported current, so the drift is what stands out.
    assert done.stdout.count('already current') >= len(WRITES) - 4, done.stdout


def test_diff_names_a_missing_gitignore_entry():
    with fresh_project() as root:
        assert devkit(root, 'init').returncode == 0
        (root / '.gitignore').write_text('*.tmp\n', encoding='utf-8')
        done = devkit(root, 'init', '--diff')
    assert done.returncode == 0, done.stdout + done.stderr
    assert '.gitignore is missing .gate-reports/' in done.stdout, done.stdout


# --- ownership ----------------------------------------------------------------
def test_a_differing_project_owned_file_is_reported_not_refused():
    """devkit.toml, Makefile and CLAUDE.md are the project's from the first
    write. Divergence is what they are FOR, so it is not a collision."""
    with fresh_project() as root:
        assert devkit(root, 'init').returncode == 0
        mine = '# mine\n'
        for rel in ('devkit.toml', 'Makefile', 'CLAUDE.md'):
            (root / rel).write_text(mine, encoding='utf-8')
        done = devkit(root, 'init')
        kept = [(root / rel).read_text(encoding='utf-8')
                for rel in ('devkit.toml', 'Makefile', 'CLAUDE.md')]
    assert done.returncode == 0, done.stdout + done.stderr
    assert kept == [mine] * 3, 'a project-owned file was overwritten'
    assert done.stdout.count('is yours — left alone') == 3, done.stdout


def test_force_overwrites_the_installed_files_and_not_the_projects_own():
    with fresh_project() as root:
        assert devkit(root, 'init').returncode == 0
        stock = (root / 'tools/dev/checks/doctor.sh').read_text(encoding='utf-8')
        (root / 'tools/dev/checks/doctor.sh').write_text('# mine\n',
                                                         encoding='utf-8')
        (root / 'CLAUDE.md').write_text('# mine\n', encoding='utf-8')
        done = devkit(root, 'init', '--force')
        restored = (root / 'tools/dev/checks/doctor.sh').read_text(encoding='utf-8')
        claude = (root / 'CLAUDE.md').read_text(encoding='utf-8')
    assert done.returncode == 0, done.stdout + done.stderr
    assert restored == stock, '--force did not restore the devkit-owned file'
    assert claude == '# mine\n', '--force overwrote a project-owned file'


def test_a_differing_installed_file_refuses_and_names_force():
    with fresh_project() as root:
        assert devkit(root, 'init').returncode == 0
        (root / 'tools/dev/checks/doctor.sh').write_text('# mine\n',
                                                         encoding='utf-8')
        done = devkit(root, 'init')
        kept = (root / 'tools/dev/checks/doctor.sh').read_text(encoding='utf-8')
    assert done.returncode == 1, done.stdout + done.stderr
    assert kept == '# mine\n', 'the refusal wrote anyway'
    assert '--force' in done.stderr + done.stdout
    assert 'REFUSED by install-hooks' in done.stdout, done.stdout


# --- the refusal matrix -------------------------------------------------------
def test_a_directory_that_is_not_a_godot_project_is_refused_whole():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        subprocess.run(['git', 'init', '-q'], cwd=root, check=True)
        done = devkit(root, 'init')
        left = set(census(root))
    assert done.returncode == 2, done.stdout + done.stderr
    assert 'project.godot' in done.stderr
    assert 'nothing was written' in done.stderr
    assert left == set(), f'a refused init wrote: {sorted(left)}'


def test_a_directory_that_is_not_a_git_repo_is_refused_whole():
    with fresh_project(git=False) as root:
        done = devkit(root, 'init')
        left = set(census(root))
    assert done.returncode == 2, done.stdout + done.stderr
    assert 'not a git repository' in done.stderr
    assert left == set(PRE_EXISTING), f'a refused init wrote: {sorted(left)}'


@pytest.mark.parametrize('flag', ['--forse', '-f', 'install', '--diff=1', ''])
def test_an_unknown_flag_is_a_usage_error_that_writes_nothing(flag):
    with fresh_project() as root:
        done = devkit(root, 'init', flag)
        left = set(census(root))
    assert done.returncode == 2, done.stdout + done.stderr
    assert 'unknown flag' in done.stderr
    assert left == set(PRE_EXISTING), f'a usage error wrote: {sorted(left)}'


def test_help_prints_the_written_set_and_writes_nothing():
    with fresh_project() as root:
        done = devkit(root, 'init', '--help')
        left = set(census(root))
    assert done.returncode == 0, done.stdout + done.stderr
    assert 'usage: godot-devkit init' in done.stdout
    assert left == set(PRE_EXISTING)


def test_a_seed_destination_that_is_a_directory_is_a_refusal_not_a_traceback():
    with fresh_project() as root:
        (root / 'CLAUDE.md').mkdir()
        done = devkit(root, 'init')
    assert done.returncode == 1, done.stdout + done.stderr
    assert 'CLAUDE.md is a directory' in done.stderr, done.stderr
    assert 'Traceback' not in done.stderr


# --- what init does BEYOND writing --------------------------------------------
def test_the_hooks_are_armed_not_merely_installed():
    """`core.hooksPath` silently skips a non-executable hook, so an install
    without the arming run is a guard that is not there."""
    with fresh_project() as root:
        done = devkit(root, 'init')
        configured = subprocess.run(
            ['git', 'config', '--get', 'core.hooksPath'], cwd=root,
            capture_output=True, text=True).stdout.strip()
        modes = {p.name: os.access(p, os.X_OK)
                 for p in (root / 'tools/hooks').iterdir()}
    assert done.returncode == 0, done.stdout + done.stderr
    assert configured == 'tools/hooks', configured
    assert all(modes.values()), f'not executable: {sorted(k for k, v in modes.items() if not v)}'


def test_the_installed_claude_md_passes_the_doc_gate_it_arrives_beside():
    """Install day must be green. The skeleton names the standard targets, and
    every one of them lives in the INCLUDED Makefile — which is why `check doc`
    resolves a repo's include chain rather than only its root Makefile."""
    with fresh_project() as root:
        assert devkit(root, 'init').returncode == 0
        subprocess.run(['git', 'add', '-A'], cwd=root, check=True)
        done = devkit(root, 'check', 'doc')
    assert done.returncode == 0, (
        f'the skeleton reddens the gate on install day:\n'
        f'{done.stdout}{done.stderr}')


def test_the_doc_gate_widened_to_the_include_chain_and_no_further():
    """The other half of the fix above: `check doc` now resolves the targets an
    included Makefile defines — and STILL fails a target neither file defines.
    A widening that turned the gate into a false PASS would be the cardinal
    sin, so both directions are asserted in one tree."""
    with fresh_project() as root:
        assert devkit(root, 'init').returncode == 0
        (root / 'CLAUDE.md').write_text(
            '# Doc\n\nThe gate is `make check` and `make precommit`.\n',
            encoding='utf-8')
        subprocess.run(['git', 'add', '-A'], cwd=root, check=True)
        green = devkit(root, 'check', 'doc')
        (root / 'CLAUDE.md').write_text(
            '# Doc\n\nThe gate is `make check` and `make wombat`.\n',
            encoding='utf-8')
        red = devkit(root, 'check', 'doc')
    assert green.returncode == 0, green.stdout + green.stderr
    assert red.returncode == 1, red.stdout
    assert 'unknown make target: `make wombat`' in red.stdout, red.stdout
    assert 'make check' not in red.stdout.split('wombat')[0].split('\n')[-1]
