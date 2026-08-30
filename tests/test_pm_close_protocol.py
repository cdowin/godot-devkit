"""test_pm_close_protocol.py — the two defects closing a real milestone found.

Both were protocol gaps, not code bugs, and both had the same shape: a rule
demanding something no verb could do, resolved by a human who happened to know
which rule to break.

  1. `pm feature done --review-record <path>` stamped `reviewed:` at whatever it
     was handed, including a grain's transient `review.md` — which D11 then
     requires a `done` grain not to have. Delete it exactly as the protocol says
     and the feature is `done w/o review record`. Both rules could not hold.
  2. D18 requires a `done` milestone to collapse its raw decision trail to
     pointers, and `decisions.md` is append-only and written only by
     `pm decide` — so the collapse existed only as a hand edit of a file whose
     first line says never by hand.

Every test here fails against the commit before this one.
"""
from __future__ import annotations

import contextlib
import io
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from support import REPO_ROOT  # noqa: E402

sys.path.insert(0, str(REPO_ROOT / 'src'))
from godot_devkit.core.project import load_config, repo_root  # noqa: E402
from godot_devkit.repo.checks import pm as check_pm  # noqa: E402
from godot_devkit.repo.pm import cli as pm_cli  # noqa: E402

FEATURE = 'pm/roadmap/0.1-m/features/f'
MILESTONE_LOG = 'pm/roadmap/0.1-m/decisions.md'
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


# --- defect 1: the pointer and the retention rule contradicted ----------------
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


# --- defect 2: D18 demanded a collapse there was no verb for ------------------
DEVKIT_D18 = '[pm]\nchecks = ["D18"]\n'


def commit(root: Path, message: str = 'the trail') -> None:
    """Commit everything. `pm collapse` REFUSES an uncommitted log — the pointer
    it writes says the full text is in git history, and that is what makes the
    sentence true — so a fixture that wants a collapse has to have committed."""
    subprocess.run(['git', 'add', '-A'], cwd=root, check=True)
    subprocess.run(['git', '-c', 'user.email=t@example', '-c', 'user.name=t',
                    'commit', '-qm', message], cwd=root, check=True)


def _closed_milestone_with_a_trail(root: Path, entries: int = 12) -> None:
    for argv in (('init',), ('new', 'milestone', '0.1', 'M')):
        assert pm(*argv)[0] == 0
    for n in range(1, entries + 1):
        code, out = pm('decide', '0.1', '--title', f'choice number {n}',
                       '--chose', f'option {n}', '--over', f'option other {n}',
                       '--because', f'reason number {n} is that it works',
                       '--evidence', f'abc123{n}')
        assert code == 0, out
    for argv in (('milestone', 'ready', '0.1'),
                 ('milestone', 'building', '0.1'),
                 ('milestone', 'done', '0.1')):
        code, out = pm(*argv)
        assert code == 0, out
    commit(root)


def _d18() -> tuple[int, str]:
    repo_root.cache_clear()
    load_config.cache_clear()
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        code = check_pm.run()
    return code, buffer.getvalue()


def test_collapse_takes_a_closed_log_from_d18_failing_to_d18_passing():
    """The probe perturbs: D18 FAILS first, and the same gate PASSES after.

    Asserting only the second half would pass against a gate that never fires.
    """
    with tree(DEVKIT_D18) as root:
        _closed_milestone_with_a_trail(root)
        code, out = _d18()
        assert code == 1 and 'CLOSED-LOG' in out, out

        code, out = pm('collapse', '0.1', '--keep', 'D3,D7',
                       '--note', 'Two remain because a consumer hits them.')
        assert code == 0, out

        body = (root / MILESTONE_LOG).read_text(encoding='utf-8')
        assert 'Collapsed at close' in body
        # Every collapsed id is NAMED, so nothing goes missing quietly.
        for eid in ('D1', 'D2', 'D12'):
            assert eid in body
        # The kept entries survive verbatim, fields and all.
        assert '**Because:** reason number 3 is that it works' in body
        assert '**Because:** reason number 1 is that it works' not in body
        # The mandated header and the slot's own preamble are not trail.
        assert body.startswith('Append with')

        code, out = _d18()
        assert code == 0, out


def test_collapse_is_idempotent():
    with tree(DEVKIT_D18) as root:
        _closed_milestone_with_a_trail(root)
        assert pm('collapse', '0.1', '--keep', 'D3')[0] == 0
        once = (root / MILESTONE_LOG).read_bytes()
        code, out = pm('collapse', '0.1', '--keep', 'D3')
        assert code == 0 and 'already collapsed' in out
        assert (root / MILESTONE_LOG).read_bytes() == once


def test_collapse_refuses_an_open_milestone():
    with tree(DEVKIT_D18) as root:
        assert pm('init')[0] == 0
        assert pm('new', 'milestone', '0.1', 'M')[0] == 0
        assert pm('decide', '0.1', '--title', 't', '--chose', 'A',
                  '--over', 'B', '--because', 'C', '--evidence', 'abc1234')[0] == 0
        before = (root / MILESTONE_LOG).read_bytes()
        code, out = pm('collapse', '0.1')
        assert code == 1 and 'CLOSE step' in out, out
        assert (root / MILESTONE_LOG).read_bytes() == before


