"""Tier 2 — the `tiles` read verb: decode a TileMapLayer without guessing.

The DECODER is exact (a hand-built byte vector decodes to known cells, and
each corrupt shape is refused), and the READ side answers without guessing (an
undecodable layer is reported, an ambiguous layer name is refused).
"""
from __future__ import annotations

import base64
import contextlib
import io
import shutil
import struct
import sys
import tempfile
import unittest.mock
from pathlib import Path

from support import FIXTURES

from godot_devkit.godot.format import tilemap, tscn
from godot_devkit.godot.read import tiles

SCENE = FIXTURES / 'tilemap.tscn'
FLOOR = 'FloorLayer'
EMPTY = 'EmptyLayer'
NESTED_WALL = 'Nested/WallLayer'


class Codec(unittest.TestCase):
    """The 12-byte cell layout, proven against bytes built by hand. Alongside
    it, the argument grammar and the layer lookup."""

    def test_decodes_hand_built_bytes(self) -> None:
        raw = struct.pack('<HhhHHHH', 0, -3, 7, 2, 1, 4, 1)   # version, x, y, then the tile
        value = f'PackedByteArray("{base64.b64encode(raw).decode()}")'
        data = tilemap.decode(value)
        self.assertEqual((data.version, data.cells), (0, {(-3, 7): tilemap.Tile(2, 1, 4, 1)}))

    def test_refuses_each_corrupt_shape_rather_than_half_reading(self) -> None:
        for value in ('PackedInt32Array(1, 2)',          # not a PackedByteArray
                      'PackedByteArray("AAAAA")',        # not base64
                      'PackedByteArray("AAAAAAAAAA==")'):  # 7 bytes: a header plus 5, not cells
            with self.subTest(value=value), self.assertRaises(tilemap.TileMapError):
                tilemap.decode(value)

    def test_the_command_line_grammar_refuses_what_it_would_have_to_guess_at(self) -> None:
        self.assertEqual(tilemap.parse_region('3,4,1,2'), tilemap.Region(1, 2, 3, 4))
        for parse_spec, spec in (
                (tilemap.parse_region, '0,0,1'),       # wrong arity
                (tilemap.parse_region, '-30000,-30000,30000,30000'),  # too large
                (tilemap.parse_coord, 'left')):        # wrong arity
            with self.subTest(spec=spec), self.assertRaises(tilemap.TileMapError):
                parse_spec(spec)

    def test_glues_only_a_value_that_opens_negative(self) -> None:
        # argparse fixed `_negative_number_matcher` in 3.14, so the end-to-end
        # cases below only fail on 3.11/3.12/3.13. This pins the rewrite rule
        # itself, version-independently: what gets glued, and what must not.
        for argv, want in (
                (['--region', '-2,-2,1,1'], ['--region=-2,-2,1,1']),
                (['--at', '-1,-1'], ['--at=-1,-1']),
                # Already unambiguous, or not a value argparse chokes on.
                (['--region', '0,0,1,1'], ['--region', '0,0,1,1']),
                (['--region=-2,-2,1,1'], ['--region=-2,-2,1,1']),
                # A flag where a value belongs stays the usage error it is.
                (['--region', '--tile', '9/0,0'], ['--region', '--tile', '9/0,0']),
                # Not one of the signed-value flags, and not a value at all.
                (['--layer', '-Floor'], ['--layer', '-Floor']),
                (['--region'], ['--region']),
                # `--` ends option parsing; nothing after it is rewritten.
                (['--', '--region', '-1,-1,0,0'], ['--', '--region', '-1,-1,0,0'])):
            with self.subTest(argv=argv):
                self.assertEqual(tilemap.glue_signed_values(argv), want)

    def test_the_layer_lookup_finds_by_path_and_refuses_rather_than_picking(self) -> None:
        sections = tscn.parse(str(SCENE))
        self.assertEqual(tscn.find_tilemap_layer(sections, NESTED_WALL).attrs['parent'],
                         'Nested')
        for name in ('Nope', 'WallLayer'):   # unknown; two layers answer to it
            with self.subTest(name=name), self.assertRaises(tscn.TscnError):
                tscn.find_tilemap_layer(sections, name)


# Every case runs a verb in-process against its own copy of the fixture.
class Case(unittest.TestCase):

    def setUp(self) -> None:
        self.scene = Path(self.enterContext(tempfile.TemporaryDirectory())) / 'scene.tscn'
        shutil.copy2(SCENE, self.scene)
        self.path = str(self.scene)

    def verb(self, main, argv: list[str] | None) -> int:
        self.output = io.StringIO()
        with contextlib.redirect_stdout(self.output):
            return main(argv)


class Read(Case):
    def test_reports_count_bounds_kinds_and_the_edges(self) -> None:
        # Per-column counts are how an author finds where a wall stops without
        # reading a single byte of base64.
        self.verb(tiles.main, [self.path, '--layer', FLOOR, '--cols', '--rows'])
        self.assertIn('12 cells, x[-2..3] y[0..5]', self.output.getvalue())
        self.assertIn('kinds (3):', self.output.getvalue())
        self.assertIn('src=1 atlas=(0,0) alt=0   10', self.output.getvalue())
        self.assertIn('columns (5):', self.output.getvalue())
        self.assertIn('x=-2   1', self.output.getvalue())
        self.assertIn('rows (4):', self.output.getvalue())
        self.assertIn('y=5   1', self.output.getvalue())

    def test_every_layer_when_no_layer_is_named_and_at_names_a_hole(self) -> None:
        self.verb(tiles.main, [self.path, '--at', '2,1'])
        for path in (FLOOR, NESTED_WALL, 'Deep/WallLayer', EMPTY):
            self.assertIn(f'({path})', self.output.getvalue())
        self.assertIn('0 cells', self.output.getvalue())   # the never-painted layer
        self.assertIn('(2,1)  empty', self.output.getvalue())

    def test_the_negative_quadrant_is_addressable_from_the_real_argv(self) -> None:
        # The glue was once applied only to an INJECTED argv, so every test
        # passed while `python -m godot_devkit.godot.read.tiles … --at -3,-3`
        # still exited 2 on 3.11 and worked on 3.14 — the version-dependent
        # tool the glue exists to not be. So: `sys.argv`.
        with unittest.mock.patch.object(sys, 'argv', ['tiles', self.path, '--layer', FLOOR,
                                                      '--at', '-2,5']):
            self.assertEqual(self.verb(tiles.main, None), 0)   # `None`: read sys.argv
        self.assertIn('(-2,5)  src=1 atlas=(0,0) alt=0', self.output.getvalue())

    def test_refuses_a_malformed_region_before_printing_anything(self) -> None:
        # A refusal that has already printed half a census is a lie about how
        # far the tool got, so every argument is parsed before the first line.
        self.assertEqual(self.verb(tiles.main, [self.path, '--layer', FLOOR, '--region', '0,0,1']),
                         tiles.EXIT_REFUSED)
        self.assertNotIn('cells', self.output.getvalue())
