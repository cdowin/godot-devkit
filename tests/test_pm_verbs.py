"""The pm verbs over the tree — status moves, close, retire, move, decide,
and the read/write verbs beside them (list/status/get/set/sync/vocabulary).

Split from test_pm.py by concern; the shared tree/run_cli/run_gate harness is
tests/support/pm.py. The refusal contract pinned throughout: a refused write
leaves the grain byte-identical — a half-applied cascade is worse than no
cascade.
"""
from __future__ import annotations

import contextlib
import os
import subprocess
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from support.pm import (
    CASE_SENSITIVE_TMP,
    STORY_REL,
    cfg_for,
    run_cli,
    run_gate,
    tree,
    write,
)

from godot_devkit.repo.pm import cli, model, skills, templates

class ReviewRecord(unittest.TestCase):
    """ONE question: does the pointer RESOLVE.

    There used to be a `review_min_content_bytes = 20` floor under it, and it
    refused an honest 15-byte "LGTM. Ship it.". How much a reviewer needed to
    write is not a fact about the tree; whether the file they named is there
    is, and it is the same fact V4 checks for `depends_on`.
    """

    def test_a_missing_target_is_not_a_record(self):
        with tree(with_record=True) as root:
            cfg = cfg_for(root)
            (root / 'docs' / 'reviews' / 'alpha.md').unlink()
            self.assertIsNone(model.review_record_for(cfg, '0.1/alpha'))

    def test_an_EMPTY_file_is_a_record(self):
        # The tool has no opinion about how much is enough. An empty file is a
        # file, and the person who wrote it decided what belonged in it.
        with tree(with_record=True) as root:
            (root / 'docs' / 'reviews' / 'alpha.md').write_text('', encoding='utf-8')
            self.assertIsNotNone(model.review_record_for(cfg_for(root), '0.1/alpha'))

    def test_a_one_line_record_counts(self):
        with tree(with_record=True) as root:
            self.assertIsNotNone(model.review_record_for(cfg_for(root), '0.1/alpha'))


class StatusMoves(unittest.TestCase):
    """The verb writes a `status:`. It does not own a transition graph.

    The graph it replaced claimed, in this repo's own README, "transitions no
    one can hand-edit around". Proven false: a `sed` of the `status:` line
    reaches the exact state the CLI refused, and `check pm` then prints PASS,
    because nothing checks an EDGE — D3/D4/D5 check the tree's END STATE. So
    the graph taxed whoever used the sanctioned tool and stopped nobody else.
    `test_a_hand_edit_reaches_what_the_cli_refused` below is that proof, kept.

    The four shapes every status verb shares live in `StatusVerbQuartet`;
    this class keeps only the story-specific proofs.
    """

    def test_a_hand_edit_reaches_what_the_cli_refused_and_the_gate_still_says_PASS(self):
        # The measurement that removed the graph, kept as the reason. A
        # `status:` line rewritten by hand lands a story at `done` under a DONE
        # feature — a state the old graph refused from `todo` — and every rule
        # that reads an END STATE is satisfied by it.
        with tree(milestone_status='done', feature_status='done',
                  story_statuses=('todo',)) as root:
            sf = root / STORY_REL
            sf.write_text(sf.read_text(encoding='utf-8')
                          .replace('status: todo', 'status: done'),
                          encoding='utf-8')
            code, out = run_gate(root)
            self.assertEqual(code, 0, out)

    def test_the_END_STATE_is_still_gated(self):
        # Report, do not refuse: a done story under a live feature is D5's
        # finding whether the CLI or an editor put it there.
        with tree(feature_status='building', story_statuses=('todo',)) as root:
            self.assertEqual(run_cli(root, 'story', 'done', '0.1/alpha/s0')[0], 0)
            code, out = run_gate(root)
            self.assertEqual(code, 1, out)
            self.assertIn('two places in this tree disagree', out)

    def test_feature_review_REPORTS_unfinished_stories_and_still_moves(self):
        # It used to refuse: "a feature cannot be under review while its own
        # work is unfinished" is a claim about how a team works. Which stories
        # are where is a fact, and it belongs in the output, not in a veto.
        with tree(story_statuses=('review', 'wip')) as root:
            code, out = run_cli(root, 'feature', 'review', '0.1/alpha')
            self.assertEqual(code, 0, out)
            self.assertIn('not at review', out)
            self.assertIn('s1.md(wip)', out)
            self.assertEqual(
                model.field_of(root / 'pm/roadmap/0.1-demo/features/alpha/feature.md',
                               'status'), 'review')

    def test_milestone_done_REPORTS_live_features_and_still_moves(self):
        with tree(feature_status='building') as root:
            code, out = run_cli(root, 'milestone', 'done', '0.1')
            self.assertEqual(code, 0, out)
            self.assertIn('feature(s) not done', out)
            self.assertIn('alpha(building)', out)
            self.assertEqual(
                model.field_of(root / 'pm/roadmap/0.1-demo/milestone.md',
                               'status'), 'done')
            # ...and D3 asks the same question of the tree it left behind.
            code, out = run_gate(root)
            self.assertEqual(code, 1, out)
            self.assertIn('is done but feature 0.1/alpha', out)

    def test_milestone_done_records_no_date_of_its_own(self):
        """Close flips the status and stops. Git already records the WHEN.

        `actual_date:` was stamped here for one reader — the changelog render —
        and outlived it. A stamp nothing reads is a field every consumer's tree
        carries and no consumer can act on, so the close writes `status` and
        nothing else.
        """
        with tree(feature_status='done', story_statuses=('done',)) as root:
            mf = root / 'pm/roadmap/0.1-demo/milestone.md'
            code, out = run_cli(root, 'milestone', 'done', '0.1')
            self.assertEqual(code, 0, out)
            self.assertEqual(model.field_of(mf, 'status'), 'done')
            # The whole file, not just the parsed field: a re-added EMPTY
            # `actual_date:` parses as absent and would slip a reader-less
            # field back into every consumer's tree in silence.
            self.assertNotIn('actual_date', mf.read_text(encoding='utf-8'))
            self.assertNotIn('actual_date', out)

    def test_a_scaffolded_milestone_mints_no_actual_date(self):
        """The template is the other half: nothing stamps it, nothing mints it.

        Stopping the stamp while the template still minted the field would
        leave every new milestone carrying an empty slot that is now, by
        construction, never filled.
        """
        with tree() as root:
            code, out = run_cli(root, 'new', 'milestone', '0.2', 'Second')
            self.assertEqual(code, 0, out)
            minted = next(
                (root / 'pm/roadmap').glob('0.2*/milestone.md'), None)
            self.assertIsNotNone(minted, sorted(
                p.name for p in (root / 'pm/roadmap').iterdir()))
            self.assertNotIn('actual_date',
                             minted.read_text(encoding='utf-8'))


class StatusVerbQuartet(unittest.TestCase):
    """The four shapes every status verb shares, once per grain KIND.

    Every vocabulary state reachable / an out-of-vocabulary target a usage
    error naming the set / the flip an idempotent no-op / an id resolving to
    nothing exit 2. One parameterized home instead of a per-grain mirror; each
    grain's UNIQUE guards stay with their grain — `StatusMoves` keeps the
    story hand-edit measurement, `BugStatus` the `/bugs/` cross-grain guard
    and nested-id resolution, `FeatureClose` the close protocol.

    `feature done` is deliberately exercised through the full close here (it
    dispatches to the cascade — there is no "just write the field" spelling),
    which is why the fixture carries a review record and a done story.
    """

    # (kind, grain id, status-file path, initial state, unresolvable id)
    GRAINS = (
        ('story', '0.1/alpha/s0', STORY_REL, 'done', '0.1/alpha/nope'),
        ('bug', '0.1/bugs/seed-is-zero',
         'pm/roadmap/0.1-demo/bugs/seed-is-zero.md', 'open', '0.1/bugs/nope'),
        ('feature', '0.1/alpha',
         'pm/roadmap/0.1-demo/features/alpha/feature.md', 'building',
         '0.1/nope'),
        ('milestone', '0.1', 'pm/roadmap/0.1-demo/milestone.md', 'building',
         '9.9'),
    )

    @staticmethod
    def _states(kind: str) -> tuple[str, ...]:
        return getattr(model, f'DEFAULT_{kind.upper()}_STATES')

    @staticmethod
    @contextlib.contextmanager
    def _grain_tree(kind: str):
        with tree(story_statuses=('done',)) as root:
            if kind == 'bug':
                write(root / 'pm/roadmap/0.1-demo/bugs/seed-is-zero.md',
                      {'id': '0.1/bugs/seed-is-zero', 'milestone': '"0.1"',
                       'status': 'open'})
            yield root

    def test_any_state_in_the_vocabulary_is_reachable(self):
        for kind, gid, rel, _, _ in self.GRAINS:
            for state in self._states(kind):
                with self.subTest(kind=kind, state=state), \
                        self._grain_tree(kind) as root:
                    code, out = run_cli(root, kind, state, gid)
                    self.assertEqual(code, 0, out)
                    self.assertEqual(
                        model.field_of(root / rel, 'status'), state)

    def test_a_state_outside_the_vocabulary_is_a_usage_error_naming_the_set(self):
        # The half that IS a fact: `banana` is not a status in any vocabulary.
        for kind, gid, rel, initial, _ in self.GRAINS:
            with self.subTest(kind=kind), self._grain_tree(kind) as root:
                code, out = run_cli(root, kind, 'banana', gid)
                self.assertEqual(code, 2, out)
                self.assertIn(f'is not a {kind} status', out)
                for state in self._states(kind):
                    self.assertIn(state, out)
                self.assertEqual(model.field_of(root / rel, 'status'), initial)

    def test_idempotent_noop_succeeds(self):
        for kind, gid, _, initial, _ in self.GRAINS:
            with self.subTest(kind=kind), self._grain_tree(kind) as root:
                code, out = run_cli(root, kind, initial, gid)
                self.assertEqual(code, 0, out)
                self.assertIn('no-op', out)

    def test_unresolvable_id_is_a_usage_error(self):
        for kind, _, _, initial, bad in self.GRAINS:
            with self.subTest(kind=kind), self._grain_tree(kind) as root:
                code, _ = run_cli(root, kind, initial, bad)
                self.assertEqual(code, 2)


