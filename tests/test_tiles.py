"""Tier 2 — the `tiles` family: decode a TileMapLayer, and paint one.

Three properties carry the feature and each has its own case. The CODEC is
exact (a hand-built byte vector decodes to known cells, and re-encodes to the
same bytes), the READ side answers without guessing (an undecodable layer is
reported, an ambiguous layer name is refused), and the WRITE side is surgical:
only the one `tile_map_data` assignment changes, the file's other bytes —
including that line's own trailing comment — survive, and a paint that changes
no cell writes nothing.
"""
from __future__ import annotations

import base64
import contextlib
import io
import shutil
import struct
import tempfile
import unittest
from pathlib import Path

from support import FIXTURES

from godot_devkit.godot.format import tilemap
from godot_devkit.godot.format.tilemap import Tile, TileMapData, TileMapError
from godot_devkit.godot.format.tscn import TILE_MAP_DATA_PROP, TscnError, find_tilemap_layer, parse
from godot_devkit.godot.format.tscn_document import TscnDocument
from godot_devkit.godot.read import tiles
from godot_devkit.godot.write import tiles_paint

SCENE = FIXTURES / 'tilemap.tscn'
FLOOR = 'FloorLayer'
EMPTY = 'EmptyLayer'
NESTED_WALL = 'Nested/WallLayer'
TILE_DATA_LINE = TILE_MAP_DATA_PROP + ' ='


def _tile_map_data_lines(text: str) -> list[str]:
    return [line for line in text.splitlines() if line.startswith(TILE_DATA_LINE)]


def _other_lines(text: str) -> list[str]:
    return [line for line in text.splitlines() if not line.startswith(TILE_DATA_LINE)]


class Codec(unittest.TestCase):
    """The 12-byte cell layout, proven against bytes built by hand — not against
    this module's own encoder, which would agree with itself while both drift."""

    def test_decodes_the_header_and_one_signed_cell(self) -> None:
        raw = struct.pack('<H', 0) + struct.pack('<hhHHHH', -3, 7, 2, 1, 4, 1)
        data = tilemap.decode(f'PackedByteArray("{base64.b64encode(raw).decode()}")')
        self.assertEqual(data.version, 0)
        self.assertEqual(data.cells, {(-3, 7): Tile(2, 1, 4, 1)})

    def test_round_trips_a_real_layer_value_byte_for_byte(self) -> None:
        value = find_tilemap_layer(parse(str(SCENE)), FLOOR).prop(TILE_MAP_DATA_PROP).value
        self.assertEqual(tilemap.encode(tilemap.decode(value)), value)

    def test_refuses_a_payload_that_is_not_whole_cells(self) -> None:
        raw = struct.pack('<H', 0) + b'\x00' * 5
        with self.assertRaises(TileMapError):
            tilemap.decode(f'PackedByteArray("{base64.b64encode(raw).decode()}")')

    def test_refuses_a_value_that_is_not_a_packed_byte_array(self) -> None:
        with self.assertRaises(TileMapError):
            tilemap.decode('PackedInt32Array(1, 2)')

    def test_refuses_a_cell_the_format_cannot_carry(self) -> None:
        with self.assertRaises(TileMapError):
            tilemap.encode(TileMapData(0, {(40000, 0): Tile(1, 0, 0, 0)}))

    def test_absent_property_reads_as_an_empty_grid(self) -> None:
        self.assertEqual(tilemap.decode_or_empty(None).cells, {})

    def test_parses_the_command_line_spellings(self) -> None:
        self.assertEqual(tilemap.parse_tile('4/1,2/3'), Tile(4, 1, 2, 3))
        self.assertEqual(tilemap.parse_tile('4/1,2'), Tile(4, 1, 2, 0))
        self.assertEqual(tilemap.parse_region('3,4,1,2'), tilemap.Region(1, 2, 3, 4))

    def test_refuses_a_region_too_large_to_materialise(self) -> None:
        with self.assertRaises(TileMapError):
            tilemap.parse_region('-30000,-30000,30000,30000')


class ReadCase(unittest.TestCase):
    def read(self, *argv: str) -> int:
        self.output = io.StringIO()
        with contextlib.redirect_stdout(self.output):
            return tiles.main([str(SCENE), *argv])

    @property
    def text(self) -> str:
        return self.output.getvalue()


