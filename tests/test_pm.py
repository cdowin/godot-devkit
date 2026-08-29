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
from pathlib import Path

from support import REPO_ROOT  # noqa: F401  (inserts src/ on sys.path)

from godot_devkit.repo.checks import pm as pm_check
from godot_devkit.repo.pm import cli, model


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
    def test_a_stub_pointer_is_not_a_review(self):
        with tree(with_record=True) as root:
            cfg = cfg_for(root)
            (root / 'docs' / 'reviews' / 'alpha.md').write_text('  \n\n', encoding='utf-8')
            self.assertIsNone(model.review_record_for(cfg, '0.1/alpha'))

    def test_a_missing_target_is_not_a_review(self):
        with tree(with_record=True) as root:
            cfg = cfg_for(root)
            (root / 'docs' / 'reviews' / 'alpha.md').unlink()
            self.assertIsNone(model.review_record_for(cfg, '0.1/alpha'))

    def test_a_one_line_record_counts(self):
        # The bar rejects emptiness, not brevity.
        with tree(with_record=True) as root:
            self.assertIsNotNone(model.review_record_for(cfg_for(root), '0.1/alpha'))


class Transitions(unittest.TestCase):
    def test_story_done_is_refused_outright(self):
        with tree(story_statuses=('review',)) as root:
            code, out = run_cli(root, 'story', 'done', '0.1/alpha/s0')
            self.assertEqual(code, 1)
            self.assertIn('REFUSED', out)

    def test_illegal_story_edge_is_refused(self):
        with tree(story_statuses=('todo',)) as root:
            code, _ = run_cli(root, 'story', 'review', '0.1/alpha/s0')
            self.assertEqual(code, 0)  # todo->review is the no-build edge

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

    def test_feature_review_refuses_unfinished_stories(self):
        with tree(story_statuses=('review', 'wip')) as root:
            code, out = run_cli(root, 'feature', 'review', '0.1/alpha')
            self.assertEqual(code, 1)
            self.assertIn('not at review', out)

    def test_milestone_done_refuses_live_features(self):
        with tree(feature_status='building') as root:
            code, out = run_cli(root, 'milestone', 'done', '0.1')
            self.assertEqual(code, 1)
            self.assertIn('features not done', out)


