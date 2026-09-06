"""Tier 2 — the surgical write verbs.

Three properties are load-bearing: the verbs touch ONLY what they were asked
to (measured as changed lines), they are idempotent, and they REFUSE rather
than write a plausible-looking wrong answer. Each verb's write case carries its
own idempotence run; every scene read back through `text()` is asserted to
still round-trip, so each write case also proves the verb left a reparsable
scene; refusals are one case per refusal branch in the source, and address
resolution (`TscnDocument.node`) is refused ONCE, under `set`.
"""
from __future__ import annotations

import contextlib
import io
import re
import shutil
import tempfile
import unittest
from pathlib import Path

from support import FIXTURES, temp_repo

from godot_devkit.godot.read import scene_summary
from godot_devkit.godot.write import scene_edit
from godot_devkit.godot.format.tscn import TscnError
from godot_devkit.godot.format.tscn_document import TscnDocument

SINK = FIXTURES / 'kitchen_sink.tscn'
DASH_TRES = FIXTURES / 'corpus/editor_written/data/abilities/dash/standard_t1.tres'
HAZARD_TSCN = FIXTURES / 'corpus/editor_written/systems/hazards/hazard.tscn'
PANEL_TSCN = FIXTURES / 'canon_repo/scenes/panel.tscn'


class VerbCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.scene = self.tmp / 'scene.tscn'
        shutil.copy2(SINK, self.scene)
        self.addCleanup(shutil.rmtree, self.tmp)

    def copy_of(self, source: Path) -> Path:
        # A scratch copy of a committed fixture/corpus file (the corpus is
        # READ-ONLY; every write in these tests happens in the tmp dir).
        shutil.copy2(source, self.tmp / source.name)
        return self.tmp / source.name

    def run_verb(self, *argv: str) -> int:
        # Keeps the verb's (deliberately terse) output off the test log.
        self.output = io.StringIO()
        with contextlib.redirect_stdout(self.output):
            return scene_edit.main([*argv])

    def text(self, path: Path | None = None) -> str:
        # The file as it stands — asserted to still round-trip, so every case
        # that reads a written scene back proves the verb left it reparsable.
        text = (path or self.scene).read_text(encoding='utf-8')
        self.assertEqual(TscnDocument(text, path or self.scene).text, text)
        return text

    def changed_lines(self, before: str) -> list[str]:
        after = self.text().splitlines()
        return [line for line in after if line not in before.splitlines()]

    def refused(self, *argv: str, saying: tuple[str, ...] = ('REFUSED',)) -> None:
        """A verb that must REFUSE: exit 1, say why, and not move a byte."""
        before = Path(argv[1]).read_bytes()
        self.assertEqual(self.run_verb(*argv), scene_edit.EXIT_REFUSED)
        for said in saying:
            self.assertIn(said, self.output.getvalue())
        self.assertEqual(Path(argv[1]).read_bytes(), before)

    def second_run_is_a_no_op(self, *argv: str) -> None:
        once = Path(argv[1]).read_bytes()
        self.assertEqual(self.run_verb(*argv), scene_edit.EXIT_OK)
        self.assertEqual(Path(argv[1]).read_bytes(), once)


class RenameRewritesReferences(VerbCase):
    """The verb's whole reason to exist: a blanket sed rewrote
    NodePath("Sandbox/TileRoomContract") while renaming prose and broke a
    scenario. Rename resolves paths; it does not text-match."""

    def test_rewrites_every_reference_and_nothing_else(self) -> None:
        """`wall_layer` is an EXPORT name and `node_paths=` lists export names —
        neither is a path, and neither may move when the node does. An
        Animation's tracks live in a sub_resource with no path of its own and
        resolve against the AnimationPlayer's `root_node`; a rename that
        misses them breaks the animation silently. `--dry-run` (one mechanism
        in `main`, shared by every verb) writes nothing."""
        before = self.text()
        self.run_verb('rename', str(self.scene), 'WallLayer', 'Walls', '--dry-run')
        self.assertEqual(self.text(), before)
        self.run_verb('rename', str(self.scene), 'WallLayer', 'Walls')
        text = self.text()
        for kept in ('wall_layer = NodePath("../Walls")',
                     'target = NodePath("../../Walls")',
                     'tracks/0/path = NodePath("Walls:modulate")',
                     'node_paths=PackedStringArray("wall_layer")',
                     '; The contract wires the layers by NodePath'):
            self.assertIn(kept, text)
        self.assertNotIn('WallLayer', text)
        self.assertEqual(len(self.changed_lines(before)), 4)
        self.second_run_is_a_no_op('rename', str(self.scene), 'WallLayer', 'Walls')
        self.run_verb('rename', str(self.scene), 'Nested', 'Container')
        self.assertIn('[node name="Deep" type="Marker2D" parent="Container"]', self.text())

    def test_refuses_a_name_collision(self) -> None:
        self.refused('rename', str(self.scene), 'Nested', 'WallLayer')
        self.assertNotIn('name="WallLayer" type="Node2D"', self.text())


