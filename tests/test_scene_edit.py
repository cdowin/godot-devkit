"""Tier 2 — the surgical write verbs.

Three properties are load-bearing and each has its own case: the verbs touch
ONLY what they were asked to (measured as changed lines), they are idempotent,
and they REFUSE rather than write a plausible-looking wrong answer.
"""
from __future__ import annotations

import contextlib
import io
import shutil
import tempfile
import unittest
from pathlib import Path

from support import FIXTURES

from godot_devkit.godot.write import scene_edit
from godot_devkit.godot.format.tscn_document import TscnDocument

SINK = FIXTURES / 'kitchen_sink.tscn'


class VerbCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.scene = self.tmp / 'scene.tscn'
        shutil.copy2(SINK, self.scene)
        self.addCleanup(shutil.rmtree, self.tmp)

    def run_verb(self, *argv: str) -> int:
        """Run a verb, keeping its (deliberately terse) output off the test log."""
        self.output = io.StringIO()
        with contextlib.redirect_stdout(self.output):
            return scene_edit.main([*argv])

    def text(self) -> str:
        return self.scene.read_text(encoding='utf-8')

    def changed_lines(self, before: str) -> list[str]:
        after = self.text().splitlines()
        return [line for line in after if line not in before.splitlines()]


class RenameRewritesReferences(VerbCase):
    """The verb's whole reason to exist: a blanket sed rewrote
    NodePath("Sandbox/TileRoomContract") while renaming prose and broke a
    scenario. Rename resolves paths; it does not text-match."""

    def test_rewrites_relative_nodepaths_at_every_depth(self) -> None:
        self.run_verb('rename', str(self.scene), 'WallLayer', 'Walls')
        text = self.text()
        self.assertIn('wall_layer = NodePath("../Walls")', text)
        self.assertIn('target = NodePath("../../Walls")', text)
        self.assertNotIn('WallLayer', text)

    def test_rewrites_parent_attributes_of_descendants(self) -> None:
        self.run_verb('rename', str(self.scene), 'Nested', 'Container')
        self.assertIn('[node name="Deep" type="Marker2D" parent="Container"]', self.text())

    def test_leaves_prose_and_property_names_alone(self) -> None:
        """`wall_layer` is an EXPORT name and `node_paths=` lists export names —
        neither is a path, and neither may move when the node does."""
        self.run_verb('rename', str(self.scene), 'WallLayer', 'Walls')
        text = self.text()
        self.assertIn('node_paths=PackedStringArray("wall_layer")', text)
        self.assertIn('wall_layer = NodePath', text)
        self.assertIn('; The contract wires the layers by NodePath', text)

    def test_rewrites_animation_track_paths(self) -> None:
        """An Animation lives in a sub_resource with no path of its own; its
        tracks resolve against the AnimationPlayer's `root_node`. A rename that
        misses them breaks the animation silently."""
        self.run_verb('rename', str(self.scene), 'WallLayer', 'Walls')
        self.assertIn('tracks/0/path = NodePath("Walls:modulate")', self.text())

    def test_touches_only_the_lines_that_reference_the_node(self) -> None:
        before = self.text()
        self.run_verb('rename', str(self.scene), 'WallLayer', 'Walls')
        self.assertEqual(len(self.changed_lines(before)), 4)

    def test_is_idempotent(self) -> None:
        self.run_verb('rename', str(self.scene), 'WallLayer', 'Walls')
        once = self.text()
        self.assertEqual(self.run_verb('rename', str(self.scene), 'WallLayer', 'Walls'),
                         scene_edit.EXIT_OK)
        self.assertEqual(self.text(), once)

    def test_refuses_a_name_collision(self) -> None:
        code = self.run_verb('rename', str(self.scene), 'Nested', 'WallLayer')
        self.assertEqual(code, scene_edit.EXIT_REFUSED)
        self.assertNotIn('name="WallLayer" type="Node2D"', self.text())


class SetProperty(VerbCase):
    def test_replaces_a_value_in_place(self) -> None:
        before = self.text()
        self.run_verb('set', str(self.scene), 'Sandbox', 'tint', 'Color(1, 0, 0, 1)')
        self.assertIn('tint = Color(1, 0, 0, 1)', self.text())
        self.assertEqual(len(self.changed_lines(before)), 1)

    def test_appends_a_new_property_to_the_right_node(self) -> None:
        self.run_verb('set', str(self.scene), 'Nested/Deep', 'visible', 'false')
        text = self.text()
        self.assertIn('[node name="Deep" type="Marker2D" parent="Nested"]\n'
                      'target = NodePath("../../WallLayer")\nvisible = false\n', text)

    def test_preserves_an_inline_comment(self) -> None:
        self.run_verb('set', str(self.scene), 'TileRoomContract', 'layers', '{ "a": 9 }')
        self.assertIn('layers = { "a": 9 } ; trailing comment on a multi-line value',
                      self.text())

    def test_is_idempotent(self) -> None:
        self.run_verb('set', str(self.scene), 'Sandbox', 'tint', 'Color(1, 0, 0, 1)')
        once = self.text()
        self.run_verb('set', str(self.scene), 'Sandbox', 'tint', 'Color(1, 0, 0, 1)')
        self.assertEqual(self.text(), once)

    def test_refuses_an_unknown_node(self) -> None:
        self.assertEqual(self.run_verb('set', str(self.scene), 'Nope', 'x', '1'),
                         scene_edit.EXIT_REFUSED)