class FeatureClose(unittest.TestCase):
    def test_cascade_closes_stories_and_feature(self):
        with tree(feature_status='review', story_statuses=('review', 'review')) as root:
            code, _ = run_cli(root, 'feature', 'done', '0.1/alpha')
            self.assertEqual(code, 0)
            fdir = root / 'pm/roadmap/0.1-demo/features/alpha'
            self.assertEqual(model.field_of(fdir / 'feature.md', 'status'), 'done')
            for s in (fdir / 'stories').glob('*.md'):
                self.assertEqual(model.field_of(s, 'status'), 'done')

    def test_close_without_a_record_is_refused(self):
        with tree(feature_status='review', story_statuses=('review',),
                  with_record=False) as root:
            code, out = run_cli(root, 'feature', 'done', '0.1/alpha')
            self.assertEqual(code, 1)
            self.assertIn('NO substantive review record', out)

    def test_a_refused_close_leaves_feature_md_byte_identical(self):
        # The all-or-nothing guarantee: no stale `reviewed:` stamp survives a
        # refusal, and no story is flipped.
        with tree(feature_status='review', story_statuses=('review',),
                  with_record=False) as root:
            ff = root / 'pm/roadmap/0.1-demo/features/alpha/feature.md'
            story = root / 'pm/roadmap/0.1-demo/features/alpha/stories/s0.md'
            before, sbefore = ff.read_text(), story.read_text()
            (root / 'docs' / 'reviews').mkdir(parents=True, exist_ok=True)
            (root / 'docs' / 'reviews' / 'stub.md').write_text('   \n', encoding='utf-8')
            code, _ = run_cli(root, 'feature', 'done', '0.1/alpha',
                              '--review-record', 'docs/reviews/stub.md')
            self.assertEqual(code, 1)
            self.assertEqual(ff.read_text(), before)
            self.assertEqual(story.read_text(), sbefore)

    def test_close_refuses_when_a_story_is_unfinished(self):
        with tree(feature_status='review', story_statuses=('review', 'todo')) as root:
            code, out = run_cli(root, 'feature', 'done', '0.1/alpha')
            self.assertEqual(code, 1)
            self.assertIn('not at review', out)


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

    def test_d1_done_feature_without_a_record(self):
        with tree(feature_status='done', story_statuses=('done',),
                  milestone_status='done', with_record=False) as root:
            code, out = run_gate(root)
            self.assertEqual(code, 1)
            self.assertIn('done w/o review record', out)

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
            self.assertIn('only comes from the feature cascade', out)

    def test_d6_building_milestone_with_every_feature_done(self):
        with tree(milestone_status='building', feature_status='done',
                  story_statuses=('done',)) as root:
            code, out = run_gate(root)
            self.assertEqual(code, 1)
            self.assertIn('should be done', out)

    def test_d7_archive_dir_means_a_prune_is_due(self):
        with tree(story_statuses=('todo',)) as root:
            (root / 'pm' / 'roadmap' / 'zz_archive' / 'x').mkdir(parents=True)
            code, out = run_gate(root)
            self.assertEqual(code, 1)
            self.assertIn('a prune is due', out)


    # --- D12: the decision-record schema ---------------------------------
    # ENTRY is the conforming record from the schema; the mutations below each
    # break exactly one field of it, so a failure names the rule, not the fixture.
    ENTRY = (
        '## D3 — 2026-08-28 — the sweep verb belongs to the combat layer\n'
        '**Chose:** move `sweep_tracked_contributions` to `combat_behavior.gd`\n'
        '**Over:** leaving it on `entity_behavior.gd`, the lean root\n'
        '**Because:** all three consumers extend the combat layer\n'
        '**Evidence:** `64e89ad5b`\n')

    @staticmethod
    def _log(root: Path, body: str) -> Path:
        path = root / 'pm' / 'roadmap' / '0.1-demo' / 'decisions.md'
        path.write_text('# Demo — decisions\n\nAppend-only.\n\n' + body,
                        encoding='utf-8')
        return path

    def test_d12_a_conforming_entry_passes_and_a_missing_over_does_not(self):
        # The same file green then red: `Over:` is the load-bearing field, so
        # dropping only that line must flip the gate AND name the field.
        with tree(story_statuses=('todo',)) as root:
            (root / 'devkit.toml').write_text(
                '[pm]\nchecks = ["D12"]\n', encoding='utf-8')
            log = self._log(root, self.ENTRY)
            code, out = run_gate(root)
            self.assertEqual(code, 0, out)

            log.write_text(log.read_text(encoding='utf-8').replace(
                '**Over:** leaving it on `entity_behavior.gd`, the lean root\n', ''),
                encoding='utf-8')
            code, out = run_gate(root)
            self.assertEqual(code, 1)
            self.assertIn('missing **Over:**', out)
            self.assertIn('D3', out)

    def test_d12_evidence_must_be_a_reference_not_prose(self):
        with tree(story_statuses=('todo',)) as root:
            (root / 'devkit.toml').write_text(
                '[pm]\nchecks = ["D12"]\n', encoding='utf-8')
            log = self._log(root, self.ENTRY.replace(
                '**Evidence:** `64e89ad5b`',
                '**Evidence:** we discussed it and agreed'))
            code, out = run_gate(root)
            self.assertEqual(code, 1)
            self.assertIn('is prose, not a reference', out)

            # A path:line and a bare hash are both references; the same entry
            # passes the moment the sentence becomes one.
            log.write_text(log.read_text(encoding='utf-8').replace(
                '**Evidence:** we discussed it and agreed',
                '**Evidence:** `systems/combat/combat_behavior.gd:214`'),
                encoding='utf-8')
            self.assertEqual(run_gate(root)[0], 0)

    def test_d12_an_over_length_field_fails(self):
        with tree(story_statuses=('todo',)) as root:
            (root / 'devkit.toml').write_text(
                '[pm]\nchecks = ["D12"]\n', encoding='utf-8')
            self._log(root, self.ENTRY.replace(
                'all three consumers extend the combat layer', 'x' * 201))
            code, out = run_gate(root)
            self.assertEqual(code, 1)
            self.assertIn('over the 200-char cap', out)

    def test_d12_sees_an_entry_whose_id_follows_the_date(self):
        # The blind spot that would have shipped: a log writing the id AFTER
        # the date reads as prose to an opens-with-an-id test, and 28 real logs
        # in one consumer are written that way. Silence here is rule 4's sin.
        with tree(story_statuses=('todo',)) as root:
            (root / 'devkit.toml').write_text(
                '[pm]\nchecks = ["D12"]\n', encoding='utf-8')
            self._log(root, '## 2026-08-24 — D1: the plural API is the sibling\n\n'
                            'Prose, no fields at all.\n')
            code, out = run_gate(root)
            self.assertEqual(code, 1)
            self.assertIn('header is not', out)
            self.assertIn('missing **Chose:**', out)

    def test_d12_a_heading_with_no_field_lines_under_it_is_not_an_entry(self):
        # The exemption is NO FIELDS, not "an unremarkable title". A log may
        # open with a preamble, and a preamble carries prose, never a
        # `**Word:**` line — which is the whole discriminator (see the retired
        # -template case below, where the title is just as unremarkable and the
        # block IS a decision).
        with tree(story_statuses=('todo',)) as root:
            (root / 'devkit.toml').write_text(
                '[pm]\nchecks = ["D12"]\n', encoding='utf-8')
            self._log(root, '## The through-line, if you read nothing else\n\n'
                            'A log may have a preamble.\n\n' + self.ENTRY)
            code, out = run_gate(root)
            self.assertEqual(code, 0, out)
            self.assertIn('1 decision log(s), 1 entry/ies', out)

    def test_d12_sees_an_entry_in_the_retired_template_shape(self):
        # The false PASS that shipped: this package's OWN retired template told
        # authors to write `## <short title>` with `**Decision:/Because:/
        # Rejected:/Costs:**` beneath, and a detector reading only the heading
        # calls every such block prose. An entire real corpus — 9 blocks across
        # two live logs, conforming to D12 in no respect — passed in silence.
        # The FIELD LINE is the positive signal, id or date or neither.
        with tree(story_statuses=('todo',)) as root:
            (root / 'devkit.toml').write_text(
                '[pm]\nchecks = ["D12"]\n', encoding='utf-8')
            self._log(root,
                      '## The dead leave the table by REMOVAL, not by gating\n\n'
                      '**Decision:** remove them from the roster\n'
                      '**Because:** every consumer walks the roster\n'
                      '**Rejected:** a `dead` flag on the row\n')
            code, out = run_gate(root)
            self.assertEqual(code, 1, out)
            # Named by its own title, because that is the only handle it has.
            self.assertIn('The dead leave the table by REMOVAL, not by gating',
                          out)
            self.assertIn('missing **Chose:**', out)
            self.assertIn('missing **Over:**', out)
            self.assertIn('1 decision log(s), 1 entry/ies', out)

    def test_d12_ignores_a_block_inside_an_html_comment(self):
        # The retired template shipped its example COMMENTED OUT, field lines
        # and all. A `<!-- -->` block renders as nothing, so it is not in the
        # log — reporting it would be a finding against text no reader sees.
        with tree(story_statuses=('todo',)) as root:
            (root / 'devkit.toml').write_text(
                '[pm]\nchecks = ["D12"]\n', encoding='utf-8')
            self._log(root, '<!-- Template for a block:\n\n## <short title>\n\n'
                            '**Decision:** <what was chosen>\n'
                            '**Because:** <the constraint>\n\n-->\n\n'
                            + self.ENTRY)
            code, out = run_gate(root)
            self.assertEqual(code, 0, out)
            self.assertIn('1 decision log(s), 1 entry/ies', out)

    # --- the comment scan is not a one-way toggle -------------------------
    # A single-pass `inside = True` with no terminator requirement turns one
    # stray marker into a silent exemption for every line after it. All three
    # cases below were real: a PASS over a violation, a FAIL over a conforming
    # entry, and a census that undercounted while printing PASS.

    SECOND = (
        '## D2 — 2026-08-28 — the second decision, plainly conforming\n'
        '**Chose:** keep the second entry visible\n'
        '**Over:** losing it to a stray marker\n'
        '**Because:** the census must be honest\n'
        '**Evidence:** `abc1234`\n')

    def test_d12_reads_a_fenced_block_as_a_sample_not_as_log_text(self):
        # A fenced block is verbatim text: `<!--` inside it opens nothing and
        # `## <short title>` inside it is not a heading. Before the fix the
        # unterminated marker inside the fence marked the REAL `## D2` below it
        # dead, and the gate printed `1 entry/ies … PASS` over a 2-entry log.
        with tree(story_statuses=('todo',)) as root:
            (root / 'devkit.toml').write_text(
                '[pm]\nchecks = ["D12"]\n', encoding='utf-8')
            self._log(root, self.ENTRY + '\n```html\n'
                            '<!-- the retired template block\n'
                            '## <short title>\n'
                            '**Decision:** <what was chosen>\n'
                            '```\n\n'
                            '## D2 — a real decision that violates the schema\n'
                            '**Chose:** something\n'
                            '**Because:** we discussed it and agreed\n')
            code, out = run_gate(root)
            self.assertEqual(code, 1, out)
            self.assertIn('D2 — missing **Over:**', out)
            # The fenced sample is neither an entry nor an unclosed comment.
            self.assertNotIn('<short title>', out)
            self.assertNotIn('never closed', out)
            self.assertIn('1 decision log(s), 2 entry/ies', out)

    def test_d12_reads_a_marker_in_backticks_as_a_marker_being_named(self):
        # The entry that broke the parser by being ABOUT it. Before the fix its
        # own `**Chose:**` opened a comment that ate its remaining three fields
        # — a false FAIL against a conforming entry — and swallowed the next
        # entry whole, so the census said 1 over a 2-entry log.
        with tree(story_statuses=('todo',)) as root:
            (root / 'devkit.toml').write_text(
                '[pm]\nchecks = ["D12"]\n', encoding='utf-8')
            self._log(root,
                      '## D1 — 2026-08-28 — ignore comment blocks when parsing\n'
                      '**Chose:** ignore `<!--` blocks when parsing a log\n'
                      '**Over:** treating them as live text\n'
                      '**Because:** a comment renders as nothing\n'
                      '**Evidence:** `64e89ad5b`\n\n' + self.SECOND)
            code, out = run_gate(root)
            self.assertEqual(code, 0, out)
            self.assertIn('1 decision log(s), 2 entry/ies', out)

    def test_d12_reports_an_unclosed_comment_instead_of_truncating_the_log(self):
        # Rule 4, read side: a marker with no terminator is a MALFORMED log,
        # and D12 cannot honestly claim to have scanned what it cannot
        # delimit. Before the fix it printed `1 entry/ies … PASS` over three
        # entries. It must now suppress nothing and say what is wrong.
        with tree(story_statuses=('todo',)) as root:
            (root / 'devkit.toml').write_text(
                '[pm]\nchecks = ["D12"]\n', encoding='utf-8')
            log = self._log(root, self.ENTRY +
                            '\nProse that mentions <!-- and never closes it.\n\n'
                            + self.SECOND)
            code, out = run_gate(root)
            self.assertEqual(code, 1, out)
            self.assertIn('opens an HTML comment `<!--` that is never closed', out)
            self.assertIn('line 11', out)  # the marker's own line, to jump to
            self.assertIn('1 decision log(s), 2 entry/ies', out)

            # Closing it clears the finding and changes no count.
            log.write_text(log.read_text(encoding='utf-8').replace(
                'and never closes it.', 'and closes it. -->'), encoding='utf-8')
            code, out = run_gate(root)
            self.assertEqual(code, 0, out)
            self.assertIn('1 decision log(s), 2 entry/ies', out)

    def test_pm_decide_appends_past_a_stray_comment_marker(self):
        # The user-visible half of the same bug: with the rest of the log
        # marked dead, `pm decide` re-parsed its own composed entry, could not
        # see it, and refused with `does not parse as a decision entry` —
        # naming no cause an author could act on.
        with tree(story_statuses=('todo',)) as root:
            (root / 'devkit.toml').write_text(
                '[pm]\nchecks = ["D12"]\n', encoding='utf-8')
            log = self._log(root, self.ENTRY +
                            '\nProse that mentions <!-- and never closes it.\n\n'
                            + self.SECOND)
            code, out = run_cli(root, 'decide', '0.1', '--chose', 'x',
                                '--over', 'y', '--because', 'z',
                                '--evidence', '`deadbee`')
            self.assertEqual(code, 0, out)
            self.assertIn('## D3 — ', log.read_text(encoding='utf-8'))

    def test_d12_prints_its_census_and_carries_it_into_the_summary(self):
        # D11 prints its done-grain count, D13 its grain dirs, D14 its bugs.
        # Without D12's, "scanned 58 logs / 294 entries", "scanned 1 log" and
        # "scanned 2 logs / 0 entries" print identically — which is exactly what
        # kept a case-folded census and a title-guessing detector invisible.
        with tree(story_statuses=('todo',)) as root:
            (root / 'devkit.toml').write_text(
                '[pm]\nchecks = ["D12"]\n', encoding='utf-8')
            self._log(root, self.ENTRY)
            (root / 'pm/roadmap/0.1-demo/features/alpha/decisions.md').write_text(
                '# preamble only\n\n## no fields here\n\nprose\n', encoding='utf-8')
            code, out = run_gate(root)
            self.assertEqual(code, 0, out)
            self.assertIn('[check:pm] D12: 2 decision log(s), 1 entry/ies', out)
            self.assertIn('PASS', out)
            self.assertIn('2 decision log(s), 1 entry/ies', out.rsplit('PASS', 1)[1])

    def test_d12_reports_a_case_variant_log_instead_of_folding_it_in(self):
        # THE false PASS. `rglob('decisions.md')` resolves a literal final
        # segment through `Path.exists()`, so macOS answers an on-disk
        # `DECISIONS.md` with a path that does not exist — and once ONE log of a
        # tree is migrated the list is non-empty, so the scanned-nothing guard
        # never fires while every other log goes unopened. The census must not
        # count it, and the two platforms must not disagree about it.
        with tree(story_statuses=('todo',)) as root:
            (root / 'devkit.toml').write_text(
                '[pm]\nchecks = ["D12"]\n', encoding='utf-8')
            self._log(root, self.ENTRY)  # the one migrated log
            model.write_raw(
                root / 'pm/roadmap/0.1-demo/features/alpha/DECISIONS.md',
                '## a legacy block\n\n**Decision:** something\n')
            code, out = run_gate(root)
            self.assertEqual(code, 1, out)
            self.assertIn('is a case variant of decisions.md', out)
            self.assertIn('1 decision log(s), 1 entry/ies', out)

    def test_d12_reports_a_log_it_cannot_decode(self):
        # Swallowing the decode error exempts the log from D12 for free and
        # counts it as scanned-with-zero-entries — a silent exemption nobody
        # authored and nobody can see.
        with tree(story_statuses=('todo',)) as root:
            (root / 'devkit.toml').write_text(
                '[pm]\nchecks = ["D12"]\n', encoding='utf-8')
            log = self._log(root, self.ENTRY)
            log.write_bytes(b'## D1 \xff\xfe not utf-8\n')
            code, out = run_gate(root)
            self.assertEqual(code, 1, out)
            self.assertIn('cannot be read', out)
            self.assertIn('1 decision log(s), 0 entry/ies', out)

    def test_d12_a_grandfathered_log_passes_and_the_ledger_size_is_reported(self):
        rel = 'pm/roadmap/0.1-demo/decisions.md'
        legacy = '## M1 — a legacy entry conforming to none of this\n\nProse.\n\n'
        with tree(story_statuses=('todo',)) as root:
            (root / 'devkit.toml').write_text(
                '[pm]\nchecks = ["D12"]\n', encoding='utf-8')
            log = self._log(root, legacy)
            code, out = run_gate(root)
            self.assertEqual(code, 1)

            # Listed, and the same tree is green — with the ledger's size on
            # stdout, so an exemption is visible rather than silently permanent.
            (root / 'devkit.toml').write_text(
                f'[pm]\nchecks = ["D12"]\ndecision_grandfather = ["{rel}"]\n',
                encoding='utf-8')
            code, out = run_gate(root)
            self.assertEqual(code, 0, out)
            self.assertIn('D12 grandfather: 1 decision log(s) exempt', out)
            self.assertIn('may only shrink', out)

            # The CAPPED form is the point of the ledger: legacy entries stay
            # exempt while an entry ADDED past the cap still has to conform.
            (root / 'devkit.toml').write_text(
                f'[pm]\nchecks = ["D12"]\ndecision_grandfather = ["{rel}:1"]\n',
                encoding='utf-8')
            self.assertEqual(run_gate(root)[0], 0)
            log.write_text(log.read_text(encoding='utf-8') + '\n' + self.ENTRY,
                           encoding='utf-8')
            self.assertEqual(run_gate(root)[0], 0)
            log.write_text(log.read_text(encoding='utf-8').replace(
                '**Over:** leaving it on `entity_behavior.gd`, the lean root\n', ''),
                encoding='utf-8')
            code, out = run_gate(root)
            self.assertEqual(code, 1)
            self.assertIn('missing **Over:**', out)

    def test_d12_the_ledger_may_only_shrink(self):
        rel = 'pm/roadmap/0.1-demo/decisions.md'
        with tree(story_statuses=('todo',)) as root:
            # An exemption that suppresses nothing has done its job and must go,
            # or the ledger becomes permanent by inattention.
            (root / 'devkit.toml').write_text(
                f'[pm]\nchecks = ["D12"]\ndecision_grandfather = ["{rel}"]\n',
                encoding='utf-8')
            self._log(root, self.ENTRY)
            code, out = run_gate(root)
            self.assertEqual(code, 1)
            self.assertIn('every entry conforms', out)

            # A cap reaching past the end of the log is a claim the file no
            # longer supports.
            (root / 'devkit.toml').write_text(
                f'[pm]\nchecks = ["D12"]\ndecision_grandfather = ["{rel}:9"]\n',
                encoding='utf-8')
            code, out = run_gate(root)
            self.assertEqual(code, 1)
            self.assertIn('lower the cap', out)

            # A ledger line naming a log that does not exist.
            (root / 'devkit.toml').write_text(
                '[pm]\nchecks = ["D12"]\n'
                'decision_grandfather = ["pm/roadmap/gone/decisions.md"]\n',
                encoding='utf-8')
            code, out = run_gate(root)
            self.assertEqual(code, 1)
            self.assertIn('no such log exists', out)

    def test_d12_scanning_no_decision_log_is_loud(self):
        with tree(story_statuses=('todo',)) as root:
            (root / 'devkit.toml').write_text(
                '[pm]\nchecks = ["D12"]\n', encoding='utf-8')
            code, out = run_gate(root)
            self.assertEqual(code, 1)
            self.assertIn('scanned nothing', out)

    def test_d12_is_silent_when_not_enabled(self):
        with tree(story_statuses=('todo',)) as root:
            self._log(root, '## M1 — nothing here conforms\n\nProse.\n')
            code, out = run_gate(root)
            self.assertEqual(code, 0, out)
            self.assertNotIn('D12', out)

    def test_d12_a_malformed_ledger_spec_is_a_config_error(self):
        with tree(story_statuses=('todo',)) as root:
            (root / 'devkit.toml').write_text(
                '[pm]\nchecks = ["D12"]\n'
                'decision_grandfather = ["pm/roadmap/0.1-demo"]\n',
                encoding='utf-8')
            # Exit 2, never 1: a config typo is not a finding.
            from godot_devkit.core.project import load_config, repo_root
            repo_root.cache_clear()
            load_config.cache_clear()
            with self.assertRaises(model.ConfigError):
                model.load()

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
                '[pm]\nchecks = ["D1","D3","D4","D5","D6","D7"]\n', encoding='utf-8')
            code, out = run_gate(root)
            self.assertEqual(code, 1)
            self.assertNotIn('all stories done', out)
            self.assertIn('only comes from the feature cascade', out)


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
            for slot in model.MILESTONE_DIR_SLOTS:
                self.assertTrue((mf.parent / slot).is_dir(), slot)

    def test_new_renames_a_case_variant_instead_of_writing_past_it(self):
        # macOS is case-INSENSITIVE: open('decisions.md', 'w') next to an
        # existing DECISIONS.md truncates it, so the migration would delete the
        # content it exists to carry forward.
        with tree(story_statuses=('todo',)) as root:
            mdir = root / 'pm/roadmap/0.1-demo'
            legacy = mdir / 'DECISIONS.md'
            legacy.write_text(LEGACY_LOG, encoding='utf-8')
            code, out = run_cli(root, 'new', 'milestone', '0.1')
            self.assertEqual(code, 0, out)
            self.assertIn('renamed DECISIONS.md ->', out)
            self.assertEqual(model.dir_entries(mdir).get('decisions.md'), 'file')
            self.assertNotIn('DECISIONS.md', model.dir_entries(mdir))
            # Every legacy byte survives; only the instruction line is added,
            # because a migration that leaves 60 hand-edits behind is the hand
            # migration this scaffolder exists to avoid.
            body = (mdir / 'decisions.md').read_text(encoding='utf-8')
            self.assertTrue(body.endswith(LEGACY_LOG), body)
            self.assertEqual(model.header_of(mdir / 'decisions.md'),
                             model.SLOT_HEADER['decisions.md'])

    def test_new_records_the_case_rename_in_git_not_only_the_worktree(self):
        # git's default on macOS is `core.ignorecase = true`, and under it a
        # worktree-only rename leaves the INDEX on the old spelling: the tree
        # says decisions.md, `git ls-files` says DECISIONS.md, and an explicit
        # `git add` of the new name stages NOTHING. The migration goes green on
        # the laptop, gets committed, and CI on Linux checks out the old name —
        # D13 then reports every renamed grain missing and D12 scans nothing.
        with tree(story_statuses=('todo',)) as root:
            mdir = root / 'pm/roadmap/0.1-demo'
            model.write_raw(mdir / 'DECISIONS.md', LEGACY_LOG)
            git = ['git', '-c', 'user.email=t@t', '-c', 'user.name=t']
            subprocess.run([*git, 'add', '-A'], cwd=root, check=True)
            subprocess.run([*git, 'commit', '-qm', 'fixture'], cwd=root, check=True)
            tracked = subprocess.run(['git', 'ls-files'], cwd=root, check=True,
                                     capture_output=True, text=True).stdout
            self.assertIn('pm/roadmap/0.1-demo/DECISIONS.md', tracked)

            code, out = run_cli(root, 'new', 'milestone', '0.1')
            self.assertEqual(code, 0, out)
            tracked = subprocess.run(['git', 'ls-files'], cwd=root, check=True,
                                     capture_output=True, text=True).stdout
            self.assertIn('pm/roadmap/0.1-demo/decisions.md', tracked)
            self.assertNotIn('DECISIONS.md', tracked)
            self.assertEqual(model.dir_entries(mdir).get('decisions.md'), 'file')
            self.assertTrue(model.read_raw(mdir / 'decisions.md')
                            .endswith(LEGACY_LOG))

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

    # `nothing was written` is a claim about the WHOLE grain, and the slot order
    # is milestone.md, handoff.md, decisions.md, review.md — so every refusal
    # that keys on decisions.md is reached with handoff.md's rename already
    # decided. Deciding inside the moving loop put that rename on disk and, via
    # `git mv --force`, in the INDEX, where it rides out on the next commit
    # under someone else's message.

    def _committed_legacy_grain(self, root: Path, extra: dict) -> Path:
        mdir = root / 'pm/roadmap/0.1-demo'
        (mdir / 'HANDOFF.md').write_text('# legacy handoff\n', encoding='utf-8')
        for name, body in extra.items():
            if body is None:
                (mdir / name).mkdir()
            else:
                model.write_raw(mdir / name, body)
        git = ['git', '-c', 'user.email=t@t', '-c', 'user.name=t']
        subprocess.run([*git, 'add', '-A'], cwd=root, check=True)
        subprocess.run([*git, 'commit', '-qm', 'fixture'], cwd=root, check=True)
        return mdir

    def _porcelain(self, root: Path) -> str:
        return subprocess.run(['git', 'status', '--porcelain'], cwd=root,
                              check=True, capture_output=True, text=True).stdout

    def test_new_refuses_a_dir_slot_without_staging_an_earlier_rename(self):
        with tree(story_statuses=('todo',)) as root:
            mdir = self._committed_legacy_grain(root, {'decisions.md': None})
            code, out = run_cli(root, 'new', 'milestone', '0.1')
            self.assertEqual(code, 1, out)
            self.assertIn('is a DIRECTORY', out)
            self.assertIn('nothing was written', out)
            # The claim, checked: nothing on disk and nothing in the index.
            self.assertEqual(self._porcelain(root), '')
            self.assertEqual(model.dir_entries(mdir).get('HANDOFF.md'), 'file')

    @unittest.skipUnless(CASE_SENSITIVE_TMP,
                         'two spellings of one name need a case-sensitive FS')
    def test_new_refuses_two_spellings_without_staging_an_earlier_rename(self):
        with tree(story_statuses=('todo',)) as root:
            mdir = self._committed_legacy_grain(
                root, {'DECISIONS.md': LEGACY_LOG, 'Decisions.md': LEGACY_LOG})
            code, out = run_cli(root, 'new', 'milestone', '0.1')
            self.assertEqual(code, 1, out)
            self.assertIn('2 spellings of decisions.md', out)
            self.assertIn('nothing was written', out)
            self.assertEqual(self._porcelain(root), '')
            self.assertEqual(model.dir_entries(mdir).get('HANDOFF.md'), 'file')

    def test_new_never_stacks_a_second_header_on_a_doc_that_has_one(self):
        with tree(story_statuses=('todo',)) as root:
            mdir = root / 'pm/roadmap/0.1-demo'
            self.assertEqual(run_cli(root, 'new', 'milestone', '0.1')[0], 0)
            before = (mdir / 'decisions.md').read_text(encoding='utf-8')
            self.assertEqual(run_cli(root, 'new', 'milestone', '0.1')[0], 0)
            self.assertEqual((mdir / 'decisions.md').read_text(encoding='utf-8'),
                             before)

    def test_new_does_not_mint_a_review_md_on_a_done_grain(self):
        # Otherwise the scaffolder hands D11 a finding it created itself.
        with tree(feature_status='done', story_statuses=('done',)) as root:
            fdir = root / 'pm/roadmap/0.1-demo/features/alpha'
            self.assertEqual(run_cli(root, 'new', 'feature', '0.1', 'alpha')[0], 0)
            self.assertFalse((fdir / 'review.md').exists())
            self.assertTrue((fdir / 'decisions.md').is_file())

    def test_new_needs_a_name_only_when_the_grain_does_not_exist(self):
        with tree(story_statuses=('todo',)) as root:
            code, out = run_cli(root, 'new', 'milestone', '0.2')
            self.assertEqual(code, 2, out)
            self.assertIn('needs a name', out)

    def test_every_shared_doc_ships_its_instruction_header(self):
        with tree(story_statuses=('todo',)) as root:
            self.assertEqual(run_cli(root, 'new', 'milestone', '0.1')[0], 0)
            mdir = root / 'pm/roadmap/0.1-demo'
            for slot, want in model.SLOT_HEADER.items():
                self.assertEqual(model.header_of(mdir / slot), want, slot)


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
        for bad in ('review_min_content_bytes = "twenty"',
                    'review_slug_fallback = "yes"',
                    'place_branch_on_building = "yes"', 'roadmap_dir = 3'):
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


