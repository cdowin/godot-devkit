"""The pm test harness — one tree builder and two runners, shared by the
test_pm_* quartet (verbs / gate / scaffold / guidance).

The load-bearing property across that quartet is that the CLI and the gate
share ONE definition of "reviewed" and of each drift rule. So the harness
builds a tree, the tests drive it through the CLI and assert against the
GATE — if the two ever diverged, the round trips stop closing.
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import subprocess
import tempfile
from pathlib import Path

from godot_devkit.repo.checks import pm as pm_check
from godot_devkit.repo.pm import cli, model


def _case_sensitive_tmp() -> bool:
    """Can two names differing only by case coexist where tests build trees?

    macOS is case-INSENSITIVE by default, so the two-spellings case cannot be
    STAGED there at all. Reported as a skip rather than asserted away: a test
    that quietly passes because its fixture could not be built is rule 4's sin
    wearing a test's clothes.
    """
    with tempfile.TemporaryDirectory() as tmp:
        lower = Path(tmp) / 'casetest.md'
        lower.write_text('x', encoding='utf-8')
        upper = Path(tmp) / 'CASETEST.md'
        upper.write_text('y', encoding='utf-8')
        return lower.read_text(encoding='utf-8') == 'x'


CASE_SENSITIVE_TMP = _case_sensitive_tmp()


# The three ways a real editor breaks a frontmatter block WITHOUT removing it:
# a Windows editor writes the BOM, a paste lands a blank line above the fence,
# a hand-edit eats the closing one. All three still OPEN a `---` block, so all
# three are grains whose frontmatter is DAMAGED — never notes.
DAMAGE_FORMS = ('bom', 'blank-line', 'no-closing-fence')
STORY_REL = 'pm/roadmap/0.1-demo/features/alpha/stories/s0.md'


def damage(path: Path, form: str) -> None:
    raw = path.read_text(encoding='utf-8')
    if form == 'bom':
        raw = '﻿' + raw
    elif form == 'blank-line':
        raw = '\n' + raw
    elif form == 'no-closing-fence':
        lines = raw.split('\n')
        close = next(i for i in range(1, len(lines)) if lines[i] == '---')
        del lines[close]
        raw = '\n'.join(lines)
    else:  # pragma: no cover - a typo in a fixture is not a fixture
        raise AssertionError(f'unknown damage form {form!r}')
    path.write_text(raw, encoding='utf-8')


def write(path: Path, front: dict[str, str], body: str = 'x') -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = ['---'] + [f'{k}: {v}' for k, v in front.items()] + ['---', '', body, '']
    path.write_text('\n'.join(lines), encoding='utf-8')


@contextlib.contextmanager
def tree(milestone_status='building', feature_status='building',
         story_statuses=('todo',), with_record=True):
    """A one-milestone/one-feature/N-story repo, cwd'd into."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / 'repo'
        mdir = root / 'pm' / 'roadmap' / '0.1-demo'
        fdir = mdir / 'features' / 'alpha'
        write(mdir / 'milestone.md', {'id': '"0.1"', 'name': 'Demo',
                                      'status': milestone_status})
        feature = {'id': '0.1/alpha', 'milestone': '"0.1"', 'name': 'Alpha',
                   'status': feature_status, 'reviewed': ''}
        if with_record:
            (root / 'docs' / 'reviews').mkdir(parents=True, exist_ok=True)
            (root / 'docs' / 'reviews' / 'alpha.md').write_text(
                'A real review record with enough content to be substantive.\n',
                encoding='utf-8')
            feature['reviewed'] = 'docs/reviews/alpha.md'
        write(fdir / 'feature.md', feature)
        for i, st in enumerate(story_statuses):
            write(fdir / 'stories' / f's{i}.md',
                  {'id': f'0.1/alpha/s{i}', 'feature': '0.1/alpha',
                   'milestone': '"0.1"', 'name': f'S{i}', 'status': st})
        subprocess.run(['git', 'init', '-q'], cwd=root, check=True)
        previous = Path.cwd()
        os.chdir(root)
        try:
            yield root
        finally:
            os.chdir(previous)


def bug(root: Path, slug: str = 'crash', status: str = 'open',
        **extra: str) -> Path:
    """One bug document under `tree()`'s milestone, and its path.

    The canonical frontmatter a scaffolded bug carries, so a test that cares
    about ONE field (`caused_by:`) names that field and nothing else.
    """
    path = root / 'pm/roadmap/0.1-demo/bugs' / f'{slug}.md'
    front = {'id': f'0.1/bugs/{slug}', 'milestone': '"0.1"', 'name': '',
             'status': status, 'caught_in': '"0.1"', 'fix_milestone': ''}
    front.update(extra)
    write(path, front)
    return path


def frontmatter(path: Path) -> list[str]:
    """The lines INSIDE the leading `---` fence, verbatim.

    The bytes, not a parse: field order and an empty field's exact spelling
    (`caused_by:`, no trailing space) are half of what a template promises.
    """
    lines = path.read_text(encoding='utf-8').split('\n')
    assert lines[0] == '---', f'{path} does not open a frontmatter block'
    return lines[1:lines.index('---', 1)]


LEDGER_REL = 'pm/roadmap/0.1-demo/ledger.jsonl'


def ledger_lines(root: Path, rel: str = LEDGER_REL) -> list[str]:
    """The milestone ledger's raw LINES — the bytes, never a re-serialisation.

    Read as text rather than through a parser on purpose: compactness, key
    order and one-row-per-line are half the row shape, and a parse would
    answer the same for a pretty-printed file that no `readline` reader could
    use. An absent ledger is [] — a milestone nothing has happened in yet.
    """
    path = root / rel
    if not path.is_file():
        return []
    return path.read_text(encoding='utf-8').splitlines()