class SetProperty(VerbCase):
    def test_replaces_a_value_in_place_keeping_an_inline_comment(self) -> None:
        before = self.text()
        self.run_verb('set', str(self.scene), 'Sandbox', 'tint', 'Color(1, 0, 0, 1)')
        self.assertIn('tint = Color(1, 0, 0, 1)', self.text())
        self.assertEqual(len(self.changed_lines(before)), 1)
        self.second_run_is_a_no_op('set', str(self.scene), 'Sandbox', 'tint',
                                   'Color(1, 0, 0, 1)')
        self.run_verb('set', str(self.scene), 'TileRoomContract', 'layers', '{ "a": 9 }')
        self.assertIn('layers = { "a": 9 } ; trailing comment on a multi-line value',
                      self.text())

    def test_appends_a_new_property_to_the_right_node(self) -> None:
        self.run_verb('set', str(self.scene), 'Nested/Deep', 'visible', 'false')
        text = self.text()
        self.assertIn('[node name="Deep" type="Marker2D" parent="Nested"]\n'
                      'target = NodePath("../../WallLayer")\nvisible = false\n', text)

    def test_refuses_an_unknown_node(self) -> None:
        self.refused('set', str(self.scene), 'Nope', 'x', '1')


class AddRemoveReparent(VerbCase):
    def test_add_places_the_node_after_the_parent_subtree(self) -> None:
        self.run_verb('add', str(self.scene), 'Nested', 'Extra', 'Sprite2D')
        text = self.text()
        self.assertIn('[node name="Extra" type="Sprite2D" parent="Nested"]', text)
        self.assertLess(text.index('name="Deep"'), text.index('name="Extra"'))
        self.second_run_is_a_no_op('add', str(self.scene), 'Nested', 'Extra', 'Sprite2D')
        # Same name, different type: not a re-run, a shadowing — refused.
        self.refused('add', str(self.scene), 'Nested', 'Extra', 'Node2D')

    def test_rm_takes_descendants_connections_markers_and_orphaned_resources(self) -> None:
        self.run_verb('rm', str(self.scene), 'Panel')
        text = self.text()
        for gone in ('name="Panel"', 'name="Inner"', '[connection', '[editable',
                     'panel.tscn'):
            self.assertNotIn(gone, text)
        self.assertIn('load_steps=7', text)          # 8 -> 7, one resource fewer
        # `rm` of a path that resolves nothing REFUSES (exit 1): with no node
        # there is no evidence a removal ever happened, so a typo'd path must
        # not read as success. `--force` opts back into the exit-0 no-op.
        self.refused('rm', str(self.scene), 'Panel')
        self.second_run_is_a_no_op('rm', str(self.scene), 'Panel', '--force')

    def test_reparent_moves_the_subtree_and_fixes_its_nodepaths(self) -> None:
        self.run_verb('reparent', str(self.scene), 'Nested/Deep', '.')
        text = self.text()
        self.assertIn('[node name="Deep" type="Marker2D" parent="."]', text)
        # One `..` fewer now that the node sits one level higher.
        self.assertIn('target = NodePath("../WallLayer")', text)
        self.second_run_is_a_no_op('reparent', str(self.scene), 'Nested/Deep', '.')
        self.refused('reparent', str(self.scene), 'Nested', 'Nested/Deep')


