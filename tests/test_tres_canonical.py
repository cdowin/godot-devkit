"""`.tres` spelling and order — `check canonical` and `scene canonicalize --respell --order`.

The two dimensions of editor-save churn `check defaults` leaves out. The bar is
the fixer's: every edit is a LINE edit a reviewer can read — a token re-spelled
inside the line it sat on, a property line moved whole — with comments, `uid=`
and every untouched byte surviving, anything unprovable named and left alone,
and the second run a no-op. Proven by function call on the committed fixture
(`tests/fixtures/canonical_repo/`), never a temp tree: nothing here needs git.
Corpus-scale fidelity rides on the round-trip harness in `test_tscn_roundtrip`.
"""
from __future__ import annotations

import contextlib
import io
import unittest

from support import FIXTURES

from godot_devkit import cli
from godot_devkit.godot.checks import canonical
from godot_devkit.godot.format.tscn_document import TscnDocument
from godot_devkit.godot.format.value_spelling import (
    COMPONENT_CONTEXT,
    FLOAT_CONTEXT,
    OPAQUE_CONTEXT,
    VARIANT_CONTEXT,
    apply_edits,
    respell,
    scan_value,
)
from godot_devkit.godot.index.gdscript import ScriptIndex
from godot_devkit.godot.index.resource_canonical import CanonicalAnalyzer
from godot_devkit.godot.write.scene_canonicalize import order_properties, respell_values

ROOT = FIXTURES / 'canonical_repo'
SCRIPTS = ['systems/item.gd', 'systems/base_item.gd']
DRIFTED = 'data/drifted.tres'
CLEAN = 'data/clean.tres'

# The drifted fixture after `--respell --order`: every changed line, keyed by
# the line it replaces. Anything not here must come through byte-identical.
EXPECTED_CHANGES = {
    'price = 2.50': 'weight = 3.0',             # Child: moved, and re-spelled
    'weight = 3.0': 'price = 2.5',
    'offsets = PackedFloat32Array(0.0, 0.50, 1)': 'offsets = PackedFloat32Array(0, 0.5, 1)',
    'colors = PackedColorArray(1, 1, 1, 1.0, 0, 0, 0, 1)':
        'colors = PackedColorArray(1, 1, 1, 1, 0, 0, 0, 1)',
    'weight = 0.30 ; the inline comment rides along with its value':
        'weight = 0.3 ; the inline comment rides along with its value',
    'tags = [&"a", &"b"]': 'tags = Array[StringName]([&"a", &"b"])',
    'price = 12.50': 'price = 12.5',
    'scale = Vector2(1.50, 2.0)': 'scale = Vector2(1.5, 2)',
    'ratios = [1, 0.250,': 'ratios = Array[float]([1.0, 0.25,',
    '0.5]': '0.5])',
    'children = [SubResource("Child"), null]':
        'children = Array[ExtResource("1_item")]([SubResource("Child"), null])',
    'icons = []': 'icons = Array[Texture2D]([])',
    'notes = [0.10, "x;y", {"k": 2.50}]': 'notes = [0.1, "x;y", {"k": 2.5}]',
}
# The same drift as the gate counts it: properties, not lines (`ratios` spans
# two; Child's `weight` only moved), plus each of Child's two misplaced lines.
RESPELLED_PROPERTIES = 11
OUT_OF_PLACE = 2
# Named, not guessed: each for a different reason the saver's output is unknowable.
EXPECTED_REFUSALS = ('[resource].modes: element type Mode',
                     '[resource].guarded: export has a setter/getter',
                     '[sub_resource id="Commented"]: section order drifts but a comment')


def analyzer() -> CanonicalAnalyzer:
    return CanonicalAnalyzer(ScriptIndex(ROOT, SCRIPTS))


def both_passes(text: str) -> tuple[str, list[str]]:
    doc = TscnDocument(text)
    report = respell_values(doc, analyzer())
    report += order_properties(doc, analyzer())
    return doc.text, report


