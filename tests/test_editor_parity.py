"""Editor parity — `scene canonicalize --respell --order --elide-defaults` writes what the editor writes.

Each pair under `tests/fixtures/editor_parity/` is a hand-written file (`hand/`)
and the bytes a windowed Godot 4.7.2 editor wrote when it loaded and saved that
file (`editor/`), vendored once; nothing here boots Godot. A derivable gap must
come out byte-identical to the editor form, and `check canonical` must flag the
hand form and pass the editor form. A gap that needs engine data a parse cannot
see must come out UNRESOLVED, named, with the file otherwise untouched.
"""
from __future__ import annotations

import unittest
from collections import Counter

from support import FIXTURES

from godot_devkit.godot.checks import canonical
from godot_devkit.godot.format.tscn import parse
from godot_devkit.godot.index.gdscript import ScriptIndex
from godot_devkit.godot.index.resource_canonical import CanonicalAnalyzer
from godot_devkit.godot.index.resource_defaults import DefaultAnalyzer
from godot_devkit.godot.index.uid_index import UidIndex
from godot_devkit.godot.format.tscn_document import TscnDocument
from godot_devkit.godot.write.editor_layout import layout
from godot_devkit.godot.write.scene_canonicalize import BaseScenes, canonicalize, respell_values

ROOT = FIXTURES / 'editor_parity'
SCRIPTS = ['systems/base_item.gd', 'systems/item.gd', 'systems/tooled.gd',
           'systems/plain.gd', 'systems/holder.gd', 'systems/pointer.gd', 'systems/pair.gd']

# The gaps canonicalize closes: hand form -> editor form, byte for byte. Two
# editor forms are the editor's save of canonicalize's OUTPUT, because the
# editor's own value is not a fixed point: g10b/g10d (the editor mints a random
# unique_id but keeps any it reads) and g10c (a second save re-walks the
# now-sorted dictionary). There, equality proves an editor save is a no-op.
DERIVABLE = ('g10b_unique.tscn', 'g10d_attrs.tscn', 'g07_shader.tres', 'g07b_shader_types.tres',
             'g01_order.tres', 'g02_ext.tres', 'g04_class.tres', 'g04b_noclass.tres',
             'g05_array.tres', 'g08_frames.tres', 'g09_dict.tres', 'g10_scene.tscn',
             'g10c_dict_first_use.tres', 'g06_gradient.tres', 'g11_sub_by_name.tres',
             'g12_ext_named.tres')
ELIDED = ('g06_gradient.tres',)


def run(name: str) -> tuple[str, list[str]]:
    scripts = ScriptIndex(ROOT, SCRIPTS)
    return canonicalize(ROOT / 'hand' / name, ROOT, UidIndex(ROOT), BaseScenes(ROOT),
                        DefaultAnalyzer(scripts), CanonicalAnalyzer(scripts),
                        respell=True, order=True)


def drift(folder: str, name: str) -> list[str]:
    analyzer = CanonicalAnalyzer(ScriptIndex(ROOT, SCRIPTS))
    return canonical.findings_of(ROOT, f'{folder}/{name}', analyzer, Counter())


def redundant(folder: str, name: str) -> list:
    analyzer = DefaultAnalyzer(ScriptIndex(ROOT, SCRIPTS))
    return analyzer.analyze(parse(str(ROOT / folder / name)), Counter())


def editor_bytes(name: str) -> str:
    return (ROOT / 'editor' / name).read_text(encoding='utf-8')


class UnderivableGapsAreNamed(unittest.TestCase):
    def test_a_tool_default_is_unresolved_and_the_file_is_untouched(self) -> None:
        # Gap 3: the editor adds an ext_resource under an id it generates at random.
        name = 'g03_tool.tres'
        text, report = run(name)
        self.assertEqual(text, (ROOT / 'hand' / name).read_text(encoding='utf-8'))
        self.assertNotEqual(text, editor_bytes(name))
        unresolved = [line for line in report if 'UNRESOLVED' in line]
        self.assertEqual(len(unresolved), 1, report)
        self.assertIn('@tool default res://art/d.tres', unresolved[0])


