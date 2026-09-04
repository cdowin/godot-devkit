"""Tier 3 — restoring what `PackedScene.pack()` + `ResourceSaver.save()` drop.

Each case degrades a fixture the way `save()` does and checks that canonicalize
puts back exactly what was lost — anything the tool invents rather than derives
shows up as a diff. The same proof over a REAL consumer scene is `make smoke`'s
`canonicalize round trip` row, which picks the scene the degradation costs most.
"""
from __future__ import annotations

import contextlib
import io
import re
import unittest

from support import FIXTURES, temp_repo

from godot_devkit.godot.write import scene_canonicalize
from godot_devkit.godot.format.tscn_document import read_scene_text
from godot_devkit.godot.index.uid_index import UidIndex
from godot_devkit.core.project import repo_root


def canonicalize_in_repo(*argv: str) -> tuple[int, str]:
    repo_root.cache_clear()
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        code = scene_canonicalize.main([*argv])
    repo_root.cache_clear()
    return code, buffer.getvalue()


class RestoresWhatPackDrops(unittest.TestCase):
    def test_restores_all_three_losses(self) -> None:
        with temp_repo('canon_repo') as root:
            code, out = canonicalize_in_repo('scenes/packed.tscn')
            text = (root / 'scenes/packed.tscn').read_text(encoding='utf-8')
        self.assertEqual(code, scene_canonicalize.EXIT_OK, out)
        # 1. uid-in-refs, from the .gd sidecar and from the .tscn's own header
        self.assertIn('uid="uid://dcanonlogic" path="res://systems/logic.gd"', text)
        self.assertIn('uid="uid://dcanonpanel" path="res://scenes/panel.tscn"', text)
        # 2. the file's own header uid, recovered from what already references it
        self.assertIn('[gd_scene load_steps=3 format=3 uid="uid://dcanonpacked"]', text)
        # 3. index= — without it this override reloads as a NEW SIBLING
        self.assertIn('[node name="Footer" parent="Panel" index="1"]', text)
        # There is no fourth: `[editable]` is authored state, not a pack() loss
        # — see EditableMarkersAreAuthoredNotDerived below.

    def test_index_is_counted_off_the_base_scene_not_guessed(self) -> None:
        """Footer is the SECOND child of panel.tscn's root, so index must be 1."""
        with temp_repo('canon_repo') as root:
            canonicalize_in_repo('scenes/packed.tscn')
            text = (root / 'scenes/packed.tscn').read_text(encoding='utf-8')
        self.assertIn('index="1"', text)
        self.assertNotIn('index="0"', text)

    def test_is_idempotent(self) -> None:
        with temp_repo('canon_repo') as root:
            canonicalize_in_repo('scenes/packed.tscn')
            once = (root / 'scenes/packed.tscn').read_text(encoding='utf-8')
            code, out = canonicalize_in_repo('scenes/packed.tscn')
            twice = (root / 'scenes/packed.tscn').read_text(encoding='utf-8')
        self.assertEqual(twice, once)
        self.assertIn('already canonical', out)
        self.assertEqual(code, scene_canonicalize.EXIT_OK)

    def test_a_crlf_file_keeps_its_endings_through_a_restoration(self) -> None:
        """Canonicalize restores what pack() dropped — it does not get to
        normalize every line ending in the file on the way through."""
        with temp_repo('canon_repo') as root:
            scene = root / 'scenes/packed.tscn'
            crlf = scene.read_text(encoding='utf-8').replace('\n', '\r\n').encode()
            scene.write_bytes(crlf)
            code, out = canonicalize_in_repo('scenes/packed.tscn')
            raw = scene.read_bytes()
        self.assertEqual(code, scene_canonicalize.EXIT_OK, out)
        self.assertIn(b'uid="uid://dcanonlogic"', raw)          # it DID restore
        self.assertNotIn(b'\n', raw.replace(b'\r\n', b''),
                         'restoration minted lone-LF lines in a CRLF file')

    def test_a_non_utf8_file_is_refused_not_a_traceback(self) -> None:
        with temp_repo('canon_repo') as root:
            scene = root / 'scenes/packed.tscn'
            scene.write_bytes(b'[gd_scene format=3]\n\xff\xfe not utf-8\n')
            code, out = canonicalize_in_repo('scenes/packed.tscn')
        self.assertEqual(code, scene_canonicalize.EXIT_FINDINGS)
        self.assertIn('REFUSED', out)

    def test_reports_and_refuses_a_uid_it_cannot_resolve(self) -> None:
        """A uid that cannot be derived is left alone and named — inventing one
        would be worse than the missing ref."""
        with temp_repo('canon_repo') as root:
            scene = root / 'scenes/packed.tscn'
            scene.write_text(scene.read_text(encoding='utf-8').replace(
                'res://systems/logic.gd', 'res://systems/ghost.gd'), encoding='utf-8')
            code, out = canonicalize_in_repo('scenes/packed.tscn')
            text = scene.read_text(encoding='utf-8')
        self.assertEqual(code, scene_canonicalize.EXIT_FINDINGS)
        self.assertIn('UNRESOLVED', out)
        self.assertIn('ghost.gd', out)
        self.assertIn('path="res://systems/ghost.gd"', text)


