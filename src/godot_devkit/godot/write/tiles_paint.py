"""tiles_paint.py — fill and clear rectangles of a TileMapLayer, in place.

    godot-devkit tiles paint <file.tscn> --layer NAME --region X0,Y0,X1,Y1
                             --tile SRC/AX,AY[/ALT]
    godot-devkit tiles erase <file.tscn> --layer NAME --region X0,Y0,X1,Y1

Painting a wall, a floor slab, or a lid is the one scene edit that has no
hand form: the grid is a single base64 property, so the alternative is opening
the editor or writing a throwaway decode/encode script — which is exactly what
kept happening.

The surgery is the point. Only that ONE property's line is rewritten; every
other byte of the file — comments, spacing, the other layers, the rest of the
scene — is carried through verbatim by `TscnDocument`, and the cells that
survive keep their position in the stream so the encoded value changes as
little as the edit does. A run that changes no cell writes nothing and says
`unchanged`, which makes both verbs idempotent by construction.

Refusals, all decided before anything is written: an unknown or ambiguous
`--layer`, a malformed `--tile`/`--region`, a coordinate the format cannot
carry, and a `tile_map_data` value that does not decode (re-encoding a partial
read would silently delete the tail of somebody's map).
"""
from __future__ import annotations

import argparse
from pathlib import Path

from godot_devkit.godot.format.tilemap import (
    REGION_SPEC,
    TILE_SPEC,
    Region,
    Tile,
    TileMapData,
    TileMapError,
    bounds,
    decode_or_empty,
    encode,
    glue_signed_values,
    parse_region,
    parse_tile,
)
from godot_devkit.godot.format.tscn import (
    TILE_MAP_DATA_PROP,
    Section,
    TscnError,
    find_tilemap_layer,
    node_own_path,
)
from godot_devkit.godot.format.tscn_document import TscnDocument
from godot_devkit.godot.write import (file_exists, load_scene_or_refuse,
                                      render_diff)

VERBS = ('paint', 'erase')
PAINT, ERASE = VERBS
UNCHANGED = 'unchanged'
EXIT_OK = 0
EXIT_REFUSED = 1
EXIT_USAGE = 2
INDENT = '  '
Cells = dict[tuple[int, int], Tile]


class Outcome:
    """What a run did, in the numbers the caller needs to trust it."""

    def __init__(self, added: int = 0, replaced: int = 0, erased: int = 0) -> None:
        self.added = added
        self.replaced = replaced
        self.erased = erased

    @property
    def changed(self) -> bool:
        return bool(self.added or self.replaced or self.erased)

    def __str__(self) -> str:
        return (f'{self.added} added, {self.replaced} replaced, '
                f'{self.erased} erased')


def apply_paint(cells: Cells, region: Region, tile: Tile) -> tuple[Cells, Outcome]:
    """Fill `region` with `tile`, replacing whatever was there.

    Surviving cells keep their ORDER in the stream and newcomers are appended
    in row-major order: the encoding is a function of the content, not of the
    order the edits happened to arrive in, so the same command twice produces
    the same bytes.
    """
    outcome = Outcome()
    updated = dict(cells)
    for coord in region.coords():
        existing = updated.get(coord)
        if existing == tile:
            continue                                  # already this tile — not a change
        if existing is None:
            outcome.added += 1
        else:
            outcome.replaced += 1
        updated[coord] = tile
    return updated, outcome


def apply_erase(cells: Cells, region: Region) -> tuple[Cells, Outcome]:
    """Delete every cell inside `region`; the rest keep their order."""
    survivors = {coord: tile for coord, tile in cells.items() if coord not in region}
    return survivors, Outcome(erased=len(cells) - len(survivors))


def _write_layer(doc: TscnDocument, layer: Section, data: TileMapData) -> None:
    """Replace only the layer's `tile_map_data` assignment (or append it)."""
    doc.set_prop(node_own_path(layer), TILE_MAP_DATA_PROP, encode(data))


def _summary(cells: Cells) -> str:
    if not cells:
        return '0 cells'
    min_x, max_x, min_y, max_y = bounds(cells)
    return f'{len(cells)} cells, x[{min_x}..{max_x}] y[{min_y}..{max_y}]'


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog='godot-devkit tiles', description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    subs = parser.add_subparsers(dest='verb', required=True)
    for verb in VERBS:
        sub = subs.add_parser(verb)
        sub.add_argument('file')
        sub.add_argument('--layer', required=True,
                         help='the layer by node name or full node path')
        sub.add_argument('--region', required=True, metavar=REGION_SPEC,
                         help='the inclusive rectangle to fill or clear')
        if verb == PAINT:
            sub.add_argument('--tile', required=True, metavar=TILE_SPEC,
                             help='the tile to fill the region with')
        sub.add_argument('--dry-run', action='store_true',
                         help='print the unified diff instead of writing')
    return parser


def main(argv: list[str]) -> int:
    parser = _build_parser()
    # `--region -2,-2,1,1` is an ordinary rectangle in the upper-left quadrant,
    # and argparse before 3.14 reads it as an option. See `glue_signed_values`.
    args = parser.parse_args(glue_signed_values(argv))
    path = Path(args.file)
    if not file_exists(path):
        print(f'godot-devkit tiles {args.verb}: no such file: {path}')
        return EXIT_USAGE

    before = load_scene_or_refuse(path)
    if before is None:
        return EXIT_REFUSED
    doc = TscnDocument(before, path)
    try:
        region = parse_region(args.region)
        tile = parse_tile(args.tile) if args.verb == PAINT else None
        layer = find_tilemap_layer(doc.sections, args.layer)
        prop = layer.prop(TILE_MAP_DATA_PROP)
        data = decode_or_empty(prop.value if prop is not None else None)
        cells, outcome = (apply_paint(data.cells, region, tile) if args.verb == PAINT
                          else apply_erase(data.cells, region))
        if outcome.changed:
            _write_layer(doc, layer, TileMapData(data.version, cells))
    except (TscnError, TileMapError) as err:
        print(f'REFUSED  {path}: {err}')
        return EXIT_REFUSED

    label = f'{args.verb}  {path}  {node_own_path(layer)}'
    if not outcome.changed:
        print(f'{label}  {UNCHANGED}  ({_summary(cells)})')
        return EXIT_OK
    if args.dry_run:
        print(render_diff(before, doc.text, path.name), end='')
    else:
        doc.save()
    print(f'{label}  {outcome} in {region}'
          f'{"  (dry run)" if args.dry_run else ""}')
    print(f'{INDENT}layer now {_summary(cells)}')
    for note in doc.notes:
        print(f'{INDENT}{note}')
    return EXIT_OK