class FeatureClose(unittest.TestCase):
    def test_done_without_the_flag_leaves_every_story_BYTE_IDENTICAL(self):
        # The default blast radius is the file the caller named. A command
        # aimed at a feature that rewrites three story files is the tool acting
        # on its own initiative.
        with tree(feature_status='review', story_statuses=('review', 'review')) as root:
            sdir = root / 'pm/roadmap/0.1-demo/features/alpha/stories'
            before = {p.name: p.read_bytes() for p in sorted(sdir.iterdir())}
            code, out = run_cli(root, 'feature', 'done', '0.1/alpha')
            self.assertEqual(code, 0, out)
            self.assertEqual(
                model.field_of(root / 'pm/roadmap/0.1-demo/features/alpha/feature.md',
                               'status'), 'done')
            after = {p.name: p.read_bytes() for p in sorted(sdir.iterdir())}
            self.assertEqual(before, after)

    def test_it_REPORTS_the_stories_it_did_not_touch(self):
        with tree(feature_status='review', story_statuses=('review', 'wip')) as root:
            code, out = run_cli(root, 'feature', 'done', '0.1/alpha')
            self.assertEqual(code, 0, out)
            self.assertIn('NOT touched', out)
            self.assertIn('s0.md(review)', out)
            self.assertIn('s1.md(wip)', out)
            self.assertIn('--cascade', out)

    def test_an_unfinished_story_is_reported_never_refused(self):
        with tree(feature_status='review', story_statuses=('wip',)) as root:
            code, out = run_cli(root, 'feature', 'done', '0.1/alpha', '--cascade')
            self.assertEqual(code, 0, out)
            self.assertIn('s0.md(wip)', out)
            self.assertEqual(model.field_of(root / STORY_REL, 'status'), 'wip')

    def test_cascade_closes_stories_and_feature(self):
        with tree(feature_status='review', story_statuses=('review', 'review')) as root:
            code, _ = run_cli(root, 'feature', 'done', '0.1/alpha', '--cascade')
            self.assertEqual(code, 0)
            fdir = root / 'pm/roadmap/0.1-demo/features/alpha'
            self.assertEqual(model.field_of(fdir / 'feature.md', 'status'), 'done')
            for s in (fdir / 'stories').glob('*.md'):
                self.assertEqual(model.field_of(s, 'status'), 'done')

    def test_close_without_a_record_says_so_and_closes(self):
        # "You have not written a review record yet" is an opinion about how a
        # person works. The verb says what it saw and does what it was asked.
        with tree(feature_status='review', story_statuses=('review',),
                  with_record=False) as root:
            code, out = run_cli(root, 'feature', 'done', '0.1/alpha')
            self.assertEqual(code, 0, out)
            self.assertIn('no review record', out)
            self.assertEqual(
                model.field_of(root / 'pm/roadmap/0.1-demo/features/alpha/feature.md',
                               'status'), 'done')

    def test_a_record_pointer_naming_no_file_is_refused_and_writes_nothing(self):
        # The half that IS a fact, and the one D1 reports afterwards: a pointer
        # that resolves to nothing. Refused WHOLE — no stale stamp, no story.
        with tree(feature_status='review', story_statuses=('review',),
                  with_record=False) as root:
            ff = root / 'pm/roadmap/0.1-demo/features/alpha/feature.md'
            story = root / 'pm/roadmap/0.1-demo/features/alpha/stories/s0.md'
            before, sbefore = ff.read_text(), story.read_text()
            code, out = run_cli(root, 'feature', 'done', '0.1/alpha', '--cascade',
                                '--review-record', 'docs/reviews/never-written.md')
            self.assertEqual(code, 1, out)
            self.assertIn('names no file', out)
            self.assertEqual(ff.read_text(), before)
            self.assertEqual(story.read_text(), sbefore)

    def test_cascade_moves_only_the_stories_at_review(self):
        with tree(feature_status='review', story_statuses=('review', 'wip')) as root:
            sdir = root / 'pm/roadmap/0.1-demo/features/alpha/stories'
            wip_before = (sdir / 's1.md').read_bytes()
            code, out = run_cli(root, 'feature', 'done', '0.1/alpha', '--cascade')
            self.assertEqual(code, 0, out)
            self.assertEqual(model.field_of(sdir / 's0.md', 'status'), 'done')
            self.assertEqual((sdir / 's1.md').read_bytes(), wip_before)

    def test_an_unfinished_story_does_not_block_the_close(self):
        # It used to refuse. A feature close is a statement about the feature;
        # what its stories are left holding is D5's question, asked of the tree.
        with tree(feature_status='review', story_statuses=('review', 'todo')) as root:
            code, out = run_cli(root, 'feature', 'done', '0.1/alpha', '--cascade')
            self.assertEqual(code, 0, out)
            self.assertIn('s1.md(todo)', out)

    def test_the_two_step_the_output_recommends_actually_cascades(self):
        # The literal sequence a plain close PRINTS as the remedy: close the
        # feature, read "--cascade closes the ones at `review`", run that. The
        # `review` story has to end up `done`. A second run that answers
        # "already done (no-op)" at exit 0 and writes nothing is the remedy the
        # tool recommended being a silent partial success.
        with tree(feature_status='review',
                  story_statuses=('review', 'todo')) as root:
            sdir = root / 'pm/roadmap/0.1-demo/features/alpha/stories'
            code, first = run_cli(root, 'feature', 'done', '0.1/alpha')
            self.assertEqual(code, 0, first)
            self.assertIn('--cascade closes the ones at `review`', first)
            self.assertEqual(model.field_of(sdir / 's0.md', 'status'), 'review')

            code, second = run_cli(root, 'feature', 'done', '0.1/alpha',
                                   '--cascade')
            self.assertEqual(code, 0, second)
            self.assertEqual(model.field_of(sdir / 's0.md', 'status'), 'done')
            # ...and the story it still did not touch is still reported.
            self.assertIn('s1.md(todo)', second)

    def test_an_already_done_feature_still_reports_what_it_did_not_touch(self):
        # The no-op branch used to swallow the report as well as the cascade,
        # so the second run was quieter than the first about the same tree.
        with tree(feature_status='done', story_statuses=('review', 'todo')) as root:
            code, out = run_cli(root, 'feature', 'done', '0.1/alpha')
            self.assertEqual(code, 0, out)
            self.assertIn('already done (no-op)', out)
            self.assertIn('s0.md(review)', out)
            self.assertIn('s1.md(todo)', out)

    def test_the_second_cascade_run_writes_nothing(self):
        # Rule 3: the same command twice is a no-op the second time.
        with tree(feature_status='review',
                  story_statuses=('review', 'todo')) as root:
            fdir = root / 'pm/roadmap/0.1-demo/features/alpha'
            self.assertEqual(
                run_cli(root, 'feature', 'done', '0.1/alpha', '--cascade')[0], 0)
            settled = {p.name: p.read_bytes()
                       for p in sorted((fdir / 'stories').iterdir())}
            feature_settled = (fdir / 'feature.md').read_bytes()
            code, out = run_cli(root, 'feature', 'done', '0.1/alpha', '--cascade')
            self.assertEqual(code, 0, out)
            self.assertIn('already done (no-op)', out)
            self.assertEqual({p.name: p.read_bytes()
                              for p in sorted((fdir / 'stories').iterdir())},
                             settled)
            self.assertEqual((fdir / 'feature.md').read_bytes(), feature_settled)

    def test_a_durable_decision_log_serves_as_the_review_record(self):
        # The close-protocol model end to end: `pm decide` writes the durable
        # log, and that log IS an acceptable `--review-record`.
        with tree(feature_status='review', story_statuses=('review',),
                  with_record=False) as root:
            code, out = run_cli(root, 'decide', '0.1/alpha', 'ship', 'it')
            self.assertEqual(code, 0, out)
            code, out = run_cli(
                root, 'feature', 'done', '0.1/alpha', '--review-record',
                'pm/roadmap/0.1-demo/features/alpha/decisions.md')
            self.assertEqual(code, 0, out)
            self.assertEqual(
                model.field_of(root / 'pm/roadmap/0.1-demo/features/alpha/feature.md',
                               'status'), 'done')

    def test_a_dangling_symlink_is_judged_without_raising(self):
        # A `--review-record` pointer can outlive what it points at. A path
        # that resolves nowhere names no file — a refusal, not a crash.
        with tree(feature_status='review', story_statuses=('review',),
                  with_record=False) as root:
            fdir = root / 'pm/roadmap/0.1-demo/features/alpha'
            (fdir / 'gone.md').symlink_to('nowhere.md')
            code, out = run_cli(
                root, 'feature', 'done', '0.1/alpha', '--review-record',
                'pm/roadmap/0.1-demo/features/alpha/gone.md')
            self.assertEqual(code, 1, out)
            self.assertIn('names no file', out)

    def test_a_fifteen_byte_record_closes_the_feature(self):
        # The measurement that removed the byte floor:
        # `review_min_content_bytes = 20` refused this exact string. Whether a
        # one-line close is enough review is the reviewer's call, and it was
        # never a fact about the tree.
        with tree(feature_status='review', story_statuses=('review',),
                  with_record=False) as root:
            record = root / 'docs' / 'reviews' / 'f.md'
            record.parent.mkdir(parents=True)
            record.write_text('LGTM. Ship it.', encoding='utf-8')
            code, out = run_cli(root, 'feature', 'done', '0.1/alpha',
                                '--review-record', 'docs/reviews/f.md')
            self.assertEqual(code, 0, out)
            self.assertEqual(
                model.field_of(root / 'pm/roadmap/0.1-demo/features/alpha/feature.md',
                               'status'), 'done')

    def test_a_record_under_a_custom_review_dir_is_still_accepted(self):
        # The refusal is aimed at ONE named slot, not at review records
        # generally — a rule that widened to any file called review-anything
        # would break a consumer that had done nothing wrong.
        with tree(feature_status='review', story_statuses=('review',),
                  with_record=False) as root:
            (root / 'devkit.toml').write_text(
                '[pm]\nreview_dir = "docs/reviews"\n', encoding='utf-8')
            record = root / 'docs' / 'reviews' / '0.1-alpha.md'
            record.parent.mkdir(parents=True)
            record.write_text('a durable review record with real content\n',
                              encoding='utf-8')
            code, out = run_cli(root, 'feature', 'done', '0.1/alpha',
                                '--review-record', 'docs/reviews/0.1-alpha.md')
            self.assertEqual(code, 0, out)

    def test_a_late_record_on_a_done_feature_still_has_to_resolve(self):
        # The no-op branch stamped `reviewed:` without asking whether the path
        # named a file — the one question a record is ever asked.
        with tree(feature_status='done', story_statuses=('done',),
                  with_record=False) as root:
            ff = root / 'pm/roadmap/0.1-demo/features/alpha/feature.md'
            before = ff.read_text()
            code, out = run_cli(root, 'feature', 'done', '0.1/alpha',
                                '--review-record', 'docs/reviews/never.md')
            self.assertEqual(code, 1, out)
            self.assertIn('names no file', out)
            self.assertEqual(ff.read_text(), before)