class FlowChecks(unittest.TestCase):
    """D8-D10 — branch-per-milestone + bump-at-start. Off unless opted into."""

    ON = '[pm]\nchecks = ["D8","D9","D10"]\n'

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

    def test_d10_wants_the_integration_branch_in_the_trunk(self):
        with tree(story_statuses=('todo',)) as root:
            self._building(root, branch='feat/0.1-demo', version='0.1')
            (root / 'devkit.toml').write_text(self.ON, encoding='utf-8')
            code, out = run_gate(root)
            self.assertEqual(code, 1)
            self.assertIn('belongs in the trunk', out)

    def test_d10_skips_a_milestone_built_on_the_trunk(self):
        # `branch: staging` means "no integration branch" — not a violation.
        with tree(story_statuses=('todo',)) as root:
            self._building(root, branch='staging', version='0.1')
            (root / 'devkit.toml').write_text(self.ON, encoding='utf-8')
            self.assertEqual(run_gate(root)[0], 0)


class BranchPlacement(unittest.TestCase):
    """`[pm] place_branch_on_building` — the flip also places the branch.

    D10 asserts the milestone's branch is checked out in the trunk. When one
    command creates that obligation and another has to satisfy it by hand, the
    gap between them is where drift lives. What is pinned here is ORDER: every
    refusal is decided BEFORE the flip (so a refused placement leaves
    milestone.md byte-identical), and the flip lands BEFORE the checkout (so a
    failed checkout is a repairable re-run, never a lost transition).
    """

    ON = '[pm]\nplace_branch_on_building = true\n'
    MFILE = 'pm/roadmap/0.1-demo/milestone.md'
    BRANCH = 'feat/0.1-demo'

    @staticmethod
    def _git(root: Path, *args: str, check: bool = True):
        return subprocess.run(
            ['git', '-c', 'user.email=t@example.invalid', '-c', 'user.name=T',
             *args], cwd=root, capture_output=True, text=True, check=check)

    def _head(self, root: Path) -> str:
        return self._git(root, 'branch', '--show-current').stdout.strip()

    def _prepare(self, root: Path, branch: str = BRANCH, config: str = ON,
                 make_branch: bool = True, status: str = 'ready') -> Path:
        """A milestone stamped with `branch:`, on a CLEAN committed trunk.

        The stamps and devkit.toml go in BEFORE the commit on purpose: the
        dirty-trunk refusal has to be something a case opts into, not something
        every case trips over by leaving the fixture uncommitted.
        """
        mfile = root / self.MFILE
        model.set_field(mfile, 'status', status)
        if branch:
            model.set_field(mfile, 'branch', branch)
        (root / 'devkit.toml').write_text(config, encoding='utf-8')
        self._git(root, 'add', '-A')
        self._git(root, 'commit', '-q', '-m', 'fixture')
        if branch and make_branch:
            self._git(root, 'branch', branch)
        return mfile

    def test_off_by_default_the_trunk_never_moves(self):
        with tree() as root:
            mfile = self._prepare(root, config='')
            before = self._head(root)
            code, out = run_cli(root, 'milestone', 'building', '0.1')
            self.assertEqual(code, 0, out)
            self.assertEqual(model.field_of(mfile, 'status'), 'building')
            self.assertEqual(self._head(root), before)

    def test_a_clean_trunk_gets_the_branch_and_the_flip(self):
        with tree() as root:
            mfile = self._prepare(root)
            code, out = run_cli(root, 'milestone', 'building', '0.1')
            self.assertEqual(code, 0, out)
            self.assertEqual(model.field_of(mfile, 'status'), 'building')
            self.assertEqual(self._head(root), self.BRANCH)
            self.assertIn('checked out', out)

    def test_a_dirty_trunk_refuses_and_flips_nothing(self):
        with tree() as root:
            mfile = self._prepare(root)
            before_head, before_bytes = self._head(root), mfile.read_bytes()
            (root / 'stray.txt').write_text('uncommitted', encoding='utf-8')
            code, out = run_cli(root, 'milestone', 'building', '0.1')
            self.assertEqual(code, 1, out)
            self.assertIn('dirty', out)
            # The refusal is decided before the write, so the file is untouched.
            self.assertEqual(mfile.read_bytes(), before_bytes)
            self.assertEqual(self._head(root), before_head)

    def test_a_missing_branch_refuses_rather_than_minting_it(self):
        with tree() as root:
            mfile = self._prepare(root, make_branch=False)
            code, out = run_cli(root, 'milestone', 'building', '0.1')
            self.assertEqual(code, 1, out)
            self.assertIn('does not exist', out)
            self.assertIn('checkout -b', out)
            self.assertEqual(model.field_of(mfile, 'status'), 'ready')

    def test_a_branch_held_by_another_worktree_refuses_and_names_the_holder(self):
        with tree() as root:
            mfile = self._prepare(root)
            other = root.parent / 'held'
            self._git(root, 'worktree', 'add', '-q', str(other), self.BRANCH)
            code, out = run_cli(root, 'milestone', 'building', '0.1')
            self.assertEqual(code, 1, out)
            self.assertIn(str(other), out)
            self.assertIn('worktree remove', out)
            self.assertEqual(model.field_of(mfile, 'status'), 'ready')

    def test_no_branch_stamp_refuses_and_names_the_fix(self):
        with tree() as root:
            mfile = self._prepare(root, branch='')
            code, out = run_cli(root, 'milestone', 'building', '0.1')
            self.assertEqual(code, 1, out)
            self.assertIn('declares no branch', out)
            self.assertIn('pm set 0.1 branch', out)
            self.assertEqual(model.field_of(mfile, 'status'), 'ready')

    def test_rerunning_on_an_already_building_milestone_repairs_the_trunk(self):
        # The milestone is committed at `building`, so both runs take the no-op
        # path and the trunk stays clean — the drift being repaired is purely
        # the trunk sitting on the wrong branch, which is the D10 finding.
        with tree() as root:
            self._prepare(root, status='building')
            trunk_was = self._head(root)
            code, out = run_cli(root, 'milestone', 'building', '0.1')
            self.assertEqual(code, 0, out)
            self.assertEqual(self._head(root), self.BRANCH)
            # Somebody switched the trunk away.
            self._git(root, 'checkout', '-q', trunk_was)
            code, out = run_cli(root, 'milestone', 'building', '0.1')
            self.assertEqual(code, 0, out)
            self.assertIn('already building', out)
            self.assertEqual(self._head(root), self.BRANCH)

    def test_a_trunk_branch_places_nothing_but_says_so(self):
        # `branch: main` means "no integration branch" — a real answer, and a
        # placement command that printed nothing would read as a failure.
        with tree() as root:
            mfile = self._prepare(root, branch='main', make_branch=False)
            before = self._head(root)
            code, out = run_cli(root, 'milestone', 'building', '0.1')
            self.assertEqual(code, 0, out)
            self.assertIn('nothing to place', out)
            self.assertEqual(model.field_of(mfile, 'status'), 'building')
            self.assertEqual(self._head(root), before)

    def test_a_checkout_failing_after_the_flip_is_an_idempotent_rerun(self):
        """The flip lands first, so its failure mode is repair, not rollback.

        Setup: `.git` is made read-only. `git status --porcelain` still answers
        (clean, exit 0) off the fresh index, so the placement is approved and
        the flip lands — but the checkout cannot take `index.lock` and dies.
        Making the WORKING TREE unwritable instead does not work: git reports
        `unable to create file …` and still exits 0 with HEAD moved.
        """
        with tree() as root:
            mfile = self._prepare(root)
            trunk_was = self._head(root)
            os.chmod(root / '.git', 0o555)
            try:
                code, out = run_cli(root, 'milestone', 'building', '0.1')
            finally:
                os.chmod(root / '.git', 0o755)
            self.assertEqual(code, 2, out)
            self.assertEqual(model.field_of(mfile, 'status'), 'building')
            self.assertIn('re-run', out)
            self.assertEqual(self._head(root), trunk_was)


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
                code, out = run_cli(root, 'feature', 'done', '0.1/alpha')
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


