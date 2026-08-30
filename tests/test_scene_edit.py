"""Tier 2 — the surgical write verbs.

Three properties are load-bearing and each has its own case: the verbs touch
ONLY what they were asked to (measured as changed lines), they are idempotent,
and they REFUSE rather than write a plausible-looking wrong answer.
"""
from __future__ import annotations

import contextlib
import io
import re
import shutil
import tempfile
import unittest
from pathlib import Path

from support import FIXTURES

from godot_devkit.godot.write import scene_edit
from godot_devkit.godot.format.tscn import TscnError
from godot_devkit.godot.format.tscn_document import TscnDocument

SINK = FIXTURES / 'kitchen_sink.tscn'
CORPUS = FIXTURES / 'corpus'
DASH_TRES = CORPUS / 'nb/data/abilities/dash/standard_t1.tres'
HAZARD_TSCN = CORPUS / 'nb/systems/hazards/hazard.tscn'
PANEL_TSCN = FIXTURES / 'canon_repo/scenes/panel.tscn'


class VerbCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.scene = self.tmp / 'scene.tscn'
        shutil.copy2(SINK, self.scene)
        self.addCleanup(shutil.rmtree, self.tmp)

    def copy_of(self, source: Path) -> Path:
        """A scratch copy of a committed fixture/corpus file (corpus is
        READ-ONLY; every write in these tests happens in the tmp dir)."""
        target = self.tmp / source.name
        shutil.copy2(source, target)
        return target

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

    def test_add_is_idempotent(self) -> None:
        self.run_verb('add', str(self.scene), 'Nested', 'Extra', 'Sprite2D')
        once = self.text()
        self.assertEqual(self.run_verb('add', str(self.scene), 'Nested', 'Extra', 'Sprite2D'),
                         scene_edit.EXIT_OK)
        self.assertEqual(self.text(), once)

    def test_reparent_is_idempotent(self) -> None:
        self.run_verb('reparent', str(self.scene), 'Nested/Deep', '.')
        once = self.text()
        self.assertEqual(self.run_verb('reparent', str(self.scene), 'Nested/Deep', '.'),
                         scene_edit.EXIT_OK)
        self.assertEqual(self.text(), once)

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


class RmSemantics(VerbCase):
    """`rm` on a path that resolves nothing REFUSES (exit 1): with no node
    there is no evidence a removal ever happened, so a typo'd path must not
    read as success. `--force` opts back into the exit-0 no-op for scripted
    re-runs."""

    def test_rm_refuses_a_path_that_resolves_nothing(self) -> None:
        before = self.text()
        self.assertEqual(self.run_verb('rm', str(self.scene), 'Typo/Node'),
                         scene_edit.EXIT_REFUSED)
        self.assertIn('REFUSED', self.output.getvalue())
        self.assertEqual(self.text(), before)

    def test_rm_force_treats_a_missing_node_as_already_removed(self) -> None:
        before = self.text()
        self.assertEqual(self.run_verb('rm', str(self.scene), 'Typo/Node', '--force'),
                         scene_edit.EXIT_OK)
        self.assertEqual(self.text(), before)

    def test_rm_twice_never_writes_and_force_makes_it_exit_0(self) -> None:
        self.run_verb('rm', str(self.scene), 'Panel')
        once = self.text()
        self.assertEqual(self.run_verb('rm', str(self.scene), 'Panel'),
                         scene_edit.EXIT_REFUSED)
        self.assertEqual(self.text(), once)
        self.assertEqual(self.run_verb('rm', str(self.scene), 'Panel', '--force'),
                         scene_edit.EXIT_OK)
        self.assertEqual(self.text(), once)


class RefusesUnreadableBytes(VerbCase):
    def test_a_non_utf8_file_is_refused_not_a_traceback(self) -> None:
        self.scene.write_bytes(b'[gd_scene format=3]\n\xff\xfe not utf-8\n')
        code = self.run_verb('set', str(self.scene), '.', 'x', '1')
        self.assertEqual(code, scene_edit.EXIT_REFUSED)
        self.assertIn('REFUSED', self.output.getvalue())


