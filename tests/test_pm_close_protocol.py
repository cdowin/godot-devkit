"""test_pm_close_protocol.py — the defect closing a real milestone found.

A protocol gap, not a code bug: a rule demanding something no verb could do,
resolved by a human who happened to know which rule to break.

`pm feature done --review-record <path>` stamped `reviewed:` at whatever it was
handed, including a grain's transient `review.md` — which D11 then requires a
`done` grain not to have. Delete it exactly as the protocol says and the feature
is `done w/o review record`. Both rules could not hold.

Every test here fails against the commit before this one.
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


def test_a_record_pointing_at_the_transient_slot_is_refused():
    with tree() as root:
        _feature_at_review(root)
        before = (root / FEATURE / 'feature.md').read_bytes()
        code, out = pm('feature', 'done', '0.1/f', '--review-record', REVIEW)
    assert code == 1, out
    assert 'TRANSIENT' in out
    # The repair, named: which file, and the command that fills it.
    assert DECISIONS in out
    assert 'pm decide 0.1/f' in out
    # A refused close leaves feature.md byte-identical — never a stale stamp.
    assert (root / FEATURE / 'feature.md').read_bytes() == before \
        if (root / FEATURE / 'feature.md').exists() else True


def test_the_refusal_leaves_feature_md_byte_identical():
    with tree() as root:
        _feature_at_review(root)
        ffile = root / FEATURE / 'feature.md'
        before = ffile.read_bytes()
        pm('feature', 'done', '0.1/f', '--review-record', REVIEW)
        assert ffile.read_bytes() == before


def test_a_standing_reviewed_pointer_at_the_slot_is_refused_too():
    """The same defect by the other door: a hand-edited `reviewed:` line.

    Refused BEFORE the story cascade, so a tree that reaches this state by hand
    cannot be closed halfway into it.
    """
    with tree() as root:
        _feature_at_review(root)
        ffile = root / FEATURE / 'feature.md'
        ffile.write_text(
            ffile.read_text(encoding='utf-8')
            .replace('reviewed:', f'reviewed: {REVIEW}', 1), encoding='utf-8')
        code, out = pm('feature', 'done', '0.1/f')
        assert code == 1, out
        assert 'TRANSIENT' in out
        story = next((root / FEATURE / 'stories').glob('*.md'))
        assert 'status: review' in story.read_text(encoding='utf-8')


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


# --- nit: the transient-slot refusal was bypassable by a symlink --------------
def test_a_symlink_under_another_name_is_still_the_transient_slot():
    """`durable.md -> review.md` is review.md wearing a hat. D11 deletes what
    the link points at, and the pointer strands identically."""
    with tree() as root:
        _feature_at_review(root)
        link = root / FEATURE / 'durable.md'
        link.symlink_to('review.md')
        code, out = pm('feature', 'done', '0.1/f',
                       '--review-record', f'{FEATURE}/durable.md')
    assert code == 1, out
    assert 'TRANSIENT' in out, out


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
