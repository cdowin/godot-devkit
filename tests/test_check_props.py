"""The Tier-1 gate: does it catch the rename it exists for, without crying wolf?"""
from __future__ import annotations

import unittest

from support import run_check, temp_repo

from godot_devkit.core.config import ConfigError
from godot_devkit.godot.checks import props

CLEAN = ['project.godot', 'systems/contract.gd', 'systems/contract.gd.uid', 'scenes/clean.tscn']
DRIFTED = CLEAN + ['scenes/drift.tscn']
# A node scripted with FixtureContract assigning `phantom_prop`, which no
# script or engine class declares — legal ONLY under an extra_properties
# carve-out that actually addresses that node's class.
VIRTUAL = CLEAN + ['scenes/virtual.tscn']
VIRTUAL_CHILD = CLEAN + ['systems/contract_child.gd', 'scenes/virtual_child.tscn']


def _run(only: list[str], toml: str) -> tuple[int, str]:
    with temp_repo('props_repo', only=only) as root:
        (root / 'devkit.toml').write_text(toml, encoding='utf-8')
        return run_check(props)


class DeadPropertyDetection(unittest.TestCase):
    def test_flags_an_assignment_to_a_renamed_export(self) -> None:
        with temp_repo('props_repo', only=DRIFTED):
            code, out = run_check(props)
        self.assertEqual(code, 1, out)
        self.assertIn('drift.tscn', out)
        self.assertIn('floor_layer', out)
        # The rename also leaves the header's node_paths list stale.
        self.assertIn('node_paths', out)

    def test_passes_a_repo_with_no_drift_and_the_census_balances(self) -> None:
        # `position` is a built-in; `flags`/`tint` come from a multi-line
        # `@export_flags(...)` and from inside an `@export_group` — all legal.
        with temp_repo('props_repo', only=CLEAN):
            code, out = run_check(props)
        self.assertEqual(code, 0, out)
        self.assertIn('PASS', out)
        for name in ('position', 'flags', 'tint', 'background_layer'):
            self.assertNotIn(f'.{name} —', out)
        self.assertIn('all accounted for', out)
        self.assertNotIn('BUG', out)

    def test_a_tracked_but_deleted_file_is_censused_not_a_traceback(self) -> None:
        # In the git index but gone on disk (partial checkout, mid-rebase):
        # an UNVERIFIED skip, never a FileNotFoundError — exit 1 with a stack
        # trace is a hook reading a crash as findings — and never a silent
        # drop from the census.
        with temp_repo('props_repo', only=DRIFTED) as root:
            (root / 'scenes/drift.tscn').unlink()
            code, out = run_check(props)
        self.assertEqual(code, 0, out)          # the drifted file WAS the gap
        self.assertIn('UNVERIFIED  scenes/drift.tscn — tracked in git but '
                      'not readable on disk; not scanned', out)
        self.assertIn('in 1 file(s)', out)      # the gap is not counted scanned

    def test_empty_scope_names_what_the_exclude_ate(self) -> None:
        # A census emptied by an exclude reads differently from an empty repo:
        # "0 of 0" is a tree with no Godot resources, "0 of 2" is a
        # misconfigured `exclude_prefixes`, and the fix is different for each.
        code, out = _run(DRIFTED, '[props]\nexclude_prefixes = ["scenes/"]\n')
        self.assertEqual(code, 1)
        self.assertIn('scanned 0 of 2 tracked', out)


class ExtraPropertiesCarveOut(unittest.TestCase):
    """`[props] extra_properties = { Class = [...] }` — the key is a SCOPE.

    Pre-fix the class key was discarded (`for names in extra.values()`), so one
    class's `_get_property_list` carve-out legalized that name on every node in
    the tree — a false PASS on any typo'd assignment of it — and a bare-string
    value was iterated into single-character legal property names.
    """

    def test_a_carve_out_never_leaks_to_another_class(self) -> None:
        code, out = _run(
            VIRTUAL, '[props]\nextra_properties = { TileMapLayer = ["phantom_prop"] }\n')
        self.assertEqual(code, 1, out)
        self.assertIn('phantom_prop', out)

    def test_a_carve_out_applies_to_the_named_class_or_engine_type(self) -> None:
        # The key may name the script's class or the node's engine type; and a
        # bare-string value is the whole name (pre-fix `allowed.update(
        # "phantom_prop")` legalized eleven single-character property names
        # and NOT the name itself).
        for value in ('{ FixtureContract = ["phantom_prop"] }',
                      '{ Node2D = ["phantom_prop"] }',
                      '{ FixtureContract = "phantom_prop" }'):
            with self.subTest(value):
                code, out = _run(VIRTUAL, f'[props]\nextra_properties = {value}\n')
                self.assertEqual(code, 0, out)

    def test_a_carve_out_on_a_base_class_covers_subclasses(self) -> None:
        code, out = _run(
            VIRTUAL_CHILD,
            '[props]\nextra_properties = { FixtureContract = ["phantom_prop"] }\n')
        self.assertEqual(code, 0, out)

    def test_a_non_string_value_is_refused_naming_the_key(self) -> None:
        # `cli.py` turns the ConfigError into exit 2 without a traceback
        # (proven once, in test_read_verbs); the gate's job is to raise it.
        with self.assertRaises(ConfigError) as caught:
            _run(VIRTUAL, '[props]\nextra_properties = { FixtureContract = 5 }\n')
        self.assertIn('extra_properties.FixtureContract', str(caught.exception))


# Calibration against real-world trees — every finding real drift, the count
# pinned — was a live-consumer sweep and is not one any more (CLAUDE.md rule
# 8). Its replacement is a vendored fixture: see the false-positive census
# above, and 0.24.0/bugs/the-smoke-took-fixture-scale-with-it for what a
# committed calibration set would have to carry.