HEAD = '[gd_resource type="Resource" format=3]\n\n'
HEAD_ITEM = '[gd_resource type="Resource" script_class="Item" format=3]\n\n'
ITEM = '[ext_resource type="Script" path="res://systems/item.gd" id="1_item"]\n'
MATERIAL = ('[gd_resource type="ShaderMaterial" format=3]\n\n'
            '[ext_resource type="Shader" path="res://art/{shader}" id="1"]\n\n'
            '[resource]\nshader = ExtResource("1")\n{extra}')
# Each input the editor WOULD rewrite but the tool cannot prove: (text, reason).
REFUSED = {
    'StringName and int keys': (
        HEAD_ITEM + ITEM + '\n[resource]\nscript = ExtResource("1_item")\n'
        'table = {&"b": 1, 2: 3}\n', 'mixes StringName and int'),
    'uneven separators': (
        HEAD_ITEM + ITEM + '\n[resource]\nscript = ExtResource("1_item")\n'
        'table = {"b": 1, "a": 2,\n"c": 3}\n', 'not separated the same way'),
    'comment in the ext block': (
        HEAD + '[ext_resource type="Texture2D" path="res://art/b.tres" id="2"]\n'
        '; why\n[ext_resource type="Texture2D" path="res://art/a.tres" id="1"]\n',
        'ext_resource block holds a comment'),
    'unreferenced sub_resource': (
        HEAD + '[sub_resource type="Resource" id="b"]\n\n[sub_resource type="Resource" id="a"]'
        '\n\n[resource]\nnext = SubResource("a")\n', 'referenced by nothing'),
    'engine property on a material': (MATERIAL.format(shader='tint.gdshader', extra='next_pass = null\n'),
                      'other than shader'),
}


class UnprovableEditsAreRefusedNotGuessed(unittest.TestCase):
    def test_each_refusal_names_its_reason_and_changes_nothing(self) -> None:
        scripts = ScriptIndex(ROOT, SCRIPTS)
        for case, (text, reason) in REFUSED.items():
            with self.subTest(case):
                doc = TscnDocument(text)
                report = respell_values(doc, CanonicalAnalyzer(scripts))
                report += layout(doc, scripts, ROOT)
                unresolved = [line for line in report if 'UNRESOLVED' in line]
                self.assertTrue(any(reason in line for line in unresolved), report)
                self.assertEqual(doc.text, text)


class DerivableGapsMatchTheEditor(unittest.TestCase):
    def test_hand_form_canonicalizes_to_the_editor_bytes(self) -> None:
        for name in DERIVABLE:
            with self.subTest(name):
                text, report = run(name)
                self.assertEqual(text, editor_bytes(name))
                self.assertFalse([line for line in report if 'UNRESOLVED' in line])

    def test_the_editor_form_is_a_fixed_point(self) -> None:
        scripts = ScriptIndex(ROOT, SCRIPTS)
        for name in DERIVABLE:
            with self.subTest(name):
                text, _ = canonicalize(ROOT / 'editor' / name, ROOT, UidIndex(ROOT),
                                       BaseScenes(ROOT), DefaultAnalyzer(scripts),
                                       CanonicalAnalyzer(scripts), respell=True, order=True)
                self.assertEqual(text, editor_bytes(name))

    def test_the_gates_flag_the_hand_form_and_pass_the_editor_form(self) -> None:
        # `check canonical` owns spelling, order and layout; `check defaults`
        # owns elision (gap 6). A .tscn is in neither gate's census.
        for name in DERIVABLE:
            if not name.endswith('.tres'):
                continue
            with self.subTest(name):
                gate = redundant if name in ELIDED else drift
                self.assertTrue(gate('hand', name))
                self.assertEqual(drift('editor', name), [])
                self.assertEqual(redundant('editor', name), [])


if __name__ == '__main__':
    unittest.main()