class LineEndingFidelity(VerbCase):
    """A write verb must never rewrite a byte it was not asked to touch — and
    a line ENDING is a byte. Verbs once normalized every ending in the file
    (universal-newline read + os.linesep write); these pin the whole-verb
    path on real bytes."""

    def test_set_on_a_crlf_file_changes_exactly_one_line_of_bytes(self) -> None:
        crlf = self.text().replace('\n', '\r\n').encode()
        self.scene.write_bytes(crlf)
        code = self.run_verb('set', str(self.scene), 'Sandbox', 'tint',
                             'Color(1, 0, 0, 1)')
        self.assertEqual(code, scene_edit.EXIT_OK)
        raw = self.scene.read_bytes()
        before_lines = crlf.split(b'\r\n')
        after_lines = raw.split(b'\r\n')
        self.assertEqual(len(after_lines), len(before_lines))   # still CRLF everywhere
        self.assertNotIn(b'\n', raw.replace(b'\r\n', b''))      # no lone LF minted
        changed = [pair for pair in zip(before_lines, after_lines)
                   if pair[0] != pair[1]]
        self.assertEqual(len(changed), 1)

    def test_an_unchanged_run_leaves_a_crlf_file_byte_identical(self) -> None:
        crlf = self.text().replace('\n', '\r\n').encode()
        self.scene.write_bytes(crlf)
        self.run_verb('set', str(self.scene), 'Sandbox', 'tint', 'Color(1, 0, 0, 1)')
        once = self.scene.read_bytes()
        self.assertEqual(self.run_verb('set', str(self.scene), 'Sandbox', 'tint',
                                       'Color(1, 0, 0, 1)'), scene_edit.EXIT_OK)
        self.assertEqual(self.scene.read_bytes(), once)


class RootNameAmbiguity(unittest.TestCase):
    """Addressing the root by its own name is a convenience — until a CHILD
    carries the same name, when the address means two nodes and answering
    with either is a silent wrong edit. Refuse; `.` is always unambiguous."""

    AMBIGUOUS = ('[gd_scene format=3]\n\n'
                 '[node name="Sandbox" type="Node2D"]\n\n'
                 '[node name="Sandbox" type="Node2D" parent="."]\n')

    def test_refuses_a_root_name_shared_with_a_child(self) -> None:
        doc = TscnDocument(self.AMBIGUOUS)
        with self.assertRaises(TscnError) as caught:
            doc.node('Sandbox')
        self.assertIn('ambiguous', str(caught.exception))

    def test_dot_still_answers_with_the_root(self) -> None:
        doc = TscnDocument(self.AMBIGUOUS)
        self.assertNotIn('parent', doc.node('.').attrs)


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


