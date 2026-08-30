"""Round-trip fidelity — the property every write verb rests on.

parse -> serialise with NO mutation must be byte-identical. If it is not, the
toolkit is more dangerous than `sed`, because it silently touches lines nobody
asked it to touch. Proven twice: against a hermetic fixture that carries every
awkward construct we have met in real files, and against every .tscn/.tres in
whichever consumer checkouts are present.
"""
from __future__ import annotations

import ast
import shutil
import tempfile
import unittest
from pathlib import Path

from support import FIXTURES, REPO_ROOT, available_consumers

from godot_devkit.godot.format.tscn import parse_text
from godot_devkit.godot.format.tscn_document import TscnDocument

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

    def test_parse_is_unfazed_by_crlf(self) -> None:
        """The endings live in the line store, not the line contents — a CRLF
        header must parse to the same sections as its LF spelling."""
        lf = '[node name="A" type="Node"]\nlayer = 16\n'
        crlf = lf.replace('\n', '\r\n')
        self.assertEqual(parse_text(lf)[0].props,
                         TscnDocument(crlf).sections[0].props)

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


MIXED = (b'[gd_scene format=3]\r\n'
         b'\n'
         b'[node name="A" type="Node"]\n'
         b'x = 1\r\n'
         b'\r\n'
         b'[node name="B" type="Node" parent="."]\r'
         b'y = 2\n')


class LoadSaveNewlineFidelity(unittest.TestCase):
    """The in-memory round trip above once proved nothing about files:
    `load()` translated every ending to `\\n` and `save()` wrote `os.linesep`,
    so every write verb silently normalized whole files. These pin the
    LOAD/SAVE path on real bytes — including the mixed-endings policy: an
    untouched line keeps its exact ending, an in-place rewrite keeps the
    line's ending, an inserted line gets the file's dominant ending."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        self.path = self.tmp / 'scene.tscn'

    def _load(self, raw: bytes) -> TscnDocument:
        self.path.write_bytes(raw)
        return TscnDocument.load(self.path)

    def test_a_crlf_file_survives_load_save_byte_for_byte(self) -> None:
        raw = (FIXTURES / 'kitchen_sink.tscn').read_text(
            encoding='utf-8').replace('\n', '\r\n').encode()
        self._load(raw).save()
        self.assertEqual(self.path.read_bytes(), raw)

    def test_a_mixed_endings_file_survives_load_save_byte_for_byte(self) -> None:
        self._load(MIXED).save()
        self.assertEqual(self.path.read_bytes(), MIXED)

    def test_an_in_place_edit_keeps_every_lines_own_ending(self) -> None:
        doc = self._load(MIXED)
        doc.set_prop('.', 'x', '2')                  # a CRLF-terminated line
        doc.save()
        self.assertEqual(self.path.read_bytes(), MIXED.replace(b'x = 1\r\n', b'x = 2\r\n'))

    def test_an_inserted_line_gets_the_dominant_ending(self) -> None:
        raw = (b'[gd_scene format=3]\r\n\r\n'
               b'[node name="A" type="Node"]\r\n'
               b'x = 1\n')                           # one deviant LF line
        doc = self._load(raw)
        doc.set_prop('.', 'fresh', '9')
        doc.save()
        out = self.path.read_bytes()
        self.assertIn(b'fresh = 9\r\n', out)         # newcomer takes the majority ending
        self.assertIn(b'x = 1\n', out)
        self.assertNotIn(b'x = 1\r\n', out)          # the deviant line stays deviant


class FormatLayerStaysAtTheBottom(unittest.TestCase):
    """`format/` is the floor of `godot/` — importing `index/`, `read/`,
    `write/` or `checks/` from it is the layering running backwards. The one
    upward edge there ever was (`_uid_of` importing `uid_index`) is now an
    injected resolver; this keeps the direction from recurring."""

    FORMAT_DIR = REPO_ROOT / 'src' / 'godot_devkit' / 'godot' / 'format'
    UPWARD = ('godot_devkit.godot.index', 'godot_devkit.godot.read',
              'godot_devkit.godot.write', 'godot_devkit.godot.checks')

    def test_format_imports_nothing_from_the_layers_above(self) -> None:
        files = sorted(self.FORMAT_DIR.glob('*.py'))
        self.assertGreater(len(files), 3, 'census too small — wrong directory?')
        offenders: list[str] = []
        for path in files:
            tree = ast.parse(path.read_text(encoding='utf-8'), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    names = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom) and node.module:
                    names = [node.module]
                else:
                    continue
                offenders.extend(f'{path.name}:{node.lineno}: {name}'
                                 for name in names if name.startswith(self.UPWARD))
        self.assertEqual(offenders, [])


if __name__ == '__main__':
    unittest.main()