class AddRemoveReparent(VerbCase):
    def test_add_places_the_node_after_the_parent_subtree(self) -> None:
        self.run_verb('add', str(self.scene), 'Nested', 'Extra', 'Sprite2D')
        text = self.text()
        self.assertIn('[node name="Extra" type="Sprite2D" parent="Nested"]', text)
        self.assertLess(text.index('name="Deep"'), text.index('name="Extra"'))

    def test_add_refuses_to_shadow_a_different_type(self) -> None:
        self.run_verb('add', str(self.scene), 'Nested', 'Extra', 'Sprite2D')
        self.assertEqual(self.run_verb('add', str(self.scene), 'Nested', 'Extra', 'Node2D'),
                         scene_edit.EXIT_REFUSED)

    def test_rm_takes_descendants_connections_and_editable_markers(self) -> None:
        self.run_verb('rm', str(self.scene), 'Panel')
        text = self.text()
        for gone in ('name="Panel"', 'name="Inner"', '[connection', '[editable'):
            self.assertNotIn(gone, text)

    def test_rm_prunes_the_now_unreferenced_ext_resource(self) -> None:
        self.run_verb('rm', str(self.scene), 'Panel')
        text = self.text()
        self.assertNotIn('panel.tscn', text)
        self.assertIn('load_steps=7', text)          # 8 -> 7, one resource fewer

    def test_reparent_moves_the_subtree_and_fixes_its_nodepaths(self) -> None:
        self.run_verb('reparent', str(self.scene), 'Nested/Deep', '.')
        text = self.text()
        self.assertIn('[node name="Deep" type="Marker2D" parent="."]', text)
        # One `..` fewer now that the node sits one level higher.
        self.assertIn('target = NodePath("../WallLayer")', text)

    def test_reparent_refuses_to_nest_a_node_inside_itself(self) -> None:
        self.assertEqual(self.run_verb('reparent', str(self.scene), 'Nested', 'Nested/Deep'),
                         scene_edit.EXIT_REFUSED)

    def test_every_verb_leaves_a_reparsable_scene(self) -> None:
        self.run_verb('add', str(self.scene), 'Nested', 'Extra', 'Sprite2D')
        self.run_verb('reparent', str(self.scene), 'Nested/Deep', 'Nested/Extra')
        self.run_verb('rename', str(self.scene), 'Nested/Extra', 'Holder')
        self.run_verb('rm', str(self.scene), 'Panel')
        text = self.text()
        doc = TscnDocument(text, self.scene)
        self.assertEqual(doc.text, text)             # still round-trips
        self.assertIn('[node name="Deep" type="Marker2D" parent="Nested/Holder"]', text)
        self.assertIn('target = NodePath("../../../WallLayer")', text)


class ScriptRefsAreBornCanonical(VerbCase):
    """`check tres` requires uid-in-refs. A verb that mints a path-only ref is
    handing the next gate a failure, so `add --script` resolves the uid."""

    def test_add_with_script_writes_a_uid_in_ref(self) -> None:
        from support import temp_repo

        with temp_repo('canon_repo') as root:
            scene = root / 'scenes/panel.tscn'
            code = scene_edit.main(['add', str(scene), '.', 'Logic', 'Node2D',
                                    '--script', 'res://systems/logic.gd'])
            text = scene.read_text(encoding='utf-8')
        self.assertEqual(code, scene_edit.EXIT_OK)
        self.assertIn('uid="uid://dcanonlogic" path="res://systems/logic.gd"', text)
        self.assertIn('script = ExtResource(', text)

    def test_add_reports_a_script_whose_uid_cannot_be_resolved(self) -> None:
        from support import temp_repo

        with temp_repo('canon_repo') as root:
            scene = root / 'scenes/panel.tscn'
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                scene_edit.main(['add', str(scene), '.', 'Ghost', 'Node2D',
                                 '--script', 'res://systems/ghost.gd'])
        self.assertIn('NO UID', output.getvalue())


class DryRun(VerbCase):
    def test_dry_run_writes_nothing(self) -> None:
        before = self.text()
        self.run_verb('rename', str(self.scene), 'WallLayer', 'Walls', '--dry-run')
        self.assertEqual(self.text(), before)


if __name__ == '__main__':
    unittest.main()
