"""The Tier-1 gate: does it catch the rename it exists for, without crying wolf?"""
from __future__ import annotations

import os
import subprocess
import sys
import unittest

from support import REPO_ROOT, run_check, temp_repo

CLEAN = ['project.godot', 'systems/contract.gd', 'systems/contract.gd.uid', 'scenes/clean.tscn']
DRIFTED = CLEAN + ['scenes/drift.tscn']
# A node scripted with FixtureContract assigning `phantom_prop`, which no
# script or engine class declares — legal ONLY under an extra_properties
# carve-out that actually addresses that node's class.
VIRTUAL = CLEAN + ['scenes/virtual.tscn']
VIRTUAL_CHILD = CLEAN + ['systems/contract_child.gd', 'scenes/virtual_child.tscn']


class DeadPropertyDetection(unittest.TestCase):
    def test_flags_an_assignment_to_a_renamed_export(self) -> None:
        from godot_devkit.godot.checks import props
        with temp_repo('props_repo', only=DRIFTED):
            code, out = run_check(props)
        self.assertEqual(code, 1, out)
        self.assertIn('drift.tscn', out)
        self.assertIn('floor_layer', out)
        # The rename also leaves the header's node_paths list stale.
        self.assertIn('node_paths', out)

    def test_passes_a_repo_with_no_drift(self) -> None:
        from godot_devkit.godot.checks import props
        with temp_repo('props_repo', only=CLEAN):
            code, out = run_check(props)
        self.assertEqual(code, 0, out)
        self.assertIn('PASS', out)

    def test_does_not_flag_engine_builtins_or_export_groups(self) -> None:
        """`position` is a built-in; `flags`/`tint` come from a multi-line
        `@export_flags(...)` and from inside an `@export_group` — all legal."""
        from godot_devkit.godot.checks import props
        with temp_repo('props_repo', only=CLEAN):
            _, out = run_check(props)
        for name in ('position', 'flags', 'tint', 'background_layer'):
            self.assertNotIn(f'.{name} —', out)

    def test_census_balances(self) -> None:
        from godot_devkit.godot.checks import props
        with temp_repo('props_repo', only=CLEAN):
            _, out = run_check(props)
        self.assertIn('all accounted for', out)
        self.assertNotIn('BUG', out)

    def test_empty_scope_fails_loudly(self) -> None:
        """Rule: a gate scanning nothing must say so, never print PASS."""
        from godot_devkit.godot.checks import props
        with temp_repo('props_repo', only=['project.godot']):
            code, out = run_check(props)
        self.assertEqual(code, 1)
        self.assertIn('scanned 0 of 0 tracked', out)

    def test_a_tracked_but_deleted_file_is_censused_not_a_traceback(self) -> None:
        """In the git index but gone on disk (partial checkout, mid-rebase):
        an UNVERIFIED skip, never a FileNotFoundError — exit 1 with a stack
        trace is a hook reading a crash as findings — and never a silent
        drop from the census."""
        from godot_devkit.godot.checks import props
        with temp_repo('props_repo', only=DRIFTED) as root:
            (root / 'scenes/drift.tscn').unlink()
            code, out = run_check(props)
        self.assertEqual(code, 0, out)          # the drifted file WAS the gap
        self.assertIn('UNVERIFIED  scenes/drift.tscn — tracked in git but '
                      'not readable on disk; not scanned', out)
        self.assertIn('in 1 file(s)', out)      # the gap is not counted scanned

    def test_empty_scope_names_what_the_exclude_ate(self) -> None:
        """A census emptied by an exclude reads differently from an empty repo:
        "0 of 0" is a tree with no Godot resources, "0 of 2" is a misconfigured
        `exclude_prefixes`, and the fix is different for each."""
        from godot_devkit.godot.checks import props
        with temp_repo('props_repo', only=DRIFTED) as root:
            (root / 'devkit.toml').write_text(
                '[props]\nexclude_prefixes = ["scenes/"]\n', encoding='utf-8')
            code, out = run_check(props)
        self.assertEqual(code, 1)
        self.assertIn('scanned 0 of 2 tracked', out)


class ExtraPropertiesCarveOut(unittest.TestCase):
    """`[props] extra_properties = { Class = [...] }` — the key is a SCOPE.

    Pre-fix the class key was discarded (`for names in extra.values()`), so one
    class's `_get_property_list` carve-out legalized that name on every node in
    the tree — a false PASS on any typo'd assignment of it — and a bare-string
    value was iterated into single-character legal property names.
    """

    def _run(self, only: list[str], toml: str) -> tuple[int, str]:
        from godot_devkit.godot.checks import props
        with temp_repo('props_repo', only=only) as root:
            (root / 'devkit.toml').write_text(toml, encoding='utf-8')
            return run_check(props)

    def test_a_carve_out_never_leaks_to_another_class(self) -> None:
        code, out = self._run(
            VIRTUAL, '[props]\nextra_properties = { TileMapLayer = ["phantom_prop"] }\n')
        self.assertEqual(code, 1, out)
        self.assertIn('phantom_prop', out)

    def test_a_carve_out_applies_to_the_named_class(self) -> None:
        code, out = self._run(
            VIRTUAL, '[props]\nextra_properties = { FixtureContract = ["phantom_prop"] }\n')
        self.assertEqual(code, 0, out)

    def test_a_carve_out_on_a_base_class_covers_subclasses(self) -> None:
        code, out = self._run(
            VIRTUAL_CHILD,
            '[props]\nextra_properties = { FixtureContract = ["phantom_prop"] }\n')
        self.assertEqual(code, 0, out)

    def test_a_carve_out_may_name_the_engine_type(self) -> None:
        code, out = self._run(
            VIRTUAL, '[props]\nextra_properties = { Node2D = ["phantom_prop"] }\n')
        self.assertEqual(code, 0, out)

    def test_a_bare_string_value_means_the_whole_name(self) -> None:
        """Pre-fix `allowed.update("phantom_prop")` legalized eleven
        single-character property names and NOT the name itself."""
        code, out = self._run(
            VIRTUAL, '[props]\nextra_properties = { FixtureContract = "phantom_prop" }\n')
        self.assertEqual(code, 0, out)

    def test_a_non_string_value_is_exit_2_not_a_traceback(self) -> None:
        with temp_repo('props_repo', only=VIRTUAL) as root:
            (root / 'devkit.toml').write_text(
                '[props]\nextra_properties = { FixtureContract = 5 }\n',
                encoding='utf-8')
            proc = subprocess.run(
                [sys.executable, '-m', 'godot_devkit.cli', 'check', 'props'],
                cwd=root, capture_output=True, text=True,
                env={**os.environ, 'PYTHONPATH': str(REPO_ROOT / 'src')})
        self.assertEqual(proc.returncode, 2, proc.stderr)
        self.assertIn('extra_properties.FixtureContract', proc.stderr)
        self.assertNotIn('Traceback', proc.stderr)


# The calibration set — every `check props` finding on a live consumer must be
# real drift, the count pinned — is `make smoke`'s `check props findings` row.

if __name__ == '__main__':
    unittest.main()