class Prune(unittest.TestCase):
    def _commit(self, root: Path) -> None:
        for args in (['add', '-A'], ['-c', 'user.email=t@t', '-c', 'user.name=t',
                                     'commit', '-qm', 'x']):
            subprocess.run(['git', *args], cwd=root, check=True,
                           capture_output=True)

    def test_the_resurrect_anchor_is_written_even_with_no_roadmap_index(self):
        with tree(milestone_status='done', feature_status='done',
                  story_statuses=('done',)) as root:
            other = root / 'pm/roadmap/0.2-later'
            write(other / 'milestone.md',
                  {'id': '"0.2"', 'name': 'Later', 'status': 'done'})
            self._commit(root)
            self.assertFalse((root / 'pm/roadmap/ROADMAP.md').exists())
            code, out = run_cli(root, 'prune')
            self.assertEqual(code, 0, out)
            index = root / 'pm/roadmap/ROADMAP.md'
            # The anchor is the only way back to what prune deleted; claiming to
            # have stamped it without doing so is the failure this pins.
            self.assertTrue(index.is_file())
            self.assertIn('Prune log', index.read_text())

    def test_lag_by_one_keeps_the_version_newest_not_the_lexically_last(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'repo'
            for v in ('0.9', '0.10', '0.11'):
                write(root / f'pm/roadmap/{v}-m/milestone.md',
                      {'id': f'"{v}"', 'name': v, 'status': 'done'})
            subprocess.run(['git', 'init', '-q'], cwd=root, check=True)
            previous = Path.cwd()
            os.chdir(root)
            try:
                self._commit(root)
                code, out = run_cli(root, 'prune')
            finally:
                os.chdir(previous)
            self.assertEqual(code, 0, out)
            survivors = sorted(p.name for p in (root / 'pm/roadmap').iterdir()
                               if p.is_dir())
            self.assertEqual(survivors, ['0.11-m'])

    def test_prune_refuses_a_dirty_tree(self):
        with tree(milestone_status='done', feature_status='done',
                  story_statuses=('done',)) as root:
            self._commit(root)
            (root / 'dirty.txt').write_text('x', encoding='utf-8')
            code, out = run_cli(root, 'prune')
            self.assertEqual(code, 1)
            self.assertIn('dirty', out)


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

    def test_v5_phase_monotone(self):
        with tree() as root:
            run_cli(root, 'new', 'feature', '0.1', 'beta', 'Beta')
            fdir = root / 'pm/roadmap/0.1-demo/features'
            model.set_field(fdir / 'alpha/feature.md', 'phase', '1')
            model.set_field(fdir / 'alpha/feature.md', 'depends_on', '["0.1/beta"]')
            model.set_field(fdir / 'beta/feature.md', 'phase', '2')
            findings, _ = self._run(root)
            self.assertTrue(any('LATER phase' in f for f in findings), findings)

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

    def test_install_refuses_to_clobber_a_file_it_did_not_write(self):
        with tree() as root:
            rule = root / '.claude/rules/pm-execution.md'
            rule.parent.mkdir(parents=True, exist_ok=True)
            rule.write_text('# our own version\n', encoding='utf-8')
            code, out = run_cli(root, 'install-skills')
            self.assertEqual(code, 1)
            self.assertIn('not generated by this tool', out)
            self.assertEqual(rule.read_text(), '# our own version\n')

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

    def test_d10_says_so_when_it_cannot_see_the_trunk(self):
        # Detached HEAD is what CI checks out; silently skipping there turned
        # D10 off in the one environment it guards.
        with tree(milestone_status='building', story_statuses=('todo',)) as root:
            model.set_field(root / 'pm/roadmap/0.1-demo/milestone.md',
                            'branch', 'feat/0.1-demo')
            (root / 'project.godot').write_text(
                '[application]\nconfig/version="0.1"\n', encoding='utf-8')
            (root / 'devkit.toml').write_text(
                '[pm]\nchecks = ["D10"]\n', encoding='utf-8')
            subprocess.run(['git', 'add', '-A'], cwd=root, check=True,
                           capture_output=True)
            subprocess.run(['git', '-c', 'user.email=t@t', '-c', 'user.name=t',
                            'commit', '-qm', 'x'], cwd=root, check=True,
                           capture_output=True)
            subprocess.run(['git', 'checkout', '--detach', '-q', 'HEAD'],
                           cwd=root, check=True, capture_output=True)
            code, out = run_gate(root)
            self.assertIn('UNVERIFIED', out)
            self.assertIn('DETACHED', out)


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


class PhaseEdges(unittest.TestCase):
    def test_a_numeric_phase_may_not_depend_on_an_unordered_one(self):
        # `seam` means nothing blocks on it; sitting mid-chain contradicts that.
        with tree() as root:
            run_cli(root, 'new', 'feature', '0.1', 'beta', 'Beta')
            fdir = root / 'pm/roadmap/0.1-demo/features'
            model.set_field(fdir / 'alpha/feature.md', 'phase', '2')
            model.set_field(fdir / 'alpha/feature.md', 'depends_on', '["0.1/beta"]')
            model.set_field(fdir / 'beta/feature.md', 'phase', 'seam')
            from godot_devkit.repo.pm import validate
            findings = validate.run(model.PmConfig(root=root))[0]
            self.assertTrue(any('seam' in f for f in findings), findings)

    def test_an_unphased_milestone_raises_no_phase_findings(self):
        with tree() as root:
            run_cli(root, 'new', 'feature', '0.1', 'beta', 'Beta')
            fdir = root / 'pm/roadmap/0.1-demo/features'
            model.set_field(fdir / 'alpha/feature.md', 'depends_on', '["0.1/beta"]')
            from godot_devkit.repo.pm import validate
            self.assertEqual(validate.run(model.PmConfig(root=root))[0], [])


class Templates(unittest.TestCase):
    def test_new_grains_come_from_templates_and_validate(self):
        with tree() as root:
            self.assertEqual(run_cli(root, 'new', 'feature', '0.1', 'b', 'B')[0], 0)
            ff = root / 'pm/roadmap/0.1-demo/features/b/feature.md'
            self.assertEqual(model.field_of(ff, 'id'), '0.1/b')
            self.assertEqual(model.field_of(ff, 'milestone'), '0.1')
            self.assertEqual(run_cli(root, 'validate')[0], 0)

    def test_a_new_milestone_gets_handoff_and_decisions(self):
        # EXACT names, from a listing: `is_file()` here passed on macOS against
        # the OLD uppercase spellings long after the rename landed, and would
        # have failed in CI on Linux. The slot names are the assertion.
        with tree() as root:
            run_cli(root, 'new', 'milestone', '0.2', 'Second')
            mdir = root / 'pm/roadmap/0.2-second'
            entries = model.dir_entries(mdir)
            for f in model.MILESTONE_FILE_SLOTS:
                self.assertEqual(entries.get(f), 'file', f)
            self.assertIn('0.2 Second', (mdir / 'handoff.md').read_text())

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

            # Renamed, it is the template `new` renders from — the whole point.
            # Through a temp name: a direct rename is a no-op on macOS.
            (tdir / 'DECISIONS.md').rename(tdir / 'x.tmp')
            (tdir / 'x.tmp').rename(tdir / 'decisions.md')
            self.assertEqual(run_cli(root, 'new', 'milestone', '0.3', 'Third')[0], 0)
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

    def test_status_is_refused(self):
        # It has a transition graph and preconditions behind it; a settable
        # status would reopen the hole the CLI exists to close.
        with tree(story_statuses=('todo',)) as root:
            code, out = run_cli(root, 'set', '0.1/alpha/s0', 'status', 'done')
            self.assertEqual(code, 1)
            self.assertIn('transition', out)
            sf = root / 'pm/roadmap/0.1-demo/features/alpha/stories/s0.md'
            self.assertEqual(model.field_of(sf, 'status'), 'todo')

    def test_claim_and_release_move_owner(self):
        with tree(story_statuses=('todo',)) as root:
            sf = root / 'pm/roadmap/0.1-demo/features/alpha/stories/s0.md'
            run_cli(root, 'claim', '0.1/alpha/s0', 'dev-1')
            self.assertEqual(model.field_of(sf, 'owner'), 'dev-1')
            run_cli(root, 'release', '0.1/alpha/s0')
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

    def test_v6_catches_a_stale_list(self):
        with tree(story_statuses=('todo',)) as root:
            run_cli(root, 'sync')
            run_cli(root, 'new', 'feature', '0.1', 'newcomer', 'Newcomer')
            self.assertTrue(any('stale' in f for f in self._validate(root)[0]))
            self.assertEqual(run_cli(root, 'sync', '--check')[0], 1)
            run_cli(root, 'sync')
            self.assertEqual(run_cli(root, 'sync', '--check')[0], 0)

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


class AgentDefinitions(unittest.TestCase):
    """`check agents` — definitions that instruct what the tooling refuses."""

    def _gate(self, root: Path):
        from godot_devkit.repo.checks import agents
        from godot_devkit.core.config import config_section
        from godot_devkit.core.project import load_config, repo_root
        repo_root.cache_clear()
        load_config.cache_clear()
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = agents.run()
        return code, buf.getvalue()

    def _def(self, root: Path, rel: str, body: str) -> None:
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding='utf-8')

    def test_a_legal_workflow_passes(self):
        with tree() as root:
            self._def(root, '.claude/agents/dev.md',
                      'Claim with `pm story wip <id>`, then the reviewer runs\n'
                      '`pm story review <id>`. A story goes wip -> review.\n')
            code, out = self._gate(root)
            self.assertEqual(code, 0, out)

    def test_an_impossible_story_transition_is_caught(self):
        # The real drift: a story reaching done outside the feature cascade.
        with tree() as root:
            self._def(root, '.claude/agents/po.md',
                      'When the story is verified, flip `status: review -> done`.\n')
            code, out = self._gate(root)
            self.assertEqual(code, 1)
            self.assertIn('review -> done', out)
            self.assertIn('cascade', out)

    def test_the_same_transition_is_legal_for_a_feature(self):
        # review -> done IS the feature close edge. Grain context decides.
        with tree() as root:
            self._def(root, '.claude/agents/po.md',
                      'Close the feature: it moves review -> done.\n')
            self.assertEqual(self._gate(root)[0], 0)

    def test_a_nonexistent_verb_is_caught(self):
        with tree() as root:
            self._def(root, '.claude/agents/dev.md', 'Run `pm story done <id>`.\n')
            code, out = self._gate(root)
            self.assertEqual(code, 1)
            self.assertIn("no 'done' verb", out)

    def test_an_ambiguous_line_is_censused_not_guessed(self):
        # Precision over reach: a false FAIL gets the gate switched off.
        with tree() as root:
            self._def(root, '.claude/agents/po.md',
                      'The milestone is building; your stories go review -> done.\n')
            code, out = self._gate(root)
            self.assertEqual(code, 0, out)
            self.assertIn('UNVERIFIED', out)

    def test_a_flat_skill_file_is_caught(self):
        with tree() as root:
            self._def(root, '.claude/skills/planning.md', '# Planning\n')
            code, out = self._gate(root)
            self.assertEqual(code, 1)
            self.assertIn('does NOT load as a skill', out)

    def test_a_correctly_shaped_skill_passes(self):
        with tree() as root:
            self._def(root, '.claude/skills/planning/SKILL.md', '# Planning\n')
            self.assertEqual(self._gate(root)[0], 0)

    def test_a_configured_forbidden_pattern_fires(self):
        with tree() as root:
            self._def(root, '.claude/agents/dev.md', 'Run godot --headless yourself.\n')
            (root / 'devkit.toml').write_text(
                '[agents]\nforbidden = ["godot --headless"]\n', encoding='utf-8')
            code, out = self._gate(root)
            self.assertEqual(code, 1)
            self.assertIn('forbidden pattern', out)

    def test_scanning_nothing_fails_rather_than_passing(self):
        with tree() as root:
            code, out = self._gate(root)
            self.assertEqual(code, 1)
            self.assertIn('scanned 0 definitions', out)


