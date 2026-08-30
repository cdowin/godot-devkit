"""test_pm_close_protocol.py — what `pm feature done` accepts as a review record.

The close verb refuses a record that is missing, empty or whitespace, and D1
reports the same feature afterwards off the same predicate. These are the cases
where "the record exists" and "the record says something" come apart: a pointer
into a file outside the PM tree, and a symlink that resolves nowhere.
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
from godot_devkit.core.project import load_config, repo_root  # noqa: E402
from godot_devkit.repo.pm import cli as pm_cli  # noqa: E402

FEATURE = 'pm/roadmap/0.1-m/features/f'
REVIEW = f'{FEATURE}/review.md'
DECISIONS = f'{FEATURE}/decisions.md'


def pm(*argv: str) -> tuple[int, str]:
    """One pm command in the cwd repo, with the config caches cleared."""
    repo_root.cache_clear()
    load_config.cache_clear()
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = pm_cli.main(list(argv))
    return code, out.getvalue() + err.getvalue()


@contextlib.contextmanager
def tree(config: str = ''):
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / 'repo'
        root.mkdir()
        if config:
            (root / 'devkit.toml').write_text(config, encoding='utf-8')
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


def _feature_at_review(root: Path) -> None:
    for argv in (('init',),
                 ('new', 'milestone', '0.1', 'M'),
                 ('new', 'feature', '0.1', 'f', 'F'),
                 ('new', 'story', '0.1/f', '01-s', 'S'),
                 ('story', 'wip', '0.1/f/01-s'),
                 ('story', 'review', '0.1/f/01-s'),
                 ('feature', 'ready', '0.1/f'),
                 ('feature', 'building', '0.1/f'),
                 ('feature', 'review', '0.1/f')):
        code, out = pm(*argv)
        assert code == 0, f'{argv}: {out}'
    with (root / REVIEW).open('a', encoding='utf-8') as fh:
        fh.write('\na finding with enough content to be substantive\n')


def test_the_durable_decision_log_closes_the_feature():
    """The model the tool now enforces, end to end."""
    with tree() as root:
        _feature_at_review(root)
        code, out = pm('decide', '0.1/f', '--title', 'the thing',
                       '--chose', 'A', '--over', 'B', '--because', 'C',
                       '--evidence', 'abc1234')
        assert code == 0, out
        code, out = pm('feature', 'done', '0.1/f', '--review-record', DECISIONS)
        assert code == 0, out
        assert 'status: done' in (root / FEATURE / 'feature.md').read_text(
            encoding='utf-8')


def test_a_durable_record_outside_the_tree_is_still_accepted():
    """No regression for a project that keeps records in docs/reviews/.

    The refusal is aimed at ONE named slot, not at review records generally —
    a rule that widened to any file called review anything would break a
    consumer that had done nothing wrong.
    """
    with tree('[pm]\nreview_dir = "docs/reviews"\n') as root:
        _feature_at_review(root)
        record = root / 'docs' / 'reviews' / '0.1-f.md'
        record.parent.mkdir(parents=True)
        record.write_text('a durable review record with real content\n',
                          encoding='utf-8')
        code, out = pm('feature', 'done', '0.1/f',
                       '--review-record', 'docs/reviews/0.1-f.md')
        assert code == 0, out


def test_a_dangling_symlink_is_judged_without_raising():
    """D11 leaves a dangling link behind, so the resolver meets one. A path
    that resolves nowhere is not the transient slot and is not a crash."""
    with tree() as root:
        _feature_at_review(root)
        (root / FEATURE / 'gone.md').symlink_to('nowhere.md')
        code, out = pm('feature', 'done', '0.1/f',
                       '--review-record', f'{FEATURE}/gone.md')
    assert code == 1, out
    assert 'missing/empty/whitespace' in out, out
