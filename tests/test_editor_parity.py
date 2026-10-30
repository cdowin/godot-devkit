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
from godot_devkit.godot.write.scene_canonicalize import BaseScenes, canonicalize

ROOT = FIXTURES / 'editor_parity'
SCRIPTS = ['systems/base_item.gd', 'systems/item.gd', 'systems/tooled.gd',
           'systems/plain.gd', 'systems/holder.gd', 'systems/pointer.gd']

# The gaps canonicalize closes: hand form -> editor form, byte for byte. Two
# editor forms are the editor's save of canonicalize's OUTPUT, because the
# editor's own value is not a fixed point: g10b/g10d (the editor mints a random
# unique_id but keeps any it reads) and g10c (a second save re-walks the
# now-sorted dictionary). There, equality proves an editor save is a no-op.
DERIVABLE = ('g10b_unique.tscn', 'g10d_attrs.tscn', 'g01_order.tres', 'g02_ext.tres', 'g04_class.tres', 'g04b_noclass.tres',
             'g05_array.tres', 'g08_frames.tres', 'g09_dict.tres', 'g10_scene.tscn',
             'g10c_dict_first_use.tres', 'g06_gradient.tres')
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