class Vocabulary(unittest.TestCase):
    def test_json_states_the_story_terminal_machine_readably(self):
        # The whole point: a checker must never scrape help text.
        import json
        with tree() as root:
            code, out = run_cli(root, 'vocabulary', '--json')
            self.assertEqual(code, 0)
            data = json.loads(out)
            self.assertEqual(data['notes']['story_terminal'], 'review')
            self.assertNotIn('done', data['grains']['story']['verbs'])
            self.assertIn('done', data['grains']['feature']['verbs'])


class EveryConfigSection(unittest.TestCase):
    """The gap that let a false PASS survive a refactor meant to remove it.

    Every exit-2 config assertion lived in test_pm.py, so `[defaults]` kept the
    literal `tuple(cfg.get(...))` CLAUDE.md forbids by name — and a bare-string
    exclude hid two real findings while printing PASS.
    """

    SECTIONS = (
        ('uid', 'exclude_prefixes'), ('tres', 'exclude_prefixes'),
        ('props', 'exclude_prefixes'), ('defaults', 'exclude_prefixes'),
        ('shell', 'roots'), ('doc', 'scope'), ('agents', 'scope'),
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


class AgentGatePrecision(unittest.TestCase):
    """A false FAIL gets a gate switched off; these are the four that shipped."""

    def _gate(self, root: Path):
        from godot_devkit.repo.checks import agents
        from godot_devkit.core.project import load_config, repo_root
        repo_root.cache_clear()
        load_config.cache_clear()
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = agents.run()
        return code, buf.getvalue()

    def _write(self, root: Path, rel: str, body: str) -> None:
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding='utf-8')

    def test_a_supporting_file_in_a_real_skill_dir_is_not_a_flat_skill(self):
        with tree() as root:
            self._write(root, '.claude/skills/mine/SKILL.md', '# s\n')
            self._write(root, '.claude/skills/mine/references/api.md', '# api\n')
            code, out = self._gate(root)
            self.assertEqual(code, 0, out)

    def test_a_fenced_example_is_not_an_instruction(self):
        with tree() as root:
            self._write(root, '.claude/rules/r.md',
                        '```\n[pm] REFUSED — story wip -> done\n```\n')
            self.assertEqual(self._gate(root)[0], 0)

    def test_prose_prohibiting_a_transition_is_not_instructing_it(self):
        with tree() as root:
            self._write(root, '.claude/rules/r.md',
                        'Never flip a story wip -> done; the CLI refuses it.\n')
            self.assertEqual(self._gate(root)[0], 0)

    def test_unbackticked_prose_is_not_an_invocation(self):
        with tree() as root:
            self._write(root, '.claude/agents/a.md',
                        'The pm feature and pm milestone verbs both take an id.\n')
            self.assertEqual(self._gate(root)[0], 0)

    def test_a_chained_arrow_does_not_hide_its_middle_edge(self):
        # findall is non-overlapping: `a -> b -> c` silently dropped (b, c).
        with tree() as root:
            self._write(root, '.claude/rules/r.md',
                        'The milestone lifecycle is planning -> ready -> done.\n')
            code, out = self._gate(root)
            self.assertEqual(code, 1)
            self.assertIn('ready -> done', out)

    def test_an_unknown_state_is_censused_not_dropped(self):
        with tree() as root:
            self._write(root, '.claude/rules/r.md',
                        'A story goes todo -> reviewd (a typo in this doc).\n')
            code, out = self._gate(root)
            self.assertEqual(code, 0, out)
            self.assertIn('UNVERIFIED', out)