class ReadsTheGrid(ReadCase):
    def test_reports_count_bounds_and_kinds(self) -> None:
        self.read('--layer', FLOOR)
        self.assertIn('12 cells, x[-2..3] y[0..5]', self.text)
        self.assertIn('kinds (3):', self.text)
        self.assertIn('src=1 atlas=(0,0) alt=0   10', self.text)

    def test_every_layer_when_no_layer_is_named(self) -> None:
        self.read()
        for path in (FLOOR, NESTED_WALL, 'Deep/WallLayer', EMPTY):
            self.assertIn(f'({path})', self.text)

    def test_a_never_painted_layer_reads_as_zero_cells(self) -> None:
        self.read('--layer', EMPTY)
        self.assertIn('0 cells', self.text)

    def test_at_answers_a_single_cell_and_names_the_holes(self) -> None:
        self.read('--layer', FLOOR, '--at', '0,0')
        self.assertIn('(0,0)  src=1 atlas=(2,1) alt=0', self.text)
        self.read('--layer', FLOOR, '--at', '2,1')
        self.assertIn('(2,1)  empty', self.text)

    def test_region_counts_the_cells_inside_it(self) -> None:
        self.read('--layer', FLOOR, '--region', '0,0,3,2')
        self.assertIn('region x[0..3] y[0..2]  11/12 cells', self.text)
        self.assertIn('kinds (3):', self.text)

    def test_cols_and_rows_expose_the_edges(self) -> None:
        """The field use: per-column counts are how an author finds where a wall
        stops without reading a single byte of base64."""
        self.read('--layer', FLOOR, '--cols', '--rows')
        self.assertIn('columns (5):', self.text)
        self.assertIn('x=-2   1', self.text)
        self.assertIn('rows (4):', self.text)
        self.assertIn('y=5   1', self.text)


class ReadRefuses(ReadCase):
    def test_refuses_an_unknown_layer_and_lists_the_real_ones(self) -> None:
        self.assertEqual(self.read('--layer', 'Nope'), tiles.EXIT_REFUSED)
        self.assertIn(FLOOR, self.text)

    def test_refuses_a_name_two_layers_answer_to(self) -> None:
        self.assertEqual(self.read('--layer', 'WallLayer'), tiles.EXIT_REFUSED)
        self.assertIn('ambiguous', self.text)

    def test_a_full_path_beats_an_ambiguous_name(self) -> None:
        self.assertEqual(self.read('--layer', NESTED_WALL), tiles.EXIT_OK)
        self.assertIn('1 cells', self.text)

    def test_refuses_a_malformed_region_before_printing_anything(self) -> None:
        """A refusal that has already printed half a census is a lie about how
        far the tool got, so every argument is parsed before the first line."""
        self.assertEqual(self.read('--layer', FLOOR, '--region', '0,0,1'),
                         tiles.EXIT_REFUSED)
        self.assertNotIn('cells', self.text)

    def test_refuses_a_malformed_coordinate(self) -> None:
        self.assertEqual(self.read('--layer', FLOOR, '--at', 'left'),
                         tiles.EXIT_REFUSED)

    def test_reports_an_undecodable_layer_instead_of_calling_it_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            broken = Path(tmp) / 'broken.tscn'
            broken.write_text(SCENE.read_text(encoding='utf-8').replace(
                'PackedByteArray("AAAAAAAAAwAAAAAAAAA=")', 'PackedByteArray("AAAAAAAA")'),
                encoding='utf-8')
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                code = tiles.main([str(broken), '--layer', NESTED_WALL])
        self.assertEqual(code, tiles.EXIT_OK)
        self.assertIn('UNREADABLE', output.getvalue())
        self.assertNotIn('0 cells', output.getvalue())


class PaintCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.scene = self.tmp / 'scene.tscn'
        shutil.copy2(SCENE, self.scene)
        self.before = self.text()
        self.addCleanup(shutil.rmtree, self.tmp)

    def run_verb(self, *argv: str) -> int:
        self.output = io.StringIO()
        with contextlib.redirect_stdout(self.output):
            return tiles_paint.main([argv[0], str(self.scene), *argv[1:]])

    def text(self) -> str:
        return self.scene.read_text(encoding='utf-8')

    def cells(self, layer: str) -> dict:
        section = find_tilemap_layer(parse(str(self.scene)), layer)
        prop = section.prop(TILE_MAP_DATA_PROP)
        return tilemap.decode_or_empty(prop.value if prop is not None else None).cells