class ListFindsTheNail(unittest.TestCase):
    """`pm list` — a filter over facts, and nothing else.

    Measured on one consumer: `pm status` prints 165 lines, and the answer to
    "what is open right now" was 2 stories. `pm list --status wip,review,blocked`
    prints those 2.

    There is deliberately no `pm next`. A verb that picks THE next thing is the
    tool having an opinion about your priorities, which is what this release
    removes everywhere else.
    """

    @staticmethod
    def _rows(out: str) -> list[list[str]]:
        return [line.split('\t') for line in out.strip().split('\n')
                if '\t' in line]

    def _tree(self):
        return tree(story_statuses=('todo', 'wip', 'review', 'done'))

    def test_every_story_one_tab_separated_row(self):
        with self._tree() as root:
            code, out = run_cli(root, 'list')
            self.assertEqual(code, 0, out)
            rows = self._rows(out)
            self.assertEqual(len(rows), 4)
            self.assertEqual(rows[0][0], '0.1/alpha/s0')
            self.assertEqual(rows[0][1], 'todo')
            self.assertEqual(rows[0][3], '0.1/alpha')

    def test_status_filter_narrows_to_what_is_open(self):
        with self._tree() as root:
            code, out = run_cli(root, 'list', '--status', 'wip,review')
            self.assertEqual(code, 0, out)
            self.assertEqual([r[1] for r in self._rows(out)], ['wip', 'review'])
            self.assertIn('2 of 4 story/ies', out)

    def test_owner_filter(self):
        with self._tree() as root:
            self.assertEqual(
                run_cli(root, 'set', '0.1/alpha/s1', 'owner', 'ada')[0], 0)
            code, out = run_cli(root, 'list', '--owner', 'ada')
            self.assertEqual(code, 0, out)
            rows = self._rows(out)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0][2], 'ada')

    def test_milestone_filter(self):
        with self._tree() as root:
            write(root / 'pm/roadmap/0.2-later/milestone.md',
                  {'id': '"0.2"', 'name': 'Later', 'status': 'planning'})
            write(root / 'pm/roadmap/0.2-later/features/beta/feature.md',
                  {'id': '0.2/beta', 'milestone': '"0.2"', 'name': 'Beta',
                   'status': 'planning'})
            write(root / 'pm/roadmap/0.2-later/features/beta/stories/b0.md',
                  {'id': '0.2/beta/b0', 'feature': '0.2/beta',
                   'milestone': '"0.2"', 'name': 'B0', 'status': 'todo'})
            code, out = run_cli(root, 'list', '--milestone', '0.2')
            self.assertEqual(code, 0, out)
            self.assertEqual([r[0] for r in self._rows(out)], ['0.2/beta/b0'])

    def test_a_milestone_that_is_not_in_the_tree_is_a_usage_error(self):
        # `--milestone 0.2` on a tree holding only 0.1 printed `0 of 0` at exit
        # 0 — indistinguishable from a milestone whose stories are all gone,
        # and from a wrong `roadmap_dir`. Milestone ids are enumerable, so the
        # set gets named exactly the way `--status wombat` already names its
        # set.
        with self._tree() as root:
            code, out = run_cli(root, 'list', '--milestone', '0.2')
            self.assertEqual(code, 2, out)
            self.assertIn('--milestone names', out)
            self.assertIn('0.1', out)

    def test_an_empty_tree_says_so_rather_than_naming_an_empty_set(self):
        # Rule 4: refusing against a census of ZERO milestones must not read as
        # "you typo'd" when the truth is "nothing was scanned".
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'repo'
            (root / 'pm' / 'roadmap').mkdir(parents=True)
            subprocess.run(['git', 'init', '-q'], cwd=root, check=True)
            previous = Path.cwd()
            os.chdir(root)
            try:
                code, out = run_cli(root, 'list', '--milestone', '0.1')
            finally:
                os.chdir(previous)
            self.assertEqual(code, 2, out)
            self.assertIn('no milestone at all', out)

    def test_a_status_outside_the_vocabulary_is_a_usage_error(self):
        with self._tree() as root:
            code, out = run_cli(root, 'list', '--status', 'butterfly')
            self.assertEqual(code, 2, out)
            self.assertIn('is not a story status', out)

    def test_matching_nothing_and_scanning_nothing_look_different(self):
        # Rule 4, on a read verb: 0 rows out of 4 stories is an answer; 0 rows
        # out of 0 is a wrong `roadmap_dir`, and the census says which.
        with self._tree() as root:
            _, out = run_cli(root, 'list', '--owner', 'nobody')
            self.assertEqual(self._rows(out), [])
            self.assertIn('0 of 4 story/ies', out)
        with tree(story_statuses=()) as root:
            _, out = run_cli(root, 'list')
            self.assertIn('0 of 0 story/ies', out)

    def test_pm_status_is_untouched(self):
        # Contract stability: `pm list` is additive. `pm status` prints exactly
        # what it printed before, and nothing here may quietly reshape it.
        with self._tree() as root:
            code, out = run_cli(root, 'status')
            self.assertEqual(code, 0, out)
            self.assertIn('milestone 0.1', out)
            self.assertIn('stories 1/4 done', out)
            self.assertNotIn('\t', out)


class StatusReport(unittest.TestCase):
    def test_unphased_milestone_prints_no_bucket_header(self):
        with tree(story_statuses=('todo',)) as root:
            _, out = run_cli(root, 'status')
            self.assertNotIn('--', out)

    def test_phases_group_numeric_then_seam_then_unphased(self):
        with tree(story_statuses=('todo',)) as root:
            run_cli(root, 'new', 'feature', '0.1', 'b', 'B')
            run_cli(root, 'new', 'feature', '0.1', 'c', 'C')
            fdir = root / 'pm/roadmap/0.1-demo/features'
            model.set_field(fdir / 'alpha' / 'feature.md', 'phase', '2')
            model.set_field(fdir / 'b' / 'feature.md', 'phase', 'seam')
            # 'c' stays unphased on purpose.
            _, out = run_cli(root, 'status')
            order = [ln for ln in out.splitlines() if ln.startswith('  --')]
            self.assertEqual(
                order, ['  -- phase 2 (0/1 done)', '  -- seam (0/1 done)',
                        '  -- unphased (0/1 done)'])


