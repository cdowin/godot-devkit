"""PM tree — transitions, the review-record definition, and the drift gate.

The load-bearing property is that the CLI and the gate share ONE definition of
"reviewed" and of each drift rule. So these build a tree, drive it through the
CLI, and assert against the GATE — if the two ever diverged, the round trips
below stop closing.

The other thing pinned here is refusal behaviour: a refused close must leave
feature.md byte-identical. A half-applied cascade is worse than no cascade.
"""
from __future__ import annotations

import contextlib
import io
import os
import subprocess
import tempfile
import unittest
import unittest.mock
from datetime import datetime, timezone
from pathlib import Path

from support import REPO_ROOT  # noqa: F401  (inserts src/ on sys.path)

from godot_devkit.repo.checks import pm as pm_check
from godot_devkit.repo.pm import cli, model, templates


LEGACY_LOG = '# legacy log\n\nM1 said something.\n'


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


class Frontmatter(unittest.TestCase):
    def test_field_ignores_the_body(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / 'g.md'
            write(p, {'status': 'todo'}, body='status: done\n\nprose')
            self.assertEqual(model.field_of(p, 'status'), 'todo')

    def test_set_field_preserves_every_other_byte(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / 'g.md'
            write(p, {'id': 'a', 'status': 'todo', 'labels': '[]'}, body='# Title\n\nprose')
            before = p.read_text()
            self.assertTrue(model.set_field(p, 'status', 'wip'))
            after = p.read_text()
            self.assertEqual(before.replace('status: todo', 'status: wip'), after)

    def test_set_field_inserts_a_missing_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / 'g.md'
            write(p, {'id': 'a', 'status': 'todo'})
            self.assertTrue(model.set_field(p, 'reviewed', 'docs/r.md'))
            self.assertEqual(model.field_of(p, 'reviewed'), 'docs/r.md')

    def test_set_field_refuses_a_file_with_no_frontmatter(self):
        # Nowhere to put the key: refuse rather than silently drop it.
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / 'g.md'
            p.write_text('no fence here\n', encoding='utf-8')
            self.assertFalse(model.set_field(p, 'status', 'done'))
            self.assertEqual(p.read_text(), 'no fence here\n')


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
    """

    def test_any_state_in_the_vocabulary_is_reachable(self):
        for state in model.DEFAULT_STORY_STATES:
            with self.subTest(state=state), tree(story_statuses=('todo',)) as root:
                code, out = run_cli(root, 'story', state, '0.1/alpha/s0')
                self.assertEqual(code, 0, out)
                self.assertEqual(
                    model.field_of(root / STORY_REL, 'status'), state)

    def test_a_state_outside_the_vocabulary_is_a_usage_error(self):
        # The half that IS a fact: `banana` is not a story status.
        with tree(story_statuses=('todo',)) as root:
            code, out = run_cli(root, 'story', 'banana', '0.1/alpha/s0')
            self.assertEqual(code, 2, out)
            self.assertIn('is not a story status', out)
            self.assertEqual(model.field_of(root / STORY_REL, 'status'), 'todo')
            for grain, gid in (('feature', '0.1/alpha'), ('milestone', '0.1')):
                code, out = run_cli(root, grain, 'banana', gid)
                self.assertEqual(code, 2, out)
                self.assertIn(f'is not a {grain} status', out)

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

    def test_idempotent_noop_succeeds(self):
        with tree(story_statuses=('wip',)) as root:
            code, out = run_cli(root, 'story', 'wip', '0.1/alpha/s0')
            self.assertEqual(code, 0)
            self.assertIn('no-op', out)

    def test_blocked_is_reachable_from_any_state(self):
        with tree(story_statuses=('todo',)) as root:
            self.assertEqual(run_cli(root, 'story', 'blocked', '0.1/alpha/s0')[0], 0)

    def test_unresolvable_id_is_a_usage_error(self):
        with tree() as root:
            code, _ = run_cli(root, 'story', 'wip', '0.1/alpha/nope')
            self.assertEqual(code, 2)

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


class DriftGate(unittest.TestCase):
    def test_clean_tree_passes_and_prints_a_census(self):
        with tree(story_statuses=('todo',)) as root:
            code, out = run_gate(root)
            self.assertEqual(code, 0, out)
            self.assertIn('1 milestone(s), 1 feature(s), 1 story/ies', out)

    def test_an_empty_tree_fails_loudly_rather_than_passing(self):
        # Rule 4: a gate that scanned nothing must say so, not print PASS.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'repo'
            (root / 'pm' / 'roadmap').mkdir(parents=True)
            subprocess.run(['git', 'init', '-q'], cwd=root, check=True)
            previous = Path.cwd()
            os.chdir(root)
            try:
                code, out = run_gate(root)
            finally:
                os.chdir(previous)
            self.assertEqual(code, 1)
            self.assertIn('no milestones found', out)

    def test_d1_a_reviewed_pointer_that_resolves_to_nothing(self):
        with tree(feature_status='done', story_statuses=('done',),
                  milestone_status='done', with_record=True) as root:
            (root / 'docs' / 'reviews' / 'alpha.md').unlink()
            code, out = run_gate(root)
            self.assertEqual(code, 1, out)
            self.assertIn('resolves to nothing', out)

    def test_d1_says_nothing_about_a_feature_with_no_pointer_at_all(self):
        # The half that was an opinion. An absent review record is the absence
        # of a document — a fact about a team, not about a tree.
        with tree(feature_status='done', story_statuses=('done',),
                  milestone_status='done', with_record=False) as root:
            code, out = run_gate(root)
            self.assertEqual(code, 0, out)

    def test_d2_all_stories_done_but_feature_stalled(self):
        with tree(feature_status='building', story_statuses=('done',)) as root:
            code, out = run_gate(root)
            self.assertEqual(code, 1)
            self.assertIn('all stories done, feature still building', out)

    def test_d3_done_milestone_with_a_live_feature(self):
        with tree(milestone_status='done', feature_status='building') as root:
            code, out = run_gate(root)
            self.assertEqual(code, 1)
            self.assertIn('is done but feature', out)

    def test_d4_status_outside_the_vocabulary(self):
        with tree(feature_status='bogus') as root:
            code, out = run_gate(root)
            self.assertEqual(code, 1)
            self.assertIn('not in (planning ready building review done)', out)

    def test_d5_done_story_under_a_live_feature(self):
        with tree(feature_status='review', story_statuses=('done',)) as root:
            code, out = run_gate(root)
            self.assertEqual(code, 1)
            self.assertIn('two places in this tree disagree', out)

    def test_d6_building_milestone_with_every_feature_done(self):
        with tree(milestone_status='building', feature_status='done',
                  story_statuses=('done',)) as root:
            code, out = run_gate(root)
            self.assertEqual(code, 1)
            self.assertIn('should be done', out)

    def test_a_disabled_rule_does_not_fire(self):
        # `[pm] checks` is the knob. This fixture trips D2 AND D5, so turning
        # D2 off must silence D2's message specifically while D5 still fires —
        # a blanket "exit 0" would also pass if the config had disabled
        # everything, which is exactly the false green worth avoiding.
        with tree(feature_status='building', story_statuses=('done',)) as root:
            code, out = run_gate(root)
            self.assertEqual(code, 1)
            self.assertIn('all stories done, feature still building', out)
            (root / 'devkit.toml').write_text(
                '[pm]\nchecks = ["D1","D3","D4","D5","D6"]\n', encoding='utf-8')
            code, out = run_gate(root)
            self.assertEqual(code, 1)
            self.assertNotIn('all stories done', out)
            self.assertIn('two places in this tree disagree', out)


class Scaffolding(unittest.TestCase):
    def test_new_grains_round_trip_into_a_clean_gate(self):
        with tree(story_statuses=('todo',)) as root:
            self.assertEqual(run_cli(root, 'new', 'feature', '0.1', 'beta', 'Beta')[0], 0)
            self.assertEqual(
                run_cli(root, 'new', 'story', '0.1/beta', 'first', 'First')[0], 0)
            code, out = run_gate(root)
            self.assertEqual(code, 0, out)
            self.assertIn('2 feature(s), 2 story/ies', out)

    def test_new_is_idempotent_over_an_existing_grain(self):
        # This is how a consumer MIGRATES. A tree of 22 milestones and 136
        # features cannot be hand-shaped, so re-running the scaffolder has to
        # fill gaps and leave every existing byte alone.
        with tree(story_statuses=('todo',)) as root:
            ff = root / 'pm/roadmap/0.1-demo/features/alpha/feature.md'
            before = ff.read_text(encoding='utf-8')
            code, out = run_cli(root, 'new', 'feature', '0.1', 'alpha')
            self.assertEqual(code, 0, out)
            self.assertEqual(ff.read_text(encoding='utf-8'), before)
            for slot in model.FEATURE_FILE_SLOTS:
                self.assertTrue((ff.parent / slot).is_file(), slot)

            # Second run: nothing left to do, and it says so.
            code, out = run_cli(root, 'new', 'feature', '0.1', 'alpha')
            self.assertEqual(code, 0, out)
            self.assertIn('already has every canonical slot', out)
            self.assertEqual(ff.read_text(encoding='utf-8'), before)

    def test_new_fills_a_milestones_slots_without_touching_milestone_md(self):
        with tree(story_statuses=('todo',)) as root:
            mf = root / 'pm/roadmap/0.1-demo/milestone.md'
            before = mf.read_text(encoding='utf-8')
            code, out = run_cli(root, 'new', 'milestone', '0.1')
            self.assertEqual(code, 0, out)
            self.assertEqual(mf.read_text(encoding='utf-8'), before)
            for slot in model.MILESTONE_FILE_SLOTS:
                self.assertTrue((mf.parent / slot).is_file(), slot)

    def test_a_legacy_uppercase_slot_is_refused_never_renamed_or_twinned(self):
        # The uppercase->lowercase migration is COMPLETE in every consumer and
        # the rename machinery is retired. The CHOSEN successor behavior: a
        # leftover case variant is a refusal that names it and the canonical
        # name — never a rename, and never a `decisions.md` minted beside
        # `DECISIONS.md` (a twin on a case-sensitive filesystem, a truncation
        # of the legacy bytes on an insensitive one).
        with tree(story_statuses=('todo',)) as root:
            mdir = root / 'pm/roadmap/0.1-demo'
            legacy = mdir / 'DECISIONS.md'
            model.write_raw(legacy, LEGACY_LOG)
            code, out = run_cli(root, 'new', 'milestone', '0.1')
            self.assertEqual(code, 1, out)
            self.assertIn('REFUSED', out)
            self.assertIn('DECISIONS.md', out)
            self.assertIn('decisions.md', out)
            self.assertIn('nothing was written', out)
            entries = model.dir_entries(mdir)
            # EXACT names: on macOS `exists('decisions.md')` answers True off
            # the DECISIONS.md sitting there, so only a listing can prove no
            # twin was minted and no rename ran.
            self.assertEqual(entries.get('DECISIONS.md'), 'file')
            self.assertNotIn('decisions.md', entries)
            self.assertNotIn('handoff.md', entries)
            self.assertEqual(model.read_raw(legacy), LEGACY_LOG)

    def test_new_refuses_a_file_slot_that_exists_as_a_directory(self):
        # Rule 6 reserves exit 1 for FINDINGS, so an uncaught IsADirectoryError
        # reads to a consumer's hook as "drift found" with a traceback attached.
        # ScaffoldRefused is the shape, and it refuses before anything moves.
        with tree(story_statuses=('todo',)) as root:
            mdir = root / 'pm/roadmap/0.1-demo'
            (mdir / model.DECISION_FILE_NAME).mkdir()
            code, out = run_cli(root, 'new', 'milestone', '0.1')
            self.assertEqual(code, 1, out)
            self.assertIn('REFUSED', out)
            self.assertIn('is a DIRECTORY', out)
            self.assertIn('nothing was written', out)
            self.assertFalse((mdir / 'handoff.md').exists())

    def test_new_refuses_a_slot_it_cannot_prepend_a_header_to(self):
        # `_fill_header` guarded the READ and not the write, so a read-only
        # legacy doc raised `PermissionError` — a traceback, exit 1, and the
        # remaining slots never created. Writability is inspectable up front.
        with tree(story_statuses=('todo',)) as root:
            mdir = root / 'pm/roadmap/0.1-demo'
            model.write_raw(mdir / 'handoff.md', 'legacy prose\n')
            model.write_raw(mdir / 'decisions.md', LEGACY_LOG)
            (mdir / 'handoff.md').chmod(0o444)
            try:
                code, out = run_cli(root, 'new', 'milestone', '0.1')
                self.assertEqual(code, 1, out)
                self.assertIn('is not writable', out)
                self.assertIn('nothing was written', out)
                self.assertNotIn('Traceback', out)
                self.assertEqual(model.read_raw(mdir / 'decisions.md'), LEGACY_LOG)
            finally:
                (mdir / 'handoff.md').chmod(0o644)
            # And it goes through once the mode allows it.
            self.assertEqual(run_cli(root, 'new', 'milestone', '0.1')[0], 0)
            self.assertTrue((mdir / 'handoff.md').is_file())

    def test_new_refuses_an_undecodable_template_before_the_first_write(self):
        # A latin-1 byte in a project's `template_dir` raised
        # `UnicodeDecodeError` from inside the slot loop, two files in. Every
        # template the grain needs is loaded and decoded before anything lands.
        with tree(story_statuses=('todo',)) as root:
            (root / 'devkit.toml').write_text(
                '[pm]\ntemplate_dir = "pm/templates"\n', encoding='utf-8')
            self.assertEqual(run_cli(root, 'templates')[0], 0)
            (root / 'pm/templates/milestone.md').write_bytes(b'caf\xe9\n')
            (root / 'pm/roadmap/0.1-demo/milestone.md').unlink()
            code, out = run_cli(root, 'new', 'milestone', '0.1')
            self.assertEqual(code, 1, out)
            self.assertIn('template cannot be read', out)
            self.assertIn('nothing was written', out)
            self.assertNotIn('Traceback', out)
            self.assertFalse((root / 'pm/roadmap/0.1-demo/milestone.md').exists())

    def test_decide_refuses_an_undecodable_decisions_template(self):
        # `pm decide` mints the log on first write, so the decode that used to
        # happen inside `pm new` now happens here — and it refuses the same
        # way, with the grain byte-identical.
        with tree(story_statuses=('todo',)) as root:
            (root / 'devkit.toml').write_text(
                '[pm]\ntemplate_dir = "pm/templates"\n', encoding='utf-8')
            self.assertEqual(run_cli(root, 'templates')[0], 0)
            (root / 'pm/templates/decisions.md').write_bytes(b'caf\xe9\n')
            code, out = run_cli(root, 'decide', '0.1', 'a choice')
            self.assertEqual(code, 2, out)
            self.assertIn('template cannot be read', out)
            self.assertNotIn('Traceback', out)
            self.assertFalse(
                (root / 'pm/roadmap/0.1-demo/decisions.md').exists())

    def test_new_reports_a_write_that_no_listing_could_have_predicted(self):
        # Not everything is pre-inspectable — a mode changed under us, a disk
        # that fills. Rule 6 still holds: exit 1 is a finding a consumer's hook
        # can print, so the escaping exception becomes a refusal that names
        # exactly which slots did land rather than a stack trace over them.
        with tree(story_statuses=('todo',)) as root:
            gdir = root / 'pm/roadmap/0.2-second'
            real = templates.write

            def flaky(path: Path, text: str) -> None:
                if path.name == 'milestone.md':
                    raise OSError(28, 'No space left on device')
                real(path, text)

            with unittest.mock.patch.object(templates, 'write', flaky):
                code, out = run_cli(root, 'new', 'milestone', '0.2', 'Second')
            self.assertEqual(code, 1, out)
            self.assertNotIn('Traceback', out)
            self.assertIn('No space left on device', out)
            self.assertIn('PART-FILLED', out)
            # The grain file is the FIRST write, so the honest report is that
            # nothing had landed — the claim has to track the truth in both
            # directions, not only when something did.
            self.assertIn('nothing had been written yet', out)
            self.assertFalse((gdir / 'features').exists())

    def test_new_refuses_a_slot_that_is_a_symlink_out_of_the_grain(self):
        # `_fill_header` followed it and rewrote a file the verb was never
        # pointed at. A write verb stays inside the grain it was asked to fill.
        with tree(story_statuses=('todo',)) as root:
            mdir = root / 'pm/roadmap/0.1-demo'
            outside = root / 'outside.md'
            model.write_raw(outside, 'OUTSIDE\n')
            (mdir / 'decisions.md').symlink_to(outside)
            code, out = run_cli(root, 'new', 'milestone', '0.1')
            self.assertEqual(code, 1, out)
            self.assertIn('is a SYMLINK', out)
            self.assertIn('nothing was written', out)
            self.assertEqual(model.read_raw(outside), 'OUTSIDE\n')
            self.assertFalse((mdir / 'handoff.md').exists())

    def test_a_symlinked_slot_is_named_a_LINK_even_when_it_points_at_a_dir(self):
        # `dir_entries` classifies with `is_dir()`, which FOLLOWS the link, so a
        # link to a directory got the DIRECTORY refusal: refused correctly, and
        # then told to move aside a directory that is not in the grain at all.
        with tree(story_statuses=('todo',)) as root:
            mdir = root / 'pm/roadmap/0.1-demo'
            outside = root / 'outside'
            outside.mkdir()
            (mdir / 'decisions.md').symlink_to(outside)
            code, out = run_cli(root, 'new', 'milestone', '0.1')
            self.assertEqual(code, 1, out)
            self.assertIn('is a SYMLINK', out)
            self.assertNotIn('is a DIRECTORY', out)

    def test_new_never_stacks_a_second_header_on_a_doc_that_has_one(self):
        with tree(story_statuses=('todo',)) as root:
            mdir = root / 'pm/roadmap/0.1-demo'
            self.assertEqual(run_cli(root, 'new', 'milestone', '0.1')[0], 0)
            model.write_raw(mdir / 'decisions.md',
                            f'{model.SLOT_HEADER["decisions.md"]}\n\n# log\n')
            before = (mdir / 'decisions.md').read_text(encoding='utf-8')
            self.assertEqual(run_cli(root, 'new', 'milestone', '0.1')[0], 0)
            self.assertEqual((mdir / 'decisions.md').read_text(encoding='utf-8'),
                             before)

    def test_new_needs_a_name_only_when_the_grain_does_not_exist(self):
        with tree(story_statuses=('todo',)) as root:
            code, out = run_cli(root, 'new', 'milestone', '0.2')
            self.assertEqual(code, 2, out)
            self.assertIn('needs a name', out)

    def test_new_mints_no_shared_doc_and_repairs_the_header_of_one_present(self):
        # BOTH halves. `pm new` stopped CREATING a shared doc — that scaffolded
        # 204 empty files into one consumer's tree — and still MANAGES one that
        # exists, which is what a migration needs.
        with tree(story_statuses=('todo',)) as root:
            mdir = root / 'pm/roadmap/0.1-demo'
            self.assertEqual(run_cli(root, 'new', 'milestone', '0.1')[0], 0)
            for slot in model.MILESTONE_OPTIONAL_SLOTS:
                self.assertFalse((mdir / slot).exists(), slot)
            for slot, want in model.SLOT_HEADER.items():
                (mdir / slot).write_text('# headerless\n', encoding='utf-8')
                self.assertEqual(run_cli(root, 'new', 'milestone', '0.1')[0], 0)
                self.assertEqual(model.header_of(mdir / slot), want, slot)
                self.assertIn('# headerless',
                              (mdir / slot).read_text(encoding='utf-8'))

    def test_a_name_the_filesystem_refuses_is_a_refusal_not_a_traceback(self):
        # The grain DIRECTORY was the last unguarded write: `gdir.mkdir` on a
        # name too long for the filesystem came out as an OSError traceback
        # under exit 1, and exit 1 is what a consumer's pre-push hook reads as
        # "drift found".
        with tree(story_statuses=('todo',)) as root:
            code, out = run_cli(root, 'new', 'milestone', '0.2-' + 'a' * 300,
                                'Too Long')
            self.assertEqual(code, 1, out)
            self.assertNotIn('Traceback', out)
            self.assertIn('REFUSED', out)
            self.assertIn('could not be created', out)
            self.assertIn('nothing was written', out)

    def test_new_story_and_new_bug_refuse_a_name_the_filesystem_rejects(self):
        # Those two write straight rather than through the scaffolder, so
        # neither guard `new` grew ever covered them.
        with tree(story_statuses=('todo',)) as root:
            for argv in (('new', 'story', '0.1/alpha', 'a' * 300, 'S'),
                         ('new', 'bug', '0.1', 'a' * 300)):
                code, out = run_cli(root, *argv)
                self.assertEqual(code, 1, out)
                self.assertNotIn('Traceback', out)
                self.assertIn('nothing was written', out)

    def test_the_same_pm_new_refuses_on_every_supported_python(self):
        # `Path.exists()` raises OSError on an over-long name up to 3.13 and
        # answers False from 3.14 on, so the verb came out as a traceback or as
        # a refusal depending on which interpreter `uvx` picked.
        from godot_devkit.repo.pm import cli as pm_cli
        with tree(story_statuses=('todo',)) as root:
            self.assertFalse(pm_cli._exists(root / ('a' * 300)))

    def test_an_unwritable_roadmap_dir_is_a_refusal_not_a_traceback(self):
        # The same unguarded call from the other side, and the claim is
        # honest here: nothing has been written when the mkdir fails.
        with tree(story_statuses=('todo',)) as root:
            rdir = root / 'pm/roadmap'
            rdir.chmod(0o555)
            try:
                code, out = run_cli(root, 'new', 'milestone', '0.2', 'Next')
                self.assertEqual(code, 1, out)
                self.assertNotIn('Traceback', out)
                self.assertIn('nothing was written', out)
                self.assertFalse((rdir / '0.2-next').exists())
            finally:
                rdir.chmod(0o755)
            self.assertEqual(run_cli(root, 'new', 'milestone', '0.2', 'Next')[0], 0)


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


class ConfigValidation(unittest.TestCase):
    """A malformed `[pm]` must never narrow the gate into a rubber stamp.

    A bare string iterates into characters and a table into keys, so an
    unvalidated `checks` silently disables every rule and prints PASS over real
    drift. Each case here is a plausible authoring mistake.
    """

    def _drifted(self, root: Path) -> None:
        write(root / 'pm/roadmap/0.1-demo/features/alpha/stories/s0.md',
              {'id': '0.1/alpha/s0', 'feature': '0.1/alpha', 'milestone': '"0.1"',
               'name': 'S0', 'status': 'banana'})

    def test_bad_checks_is_a_config_error_not_a_pass(self):
        for bad in ('checks = "D1"', 'checks = ["D99"]', 'checks = ["d1","d4"]',
                    'checks = 7', 'checks = []', 'checks = { a = 1 }'):
            with self.subTest(bad=bad), tree(story_statuses=('todo',)) as root:
                self._drifted(root)
                (root / 'devkit.toml').write_text(f'[pm]\n{bad}\n', encoding='utf-8')
                code, _ = run_gate(root)
                # 2 = config error. NEVER 0 — that is the rubber stamp.
                self.assertEqual(code, 2, f'{bad!r} must not be accepted')

    def test_other_scalar_type_errors_are_also_exit_2(self):
        for bad in ('review_slug_fallback = "yes"',
                    'roadmap_dir = 3'):
            with self.subTest(bad=bad), tree() as root:
                (root / 'devkit.toml').write_text(f'[pm]\n{bad}\n', encoding='utf-8')
                self.assertEqual(run_gate(root)[0], 2)

    def test_a_valid_subset_still_narrows_correctly(self):
        with tree(story_statuses=('todo',)) as root:
            self._drifted(root)
            (root / 'devkit.toml').write_text(
                '[pm]\nchecks = ["D1","D2"]\n', encoding='utf-8')
            code, out = run_gate(root)
            self.assertEqual(code, 0, out)   # D4 is off, so the bogus status is quiet


class AStaleRuleIdStopsTheGATE_NotTheReadVerbs(unittest.TestCase):
    """One retired id in `[pm] checks` must not take the whole CLI down.

    A version bump that retires a rule is exactly what leaves a stale id in a
    consumer's config, and one consumer names sixteen rules explicitly. Raised
    from `model.load()`, that typo killed `pm status`, `pm get`, `pm new`,
    `pm validate`, `pm vocabulary --json` and `check pm` at exit 2 together —
    so the consumer could neither read its own tree nor ask
    the tool what the new vocabulary is while deciding what to do about it.

    The strictness is right; the placement was not. The GATES refuse, because
    a narrowed roster is a lie told by a gate. Everything that only READS is
    still readable.
    """

    STALE = '[pm]\nchecks = ["D1","D2","D3","D4","D5","D6","D99"]\n'

    def test_the_read_verbs_still_run(self):
        with tree(story_statuses=('todo',)) as root:
            (root / 'devkit.toml').write_text(self.STALE, encoding='utf-8')
            for argv in (('status',), ('vocabulary', '--json'),
                         ('get', '0.1/alpha', 'status'),
                         ('new', 'story', '0.1/alpha', 's9', 'S9')):
                with self.subTest(argv=argv):
                    code, out = run_cli(root, *argv)
                    self.assertEqual(code, 0, out)
            self.assertIn('milestone 0.1', run_cli(root, 'status')[1])

    def test_a_write_verb_still_runs(self):
        with tree(story_statuses=('todo',)) as root:
            (root / 'devkit.toml').write_text(self.STALE, encoding='utf-8')
            code, out = run_cli(root, 'story', 'wip', '0.1/alpha/s0')
            self.assertEqual(code, 0, out)

    def test_the_two_gates_refuse_loudly_and_name_the_id(self):
        with tree(story_statuses=('todo',)) as root:
            (root / 'devkit.toml').write_text(self.STALE, encoding='utf-8')
            code, out = run_gate(root)
            self.assertEqual(code, 2, out)
            code, out = run_cli(root, 'validate')
            self.assertEqual(code, 2, out)
            self.assertIn('D99', out)


class FlowChecks(unittest.TestCase):
    """D8/D9 — branch-per-milestone + bump-at-start. Off unless opted into."""

    ON = '[pm]\nchecks = ["D8","D9"]\n'

    def _building(self, root: Path, branch: str = '', version: str = '0.1.0'):
        model.set_field(root / 'pm/roadmap/0.1-demo/milestone.md', 'status', 'building')
        if branch:
            model.set_field(root / 'pm/roadmap/0.1-demo/milestone.md', 'branch', branch)
        if version:
            (root / 'project.godot').write_text(
                f'[application]\nconfig/version="{version}"\n', encoding='utf-8')

    def test_off_by_default(self):
        # A project bumping at close is running a different valid flow, not
        # drifting — the stock gate must stay silent about it.
        with tree(story_statuses=('todo',)) as root:
            self._building(root, version='9.9.9')
            code, out = run_gate(root)
            self.assertEqual(code, 0, out)

    def test_d8_version_must_equal_the_building_milestone_id(self):
        with tree(story_statuses=('todo',)) as root:
            self._building(root, branch='staging', version='9.9.9')
            (root / 'devkit.toml').write_text(self.ON, encoding='utf-8')
            code, out = run_gate(root)
            self.assertEqual(code, 1)
            self.assertIn('does not match the building milestone', out)

    def test_d8_passes_on_an_exact_match(self):
        with tree(story_statuses=('todo',)) as root:
            self._building(root, branch='staging', version='0.1')
            (root / 'devkit.toml').write_text(self.ON, encoding='utf-8')
            code, out = run_gate(root)
            self.assertEqual(code, 0, out)

    def test_d9_requires_a_branch_stamp(self):
        with tree(story_statuses=('todo',)) as root:
            self._building(root, version='0.1')
            (root / 'devkit.toml').write_text(self.ON, encoding='utf-8')
            code, out = run_gate(root)
            self.assertEqual(code, 1)
            self.assertIn('declares no branch:', out)


class ThePMTrackerNeverMovesYourCheckout(unittest.TestCase):
    """`pm milestone building` ran `git checkout` in the trunk worktree.

    Behind it were six refusal paths and not one of them was "this input is
    malformed or absent" — every one was "a git worktree elsewhere on your disk
    is not how I want it": a dirty trunk, a branch another worktree holds, a
    branch that does not exist, an unreadable status. A PM tracker that mutates
    your VCS checkout is the failure mode this whole change removes, and it
    reached for it on the way past a status flip.

    D9 stays: a `building` milestone declaring `branch:` is a required field in
    a state, which is a fact about the file. Whether a checkout somewhere obeys
    it is not.
    """

    MFILE = 'pm/roadmap/0.1-demo/milestone.md'
    BRANCH = 'feat/0.1-demo'

    @staticmethod
    def _git(root: Path, *args: str):
        return subprocess.run(
            ['git', '-c', 'user.email=t@example.invalid', '-c', 'user.name=T',
             *args], cwd=root, capture_output=True, text=True, check=True)

    # The key set to `true` on purpose: these measure it having NO effect. It
    # is the spelling one consumer ships, so this is the pin-bump case.
    ON = '[pm]\nplace_branch_on_building = true\n'

    def _prepare(self, root: Path) -> None:
        model.set_field(root / self.MFILE, 'status', 'ready')
        model.set_field(root / self.MFILE, 'branch', self.BRANCH)
        (root / 'devkit.toml').write_text(self.ON, encoding='utf-8')
        self._git(root, 'add', '-A')
        self._git(root, 'commit', '-q', '-m', 'fixture')
        self._git(root, 'branch', self.BRANCH)

    def test_the_flip_lands_and_the_checkout_does_not_move(self):
        with tree(story_statuses=('todo',)) as root:
            self._prepare(root)
            before = self._git(root, 'branch', '--show-current').stdout.strip()
            code, out = run_cli(root, 'milestone', 'building', '0.1')
            self.assertEqual(code, 0, out)
            self.assertEqual(
                model.field_of(root / self.MFILE, 'status'), 'building')
            after = self._git(root, 'branch', '--show-current').stdout.strip()
            self.assertEqual(before, after)
            self.assertNotIn('checked out', out)

    def test_a_dirty_tree_is_none_of_its_business(self):
        # It used to refuse here — a status flip declining to happen because an
        # unrelated file was uncommitted.
        with tree(story_statuses=('todo',)) as root:
            self._prepare(root)
            (root / 'dirty.txt').write_text('x', encoding='utf-8')
            code, out = run_cli(root, 'milestone', 'building', '0.1')
            self.assertEqual(code, 0, out)
            self.assertEqual(
                model.field_of(root / self.MFILE, 'status'), 'building')

    def test_a_branch_that_does_not_exist_is_none_of_its_business_either(self):
        with tree(story_statuses=('todo',)) as root:
            model.set_field(root / self.MFILE, 'branch', 'feat/never-created')
            (root / 'devkit.toml').write_text(self.ON, encoding='utf-8')
            self._git(root, 'add', '-A')
            self._git(root, 'commit', '-q', '-m', 'fixture')
            code, out = run_cli(root, 'milestone', 'building', '0.1')
            self.assertEqual(code, 0, out)

    def test_the_rule_is_gone_and_the_gate_says_so(self):
        with tree(story_statuses=('todo',)) as root:
            (root / 'devkit.toml').write_text(
                '[pm]\nchecks = ["D10"]\n', encoding='utf-8')
            code, out = run_gate(root)
            self.assertEqual(code, 2, out)
        self.assertNotIn('D10', model.KNOWN_CHECKS)
        self.assertFalse(hasattr(model.PmConfig, 'place_branch_on_building'))
        self.assertFalse(hasattr(model.PmConfig, 'trunk_branches'))

    def test_a_retired_KEY_is_named_by_the_gate_never_silently_ignored(self):
        # A config key that does nothing is worse than one that errors: the
        # author believes it took effect. Reported where a stale rule id is —
        # on the gate, so the read verbs keep working through the pin bump.
        with tree(story_statuses=('todo',)) as root:
            (root / 'devkit.toml').write_text(self.ON, encoding='utf-8')
            from godot_devkit.core.project import load_config, repo_root
            repo_root.cache_clear()
            load_config.cache_clear()
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
                code = pm_check.run()
            out = buf.getvalue()
            self.assertEqual(code, 2, out)
            self.assertIn('place_branch_on_building was retired', out)
            # ...and `pm status` still runs, which is the whole point.
            self.assertEqual(run_cli(root, 'status')[0], 0)

    def test_the_cli_holds_no_git_checkout_at_all(self):
        source = Path(cli.__file__).read_text(encoding='utf-8')
        for spelling in ('checkout', 'worktree', 'subprocess'):
            self.assertNotIn(spelling, source,
                             f'{spelling} is back in the pm CLI')


class EveryKeyThisReleaseStoppedHonouring(unittest.TestCase):
    """The eleven config surfaces v0.14.0 read and HEAD does not.

    Six were named in `RETIRED_KEYS` when the cuts landed. Ten more `[pm]` keys
    and the whole `[agents]` section went out in the same release and were not,
    so a project declaring them got PASS at exit 0 from both gates — the exact
    thing `RETIRED_KEYS` exists to prevent, and the one that costs most: a
    project that had set `review_min_content_bytes` lost its review-prose floor
    with no word said.

    The keys are enumerated from the source of truth rather than retyped, so a
    key added to the ledger without a test cannot happen and a key removed from
    it cannot leave a test asserting nothing.
    """

    GONE_AT_014 = (
        ('review_min_content_bytes', '400'),
        ('prose_grandfather', '["pm/roadmap/legacy.md"]'),
        ('changelog_grandfather', '["pm/roadmap/legacy.md"]'),
        ('decision_grandfather', '["pm/roadmap/legacy.md"]'),
        ('story_lines_max', '120'),
        ('feature_lines_max', '200'),
        ('bug_lines_max', '125'),
        ('decisions_lines_max', '150'),
        ('changelog_lines_max', '150'),
        ('closed_log_lines_max', '60'),
    )

    @staticmethod
    def _gate(root: Path) -> tuple[int, str]:
        """`check pm` with BOTH streams captured.

        The shared `run_gate` takes stdout only, and a config complaint goes to
        stderr — so a test built on it would assert exit 2 against an empty
        string and pass on any exit-2 whatsoever, including one this fix did not
        cause.
        """
        from godot_devkit.core.project import load_config, repo_root
        repo_root.cache_clear()
        load_config.cache_clear()
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            code = pm_check.run()
        return code, buf.getvalue()

    def test_the_ledger_names_every_one_of_them(self):
        for key, _ in self.GONE_AT_014:
            with self.subTest(key=key):
                self.assertIn(key, model.RETIRED_KEYS)

    def test_the_gate_names_each_key_at_exit_2(self):
        for key, value in self.GONE_AT_014:
            with self.subTest(key=key):
                with tree(story_statuses=('todo',)) as root:
                    (root / 'devkit.toml').write_text(
                        f'[pm]\n{key} = {value}\n', encoding='utf-8')
                    code, out = self._gate(root)
                    self.assertEqual(code, 2, out)
                    self.assertIn(f'{key} was retired', out)

    def test_pm_validate_names_it_too(self):
        with tree(story_statuses=('todo',)) as root:
            (root / 'devkit.toml').write_text(
                '[pm]\nreview_min_content_bytes = 400\n', encoding='utf-8')
            code, out = run_cli(root, 'validate')
            self.assertEqual(code, 2, out)
            self.assertIn('review_min_content_bytes was retired', out)

    def test_a_retired_SECTION_is_named_the_same_way(self):
        # `[agents]` was a whole config surface, and `config_section` cannot
        # tell an absent table from an empty one — both spellings must land.
        for body in ('[agents]\nscope = [".claude/agents/*.md"]\n', '[agents]\n'):
            with self.subTest(body=body):
                with tree(story_statuses=('todo',)) as root:
                    (root / 'devkit.toml').write_text(body, encoding='utf-8')
                    code, out = self._gate(root)
                    self.assertEqual(code, 2, out)
                    self.assertIn('[agents] was retired', out)

    def test_the_read_verbs_keep_working_through_the_pin_bump(self):
        # The placement is the whole point: a project must still be able to
        # read its own tree while deciding what to do about the dead key.
        with tree(story_statuses=('todo',)) as root:
            (root / 'devkit.toml').write_text(
                '[pm]\nstory_lines_max = 120\n\n[agents]\nscope = ["x"]\n',
                encoding='utf-8')
            self.assertEqual(run_cli(root, 'status')[0], 0)
            self.assertEqual(run_cli(root, 'list')[0], 0)
            self.assertEqual(run_cli(root, 'vocabulary', '--json')[0], 0)

    def test_none_of_them_is_read_by_load(self):
        # A ledger entry for a key still being read would be a lie in the other
        # direction. `load()` must not name any of them.
        source = Path(model.__file__).read_text(encoding='utf-8')
        for key, _ in self.GONE_AT_014:
            with self.subTest(key=key):
                self.assertNotIn(f"'pm', '{key}'", source)


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


class StructuralIntegrity(unittest.TestCase):
    def test_a_dir_with_no_grain_file_is_reported_not_skipped(self):
        with tree(story_statuses=('todo',)) as root:
            ghost = root / 'pm/roadmap/0.2-beta/features/gizmo'
            write(ghost / 'feature.md',
                  {'id': '0.2/gizmo', 'milestone': '"0.2"', 'name': 'G',
                   'status': 'done', 'reviewed': ''})
            # 0.2-beta has NO milestone.md, so its drifted feature would
            # otherwise vanish from the scan entirely.
            code, out = run_gate(root)
            self.assertEqual(code, 1)
            self.assertIn('SKIPPED', out)


class NoDeleter(unittest.TestCase):
    """The tracker mostly REPORTS; the one verb that deletes NAMES its target.

    Reproduced on the default roster before `prune` was removed: an OPEN bug
    filed under a `done` milestone, `check pm` PASS, `pm prune`, and the bug
    file was gone. The rule that was supposed to make that impossible (an open
    bug under a done milestone) was opt-in and neither consumer enabled it, so
    nothing at all stood between the two commands. `prune` stays gone, and
    every one of these tests still holds for it.

    If archive sprawl needs an answer it is a READ verb — that is still true.
    What changed at 0.16.0 is `pm retire <milestone-id>`, the OPPOSITE shape
    from `prune`: one milestone, spelled out on the command line by the
    caller every time, never a sweep the tool decides the scope of on its
    own. `test_the_pm_cli_carries_no_recursive_delete` below is narrowed to
    let exactly that one command through — see it for why the shape still
    holds everywhere else.
    """

    def _commit(self, root: Path) -> None:
        for args in (['add', '-A'], ['-c', 'user.email=t@t', '-c', 'user.name=t',
                                     'commit', '-qm', 'x']):
            subprocess.run(['git', *args], cwd=root, check=True,
                           capture_output=True)

    def _two_closed_milestones_and_an_open_bug(self, root: Path) -> Path:
        write(root / 'pm/roadmap/0.2-later/milestone.md',
              {'id': '"0.2"', 'name': 'Later', 'status': 'done'})
        bug = root / 'pm/roadmap/0.1-demo/bugs/seed-is-zero.md'
        write(bug, {'id': '0.1/bugs/seed-is-zero', 'milestone': '"0.1"',
                    'status': 'open'})
        return bug

    def test_the_open_bug_under_the_cooled_milestone_survives(self):
        with tree(milestone_status='done', feature_status='done',
                  story_statuses=('done',)) as root:
            bug = self._two_closed_milestones_and_an_open_bug(root)
            self._commit(root)
            code, out = run_cli(root, 'prune')
            self.assertEqual(code, 2, out)
            self.assertIn('unknown command', out)
            self.assertTrue(bug.is_file(), 'the bug file was deleted')
            self.assertTrue((root / 'pm/roadmap/0.1-demo/milestone.md').is_file())

    def test_two_closed_milestones_are_a_fact_not_a_gate_failure(self):
        # The other half: the gate used to REDDEN until the destructive verb
        # was run, so a green build depended on a deletion whose scope the
        # person running it did not choose.
        with tree(milestone_status='done', feature_status='done',
                  story_statuses=('done',)) as root:
            self._two_closed_milestones_and_an_open_bug(root)
            code, out = run_gate(root)
            self.assertEqual(code, 0, out)

    def test_an_archive_directory_is_not_a_gate_failure_either(self):
        with tree(milestone_status='building') as root:
            (root / 'pm/roadmap/zz_archive').mkdir(parents=True)
            (root / 'pm/roadmap/zz_archive/note.md').write_text('x\n',
                                                               encoding='utf-8')
            code, out = run_gate(root)
            self.assertEqual(code, 0, out)

    def test_the_pm_cli_carries_no_recursive_delete_OUTSIDE_cmd_retire(self):
        # The shape, not the instance: any function OTHER than the one that
        # is `pm retire`'s own implementation reaching for one of these is
        # `prune` wearing a different name. Narrowed to `cmd_retire`'s own
        # body — not dropped — so the guard still catches a delete that
        # turns up in `cmd_bug`, `cmd_move`, or anywhere else future work
        # adds a verb.
        source = Path(cli.__file__).read_text(encoding='utf-8')
        lines = source.split('\n')
        start = next(i for i, line in enumerate(lines)
                     if line.startswith('def cmd_retire('))
        end = next(i for i in range(start + 1, len(lines))
                   if lines[i].startswith('def '))
        retire_body = '\n'.join(lines[start:end])
        rest = '\n'.join(lines[:start] + lines[end:])
        for spelling in ('remove_tree', 'rmtree', "'rm'", 'unlink', 'delete_tree'):
            self.assertNotIn(spelling, rest,
                             f'{spelling} is back in the pm CLI outside '
                             f'cmd_retire')
        self.assertIn('delete_tree', retire_body,
                      "cmd_retire no longer deletes anything — this test's "
                      'own fixture has gone stale')

    def test_the_retired_rules_are_not_silently_accepted_names(self):
        # A retired id must not linger in KNOWN_CHECKS: a name that parses but
        # runs nothing is a gate a consumer believes is on.
        for retired in ('D7', 'D14'):
            self.assertNotIn(retired, model.KNOWN_CHECKS)


class IdsAreLiterals(unittest.TestCase):
    def test_a_glob_never_resolves_to_a_grain(self):
        with tree() as root:
            for bad in ('*', '0.?', '0.1/*'):
                with self.subTest(bad=bad):
                    self.assertEqual(run_cli(root, 'milestone', 'ready', bad)[0], 2)


class Validate(unittest.TestCase):
    """Structural + referential integrity — a different question from drift.

    A tree can be perfectly undrifted and still depend on a feature that does
    not exist.
    """

    def _run(self, root: Path):
        from godot_devkit.repo.pm import validate
        return validate.run(model.PmConfig(root=root))

    def test_a_clean_tree_validates(self):
        with tree(story_statuses=('todo',)) as root:
            findings, census = self._run(root)
            self.assertEqual(findings, [])
            self.assertEqual(census['grains'], 3)

    def test_v2_id_must_match_path(self):
        with tree() as root:
            ff = root / 'pm/roadmap/0.1-demo/features/alpha/feature.md'
            model.set_field(ff, 'id', '0.1/WRONG')
            findings, _ = self._run(root)
            self.assertTrue(any('does not match its path' in f for f in findings))

    def test_v3_parentage_must_be_consistent(self):
        with tree(story_statuses=('todo',)) as root:
            sf = root / 'pm/roadmap/0.1-demo/features/alpha/stories/s0.md'
            model.set_field(sf, 'feature', '0.1/somewhere-else')
            findings, _ = self._run(root)
            self.assertTrue(any('but it lives under feature' in f for f in findings))

    def test_v4_a_dangling_ref_inside_the_tree_is_a_finding(self):
        with tree() as root:
            ff = root / 'pm/roadmap/0.1-demo/features/alpha/feature.md'
            model.set_field(ff, 'depends_on', '["0.1/no-such-feature"]')
            findings, _ = self._run(root)
            self.assertTrue(any('resolves to nothing' in f for f in findings))

    def test_v4_a_ref_into_a_pruned_milestone_is_unverifiable_not_a_finding(self):
        # Git history is the archive: depending on a milestone that has been
        # pruned is expected, so it is censused rather than failed.
        with tree() as root:
            ff = root / 'pm/roadmap/0.1-demo/features/alpha/feature.md'
            model.set_field(ff, 'depends_on', '["0.0.9/long-gone"]')
            findings, census = self._run(root)
            self.assertEqual(findings, [])
            self.assertEqual(census['unverifiable'], 1)

    def test_v5_detects_a_dependency_cycle(self):
        with tree() as root:
            run_cli(root, 'new', 'feature', '0.1', 'beta', 'Beta')
            fdir = root / 'pm/roadmap/0.1-demo/features'
            model.set_field(fdir / 'alpha/feature.md', 'depends_on', '["0.1/beta"]')
            model.set_field(fdir / 'beta/feature.md', 'depends_on', '["0.1/alpha"]')
            findings, _ = self._run(root)
            self.assertTrue(any('CYCLE' in f for f in findings), findings)

    def test_phase_monotone_is_satisfied_in_the_right_order(self):
        with tree() as root:
            run_cli(root, 'new', 'feature', '0.1', 'beta', 'Beta')
            fdir = root / 'pm/roadmap/0.1-demo/features'
            model.set_field(fdir / 'alpha/feature.md', 'phase', '2')
            model.set_field(fdir / 'alpha/feature.md', 'depends_on', '["0.1/beta"]')
            model.set_field(fdir / 'beta/feature.md', 'phase', '1')
            self.assertEqual(self._run(root)[0], [])

    def test_the_verb_refuses_an_empty_tree_instead_of_saying_VALID(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'repo'
            (root / 'pm' / 'roadmap').mkdir(parents=True)
            subprocess.run(['git', 'init', '-q'], cwd=root, check=True)
            previous = Path.cwd()
            os.chdir(root)
            try:
                code, _ = run_cli(root, 'validate')
            finally:
                os.chdir(previous)
            self.assertEqual(code, 2)

    def test_the_gate_runs_the_same_predicates(self):
        # One definition, two readers: a dangling ref must fail `check pm` too.
        with tree(story_statuses=('todo',)) as root:
            ff = root / 'pm/roadmap/0.1-demo/features/alpha/feature.md'
            model.set_field(ff, 'depends_on', '["0.1/no-such-feature"]')
            code, out = run_gate(root)
            self.assertEqual(code, 1)
            self.assertIn('resolves to nothing', out)


class Guidance(unittest.TestCase):
    """`pm install-skills` / `pm init` — the shared doctrine, and only that."""

    def test_install_writes_a_rule_and_a_skill(self):
        with tree() as root:
            code, out = run_cli(root, 'install-skills')
            self.assertEqual(code, 0, out)
            rule = root / '.claude/rules/pm-execution.md'
            skill = root / '.claude/skills/pm-operations/SKILL.md'
            self.assertTrue(rule.is_file())
            self.assertTrue(skill.is_file())
            # The rule must AUTO-LOAD: without a paths: header it only applies
            # when someone thinks to ask for it, which defeats the purpose.
            self.assertIn('paths:', rule.read_text().split('---')[1])

    def test_install_is_idempotent(self):
        with tree() as root:
            run_cli(root, 'install-skills')
            code, out = run_cli(root, 'install-skills')
            self.assertEqual(code, 0)
            self.assertIn('already current', out)

    def test_diff_shows_what_an_install_would_change_and_writes_nothing(self):
        """The fourth install verb answers --diff off the SAME helper the
        install-* verbs use, so the four cannot print four kinds of diff."""
        with tree() as root:
            rule = root / '.claude/rules/pm-execution.md'
            rule.parent.mkdir(parents=True, exist_ok=True)
            rule.write_text('# our own version\n', encoding='utf-8')
            code, out = run_cli(root, 'install-skills', '--diff')
            self.assertEqual(code, 0, out)
            self.assertIn('--- a/.claude/rules/pm-execution.md', out)
            self.assertIn('-# our own version', out)
            self.assertIn('.claude/skills/pm-operations/SKILL.md does not exist',
                          out)
            self.assertEqual(rule.read_text(), '# our own version\n')
            self.assertFalse(
                (root / '.claude/skills/pm-operations/SKILL.md').exists())

    def test_install_refuses_to_clobber_a_file_it_did_not_write(self):
        with tree() as root:
            rule = root / '.claude/rules/pm-execution.md'
            rule.parent.mkdir(parents=True, exist_ok=True)
            rule.write_text('# our own version\n', encoding='utf-8')
            code, out = run_cli(root, 'install-skills')
            self.assertEqual(code, 1)
            self.assertIn('differs from what this would write', out)
            self.assertEqual(rule.read_text(), '# our own version\n')

    def test_a_collision_on_the_SECOND_entry_installs_neither(self):
        """The rule installed, the skill refused, and the operator was told
        nothing was written about a repo that now held one of the two. Every
        collision in the plan is decided before the first write."""
        with tree() as root:
            rule = root / '.claude/rules/pm-execution.md'
            skill = root / '.claude/skills/pm-operations/SKILL.md'
            skill.parent.mkdir(parents=True, exist_ok=True)
            skill.write_text('# our own operations manual\n', encoding='utf-8')
            code, out = run_cli(root, 'install-skills')
            self.assertEqual(code, 1, out)
            self.assertFalse(
                rule.exists(),
                'the FIRST entry was installed before the SECOND was refused')
            self.assertEqual(skill.read_text(), '# our own operations manual\n')
            self.assertNotIn('installed', out)

    def test_both_collisions_are_named_in_one_refusal(self):
        with tree() as root:
            for rel in ('.claude/rules/pm-execution.md',
                        '.claude/skills/pm-operations/SKILL.md'):
                target = root / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text('# ours\n', encoding='utf-8')
            code, out = run_cli(root, 'install-skills')
            self.assertEqual(code, 1)
            self.assertIn('pm-execution.md', out)
            self.assertIn('SKILL.md', out)

    def test_the_plural_refusal_reads_as_a_sentence(self):
        """It did not. With two collisions this printed

            "    .claude/rules/pm-execution.md
                 .claude/skills/pm-operations/SKILL.md exist and were not
                 generated by this tool"

        — the list where the subject goes, so the sentence trails off. The
        install verbs in repo/install.py formatted the same refusal correctly
        and this was a second copy; both now come from one formatter."""
        with tree() as root:
            for rel in ('.claude/rules/pm-execution.md',
                        '.claude/skills/pm-operations/SKILL.md'):
                target = root / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text('# ours\n', encoding='utf-8')
            code, out = run_cli(root, 'install-skills')
        self.assertEqual(code, 1)
        self.assertIn('2 destinations exist and differ from what this', out)
        # The count opens the sentence; the paths are listed under it.
        head = out.partition('2 destinations')[2].partition('\n')[0]
        self.assertNotIn('.claude', head, out)

    def test_a_destination_that_cannot_be_written_refuses_before_any_write(self):
        """The all-or-nothing property covered collisions only: a destination
        that is a DIRECTORY tracebacked out of `write_text` with the first file
        already on disk."""
        with tree() as root:
            skill = root / '.claude/skills/pm-operations/SKILL.md'
            skill.mkdir(parents=True)
            code, out = run_cli(root, 'install-skills')
            self.assertEqual(code, 1, out)
            self.assertIn('is a directory', out)
            self.assertIn('Nothing was written', out)
            self.assertFalse((root / '.claude/rules/pm-execution.md').exists(),
                             'the FIRST entry was written before the SECOND '
                             'was found unwritable')

    def test_force_overwrites_and_updates_a_stale_generated_file(self):
        with tree() as root:
            rule = root / '.claude/rules/pm-execution.md'
            rule.parent.mkdir(parents=True, exist_ok=True)
            rule.write_text('# ours\n', encoding='utf-8')
            self.assertEqual(run_cli(root, 'install-skills', '--force')[0], 0)
            # A file we DID generate, merely stale, updates without --force.
            rule.write_text(rule.read_text().replace('godot-devkit v', 'godot-devkit v0.0.1 v'),
                            encoding='utf-8')
            self.assertEqual(run_cli(root, 'install-skills')[0], 0)

    def test_init_stands_up_a_usable_tree_from_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'repo'
            root.mkdir()
            subprocess.run(['git', 'init', '-q'], cwd=root, check=True)
            previous = Path.cwd()
            os.chdir(root)
            try:
                self.assertEqual(run_cli(root, 'init')[0], 0)
                # The flow init tells the user to run must actually work.
                self.assertEqual(
                    run_cli(root, 'new', 'milestone', '0.1', 'First')[0], 0)
                self.assertEqual(
                    run_cli(root, 'new', 'feature', '0.1', 'gw', 'GW')[0], 0)
                self.assertEqual(run_cli(root, 'validate')[0], 0)
            finally:
                os.chdir(previous)
            self.assertTrue((root / 'pm/roadmap/ROADMAP.md').is_file())
            self.assertTrue((root / '.claude/rules/pm-execution.md').is_file())

    def test_init_is_non_destructive_on_an_existing_tree(self):
        # It fills gaps (a missing ROADMAP.md) but must never disturb grains
        # that are already there.
        with tree(story_statuses=('todo',)) as root:
            ff = root / 'pm/roadmap/0.1-demo/features/alpha/feature.md'
            before = ff.read_bytes()
            index = root / 'pm/roadmap/ROADMAP.md'
            index.write_text('# Ours\n', encoding='utf-8')
            code, out = run_cli(root, 'init')
            self.assertEqual(code, 0, out)
            self.assertEqual(ff.read_bytes(), before)
            self.assertEqual(index.read_text(), '# Ours\n')  # not reseeded
            self.assertEqual(run_cli(root, 'validate')[0], 0)


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


class RefParsing(unittest.TestCase):
    """An unreadable ref list is a FINDING. Never an empty list.

    Returning [] would mean "no refs to check", so a trailing comment or a YAML
    block sequence would take every ref out of V4's reach and still read clean.
    """

    def _with(self, root: Path, raw: str):
        ff = root / 'pm/roadmap/0.1-demo/features/alpha/feature.md'
        self.assertTrue(model.set_field(ff, 'depends_on', raw))
        from godot_devkit.repo.pm import validate
        return validate.run(model.PmConfig(root=root))

    def test_a_dangling_ref_in_the_normal_shape_is_found(self):
        with tree() as root:
            findings, census = self._with(root, '["0.1/ghost"]')
            self.assertTrue(any('resolves to nothing' in f for f in findings))
            self.assertEqual(census['refs'], 1)

    def test_unreadable_shapes_are_reported_not_silently_dropped(self):
        for raw in ('["0.1/ghost"]  # note', '0.1/ghost', '[["0.1/ghost"]]',
                    '["0.1/a, and 0.1/b"]'):
            with self.subTest(raw=raw), tree() as root:
                findings, _ = self._with(root, raw)
                self.assertTrue(findings, f'{raw!r} vanished silently')

    def test_empty_and_null_are_genuinely_empty(self):
        for raw in ('[]', 'null', '~'):
            with self.subTest(raw=raw), tree() as root:
                findings, census = self._with(root, raw)
                self.assertEqual(findings, [])
                self.assertEqual(census['refs'], 0)

    def test_the_ref_census_does_not_depend_on_which_rules_ran(self):
        with tree() as root:
            ff = root / 'pm/roadmap/0.1-demo/features/alpha/feature.md'
            model.set_field(ff, 'depends_on', '["0.1/alpha"]')
            from godot_devkit.repo.pm import validate
            cfg = model.PmConfig(root=root)
            self.assertEqual(validate.run(cfg, {'V1'})[1]['refs'],
                             validate.run(cfg, {'V4'})[1]['refs'])


class FlowRuleEdges(unittest.TestCase):
    def test_d8_refuses_when_two_milestones_are_building(self):
        # A matching sibling used to mask the exact drift D8 exists for.
        with tree(milestone_status='building', story_statuses=('todo',)) as root:
            write(root / 'pm/roadmap/0.2-two/milestone.md',
                  {'id': '"0.2"', 'name': 'Two', 'status': 'building',
                   'branch': 'staging'})
            model.set_field(root / 'pm/roadmap/0.1-demo/milestone.md',
                            'branch', 'staging')
            (root / 'project.godot').write_text(
                '[application]\nconfig/version="0.1"\n', encoding='utf-8')
            (root / 'devkit.toml').write_text(
                '[pm]\nchecks = ["D8"]\n', encoding='utf-8')
            code, out = run_gate(root)
            self.assertEqual(code, 1)
            self.assertIn('milestones are building', out)


class ConfigValueErrors(unittest.TestCase):
    def test_a_bad_version_pattern_is_exit_2_not_a_finding(self):
        for bad in ('version_pattern = "config/version=\\"(.*\\""',
                    'version_pattern = "^config/version=.*$"'):
            with self.subTest(bad=bad), tree() as root:
                (root / 'devkit.toml').write_text(
                    f'[pm]\nchecks = ["D8"]\n{bad}\n', encoding='utf-8')
                self.assertEqual(run_gate(root)[0], 2)

    def test_scaffold_misconfiguration_is_refused_not_ignored(self):
        for bad in ('[pm.scaffold]\nmilestone = "theme,risk"',
                    '[pm.scaffold.epic]\nx = "y"',
                    '[pm.scaffold.story]\ntags = ["a"]'):
            with self.subTest(bad=bad), tree() as root:
                (root / 'devkit.toml').write_text(f'[pm]\n{bad}\n', encoding='utf-8')
                self.assertEqual(run_gate(root)[0], 2)


class NewRefusesUnsafeSlugs(unittest.TestCase):
    def test_a_slug_is_one_path_component_never_a_path(self):
        with tree() as root:
            before = sorted(p.name for p in root.iterdir())
            for bad in ('../../../pwned', 'a/b', '..', '-dash', 'glob*'):
                with self.subTest(bad=bad):
                    code, _ = run_cli(root, 'new', 'bug', '0.1', bad)
                    self.assertEqual(code, 1)
            self.assertEqual(sorted(p.name for p in root.iterdir()), before)

    def test_a_milestone_version_is_validated_too(self):
        with tree() as root:
            self.assertEqual(
                run_cli(root, 'new', 'milestone', '../../oops', 'Name')[0], 1)


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


class Templates(unittest.TestCase):
    def test_new_grains_come_from_templates_and_validate(self):
        with tree() as root:
            self.assertEqual(run_cli(root, 'new', 'feature', '0.1', 'b', 'B')[0], 0)
            ff = root / 'pm/roadmap/0.1-demo/features/b/feature.md'
            self.assertEqual(model.field_of(ff, 'id'), '0.1/b')
            self.assertEqual(model.field_of(ff, 'milestone'), '0.1')
            self.assertEqual(run_cli(root, 'validate')[0], 0)

    def test_a_new_milestone_gets_its_grain_file_under_the_exact_name(self):
        # EXACT names, from a listing: `is_file()` here passed on macOS against
        # the OLD uppercase spellings long after the rename landed, and would
        # have failed in CI on Linux. The slot names are the assertion.
        with tree() as root:
            run_cli(root, 'new', 'milestone', '0.2', 'Second')
            mdir = root / 'pm/roadmap/0.2-second'
            entries = model.dir_entries(mdir)
            for f in model.MILESTONE_FILE_SLOTS:
                self.assertEqual(entries.get(f), 'file', f)
            self.assertIn('# 0.2 — Second', (mdir / 'milestone.md').read_text())

    def test_templates_command_refuses_to_write_past_a_case_variant(self):
        # `is_file()` on macOS answers `decisions.md` with a leftover
        # `DECISIONS.md`, so the install skipped the very name `load` reads —
        # the project's customised template silently ignored, and no message
        # naming the spelling to port it to. Writing it anyway is worse still:
        # `open('decisions.md', 'w')` TRUNCATES the variant sitting there.
        with tree() as root:
            (root / 'devkit.toml').write_text(
                '[pm]\ntemplate_dir = "pm/templates"\n', encoding='utf-8')
            tdir = root / 'pm/templates'
            tdir.mkdir(parents=True)
            mine = 'MINE — a customised decisions template\n'
            model.write_raw(tdir / 'DECISIONS.md', mine)
            code, out = run_cli(root, 'templates')
            self.assertEqual(code, 0, out)
            self.assertIn('is a case variant of decisions.md', out)
            self.assertIn('git mv --force', out)
            self.assertEqual(model.read_raw(tdir / 'DECISIONS.md'), mine)
            self.assertNotIn('decisions.md', model.dir_entries(tdir))

            # Renamed, it is the template the log is MINTED from — the whole
            # point. Through a temp name: a direct rename is a no-op on macOS.
            (tdir / 'DECISIONS.md').rename(tdir / 'x.tmp')
            (tdir / 'x.tmp').rename(tdir / 'decisions.md')
            self.assertEqual(run_cli(root, 'new', 'milestone', '0.3', 'Third')[0], 0)
            self.assertEqual(run_cli(root, 'decide', '0.3', 'a choice')[0], 0)
            self.assertIn('MINE', model.read_raw(
                root / 'pm/roadmap/0.3-third/decisions.md'))

    def test_a_project_template_overrides_the_packaged_one(self):
        with tree() as root:
            (root / 'devkit.toml').write_text(
                '[pm]\ntemplate_dir = "pm/templates"\n', encoding='utf-8')
            tdir = root / 'pm/templates'
            tdir.mkdir(parents=True)
            (tdir / 'story.md').write_text(
                '---\nid: {id}\nfeature: {feature}\nmilestone: "{milestone}"\n'
                'name: {name}\nstatus: todo\nhouse_field: yes\n---\n\n# {name}\n',
                encoding='utf-8')
            run_cli(root, 'new', 'story', '0.1/alpha', 's', 'S')
            sf = root / 'pm/roadmap/0.1-demo/features/alpha/stories/s.md'
            self.assertEqual(model.field_of(sf, 'house_field'), 'yes')

    def test_missing_grains_fall_back_to_the_packaged_template(self):
        # Overriding one grain must not make a project own all of them.
        with tree() as root:
            (root / 'devkit.toml').write_text(
                '[pm]\ntemplate_dir = "pm/templates"\n', encoding='utf-8')
            (root / 'pm/templates').mkdir(parents=True)
            self.assertEqual(run_cli(root, 'new', 'feature', '0.1', 'z', 'Z')[0], 0)

    def test_templates_command_copies_them_out_without_clobbering(self):
        with tree() as root:
            (root / 'devkit.toml').write_text(
                '[pm]\ntemplate_dir = "pm/templates"\n', encoding='utf-8')
            self.assertEqual(run_cli(root, 'templates')[0], 0)
            self.assertTrue((root / 'pm/templates/feature.md').is_file())
            (root / 'pm/templates/feature.md').write_text('mine\n', encoding='utf-8')
            run_cli(root, 'templates')
            self.assertEqual((root / 'pm/templates/feature.md').read_text(), 'mine\n')


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
            self.assertNotIn('->', out)


class EveryConfigSection(unittest.TestCase):
    """The gap that let a false PASS survive a refactor meant to remove it.

    Every exit-2 config assertion lived in test_pm.py, so `[defaults]` kept the
    literal `tuple(cfg.get(...))` CLAUDE.md forbids by name — and a bare-string
    exclude hid two real findings while printing PASS.
    """

    SECTIONS = (
        ('uid', 'exclude_prefixes'), ('tres', 'exclude_prefixes'),
        ('props', 'exclude_prefixes'), ('defaults', 'exclude_prefixes'),
        ('shell', 'roots'), ('doc', 'scope'),
        ('pm', 'checks'),
    )
    BAD = ('"a-string"', '5', '[]', '{ k = 1 }')

    def test_no_section_accepts_a_malformed_list(self):
        from godot_devkit.core.project import load_config, repo_root
        for section, key in self.SECTIONS:
            for bad in self.BAD:
                with self.subTest(section=section, bad=bad), tree() as root:
                    (root / 'devkit.toml').write_text(
                        f'[{section}]\n{key} = {bad}\n', encoding='utf-8')
                    repo_root.cache_clear()
                    load_config.cache_clear()
                    buf = io.StringIO()
                    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
                        from godot_devkit import cli as top
                        code = top.main(['check', section.replace('_', '-')])
                    # 2 = config error. Never 0 (a silent narrowed census) and
                    # never 1 (which CI reads as "drift found").
                    self.assertEqual(code, 2, f'[{section}] {key} = {bad}\n{buf.getvalue()}')

    def test_a_non_table_section_is_refused(self):
        from godot_devkit.core.project import load_config, repo_root
        for section, _ in self.SECTIONS:
            with self.subTest(section=section), tree() as root:
                (root / 'devkit.toml').write_text(f'{section} = "nope"\n', encoding='utf-8')
                repo_root.cache_clear()
                load_config.cache_clear()
                buf = io.StringIO()
                with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
                    from godot_devkit import cli as top
                    code = top.main(['check', section.replace('_', '-')])
                self.assertEqual(code, 2, buf.getvalue())


class FamilySeparation(unittest.TestCase):
    def test_repo_never_imports_godot(self):
        """CLAUDE.md states this invariant; nothing was enforcing it.

        It is what makes rule 2's exit clause ("if pm stops belonging, it
        leaves") a real option rather than a sentiment.
        """
        src = Path(__file__).resolve().parent.parent / 'src' / 'godot_devkit'
        offenders = []
        for path in (src / 'repo').rglob('*.py'):
            text = path.read_text(encoding='utf-8')
            if 'godot_devkit.godot' in text:
                offenders.append(str(path.relative_to(src)))
        self.assertEqual(offenders, [], 'repo/ must not import godot/')

    def test_core_imports_neither_family(self):
        src = Path(__file__).resolve().parent.parent / 'src' / 'godot_devkit'
        offenders = []
        for path in (src / 'core').rglob('*.py'):
            text = path.read_text(encoding='utf-8')
            if 'godot_devkit.godot' in text or 'godot_devkit.repo' in text:
                offenders.append(str(path.relative_to(src)))
        self.assertEqual(offenders, [], 'core/ must know about neither family')


class SkillShape(unittest.TestCase):
    """A flat `.claude/skills/<name>.md` does not load as a skill.

    The one mechanically-decidable FACT the retired `check agents` held: where
    the file sits decides whether its description ever fires, so an otherwise
    perfect skill written flat is inert. It lives in `check doc` now, beside
    the other "does this resolve" facts, and it INFERS nothing — it lists one
    directory.

    Its three neighbours in that gate did infer, and are gone: A1/A2 failed a
    build because a markdown file DESCRIBED a workflow, guessed the subject of
    a line by "exactly one grain word appears" (6 of 8 real mentions came back
    UNVERIFIED), and suppressed an identical finding because the line happened
    to contain the word "not".
    """

    def _doc(self, root: Path) -> tuple[int, str]:
        import importlib
        from godot_devkit.repo.checks import doc
        from godot_devkit.core.project import load_config, repo_root
        repo_root.cache_clear()
        load_config.cache_clear()
        # `doc` binds its root and scope at IMPORT, where production resolves
        # them once per process and the cwd never moves. Tests move it.
        importlib.reload(doc)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = doc.run()
        return code, buf.getvalue()

    def _write(self, root: Path, rel: str, body: str = '# s\n') -> None:
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding='utf-8')

    def test_a_flat_skill_file_is_a_finding(self):
        with tree() as root:
            self._write(root, 'CLAUDE.md', '# c\n')
            self._write(root, '.claude/skills/mine.md')
            code, out = self._doc(root)
            self.assertEqual(code, 1, out)
            self.assertIn('.claude/skills/mine.md', out)
            self.assertIn('does NOT load as a skill', out)

    def test_a_correctly_shaped_skill_and_its_supporting_files_pass(self):
        with tree() as root:
            self._write(root, 'CLAUDE.md', '# c\n')
            self._write(root, '.claude/skills/mine/SKILL.md')
            self._write(root, '.claude/skills/mine/references/api.md')
            code, out = self._doc(root)
            self.assertEqual(code, 0, out)

    def test_the_census_says_what_it_listed(self):
        # Rule 4: "no flat skills" out of an empty directory and out of twelve
        # correctly-shaped ones are different reports.
        with tree() as root:
            self._write(root, 'CLAUDE.md', '# c\n')
            self._write(root, '.claude/skills/one/SKILL.md')
            self._write(root, '.claude/skills/two/SKILL.md')
            code, out = self._doc(root)
            self.assertEqual(code, 0, out)
            self.assertIn('2 .claude/skills/ entr(ies)', out)


class TheAgentsGateIsGone(unittest.TestCase):
    """`check agents` gated ENGLISH PROSE, and it inferred. Both are removed.

    A1 failed a build for a `pm <grain> <verb>` spelling inside a backtick
    span; A2 for a `<state> -> <state>` a graph refused — in a file whose job
    is to DESCRIBE the workflow. A4 was a project-supplied regex over prose.
    None of them is a fact about the tree.
    """

    def test_it_is_not_a_gate_name(self):
        with tree() as root:
            from godot_devkit.core.project import load_config, repo_root
            repo_root.cache_clear()
            load_config.cache_clear()
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
                from godot_devkit import cli as top
                code = top.main(['check', 'agents'])
            self.assertEqual(code, 2, buf.getvalue())
            self.assertIn('unknown check', buf.getvalue())

    def test_a_definition_describing_a_workflow_reddens_nothing(self):
        # The exact text A2 failed on, and the near-identical line it let pass
        # because the word "not" appeared in it.
        with tree() as root:
            d = root / '.claude' / 'rules'
            d.mkdir(parents=True)
            (d / 'r.md').write_text(
                'The milestone lifecycle is planning -> ready -> done.\n'
                'When the story is verified, flip `status: review -> done`.\n'
                'A story does not go review -> done on its own.\n',
                encoding='utf-8')
            (root / 'CLAUDE.md').write_text('# c\n', encoding='utf-8')
            import importlib
            from godot_devkit.repo.checks import doc
            from godot_devkit.core.project import load_config, repo_root
            repo_root.cache_clear()
            load_config.cache_clear()
            importlib.reload(doc)
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                self.assertEqual(doc.run(), 0, buf.getvalue())
        # And there is no other gate left to redden it: the module that held
        # A1/A2/A4 and the two inference helpers is gone, not narrowed.
        with self.assertRaises(ModuleNotFoundError):
            importlib.import_module('godot_devkit.repo.checks.agents')


class BlockedIsNotATrap(unittest.TestCase):
    def test_a_blocked_story_can_be_unblocked_through_the_cli(self):
        with tree(story_statuses=('todo',)) as root:
            self.assertEqual(run_cli(root, 'story', 'wip', '0.1/alpha/s0')[0], 0)
            self.assertEqual(run_cli(root, 'story', 'blocked', '0.1/alpha/s0')[0], 0)
            self.assertEqual(run_cli(root, 'story', 'wip', '0.1/alpha/s0')[0], 0)
            self.assertEqual(run_cli(root, 'story', 'review', '0.1/alpha/s0')[0], 0)


class ATemplateMintsWhateverItSays(unittest.TestCase):
    def test_a_project_template_may_open_a_grain_at_any_state(self):
        # The guard here forbade a project's OWN template from minting a grain
        # past `planning` — the tool overruling a project about its own
        # scaffold. What the state has to be is in the vocabulary, and D4 reads
        # that off the tree.
        with tree() as root:
            (root / 'devkit.toml').write_text(
                '[pm]\ntemplate_dir = "pm/templates"\n', encoding='utf-8')
            run_cli(root, 'templates')
            t = root / 'pm/templates/feature.md'
            t.write_text(t.read_text().replace('status: planning', 'status: done'),
                         encoding='utf-8')
            code, out = run_cli(root, 'new', 'feature', '0.1', 'sneaky', 'S')
            self.assertEqual(code, 0, out)
            self.assertEqual(
                model.field_of(root / 'pm/roadmap/0.1-demo/features/sneaky/feature.md',
                               'status'), 'done')



class YourMilestoneDirectoryIsYours(unittest.TestCase):
    """D13 is gone, both halves, and `pm new` mints no directory.

    D13b — "extra slot" — FAILED your gate for keeping a file in your own
    milestone directory. `plans/`, `findings/`, `AUDIT-REPORT.md`: those are a
    project's own notes in a project's own tree, and a tracker with an opinion
    about them is a tracker deciding what you may write down.

    D13a — a grain dir with no grain file — was already reported twice over:
    `orphan_dirs` says it (always on, never gated by `[pm] checks`) because a
    dropped directory takes every descendant out of the scan, and V1 says a
    grain file with no `id:`/`status:` is malformed. This pins BOTH so the
    coverage cannot quietly leave with the rule.

    And `pm new` no longer mints `features/ bugs/ design/ stories/`. Git does
    not store an empty directory: across one consumer's tree that produced 158
    `design/` dirs, 11 of which hold anything.
    """

    def test_your_own_files_in_your_own_milestone_dir_are_not_findings(self):
        for name in ('plans', 'findings', 'AUDIT-REPORT.md',
                     'DELETED-SCENARIO-LEDGER.md', 'design'):
            with self.subTest(name=name), tree(story_statuses=('todo',)) as root:
                target = root / 'pm/roadmap/0.1-demo' / name
                if name.endswith('.md'):
                    target.write_text('# notes\n', encoding='utf-8')
                else:
                    target.mkdir()
                code, out = run_gate(root)
                self.assertEqual(code, 0, out)

    def test_a_shared_doc_that_lost_its_header_is_not_a_finding(self):
        with tree(story_statuses=('todo',)) as root:
            (root / 'pm/roadmap/0.1-demo/decisions.md').write_text(
                '# log\n\n## D1 — 2026-01-01 — a thing\n', encoding='utf-8')
            code, out = run_gate(root)
            self.assertEqual(code, 0, out)

    def test_a_missing_grain_file_is_STILL_reported_by_two_other_rules(self):
        # The fold-in, proven. If this ever goes quiet, the D13a coverage left
        # with the rule and the census is lying about what it scanned.
        with tree(story_statuses=('todo',)) as root:
            (root / 'pm/roadmap/0.2-scaffolded-by-hand').mkdir()
            (root / 'pm/roadmap/0.1-demo/features/beta').mkdir()
            code, out = run_gate(root)
            self.assertEqual(code, 1, out)
            self.assertIn('milestone dir with no milestone.md', out)
            self.assertIn('feature dir with no feature.md', out)
            self.assertIn('SKIPPED', out)

    def test_a_grain_file_with_no_id_or_status_is_STILL_V1(self):
        with tree(story_statuses=('todo',)) as root:
            (root / 'pm/roadmap/0.1-demo/features/beta').mkdir()
            (root / 'pm/roadmap/0.1-demo/features/beta/feature.md').write_text(
                '---\nname: Beta\n---\n\nprose\n', encoding='utf-8')
            code, out = run_gate(root)
            self.assertEqual(code, 1, out)
            self.assertIn('missing id: or status:', out)

    def test_the_rule_and_its_config_name_are_both_gone(self):
        self.assertNotIn('D13', model.KNOWN_CHECKS)
        with tree(story_statuses=('todo',)) as root:
            (root / 'devkit.toml').write_text(
                '[pm]\nchecks = ["D13"]\n', encoding='utf-8')
            self.assertEqual(run_gate(root)[0], 2)

    def test_new_mints_no_empty_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'repo'
            root.mkdir()
            subprocess.run(['git', 'init', '-q'], cwd=root, check=True)
            previous = Path.cwd()
            os.chdir(root)
            try:
                self.assertEqual(run_cli(root, 'new', 'milestone', '0.1', 'M')[0], 0)
                mdir = root / 'pm/roadmap/0.1-m'
                self.assertEqual(sorted(p.name for p in mdir.iterdir()),
                                 ['milestone.md'])
                self.assertEqual(run_cli(root, 'new', 'feature', '0.1', 'f', 'F')[0], 0)
                fdir = mdir / 'features' / 'f'
                self.assertEqual(sorted(p.name for p in fdir.iterdir()),
                                 ['feature.md'])
                # ...and `stories/` appears when the first story goes into it.
                self.assertEqual(
                    run_cli(root, 'new', 'story', '0.1/f', 's0', 'S0')[0], 0)
                self.assertTrue((fdir / 'stories' / 's0.md').is_file())
            finally:
                os.chdir(previous)

    def test_the_help_line_matches_what_new_milestone_actually_mints(self):
        # The help said "No directory is minted" while the verb minted three and
        # printed one of them. A claim in shipped output is a claim under test.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'repo'
            root.mkdir()
            subprocess.run(['git', 'init', '-q'], cwd=root, check=True)
            previous = Path.cwd()
            os.chdir(root)
            try:
                code, out = run_cli(root, '--help')
                self.assertEqual(code, 0, out)
                self.assertIn('in its own dir', out)
                self.assertIn('no sub-slot dirs', out)
                self.assertNotIn('No directory\n', out)
                self.assertEqual(run_cli(root, 'new', 'milestone', '0.9', 'N')[0], 0)
                mdir = root / 'pm/roadmap/0.9-n'
                # its OWN dir exists, and holds no sub-slot dir
                self.assertTrue(mdir.is_dir())
                self.assertEqual([p.name for p in mdir.iterdir() if p.is_dir()], [])
            finally:
                os.chdir(previous)


class BugStatusVocabulary(unittest.TestCase):
    """D4 — a bug's status, held to the vocabulary like every other grain's.

    Where a bug LIVES is not this tool's business: it is filed where it was
    caught, nothing moves it, and nothing deletes it. What is a fact about the
    file is whether its status is a word the schema has — and it matters more
    for a bug than anywhere else, because every reader asking "is this still
    open" tests for a NAME, so a typo reads as closed and passes in silence.
    """

    @staticmethod
    def _bug(root: Path, slug: str, status: str, **extra) -> Path:
        p = root / 'pm/roadmap/0.1-demo/bugs' / f'{slug}.md'
        front = {'id': f'0.1/bugs/{slug}', 'milestone': '"0.1"',
                 'status': status, 'caught_in': '"0.1"'}
        front.update(extra)
        write(p, front)
        return p

    def test_a_status_outside_the_vocabulary_is_a_finding(self):
        # On the DEFAULT roster — no devkit.toml, no opt-in.
        with tree(milestone_status='building') as root:
            self._bug(root, 'seed-is-zero', 'opne')
            code, out = run_gate(root)
            self.assertEqual(code, 1, out)
            self.assertIn("bug status 'opne' is not in", out)

    def test_an_open_bug_under_a_done_milestone_is_not_a_finding(self):
        with tree(milestone_status='done', feature_status='done',
                  story_statuses=('done',)) as root:
            self._bug(root, 'seed-is-zero', 'open')
            code, out = run_gate(root)
            self.assertEqual(code, 0, out)

    def test_every_vocabulary_status_passes(self):
        with tree(milestone_status='building') as root:
            for i, status in enumerate(model.DEFAULT_BUG_STATES):
                self._bug(root, f'b{i}', status)
            code, out = run_gate(root)
            self.assertEqual(code, 0, out)
            self.assertIn('3 bug(s)', out)

    def test_a_bug_in_a_bugs_SUBDIR_is_not_invisible(self):
        # `bugs/` is a permitted slot and D13 never descends into it, so a
        # `glob('*.md')` made a nested bug invisible to every rule at once —
        # and the census printed the smaller number without saying it had
        # looked less far.
        with tree(milestone_status='building') as root:
            write(root / 'pm/roadmap/0.1-demo/bugs/spatial/seed-is-zero.md',
                  {'id': '0.1/bugs/seed-is-zero', 'milestone': '"0.1"',
                   'status': 'opne'})
            code, out = run_gate(root)
            self.assertEqual(code, 1, out)
            self.assertIn('bugs/spatial/seed-is-zero.md', out)
            self.assertIn('1 bug(s)', out)

    def test_an_uppercase_MD_extension_is_not_invisible(self):
        with tree(milestone_status='building') as root:
            write(root / 'pm/roadmap/0.1-demo/bugs/SEED-IS-ZERO.MD',
                  {'id': '0.1/bugs/seed-is-zero', 'milestone': '"0.1"',
                   'status': 'opne'})
            code, out = run_gate(root)
            self.assertEqual(code, 1, out)
            self.assertIn('SEED-IS-ZERO.MD', out)

    def test_the_census_counts_every_bug_file_it_opened(self):
        with tree(milestone_status='building') as root:
            self._bug(root, 'flat', 'fixed')
            write(root / 'pm/roadmap/0.1-demo/bugs/deep/nested.md',
                  {'id': '0.1/bugs/nested', 'milestone': '"0.1"',
                   'status': 'fixed'})
            write(root / 'pm/roadmap/0.1-demo/bugs/UPPER.MD',
                  {'id': '0.1/bugs/upper', 'milestone': '"0.1"',
                   'status': 'fixed'})
            code, out = run_gate(root)
            self.assertEqual(code, 0, out)
            self.assertIn('3 bug(s)', out)

    def test_the_census_says_zero_when_a_tree_files_no_bugs(self):
        # Rule 4: "0 bug(s)" is a fact this scan states, never an omission.
        with tree(milestone_status='building') as root:
            code, out = run_gate(root)
            self.assertEqual(code, 0, out)
            self.assertIn('0 bug(s)', out)

    def test_a_non_grain_md_parked_under_bugs_is_not_a_bug(self):
        # A grain IS its frontmatter, so a README explaining how bugs are filed
        # — or a design note beside them — is not a bug with an empty status.
        with tree(milestone_status='building') as root:
            bdir = root / 'pm/roadmap/0.1-demo/bugs'
            (bdir / 'design').mkdir(parents=True, exist_ok=True)
            (bdir / 'README.md').write_text('# how bugs are filed here\n',
                                            encoding='utf-8')
            (bdir / 'design/sketch.md').write_text('a sketch\n',
                                                   encoding='utf-8')
            code, out = run_gate(root)
            self.assertEqual(code, 0, out)
            self.assertNotIn('README.md', out)
            self.assertIn('0 bug(s)', out)

    def test_that_narrowing_does_not_reopen_the_subdir_hole_beside_it(self):
        # The control: a REAL bug carries frontmatter wherever it is parked and
        # whatever its extension, so narrowing the walk to grain documents must
        # not undo the recursion that made nested bugs visible at all.
        with tree(milestone_status='building') as root:
            bdir = root / 'pm/roadmap/0.1-demo/bugs'
            bdir.mkdir(parents=True, exist_ok=True)
            (bdir / 'README.md').write_text('# how bugs are filed here\n',
                                            encoding='utf-8')
            write(bdir / 'spatial/SEED.MD',
                  {'id': '0.1/bugs/seed', 'milestone': '"0.1"',
                   'status': 'opne'})
            code, out = run_gate(root)
            self.assertEqual(code, 1, out)
            self.assertIn('bugs/spatial/SEED.MD', out)
            self.assertIn('1 bug(s)', out)


class StoryWalk(unittest.TestCase):
    """`stories/` is the same never-descended slot shape `bugs/` was.

    The bug walk was made recursive and case-insensitive on extension and
    `stories/` never got it, so a story parked one directory down was invisible
    to every rule at once — and worse than invisible: D4 could not see its
    status, and D2 read "all stories done" off the ones it could see and filed
    a FALSE finding against a feature that had an unfinished story in it.
    """

    FDIR = 'pm/roadmap/0.1-demo/features/alpha'

    def test_a_story_in_a_stories_SUBDIR_is_not_invisible(self):
        with tree(feature_status='building', story_statuses=('done',)) as root:
            write(root / self.FDIR / 'stories/parked/s2.md',
                  {'id': '0.1/alpha/s2', 'feature': '0.1/alpha',
                   'milestone': '"0.1"', 'name': 'S2', 'status': 'todo'})
            code, out = run_gate(root)
            self.assertIn('2 story/ies', out)

    def test_it_is_the_false_D2_finding_that_makes_this_load_bearing(self):
        # Not just an undercount: the stories it COULD see were all done, so
        # D2 told the author to close a feature with an open story in it.
        with tree(feature_status='building', story_statuses=('done',)) as root:
            write(root / self.FDIR / 'stories/parked/s2.md',
                  {'id': '0.1/alpha/s2', 'feature': '0.1/alpha',
                   'milestone': '"0.1"', 'name': 'S2', 'status': 'todo'})
            code, out = run_gate(root)
            self.assertNotIn('all stories done', out)

    def test_D4_can_see_a_nested_story_with_an_illegal_status(self):
        with tree(feature_status='building', story_statuses=('todo',)) as root:
            write(root / self.FDIR / 'stories/parked/s2.md',
                  {'id': '0.1/alpha/s2', 'feature': '0.1/alpha',
                   'milestone': '"0.1"', 'name': 'S2',
                   'status': 'NOT-A-REAL-STATUS'})
            code, out = run_gate(root)
            self.assertEqual(code, 1, out)
            self.assertIn("status 'NOT-A-REAL-STATUS' not in", out)

    def test_an_uppercase_MD_story_is_counted(self):
        with tree(feature_status='building', story_statuses=('todo',)) as root:
            write(root / self.FDIR / 'stories/S3.MD',
                  {'id': '0.1/alpha/S3', 'feature': '0.1/alpha',
                   'milestone': '"0.1"', 'name': 'S3', 'status': 'todo'})
            code, out = run_gate(root)
            self.assertEqual(code, 0, out)
            self.assertIn('2 story/ies', out)

    def test_a_non_grain_md_parked_under_stories_is_not_a_story(self):
        # The same rule `bugs/` gets, from the same walk: a README beside the
        # stories is not a story with an empty status.
        with tree(feature_status='building', story_statuses=('todo',)) as root:
            (root / self.FDIR / 'stories/README.md').write_text(
                '# how stories are written here\n', encoding='utf-8')
            code, out = run_gate(root)
            self.assertEqual(code, 0, out)
            self.assertIn('1 story/ies', out)


class DamagedFrontmatter(unittest.TestCase):
    """A broken grain stays IN the census and is REPORTED.

    "This has no frontmatter" and "this frontmatter is broken" are different
    facts, and the grain walk answered the second with the first: scope was
    decided by the STRICT parser, so a BOM before the fence, a blank line above
    it or a missing closing fence dropped the document out of every rule at
    once — D4, D5 and V1 went blind together and the gate printed PASS. The bug
    half is the loudest: the census said there was no bug in the directory at
    all, so a damaged bug was a bug nobody could be told to fix.

    Detection is lenient, parsing is strict. That split is the whole rule, and
    the controls below are the other half of it: a genuine note must stay out.
    """

    BUG_TOML = '[pm]\nchecks = ["D4","V1"]\n'

    @staticmethod
    def _bug(root: Path, slug: str, status: str) -> Path:
        p = root / 'pm/roadmap/0.1-demo/bugs' / f'{slug}.md'
        write(p, {'id': f'0.1/bugs/{slug}', 'milestone': '"0.1"',
                  'status': status, 'caught_in': '"0.1"'})
        return p

    def test_a_damaged_story_is_reported_not_dropped(self):
        for form in DAMAGE_FORMS:
            with self.subTest(form=form):
                with tree(feature_status='building',
                          story_statuses=('todo',)) as root:
                    damage(root / STORY_REL, form)
                    code, out = run_gate(root)
                    self.assertEqual(code, 1, out)
                    self.assertIn("status '' not in", out)
                    self.assertIn('missing id: or status:', out)
                    self.assertIn('1 story/ies', out)

    def test_a_damaged_bug_is_reported_not_dropped(self):
        for form in DAMAGE_FORMS:
            with self.subTest(form=form):
                with tree(milestone_status='building') as root:
                    (root / 'devkit.toml').write_text(self.BUG_TOML,
                                                      encoding='utf-8')
                    damage(self._bug(root, 'seed-is-zero', 'open'), form)
                    code, out = run_gate(root)
                    self.assertEqual(code, 1, out)
                    self.assertIn("bug status '' is not in", out)
                    self.assertIn('1 bug(s)', out)
                    self.assertNotIn('no bug files under', out)

    def test_a_damaged_bug_is_still_counted_under_a_closed_milestone(self):
        # A BOM before the fence used to drop the file out of the walk
        # entirely, so the census reported a directory with no bugs in it while
        # the file sat there unreadable and unreported.
        for form in DAMAGE_FORMS:
            with self.subTest(form=form):
                with tree(milestone_status='done', feature_status='done',
                          story_statuses=('done',)) as root:
                    (root / 'devkit.toml').write_text(self.BUG_TOML,
                                                      encoding='utf-8')
                    damage(self._bug(root, 'leaky', 'open'), form)
                    code, out = run_gate(root)
                    self.assertEqual(code, 1, out)
                    self.assertNotIn('nothing to place', out)
                    self.assertIn('bugs/leaky.md', out)
                    self.assertIn('1 bug(s)', out)

    def test_the_resolver_names_the_damage_not_a_missing_story(self):
        # `story_file` walks the same grain walk, so it went blind with the
        # gate: `pm story wip <id>` answered "no story resolves from id" about
        # a file sitting right there. Each answer is defensible alone; together
        # they leave nothing to do.
        for form in DAMAGE_FORMS:
            with self.subTest(form=form):
                with tree(feature_status='building',
                          story_statuses=('todo',)) as root:
                    damage(root / STORY_REL, form)
                    self.assertIsNotNone(
                        model.story_file(cfg_for(root), '0.1/alpha/s0'))
                    code, out = run_cli(root, 'story', 'wip', '0.1/alpha/s0')
                    self.assertEqual(code, 2, out)
                    self.assertNotIn('no story resolves', out)
                    # The one refusal a status verb keeps: the FRONTMATTER is
                    # malformed, which is a fact about the file. What the
                    # status VALUE happens to be is never a refusal.
                    self.assertIn('malformed frontmatter', out)

    def test_a_damaged_grain_is_never_quietly_accepted(self):
        # Lenient DETECTION must not become a lenient PARSER. A BOM'd file is a
        # grain whose frontmatter is broken, so `field_of` still reads nothing
        # out of it and `set_field` still refuses to write into it.
        for form in DAMAGE_FORMS:
            with self.subTest(form=form):
                with tree(story_statuses=('todo',)) as root:
                    sfile = root / STORY_REL
                    damage(sfile, form)
                    self.assertTrue(model._is_grain_doc(sfile))
                    self.assertEqual(model.field_of(sfile, 'status'), '')
                    before = sfile.read_bytes()
                    self.assertFalse(model.set_field(sfile, 'status', 'wip'))
                    self.assertEqual(sfile.read_bytes(), before)

    # --- the controls: a genuine note stays OUT --------------------------
    def test_a_readme_with_no_frontmatter_under_bugs_is_still_silent(self):
        with tree(milestone_status='building') as root:
            (root / 'devkit.toml').write_text(self.BUG_TOML, encoding='utf-8')
            (root / 'pm/roadmap/0.1-demo/bugs').mkdir(parents=True,
                                                      exist_ok=True)
            (root / 'pm/roadmap/0.1-demo/bugs/README.md').write_text(
                '# how bugs are filed here\n', encoding='utf-8')
            code, out = run_gate(root)
            self.assertEqual(code, 0, out)
            self.assertNotIn('README.md', out)
            self.assertIn('0 bug(s)', out)
            self.assertIn('1 note(s) skipped', out)

    def test_a_readme_with_no_frontmatter_under_stories_is_still_silent(self):
        with tree(feature_status='building', story_statuses=('todo',)) as root:
            (root / 'pm/roadmap/0.1-demo/features/alpha/stories/README.md'
             ).write_text('# how stories are written\n', encoding='utf-8')
            code, out = run_gate(root)
            self.assertEqual(code, 0, out)
            self.assertIn('1 story/ies', out)

    def test_a_thematic_break_after_prose_does_not_make_a_note_a_grain(self):
        # The one thing leniency will NOT step over is prose. A `---` under a
        # paragraph is a thematic break in a note, not a frontmatter fence.
        with tree(feature_status='building', story_statuses=('todo',)) as root:
            (root / 'pm/roadmap/0.1-demo/features/alpha/stories/notes.md'
             ).write_text('Some prose\n\n---\n\nmore prose\n',
                          encoding='utf-8')
            code, out = run_gate(root)
            self.assertEqual(code, 0, out)
            self.assertIn('1 story/ies', out)

    def test_the_census_says_how_many_documents_the_walk_skipped(self):
        # A census must never assert the opposite of the filesystem. "0 bug(s)"
        # is a fact about the filter, not about the directory, unless the scan
        # says how far it looked.
        with tree(feature_status='building', story_statuses=('todo',)) as root:
            (root / 'pm/roadmap/0.1-demo/features/alpha/stories/README.md'
             ).write_text('# notes\n', encoding='utf-8')
            (root / 'pm/roadmap/0.1-demo/bugs').mkdir(parents=True,
                                                      exist_ok=True)
            (root / 'pm/roadmap/0.1-demo/bugs/README.md').write_text(
                '# notes\n', encoding='utf-8')
            code, out = run_gate(root)
            self.assertEqual(code, 0, out)
            self.assertIn('2 note(s) skipped', out)

    def test_a_clean_tree_discloses_nothing_because_it_skipped_nothing(self):
        with tree(feature_status='building', story_statuses=('todo',)) as root:
            code, out = run_gate(root)
            self.assertEqual(code, 0, out)
            self.assertNotIn('note(s) skipped', out)

    def test_the_census_says_how_many_documents_the_dotted_filter_hid(self):
        # The twin of the note disclosure, and the reason it matters: an open
        # bug parked under `bugs/.hold/` is out of scope for every rule, so no
        # rule can report its status.
        # A dot prefix is a deliberate hide; an UNCOUNTED one is a census
        # asserting the opposite of the filesystem.
        with tree(feature_status='building', story_statuses=('todo',)) as root:
            hold = root / 'pm/roadmap/0.1-demo/bugs/.hold'
            hold.mkdir(parents=True, exist_ok=True)
            (hold / 'openbug.md').write_text(
                '---\nid: 0.1/bugs/openbug\nmilestone: "0.1"\n'
                'name: b\nstatus: open\nseverity: high\n---\n# b\n',
                encoding='utf-8')
            code, out = run_gate(root)
            self.assertEqual(code, 0, out)
            self.assertIn('1 hidden (dot-prefixed', out)

    def test_a_tree_with_nothing_hidden_discloses_no_hidden_count(self):
        with tree(feature_status='building', story_statuses=('todo',)) as root:
            code, out = run_gate(root)
            self.assertEqual(code, 0, out)
            self.assertNotIn('hidden (dot-prefixed', out)

    def test_the_grain_walk_skips_dotted_names_exactly_as_D13_does(self):
        # `structure_findings` skips a dotted entry, so a `stories/.hidden/d.md`
        # held to D4 was one walk enforcing a rule the structure gate had
        # already declared out of scope. Two walks, one tree, one answer.
        with tree(feature_status='building', story_statuses=('todo',)) as root:
            sdir = root / 'pm/roadmap/0.1-demo/features/alpha/stories'
            write(sdir / '.hidden/d.md',
                  {'id': '0.1/alpha/d', 'status': 'NOT-A-REAL-STATUS'})
            write(sdir / '.dotfile.md',
                  {'id': '0.1/alpha/dot', 'status': 'NOT-A-REAL-STATUS'})
            code, out = run_gate(root)
            self.assertEqual(code, 0, out)
            self.assertIn('1 story/ies', out)
            self.assertNotIn('NOT-A-REAL-STATUS', out)


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


class MarkdownFences(unittest.TestCase):
    """`check doc` — what a fence may and may not hide.

    A fence masks because a quoted refusal message is an ILLUSTRATION, not an
    instruction. An UNTERMINATED one illustrates nothing and hides the rest of
    the file, and a parity toggle let it do that in silence: two claims that
    FAIL normally printed PASS the moment one stray ``` was prepended above
    them.
    """

    DEAD = ('See [the missing spec](docs/specs/nope.md).\n'
            'Run `make no-such-target` to do it.\n')
    def _doc(self, root: Path, body: str) -> tuple[int, str]:
        import importlib
        from godot_devkit.repo.checks import doc
        (root / 'CLAUDE.md').write_text(body, encoding='utf-8')
        from godot_devkit.core.project import load_config, repo_root
        repo_root.cache_clear()
        load_config.cache_clear()
        # `doc` binds its root and scope at IMPORT, where production resolves
        # them once per process and the cwd never moves. Tests move it.
        importlib.reload(doc)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = doc.run()
        return code, buf.getvalue()

    def test_doc_still_fails_on_the_claims_without_any_fence(self):
        with tree() as root:
            code, out = self._doc(root, self.DEAD)
            self.assertEqual(code, 1, out)
            self.assertIn('dead link target', out)
            self.assertIn('unknown make target', out)

    def test_an_unterminated_fence_cannot_hide_a_doc_claim(self):
        with tree() as root:
            code, out = self._doc(root, '```\n' + self.DEAD)
            self.assertEqual(code, 1, out)
            self.assertIn('dead link target', out)
            self.assertIn('unknown make target', out)
            self.assertIn('never terminated', out)
            self.assertIn('malformed doc(s)', out)

    def test_a_terminated_fence_still_masks(self):
        # The fix is not "stop masking": a doc quoting a command that no longer
        # exists is illustrating it, and flagging that is how a gate gets
        # switched off.
        with tree() as root:
            code, out = self._doc(root, '```\n' + self.DEAD + '```\n')
            self.assertEqual(code, 0, out)

    def test_an_indented_fence_is_content_not_a_fence(self):
        # CommonMark: four spaces is INDENTED CODE, so what it holds is text. A
        # doc showing how a fence is written indents the sample, and reading it
        # as real opened a block that never closed.
        with tree() as root:
            code, out = self._doc(root, 'Opening a block:\n\n    ```gdscript\n\n'
                                        + self.DEAD)
            self.assertEqual(code, 1, out)
            self.assertIn('dead link target', out)
            self.assertNotIn('never terminated', out)

    def test_a_tilde_run_does_not_close_a_backtick_fence(self):
        # A parity toggle counted any fence-looking line, so the `~~~` "closed"
        # the block and the `````` that really closed it opened a new one —
        # every line after it dropped.
        with tree() as root:
            code, out = self._doc(root, '```\n~~~\n```\n' + self.DEAD)
            self.assertEqual(code, 1, out)
            self.assertIn('dead link target', out)

    def test_the_census_says_how_much_it_skipped(self):
        # The census counts FILES, and files are not what a fence hides.
        with tree() as root:
            code, out = self._doc(root, '```\nhidden\n```\nfine.\n')
            self.assertEqual(code, 0, out)
            self.assertIn('3 fenced line(s) skipped', out)

    def test_a_balanced_inline_span_leading_a_line_is_not_a_fence_opener(self):
        # CommonMark: the info string after a BACKTICK fence may not contain a
        # backtick. Without that rule a paragraph merely BEGINNING with a
        # ```balanced``` span opened a fence, a later bare ``` "closed" it, and
        # the claims between were masked with NO defect reported — the silent
        # mask, reached by a third route.
        with tree() as root:
            code, out = self._doc(
                root, '```make nosuchtarget``` is the spelling.\n'
                      + self.DEAD + '```\n')
            self.assertEqual(code, 1, out)
            self.assertIn('unknown make target: `make nosuchtarget`', out)
            self.assertIn('dead link target', out)
            self.assertIn('unknown make target: `make no-such-target`', out)
            # And the ``` that used to "close" it opens nothing it can finish.
            self.assertIn('never terminated', out)

    def test_a_longer_run_leading_a_line_is_not_a_fence_opener_either(self):
        # ````x``` is the same shape one backtick wider, and the fuzz found it
        # as the second half of the one divergence class.
        with tree() as root:
            code, out = self._doc(root, '````x``` and\n' + self.DEAD + '````\n')
            self.assertEqual(code, 1, out)
            self.assertIn('dead link target', out)
            self.assertIn('unknown make target', out)

    def test_a_tilde_fence_may_carry_backticks_in_its_info_string(self):
        # The rule is BACKTICK-fence-only. Over-applying it would stop a real
        # `~~~` block masking, which is the same defect pointing the other way.
        with tree() as root:
            code, out = self._doc(root, '~~~ a ``b`` c\n' + self.DEAD + '~~~\n')
            self.assertEqual(code, 0, out)
            self.assertIn('4 fenced line(s) skipped', out)

    def test_the_doc_FAIL_line_says_what_it_scanned(self):
        # The verdict used to print alone. "1 malformed doc(s)" out of one doc and out of two
        # hundred are different reports, and only one of them printed.
        with tree() as root:
            code, out = self._doc(root, '```\n' + self.DEAD)
            self.assertEqual(code, 1, out)
            self.assertIn('1 doc(s)', out.splitlines()[0])
            self.assertIn('fenced line(s) skipped', out.splitlines()[0])


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


class OneHomeForEachFact(unittest.TestCase):
    def test_the_VALIDATE_RULES_second_name_is_gone(self):
        # `model.VALIDATE_CHECKS` is the one roster; a copy in validate.py
        # meant a V7 added to one silently split `pm validate` from `check pm`.
        from godot_devkit.repo.pm import validate
        self.assertFalse(hasattr(validate, 'VALIDATE_RULES'))
        self.assertEqual(model.VALIDATE_CHECKS,
                         ('V1', 'V2', 'V3', 'V4', 'V5', 'V6'))

    def test_the_dead_include_archive_parameter_is_gone(self):
        # Zero callers ever passed True; the archive-merging branch was
        # unreachable. A declaration whose last reader is gone dies with it.
        import inspect
        self.assertEqual(
            list(inspect.signature(model.milestone_walk).parameters), ['cfg'])
        self.assertEqual(
            list(inspect.signature(model.milestone_dirs).parameters), ['cfg'])


class BugStatus(unittest.TestCase):
    """`pm bug <status> <bug-id>` — exactly `cmd_story`'s shape, for bugs.

    Before this, the vocabulary and the `/bugs/` resolver both existed
    (`_grain_file`, `checks/pm.py`'s D4) and nothing sanctioned reached them
    together — only a hand edit or the untyped `pm set` moved a bug's own
    `status:`. Mirrors `StatusMoves`' story coverage: every vocabulary state
    reachable, an out-of-vocabulary target a Usage error naming the set, the
    flip idempotent, an id that resolves to nothing exit 2.
    """

    @staticmethod
    def _bug(root: Path, slug: str, status: str) -> Path:
        p = root / 'pm/roadmap/0.1-demo/bugs' / f'{slug}.md'
        write(p, {'id': f'0.1/bugs/{slug}', 'milestone': '"0.1"',
                  'status': status})
        return p

    def test_any_state_in_the_vocabulary_is_reachable(self):
        for state in model.DEFAULT_BUG_STATES:
            with self.subTest(state=state), tree() as root:
                bug = self._bug(root, 'seed-is-zero', 'open')
                code, out = run_cli(root, 'bug', state,
                                    '0.1/bugs/seed-is-zero')
                self.assertEqual(code, 0, out)
                self.assertEqual(model.field_of(bug, 'status'), state)

    def test_a_state_outside_the_vocabulary_is_a_usage_error_naming_the_set(self):
        with tree() as root:
            bug = self._bug(root, 'seed-is-zero', 'open')
            code, out = run_cli(root, 'bug', 'banana',
                                '0.1/bugs/seed-is-zero')
            self.assertEqual(code, 2, out)
            self.assertIn('is not a bug status', out)
            for state in model.DEFAULT_BUG_STATES:
                self.assertIn(state, out)
            self.assertEqual(model.field_of(bug, 'status'), 'open')

    def test_idempotent_noop_succeeds(self):
        with tree() as root:
            self._bug(root, 'seed-is-zero', 'fixed')
            code, out = run_cli(root, 'bug', 'fixed', '0.1/bugs/seed-is-zero')
            self.assertEqual(code, 0, out)
            self.assertIn('no-op', out)

    def test_unresolvable_id_is_a_usage_error(self):
        with tree() as root:
            code, out = run_cli(root, 'bug', 'open', '0.1/bugs/nope')
            self.assertEqual(code, 2, out)
            self.assertIn('no bug resolves', out)

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
        index.write_text(cli.ROADMAP_SEED, encoding='utf-8')
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


if __name__ == '__main__':
    unittest.main()