def test_collapse_refuses_an_unknown_keep_id_without_writing():
    with tree(DEVKIT_D18) as root:
        _closed_milestone_with_a_trail(root)
        before = (root / MILESTONE_LOG).read_bytes()
        code, out = pm('collapse', '0.1', '--keep', 'D3,D99')
        assert code == 1 and 'D99' in out
        assert (root / MILESTONE_LOG).read_bytes() == before


def test_collapse_refuses_to_emit_a_file_its_own_rule_would_still_fail():
    """Gate-clean by construction, or refused. The output is never half-done."""
    with tree(DEVKIT_D18) as root:
        _closed_milestone_with_a_trail(root)
        before = (root / MILESTONE_LOG).read_bytes()
        code, out = pm('collapse', '0.1', '--keep', 'D1,D2,D3,D4,D5,D6,D7',
                       '--note', 'padding. ' * 200)
        assert code == 1 and 'close budget' in out, out
        assert (root / MILESTONE_LOG).read_bytes() == before


def test_collapse_refuses_a_feature_log():
    with tree(DEVKIT_D18) as root:
        _closed_milestone_with_a_trail(root)
        code, out = pm('collapse', '0.1/f')
        assert code == 1 and 'MILESTONE log' in out, out


# --- defect 3: the collapse destroyed prose and lied about where it went ------
# `pm collapse` rewrites an append-only log, deleting the text of every entry it
# retires, and writes a pointer saying "the full text is in git history (`git
# log -p` on this file)". On an UNCOMMITTED log that sentence is false and the
# prose is gone for good — measured, on the tree these fixtures build: 328 bytes
# deleted, `git log -p` hits: 0. `pm prune` has refused a dirty tree since it
# shipped, with a comment naming this exact anti-pattern ("a destructive command
# lying about recoverability"); this is the same guard on the other destructive
# verb, scoped to the one file it is about to rewrite.
def _uncommitted_trail(root: Path) -> bytes:
    """A closed milestone whose decisions.md has never been committed."""
    for argv in (('init',), ('new', 'milestone', '0.1', 'M')):
        assert pm(*argv)[0] == 0
    for n in range(1, 6):
        assert pm('decide', '0.1', '--title', f'choice number {n}',
                  '--chose', f'option {n}', '--over', f'option other {n}',
                  '--because', f'reason number {n} is that it works',
                  '--evidence', f'abc123{n}')[0] == 0
    for argv in (('milestone', 'ready', '0.1'),
                 ('milestone', 'building', '0.1'),
                 ('milestone', 'done', '0.1')):
        assert pm(*argv)[0] == 0
    return (root / MILESTONE_LOG).read_bytes()


def test_collapse_refuses_an_uncommitted_log_and_leaves_it_byte_identical():
    with tree(DEVKIT_D18) as root:
        before = _uncommitted_trail(root)
        code, out = pm('collapse', '0.1', '--keep', 'D2')
        assert code == 1, out
        assert (root / MILESTONE_LOG).read_bytes() == before
        # The prose the collapse would have deleted is still here.
        assert b'reason number 4 is that it works' in before
        # And the refusal names the repair, not just the problem.
        assert 'git add' in out and 'git commit' in out, out
        assert 'left untouched' in out, out


def test_collapse_refuses_a_TRACKED_log_with_uncommitted_changes():
    """The protocol's normal state: `pm decide` runs, then `pm collapse`. The
    new entry is exactly the text a collapse would delete before git saw it."""
    with tree(DEVKIT_D18) as root:
        _closed_milestone_with_a_trail(root, entries=5)
        assert pm('decide', '0.1', '--title', 'promoted from the review',
                  '--chose', 'the durable half', '--over', 'the review.md',
                  '--because', 'D11 deletes the transient slot at close',
                  '--evidence', 'abc1234')[0] == 0
        before = (root / MILESTONE_LOG).read_bytes()
        code, out = pm('collapse', '0.1', '--keep', 'D2')
        assert code == 1, out
        assert 'uncommitted changes' in out, out
        assert (root / MILESTONE_LOG).read_bytes() == before
        assert b'D11 deletes the transient slot at close' in before


def test_collapse_proceeds_once_the_log_is_committed():
    """The other half of the same probe: the guard is a precondition, not a
    ban. Committing the file is what makes the pointer's claim true."""
    with tree(DEVKIT_D18) as root:
        _uncommitted_trail(root)
        assert pm('collapse', '0.1', '--keep', 'D2')[0] == 1
        commit(root)
        code, out = pm('collapse', '0.1', '--keep', 'D2')
        assert code == 0, out
        body = (root / MILESTONE_LOG).read_text(encoding='utf-8')
        assert 'reason number 4 is that it works' not in body
        # The pointer's claim, verified against git rather than trusted.
        history = subprocess.run(
            ['git', 'log', '-p', '--', MILESTONE_LOG], cwd=root,
            capture_output=True, text=True).stdout
        assert history.count('reason number 4 is that it works') >= 1