class WriteFidelity(unittest.TestCase):
    """Rule 3 — a write verb touches only what it was asked to touch."""

    def test_crlf_survives_a_status_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / 'g.md'
            p.write_bytes(b'---\r\nid: a\r\nstatus: todo\r\n---\r\n\r\nbody\r\n')
            self.assertTrue(model.set_field(p, 'status', 'wip'))
            self.assertEqual(
                p.read_bytes(),
                b'---\r\nid: a\r\nstatus: wip\r\n---\r\n\r\nbody\r\n')

    def test_exotic_body_line_breaks_survive(self):
        # str.splitlines() breaks on U+2028, form feed and a lone CR; joining
        # back on '\n' would rewrite all three. Compare BYTES — read_text() does
        # its own newline translation and would hide exactly this defect.
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / 'g.md'
            body = 'A\u2028B\npage\x0cbreak\ncr-only\rtail\n'
            p.write_text('---\nid: a\nstatus: todo\n---\n\n' + body, encoding='utf-8')
            before = p.read_bytes()
            self.assertTrue(model.set_field(p, 'status', 'wip'))
            self.assertEqual(p.read_bytes(),
                             before.replace(b'status: todo', b'status: wip'))

    def test_an_unwritable_file_reports_failure_instead_of_raising(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / 'g.md'
            write(p, {'id': 'a', 'status': 'todo'})
            p.chmod(0o444)
            try:
                self.assertFalse(model.set_field(p, 'status', 'wip'))
            finally:
                p.chmod(0o644)

    def test_a_mid_cascade_write_failure_aborts_loudly(self):
        with tree(feature_status='review', story_statuses=('review', 'review')) as root:
            sdir = root / 'pm/roadmap/0.1-demo/features/alpha/stories'
            blocked = sorted(sdir.glob('*.md'))[-1]
            blocked.chmod(0o444)
            try:
                code, out = run_cli(root, 'feature', 'done', '0.1/alpha',
                                    '--cascade')
            finally:
                blocked.chmod(0o644)
            # Exit 2 (a tool failure), never 1 (which means "findings"), and it
            # must say how to finish rather than abandoning the user mid-write.
            self.assertEqual(code, 2)
            self.assertIn('re-run', out.lower())


class IdsAreLiterals(unittest.TestCase):
    def test_a_glob_never_resolves_to_a_grain(self):
        with tree() as root:
            for bad in ('*', '0.?', '0.1/*'):
                with self.subTest(bad=bad):
                    self.assertEqual(run_cli(root, 'milestone', 'ready', bad)[0], 2)


def _phased(root: Path, slug: str, phase: str, deps: list[str]) -> None:
    """One feature under 0.1 with a `phase:` and a `depends_on:` list."""
    write(root / f'pm/roadmap/0.1-demo/features/{slug}/feature.md',
          {'id': f'0.1/{slug}', 'milestone': '"0.1"', 'name': slug.title(),
           'status': 'planning', 'phase': phase,
           'depends_on': '[' + ', '.join(f'"{d}"' for d in deps) + ']'})


class PhaseIsABucketNotAConstraint(unittest.TestCase):
    """V5b is gone. A cycle is a fact; a bucket disagreeing with the graph is not.

    "A feature may not depend on one in a LATER phase" fired on `seam` — a
    vocabulary this tool invented, defined as neither blocking nor blocked, and
    then reported for sitting in a dependency chain. `phase:` groups the board
    for `pm status`; the dependency graph orders the work. They are allowed to
    be two different readings of the same tree.
    """

    def test_a_numeric_phase_may_depend_on_a_LATER_one(self):
        with tree() as root:
            _phased(root, 'alpha', '2', ['0.1/beta'])
            _phased(root, 'beta', '5', [])
            code, out = run_cli(root, 'validate')
            self.assertEqual(code, 0, out)

    def test_a_numeric_phase_may_depend_on_an_unordered_one(self):
        with tree() as root:
            _phased(root, 'alpha', '1', ['0.1/seamy'])
            _phased(root, 'seamy', 'seam', [])
            code, out = run_cli(root, 'validate')
            self.assertEqual(code, 0, out)

    def test_a_CYCLE_is_still_a_finding(self):
        # V5a survives: a loop means no build order exists at all.
        with tree() as root:
            _phased(root, 'alpha', '1', ['0.1/beta'])
            _phased(root, 'beta', '1', ['0.1/alpha'])
            code, out = run_cli(root, 'validate')
            self.assertEqual(code, 1, out)
            self.assertIn('dependency CYCLE', out)


class FieldMutation(unittest.TestCase):
    def test_set_and_get_round_trip(self):
        with tree(story_statuses=('todo',)) as root:
            self.assertEqual(
                run_cli(root, 'set', '0.1/alpha/s0', 'estimate', '3d')[0], 0)
            code, out = run_cli(root, 'get', '0.1/alpha/s0', 'estimate')
            self.assertEqual(code, 0)
            self.assertIn('3d', out)

    def test_status_is_not_a_protected_field(self):
        # `status` was refused here because it "has a transition graph behind
        # it". There is no graph, and the refusal never protected anything: the
        # `sed` it pushed people towards is the write this verb does correctly.
        with tree(story_statuses=('todo',)) as root:
            code, out = run_cli(root, 'set', '0.1/alpha/s0', 'status', 'done')
            self.assertEqual(code, 0, out)
            sf = root / 'pm/roadmap/0.1-demo/features/alpha/stories/s0.md'
            self.assertEqual(model.field_of(sf, 'status'), 'done')

    def test_set_moves_owner_in_both_directions(self):
        # `claim`/`release` were fourteen lines calling this with the key
        # hardcoded. One verb, and `owner` is not special among fields.
        with tree(story_statuses=('todo',)) as root:
            sf = root / 'pm/roadmap/0.1-demo/features/alpha/stories/s0.md'
            self.assertEqual(
                run_cli(root, 'set', '0.1/alpha/s0', 'owner', 'dev-1')[0], 0)
            self.assertEqual(model.field_of(sf, 'owner'), 'dev-1')
            self.assertEqual(
                run_cli(root, 'set', '0.1/alpha/s0', 'owner', '')[0], 0)
            self.assertEqual(model.field_of(sf, 'owner'), '')

    def test_every_grain_kind_resolves(self):
        with tree(story_statuses=('todo',)) as root:
            run_cli(root, 'new', 'bug', '0.1', 'oops')
            for gid in ('0.1', '0.1/alpha', '0.1/alpha/s0', '0.1/bugs/oops'):
                with self.subTest(gid=gid):
                    self.assertEqual(run_cli(root, 'set', gid, 'labels', '[]')[0], 0)

    def test_set_replaces_an_existing_field_byte_for_byte(self):
        with tree() as root:
            ff = root / 'pm/roadmap/0.1-demo/features/alpha/feature.md'
            before = ff.read_bytes()
            run_cli(root, 'set', '0.1/alpha', 'name', 'Renamed')
            self.assertEqual(ff.read_bytes(),
                             before.replace(b'name: Alpha', b'name: Renamed'))

    def test_set_inserts_a_missing_field_and_changes_nothing_else(self):
        with tree() as root:
            ff = root / 'pm/roadmap/0.1-demo/features/alpha/feature.md'
            before = ff.read_text().splitlines()
            run_cli(root, 'set', '0.1/alpha', 'risk', 'high')
            after = ff.read_text().splitlines()
            self.assertEqual(len(after), len(before) + 1)
            self.assertIn('risk: high', after)
            self.assertEqual([ln for ln in after if ln != 'risk: high'], before)


class ExecutionList(unittest.TestCase):
    def _validate(self, root):
        from godot_devkit.repo.pm import validate
        return validate.run(model.PmConfig(root=root))

    def test_sync_writes_a_block_and_validate_then_passes(self):
        with tree(story_statuses=('todo',)) as root:
            self.assertEqual(run_cli(root, 'sync')[0], 0)
            mfile = root / 'pm/roadmap/0.1-demo/milestone.md'
            self.assertIn('pm:execution', mfile.read_text())
            self.assertEqual(self._validate(root)[0], [])

    def test_a_tree_with_no_block_is_not_stale(self):
        # The list is opt-in per file; absence is not staleness, or the gate
        # would go red on every tree that never asked for the feature.
        with tree(story_statuses=('todo',)) as root:
            self.assertEqual(self._validate(root)[0], [])
            self.assertEqual(run_cli(root, 'sync', '--check')[0], 0)

    def test_v6_catches_a_stale_list_when_asked_to(self):
        with tree(story_statuses=('todo',)) as root:
            run_cli(root, 'sync')
            run_cli(root, 'new', 'feature', '0.1', 'newcomer', 'Newcomer')
            self.assertTrue(any('stale' in f for f in self._validate(root)[0]))
            self.assertEqual(run_cli(root, 'sync', '--check')[0], 1)
            run_cli(root, 'sync')
            self.assertEqual(run_cli(root, 'sync', '--check')[0], 0)

    def test_v6_is_NOT_in_the_default_roster(self):
        # Demoted, not deleted. A generated VIEW going stale while ordinary work
        # moves the tree is not a defect in the tree, and reddening a commit
        # gate over it makes the ordinary case the exceptional one.
        with tree(story_statuses=('todo',)) as root:
            run_cli(root, 'sync')
            run_cli(root, 'new', 'feature', '0.1', 'newcomer', 'Newcomer')
            code, out = run_gate(root)
            self.assertEqual(code, 0, out)
            self.assertNotIn('stale', out)
            # ...and `pm sync --check` still answers, for anyone who wants it.
            self.assertEqual(run_cli(root, 'sync', '--check')[0], 1)
        self.assertNotIn('V6', model.DEFAULT_CHECKS)
        self.assertIn('V6', model.KNOWN_CHECKS)

    def test_naming_V6_puts_it_back_on_the_gate(self):
        with tree(story_statuses=('todo',)) as root:
            run_cli(root, 'sync')
            run_cli(root, 'new', 'feature', '0.1', 'newcomer', 'Newcomer')
            (root / 'devkit.toml').write_text(
                '[pm]\nchecks = ["V6"]\n', encoding='utf-8')
            code, out = run_gate(root)
            self.assertEqual(code, 1, out)
            self.assertIn('execution list is stale', out)

    def test_order_follows_dependencies_then_name(self):
        with tree() as root:
            for slug in ('aaa', 'zzz'):
                run_cli(root, 'new', 'feature', '0.1', slug, slug.upper())
            fdir = root / 'pm/roadmap/0.1-demo/features'
            # aaa sorts first by name but depends on zzz, so zzz must lead.
            model.set_field(fdir / 'aaa/feature.md', 'depends_on', '["0.1/zzz"]')
            run_cli(root, 'sync')
            block = (root / 'pm/roadmap/0.1-demo/milestone.md').read_text()
            self.assertLess(block.index('`zzz`'), block.index('`aaa`'))
            self.assertIn('after zzz', block)

    def test_sync_is_idempotent(self):
        with tree(story_statuses=('todo',)) as root:
            run_cli(root, 'sync')
            mfile = root / 'pm/roadmap/0.1-demo/milestone.md'
            once = mfile.read_bytes()
            run_cli(root, 'sync')
            self.assertEqual(mfile.read_bytes(), once)

    def test_sync_preserves_the_rest_of_the_file(self):
        with tree() as root:
            mfile = root / 'pm/roadmap/0.1-demo/milestone.md'
            mfile.write_text(mfile.read_text() + '\n## Notes\n\nkeep me\n',
                             encoding='utf-8')
            run_cli(root, 'sync')
            self.assertIn('keep me', mfile.read_text())


class AStatusVerbIsTheREPAIRForWhatD4Reports(unittest.TestCase):
    """The verb validates the state it was ASKED for. Never the one it found.

    Reproduced on a hand-edited tree: `check pm` reported
    `milestone 0.1: status 'wombat' not in (planning ready building done)`,
    and `pm milestone done 0.1` answered
    `ERROR — milestone '0.1' has an unknown current status 'wombat'` and wrote
    nothing. The gate diagnosed the breakage and the verb declined to repair
    it, leaving the editor as the only way out — which is the one thing this
    tool exists to spare a person.

    The current value is read FOR THE MESSAGE. `wombat -> done`.
    """

    NONSENSE = {'milestone': ('pm/roadmap/0.1-demo/milestone.md', '0.1', 'wombat'),
                'feature': ('pm/roadmap/0.1-demo/features/alpha/feature.md',
                            '0.1/alpha', 'hedgehog'),
                'story': (STORY_REL, '0.1/alpha/s0', 'butterfly')}

    def _mangle(self, root: Path, rel: str, value: str) -> Path:
        path = root / rel
        text = path.read_text(encoding='utf-8')
        line = next(l for l in text.split('\n') if l.startswith('status:'))
        path.write_text(text.replace(line, f'status: {value}'), encoding='utf-8')
        return path

    def test_every_grain_kind_is_repairable_from_nonsense(self):
        for grain, (rel, gid, junk) in self.NONSENSE.items():
            # A milestone close still asks its features to be done (that
            # precondition is a separate question); the fixture satisfies it so
            # this case isolates the one being asked here.
            kw = ({'feature_status': 'done', 'story_statuses': ('done',)}
                  if grain == 'milestone' else {'story_statuses': ('todo',)})
            with self.subTest(grain=grain), tree(**kw) as root:
                path = self._mangle(root, rel, junk)
                # The gate reports it...
                code, out = run_gate(root)
                self.assertEqual(code, 1, out)
                self.assertIn(junk, out)
                # ...and the verb fixes it, naming what it found.
                code, out = run_cli(root, grain, 'done', gid)
                self.assertEqual(code, 0, out)
                self.assertIn(f'{junk} -> done', out)
                self.assertEqual(model.field_of(path, 'status'), 'done')

    def test_an_absent_status_key_reads_as_none_and_is_still_settable(self):
        with tree(story_statuses=('todo',)) as root:
            path = root / STORY_REL
            path.write_text(
                '\n'.join(l for l in path.read_text(encoding='utf-8').split('\n')
                          if not l.startswith('status:')), encoding='utf-8')
            code, out = run_cli(root, 'story', 'wip', '0.1/alpha/s0')
            self.assertEqual(code, 0, out)
            self.assertIn('(none) -> wip', out)
            self.assertEqual(model.field_of(path, 'status'), 'wip')

    def test_the_REQUESTED_state_is_still_closed(self):
        # The one refusal that survives, on every grain kind, naming the set.
        for grain, (_, gid, _) in self.NONSENSE.items():
            with self.subTest(grain=grain), tree(story_statuses=('todo',)) as root:
                code, out = run_cli(root, grain, 'butterfly', gid)
                self.assertEqual(code, 2, out)
                self.assertIn(f'is not a {grain} status', out)


class TheShortestPathFromNothingToAClosedMilestone(unittest.TestCase):
    """Six commands, and every one of them writes something.

    Measured on the graph this replaced: an empty repo to one closed milestone
    was 14 commands, six of them pure ceremony — `milestone ready`,
    `milestone building`, `feature ready`, `feature building`, `feature review`
    and a `story wip` nobody wanted — each existing only because an edge
    demanded it, and each reachable by `sed` anyway.
    """

    def test_it_is_six_commands_and_they_all_land(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'repo'
            root.mkdir()
            (root / 'docs' / 'reviews').mkdir(parents=True)
            (root / 'docs' / 'reviews' / 'alpha.md').write_text(
                'Reviewed, and it holds up under the cases that matter.\n',
                encoding='utf-8')
            subprocess.run(['git', 'init', '-q'], cwd=root, check=True)
            previous = Path.cwd()
            os.chdir(root)
            try:
                sequence = (
                    ('new', 'milestone', '0.1', 'Demo'),
                    ('new', 'feature', '0.1', 'alpha', 'Alpha'),
                    ('new', 'story', '0.1/alpha', 's0', 'S0'),
                    ('story', 'review', '0.1/alpha/s0'),
                    ('feature', 'done', '0.1/alpha', '--cascade',
                     '--review-record', 'docs/reviews/alpha.md'),
                    ('milestone', 'done', '0.1'),
                )
                for argv in sequence:
                    code, out = run_cli(root, *argv)
                    self.assertEqual(code, 0, f'{argv}\n{out}')
                self.assertEqual(len(sequence), 6)
                code, out = run_gate(root)
            finally:
                os.chdir(previous)
            self.assertEqual(code, 0, out)


class Vocabulary(unittest.TestCase):
    """`pm vocabulary` prints the CLOSED SETS, and no longer prints edges.

    Its audience is the pin bump: this toolkit ships a shape, a project bumps
    its pin, and then has to see what changed. The set of states a grain may
    hold and the set of rule ids `[pm] checks` may name are what changed, so
    they have to be readable from the tool rather than scraped from a
    changelog — which is also why this verb keeps running when `[pm] checks`
    names an id the release retired.
    """

    def test_json_states_the_closed_sets_and_no_edges(self):
        import json
        with tree() as root:
            code, out = run_cli(root, 'vocabulary', '--json')
            self.assertEqual(code, 0, out)
            data = json.loads(out)
            self.assertEqual(data['grains']['story']['states'],
                             list(model.DEFAULT_STORY_STATES))
            self.assertEqual(data['grains']['bug']['states'],
                             list(model.DEFAULT_BUG_STATES))
            self.assertEqual(data['checks'], list(model.KNOWN_CHECKS))
            # The edge table is what died. Nothing may re-grow one here.
            for grain in data['grains'].values():
                self.assertEqual(list(grain), ['states'])
            self.assertNotIn('->', out)

    def test_it_reads_the_projects_OWN_vocabulary_not_the_stock_one(self):
        with tree() as root:
            (root / 'devkit.toml').write_text(
                '[pm]\nstory_states = ["todo","wip","review","done","parked"]\n',
                encoding='utf-8')
            import json
            code, out = run_cli(root, 'vocabulary', '--json')
            self.assertEqual(code, 0, out)
            self.assertIn('parked', json.loads(out)['grains']['story']['states'])

    def test_the_plain_print_names_every_grain_and_the_rule_ids(self):
        with tree() as root:
            code, out = run_cli(root, 'vocabulary')
            self.assertEqual(code, 0, out)
            for grain in ('milestone', 'feature', 'story', 'bug'):
                self.assertIn(grain, out)
            self.assertIn('D9', out)
            self.assertIn('D10', out)
            self.assertNotIn('->', out)


class BlockedIsNotATrap(unittest.TestCase):
    def test_a_blocked_story_can_be_unblocked_through_the_cli(self):
        with tree(story_statuses=('todo',)) as root:
            self.assertEqual(run_cli(root, 'story', 'wip', '0.1/alpha/s0')[0], 0)
            self.assertEqual(run_cli(root, 'story', 'blocked', '0.1/alpha/s0')[0], 0)
            self.assertEqual(run_cli(root, 'story', 'wip', '0.1/alpha/s0')[0], 0)
            self.assertEqual(run_cli(root, 'story', 'review', '0.1/alpha/s0')[0], 0)


class StoryResolution(unittest.TestCase):
    """`story_file` and `story_files` must agree about what a story IS.

    They did not: the gate walk went recursive while the ID RESOLVER still
    globbed one directory level, so a story at `stories/parked/s2.md` was
    reported by `check pm` and then refused by `pm story wip <id>` as a story
    that does not exist. Each answer is defensible alone; together they leave
    the author nothing to do.
    """

    FDIR = 'pm/roadmap/0.1-demo/features/alpha'

    def test_a_nested_story_is_addressable_by_id(self):
        with tree() as root:
            write(root / self.FDIR / 'stories/parked/s2.md',
                  {'id': '0.1/alpha/s2', 'feature': '0.1/alpha',
                   'milestone': '"0.1"', 'name': 'S2', 'status': 'todo'})
            code, out = run_cli(root, 'story', 'wip', '0.1/alpha/s2')
            self.assertEqual(code, 0, out)
            self.assertEqual(
                model.field_of(root / self.FDIR / 'stories/parked/s2.md', 'status'),
                'wip')

    def test_the_gate_and_the_verb_now_see_the_same_story(self):
        with tree() as root:
            write(root / self.FDIR / 'stories/parked/s2.md',
                  {'id': '0.1/alpha/s2', 'feature': '0.1/alpha',
                   'milestone': '"0.1"', 'name': 'S2', 'status': 'todo'})
            _, gate = run_gate(root)
            self.assertIn('2 story/ies', gate)
            self.assertIsNotNone(model.story_file(cfg_for(root), '0.1/alpha/s2'))

    @unittest.skipUnless(CASE_SENSITIVE_TMP, 'case-insensitive filesystem')
    def test_an_uppercase_extension_resolves(self):
        with tree() as root:
            write(root / self.FDIR / 'stories/S3.MD',
                  {'id': '0.1/alpha/S3', 'feature': '0.1/alpha',
                   'milestone': '"0.1"', 'name': 'S3', 'status': 'todo'})
            self.assertEqual(model.story_file(cfg_for(root), '0.1/alpha/S3').name,
                             'S3.MD')

    def test_two_files_claiming_one_id_refuse_rather_than_pick(self):
        with tree() as root:
            for where in ('stories/dup.md', 'stories/parked/dup.md'):
                write(root / self.FDIR / where,
                      {'id': '0.1/alpha/dup', 'feature': '0.1/alpha',
                       'milestone': '"0.1"', 'name': 'Dup', 'status': 'todo'})
            with self.assertRaises(model.AmbiguousStory):
                model.story_file(cfg_for(root), '0.1/alpha/dup')

    def test_an_exact_stem_still_beats_an_ordinal_prefixed_sibling(self):
        cfg = None
        with tree() as root:
            cfg = model.PmConfig(root=root, story_ordinal_prefix=True)
            for where in ('stories/s9.md', 'stories/07-s9.md'):
                write(root / self.FDIR / where,
                      {'id': '0.1/alpha/s9', 'feature': '0.1/alpha',
                       'milestone': '"0.1"', 'name': 'S9', 'status': 'todo'})
            self.assertEqual(model.story_file(cfg, '0.1/alpha/s9').name, 's9.md')

    def test_an_ordinal_prefixed_story_one_directory_down_resolves(self):
        with tree() as root:
            cfg = model.PmConfig(root=root, story_ordinal_prefix=True)
            write(root / self.FDIR / 'stories/parked/03-s4.md',
                  {'id': '0.1/alpha/s4', 'feature': '0.1/alpha',
                   'milestone': '"0.1"', 'name': 'S4', 'status': 'todo'})
            self.assertEqual(model.story_file(cfg, '0.1/alpha/s4').name, '03-s4.md')

    def test_a_note_beside_the_stories_is_not_addressable_as_one(self):
        # The same definition the walk uses: a grain IS its frontmatter, so a
        # README parked in `stories/` is not a story with an empty status.
        with tree() as root:
            (root / self.FDIR / 'stories/README.md').write_text(
                '# how stories are written here\n', encoding='utf-8')
            self.assertIsNone(model.story_file(cfg_for(root), '0.1/alpha/README'))


class OrdinalPrefix(unittest.TestCase):
    """`story_ordinal_prefix` must TEACH V2 the prefix, never switch V2 off.

    Skipping instead of stripping left every story in such a tree unchecked
    while the gate printed VALID — under the configuration the docs mandate.
    """

    def _prefixed(self, root: Path, sid: str) -> Path:
        sdir = root / 'pm/roadmap/0.1-demo/features/alpha/stories'
        p = sdir / '01-boots.md'
        write(p, {'id': sid, 'feature': '0.1/alpha', 'milestone': '"0.1"',
                  'name': 'B', 'status': 'todo'})
        return p

    def _validate(self, root: Path):
        from godot_devkit.repo.pm import validate
        return validate.run(model.PmConfig(root=root, story_ordinal_prefix=True))

    def test_a_prefixed_file_with_a_matching_id_is_valid(self):
        with tree(story_statuses=()) as root:
            self._prefixed(root, '0.1/alpha/boots')
            self.assertEqual(self._validate(root)[0], [])

    def test_a_prefixed_file_with_a_WRONG_id_is_still_caught(self):
        # The regression: this used to pass because the whole arm was skipped.
        with tree(story_statuses=()) as root:
            self._prefixed(root, 'TOTAL/GARBAGE/nonsense')
            findings = self._validate(root)[0]
            self.assertTrue(any('does not match its path' in f for f in findings),
                            findings)

    def test_the_prefix_is_not_stripped_when_the_flag_is_off(self):
        with tree(story_statuses=()) as root:
            self._prefixed(root, '0.1/alpha/boots')
            from godot_devkit.repo.pm import validate
            findings = validate.run(model.PmConfig(root=root))[0]
            self.assertTrue(any('does not match its path' in f for f in findings))


class Decide(unittest.TestCase):
    """`pm decide` — one dated, ordinal-stamped heading, and nothing else.

    The two things an author writing this by hand gets wrong are the date and
    the ordinal, so the verb stamps both. It imposes no field schema: the
    four-field one this replaced produced zero conforming entries across a
    consumer's 158 decision logs.
    """

    MDIR = 'pm/roadmap/0.1-demo'

    def _scaffolded(self, root: Path) -> None:
        self.assertEqual(run_cli(root, 'new', 'milestone', '0.1')[0], 0)
        self.assertEqual(run_cli(root, 'new', 'feature', '0.1', 'alpha')[0], 0)

    def _log(self, root: Path, rel: str = '') -> str:
        return (root / self.MDIR / (rel or 'decisions.md')).read_text(
            encoding='utf-8')

    def test_the_log_is_minted_on_the_FIRST_decision_and_not_before(self):
        # The whole cut. `pm new` scaffolded an empty decisions.md into every
        # grain — 204 files, ~1,900 lines, a quarter of one consumer's PM tree,
        # minted by the verb that exists to stop sprawl. It appears when there
        # is something in it.
        with tree() as root:
            self._scaffolded(root)
            log = root / self.MDIR / 'decisions.md'
            self.assertFalse(log.exists())
            code, out = run_cli(root, 'decide', '0.1', 'the first choice')
            self.assertEqual(code, 0, out)
            self.assertTrue(log.is_file())
            body = log.read_text(encoding='utf-8')
            # Minted from the template, header and all — a bare heading with no
            # instruction line is what D13 reports.
            self.assertTrue(body.startswith(model.SLOT_HEADER['decisions.md']))
            self.assertIn('## D1 — ', body)

    def test_a_refused_decision_mints_nothing(self):
        # Refuses WHOLE: the mint and the append are one write, so a refusal
        # cannot leave an empty log behind — which would be the sprawl again,
        # arriving by the error path.
        with tree() as root:
            self._scaffolded(root)
            code, out = run_cli(root, 'decide', '0.1')
            self.assertEqual(code, 2, out)
            self.assertFalse((root / self.MDIR / 'decisions.md').exists())

    def test_it_stamps_todays_date_and_the_first_ordinal(self):
        with tree() as root:
            self._scaffolded(root)
            code, out = run_cli(root, 'decide', '0.1', 'the sweep verb moves')
            self.assertEqual(code, 0, out)
            today = datetime.now(timezone.utc).date().isoformat()
            self.assertIn(f'## D1 — {today} — the sweep verb moves',
                          self._log(root))

    def test_the_ordinal_advances_from_what_the_log_already_holds(self):
        # The whole reason the verb exists: a second D1 in one log is
        # invisible until somebody cites it.
        with tree() as root:
            self._scaffolded(root)
            for n in range(3):
                self.assertEqual(
                    run_cli(root, 'decide', '0.1', f'choice {n}')[0], 0)
            body = self._log(root)
            for eid in ('## D1 ', '## D2 ', '## D3 '):
                self.assertIn(eid, body)

    def test_it_keeps_the_prefix_the_log_already_numbers_itself_with(self):
        # A tree numbering `M27` keeps numbering `M`. Falling back to `D`
        # would put two numbering schemes in one file.
        with tree() as root:
            self._scaffolded(root)
            log = root / self.MDIR / 'decisions.md'
            model.write_raw(log, f'{model.SLOT_HEADER["decisions.md"]}\n\n'
                                 f'## M27 — 2026-01-01 — an older choice\n')
            self.assertEqual(run_cli(root, 'decide', '0.1', 'the next one')[0], 0)
            self.assertIn('## M28 — ', self._log(root))

    def test_the_prose_under_a_heading_is_never_touched(self):
        # No field schema means the body is the author's. An append that
        # rewrote or refused hand-written prose would be the old verb again.
        with tree() as root:
            self._scaffolded(root)
            log = root / self.MDIR / 'decisions.md'
            hand = ('## D9 — 2026-01-01 — a hand-written entry\n'
                    'Free prose, no fields, several\nlines of it.\n')
            model.write_raw(log, f'{model.SLOT_HEADER["decisions.md"]}\n\n{hand}')
            self.assertEqual(run_cli(root, 'decide', '0.1', 'the next one')[0], 0)
            body = self._log(root)
            self.assertIn(hand.strip(), body)
            self.assertIn('## D10 — ', body)

    def test_a_missing_title_is_a_usage_error_and_leaves_the_log_alone(self):
        with tree() as root:
            self._scaffolded(root)
            self.assertEqual(run_cli(root, 'decide', '0.1', 'a choice')[0], 0)
            before = self._log(root)
            code, out = run_cli(root, 'decide', '0.1')
            self.assertEqual(code, 2, out)
            self.assertEqual(self._log(root), before)

    def test_a_flag_shaped_title_is_refused_not_written(self):
        # The retired four-field interface (`--title X --chose A --over B …`)
        # once parsed here; today those words would be just words, and the one
        # caller who types a title whose FIRST word starts with `--` is a
        # caller speaking that dead interface. Writing their flag soup into a
        # durable log at exit 0 is a quiet lie — refuse, name the word, write
        # nothing.
        with tree() as root:
            code, out = run_cli(root, 'decide', '0.1/alpha', '--title',
                                'the thing', '--chose', 'A', '--over', 'B')
            self.assertEqual(code, 2, out)
            self.assertIn('--title', out)
            self.assertFalse(
                (root / 'pm/roadmap/0.1-demo/features/alpha/decisions.md')
                .exists())

    def test_a_story_or_bug_has_no_decision_log(self):
        with tree() as root:
            self._scaffolded(root)
            code, out = run_cli(root, 'decide', '0.1/alpha/a-story', 'nope')
            self.assertEqual(code, 1, out)
            self.assertIn('no decision log', out)

    def test_a_feature_log_is_addressable_too(self):
        with tree() as root:
            self._scaffolded(root)
            code, out = run_cli(root, 'decide', '0.1/alpha', 'a feature choice')
            self.assertEqual(code, 0, out)
            self.assertIn('## D1 — ', self._log(root, 'features/alpha/decisions.md'))


class ExeclistRefusals(unittest.TestCase):
    """A grain the renderer cannot rewrite CORRECTLY is a refusal — the file
    and the problem named, nothing written — never a traceback, and never a
    file that quietly grows by one fresh block per run."""

    MFILE = 'pm/roadmap/0.1-demo/milestone.md'
    FFILE = 'pm/roadmap/0.1-demo/features/alpha/feature.md'

    def test_a_non_utf8_grain_refuses_instead_of_crashing(self):
        # The audit's \xff-grain reproduction: UnicodeDecodeError traceback
        # out of the inline read in execlist.sync, scan aborted mid-tree.
        with tree() as root:
            (root / self.FFILE).write_bytes(
                b'---\nid: 0.1/alpha\nstatus: building\n---\n\xff\n')
            code, out = run_cli(root, 'sync')
            self.assertEqual(code, 1, out)
            self.assertIn('REFUSED', out)
            self.assertIn('feature.md', out)
            self.assertIn('not UTF-8', out)
            # `--check` reads the same bytes; it refuses the same way.
            code, out = run_cli(root, 'sync', '--check')
            self.assertEqual(code, 1, out)
            self.assertIn('not UTF-8', out)

    def test_v6_reports_a_non_utf8_grain_and_keeps_earlier_findings(self):
        from godot_devkit.repo.pm import validate
        with tree() as root:
            run_cli(root, 'sync')
            (root / self.FFILE).write_bytes(b'\xff\xfe broken')
            findings, _ = validate.run(cfg_for(root))
            self.assertTrue(any('not UTF-8' in f for f in findings), findings)
            # V1's finding about the same grain survives — the crash used to
            # abort run() and take every finding gathered before V6 with it.
            self.assertTrue(any('missing id' in f for f in findings), findings)

    def test_reversed_markers_refuse_instead_of_growing_the_file(self):
        # The audit's growth reproduction: 25 -> 33 -> 41 lines over three
        # `pm sync` runs, each exit 0 — the append branch fired every time.
        from godot_devkit.repo.pm import execlist
        with tree() as root:
            run_cli(root, 'sync')
            mfile = root / self.MFILE
            text = mfile.read_text(encoding='utf-8')
            mfile.write_text(text.replace(execlist.OPEN, '@@TMP@@')
                             .replace(execlist.CLOSE, execlist.OPEN)
                             .replace('@@TMP@@', execlist.CLOSE),
                             encoding='utf-8')
            before = mfile.read_bytes()
            code, out = run_cli(root, 'sync')
            self.assertEqual(code, 1, out)
            self.assertIn('BEFORE', out)
            self.assertIn(execlist.OPEN, out)
            self.assertIn(execlist.CLOSE, out)
            self.assertIn('milestone.md', out)
            self.assertEqual(mfile.read_bytes(), before)
            # Refusing twice is still refusing — and still not writing.
            code, _ = run_cli(root, 'sync')
            self.assertEqual(code, 1)
            self.assertEqual(mfile.read_bytes(), before)

    def test_a_lone_marker_refuses_too(self):
        # Half a pair is not "no block" — it used to take the append branch.
        from godot_devkit.repo.pm import execlist
        with tree() as root:
            run_cli(root, 'sync')
            mfile = root / self.MFILE
            mfile.write_text(mfile.read_text(encoding='utf-8')
                             .replace(execlist.CLOSE, ''), encoding='utf-8')
            before = mfile.read_bytes()
            code, out = run_cli(root, 'sync')
            self.assertEqual(code, 1, out)
            self.assertIn('without', out)
            self.assertIn('milestone.md', out)
            self.assertEqual(mfile.read_bytes(), before)


class StatusVerbHonoursACustomVocabulary(unittest.TestCase):
    """`done` and `review` are dispatch verbs, but the TARGET state still has
    to be in the project's own closed set. Pre-fix they dispatched before the
    membership check, so with a custom vocabulary the sanctioned tool wrote
    the exact out-of-vocabulary status D4 reports. The CURRENT state stays
    ungated — repair-from-wombat is pinned elsewhere and unchanged."""

    FFILE = 'pm/roadmap/0.1-demo/features/alpha/feature.md'

    def test_feature_done_refuses_when_the_vocabulary_excludes_done(self):
        with tree() as root:
            (root / 'devkit.toml').write_text(
                '[pm]\nfeature_states = ["todo", "building", "shipped"]\n',
                encoding='utf-8')
            ffile = root / self.FFILE
            before = ffile.read_bytes()
            code, out = run_cli(root, 'feature', 'done', '0.1/alpha')
            self.assertEqual(code, 2, out)
            self.assertIn('todo building shipped', out)
            self.assertEqual(ffile.read_bytes(), before)

    def test_feature_review_refuses_when_the_vocabulary_excludes_review(self):
        with tree() as root:
            (root / 'devkit.toml').write_text(
                '[pm]\nfeature_states = ["todo", "building", "shipped"]\n',
                encoding='utf-8')
            ffile = root / self.FFILE
            before = ffile.read_bytes()
            code, out = run_cli(root, 'feature', 'review', '0.1/alpha')
            self.assertEqual(code, 2, out)
            self.assertIn('todo building shipped', out)
            self.assertEqual(ffile.read_bytes(), before)

    def test_cascade_refuses_when_story_states_exclude_done(self):
        with tree(story_statuses=('review',)) as root:
            (root / 'devkit.toml').write_text(
                '[pm]\nstory_states = ["todo", "wip", "review", "shipped"]\n',
                encoding='utf-8')
            sfile, ffile = root / STORY_REL, root / self.FFILE
            s_before, f_before = sfile.read_bytes(), ffile.read_bytes()
            code, out = run_cli(root, 'feature', 'done', '0.1/alpha',
                                '--cascade')
            self.assertEqual(code, 2, out)
            self.assertIn('todo wip review shipped', out)
            # Nothing was touched — neither the story nor the feature.
            self.assertEqual(sfile.read_bytes(), s_before)
            self.assertEqual(ffile.read_bytes(), f_before)

    def test_a_custom_vocabulary_that_keeps_done_still_closes(self):
        with tree() as root:
            (root / 'devkit.toml').write_text(
                '[pm]\nfeature_states = ["building", "done"]\n',
                encoding='utf-8')
            code, out = run_cli(root, 'feature', 'done', '0.1/alpha')
            self.assertEqual(code, 0, out)
            self.assertEqual(model.field_of(root / self.FFILE, 'status'),
                             'done')

    def test_review_record_equals_spelling_with_no_value_refuses(self):
        # Pre-fix: `--review-record=` stored '' and silently skipped the
        # stamp at exit 0 — flag consumed, nothing done. The space spelling's
        # missing-arg case was already a Usage refusal; they now agree.
        with tree() as root:
            ffile = root / self.FFILE
            before = ffile.read_bytes()
            code, out = run_cli(root, 'feature', 'done', '0.1/alpha',
                                '--review-record=')
            self.assertEqual(code, 2, out)
            self.assertIn('needs a path', out)
            self.assertEqual(ffile.read_bytes(), before)

    def test_review_record_space_spelling_with_an_empty_value_refuses_too(self):
        with tree() as root:
            ffile = root / self.FFILE
            before = ffile.read_bytes()
            code, out = run_cli(root, 'feature', 'done', '0.1/alpha',
                                '--review-record', '')
            self.assertEqual(code, 2, out)
            self.assertIn('needs a path', out)
            self.assertEqual(ffile.read_bytes(), before)


class ZeroCensusIsLoud(unittest.TestCase):
    """An empty print at exit 0 over a tree that holds nothing is a scan of
    zero files, passing — rule 4's read-side sin. `pm list` got the loud arm
    first; `pm status` and `pm sync --check` mirror it."""

    def _emptied(self, root: Path) -> None:
        import shutil
        shutil.rmtree(root / 'pm/roadmap/0.1-demo')

    def test_status_over_an_empty_roadmap_refuses(self):
        with tree() as root:
            self._emptied(root)
            code, out = run_cli(root, 'status')
            self.assertEqual(code, 2, out)
            self.assertIn('no milestone at all', out)

    def test_status_naming_an_unknown_milestone_refuses_naming_the_set(self):
        with tree() as root:
            code, out = run_cli(root, 'status', '9.9')
            self.assertEqual(code, 2, out)
            self.assertIn("'9.9'", out)
            self.assertIn('0.1', out)

    def test_status_still_prints_a_real_tree(self):
        with tree() as root:
            code, out = run_cli(root, 'status', '0.1')
            self.assertEqual(code, 0, out)
            self.assertIn('milestone 0.1', out)

    def test_sync_check_over_zero_grains_refuses(self):
        # Pre-fix: `all 0 execution list(s) current`, exit 0 — only the write
        # mode refused.
        with tree() as root:
            self._emptied(root)
            code, out = run_cli(root, 'sync', '--check')
            self.assertEqual(code, 2, out)
            self.assertIn('no grains', out)
            code, out = run_cli(root, 'sync')
            self.assertEqual(code, 2, out)
            self.assertIn('no grains', out)


class BugStatus(unittest.TestCase):
    """`pm bug <status> <bug-id>` — exactly `cmd_story`'s shape, for bugs.

    Before this, the vocabulary and the `/bugs/` resolver both existed
    (`_grain_file`, `checks/pm.py`'s D4) and nothing sanctioned reached them
    together — only a hand edit or the untyped `pm set` moved a bug's own
    `status:`. The shared shapes live in `StatusVerbQuartet`; kept here are
    the guards only a bug id can exercise.
    """

    @staticmethod
    def _bug(root: Path, slug: str, status: str) -> Path:
        p = root / 'pm/roadmap/0.1-demo/bugs' / f'{slug}.md'
        write(p, {'id': f'0.1/bugs/{slug}', 'milestone': '"0.1"',
                  'status': status})
        return p

    def test_a_traversal_in_the_slug_half_never_writes_a_sibling_grain(self):
        # v0.16.0 release-review blocker: `0.1/bugs/../features/alpha/feature`
        # resolved by traversal and wrote a BUG-vocabulary status into the
        # feature file — the cross-grain write the docstring above promises
        # cannot happen. The slug half holds no path segments, ever.
        with tree() as root:
            self._bug(root, 'crash', 'open')
            victim = root / 'pm/roadmap/0.1-demo/features/alpha/feature.md'
            for gid in ('0.1/bugs/../features/alpha/feature',
                        '0.1/bugs/sub/../../features/alpha/feature',
                        '0.1/bugs/'):
                code, out = run_cli(root, 'bug', 'fixed', gid)
                self.assertEqual(code, 2, (gid, out))
                self.assertIn('no bug resolves', out)
            self.assertEqual(model.field_of(victim, 'status'), 'building')
            # `pm set` rides the same resolver — the same id must refuse.
            code, out = run_cli(root, 'set',
                                '0.1/bugs/../features/alpha/feature',
                                'status', 'PWNED')
            self.assertEqual(code, 2, out)
            self.assertEqual(model.field_of(victim, 'status'), 'building')

    def test_an_id_lacking_the_bugs_segment_never_writes_a_different_grain(self):
        # `_grain_file` alone resolves a FEATURE id too when `/bugs/` is
        # absent — a bug verb reaching it unguarded would validate the
        # target against `bug_states` and then write it into the feature's
        # own `status:`, a cross-grain write no caller asked for.
        with tree() as root:
            code, out = run_cli(root, 'bug', 'open', '0.1/alpha')
            self.assertEqual(code, 2, out)
            self.assertIn('no bug resolves', out)
            self.assertEqual(
                model.field_of(
                    root / 'pm/roadmap/0.1-demo/features/alpha/feature.md',
                    'status'),
                'building')

    def test_a_nested_bug_id_resolves(self):
        with tree() as root:
            bug = root / 'pm/roadmap/0.1-demo/bugs/spatial/seed-is-zero.md'
            write(bug, {'id': '0.1/bugs/spatial/seed-is-zero',
                       'milestone': '"0.1"', 'status': 'open'})
            code, out = run_cli(root, 'bug', 'fixed',
                                '0.1/bugs/spatial/seed-is-zero')
            self.assertEqual(code, 0, out)
            self.assertEqual(model.field_of(bug, 'status'), 'fixed')


class Retire(unittest.TestCase):
    """`pm retire <milestone-id>` — the prune flow `pm init` seeds a table
    for, made whole: one write that removes the milestone directory and
    appends its row.

    Refuses on exactly two impossibilities (an unresolvable id, no
    ROADMAP.md); everything else it notices about the tree — a milestone
    not `done`, a feature or bug still open — is reported below the line
    that says what moved, never a precondition.
    """

    @staticmethod
    def _seed_roadmap(root: Path) -> Path:
        index = root / 'pm/roadmap/ROADMAP.md'
        index.write_text(skills.ROADMAP_SEED, encoding='utf-8')
        return index

    def test_an_unresolvable_id_is_a_usage_error_naming_the_known_set(self):
        with tree() as root:
            self._seed_roadmap(root)
            code, out = run_cli(root, 'retire', '9.9')
            self.assertEqual(code, 2, out)
            self.assertIn('is not a milestone', out)
            self.assertIn('0.1', out)
            self.assertTrue((root / 'pm/roadmap/0.1-demo').is_dir())

    def test_no_roadmap_index_is_refused_naming_where_it_looked(self):
        with tree(milestone_status='done', feature_status='done',
                  story_statuses=('done',)) as root:
            # tree() never seeds ROADMAP.md — this IS the missing-index case.
            code, out = run_cli(root, 'retire', '0.1')
            self.assertEqual(code, 1, out)
            self.assertIn('ROADMAP.md', out)
            self.assertIn('does not exist', out)
            self.assertIn('pm/roadmap', out)
            self.assertTrue((root / 'pm/roadmap/0.1-demo').is_dir())

    def test_a_non_done_milestone_is_reported_not_refused(self):
        with tree(milestone_status='building',
                  feature_status='building') as root:
            self._seed_roadmap(root)
            BugStatus._bug(root, 'seed-is-zero', 'open')
            code, out = run_cli(root, 'retire', '0.1')
            self.assertEqual(code, 0, out)
            self.assertIn('noticed: milestone 0.1 is building, not done', out)
            self.assertIn('feature(s) not done', out)
            self.assertIn('bug(s) still open', out)
            self.assertFalse((root / 'pm/roadmap/0.1-demo').exists())

    def test_dry_run_writes_nothing_byte_for_byte(self):
        with tree(milestone_status='done', feature_status='done',
                  story_statuses=('done',)) as root:
            index = self._seed_roadmap(root)
            before_index = index.read_bytes()
            mdir = root / 'pm/roadmap/0.1-demo'
            before_files = sorted(
                (p.relative_to(root), p.read_bytes())
                for p in mdir.rglob('*') if p.is_file())
            code, out = run_cli(root, 'retire', '0.1', '--dry-run')
            self.assertEqual(code, 0, out)
            self.assertIn('[dry-run]', out)
            self.assertEqual(index.read_bytes(), before_index)
            self.assertTrue(mdir.is_dir())
            after_files = sorted(
                (p.relative_to(root), p.read_bytes())
                for p in mdir.rglob('*') if p.is_file())
            self.assertEqual(before_files, after_files)

    def test_retire_appends_exactly_one_row_and_removes_exactly_the_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'repo'
            write(root / 'pm/roadmap/0.1-demo/milestone.md',
                  {'id': '"0.1"', 'name': 'Demo', 'status': 'done',
                   'actual_date': '2026-01-02'})
            write(root / 'pm/roadmap/0.2-later/milestone.md',
                  {'id': '"0.2"', 'name': 'Later', 'status': 'building'})
            subprocess.run(['git', 'init', '-q'], cwd=root, check=True)
            previous = Path.cwd()
            os.chdir(root)
            try:
                index = self._seed_roadmap(root)
                code, out = run_cli(root, 'retire', '0.1', 'shipped',
                                    'X', 'and', 'Y')
                self.assertEqual(code, 0, out)
                rows = [line for line in
                       index.read_text(encoding='utf-8').split('\n')
                       if line.startswith('| 0.1 |')]
                self.assertEqual(len(rows), 1, rows)
                self.assertIn('2026-01-02', rows[0])
                self.assertIn('shipped X and Y', rows[0])
                self.assertFalse((root / 'pm/roadmap/0.1-demo').exists())
                self.assertTrue((root / 'pm/roadmap/0.2-later').is_dir())
            finally:
                os.chdir(previous)


class Move(unittest.TestCase):
    """`pm move <story-id> <feature-id>` — re-parents a story whole, or not
    at all.

    Before this, re-parenting was a rename plus three hand-edited
    frontmatter fields, policed afterwards (if at all) by V2/V3 — one
    whole-or-nothing verb through the machinery the templates already own.
    """

    @staticmethod
    def _second_feature(root: Path) -> None:
        write(root / 'pm/roadmap/0.1-demo/features/beta/feature.md',
              {'id': '0.1/beta', 'milestone': '"0.1"', 'name': 'Beta',
               'status': 'building', 'reviewed': ''})

    def test_a_story_moves_whole(self):
        with tree(story_statuses=('todo',)) as root:
            self._second_feature(root)
            code, out = run_cli(root, 'move', '0.1/alpha/s0', '0.1/beta')
            self.assertEqual(code, 0, out)
            old = root / STORY_REL
            new = root / 'pm/roadmap/0.1-demo/features/beta/stories/s0.md'
            self.assertFalse(old.exists())
            self.assertTrue(new.is_file())
            self.assertEqual(model.field_of(new, 'id'), '0.1/beta/s0')
            self.assertEqual(model.field_of(new, 'feature'), '0.1/beta')
            self.assertEqual(model.field_of(new, 'milestone'), '0.1')
            self.assertIn('milestone: "0.1"', new.read_text(encoding='utf-8'))

    def test_every_other_byte_survives_the_move(self):
        with tree(story_statuses=('todo',)) as root:
            self._second_feature(root)
            before = (root / STORY_REL).read_text(encoding='utf-8')
            code, out = run_cli(root, 'move', '0.1/alpha/s0', '0.1/beta')
            self.assertEqual(code, 0, out)
            new = root / 'pm/roadmap/0.1-demo/features/beta/stories/s0.md'
            after = new.read_text(encoding='utf-8')
            expected = (before.replace('feature: 0.1/alpha', 'feature: 0.1/beta')
                             .replace('id: 0.1/alpha/s0', 'id: 0.1/beta/s0'))
            self.assertEqual(expected, after)

    def test_unknown_target_feature_is_usage_naming_known_features(self):
        with tree(story_statuses=('todo',)) as root:
            self._second_feature(root)
            code, out = run_cli(root, 'move', '0.1/alpha/s0', '0.1/nope')
            self.assertEqual(code, 2, out)
            self.assertIn('no feature resolves', out)
            self.assertIn('0.1/alpha', out)
            self.assertIn('0.1/beta', out)
            self.assertTrue((root / STORY_REL).is_file())

    def test_unresolvable_story_is_a_usage_error(self):
        with tree(story_statuses=('todo',)) as root:
            self._second_feature(root)
            code, out = run_cli(root, 'move', '0.1/alpha/nope', '0.1/beta')
            self.assertEqual(code, 2, out)

    def test_already_under_the_target_is_a_noop(self):
        with tree(story_statuses=('todo',)) as root:
            code, out = run_cli(root, 'move', '0.1/alpha/s0', '0.1/alpha')
            self.assertEqual(code, 0, out)
            self.assertIn('no-op', out)
            self.assertTrue((root / STORY_REL).is_file())

    @unittest.skipIf(hasattr(os, 'geteuid') and os.geteuid() == 0,
                     'permission bits are not the obstruction as root')
    def test_an_unwritable_target_directory_moves_nothing(self):
        with tree(story_statuses=('todo',)) as root:
            self._second_feature(root)
            target_dir = root / 'pm/roadmap/0.1-demo/features/beta'
            target_dir.chmod(0o555)
            try:
                before = (root / STORY_REL).read_bytes()
                code, out = run_cli(root, 'move', '0.1/alpha/s0', '0.1/beta')
                self.assertEqual(code, 1, out)
                self.assertIn('nothing was moved', out)
                self.assertTrue((root / STORY_REL).is_file())
                self.assertEqual((root / STORY_REL).read_bytes(), before)
                self.assertFalse((target_dir / 'stories' / 's0.md').exists())
            finally:
                target_dir.chmod(0o755)