class PaintFills(PaintCase):
    def test_fills_a_never_painted_layer_by_adding_the_property(self) -> None:
        code = self.run_verb('paint', '--layer', EMPTY, '--region', '0,0,2,1',
                             '--tile', '4/1,2/3')
        self.assertEqual(code, tiles_paint.EXIT_OK)
        self.assertEqual(self.cells(EMPTY),
                         {(x, y): Tile(4, 1, 2, 3) for y in (0, 1) for x in (0, 1, 2)})
        self.assertIn('6 added, 0 replaced, 0 erased', self.output.getvalue())

    def test_replaces_what_the_region_already_held(self) -> None:
        self.run_verb('paint', '--layer', FLOOR, '--region', '0,0,1,1',
                      '--tile', '9/0,0')
        cells = self.cells(FLOOR)
        self.assertEqual(cells[(0, 0)], Tile(9, 0, 0, 0))
        self.assertEqual(cells[(1, 1)], Tile(9, 0, 0, 0))
        self.assertEqual(cells[(-2, 5)], Tile(1, 0, 0, 0))   # outside, untouched
        self.assertIn('0 added, 4 replaced', self.output.getvalue())

    def test_counts_added_and_replaced_separately(self) -> None:
        """(2,1) is a hole in the fixture slab — filling it is an ADD inside a
        region that otherwise replaces, and conflating the two hides that."""
        self.run_verb('paint', '--layer', FLOOR, '--region', '2,1,3,1',
                      '--tile', '5/0,0')
        self.assertIn('1 added, 1 replaced, 0 erased', self.output.getvalue())

    def test_erase_deletes_only_the_region(self) -> None:
        self.run_verb('erase', '--layer', FLOOR, '--region', '0,0,3,2')
        self.assertEqual(self.cells(FLOOR), {(-2, 5): Tile(1, 0, 0, 0)})
        self.assertIn('0 added, 0 replaced, 11 erased', self.output.getvalue())

    def test_reports_the_new_bounds(self) -> None:
        self.run_verb('erase', '--layer', FLOOR, '--region', '-2,5,-2,5')
        self.assertIn('layer now 11 cells, x[0..3] y[0..2]', self.output.getvalue())


class PaintIsSurgical(PaintCase):
    def test_touches_only_the_one_tile_map_data_line(self) -> None:
        self.run_verb('paint', '--layer', FLOOR, '--region', '0,0,1,1',
                      '--tile', '9/0,0')
        after = self.text()
        self.assertEqual(_other_lines(after), _other_lines(self.before))
        changed = [a for a, b in zip(_tile_map_data_lines(after),
                                     _tile_map_data_lines(self.before)) if a != b]
        self.assertEqual(len(changed), 1)

    def test_keeps_the_assignments_own_trailing_comment(self) -> None:
        self.run_verb('paint', '--layer', FLOOR, '--region', '0,0,1,1',
                      '--tile', '9/0,0')
        self.assertIn('") ; the grid, in one line', self.text())

    def test_leaves_the_other_layers_bytes_alone(self) -> None:
        self.run_verb('paint', '--layer', FLOOR, '--region', '0,0,1,1',
                      '--tile', '9/0,0')
        self.assertIn('PackedByteArray("AAAAAAAAAwAAAAAAAAA=")', self.text())

    def test_a_paint_that_changes_no_cell_writes_nothing(self) -> None:
        code = self.run_verb('paint', '--layer', FLOOR, '--region', '0,1,1,1',
                             '--tile', '1/0,0')
        self.assertEqual(code, tiles_paint.EXIT_OK)
        self.assertIn(tiles_paint.UNCHANGED, self.output.getvalue())
        self.assertEqual(self.text(), self.before)

    def test_an_erase_over_empty_space_writes_nothing(self) -> None:
        code = self.run_verb('erase', '--layer', FLOOR, '--region', '40,40,50,50')
        self.assertEqual(code, tiles_paint.EXIT_OK)
        self.assertEqual(self.text(), self.before)

    def test_is_idempotent(self) -> None:
        self.run_verb('paint', '--layer', FLOOR, '--region', '0,0,4,4',
                      '--tile', '9/0,0')
        once = self.text()
        self.assertEqual(self.run_verb('paint', '--layer', FLOOR, '--region', '0,0,4,4',
                                       '--tile', '9/0,0'), tiles_paint.EXIT_OK)
        self.assertEqual(self.text(), once)

    def test_dry_run_writes_nothing(self) -> None:
        self.run_verb('paint', '--layer', FLOOR, '--region', '0,0,1,1',
                      '--tile', '9/0,0', '--dry-run')
        self.assertEqual(self.text(), self.before)
        self.assertIn('--- a/scene.tscn', self.output.getvalue())

    def test_the_result_still_round_trips_as_a_document(self) -> None:
        """Several edits in a row leave a file the document layer still parses
        and re-serialises byte-for-byte — the invariant every write verb rests on."""
        self.run_verb('paint', '--layer', EMPTY, '--region', '0,0,2,1', '--tile', '4/1,2')
        self.run_verb('erase', '--layer', NESTED_WALL, '--region', '0,0,0,0')
        text = self.text()
        self.assertEqual(TscnDocument(text, self.scene).text, text)
        self.assertEqual(self.cells(NESTED_WALL), {})
        self.assertEqual(len(self.cells(EMPTY)), 6)