class MainMechanics(VerbCase):
    """What `main` does for every verb before and after the handler."""

    def test_a_non_utf8_file_is_refused_not_a_traceback(self) -> None:
        self.scene.write_bytes(b'[gd_scene format=3]\n\xff\xfe not utf-8\n')
        self.refused('set', str(self.scene), '.', 'x', '1')

    def test_set_on_a_crlf_file_changes_exactly_one_line_of_bytes(self) -> None:
        """A line ENDING is a byte a verb was not asked to touch. Verbs once
        normalized every ending (universal-newline read + os.linesep write);
        this pins the whole-verb path on real bytes."""
        crlf = self.text().replace('\n', '\r\n').encode()
        self.scene.write_bytes(crlf)
        self.assertEqual(self.run_verb('set', str(self.scene), 'Sandbox', 'tint',
                                       'Color(1, 0, 0, 1)'), scene_edit.EXIT_OK)
        raw = self.scene.read_bytes()
        before_lines = crlf.split(b'\r\n')
        after_lines = raw.split(b'\r\n')
        self.assertEqual(len(after_lines), len(before_lines))   # still CRLF everywhere
        self.assertNotIn(b'\n', raw.replace(b'\r\n', b''))      # no lone LF minted
        changed = [pair for pair in zip(before_lines, after_lines)
                   if pair[0] != pair[1]]
        self.assertEqual(len(changed), 1)

    def test_each_exactly_one_usage_rule_exits_2(self) -> None:
        # The rules argparse cannot spell, one row per `parser.error` branch.
        for argv in (('set', str(self.scene), 'Sandbox', 'x', '1', '--resource'),
                     ('add', str(self.scene), '.', 'X'),
                     ('add', str(self.scene), '.', 'X',
                      '--instance', 'res://scenes/panel.tscn',
                      '--script', 'res://systems/logic.gd')):
            with self.assertRaises(SystemExit) as bail, \
                    contextlib.redirect_stderr(io.StringIO()):
                self.run_verb(*argv)
            self.assertEqual(bail.exception.code, 2, argv)


class RootNameAmbiguity(unittest.TestCase):
    """Addressing the root by its own name is a convenience — until a CHILD
    carries the same name, when the address means two nodes and answering
    with either is a silent wrong edit. Refuse; `.` is always unambiguous."""

    AMBIGUOUS = ('[gd_scene format=3]\n\n'
                 '[node name="Sandbox" type="Node2D"]\n\n'
                 '[node name="Sandbox" type="Node2D" parent="."]\n')

    def test_refuses_a_root_name_shared_with_a_child_but_dot_still_answers(self) -> None:
        doc = TscnDocument(self.AMBIGUOUS)
        with self.assertRaises(TscnError) as caught:
            doc.node('Sandbox')
        self.assertIn('ambiguous', str(caught.exception))
        self.assertNotIn('parent', doc.node('.').attrs)


class SetResourceProps(VerbCase):
    """`set --resource` / `set --sub-resource <id>` — the whole data/**.tres
    plane, previously hand-edit-only. The id is exactly what `scene --props`
    prints: read output is write input."""

    def test_refuses_a_resource_address_the_file_does_not_have(self) -> None:
        self.refused('set', str(self.scene), '--sub-resource', 'Nope', 'size', '1',
                     saying=('Identity_dark', 'Rect_extent', 'Animation_pulse'))
        self.refused('set', str(self.scene), '--resource', 'x', '1', saying=('[resource]',))

    def test_resource_set_on_a_real_tres_touches_one_line(self) -> None:
        tres = self.copy_of(DASH_TRES)
        before = tres.read_text(encoding='utf-8')
        self.assertEqual(self.run_verb('set', str(tres), '--resource', 'dash_id',
                                       '&"boosted"'), scene_edit.EXIT_OK)
        after = self.text(tres)
        self.assertIn('dash_id = &"boosted"', after)
        changed = [pair for pair in zip(before.splitlines(), after.splitlines())
                   if pair[0] != pair[1]]
        self.assertEqual(len(changed), 1)

    def test_the_props_output_id_is_the_write_address(self) -> None:
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            scene_summary.main([str(self.scene)])
        match = re.search(r'\[(\w+)\] RectangleShape2D', buffer.getvalue())
        self.assertIsNotNone(match)
        self.assertEqual(self.run_verb('set', str(self.scene), '--sub-resource',
                                       match.group(1), 'size', 'Vector2(8, 8)'),
                         scene_edit.EXIT_OK)
        self.assertIn('size = Vector2(8, 8)', self.text())


