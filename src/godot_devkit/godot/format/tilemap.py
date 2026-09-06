"""tilemap.py — the `tile_map_data` codec: Godot 4's packed cell stream, both ways.

A `TileMapLayer` serialises its whole grid into one property:

    tile_map_data = PackedByteArray("<base64>")

The layout, verified against Godot 4.6 text scenes: a leading `uint16` format
tag, then 12 bytes per cell — `int16 x`, `int16 y`, `uint16 source_id`,
`uint16 atlas_x`, `uint16 atlas_y`, `uint16 alternative`. Nothing else. Cell
ORDER is not meaningful to the engine (it loads into a hash map), which is why
`encode` is free to keep the file's existing order and append newcomers.

This module owns that format alone. It knows nothing about `.tscn` sections —
`tscn.py` is a peer, not a parent — so the read side (`scene`, `scene-diff`,
`tiles`) and the write side (`tiles paint/erase`) share ONE decoder instead of
the hand-rolled twelve-byte loop that gets re-derived every time somebody needs
a cell count.

`decode(encode(...))` round-trips exactly, and `encode(decode(v)) == v` for any
value this module accepts — that identity is what lets a paint that changes no
cell leave the file byte-identical.
"""
from __future__ import annotations

import base64
import re
import struct
from typing import NamedTuple

TILE_DATA_B64 = re.compile(r'PackedByteArray\("([^"]*)"\)')
HEADER_BYTES = 2             # leading uint16 format tag, before the cell stream
CELL_BYTES = 12              # x, y, source, atlas_x, atlas_y, alternative
CELL_STRUCT = '<hhHHHH'      # x/y signed (the grid has negative quadrants), rest unsigned
HEADER_STRUCT = '<H'
DEFAULT_VERSION = 0          # what Godot 4.6 writes; preserved when one already exists
COORD_MIN, COORD_MAX = -32768, 32767
FIELD_MIN, FIELD_MAX = 0, 65535
PACKED_BYTE_ARRAY = 'PackedByteArray("{b64}")'
UNPARSED = 'PackedByteArray (unparsed)'
EMPTY_BOUNDS = '0 cells'

# --- The command-line spelling of the same values ---------------------------
# A tile and a region have a text form because the CLI has to take them; that
# spelling belongs beside the binary one, so `tiles` and `tiles paint` cannot
# drift into two dialects of the same argument.
TILE_SPEC = 'SRC/AX,AY[/ALT]'
REGION_SPEC = 'X0,Y0,X1,Y1'
COORD_SPEC = 'X,Y'
FIELD_SEP = '/'
VALUE_SEP = ','
# A region is materialised cell by cell, so an absurd one is refused rather
# than allowed to allocate the whole int16 plane (4.3 billion cells).
MAX_REGION_CELLS = 1_000_000

# The flags whose values may open with `-`, and argparse's blind spot around
# them. Before 3.14, argparse excuses a leading `-` only for a BARE number
# (`_negative_number_matcher` is `^-\d+$|^-\d*\.\d+$`), so `-2,-2,1,1` reads as
# an option and the run dies with `argument --region: expected one argument`.
# The grid's negative quadrants are not an edge case — `CELL_STRUCT` signs x
# and y precisely because the upper-left quadrant is ordinary — so on the
# declared 3.11 floor `tiles paint/erase` could not address a quarter of the
# plane, and `uvx` picks the interpreter, not the consumer.
SIGNED_VALUE_FLAGS = ('--region', '--at')
_OPENS_NEGATIVE = re.compile(r'^-\d')


class TileMapError(Exception):
    """A `tile_map_data` value this module refuses to guess at."""


class Tile(NamedTuple):
    """What a single cell points at: a source, an atlas coord, an alternative."""
    source: int
    atlas_x: int
    atlas_y: int
    alternative: int = 0

    def __str__(self) -> str:
        return f'src={self.source} atlas=({self.atlas_x},{self.atlas_y}) alt={self.alternative}'


