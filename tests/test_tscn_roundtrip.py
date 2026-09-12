"""Round-trip fidelity — the property every write verb rests on.

parse -> serialise with NO mutation must be byte-identical. If it is not, the
toolkit is more dangerous than `sed`, because it silently touches lines nobody
asked it to touch. Proven two ways here: against a hermetic fixture that
carries every awkward construct we have met in real files, and against the
committed corpus of scrubbed real-world scenes under tests/fixtures/corpus/.
Both run everywhere, including CI, and both are entirely inside this checkout:
a corpus that needs a particular repo cloned on a particular laptop proves
something different on every machine. Each fidelity case first proves its
subject's census (rule 4): a fidelity test over a fixture that exercises
nothing proves nothing.
"""
from __future__ import annotations

import re
import shutil
import tempfile
import unittest
from pathlib import Path

from support import FIXTURES

from godot_devkit.godot.format.tscn import parse_text
from godot_devkit.godot.format.tscn_document import TscnDocument
from godot_devkit.godot.index.gdscript import ScriptIndex
from godot_devkit.godot.index.resource_canonical import CanonicalAnalyzer
from godot_devkit.godot.write.scene_canonicalize import order_properties, respell_values

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
    def test_kitchen_sink_covers_the_awkward_constructs_and_is_byte_identical(self) -> None:
        path = FIXTURES / 'kitchen_sink.tscn'
        original = path.read_text(encoding='utf-8')
        for construct in AWKWARD_CONSTRUCTS:
            self.assertIn(construct, original)
        self.assertEqual(TscnDocument(original, path).text, original)

    def test_trailing_newline_and_crlf_survive(self) -> None:
        for text in ('[gd_scene format=3]\n', '[gd_scene format=3]',
                     '[gd_scene format=3]\r\n\r\n[node name="A" type="Node"]\r\n'):
            with self.subTest(text=repr(text)):
                self.assertEqual(TscnDocument(text).text, text)
        # The endings live in the line store, not the line contents — a CRLF
        # header parses to the same sections as its LF spelling.
        lf = '[node name="A" type="Node"]\nlayer = 16\n'
        self.assertEqual(parse_text(lf)[0].props,
                         TscnDocument(lf.replace('\n', '\r\n')).sections[0].props)


# The committed corpus: real-world scenes, VENDORED, in two slices that fail
# differently — `editor_written/` came out of Godot's own editor via
# ResourceSaver, `hand_authored/` was typed by hand and never round-tripped
# (every file in it carries a `;` comment the editor would have eaten). Paths
# and structure are intact, with game prose anonymized: prose-carrying property
# values (text/description/display_name/...) and comment bodies had each word
# replaced by a deterministic dictionary word; node names, types, keys, uids,
# paths and every byte of punctuation stayed. It is committed, so it runs
# everywhere, on CI too — and growing coverage means vendoring another scrubbed
# file here, never reaching for a tree outside this checkout (CLAUDE.md rule 8).
CORPUS = FIXTURES / 'corpus'

# Raising this floor is part of growing the corpus; a shrinking corpus must be
# a loud, deliberate edit here — never a silent glob over fewer files.
CORPUS_FLOOR = 66
# The corpus carries no scripts, so over it `--respell` can prove only what a
# constructor settles by itself (`Vector2(1.50, 2.0)`, `PackedFloat32Array`).
# The floor keeps that proof from going vacuous: lines it must re-spell.
RESPELL_LINES_FLOOR = 7