class AddResolvesRefs(VerbCase):
    """`check tres` requires uid-in-refs, so a verb that mints a path-only ref
    is handing the next gate a failure: `add --script` resolves the uid (and
    says so when it cannot); `add --instance` mints the PackedScene ref from
    the target's own uid, and an instance node has NO type=."""

    def test_add_with_script_writes_a_uid_in_ref_or_reports_no_uid(self) -> None:
        with temp_repo('canon_repo') as root:
            scene = root / 'scenes/panel.tscn'
            self.assertEqual(self.run_verb('add', str(scene), '.', 'Logic', 'Node2D',
                                           '--script', 'res://systems/logic.gd'),
                             scene_edit.EXIT_OK)
            text = self.text(scene)
            self.run_verb('add', str(scene), '.', 'Ghost', 'Node2D',
                          '--script', 'res://systems/ghost.gd')
        self.assertIn('uid="uid://dcanonlogic" path="res://systems/logic.gd"', text)
        self.assertIn('script = ExtResource(', text)
        self.assertIn('NO UID', self.output.getvalue())

    def test_add_instance_mints_a_canonical_packed_scene_ref(self) -> None:
        with temp_repo('canon_repo') as root:
            scene = root / 'scenes/referrer.tscn'
            self.assertEqual(self.run_verb('add', str(scene), '.', 'PanelInst',
                                           '--instance', 'res://scenes/panel.tscn'),
                             scene_edit.EXIT_OK)
            text = self.text(scene)
        for minted in ('[ext_resource type="PackedScene" uid="uid://dcanonpanel" '
                       'path="res://scenes/panel.tscn" id="2_panel"]',
                       '[node name="PanelInst" parent="." instance=ExtResource("2_panel")]',
                       'load_steps=3'):
            self.assertIn(minted, text)

    def test_add_instance_refuses_each_lie_a_ref_could_be_born_with(self) -> None:
        # A target that is not there, a target with no uid, and a name that
        # already instances a different scene — three refusal branches.
        with temp_repo('canon_repo') as root:
            (root / 'scenes/bare.tscn').write_text(
                '[gd_scene format=3]\n\n[node name="Bare" type="Node2D"]\n', encoding='utf-8')
            scene = root / 'scenes/referrer.tscn'
            for name, target, said in (('Ghost', 'res://scenes/ghost.tscn', 'REFUSED'),
                                       ('Bare', 'res://scenes/bare.tscn', 'uid'),
                                       ('Packed', 'res://scenes/panel.tscn',
                                        'res://scenes/packed.tscn')):
                with self.subTest(target=target):
                    self.refused('add', str(scene), '.', name, '--instance', target,
                                 saying=(said,))

    def test_add_instance_adopts_an_identical_existing_instance(self) -> None:
        with temp_repo('canon_repo') as root:
            self.second_run_is_a_no_op('add', str(root / 'scenes/referrer.tscn'), '.',
                                       'Packed', '--instance', 'res://scenes/packed.tscn')