class TileMapData(NamedTuple):
    """A decoded layer: the format tag it carried, and its cells in file order."""
    version: int
    cells: dict[tuple[int, int], Tile]


class Region(NamedTuple):
    """An INCLUSIVE rectangle of cell coordinates, normalised so x0 <= x1."""
    x0: int
    y0: int
    x1: int
    y1: int

    def __contains__(self, coord) -> bool:
        x, y = coord
        return self.x0 <= x <= self.x1 and self.y0 <= y <= self.y1

    @property
    def size(self) -> int:
        return (self.x1 - self.x0 + 1) * (self.y1 - self.y0 + 1)

    def coords(self):
        """Every coordinate in the rectangle, row-major — the paint order."""
        for y in range(self.y0, self.y1 + 1):
            for x in range(self.x0, self.x1 + 1):
                yield (x, y)

    def __str__(self) -> str:
        return f'x[{self.x0}..{self.x1}] y[{self.y0}..{self.y1}]'


def decode(value: str) -> TileMapData:
    """Decode a `tile_map_data` property value into `{(x, y): Tile}`.

    Raises `TileMapError` rather than returning a half-read grid: a value that
    is not a `PackedByteArray`, or whose payload is not a whole number of
    cells, is corrupt or a format this decoder does not know — and a writer
    that re-encoded a partial read would silently delete the tail.
    """
    match = TILE_DATA_B64.search(value)
    if not match:
        raise TileMapError('not a PackedByteArray("...") value')
    try:
        # `binascii.Error` (what a bad payload raises) subclasses ValueError.
        data = base64.b64decode(match.group(1), validate=True)
    except ValueError as err:
        raise TileMapError(f'undecodable base64 payload: {err}') from err
    if len(data) < HEADER_BYTES or (len(data) - HEADER_BYTES) % CELL_BYTES:
        raise TileMapError(f'{len(data)} bytes is not a {HEADER_BYTES}-byte header '
                           f'plus whole {CELL_BYTES}-byte cells')
    version = struct.unpack_from(HEADER_STRUCT, data, 0)[0]
    cells: dict[tuple[int, int], Tile] = {}
    for offset in range(HEADER_BYTES, len(data), CELL_BYTES):
        x, y, source, atlas_x, atlas_y, alternative = struct.unpack_from(
            CELL_STRUCT, data, offset)
        cells[(x, y)] = Tile(source, atlas_x, atlas_y, alternative)
    return TileMapData(version, cells)


def encode(data: TileMapData) -> str:
    """Re-emit `{(x, y): Tile}` as a `PackedByteArray("...")` property value.

    Cells are written in the dict's iteration order — the caller's job is to
    keep that order stable (surviving cells where they were, newcomers appended
    deterministically), because a reshuffled stream is a whole-line diff that
    changes nothing.
    """
    out = bytearray(struct.pack(HEADER_STRUCT, data.version))
    for (x, y), tile in data.cells.items():
        _check_range('cell coordinate', (x, y), COORD_MIN, COORD_MAX)
        _check_range('tile field', tile, FIELD_MIN, FIELD_MAX)
        out += struct.pack(CELL_STRUCT, x, y, tile.source,
                           tile.atlas_x, tile.atlas_y, tile.alternative)
    return PACKED_BYTE_ARRAY.format(b64=base64.b64encode(bytes(out)).decode('ascii'))


def decode_or_empty(value: str | None) -> TileMapData:
    """The cells a layer holds — its decoded value, or an empty grid when the
    property is absent, which is how a never-painted TileMapLayer is stored."""
    return TileMapData(DEFAULT_VERSION, {}) if value is None else decode(value)


def bounds(cells: dict[tuple[int, int], Tile]) -> tuple[int, int, int, int]:
    """`(min_x, max_x, min_y, max_y)` over the used cells. Empty is a caller error."""
    xs = [x for x, _ in cells]
    ys = [y for _, y in cells]
    return min(xs), max(xs), min(ys), max(ys)