class BlockedIsNotATrap(unittest.TestCase):
    def test_a_blocked_story_can_be_unblocked_through_the_cli(self):
        # The only exit used to be the hand-edit the tracker exists to prevent.
        with tree(story_statuses=('todo',)) as root:
            self.assertEqual(run_cli(root, 'story', 'wip', '0.1/alpha/s0')[0], 0)
            self.assertEqual(run_cli(root, 'story', 'blocked', '0.1/alpha/s0')[0], 0)
            self.assertEqual(run_cli(root, 'story', 'wip', '0.1/alpha/s0')[0], 0)
            self.assertEqual(run_cli(root, 'story', 'review', '0.1/alpha/s0')[0], 0)


class TemplateCannotMintPastTheGraph(unittest.TestCase):
    def test_a_template_naming_a_later_status_is_refused(self):
        with tree() as root:
            (root / 'devkit.toml').write_text(
                '[pm]\ntemplate_dir = "pm/templates"\n', encoding='utf-8')
            run_cli(root, 'templates')
            t = root / 'pm/templates/feature.md'
            t.write_text(t.read_text().replace('status: planning', 'status: done'),
                         encoding='utf-8')
            code, out = run_cli(root, 'new', 'feature', '0.1', 'sneaky', 'S')
            self.assertEqual(code, 1)
            self.assertIn('moves only through the CLI', out)