# --- [editable] is authored, never derived ------------------------------------
# 0.24.0/bugs/scene-canonicalize-invents-an-editable-marker. `[editable path=]`
# records ONE thing: the editor's per-instance "Editable Children" toggle. In
# the engine (scene/resources/packed_scene.cpp) it is written on pack only from
# `p_owner->is_editable_instance(p_node)` — the live flag — and on load it is
# applied LAST, after every node and property already exists, by calling
# `set_editable_instance(ei, true)`. No override anywhere consults it. So an
# instance whose children carry overrides is not thereby an editable instance,
# and deriving the marker from the node tree invents authored state: the next
# load hands a human a sub-tree the scene never said was editable, and the next
# editor save writes the marker out for good.
#
# The corpus says the same thing without the engine: it holds 21 markers on
# hosts and 7 scenes whose instance children are overridden with NO marker —
# the two facts are independent in BOTH directions, which no derivation rule
# can produce.
CORPUS = FIXTURES / 'corpus'
# Floors, so a corpus that rots into vacuity fails here instead of proving
# less. 7 scenes reproduce the invention; quarantine.tscn carries the 21
# markers that prove the opposite failure would be caught.
OVERRIDDEN_SCENE_FLOOR = 7
DECLARED_MARKER_FLOOR = 21
EDITABLE_SECTION = re.compile(r'^\[editable path="([^"]*)"\]', re.M)


def editable_paths(text: str) -> list[str]:
    return EDITABLE_SECTION.findall(text)


class EditableMarkersAreAuthoredNotDerived(unittest.TestCase):
    """The committed corpus is real consumer structure that runs on CI too, so
    this is the bug's own 21-file corpus made portable."""

    def test_no_corpus_scene_gains_or_loses_a_marker(self) -> None:
        scenes = overridden = declared = 0
        for slice_name in ('nb', 'tr'):
            root = CORPUS / slice_name
            uids = UidIndex(root)
            bases = scene_canonicalize.BaseScenes(root)
            for path in sorted(root.rglob('*.tscn')):
                before = read_scene_text(path)
                after, _report = scene_canonicalize.canonicalize(
                    path, root, uids, bases)
                self.assertEqual(
                    editable_paths(after), editable_paths(before),
                    f'{path.relative_to(CORPUS)}: canonicalize changed the '
                    f'[editable] sections')
                scenes += 1
                doc = scene_canonicalize.TscnDocument(before, path)
                if any('type' not in n.attrs and 'instance' not in n.attrs
                       for n in doc.nodes):
                    overridden += 1
                declared += len(editable_paths(before))
        self.assertGreaterEqual(overridden, OVERRIDDEN_SCENE_FLOOR,
                                f'{scenes} scenes scanned but only {overridden} '
                                'carry an instance-child override — the corpus '
                                'no longer reproduces the bug')
        self.assertGreaterEqual(declared, DECLARED_MARKER_FLOOR,
                                'the corpus no longer carries a scene whose '
                                'markers a removal would destroy')

    def test_a_declared_marker_survives_a_restoration(self) -> None:
        """The OPPOSITE failure, and it would be worse: a scene that DOES
        declare Editable Children, carrying the two degradations `pack()`
        applies — a ref that lost its uid, an override that lost its `index=`
        — must come back with both restored and its marker untouched, neither
        duplicated nor dropped. It keeps its own header uid so the run has
        nothing unresolved to report; that third loss is the case above."""
        marked = ('[gd_scene load_steps=2 format=3 uid="uid://dcanonmarked"]\n\n'
                  '[ext_resource type="PackedScene"'
                  ' path="res://scenes/panel.tscn" id="1_panel"]\n\n'
                  '[node name="Marked" type="Node2D"]\n\n'
                  '[node name="Panel" parent="."'
                  ' instance=ExtResource("1_panel")]\n\n'
                  '[node name="Footer" parent="Panel"]\nvisible = false\n\n'
                  '[editable path="Panel"]\n')
        with temp_repo('canon_repo') as root:
            (root / 'scenes/marked.tscn').write_text(marked, encoding='utf-8')
            code, out = canonicalize_in_repo('scenes/marked.tscn')
            text = (root / 'scenes/marked.tscn').read_text(encoding='utf-8')
        self.assertEqual(code, scene_canonicalize.EXIT_OK, out)
        self.assertIn('uid="uid://dcanonpanel"', text)   # it DID restore
        self.assertIn('index="1"', text)
        self.assertEqual(editable_paths(text), ['Panel'], text)


class NoMarkerIsInventedForAnOverriddenInstance(unittest.TestCase):
    def test_the_packed_fixture_gains_no_editable_section(self) -> None:
        """`canon_repo/scenes/packed.tscn` instances `panel.tscn` and overrides
        its `Footer` child. That is an override, not an editable instance, and
        Godot writes exactly this file without a marker."""
        with temp_repo('canon_repo') as root:
            code, out = canonicalize_in_repo('scenes/packed.tscn')
            text = (root / 'scenes/packed.tscn').read_text(encoding='utf-8')
        self.assertEqual(code, scene_canonicalize.EXIT_OK, out)
        self.assertIn('index="1"', text, 'the fixture stopped restoring at all')
        self.assertEqual(editable_paths(text), [], text)
        self.assertNotIn('EDITABLE', out, out)



if __name__ == '__main__':
    unittest.main()