class SetResourceProps(VerbCase):
    """`set --resource` / `set --sub-resource <id>` — the whole data/**.tres
    plane, previously hand-edit-only. The id is exactly what `scene --props`
    prints: read output is write input."""

    def test_sub_resource_set_replaces_a_value_in_place(self) -> None:
        before = self.text()
        code = self.run_verb('set', str(self.scene), '--sub-resource', 'Rect_extent',
                             'size', 'Vector2(640, 320)')
        self.assertEqual(code, scene_edit.EXIT_OK)
        self.assertIn('size = Vector2(640, 320)', self.text())
        self.assertEqual(len(self.changed_lines(before)), 1)

    def test_sub_resource_set_appends_inside_that_sub_resource(self) -> None:
        self.run_verb('set', str(self.scene), '--sub-resource', 'Identity_dark',
                      'region', 'Rect2(0, 0, 8, 8)')
        self.assertIn('display_name = &"Dark Room"\nregion = Rect2(0, 0, 8, 8)\n',
                      self.text())

    def test_sub_resource_set_is_idempotent(self) -> None:
        self.run_verb('set', str(self.scene), '--sub-resource', 'Rect_extent',
                      'size', 'Vector2(640, 320)')
        once = self.text()
        self.assertEqual(self.run_verb('set', str(self.scene), '--sub-resource',
                                       'Rect_extent', 'size', 'Vector2(640, 320)'),
                         scene_edit.EXIT_OK)
        self.assertEqual(self.text(), once)

    def test_sub_resource_refuses_an_unknown_id_naming_the_known_ones(self) -> None:
        before = self.text()
        code = self.run_verb('set', str(self.scene), '--sub-resource', 'Nope',
                             'size', '1')
        self.assertEqual(code, scene_edit.EXIT_REFUSED)
        for known in ('Identity_dark', 'Rect_extent', 'Animation_pulse'):
            self.assertIn(known, self.output.getvalue())
        self.assertEqual(self.text(), before)

    def test_resource_refuses_a_file_with_no_resource_body(self) -> None:
        code = self.run_verb('set', str(self.scene), '--resource', 'x', '1')
        self.assertEqual(code, scene_edit.EXIT_REFUSED)
        self.assertIn('[resource]', self.output.getvalue())

    def test_resource_set_on_a_real_tres_touches_one_line(self) -> None:
        tres = self.copy_of(DASH_TRES)
        before = tres.read_text(encoding='utf-8')
        code = self.run_verb('set', str(tres), '--resource', 'dash_id', '&"boosted"')
        after = tres.read_text(encoding='utf-8')
        self.assertEqual(code, scene_edit.EXIT_OK)
        self.assertIn('dash_id = &"boosted"', after)
        changed = [pair for pair in zip(before.splitlines(), after.splitlines())
                   if pair[0] != pair[1]]
        self.assertEqual(len(changed), 1)

    def test_resource_set_is_idempotent_on_a_real_tres(self) -> None:
        tres = self.copy_of(DASH_TRES)
        self.run_verb('set', str(tres), '--resource', 'dash_id', '&"boosted"')
        once = tres.read_bytes()
        self.assertEqual(self.run_verb('set', str(tres), '--resource',
                                       'dash_id', '&"boosted"'), scene_edit.EXIT_OK)
        self.assertEqual(tres.read_bytes(), once)

    def test_set_takes_exactly_one_address(self) -> None:
        for argv in (('set', str(self.scene), 'Sandbox', 'x', '1', '--resource'),
                     ('set', str(self.scene), '--resource', '--sub-resource',
                      'Rect_extent', 'x', '1')):
            with self.assertRaises(SystemExit) as bail, \
                    contextlib.redirect_stderr(io.StringIO()):
                self.run_verb(*argv)
            self.assertEqual(bail.exception.code, 2)

    def test_the_props_output_id_is_the_write_address(self) -> None:
        """Read output is write input: the id `scene --props` prints addresses
        the write verbatim."""
        from godot_devkit.godot.read import scene_summary
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            scene_summary.main([str(self.scene)])
        match = re.search(r'\[(\w+)\] RectangleShape2D', buffer.getvalue())
        self.assertIsNotNone(match)
        code = self.run_verb('set', str(self.scene), '--sub-resource', match.group(1),
                             'size', 'Vector2(8, 8)')
        self.assertEqual(code, scene_edit.EXIT_OK)
        self.assertIn('size = Vector2(8, 8)', self.text())