def ledger_rows(root: Path, rel: str = LEDGER_REL) -> list[dict]:
    """The same lines, parsed, oldest first."""
    return [json.loads(line) for line in ledger_lines(root, rel) if line.strip()]


def cfg_for(root: Path) -> model.PmConfig:
    return model.PmConfig(root=root)


def run_cli(root: Path, *argv: str) -> tuple[int, str]:
    # repo_root()/load_config() are lru_cached on purpose in production, where
    # the cwd never moves mid-run. Tests move it every case.
    from godot_devkit.core.project import load_config, repo_root
    repo_root.cache_clear()
    load_config.cache_clear()
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        try:
            code = cli.main(list(argv))
        except SystemExit as exc:  # pragma: no cover - defensive
            code = int(exc.code or 0)
    return code, buf.getvalue()


def run_gate(root: Path) -> tuple[int, str]:
    from godot_devkit.core.project import load_config, repo_root
    repo_root.cache_clear()
    load_config.cache_clear()
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = pm_check.run()
    return code, buf.getvalue()


# --- ledger fixtures ----------------------------------------------------------
# One home for the LINE builders, because two report tests seeding two
# differently-shaped ledgers must still write the row shape `pm ledger record`
# and the status verbs write — a fixture that drifted from the writer would
# test a file this package never produces. Every builder goes through
# `ledger.dumps`, the serialisation contract itself.
MILESTONE_ID = '0.1'

# D3's snapshot as the hook writes it: every bucket present, empty lists when
# empty. A row naming no grain has all five empty.
EMPTY_TREE = {'milestones_building': [MILESTONE_ID], 'features_building': [],
              'features_review': [], 'stories_wip': [], 'stories_review': []}


def snapshot(**over: list) -> dict:
    snap = dict(EMPTY_TREE)
    snap.update(over)
    return snap


def status_line(ts: str, grain: str, frm: str, to: str) -> str:
    from godot_devkit.repo.pm import ledger
    return ledger.dumps(ledger.status_row(grain, frm, to, ts=ts))


def decision_line(ts: str, grain: str, entry: str, title: str = 'why') -> str:
    from godot_devkit.repo.pm import ledger
    return ledger.dumps(ledger.decision_row(grain, entry, title, ts=ts))


def dispatch_line(ts: str, **fields: object) -> str:
    from godot_devkit.repo.pm import ledger
    fields.setdefault('tree', snapshot())
    return ledger.dumps(ledger.usage_row(ledger.KIND_DISPATCH, ts=ts,
                                         **fields))


def session_line(ts: str, **fields: object) -> str:
    from godot_devkit.repo.pm import ledger
    return ledger.dumps(ledger.usage_row(ledger.KIND_SESSION, ts=ts, **fields))


def put_ledger(root: Path, *lines: str, rel: str = LEDGER_REL) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(''.join(line + '\n' for line in lines), encoding='utf-8')


SECTION_SEPARATOR = ' — '


def section_of(out: str, title: str) -> str:
    """One `pm ledger report` section, heading included, from the whole report.

    The report is five sections and each one is a separate contract, so a case
    that pins section 4's table must fail when section 4 changes and NOT when
    section 2 grows a column. The slice runs from the section's own heading to
    the next one — `<prefix> <milestone> — <name> — <census>`, the three-part
    shape only a section heading has. Section 1's SUMMARY line carries one
    separator, not two, so it belongs to the section it closes rather than
    opening a new one.
    """
    from godot_devkit.repo.pm import report
    lines = out.rstrip('\n').split('\n')
    heads = [i for i, line in enumerate(lines)
             if line.startswith(report.HEADING_PREFIX)
             and line.count(SECTION_SEPARATOR) >= 2]
    start = next(i for i in heads if f'— {title} —' in lines[i])
    end = next((i for i in heads if i > start), len(lines))
    return '\n'.join(lines[start:end]).rstrip('\n')


# --- git fixtures -------------------------------------------------------------
# `tree()` already `git init`s, because `check pm`'s flow rules read the branch.
# These three add the rest of what a `--from <rev>` case needs: a commit, a tag,
# and a way to assert that a read verb left the tree exactly as it found it.
#
# Identity and signing are supplied per INVOCATION rather than written into the
# scratch repo's config. A test that inherited the developer's `user.email`, a
# global `commit.gpgsign`, or a `gpg.program` that prompts would pass on one
# machine and hang or fail on the next, for a reason having nothing to do with
# the verb under test.
GIT_IDENTITY = ('-c', 'user.name=pm tests', '-c', 'user.email=pm@tests.invalid',
                '-c', 'commit.gpgsign=false', '-c', 'tag.gpgsign=false')


def git(root: Path, *args: str) -> str:
    """One git command in a scratch repo. A failure is an ASSERTION, not a
    return code: a fixture that half-built itself and carried on would test a
    tree nobody described, which is the one failure mode a fixture cannot
    report on its own."""
    done = subprocess.run(['git', *GIT_IDENTITY, *args], cwd=root,
                          capture_output=True, text=True)
    assert done.returncode == 0, (
        f'git {" ".join(args)} failed in {root}:\n{done.stderr}{done.stdout}')
    return done.stdout


def commit(root: Path, message: str = 'seed') -> str:
    """Stage everything and commit it; return the commit's full hash."""
    git(root, 'add', '-A')
    git(root, 'commit', '-q', '--allow-empty', '-m', message)
    return git(root, 'rev-parse', 'HEAD').strip()


def porcelain(root: Path) -> str:
    """`git status --porcelain` — '' for a tree a read verb did not touch."""
    return git(root, 'status', '--porcelain')
