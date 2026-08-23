"""The Tier-1 gate: does it catch the rename it exists for, without crying wolf?"""
from __future__ import annotations

import unittest

from support import available_consumers, run_check, temp_repo

CLEAN = ['project.godot', 'systems/contract.gd', 'systems/contract.gd.uid', 'scenes/clean.tscn']
DRIFTED = CLEAN + ['scenes/drift.tscn']


class DeadPropertyDetection(unittest.TestCase):
    def test_flags_an_assignment_to_a_renamed_export(self) -> None:
        from godot_devkit.checks import props
        with temp_repo('props_repo', only=DRIFTED):
            code, out = run_check(props)
        self.assertEqual(code, 1, out)
        self.assertIn('drift.tscn', out)
        self.assertIn('floor_layer', out)
        # The rename also leaves the header's node_paths list stale.
        self.assertIn('node_paths', out)

    def test_passes_a_repo_with_no_drift(self) -> None:
        from godot_devkit.checks import props
        with temp_repo('props_repo', only=CLEAN):
            code, out = run_check(props)
        self.assertEqual(code, 0, out)
        self.assertIn('PASS', out)

    def test_does_not_flag_engine_builtins_or_export_groups(self) -> None:
        """`position` is a built-in; `flags`/`tint` come from a multi-line
        `@export_flags(...)` and from inside an `@export_group` — all legal."""
        from godot_devkit.checks import props
        with temp_repo('props_repo', only=CLEAN):
            _, out = run_check(props)
        for name in ('position', 'flags', 'tint', 'background_layer'):
            self.assertNotIn(f'.{name} —', out)

    def test_census_balances(self) -> None:
        from godot_devkit.checks import props
        with temp_repo('props_repo', only=CLEAN):
            _, out = run_check(props)
        self.assertIn('all accounted for', out)
        self.assertNotIn('BUG', out)

    def test_empty_scope_fails_loudly(self) -> None:
        """Rule: a gate scanning nothing must say so, never print PASS."""
        from godot_devkit.checks import props
        with temp_repo('props_repo', only=['project.godot']):
            code, out = run_check(props)
        self.assertEqual(code, 1)
        self.assertIn('scanned 0 files', out)


class NoFalsePositivesOnRealRepos(unittest.TestCase):
    """The consumers are the calibration set: every finding there must be real
    drift, so the count is pinned. If this changes, look at the diff before
    changing the number."""

    @unittest.skipUnless(available_consumers(), 'no consumer checkout available')
    def test_findings_are_bounded(self) -> None:
        import os

        from godot_devkit.checks import props
        for repo in available_consumers():
            previous = os.getcwd()
            os.chdir(repo)
            try:
                code, out = run_check(props)
            finally:
                os.chdir(previous)
            with self.subTest(repo=repo.name):
                self.assertIn('all accounted for', out)
                self.assertNotIn('BUG', out)
                dead = [ln for ln in out.splitlines() if ln.startswith('  DEAD')]
                # Real, hand-verified drift only — see the branch report.
                self.assertLessEqual(len(dead), 30, '\n'.join(dead))
                self.assertEqual(code, 1 if dead else 0)


if __name__ == '__main__':
    unittest.main()