def test_a_dirty_UNRELATED_file_does_not_block_the_collapse():
    """File-scoped on purpose, where prune's check is whole-tree. The close
    protocol collapses with milestone.md and changelog.md legitimately dirty; a
    whole-tree check would refuse the protocol's normal state, and a gate that
    fires on normal operation is one people learn to route around."""
    with tree(DEVKIT_D18) as root:
        _closed_milestone_with_a_trail(root, entries=5)
        (root / 'unrelated.md').write_text('work in progress\n', encoding='utf-8')
        code, out = pm('collapse', '0.1', '--keep', 'D2')
    assert code == 0, out


# --- defect 4: the next decide re-minted a collapsed id -----------------------
# Observed: a pointer reading `… D1, D3, D4, D5 — collapsed` with a freshly
# minted `## D3` three lines under it. One file, two different D3s, and
# `check pm` PASSED throughout because a pointer is prose.
def test_decide_after_a_collapse_never_re_mints_a_retired_id():
    with tree(DEVKIT_D18) as root:
        _closed_milestone_with_a_trail(root, entries=5)
        assert pm('collapse', '0.1', '--keep', 'D2')[0] == 0
        code, out = pm('decide', '0.1', '--title', 'a later decision',
                       '--chose', 'X', '--over', 'Y', '--because', 'Z',
                       '--evidence', 'abc1234')
        assert code == 0, out
        assert ': D6 —' in out, out
        body = (root / MILESTONE_LOG).read_text(encoding='utf-8')
        assert body.count('## D3 ') == 0, body


def test_a_FULLY_collapsed_log_allocates_past_every_retired_id():
    """The worse half of the same defect: with nothing left in the file, the
    allocator restarted at D1 — colliding with all five at once."""
    with tree(DEVKIT_D18) as root:
        _closed_milestone_with_a_trail(root, entries=5)
        assert pm('collapse', '0.1', '--keep', 'D5')[0] == 0
        # D5 is the only entry left; retire it too, by hand-free means: a
        # second collapse of the remaining trail.
        commit(root, 'the first collapse')
        assert pm('collapse', '0.1')[0] == 0
        body = (root / MILESTONE_LOG).read_text(encoding='utf-8')
        assert '## D' not in body, body
        code, out = pm('decide', '0.1', '--title', 'after everything',
                       '--chose', 'X', '--over', 'Y', '--because', 'Z',
                       '--evidence', 'abc1234')
        assert code == 0, out
        assert ': D6 —' in out, out


def test_the_gate_reports_a_re_minted_id_rather_than_passing_over_prose():
    """The hand-edited route in. A human appending `## D3` under a pointer that
    retired D3 gets a finding, where every check used to read one entry and one
    paragraph and say nothing."""
    with tree('[pm]\nchecks = ["D12", "D18"]\n') as root:
        _closed_milestone_with_a_trail(root, entries=5)
        assert pm('collapse', '0.1', '--keep', 'D2')[0] == 0
        code, out = _d18()
        assert code == 0, out
        with (root / MILESTONE_LOG).open('a', encoding='utf-8') as fh:
            fh.write('\n## D3 — 2026-08-29 — a hand written duplicate\n'
                     '**Chose:** A\n**Over:** B\n**Because:** C\n'
                     '**Evidence:** abc1234\n')
        code, out = _d18()
    assert code == 1, out
    assert 'D3 is minted twice' in out, out


def test_a_pointer_with_no_id_list_refuses_the_append_rather_than_guessing():
    """Degrade safely. A hand-written pointer that records nothing cannot tell
    the allocator which ids are spent, and guessing there is the silent
    re-mint this whole guard exists to stop."""
    with tree(DEVKIT_D18) as root:
        _closed_milestone_with_a_trail(root, entries=5)
        assert pm('collapse', '0.1', '--keep', 'D2')[0] == 0
        log = root / MILESTONE_LOG
        # Strip the labelled slot out of the pointer, leaving the prose — which
        # is what a hand-written pointer looks like.
        stripped = re.sub(r'Ids spent[^.]*\.', '', log.read_text(encoding='utf-8'),
                          flags=re.S)
        log.write_text(stripped, encoding='utf-8')
        assert 'Ids spent' not in stripped
        before = log.read_bytes()
        code, out = pm('decide', '0.1', '--title', 'a later decision',
                       '--chose', 'X', '--over', 'Y', '--because', 'Z',
                       '--evidence', 'abc1234')
        assert code == 1, out
        assert 'Ids spent' in out and 'no' in out, out
        assert log.read_bytes() == before


def test_a_rule_id_quoted_in_the_pointer_prose_is_not_a_retired_entry():
    """The first cut of the id parse read the whole pointer and took `D16's
    separation from D15` — two RULE names in this repo's own hand-written
    pointer — as two retired entries. Ids are read from a labelled slot."""
    from godot_devkit.repo.pm import model
    text = ('Collapsed at close. D16\'s separation from D15 is described '
            'here.\n\n## D1 — 2026-08-29 — t\n**Chose:** a\n')
    ids, defects = model.spent_entry_ids(text)
    assert ids == set(), ids
    assert defects and 'Ids spent' in defects[0], defects


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