class ConnectDisconnect(VerbCase):
    """`connect` appends a `[connection]` in Godot's serialization position
    (after all nodes); `disconnect` removes exactly the matching one, refusing
    ambiguity."""

    NEW_CONN = ('[connection signal="toggled" from="Nested/Deep" '
                'to="TileRoomContract" method="_on_toggled"]')

    def test_connect_appends_in_serialization_position(self) -> None:
        before = self.text()
        self.assertEqual(self.run_verb('connect', str(self.scene), 'toggled', 'Nested/Deep',
                                       'TileRoomContract', '_on_toggled'), scene_edit.EXIT_OK)
        text = self.text()
        self.assertIn(self.NEW_CONN, text)
        self.assertLess(text.index('[connection signal="pressed"'),
                        text.index(self.NEW_CONN))
        self.assertLess(text.index(self.NEW_CONN), text.index('[editable'))
        self.assertEqual(len(self.changed_lines(before)), 1)
        self.second_run_is_a_no_op('connect', str(self.scene), 'toggled', 'Nested/Deep',
                                   'TileRoomContract', '_on_toggled')
        # The root addressed by its own name is written as `.`, as .tscn spells it.
        self.run_verb('connect', str(self.scene), 'ready', 'Sandbox',
                      'TileRoomContract', '_on_ready')
        self.assertIn('[connection signal="ready" from="." to="TileRoomContract" '
                      'method="_on_ready"]', self.text())

    def test_first_connection_lands_at_eof_and_disconnect_restores_the_bytes(self) -> None:
        # No stray trailing blank line may survive the disconnect.
        panel = self.copy_of(PANEL_TSCN)
        before = panel.read_bytes()
        self.assertEqual(self.run_verb('connect', str(panel), 'pressed', 'Inner', '.',
                                       '_on_pressed'), scene_edit.EXIT_OK)
        self.assertTrue(self.text(panel).endswith(
            '[node name="Footer" type="HBoxContainer" parent="."]\n\n'
            '[connection signal="pressed" from="Inner" to="." '
            'method="_on_pressed"]\n'))
        self.run_verb('disconnect', str(panel), 'pressed', 'Inner', '.', '_on_pressed')
        self.assertEqual(panel.read_bytes(), before)

    def test_connect_serializes_flags_and_refuses_a_route_that_differs_only_in_flags(
            self) -> None:
        self.run_verb('connect', str(self.scene), 'toggled', 'Nested/Deep',
                      'TileRoomContract', '_on_toggled')
        self.refused('connect', str(self.scene), 'toggled', 'Nested/Deep',
                     'TileRoomContract', '_on_toggled', '--flags', '3', saying=('flags',))
        self.run_verb('connect', str(self.scene), 'ready', 'Nested/Deep',
                      'TileRoomContract', '_on_ready', '--flags', '3')
        self.assertIn('method="_on_ready" flags=3]', self.text())

    def test_disconnect_removes_exactly_the_matching_connection_once(self) -> None:
        hazard = self.copy_of(HAZARD_TSCN)
        before = hazard.read_text(encoding='utf-8')
        self.assertEqual(self.run_verb('disconnect', str(hazard), 'body_entered',
                                       'DetectorArea', '.', '_on_detector_body_entered'),
                         scene_edit.EXIT_OK)
        after = self.text(hazard)
        self.assertNotIn('_on_detector_body_entered', after)
        self.assertIn('[connection signal="body_exited" from="DetectorArea" to="." '
                      'method="_on_detector_body_exited"]', after)
        self.assertEqual(len(before.splitlines()) - len(after.splitlines()), 1)
        # A second disconnect matches nothing: REFUSED, and not a byte moves.
        self.refused('disconnect', str(hazard), 'body_entered',
                     'DetectorArea', '.', '_on_detector_body_entered')

    def test_disconnect_refuses_ambiguity_and_flags_disambiguate(self) -> None:
        hazard = self.copy_of(HAZARD_TSCN)
        with hazard.open('a', encoding='utf-8') as handle:
            handle.write('[connection signal="body_entered" from="DetectorArea" '
                         'to="." method="_on_detector_body_entered" flags=3]\n')
        self.refused('disconnect', str(hazard), 'body_entered',
                     'DetectorArea', '.', '_on_detector_body_entered', saying=('--flags',))
        self.assertEqual(self.run_verb('disconnect', str(hazard), 'body_entered',
                                       'DetectorArea', '.', '_on_detector_body_entered',
                                       '--flags', '3'), scene_edit.EXIT_OK)
        text = self.text(hazard)
        self.assertNotIn('flags=3', text)
        self.assertIn('method="_on_detector_body_entered"]', text)

    def test_connect_then_disconnect_restores_the_exact_bytes(self) -> None:
        """Disconnect must not eat the blank separator of the NEXT section
        (the [editable] marker's, here) — a byte it was not asked to touch."""
        before = self.scene.read_bytes()
        self.run_verb('connect', str(self.scene), 'toggled', 'Nested/Deep',
                      'TileRoomContract', '_on_toggled')
        self.run_verb('disconnect', str(self.scene), 'toggled', 'Nested/Deep',
                      'TileRoomContract', '_on_toggled')
        self.assertEqual(self.scene.read_bytes(), before)
