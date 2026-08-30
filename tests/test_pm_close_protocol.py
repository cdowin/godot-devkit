"""test_pm_close_protocol.py — what `pm feature done` accepts as a review record.

ONE question: does the pointer RESOLVE. The close verb refuses a `--review-record`
naming no file, and D1 reports a `reviewed:` that resolves to nothing, off the
same predicate. There used to be a byte floor under it and it refused an honest
15-byte "LGTM. Ship it." — the tool judging whether a human's prose was long
enough, which is not a fact about anything.
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
    """A `reviewed:` pointer can outlive what it points at. A path that
    resolves nowhere names no file, and that is a refusal, not a crash."""
    with tree() as root:
        _feature_at_review(root)
        (root / FEATURE / 'gone.md').symlink_to('nowhere.md')
        code, out = pm('feature', 'done', '0.1/f',
                       '--review-record', f'{FEATURE}/gone.md')
    assert code == 1, out
    assert 'names no file' in out, out


def test_a_fifteen_byte_record_closes_the_feature():
    """The measurement that removed the floor: `review_min_content_bytes = 20`
    refused this exact string. Whether a one-line close is enough review is the
    reviewer's call, and it was never a fact about the tree."""
    with tree() as root:
        _feature_at_review(root)
        record = root / 'docs' / 'reviews' / 'f.md'
        record.parent.mkdir(parents=True)
        record.write_text('LGTM. Ship it.', encoding='utf-8')
        code, out = pm('feature', 'done', '0.1/f',
                       '--review-record', 'docs/reviews/f.md')
        assert code == 0, out
        assert 'status: done' in (root / FEATURE / 'feature.md').read_text(
            encoding='utf-8')


def test_a_feature_with_no_record_at_all_still_closes():
    """"You have not written a review record yet" is an opinion about how a
    person should work, not a fact about the tree — and D1 no longer reports
    the absence either. A DANGLING pointer is still both."""
    with tree() as root:
        _feature_at_review(root)
        code, out = pm('feature', 'done', '0.1/f')
        assert code == 0, out
        assert 'no review record' in out, out
        assert 'status: done' in (root / FEATURE / 'feature.md').read_text(
            encoding='utf-8')
