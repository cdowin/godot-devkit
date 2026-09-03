"""`check pm` and `pm validate` — drift rules, flow checks, config refusals,
and the censuses that keep a zero-file scan loud.

Split from test_pm.py by concern; the shared harness is tests/support/pm.py.
The CLI and the gate share ONE definition of "reviewed" and of each drift
rule — the round trips here are what stop the two diverging.
"""
from __future__ import annotations

import contextlib
import io
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from support.pm import (
    DAMAGE_FORMS,
    STORY_REL,
    bug,
    cfg_for,
    damage,
    run_cli,
    run_gate,
    tree,
    write,
)

from godot_devkit.repo.checks import pm as pm_check
from godot_devkit.repo.pm import cli, model

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


class MainlineGuard(unittest.TestCase):
    """D10 — a `building` milestone must not be empty or on the mainline.

    Opt-in, like D8/D9 (decision D3): a repo may run D9 alone (some
    branch declared, wherever it points) or add D10 for the stricter
    guarantee that it is not the trunk itself.
    """

    def _building(self, root: Path, branch: str = '', version: str = '0.1'):
        model.set_field(root / 'pm/roadmap/0.1-demo/milestone.md', 'status', 'building')
        if branch:
            model.set_field(root / 'pm/roadmap/0.1-demo/milestone.md', 'branch', branch)
        if version:
            (root / 'project.godot').write_text(
                f'[application]\nconfig/version="{version}"\n', encoding='utf-8')

    def test_off_by_default(self):
        # Same shape as D8/D9's off-by-default case, but proved on the exact
        # input D10 exists to catch: a building milestone stamped onto the
        # mainline itself. Silent unless named.
        with tree(story_statuses=('todo',)) as root:
            self._building(root, branch='main')
            code, out = run_gate(root)
            self.assertEqual(code, 0, out)

    def test_fires_on_a_building_milestone_stamped_onto_the_mainline(self):
        with tree(story_statuses=('todo',)) as root:
            self._building(root, branch='main')
            (root / 'devkit.toml').write_text(
                '[pm]\nchecks = ["D10"]\n', encoding='utf-8')
            code, out = run_gate(root)
            self.assertEqual(code, 1, out)
            self.assertIn('the mainline itself', out)

    def test_fires_on_an_empty_branch_even_without_d9_named(self):
        with tree(story_statuses=('todo',)) as root:
            self._building(root)  # no branch: at all
            (root / 'devkit.toml').write_text(
                '[pm]\nchecks = ["D10"]\n', encoding='utf-8')
            code, out = run_gate(root)
            self.assertEqual(code, 1, out)
            self.assertIn('needs a branch off the mainline', out)

    def test_a_real_milestone_branch_passes(self):
        with tree(story_statuses=('todo',)) as root:
            self._building(root, branch='milestone/0.1-demo')
            (root / 'devkit.toml').write_text(
                '[pm]\nchecks = ["D10"]\n', encoding='utf-8')
            code, out = run_gate(root)
            self.assertEqual(code, 0, out)

    def test_mainline_strips_a_leading_origin_prefix(self):
        # `[repo_hygiene] mainline` is a git ref and keeps `origin/`; D10
        # compares against an authored `branch:` string, which never carries
        # a remote qualifier, so the stock `origin/main` must read as `main`
        # — proved here with a NON-stock value so the assertion cannot pass
        # by accident on the untouched default.
        with tree(story_statuses=('todo',)) as root:
            self._building(root, branch='trunk')
            (root / 'devkit.toml').write_text(
                '[pm]\nchecks = ["D10"]\n'
                '[repo_hygiene]\nmainline = "origin/trunk"\n', encoding='utf-8')
            code, out = run_gate(root)
            self.assertEqual(code, 1, out)
            self.assertIn("'trunk'", out)

    def test_d9_alone_does_not_refuse_the_mainline(self):
        # The opt-in split, from the other side: D9 only requires SOME stamp.
        with tree(story_statuses=('todo',)) as root:
            self._building(root, branch='main')
            (root / 'devkit.toml').write_text(
                '[pm]\nchecks = ["D9"]\n', encoding='utf-8')
            code, out = run_gate(root)
            self.assertEqual(code, 0, out)

    def test_d10_is_a_known_rule_not_a_config_error(self):
        with tree(story_statuses=('todo',)) as root:
            self._building(root, branch='milestone/0.1-demo')
            (root / 'devkit.toml').write_text(
                '[pm]\nchecks = ["D10"]\n', encoding='utf-8')
            code, out = run_gate(root)
            self.assertEqual(code, 0, out)
            self.assertNotIn('unknown rule', out)
        self.assertIn('D10', model.KNOWN_CHECKS)
        self.assertIn('D10', model.FLOW_CHECKS)


