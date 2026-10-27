"""tiles_paint.py — paint and erase cells of a TileMapLayer, in place.

    godot-devkit tiles paint <file.tscn> --layer NAME (--region X0,Y0,X1,Y1 | --at X,Y ...)
                             (--tile SRC/AX,AY[/ALT] | --atlas-map MAP.json --source SRC)
    godot-devkit tiles erase <file.tscn> --layer NAME (--region X0,Y0,X1,Y1 | --at X,Y ...)

The cells are a rectangle (`--region`, inclusive) or a list (`--at`, repeat it;
one `--at` sets one cell). The brush is one tile (`--tile`), or an AUTOTILE
atlas map (`--atlas-map` + `--source`): each painted cell gets the map's slot
for its filled 4-neighbours and its material phase (`format/atlas_map.py`),
and the layer's existing same-source neighbours whose neighbour mask the
paint changes are RE-SLOTTED in the same edit. Painting the same cells twice
is a no-op.

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
`--layer`, a malformed `--tile`/`--region`/`--at`, a coordinate the format
cannot carry, an atlas map that is malformed or has no slot for a cell, and a
`tile_map_data` value that does not decode (re-encoding a partial
read would silently delete the tail of somebody's map).
"""
from __future__ import annotations

import argparse
from pathlib import Path

from godot_devkit.godot.format import atlas_map
from godot_devkit.godot.format.tilemap import (
    COORD_SPEC,
    REGION_SPEC,
    TILE_SPEC,
    Tile,
    TileMapData,
    TileMapError,
    bounds,
    decode_or_empty,
    encode,
    glue_signed_values,
    parse_coord,
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
TILE_SET_PROP = 'tile_set'
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


def apply_paint(cells: Cells, wanted: Cells) -> tuple[Cells, Outcome]:
    """Set every cell in `wanted`, replacing whatever was there.

    Surviving cells keep their ORDER in the stream and newcomers are appended
    in `wanted`'s order: the encoding is a function of the content, not of the
    order the edits happened to arrive in, so the same command twice produces
    the same bytes.
    """
    outcome = Outcome()
    updated = dict(cells)
    for coord, tile in wanted.items():
        existing = updated.get(coord)
        if existing == tile:
            continue                                  # already this tile — not a change
        if existing is None:
            outcome.added += 1
        else:
            outcome.replaced += 1
        updated[coord] = tile
    return updated, outcome


def apply_erase(cells: Cells, targets: list[tuple[int, int]]) -> tuple[Cells, Outcome]:
    """Delete every cell in `targets`; the rest keep their order."""
    doomed = set(targets)
    survivors = {coord: tile for coord, tile in cells.items() if coord not in doomed}
    return survivors, Outcome(erased=len(cells) - len(survivors))


def _targets(args) -> tuple[list[tuple[int, int]], str]:
    """The cells a run addresses, and how to name them in the report."""
    if args.region is not None:
        region = parse_region(args.region)
        return list(region.coords()), f'in {region}'
    coords = list(dict.fromkeys(parse_coord(spec) for spec in args.at))
    return coords, f'at {len(coords)} cell(s)'


def _brush(args, cells: Cells, targets: list[tuple[int, int]]) -> Cells:
    """What each target cell (and each re-slotted neighbour) should hold."""
    if args.tile is not None:
        tile = parse_tile(args.tile)
        return {coord: tile for coord in targets}
    amap = atlas_map.load(args.atlas_map)
    return atlas_map.autotile(cells, targets, args.source, amap)


def _write_layer(doc: TscnDocument, layer: Section, data: TileMapData) -> None:
    """Replace only the layer's `tile_map_data` assignment, or add it where
    the saver writes it: above `tile_set`, which follows it in ClassDB order."""
    doc.set_section_prop(layer, TILE_MAP_DATA_PROP, encode(data),
                         before=(TILE_SET_PROP,))


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
        cells = sub.add_mutually_exclusive_group(required=True)
        cells.add_argument('--region', metavar=REGION_SPEC,
                           help='the inclusive rectangle to fill or clear')
        cells.add_argument('--at', action='append', metavar=COORD_SPEC,
                           help='one cell; repeat for a list of cells')
        if verb == PAINT:
            brush = sub.add_mutually_exclusive_group(required=True)
            brush.add_argument('--tile', metavar=TILE_SPEC,
                               help='the one tile to paint every cell with')
            brush.add_argument('--atlas-map', dest='atlas_map', metavar='MAP.json',
                               help='autotile through this atlas map (needs '
                                    '--source); existing same-source neighbors '
                                    'whose mask changes are re-slotted too')
            sub.add_argument('--source', type=int, metavar='SRC',
                             help='the TileSet source id the atlas map paints')
        sub.add_argument('--dry-run', action='store_true',
                         help='print the unified diff instead of writing')
    return parser


def main(argv: list[str]) -> int:
    parser = _build_parser()
    # `--region -2,-2,1,1` is an ordinary rectangle in the upper-left quadrant,
    # and argparse before 3.14 reads it as an option. See `glue_signed_values`.
    args = parser.parse_args(glue_signed_values(argv))
    if args.verb == PAINT and (args.atlas_map is None) != (args.source is None):
        parser.error('--atlas-map and --source go together, and only with each other')
    path = Path(args.file)
    if not file_exists(path):
        print(f'godot-devkit tiles {args.verb}: no such file: {path}')
        return EXIT_USAGE

    before = load_scene_or_refuse(path)
    if before is None:
        return EXIT_REFUSED
    doc = TscnDocument(before, path)
    try:
        targets, where = _targets(args)
        layer = find_tilemap_layer(doc.sections, args.layer)
        prop = layer.prop(TILE_MAP_DATA_PROP)
        data = decode_or_empty(prop.value if prop is not None else None)
        if args.verb == PAINT:
            wanted = _brush(args, data.cells, targets)
            cells, outcome = apply_paint(data.cells, wanted)
            reslotted = len(wanted) - len(targets)
        else:
            cells, outcome = apply_erase(data.cells, targets)
            reslotted = 0
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
    print(f'{label}  {outcome} {where}'
          f'{"  (dry run)" if args.dry_run else ""}')
    if reslotted:
        print(f'{INDENT}{reslotted} neighbor(s) re-slotted by the atlas map')
    print(f'{INDENT}layer now {_summary(cells)}')
    for note in doc.notes:
        print(f'{INDENT}{note}')
    return EXIT_OK
