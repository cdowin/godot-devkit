"""Round-trip fidelity — the property every write verb rests on.

parse -> serialise with NO mutation must be byte-identical. If it is not, the
toolkit is more dangerous than `sed`, because it silently touches lines nobody
asked it to touch. Proven twice: against a hermetic fixture that carries every
awkward construct we have met in real files, and against every .tscn/.tres in
whichever consumer checkouts are present.
"""
from __future__ import annotations

import unittest

from support import FIXTURES, available_consumers

from godot_devkit.tscn import parse_text
from godot_devkit.tscn_document import TscnDocument

# Every one of these appears in real consumer scenes and breaks a naive parser.
AWKWARD_CONSTRUCTS = (
    '&"Dark Room"',                       # StringName literal (godot-parser fails here)
    '; trailing comment',                 # inline comment after a value
    '{ "a": 1, "b": [2, 3] }',            # multi-line dictionary value
    'has a ; semicolon and a ( paren',    # comment/bracket chars inside a string
    'node_paths=PackedStringArray',       # exported NodePath declaration in a header
    'index="0"',                          # instance-child override
    '[editable path=',                    # editable-children marker
    '[connection ',                       # signal connection
    'tracks/0/path = NodePath(',           # an Animation track path in a sub_resource
    '&"pulse": SubResource(',              # StringName dictionary key, multi-line value
)


class RoundTripFidelity(unittest.TestCase):
    def test_kitchen_sink_fixture_is_byte_identical(self) -> None:
        path = FIXTURES / 'kitchen_sink.tscn'
        original = path.read_text(encoding='utf-8')
        self.assertEqual(TscnDocument(original, path).text, original)

    def test_fixture_actually_covers_the_awkward_constructs(self) -> None:
        """A fidelity test over a fixture that exercises nothing proves nothing."""
        text = (FIXTURES / 'kitchen_sink.tscn').read_text(encoding='utf-8')
        for construct in AWKWARD_CONSTRUCTS:
            self.assertIn(construct, text)

    def test_inline_comment_is_not_swallowed_into_the_value(self) -> None:
        sections = parse_text('[node name="A" type="Node"]\nlayer = 16 ; why\n')
        self.assertEqual(sections[0].props, [('layer', '16')])
        self.assertEqual(sections[0].entries[0].comment, '; why')

    def test_trailing_newline_and_crlf_survive(self) -> None:
        for text in ('[gd_scene format=3]\n', '[gd_scene format=3]',
                     '[gd_scene format=3]\r\n\r\n[node name="A" type="Node"]\r\n'):
            with self.subTest(text=repr(text)):
                self.assertEqual(TscnDocument(text).text, text)

    @unittest.skipUnless(available_consumers(), 'no consumer checkout available')
    def test_every_real_scene_round_trips(self) -> None:
        checked = 0
        for repo in available_consumers():
            for path in [*repo.rglob('*.tscn'), *repo.rglob('*.tres')]:
                if '/.git/' in str(path):
                    continue
                try:
                    original = path.read_text(encoding='utf-8')
                except (OSError, UnicodeDecodeError):
                    continue
                checked += 1
                if TscnDocument(original, path).text != original:
                    self.fail(f'round trip changed {path}')
        self.assertGreater(checked, 100, 'corpus too small to prove anything')


if __name__ == '__main__':
    unittest.main()
