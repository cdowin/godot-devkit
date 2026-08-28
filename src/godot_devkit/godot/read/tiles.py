#!/usr/bin/env python3
"""tiles.py — read a TileMapLayer's grid without reading the file.

    godot-devkit tiles <file.tscn> [--layer NAME]
                       [--cols] [--rows] [--at X,Y] [--region X0,Y0,X1,Y1]

A layer's whole grid is one base64 property, so the questions an author
actually has — how many cells, where do they stop, which tile is at (12,4),
what is in this rectangle — are unanswerable by reading and un-greppable by
eye. Every one of them is a decode away, and hand-rolling that decode is how
three different agents wrote the same twelve-byte loop in one afternoon.

`--cols` / `--rows` are the edge-finders: per-column and per-row cell counts
show where a wall ends, where a lid is missing, and which rows are solid floor,
in one screen of output that no amount of staring at base64 will give you.

Layers are addressed the way the write verbs address them — by node name, or by
the full node path when a name is ambiguous. Read output is write input.
"""
from __future__ import annotations

import argparse
from collections import Counter

from godot_devkit.godot.format.tilemap import (
    COORD_SPEC,
    REGION_SPEC,
    Region,
    Tile,
    TileMapError,
    bounds,
    decode_or_empty,
    parse_coord,
    parse_region,
)
from godot_devkit.godot.format.tscn import (
    TILE_MAP_DATA_PROP,
    TILEMAP_LAYER_TYPE,
    Section,
    TscnError,
    find_tilemap_layer,
    node_own_path,
    parse,
    tilemap_layers,
)

EXIT_OK = 0
EXIT_REFUSED = 1
EXIT_USAGE = 2
INDENT = '  '
EMPTY_CELL = 'empty'
NO_LAYERS = 'no TileMapLayer nodes'
Cells = dict[tuple[int, int], Tile]


def _histogram(cells: Cells) -> list[tuple[Tile, int]]:
    """Tile kinds by descending count, ties broken by the tile itself so the
    output is stable across runs (a shuffled histogram is a diff, not news)."""
    counts = Counter(cells.values())
    return sorted(counts.items(), key=lambda item: (-item[1], item[0]))


def _print_kinds(cells: Cells) -> None:
    kinds = _histogram(cells)
    print(f'{INDENT}kinds ({len(kinds)}):')
    for tile, count in kinds:
        print(f'{INDENT * 2}{tile}   {count}')


def _print_axis(cells: Cells, axis: int, label: str) -> None:
    """Per-column (axis 0) or per-row (axis 1) cell counts, in coordinate order."""
    counts = Counter(coord[axis] for coord in cells)
    print(f'{INDENT}{label} ({len(counts)}):')
    for key in sorted(counts):
        print(f'{INDENT * 2}{"x" if axis == 0 else "y"}={key}   {counts[key]}')


def _print_at(cells: Cells, coord: tuple[int, int]) -> None:
    tile = cells.get(coord)
    print(f'{INDENT}({coord[0]},{coord[1]})  {tile if tile is not None else EMPTY_CELL}')


def _print_region(cells: Cells, region: Region) -> None:
    inside = {coord: tile for coord, tile in cells.items() if coord in region}
    print(f'{INDENT}region {region}  {len(inside)}/{region.size} cells')
    if inside:
        _print_kinds(inside)


def _print_layer(layer: Section, args, at: tuple[int, int] | None,
                 region: Region | None) -> None:
    kind = layer.attrs.get('type') or TILEMAP_LAYER_TYPE
    print(f'\n## {layer.attrs.get("name", "?")}  [{kind}]  ({node_own_path(layer)})')
    prop = layer.prop(TILE_MAP_DATA_PROP)
    try:
        data = decode_or_empty(prop.value if prop is not None else None)
    except TileMapError as err:
        # A layer we cannot decode is reported, never guessed at — and never
        # rendered as an empty grid, which would read as "no cells here".
        print(f'{INDENT}UNREADABLE  {TILE_MAP_DATA_PROP}: {err}')
        return
    cells = data.cells
    if not cells:
        print(f'{INDENT}0 cells')
        return
    min_x, max_x, min_y, max_y = bounds(cells)
    print(f'{INDENT}{len(cells)} cells, x[{min_x}..{max_x}] y[{min_y}..{max_y}]')
    _print_kinds(cells)
    if args.cols:
        _print_axis(cells, 0, 'columns')
    if args.rows:
        _print_axis(cells, 1, 'rows')
    if at is not None:
        _print_at(cells, at)
    if region is not None:
        _print_region(cells, region)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog='godot-devkit tiles', description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('file', help='path to a .tscn')
    parser.add_argument('--layer', help='one layer by node name or full node path '
                                        '(default: every TileMapLayer in the scene)')
    parser.add_argument('--cols', action='store_true', help='per-column cell counts')
    parser.add_argument('--rows', action='store_true', help='per-row cell counts')
    parser.add_argument('--at', metavar=COORD_SPEC,
                        help='the tile at one cell, or `empty`')
    parser.add_argument('--region', metavar=REGION_SPEC,
                        help='cell count + tile kinds inside an inclusive rectangle')
    args = parser.parse_args(argv)
    try:
        sections = parse(args.file)
    except OSError as err:
        print(f'godot-devkit tiles: {err}')
        return EXIT_USAGE

    # Every refusal is decided BEFORE a byte of report is printed, so a bad
    # argument never leaves half a layer census on the caller's screen.
    try:
        at = parse_coord(args.at) if args.at is not None else None
        region = parse_region(args.region) if args.region is not None else None
        layers = ([find_tilemap_layer(sections, args.layer)] if args.layer
                  else tilemap_layers(sections))
    except (TscnError, TileMapError) as err:
        print(f'REFUSED  {args.file}: {err}')
        return EXIT_REFUSED

    print(f'# {args.file}')
    if not layers:
        print(f'{INDENT}{NO_LAYERS}')
        return EXIT_OK
    for layer in layers:
        _print_layer(layer, args, at, region)
    return EXIT_OK


if __name__ == '__main__':
    raise SystemExit(main())