def decode_tilemap_bounds(value: str) -> str:
    """`<N> cells, x[..] y[..]` — the one-line summary `scene`/`scene-diff` print.

    Lenient by design: this is a display path, so an unreadable value is
    described, never raised. The write path calls `decode` and gets the refusal.
    """
    try:
        data = decode(value)
    except TileMapError:
        return UNPARSED
    if not data.cells:
        return EMPTY_BOUNDS
    min_x, max_x, min_y, max_y = bounds(data.cells)
    return f'{len(data.cells)} cells, x[{min_x}..{max_x}] y[{min_y}..{max_y}]'


def parse_tile(spec: str) -> Tile:
    """`SRC/AX,AY[/ALT]` -> a `Tile`. Refuses anything it would have to guess at."""
    parts = spec.split(FIELD_SEP)
    if len(parts) not in (2, 3):
        raise TileMapError(f'malformed --tile {spec!r} (expected {TILE_SPEC})')
    source = _int(parts[0], '--tile source')
    atlas = parts[1].split(VALUE_SEP)
    if len(atlas) != 2:
        raise TileMapError(f'malformed --tile {spec!r}: atlas coord must be AX,AY')
    tile = Tile(source, _int(atlas[0], '--tile atlas x'), _int(atlas[1], '--tile atlas y'),
                _int(parts[2], '--tile alternative') if len(parts) == 3 else 0)
    _check_range('--tile field', tile, FIELD_MIN, FIELD_MAX)
    return tile


def parse_coord(spec: str) -> tuple[int, int]:
    """`X,Y` -> a cell coordinate."""
    parts = spec.split(VALUE_SEP)
    if len(parts) != 2:
        raise TileMapError(f'malformed coordinate {spec!r} (expected {COORD_SPEC})')
    coord = (_int(parts[0], 'coordinate x'), _int(parts[1], 'coordinate y'))
    _check_range('cell coordinate', coord, COORD_MIN, COORD_MAX)
    return coord


def glue_signed_values(argv: list[str],
                       flags: tuple[str, ...] = SIGNED_VALUE_FLAGS) -> list[str]:
    """`--region -2,-2,1,1` -> `--region=-2,-2,1,1`, which every version reads.

    Applied to the ARGV, not to the parser: the private matcher argparse keys on
    was rewritten in 3.14, and a tool whose behaviour depends on which patch of
    CPython a consumer's `uvx` happened to pick is not a tool.

    Deliberately narrow. Only a token that OPENS with a minus and a digit is
    glued, so `--region --tile 9/0,0` still reaches argparse as the malformed
    invocation it is and still exits 2. `--region=…` and anything already
    positive are untouched, and so is everything after `--`.
    """
    out: list[str] = []
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg == '--':
            out.extend(argv[i:])
            break
        if (arg in flags and i + 1 < len(argv)
                and _OPENS_NEGATIVE.match(argv[i + 1])):
            out.append(f'{arg}={argv[i + 1]}')
            i += 2
            continue
        out.append(arg)
        i += 1
    return out


def parse_region(spec: str) -> Region:
    """`X0,Y0,X1,Y1` -> an inclusive `Region`, corners in any order."""
    parts = spec.split(VALUE_SEP)
    if len(parts) != 4:
        raise TileMapError(f'malformed --region {spec!r} (expected {REGION_SPEC})')
    x0, y0, x1, y1 = (_int(p, '--region bound') for p in parts)
    _check_range('--region bound', (x0, y0, x1, y1), COORD_MIN, COORD_MAX)
    region = Region(min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))
    if region.size > MAX_REGION_CELLS:
        raise TileMapError(f'--region {region} covers {region.size} cells, over the '
                           f'{MAX_REGION_CELLS} limit — narrow it')
    return region


def _int(text: str, what: str) -> int:
    try:
        return int(text.strip())
    except ValueError as err:
        raise TileMapError(f'{what} {text.strip()!r} is not an integer') from err


def _check_range(what: str, values, low: int, high: int) -> None:
    for value in values:
        if not low <= value <= high:
            raise TileMapError(f'{what} {value} is outside [{low}..{high}] — '
                               f'the format cannot carry it')