class RetiredConfigIsRefusedByName(unittest.TestCase):
    """A key the tracker stopped reading is REFUSED by name, never ignored.

    The mechanism under test is the `RETIRED_KEYS` / `RETIRED_SECTIONS` ledger
    in model.py — the executable tombstone that keeps a consumer arriving from
    an older pin from shipping config that silently does nothing (a config key
    that does nothing is worse than one that errors: the author believes it
    took effect). One key and one section stand in for the roster; the ledger
    itself is the enumeration, so a per-key test table here would be a second
    copy of it.

    `place_branch_on_building` is the standing example on purpose: the verb
    behind it ran `git checkout` in the trunk worktree — a PM tracker mutating
    your VCS checkout on the way past a status flip — and the last test here
    pins that no such reach into the VCS ever comes back.
    """

    ON = '[pm]\nplace_branch_on_building = true\n'

    @staticmethod
    def _gate(root: Path) -> tuple[int, str]:
        """`check pm` with BOTH streams captured.

        The shared `run_gate` takes stdout only, and a config complaint goes to
        stderr — so a test built on it would assert exit 2 against an empty
        string and pass on any exit-2 whatsoever.
        """
        from godot_devkit.core.project import load_config, repo_root
        repo_root.cache_clear()
        load_config.cache_clear()
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            code = pm_check.run()
        return code, buf.getvalue()

    def test_a_retired_key_stops_the_gate_and_the_read_verbs_keep_working(self):
        # Reported where a stale rule id is — on the GATE, so a project can
        # still read its own tree while deciding what to do about the dead key.
        with tree(story_statuses=('todo',)) as root:
            (root / 'devkit.toml').write_text(self.ON, encoding='utf-8')
            code, out = self._gate(root)
            self.assertEqual(code, 2, out)
            self.assertIn('place_branch_on_building was retired', out)
            self.assertEqual(run_cli(root, 'status')[0], 0)
            self.assertEqual(run_cli(root, 'list')[0], 0)
            self.assertEqual(run_cli(root, 'vocabulary', '--json')[0], 0)

    def test_a_retired_section_is_named_the_same_way(self):
        # `[agents]` was a whole config surface, and `config_section` cannot
        # tell an absent table from an empty one — both spellings must land.
        for body in ('[agents]\nscope = [".claude/agents/*.md"]\n', '[agents]\n'):
            with self.subTest(body=body):
                with tree(story_statuses=('todo',)) as root:
                    (root / 'devkit.toml').write_text(body, encoding='utf-8')
                    code, out = self._gate(root)
                    self.assertEqual(code, 2, out)
                    self.assertIn('[agents] was retired', out)

    def test_pm_validate_names_it_too(self):
        with tree(story_statuses=('todo',)) as root:
            (root / 'devkit.toml').write_text(self.ON, encoding='utf-8')
            code, out = run_cli(root, 'validate')
            self.assertEqual(code, 2, out)
            self.assertIn('place_branch_on_building was retired', out)

    def test_no_ledgered_key_is_still_read_by_load(self):
        # A ledger entry for a key still being read would be a lie in the
        # other direction — enumerated from the ledger itself, so a key added
        # there is covered without a test edit.
        source = Path(model.__file__).read_text(encoding='utf-8')
        for key in model.RETIRED_KEYS:
            with self.subTest(key=key):
                self.assertNotIn(f"'pm', '{key}'", source)

    def test_the_cli_holds_no_git_checkout_at_all(self):
        source = Path(cli.__file__).read_text(encoding='utf-8')
        for spelling in ('checkout', 'worktree', 'subprocess'):
            self.assertNotIn(spelling, source,
                             f'{spelling} is back in the pm CLI')


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