class PaintRefuses(PaintCase):
    def assert_refused(self, *argv: str) -> None:
        self.assertEqual(self.run_verb(*argv), tiles_paint.EXIT_REFUSED)
        self.assertEqual(self.text(), self.before)   # a refusal writes nothing

    def test_refuses_an_unknown_layer(self) -> None:
        self.assert_refused('paint', '--layer', 'Nope', '--region', '0,0,1,1',
                            '--tile', '1/0,0')

    def test_refuses_an_ambiguous_layer(self) -> None:
        self.assert_refused('paint', '--layer', 'WallLayer', '--region', '0,0,1,1',
                            '--tile', '1/0,0')

    def test_refuses_a_malformed_tile(self) -> None:
        self.assert_refused('paint', '--layer', FLOOR, '--region', '0,0,1,1',
                            '--tile', '1/0')

    def test_refuses_a_tile_field_the_format_cannot_carry(self) -> None:
        self.assert_refused('paint', '--layer', FLOOR, '--region', '0,0,1,1',
                            '--tile', '99999/0,0')

    def test_refuses_a_malformed_region(self) -> None:
        self.assert_refused('erase', '--layer', FLOOR, '--region', '0,0,1')

    def test_refuses_an_undecodable_layer_rather_than_rewriting_it(self) -> None:
        """Re-encoding a partial read would silently delete the tail of a map."""
        self.scene.write_text(self.before.replace(
            'PackedByteArray("AAAAAAAAAwAAAAAAAAA=")', 'PackedByteArray("AAAAAAAA")'),
            encoding='utf-8')
        self.before = self.text()
        self.assert_refused('paint', '--layer', NESTED_WALL, '--region', '0,0,1,1',
                            '--tile', '1/0,0')

    def test_a_missing_file_is_a_usage_error_not_a_refusal(self) -> None:
        self.scene.unlink()
        self.output = io.StringIO()
        with contextlib.redirect_stdout(self.output):
            code = tiles_paint.main(['paint', str(self.scene), '--layer', FLOOR,
                                     '--region', '0,0,1,1', '--tile', '1/0,0'])
        self.assertEqual(code, tiles_paint.EXIT_USAGE)


class LayerLookup(unittest.TestCase):
    def test_finds_layers_by_type_and_by_carried_data(self) -> None:
        from godot_devkit.godot.format.tscn import tilemap_layers
        names = [s.attrs['name'] for s in tilemap_layers(parse(str(SCENE)))]
        self.assertEqual(names, [FLOOR, EMPTY, 'WallLayer', 'WallLayer'])

    def test_refuses_rather_than_picking(self) -> None:
        with self.assertRaises(TscnError):
            find_tilemap_layer(parse(str(SCENE)), 'WallLayer')


if __name__ == '__main__':
    unittest.main()