class Retention(unittest.TestCase):
    """D11 — the transient `review.md` outliving the grain that owns it.

    Co-located, so the rule asks one question at a known path and guesses at
    nothing. What it replaces resolved a findings-doc FILENAME back to the grain
    it "named", and on a real 123-doc corpus that resolved 6 — precisely the
    durable ones `reviewed:` already pointed at. Anchoring the match could only
    ever remove matches, which is why this is a rewrite and not a repair.
    """

    TOML = '[pm]\nchecks = ["D11"]\n'
    FDIR = 'pm/roadmap/0.1-demo/features/alpha'
    MDIR = 'pm/roadmap/0.1-demo'

    @staticmethod
    def _review(root: Path, rel: str) -> Path:
        p = root / rel / model.REVIEW_FILE_NAME
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(f'{model.SLOT_HEADER["review.md"]}\n\n# review\n',
                     encoding='utf-8')
        return p

    @staticmethod
    def _close(root: Path, rel: str) -> None:
        f = root / rel
        f.write_text(f.read_text(encoding='utf-8').replace(
            'status: building', 'status: done'), encoding='utf-8')

    def test_a_review_outliving_its_done_feature_is_drift_and_not_before(self):
        # The same file is legitimate WHILE the grain is open and dead weight
        # the moment it closes. A rule that merely flagged its presence would be
        # wrong for the whole first half of the grain's life.
        with tree(feature_status='building', story_statuses=('review',)) as root:
            (root / 'devkit.toml').write_text(self.TOML, encoding='utf-8')
            self._review(root, self.FDIR)
            code, out = run_gate(root)
            self.assertEqual(code, 0, out)

            self._close(root, f'{self.FDIR}/feature.md')
            code, out = run_gate(root)
            self.assertEqual(code, 1, out)
            self.assertIn(f'{self.FDIR}/review.md is transient but feature '
                          f'0.1/alpha is done', out)
            self.assertIn('decisions.md', out)

    def test_a_done_milestone_with_a_review_is_drift_too(self):
        # Milestones get the rule as well. The old D11 had to skip them: it
        # resolved through `reviewed:`, which exists only on feature.md, so a
        # milestone-scoped doc had no green state and the finding ordered a
        # repair the schema could not accept. A co-located slot has one.
        with tree(milestone_status='done', feature_status='done',
                  story_statuses=('done',)) as root:
            (root / 'devkit.toml').write_text(self.TOML, encoding='utf-8')
            self._review(root, self.MDIR)
            code, out = run_gate(root)
            self.assertEqual(code, 1, out)
            self.assertIn('milestone 0.1 is done', out)

    def test_no_done_grain_is_named_rather_than_silently_passed(self):
        # Not a FINDING — "nothing has closed yet" is this rule's own success
        # state, unlike D12, whose missing log means it can never fire at all.
        with tree(feature_status='building', story_statuses=('todo',)) as root:
            (root / 'devkit.toml').write_text(self.TOML, encoding='utf-8')
            code, out = run_gate(root)
            self.assertEqual(code, 0, out)
            self.assertIn('no `done` grain in the tree', out)

    def test_the_census_carries_the_done_grain_count(self):
        with tree(milestone_status='done', feature_status='done',
                  story_statuses=('done',)) as root:
            (root / 'devkit.toml').write_text(self.TOML, encoding='utf-8')
            code, out = run_gate(root)
            self.assertEqual(code, 0, out)
            self.assertIn('2 done grain(s)', out)

    def test_d11_is_silent_when_not_enabled(self):
        with tree(feature_status='done', story_statuses=('done',)) as root:
            (root / 'devkit.toml').write_text(
                '[pm]\nchecks = ["D4"]\n', encoding='utf-8')
            self._review(root, self.FDIR)
            code, out = run_gate(root)
            self.assertEqual(code, 0, out)
            self.assertNotIn('is transient', out)
            self.assertNotIn('done grain(s)', out)


class Structure(unittest.TestCase):
    """D13 — the canonical slots. Missing is drift AND extra is drift.

    The extra half is the one that earns the rule. Every invented sibling in a
    real tree (`plans/`, `findings/`, `AUDIT-REPORT.md`, `audit-prompt.md`,
    `DELETED-SCENARIO-LEDGER.md`) exists because no slot was scaffolded AND
    nothing flagged the invention; a missing-only check leaves all of them.
    """

    TOML = '[pm]\nchecks = ["D13"]\n'
    MDIR = 'pm/roadmap/0.1-demo'
    FDIR = 'pm/roadmap/0.1-demo/features/alpha'

    def _scaffolded(self, root: Path) -> None:
        self.assertEqual(run_cli(root, 'new', 'milestone', '0.1')[0], 0)
        self.assertEqual(run_cli(root, 'new', 'feature', '0.1', 'alpha')[0], 0)

    def test_a_scaffolded_tree_satisfies_the_rule(self):
        with tree(feature_status='building', story_statuses=('todo',)) as root:
            (root / 'devkit.toml').write_text(self.TOML, encoding='utf-8')
            self._scaffolded(root)
            code, out = run_gate(root)
            self.assertEqual(code, 0, out)
            self.assertIn('2 grain dir(s)', out)

    def test_a_missing_slot_is_drift(self):
        with tree(feature_status='building', story_statuses=('todo',)) as root:
            (root / 'devkit.toml').write_text(self.TOML, encoding='utf-8')
            self._scaffolded(root)
            (root / self.MDIR / 'handoff.md').unlink()
            code, out = run_gate(root)
            self.assertEqual(code, 1, out)
            self.assertIn('is missing handoff.md', out)

    def test_an_extra_slot_is_drift(self):
        # The half that matters. Each of these is a real invention from a real
        # consumer tree, and none of them would ever be reported by a
        # missing-only structure check.
        for name, is_dir in (('plans', True), ('findings', True),
                             ('AUDIT-REPORT.md', False),
                             ('DELETED-SCENARIO-LEDGER.md', False)):
            with self.subTest(name=name):
                with tree(feature_status='building',
                          story_statuses=('todo',)) as root:
                    (root / 'devkit.toml').write_text(self.TOML, encoding='utf-8')
                    self._scaffolded(root)
                    target = root / self.FDIR / name
                    if is_dir:
                        target.mkdir()
                        (target / 'x.md').write_text('x\n', encoding='utf-8')
                    else:
                        target.write_text('x\n', encoding='utf-8')
                    code, out = run_gate(root)
                    self.assertEqual(code, 1, out)
                    self.assertIn(f'carries {name}', out)
                    self.assertIn('not a canonical slot', out)

    def test_a_mangled_header_is_drift(self):
        # The header is the ONE delivery channel with a 100% hit rate for a
        # dispatched agent, so it has to be unrottable, not merely present once.
        with tree(feature_status='building', story_statuses=('todo',)) as root:
            (root / 'devkit.toml').write_text(self.TOML, encoding='utf-8')
            self._scaffolded(root)
            log = root / self.FDIR / 'decisions.md'
            log.write_text('# 0.1/alpha — decisions\n\nnotes\n', encoding='utf-8')
            code, out = run_gate(root)
            self.assertEqual(code, 1, out)
            self.assertIn('no longer opens with its instruction line', out)
            self.assertIn('godot-devkit pm decide', out)

    def test_review_md_is_required_open_and_forbidden_done_with_no_overlap(self):
        # The two halves of one fact. D13 owns the open half, D11 the closed
        # one, and a `done` grain must never be told both to have the file and
        # to delete it.
        with tree(feature_status='building', story_statuses=('review',)) as root:
            (root / 'devkit.toml').write_text(
                '[pm]\nchecks = ["D11","D13"]\n', encoding='utf-8')
            self._scaffolded(root)
            (root / self.FDIR / 'review.md').unlink()
            code, out = run_gate(root)
            self.assertEqual(code, 1, out)
            self.assertIn('is missing review.md', out)

            f = root / self.FDIR / 'feature.md'
            f.write_text(f.read_text(encoding='utf-8').replace(
                'status: building', 'status: done'), encoding='utf-8')
            code, out = run_gate(root)
            self.assertEqual(code, 0, out)

    def test_a_case_variant_is_both_missing_and_extra(self):
        # `DECISIONS.md` vs `decisions.md`. macOS resolves one to the other and
        # Linux does not, so existence is decided from a directory LISTING —
        # otherwise the same tree is clean on a laptop and drifting in CI.
        with tree(feature_status='building', story_statuses=('todo',)) as root:
            (root / 'devkit.toml').write_text(self.TOML, encoding='utf-8')
            self._scaffolded(root)
            src = root / self.FDIR / 'decisions.md'
            body = src.read_text(encoding='utf-8')
            src.rename(src.with_name('decisions.tmp'))
            (src.parent / 'decisions.tmp').rename(src.with_name('DECISIONS.md'))
            code, out = run_gate(root)
            self.assertEqual(code, 1, out)
            self.assertIn('is missing decisions.md', out)
            self.assertIn('DECISIONS.md is the same slot in another case', out)
            self.assertIn('carries DECISIONS.md', out)
            self.assertEqual(
                (root / self.FDIR / 'DECISIONS.md').read_text(encoding='utf-8'),
                body)

    def test_d13_is_silent_when_not_enabled(self):
        with tree(feature_status='building', story_statuses=('todo',)) as root:
            code, out = run_gate(root)
            self.assertEqual(code, 0, out)
            self.assertNotIn('D13', out)


