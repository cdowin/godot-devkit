"""Tier 2 — the `tiles` family: decode a TileMapLayer, and paint one.

Three properties carry the feature and each has its own case. The CODEC is
exact (a hand-built byte vector decodes to known cells, and re-encodes to the
same bytes), the READ side answers without guessing (an undecodable layer is
reported, an ambiguous layer name is refused), and the WRITE side is surgical:
only the one `tile_map_data` assignment changes, the file's other bytes —
including that line's own trailing comment — survive, and a paint that changes
no cell writes nothing.

Altitude: the layer lookup (`tscn.find_tilemap_layer`) and the argument grammar
(`tilemap.parse_tile` & co) are ONE function each, shared by the read verb and
the write verb, so their refusals are proven at function altitude once; each
verb keeps a single process-level refusal to prove it catches and reports.
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

from godot_devkit.godot.format import tilemap, tscn, tscn_document
from godot_devkit.godot.read import tiles
from godot_devkit.godot.write import tiles_paint

SCENE = FIXTURES / 'tilemap.tscn'
FLOOR = 'FloorLayer'
EMPTY = 'EmptyLayer'
NESTED_WALL = 'Nested/WallLayer'


class Codec(unittest.TestCase):
    """The 12-byte cell layout, proven against bytes built by hand — not against
    this module's own encoder, which would agree with itself while both drift.
    Alongside it, the two functions both verbs share: the argument grammar and
    the layer lookup."""

    def test_round_trips_hand_built_bytes(self) -> None:
        raw = struct.pack('<HhhHHHH', 0, -3, 7, 2, 1, 4, 1)   # version, x, y, then the tile
        value = f'PackedByteArray("{base64.b64encode(raw).decode()}")'
        data = tilemap.decode(value)
        self.assertEqual((data.version, data.cells), (0, {(-3, 7): tilemap.Tile(2, 1, 4, 1)}))
        self.assertEqual(tilemap.encode(data), value)

    def test_refuses_each_corrupt_shape_rather_than_half_reading(self) -> None:
        for value in ('PackedInt32Array(1, 2)',          # not a PackedByteArray
                      'PackedByteArray("AAAAA")',        # not base64
                      'PackedByteArray("AAAAAAAAAA==")'):  # 7 bytes: a header plus 5, not cells
            with self.subTest(value=value), self.assertRaises(tilemap.TileMapError):
                tilemap.decode(value)
        with self.assertRaises(tilemap.TileMapError):   # a cell the format cannot carry
            tilemap.encode(tilemap.TileMapData(0, {(40000, 0): tilemap.Tile(1, 0, 0, 0)}))

    def test_the_command_line_grammar_refuses_what_it_would_have_to_guess_at(self) -> None:
        self.assertEqual(tilemap.parse_region('3,4,1,2'), tilemap.Region(1, 2, 3, 4))
        for parse_spec, spec in (
                (tilemap.parse_tile, '1'),             # too few fields
                (tilemap.parse_tile, '1/0'),           # atlas coord is not AX,AY
                (tilemap.parse_tile, 'a/0,0'),         # not an integer
                (tilemap.parse_tile, '99999/0,0'),     # a field the format cannot carry
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
        self.before = self.text()

    def text(self) -> str:
        return self.scene.read_text(encoding='utf-8')

    def verb(self, main, argv: list[str] | None) -> int:
        self.output = io.StringIO()
        with contextlib.redirect_stdout(self.output):
            return main(argv)

    def cells(self, layer: str) -> dict:
        prop = tscn.find_tilemap_layer(tscn.parse(self.path), layer).prop(tscn.TILE_MAP_DATA_PROP)
        return tilemap.decode_or_empty(prop.value if prop is not None else None).cells


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


class Paint(Case):
    def test_fills_a_never_painted_layer_by_adding_the_property(self) -> None:
        # A region in the upper-left quadrant on purpose: `CELL_STRUCT` signs x
        # and y, and argparse before 3.14 excuses a leading `-` only for a BARE
        # number, so `--region -1,-1,1,0` died with `expected one argument` on
        # 3.11/3.12/3.13 — every Python a consumer's `uvx` selects today.
        self.assertEqual(self.verb(tiles_paint.main, ['paint', self.path, '--layer', EMPTY,
                                                     '--region', '-1,-1,1,0', '--tile', '4/1,2/3']),
                         tiles_paint.EXIT_OK, self.output.getvalue())
        self.assertEqual(self.cells(EMPTY), {(x, y): tilemap.Tile(4, 1, 2, 3)
                                             for y in (-1, 0) for x in (-1, 0, 1)})
        self.assertIn('6 added, 0 replaced, 0 erased', self.output.getvalue())

    def test_counts_added_and_replaced_separately(self) -> None:
        """(2,1) is a hole in the fixture slab — filling it is an ADD inside a
        region that otherwise replaces, and conflating the two hides that."""
        self.verb(tiles_paint.main, ['paint', self.path, '--layer', FLOOR,
                                    '--region', '2,1,3,1', '--tile', '5/0,0'])
        self.assertIn('1 added, 1 replaced, 0 erased', self.output.getvalue())

    def test_erase_deletes_only_the_region_and_reports_the_new_bounds(self) -> None:
        self.verb(tiles_paint.main, ['erase', self.path, '--layer', FLOOR, '--region', '0,0,3,2'])
        self.assertEqual(self.cells(FLOOR), {(-2, 5): tilemap.Tile(1, 0, 0, 0)})
        self.assertIn('0 added, 0 replaced, 11 erased', self.output.getvalue())
        self.assertIn('layer now 1 cells, x[-2..-2] y[5..5]', self.output.getvalue())

    def test_replaces_only_the_region_and_touches_only_that_one_line(self) -> None:
        argv = ['paint', self.path, '--layer', FLOOR, '--region', '0,0,1,1', '--tile', '9/0,0']
        self.verb(tiles_paint.main, argv + ['--dry-run'])   # shows the diff, writes nothing
        self.assertIn('--- a/scene.tscn', self.output.getvalue())
        self.assertEqual(self.text(), self.before)
        self.verb(tiles_paint.main, argv)
        cells = self.cells(FLOOR)
        self.assertEqual((cells[(0, 0)], cells[(-2, 5)]),   # inside replaced, outside untouched
                         (tilemap.Tile(9, 0, 0, 0), tilemap.Tile(1, 0, 0, 0)))
        after = self.text()
        changed = [a for a, b in zip(after.splitlines(), self.before.splitlines()) if a != b]
        self.assertEqual(len(changed), 1, changed)   # the other layers' bytes are untouched
        self.assertTrue(changed[0].startswith(tscn.TILE_MAP_DATA_PROP + ' ='), changed)
        self.assertIn('") ; the grid, in one line', changed[0])   # the line's own comment
        # And the file still parses and re-serialises byte-for-byte — the
        # invariant every write verb rests on.
        self.assertEqual(tscn_document.TscnDocument(after, self.scene).text, after)

    def test_the_same_paint_twice_writes_nothing_the_second_time(self) -> None:
        argv = ['paint', self.path, '--layer', FLOOR, '--region', '0,0,4,4', '--tile', '9/0,0']
        self.verb(tiles_paint.main, argv)
        once = self.text()
        self.assertEqual(self.verb(tiles_paint.main, argv), tiles_paint.EXIT_OK)
        self.assertIn(tiles_paint.UNCHANGED, self.output.getvalue())
        self.assertEqual(self.text(), once)

    def test_a_refusal_is_reported_and_writes_nothing(self) -> None:
        # The lookup's own branches are `Codec`'s; this is the verb catching
        # one and reporting it instead of picking a layer.
        self.assertEqual(self.verb(tiles_paint.main, ['paint', self.path, '--layer', 'WallLayer',
                                                     '--region', '0,0,1,1', '--tile', '1/0,0']),
                         tiles_paint.EXIT_REFUSED)
        self.assertIn('ambiguous', self.output.getvalue())
        self.assertEqual(self.text(), self.before)

    def test_an_undecodable_layer_is_reported_by_the_read_and_refused_by_the_write(self) -> None:
        # Rule 4's two sins at once: rendering a layer the codec cannot read as
        # "0 cells" is the read-side lie, and re-encoding a partial read would
        # silently delete the tail of the map. The nested wall's one cell,
        # truncated to no longer be whole cells:
        self.scene.write_text(self.before.replace('PackedByteArray("AAAAAAAAAwAAAAAAAAA=")',
                                                  'PackedByteArray("AAAAAAAA")'), encoding='utf-8')
        self.before = self.text()
        self.assertEqual(self.verb(tiles.main, [self.path, '--layer', NESTED_WALL]), tiles.EXIT_OK)
        self.assertIn('UNREADABLE', self.output.getvalue())
        self.assertNotIn('0 cells', self.output.getvalue())
        self.assertEqual(self.verb(tiles_paint.main, ['paint', self.path, '--layer', NESTED_WALL,
                                                     '--region', '0,0,1,1', '--tile', '1/0,0']),
                         tiles_paint.EXIT_REFUSED)
        self.assertEqual(self.text(), self.before)

    def test_a_non_utf8_file_is_refused_not_a_traceback(self) -> None:
        self.scene.write_bytes(b'[gd_scene format=3]\n\xff\xfe not utf-8\n')
        self.assertEqual(self.verb(tiles_paint.main, ['paint', self.path, '--layer', FLOOR,
                                                     '--region', '0,0,1,1', '--tile', '1/0,0']),
                         tiles_paint.EXIT_REFUSED)
        self.assertIn('REFUSED', self.output.getvalue())


if __name__ == '__main__':
    unittest.main()