class CausedBy(unittest.TestCase):
    """V4 over a bug's `caused_by:` — one definition, BOTH readers.

    A ref is a ref: a `caused_by:` naming no feature reports in exactly the
    shape a dangling `depends_on` does, at exactly its exit code, counted in
    the same census, and it does so out of `pm validate` AND out of `check pm`.
    A ref that names nothing is an integrity FACT, which is the class this
    package keeps as a gate; whether a given cause counts as an escape is a
    judgement, and that belongs to the report.
    """

    def _validate(self, root: Path, **kw):
        from godot_devkit.repo.pm import validate
        return validate.run(model.PmConfig(root=root), **kw)

    def test_a_resolving_cause_is_clean_and_counted(self):
        with tree(story_statuses=('todo',)) as root:
            bug(root, 'seed-is-zero', caused_by='0.1/alpha')
            findings, census = self._validate(root)
            self.assertEqual(findings, [])
            self.assertEqual(census['refs'], 1)
            self.assertEqual(census['unverifiable'], 0)

    def test_a_dangling_cause_reports_like_a_dangling_depends_on(self):
        # The SAME line, word for word, but for the key and the path — one
        # finding shape, so a consumer grepping `resolves to nothing` sees
        # both without learning a second spelling.
        with tree(story_statuses=('todo',)) as root:
            bug(root, 'seed-is-zero', caused_by='0.1/no-such-feature')
            findings, census = self._validate(root)
            self.assertEqual(findings, [
                "pm/roadmap/0.1-demo/bugs/seed-is-zero.md: caused_by "
                "'0.1/no-such-feature' resolves to nothing "
                "(its milestone IS in the tree)"])
            self.assertEqual(census['refs'], 1)

            ff = root / 'pm/roadmap/0.1-demo/features/alpha/feature.md'
            model.set_field(ff, 'depends_on', '["0.1/no-such-feature"]')
            dep = [f for f in self._validate(root)[0] if 'depends_on' in f]
            self.assertEqual(len(dep), 1)
            self.assertEqual(dep[0].split(': ', 1)[1].replace('depends_on', 'X'),
                             findings[0].split(': ', 1)[1].replace('caused_by', 'X'))

    def test_the_verb_exits_1_and_prints_the_finding(self):
        with tree(story_statuses=('todo',)) as root:
            bug(root, 'seed-is-zero', caused_by='0.1/no-such-feature')
            code, out = run_cli(root, 'validate')
            self.assertEqual(code, 1, out)
            self.assertIn('INVALID', out)
            self.assertIn("caused_by '0.1/no-such-feature' resolves to nothing",
                          out)

    def test_the_census_line_counts_it(self):
        with tree(story_statuses=('todo',)) as root:
            self.assertIn('3 grain(s), 0 ref(s)', run_cli(root, 'validate')[1])
            bug(root, 'seed-is-zero', caused_by='0.1/alpha')
            code, out = run_cli(root, 'validate')
            self.assertEqual(code, 0, out)
            # Bugs are walked for their ONE ref, not censused as grains: V1-V3
            # are still stated over milestones, features and stories.
            self.assertIn('3 grain(s), 1 ref(s)', out)

    def test_an_empty_or_absent_cause_is_not_a_ref_at_all(self):
        for value in ('', 'null', '~'):
            with self.subTest(value=value), tree(story_statuses=('todo',)) as root:
                bug(root, 'seed-is-zero', caused_by=value)
                findings, census = self._validate(root)
                self.assertEqual(findings, [])
                self.assertEqual(census['refs'], 0)
        with tree(story_statuses=('todo',)) as root:
            path = bug(root, 'seed-is-zero')
            self.assertEqual(model.field_of(path, 'caused_by'), '')
            self.assertEqual(self._validate(root), ([], {
                'grains': 3, 'refs': 0, 'unverifiable': 0}))

    def test_a_bug_is_walked_for_its_ref_and_NOT_counted_as_a_grain(self):
        # The walk reaches a bug for `caused_by:` alone. V1/V2/V3 are still
        # stated over milestones, features and stories, and `check pm` stays
        # the one home of the bug census (`N bug(s)`).
        with tree(story_statuses=('todo',)) as root:
            before = self._validate(root)[1]['grains']
            for i in range(3):
                bug(root, f'b{i}', caused_by='0.1/alpha')
            _, census = self._validate(root)
            self.assertEqual(census['grains'], before)
            self.assertEqual(census['refs'], 3)
            self.assertIn(f'{before} grain(s), 3 ref(s)',
                          run_cli(root, 'validate')[1])
            self.assertIn('3 bug(s)', run_gate(root)[1])

    def test_a_cause_naming_a_MILESTONE_or_a_STORY_resolves_to_nothing(self):
        # `caused_by:` records the CHANGE that produced the bug. A milestone is
        # a container of changes, not one, and a story is a slice of one — if
        # either passed here, the escape count would attribute a bug to
        # something that cannot own it.
        for value in ('0.1', '0.1/alpha/s0'):
            with self.subTest(value=value), tree(story_statuses=('todo',)) as root:
                bug(root, 'seed-is-zero', caused_by=value)
                findings, census = self._validate(root)
                self.assertTrue(any('resolves to nothing' in f for f in findings),
                                findings)
                self.assertEqual(census['refs'], 1)

    def test_a_cause_into_a_pruned_milestone_is_unverifiable_not_a_finding(self):
        # Git history is the archive — the same discipline V4 already applies
        # to a `depends_on` naming a milestone that has been retired.
        with tree(story_statuses=('todo',)) as root:
            bug(root, 'seed-is-zero', caused_by='0.0.9/long-gone')
            findings, census = self._validate(root)
            self.assertEqual(findings, [])
            self.assertEqual(census['unverifiable'], 1)
            self.assertIn('UNVERIFIABLE', run_cli(root, 'validate')[1])

    def test_a_LIST_shaped_cause_is_a_finding_not_a_silent_unverifiable(self):
        # `["0.1/alpha"]` reaches the resolver as a milestone id no glob
        # matches, so the generic path would census it UNVERIFIABLE — a
        # hand-written list quietly reported as "its milestone was pruned".
        for raw in ('["0.1/alpha"]', '0.1/alpha, 0.1/beta', '0.1/a 0.1/b',
                    '{a: b}'):
            with self.subTest(raw=raw), tree(story_statuses=('todo',)) as root:
                path = bug(root, 'seed-is-zero')
                self.assertTrue(model.set_field(path, 'caused_by', raw))
                findings, census = self._validate(root)
                self.assertTrue(findings, f'{raw!r} vanished silently')
                self.assertEqual(census['unverifiable'], 0)

    def test_an_over_long_cause_is_a_finding_not_a_traceback(self):
        # `Path.is_dir()` RAISES on a component past NAME_MAX up to 3.13 and
        # answers False from 3.14 on, so the same hand-typed id would fail
        # `pm validate` with a stack trace on one interpreter and a finding on
        # another. A tool whose behaviour depends on that is not a tool.
        with tree(story_statuses=('todo',)) as root:
            bug(root, 'seed-is-zero', caused_by='0.1/' + 'a' * 300)
            findings, census = self._validate(root)
            self.assertTrue(any('resolves to nothing' in f for f in findings),
                            findings)
            self.assertEqual(census['refs'], 1)
            code, out = run_cli(root, 'validate')
            self.assertEqual(code, 1, out)
            self.assertNotIn('Traceback', out)

    def test_a_QUOTED_id_is_the_same_id(self):
        # `milestone: "0.1"` is the convention this tree already writes, so a
        # hand-quoted cause is an id, not a shape to complain about.
        with tree(story_statuses=('todo',)) as root:
            path = bug(root, 'seed-is-zero')
            self.assertTrue(model.set_field(path, 'caused_by', '"0.1/alpha"'))
            findings, census = self._validate(root)
            self.assertEqual(findings, [])
            self.assertEqual(census['refs'], 1)

    def test_the_gate_reports_it_too_and_its_ref_census_moves(self):
        # One definition, two readers — the property the whole test_pm_*
        # quartet exists to hold. A dangling `depends_on` fails `check pm`, so
        # a dangling `caused_by:` fails it in the same line and at the same
        # exit code, and the ref it added is in the gate's census.
        with tree(story_statuses=('todo',)) as root:
            code, out = run_gate(root)
            self.assertEqual(code, 0, out)
            self.assertIn('0 bug(s), 0 ref(s)', out)

            bug(root, 'seed-is-zero', caused_by='0.1/no-such-feature')
            code, out = run_gate(root)
            self.assertEqual(code, 1, out)
            self.assertIn("  DRIFT  pm/roadmap/0.1-demo/bugs/seed-is-zero.md: "
                          "caused_by '0.1/no-such-feature' resolves to nothing "
                          "(its milestone IS in the tree)", out)
            self.assertIn('1 bug(s), 1 ref(s)', out)
            self.assertIn('integrity violation(s)', out)
            # And `pm validate`, on the same tree, says the same thing.
            self.assertEqual(run_cli(root, 'validate')[0], 1)

    def test_a_RESOLVING_cause_leaves_the_gate_green_and_still_counts(self):
        # The other half of the census claim: the ref is counted whether or
        # not it is a finding, so `1 ref(s)` is not a synonym for `1 problem`.
        with tree(story_statuses=('todo',)) as root:
            bug(root, 'seed-is-zero', caused_by='0.1/alpha')
            code, out = run_gate(root)
            self.assertEqual(code, 0, out)
            self.assertIn('1 bug(s), 1 ref(s)', out)

    def test_the_two_readers_agree_with_no_switch_between_them(self):
        # There is no parameter that runs one reader narrower than the other —
        # a second answer to one question is how the two ever diverge.
        import inspect

        from godot_devkit.repo.pm import validate
        self.assertEqual(list(inspect.signature(validate.run).parameters),
                         ['cfg', 'enabled'])
        with tree(story_statuses=('todo',)) as root:
            bug(root, 'seed-is-zero', caused_by='0.1/no-such-feature')
            findings, _ = validate.run(model.PmConfig(root=root))
            self.assertEqual(len(findings), 1)
            gate_out = run_gate(root)[1]
            self.assertIn(findings[0], gate_out)


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


    def _d8_tree_with_version(self, version: str, released: str = '0.0.9'):
        # 0.1 is building; `released` is the DONE milestone retire's lag-by-one
        # keeps in the tree — the only id a hotfix may extend.
        ctx = tree(milestone_status='building', story_statuses=('todo',))
        root = ctx.__enter__()
        model.set_field(root / 'pm/roadmap/0.1-demo/milestone.md', 'branch', 'staging')
        write(root / f'pm/roadmap/{released}-old/milestone.md',
              {'id': f'"{released}"', 'name': 'Old', 'status': 'done'})
        (root / 'project.godot').write_text(
            f'[application]\nconfig/version="{version}"\n', encoding='utf-8')
        (root / 'devkit.toml').write_text('[pm]\nchecks = ["D8"]\n', encoding='utf-8')
        return ctx, root

    def test_d8_admits_a_hotfix_of_the_released_milestone(self):
        # 0.0.9 shipped; 0.0.9.1 is a hotfix cut from the mainline that carries
        # no milestone of its own — the release branch must pass the gate.
        ctx, root = self._d8_tree_with_version('0.0.9.1')
        try:
            code, out = run_gate(root)
            self.assertNotIn('(D8)', out)
            self.assertEqual(code, 0, out)
        finally:
            ctx.__exit__(None, None, None)

    def test_d8_refuses_a_hotfix_of_anything_but_a_released_milestone(self):
        # 0.1.1 extends the BUILDING id — not a hotfix of anything shipped.
        for bad in ('0.1.1', '0.9.1', '0.0.9.1a', '0.0.9.01', '0.0.9.', '0.10', '0.0.9.\u0663'):
            with self.subTest(version=bad):
                ctx, root = self._d8_tree_with_version(bad)
                try:
                    code, out = run_gate(root)
                    self.assertEqual(code, 1, out)
                    self.assertIn('(D8)', out)
                finally:
                    ctx.__exit__(None, None, None)


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
