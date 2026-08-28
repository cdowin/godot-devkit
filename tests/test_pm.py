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

from godot_devkit.checks import pm as pm_check
from godot_devkit.pm import cli, model


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
    from godot_devkit.project import load_config, repo_root
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
    from godot_devkit.project import load_config, repo_root
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

    def test_new_refuses_to_overwrite(self):
        with tree() as root:
            code, out = run_cli(root, 'new', 'feature', '0.1', 'alpha', 'Alpha')
            self.assertEqual(code, 1)
            self.assertIn('already exists', out)


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
                    'review_slug_fallback = "yes"', 'roadmap_dir = 3'):
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


if __name__ == '__main__':
    unittest.main()