# What each slice of the corpus was SELECTED to exercise. A corpus that rots
# into vacuity (files deleted, constructs edited away) fails here, not by
# silently proving less. Every needle is a literal substring except the one
# regex, asserted to appear in at least one corpus file.
CORPUS_CONSTRUCTS = {
    'tile-heavy tile_map_data': 'tile_map_data = PackedByteArray(',
    'ShaderMaterial sub_resource': '[sub_resource type="ShaderMaterial"',
    'Animation sub_resource': '[sub_resource type="Animation"',
    'Curve sub_resource': '[sub_resource type="Curve"',
    'editable-children marker': '[editable path=',
    'instance-child index override': 'index="0"',
    'signal connection': '[connection signal=',
    'packed byte array': 'PackedByteArray(',
    'StringName with a space': '&"Dark Room"',
    'full-line comment': '\n;',
    'node_paths header declaration': 'node_paths=PackedStringArray',
    'escaped quote inside a string': '\\"',
    'multi-line dictionary value': '({\n',
    'typed array of ext_resources': 'Array[ExtResource(',
    'absolute NodePath value': 'NodePath("/root/',
    'metadata property': 'metadata/',
    'TileSet resource': '[gd_resource type="TileSet"',
    'AudioBusLayout resource': '[gd_resource type="AudioBusLayout"',
    'Theme resource': '[gd_resource type="Theme"',
    'SpriteFrames resource': '[gd_resource type="SpriteFrames"',
    'AnimationLibrary resource': '[gd_resource type="AnimationLibrary"',
    'Environment resource': '[gd_resource type="Environment"',
    'CanvasItemMaterial resource': '[gd_resource type="CanvasItemMaterial"',
    'GradientTexture2D resource': '[gd_resource type="GradientTexture2D"',
    'float with a trailing zero in a .tres': 'price = 12.50',
    'multi-line list of floats': 'ratios = [1, 0.250,\n0.5]',
    'bare list on a typed-array export': 'tags = [&"a", &"b"]',
    'inline comment after a float': 'weight = 0.30 ;',
}
INLINE_COMMENT_AFTER_VALUE = re.compile(r'^\w+ = .*\S ;', re.M)


def corpus_files() -> list[Path]:
    return sorted(p for p in CORPUS.rglob('*') if p.is_file())


class CommittedCorpusRoundTrip(unittest.TestCase):
    """Real-world structure, vendored: CI exercises scenes an engine and a
    human actually wrote, not only the hand-built kitchen_sink fixture."""

    def test_census_meets_the_floor_from_both_slices_and_covers_the_constructs(self) -> None:
        files = corpus_files()
        self.assertGreaterEqual(len(files), CORPUS_FLOOR,
                                'corpus shrank — a deleted file must lower the floor here, deliberately')
        for slice_name in ('editor_written', 'hand_authored'):
            self.assertTrue(
                any(f.is_relative_to(CORPUS / slice_name) for f in files),
                f'no corpus files under {slice_name}/ — the two halves fail '
                f'differently, and one of them just stopped being proven')
        texts = [p.read_text(encoding='utf-8') for p in files]
        missing = [name for name, needle in CORPUS_CONSTRUCTS.items()
                   if not any(needle in text for text in texts)]
        self.assertEqual(missing, [])
        self.assertTrue(any(INLINE_COMMENT_AFTER_VALUE.search(text) for text in texts),
                        'no corpus file carries an inline comment after a value')

    def test_every_corpus_file_round_trips_in_memory(self) -> None:
        # And survives `--respell --order`: same line count, no header or
        # comment line touched, and a second pass that changes nothing.
        canonical = CanonicalAnalyzer(ScriptIndex(CORPUS, []))
        respelled = 0
        for path in corpus_files():
            original = path.read_text(encoding='utf-8')
            if TscnDocument(original, path).text != original:
                self.fail(f'round trip changed {path.relative_to(CORPUS)}')
            doc = TscnDocument(original, path)
            respell_values(doc, canonical)
            order_properties(doc, canonical)
            before, after = original.split('\n'), doc.text.split('\n')
            self.assertEqual(len(before), len(after), path)
            changed = [line for line, new in zip(before, after) if line != new]
            self.assertEqual([line for line in changed if line.startswith((';', '['))], [])
            respelled += len(changed)
            again = TscnDocument(doc.text, path)
            respell_values(again, canonical)
            order_properties(again, canonical)
            self.assertEqual(again.text, doc.text, path)
        self.assertGreaterEqual(respelled, RESPELL_LINES_FLOOR)


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

    def test_a_mixed_endings_file_survives_load_save_and_an_in_place_edit(self) -> None:
        self._load(MIXED).save()
        self.assertEqual(self.path.read_bytes(), MIXED)
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