class AddInstance(unittest.TestCase):
    """`add --instance` — an instance node has NO type=; its ext_resource is
    minted from the target's own uid, so the ref is born canonical."""

    def run_verb(self, *argv: str) -> int:
        self.output = io.StringIO()
        with contextlib.redirect_stdout(self.output):
            return scene_edit.main([*argv])

    def test_add_instance_mints_a_canonical_packed_scene_ref(self) -> None:
        from support import temp_repo
        with temp_repo('canon_repo') as root:
            scene = root / 'scenes/referrer.tscn'
            code = self.run_verb('add', str(scene), '.', 'PanelInst',
                                 '--instance', 'res://scenes/panel.tscn')
            text = scene.read_text(encoding='utf-8')
        self.assertEqual(code, scene_edit.EXIT_OK)
        self.assertIn('[ext_resource type="PackedScene" uid="uid://dcanonpanel" '
                      'path="res://scenes/panel.tscn" id="2_panel"]', text)
        self.assertIn('[node name="PanelInst" parent="." '
                      'instance=ExtResource("2_panel")]', text)
        self.assertIn('load_steps=3', text)

    def test_add_instance_is_idempotent(self) -> None:
        from support import temp_repo
        with temp_repo('canon_repo') as root:
            scene = root / 'scenes/referrer.tscn'
            self.run_verb('add', str(scene), '.', 'PanelInst',
                          '--instance', 'res://scenes/panel.tscn')
            once = scene.read_bytes()
            code = self.run_verb('add', str(scene), '.', 'PanelInst',
                                 '--instance', 'res://scenes/panel.tscn')
            self.assertEqual(code, scene_edit.EXIT_OK)
            self.assertEqual(scene.read_bytes(), once)

    def test_add_instance_refuses_a_scene_that_does_not_exist(self) -> None:
        from support import temp_repo
        with temp_repo('canon_repo') as root:
            scene = root / 'scenes/referrer.tscn'
            before = scene.read_bytes()
            code = self.run_verb('add', str(scene), '.', 'Ghost',
                                 '--instance', 'res://scenes/ghost.tscn')
            self.assertEqual(code, scene_edit.EXIT_REFUSED)
            self.assertIn('REFUSED', self.output.getvalue())
            self.assertEqual(scene.read_bytes(), before)

    def test_add_instance_refuses_a_target_with_no_resolvable_uid(self) -> None:
        from support import temp_repo
        with temp_repo('canon_repo') as root:
            bare = root / 'scenes/bare.tscn'
            bare.write_text('[gd_scene format=3]\n\n'
                            '[node name="Bare" type="Node2D"]\n', encoding='utf-8')
            scene = root / 'scenes/referrer.tscn'
            before = scene.read_bytes()
            code = self.run_verb('add', str(scene), '.', 'Bare',
                                 '--instance', 'res://scenes/bare.tscn')
            self.assertEqual(code, scene_edit.EXIT_REFUSED)
            self.assertIn('uid', self.output.getvalue())
            self.assertEqual(scene.read_bytes(), before)

    def test_add_instance_refuses_a_name_instancing_a_different_scene(self) -> None:
        from support import temp_repo
        with temp_repo('canon_repo') as root:
            scene = root / 'scenes/referrer.tscn'
            code = self.run_verb('add', str(scene), '.', 'Packed',
                                 '--instance', 'res://scenes/panel.tscn')
            self.assertEqual(code, scene_edit.EXIT_REFUSED)
            self.assertIn('res://scenes/packed.tscn', self.output.getvalue())

    def test_add_instance_adopts_an_identical_existing_instance(self) -> None:
        from support import temp_repo
        with temp_repo('canon_repo') as root:
            scene = root / 'scenes/referrer.tscn'
            before = scene.read_bytes()
            code = self.run_verb('add', str(scene), '.', 'Packed',
                                 '--instance', 'res://scenes/packed.tscn')
            self.assertEqual(code, scene_edit.EXIT_OK)
            self.assertEqual(scene.read_bytes(), before)

    def test_add_instance_dry_run_writes_nothing(self) -> None:
        from support import temp_repo
        with temp_repo('canon_repo') as root:
            scene = root / 'scenes/referrer.tscn'
            before = scene.read_bytes()
            code = self.run_verb('add', str(scene), '.', 'PanelInst',
                                 '--instance', 'res://scenes/panel.tscn', '--dry-run')
            self.assertEqual(code, scene_edit.EXIT_OK)
            self.assertEqual(scene.read_bytes(), before)

    def test_add_takes_exactly_one_of_type_or_instance(self) -> None:
        from support import temp_repo
        with temp_repo('canon_repo') as root:
            scene = root / 'scenes/referrer.tscn'
            for argv in (('add', str(scene), '.', 'X'),
                         ('add', str(scene), '.', 'X', 'Node2D',
                          '--instance', 'res://scenes/panel.tscn'),
                         ('add', str(scene), '.', 'X',
                          '--instance', 'res://scenes/panel.tscn',
                          '--script', 'res://systems/logic.gd')):
                with self.assertRaises(SystemExit) as bail, \
                        contextlib.redirect_stderr(io.StringIO()):
                    self.run_verb(*argv)
                self.assertEqual(bail.exception.code, 2, argv)