class FloatSpelling(unittest.TestCase):
    def test_the_shortest_spelling_per_context_and_a_refusal_for_every_unprovable_one(
            self) -> None:
        # (value, context) -> the saver's text, or None where the tool must refuse.
        cases = {
            ('0.30', VARIANT_CONTEXT): '0.3', ('1.0', VARIANT_CONTEXT): '1.0',
            ('1.0', COMPONENT_CONTEXT): '1', ('-0.0', COMPONENT_CONTEXT): '0',
            ('2', FLOAT_CONTEXT): '2.0', ('2', VARIANT_CONTEXT): '2',
            ('6.2831855', VARIANT_CONTEXT): '6.2831855',   # corpus: TAU as a float32
            ('.5', COMPONENT_CONTEXT): '0.5',
            # 32- and 64-bit shortest forms disagree: build-dependent, refused.
            ('0.1234567890', VARIANT_CONTEXT): None,
            ('0.00001', VARIANT_CONTEXT): None,             # exponent range
            ('0.30', OPAQUE_CONTEXT): None,                 # type unknowable
        }
        for (token, context), wanted in cases.items():
            with self.subTest(token=token, context=context):
                text = f'x = {token}'
                tokens, _ = scan_value(text, 2)
                result = respell(tokens, text, context, OPAQUE_CONTEXT)
                if wanted is None:
                    self.assertEqual((result.edits, result.refused), ([], [token]))
                else:
                    self.assertEqual(apply_edits(text, result.edits), f'x = {wanted}')
                    self.assertEqual(result.refused, [])


class RespellAndOrder(unittest.TestCase):
    def test_exactly_the_provable_lines_change_the_rest_is_named_and_a_rerun_is_a_no_op(
            self) -> None:
        before = (ROOT / DRIFTED).read_text(encoding='utf-8')
        after, report = both_passes(before)
        old, new = before.split('\n'), after.split('\n')
        self.assertEqual(len(old), len(new))
        changed = {a: b for a, b in zip(old, new) if a != b}
        self.assertEqual(changed, EXPECTED_CHANGES)
        # Rule 3: comments, headers and every uid= are byte-identical.
        for line in old:
            if line.startswith((';', '[')):
                self.assertIn(line, new, line)
        unresolved = [line for line in report if 'UNRESOLVED' in line]
        self.assertEqual(len(unresolved), len(EXPECTED_REFUSALS), report)
        for needle in EXPECTED_REFUSALS:
            self.assertTrue(any(needle in line for line in unresolved), needle)
        self.assertIn('guarded = 1.50', after)
        self.assertIn('modes = [0, 1]', after)
        again, again_report = both_passes(after)
        self.assertEqual(again, after)
        self.assertEqual([line for line in again_report if 'UNRESOLVED' not in line], [])

    def test_a_reorder_moves_whole_property_lines_and_keeps_every_ending(self) -> None:
        # A multi-line value and an inline comment move WITH their property,
        # and the CRLF endings stay where they were.
        text = ('[gd_resource type="Resource" format=3]\r\n\r\n'
                '[ext_resource type="Script" path="res://systems/item.gd" id="1"]\r\n\r\n'
                '[resource]\r\n'
                'script = ExtResource("1")\r\n'
                'price = 2.0 ; kept\r\n'
                'ratios = Array[float]([1.0,\r\n'
                '2.0])\r\n'
                'weight = 3.0\r\n')
        after, report = both_passes(text)
        self.assertEqual(after, text.replace(
            'price = 2.0 ; kept\r\nratios = Array[float]([1.0,\r\n2.0])\r\nweight = 3.0\r\n',
            'weight = 3.0\r\nprice = 2.0 ; kept\r\nratios = Array[float]([1.0,\r\n2.0])\r\n'))
        self.assertEqual(report, ['  ORDER  [resource]: 3 of 4 properties moved to '
                                  'declaration order'])


class Gate(unittest.TestCase):
    def run_report(self, files: list[str]) -> tuple[int, str]:
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = canonical.report(ROOT, files, analyzer())
        return code, buffer.getvalue()

    def test_names_every_drift_passes_the_clean_file_and_fails_an_empty_census(self) -> None:
        code, out = self.run_report([DRIFTED, CLEAN])
        self.assertEqual(code, canonical.EXIT_FINDINGS, out)
        drift = [line for line in out.split('\n') if line.startswith('  DRIFT  ')]
        # One line per re-spelled property, one per property out of place.
        self.assertEqual(len(drift), RESPELLED_PROPERTIES + OUT_OF_PLACE, out)
        self.assertIn('[sub_resource id="Child"].weight — the saver writes it at '
                      'position 2 of 3', out)
        self.assertIn('in 1 of 2 .tres file(s)', out)
        code, out = self.run_report([CLEAN])
        self.assertEqual(code, canonical.EXIT_OK, out)
        self.assertIn('[check:canonical] PASS', out)
        code, out = self.run_report([])
        self.assertEqual(code, canonical.EXIT_FINDINGS, out)
        self.assertIn('scanned 0 files', out)
        # Opt-in: dispatchable and nameable, never in the stock `check all`.
        self.assertNotIn('canonical', cli.KNOWN_GATES)
        self.assertIs(cli._check_module('canonical'), canonical)


if __name__ == '__main__':
    unittest.main()