class BugLifetime(unittest.TestCase):
    """D14 — a bug lives in the milestone that will FIX it.

    Not cosmetic: `prune`'s lag-by-one deletes a done milestone's directory the
    moment the next one closes, so an open bug parked in a closed milestone is
    already scheduled for deletion. One consumer holds 28 of them.
    """

    TOML = '[pm]\nchecks = ["D14"]\n'

    @staticmethod
    def _bug(root: Path, slug: str, status: str, **extra) -> Path:
        p = root / 'pm/roadmap/0.1-demo/bugs' / f'{slug}.md'
        front = {'id': f'0.1/bugs/{slug}', 'milestone': '"0.1"',
                 'status': status, 'caught_in': '"0.1"'}
        front.update(extra)
        write(p, front)
        return p

    def test_an_open_bug_under_a_done_milestone_is_drift(self):
        with tree(milestone_status='done', feature_status='done',
                  story_statuses=('done',)) as root:
            (root / 'devkit.toml').write_text(self.TOML, encoding='utf-8')
            self._bug(root, 'seed-is-zero', 'open', fix_milestone='"0.2"')
            code, out = run_gate(root)
            self.assertEqual(code, 1, out)
            self.assertIn("is 'open' under the done milestone 0.1", out)
            # The repair names where it goes, from the bug's own decision.
            self.assertIn('move it to 0.2/bugs/', out)

    def test_an_untriaged_open_bug_is_told_to_decide_first(self):
        with tree(milestone_status='done', feature_status='done',
                  story_statuses=('done',)) as root:
            (root / 'devkit.toml').write_text(self.TOML, encoding='utf-8')
            self._bug(root, 'seed-is-zero', 'open')
            code, out = run_gate(root)
            self.assertEqual(code, 1, out)
            self.assertIn('set fix_milestone:', out)

    def test_a_closed_bug_under_a_done_milestone_is_fine(self):
        # Where a FIXED bug lives is history, and history is exactly what the
        # done milestone's directory is for.
        with tree(milestone_status='done', feature_status='done',
                  story_statuses=('done',)) as root:
            (root / 'devkit.toml').write_text(self.TOML, encoding='utf-8')
            self._bug(root, 'seed-is-zero', 'fixed')
            code, out = run_gate(root)
            self.assertEqual(code, 0, out)

    def test_an_open_bug_under_a_live_milestone_is_fine(self):
        with tree(milestone_status='building', feature_status='building',
                  story_statuses=('todo',)) as root:
            (root / 'devkit.toml').write_text(self.TOML, encoding='utf-8')
            self._bug(root, 'seed-is-zero', 'open')
            code, out = run_gate(root)
            self.assertEqual(code, 0, out)

    def test_a_status_outside_the_vocabulary_is_a_finding_not_a_silent_close(self):
        # D4 does not cover bugs, so a typo'd status would otherwise read as
        # "not open" and be passed in silence — rule 4's cardinal sin.
        with tree(milestone_status='done', feature_status='done',
                  story_statuses=('done',)) as root:
            (root / 'devkit.toml').write_text(self.TOML, encoding='utf-8')
            self._bug(root, 'seed-is-zero', 'opne')
            code, out = run_gate(root)
            self.assertEqual(code, 1, out)
            self.assertIn("bug status 'opne' is not in", out)

    def test_bug_open_states_must_be_in_bug_states(self):
        with tree(story_statuses=('todo',)) as root:
            (root / 'devkit.toml').write_text(
                '[pm]\nchecks = ["D14"]\nbug_open_states = ["triage"]\n',
                encoding='utf-8')
            from godot_devkit.core.project import load_config, repo_root
            repo_root.cache_clear()
            load_config.cache_clear()
            with self.assertRaises(model.ConfigError):
                model.load()

    def test_no_bug_file_is_named_rather_than_silently_passed(self):
        with tree(milestone_status='done', feature_status='done',
                  story_statuses=('done',)) as root:
            (root / 'devkit.toml').write_text(self.TOML, encoding='utf-8')
            code, out = run_gate(root)
            self.assertEqual(code, 0, out)
            self.assertIn('no bug files under', out)

    def test_d14_is_silent_when_not_enabled(self):
        with tree(milestone_status='done', feature_status='done',
                  story_statuses=('done',)) as root:
            (root / 'devkit.toml').write_text(
                '[pm]\nchecks = ["D4"]\n', encoding='utf-8')
            self._bug(root, 'seed-is-zero', 'open')
            code, out = run_gate(root)
            self.assertEqual(code, 0, out)
            self.assertNotIn('D14', out)


class Decide(unittest.TestCase):
    """`pm decide` — the writer that cannot produce what the gate rejects.

    It stamps the two things authors get wrong (the date and the ordinal) and
    validates every value through D12's OWN predicates, so a non-conforming
    entry is refused before the write rather than reported after it.
    """

    ARGS = ('--chose', 'move the sweep verb to combat_behavior.gd',
            '--over', 'leaving it on entity_behavior.gd, the lean root',
            '--because', 'all three consumers extend the combat layer',
            '--evidence', '64e89ad5b')
    MDIR = 'pm/roadmap/0.1-demo'

    def _scaffolded(self, root: Path) -> None:
        self.assertEqual(run_cli(root, 'new', 'milestone', '0.1')[0], 0)
        self.assertEqual(run_cli(root, 'new', 'feature', '0.1', 'alpha')[0], 0)

    def test_it_allocates_D1_on_an_empty_log_and_the_next_ordinal_after_that(self):
        with tree(feature_status='building', story_statuses=('todo',)) as root:
            self._scaffolded(root)
            log = root / self.MDIR / 'decisions.md'
            self.assertEqual(run_cli(root, 'decide', '0.1', *self.ARGS)[0], 0)
            self.assertIn('## D1 — ', log.read_text(encoding='utf-8'))
            self.assertEqual(run_cli(root, 'decide', '0.1', *self.ARGS)[0], 0)
            self.assertIn('## D2 — ', log.read_text(encoding='utf-8'))
            self.assertEqual(len(model.decision_entries_in(model.read_raw(log))), 2)

    def test_it_keeps_the_logs_own_id_prefix(self):
        # A tree that numbers `M27` keeps numbering `M`. The prefix is the
        # log's, not the tool's.
        with tree(feature_status='building', story_statuses=('todo',)) as root:
            self._scaffolded(root)
            log = root / self.MDIR / 'decisions.md'
            log.write_text(log.read_text(encoding='utf-8')
                           + '\n## M27 — 2026-01-01 — a legacy entry\n'
                             '**Chose:** a\n**Over:** b\n**Because:** c\n'
                             '**Evidence:** `abcdef1`\n', encoding='utf-8')
            self.assertEqual(run_cli(root, 'decide', '0.1', *self.ARGS)[0], 0)
            self.assertIn('## M28 — ', log.read_text(encoding='utf-8'))

    def test_what_it_writes_passes_the_D12_gate(self):
        # The load-bearing round trip: writer and gate share one schema, so an
        # entry this mints can never be one the gate reports.
        with tree(feature_status='building', story_statuses=('todo',)) as root:
            self._scaffolded(root)
            self.assertEqual(run_cli(root, 'decide', '0.1', *self.ARGS)[0], 0)
            self.assertEqual(
                run_cli(root, 'decide', '0.1/alpha', *self.ARGS)[0], 0)
            (root / 'devkit.toml').write_text(
                '[pm]\nchecks = ["D12"]\n', encoding='utf-8')
            code, out = run_gate(root)
            self.assertEqual(code, 0, out)

    def test_it_stamps_todays_date(self):
        from datetime import datetime, timezone
        with tree(feature_status='building', story_statuses=('todo',)) as root:
            self._scaffolded(root)
            self.assertEqual(run_cli(root, 'decide', '0.1', *self.ARGS)[0], 0)
            today = datetime.now(timezone.utc).date().isoformat()
            self.assertIn(f'## D1 — {today} — ',
                          (root / self.MDIR / 'decisions.md').read_text(
                              encoding='utf-8'))

    def test_a_missing_over_is_refused(self):
        # The whole point of the flag. A decision with no rejected alternative
        # is a description, and requiring it at WRITE time is what stops the
        # entry existing at all — the author still remembers the alternative.
        with tree(feature_status='building', story_statuses=('todo',)) as root:
            self._scaffolded(root)
            log = root / self.MDIR / 'decisions.md'
            before = log.read_text(encoding='utf-8')
            args = [a for a in self.ARGS
                    if a not in ('--over',
                                 'leaving it on entity_behavior.gd, the lean root')]
            code, out = run_cli(root, 'decide', '0.1', *args)
            self.assertEqual(code, 2, out)
            self.assertIn('--over is required', out)
            self.assertIn('is a description', out)
            self.assertEqual(log.read_text(encoding='utf-8'), before)

    def test_prose_evidence_is_refused_and_nothing_is_written(self):
        with tree(feature_status='building', story_statuses=('todo',)) as root:
            self._scaffolded(root)
            log = root / self.MDIR / 'decisions.md'
            before = log.read_text(encoding='utf-8')
            args = list(self.ARGS)
            args[-1] = 'we discussed it and agreed'
            code, out = run_cli(root, 'decide', '0.1', *args)
            self.assertEqual(code, 1, out)
            self.assertIn('is prose, not a reference', out)
            self.assertEqual(log.read_text(encoding='utf-8'), before)

    def test_an_overlong_value_is_refused(self):
        with tree(feature_status='building', story_statuses=('todo',)) as root:
            self._scaffolded(root)
            args = list(self.ARGS)
            args[5] = 'x' * (model.DECISION_VALUE_MAX + 1)
            code, out = run_cli(root, 'decide', '0.1', *args)
            self.assertEqual(code, 1, out)
            self.assertIn('over the', out)

    def test_a_chose_too_long_to_be_a_title_asks_for_title_not_truncation(self):
        with tree(feature_status='building', story_statuses=('todo',)) as root:
            self._scaffolded(root)
            args = list(self.ARGS)
            args[1] = 'x' * (model.DECISION_TITLE_MAX + 1)
            code, out = run_cli(root, 'decide', '0.1', *args)
            self.assertEqual(code, 1, out)
            self.assertIn('--title', out)
            self.assertEqual(run_cli(root, 'decide', '0.1', *args,
                                     '--title', 'a short one')[0], 0)
            self.assertIn('## D1', (root / self.MDIR / 'decisions.md').read_text(
                encoding='utf-8'))

    def test_a_story_or_bug_has_no_decision_log(self):
        with tree(feature_status='building', story_statuses=('todo',)) as root:
            self._scaffolded(root)
            code, out = run_cli(root, 'decide', '0.1/alpha/s0', *self.ARGS)
            self.assertEqual(code, 1, out)
            self.assertIn('no decision log', out)

    def test_a_grain_with_no_log_points_at_the_scaffolder(self):
        with tree(feature_status='building', story_statuses=('todo',)) as root:
            code, out = run_cli(root, 'decide', '0.1', *self.ARGS)
            self.assertEqual(code, 1, out)
            self.assertIn('new milestone 0.1', out)

    def test_a_crlf_log_stays_crlf(self):
        # Rule 3: a write verb touches only what it was asked to touch, and a
        # line-ending conversion is the quietest way to touch a whole file.
        with tree(feature_status='building', story_statuses=('todo',)) as root:
            self._scaffolded(root)
            log = root / self.MDIR / 'decisions.md'
            model.write_raw(log, model.read_raw(log).replace('\n', '\r\n'))
            self.assertEqual(run_cli(root, 'decide', '0.1', *self.ARGS)[0], 0)
            raw = model.read_raw(log)
            self.assertNotIn('\r\r', raw)
            self.assertEqual(raw.count('\n'), raw.count('\r\n'))
            self.assertEqual(len(model.decision_entries_in(model.read_raw(log))), 1)


if __name__ == '__main__':
    unittest.main()