class ConnectDisconnect(VerbCase):
    """`connect` appends a `[connection]` in Godot's serialization position
    (after all nodes); `disconnect` removes exactly the matching one, refusing
    ambiguity."""

    NEW_CONN = ('[connection signal="toggled" from="Nested/Deep" '
                'to="TileRoomContract" method="_on_toggled"]')

    def test_connect_appends_in_serialization_position(self) -> None:
        before = self.text()
        code = self.run_verb('connect', str(self.scene), 'toggled',
                             'Nested/Deep', 'TileRoomContract', '_on_toggled')
        text = self.text()
        self.assertEqual(code, scene_edit.EXIT_OK)
        self.assertIn(self.NEW_CONN, text)
        self.assertLess(text.index('[connection signal="pressed"'),
                        text.index(self.NEW_CONN))
        self.assertLess(text.index(self.NEW_CONN), text.index('[editable'))
        self.assertEqual(len(self.changed_lines(before)), 1)

    def test_connect_first_connection_is_separated_from_the_nodes(self) -> None:
        panel = self.copy_of(PANEL_TSCN)
        code = self.run_verb('connect', str(panel), 'pressed', 'Inner', '.',
                             '_on_pressed')
        text = panel.read_text(encoding='utf-8')
        self.assertEqual(code, scene_edit.EXIT_OK)
        self.assertTrue(text.endswith(
            '[node name="Footer" type="HBoxContainer" parent="."]\n\n'
            '[connection signal="pressed" from="Inner" to="." '
            'method="_on_pressed"]\n'), text)

    def test_connect_writes_the_canonical_root_address(self) -> None:
        self.run_verb('connect', str(self.scene), 'ready', 'Sandbox',
                      'TileRoomContract', '_on_ready')
        self.assertIn('[connection signal="ready" from="." to="TileRoomContract" '
                      'method="_on_ready"]', self.text())

    def test_connect_is_idempotent(self) -> None:
        self.run_verb('connect', str(self.scene), 'toggled',
                      'Nested/Deep', 'TileRoomContract', '_on_toggled')
        once = self.text()
        self.assertEqual(self.run_verb('connect', str(self.scene), 'toggled',
                                       'Nested/Deep', 'TileRoomContract',
                                       '_on_toggled'), scene_edit.EXIT_OK)
        self.assertEqual(self.text(), once)

    def test_connect_refuses_a_path_that_resolves_no_node(self) -> None:
        before = self.text()
        code = self.run_verb('connect', str(self.scene), 'ready', 'Ghost',
                             'TileRoomContract', '_on_ready')
        self.assertEqual(code, scene_edit.EXIT_REFUSED)
        self.assertIn('REFUSED', self.output.getvalue())
        self.assertEqual(self.text(), before)

    def test_connect_with_flags_serializes_the_flags_attr(self) -> None:
        self.run_verb('connect', str(self.scene), 'toggled', 'Nested/Deep',
                      'TileRoomContract', '_on_toggled', '--flags', '3')
        self.assertIn('method="_on_toggled" flags=3]', self.text())

    def test_connect_refuses_the_same_route_with_different_flags(self) -> None:
        self.run_verb('connect', str(self.scene), 'toggled', 'Nested/Deep',
                      'TileRoomContract', '_on_toggled')
        once = self.text()
        code = self.run_verb('connect', str(self.scene), 'toggled', 'Nested/Deep',
                             'TileRoomContract', '_on_toggled', '--flags', '3')
        self.assertEqual(code, scene_edit.EXIT_REFUSED)
        self.assertIn('flags', self.output.getvalue())
        self.assertEqual(self.text(), once)

    def test_disconnect_removes_exactly_the_matching_connection(self) -> None:
        hazard = self.copy_of(HAZARD_TSCN)
        before = hazard.read_text(encoding='utf-8')
        code = self.run_verb('disconnect', str(hazard), 'body_entered',
                             'DetectorArea', '.', '_on_detector_body_entered')
        after = hazard.read_text(encoding='utf-8')
        self.assertEqual(code, scene_edit.EXIT_OK)
        self.assertNotIn('_on_detector_body_entered', after)
        self.assertIn('[connection signal="body_exited" from="DetectorArea" to="." '
                      'method="_on_detector_body_exited"]', after)
        self.assertEqual(len(before.splitlines()) - len(after.splitlines()), 1)

    def test_disconnect_refuses_when_nothing_matches(self) -> None:
        before = self.text()
        code = self.run_verb('disconnect', str(self.scene), 'pressed', 'Panel',
                             'TileRoomContract', '_typo')
        self.assertEqual(code, scene_edit.EXIT_REFUSED)
        self.assertIn('REFUSED', self.output.getvalue())
        self.assertEqual(self.text(), before)

    def test_disconnect_refuses_ambiguity_and_flags_disambiguate(self) -> None:
        hazard = self.copy_of(HAZARD_TSCN)
        with hazard.open('a', encoding='utf-8') as handle:
            handle.write('[connection signal="body_entered" from="DetectorArea" '
                         'to="." method="_on_detector_body_entered" flags=3]\n')
        code = self.run_verb('disconnect', str(hazard), 'body_entered',
                             'DetectorArea', '.', '_on_detector_body_entered')
        self.assertEqual(code, scene_edit.EXIT_REFUSED)
        self.assertIn('--flags', self.output.getvalue())
        code = self.run_verb('disconnect', str(hazard), 'body_entered',
                             'DetectorArea', '.', '_on_detector_body_entered',
                             '--flags', '3')
        text = hazard.read_text(encoding='utf-8')
        self.assertEqual(code, scene_edit.EXIT_OK)
        self.assertNotIn('flags=3', text)
        self.assertIn('method="_on_detector_body_entered"]', text)

    def test_disconnect_twice_leaves_the_bytes_alone(self) -> None:
        hazard = self.copy_of(HAZARD_TSCN)
        self.run_verb('disconnect', str(hazard), 'body_entered',
                      'DetectorArea', '.', '_on_detector_body_entered')
        once = hazard.read_bytes()
        code = self.run_verb('disconnect', str(hazard), 'body_entered',
                             'DetectorArea', '.', '_on_detector_body_entered')
        self.assertEqual(code, scene_edit.EXIT_REFUSED)
        self.assertEqual(hazard.read_bytes(), once)

    def test_connect_then_disconnect_restores_the_exact_bytes(self) -> None:
        """Disconnect must not eat the blank separator of the NEXT section
        (the [editable] marker's, here) — a byte it was not asked to touch."""
        before = self.scene.read_bytes()
        self.run_verb('connect', str(self.scene), 'toggled', 'Nested/Deep',
                      'TileRoomContract', '_on_toggled')
        self.run_verb('disconnect', str(self.scene), 'toggled', 'Nested/Deep',
                      'TileRoomContract', '_on_toggled')
        self.assertEqual(self.scene.read_bytes(), before)

    def test_connect_then_disconnect_restores_the_exact_bytes_at_eof(self) -> None:
        """Same round trip when the connection lands at end-of-file: no stray
        trailing blank line may survive the disconnect."""
        panel = self.copy_of(PANEL_TSCN)
        before = panel.read_bytes()
        self.run_verb('connect', str(panel), 'pressed', 'Inner', '.', '_on_pressed')
        self.run_verb('disconnect', str(panel), 'pressed', 'Inner', '.', '_on_pressed')
        self.assertEqual(panel.read_bytes(), before)

    def test_connect_dry_run_writes_nothing(self) -> None:
        before = self.text()
        code = self.run_verb('connect', str(self.scene), 'toggled', 'Nested/Deep',
                             'TileRoomContract', '_on_toggled', '--dry-run')
        self.assertEqual(code, scene_edit.EXIT_OK)
        self.assertEqual(self.text(), before)

    def test_every_new_verb_leaves_a_reparsable_scene(self) -> None:
        self.run_verb('connect', str(self.scene), 'toggled', 'Nested/Deep',
                      'TileRoomContract', '_on_toggled')
        self.run_verb('set', str(self.scene), '--sub-resource', 'Rect_extent',
                      'size', 'Vector2(640, 320)')
        text = self.text()
        doc = TscnDocument(text, self.scene)
        self.assertEqual(doc.text, text)


if __name__ == '__main__':
    unittest.main()
