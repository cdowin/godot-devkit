"""atlas_map.py — autotiling from an atlas map: which atlas cell each painted cell gets.

An atlas map is a JSON file a project keeps beside its tile atlas:

    {"columns": 4, "material_period": [8, 8],
     "entries": [{"id": "...", "canonical_neighbor_mask": 80,
                  "material_phase": [0, 0],
                  "atlas_cell": {"index": 5, "x": 1, "y": 1}}, ...]}

Each entry is one SLOT: the atlas cell for a cell whose filled 4-neighbours
spell `canonical_neighbor_mask` (up 2, left 8, right 16, down 64 — the
connect16 set) and whose position modulo `material_period` is
`material_phase`. A BACKGROUND map has no masks at all: one entry per phase,
and every cell's mask is 0.

A cell counts as filled when it is being painted, or when the layer already
holds a cell of the same source. Painting therefore changes the masks of the
existing same-source neighbours too, and `autotile` re-slots them in the same
edit — a wall painted next to a wall must not leave a cap tile in the middle.

Everything here refuses rather than guesses: a malformed map, two entries for
one (mask, phase), a cell whose (mask, phase) has no slot, and a same-source
neighbour that is not one of the map's slots (a wrong `--source`, or a cell
this map does not own) all raise `AtlasMapError` before anything is written.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import NamedTuple

from godot_devkit.godot.format.tilemap import Tile, TileMapError

UP, LEFT, RIGHT, DOWN = 2, 8, 16, 64
# (dx, dy, bit) — Godot's y axis points down, so "up" is y - 1.
NEIGHBOURS = ((0, -1, UP), (-1, 0, LEFT), (1, 0, RIGHT), (0, 1, DOWN))
MASKS = frozenset(up | left | right | down
                  for up in (0, UP) for left in (0, LEFT)
                  for right in (0, RIGHT) for down in (0, DOWN))
BACKGROUND_MASK = 0
MASK_KEY = 'canonical_neighbor_mask'
Coord = tuple[int, int]


class AtlasMapError(TileMapError):
    """An atlas map, or a paint through one, this module refuses to guess at."""


class AtlasMap(NamedTuple):
    """A validated map: the phase period, and (mask, phase) -> atlas cell."""
    period: Coord
    connects: bool                       # False for a background map
    slots: dict[tuple[int, Coord], Coord]

    def phase(self, coord: Coord) -> Coord:
        # Python's % is already Godot's posmod: (-1) % 8 == 7.
        return coord[0] % self.period[0], coord[1] % self.period[1]

    def slot(self, coord: Coord, mask: int) -> Coord:
        key = (mask, self.phase(coord))
        if key not in self.slots:
            raise AtlasMapError(f'the atlas map has no slot for cell {coord}: '
                                f'neighbor mask {mask}, phase {key[1]}')
        return self.slots[key]


def load(path: str | Path) -> AtlasMap:
    """Read and validate an atlas map file."""
    try:
        data = json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as err:
        raise AtlasMapError(f'cannot read atlas map {path}: {err}') from err
    return parse(data)


def parse(data: object) -> AtlasMap:
    """Validate a decoded atlas map. Every rule is a refusal, never a default."""
    if not isinstance(data, dict):
        raise AtlasMapError('atlas map is not a JSON object')
    period = _pair(data.get('material_period'), 'material_period')
    if min(period) < 1:
        raise AtlasMapError(f'material_period {list(period)} must be positive')
    columns = data.get('columns')
    if columns is not None and not (_is_int(columns) and columns > 0):
        raise AtlasMapError(f'columns {columns!r} is not a positive integer')
    entries = data.get('entries')
    if not isinstance(entries, list) or not entries:
        raise AtlasMapError('atlas map has no entries')
    with_mask = sum(1 for e in entries if isinstance(e, dict) and MASK_KEY in e)
    if with_mask not in (0, len(entries)):
        raise AtlasMapError(f'{with_mask} of {len(entries)} entries carry {MASK_KEY} — '
                            f'a map is either connect16 (all) or background (none)')
    slots: dict[tuple[int, Coord], Coord] = {}
    for number, entry in enumerate(entries):
        where = f'entry {number}'
        if not isinstance(entry, dict):
            raise AtlasMapError(f'{where} is not an object')
        mask = entry.get(MASK_KEY, BACKGROUND_MASK)
        if not _is_int(mask) or mask not in MASKS:
            raise AtlasMapError(f'{where}: {MASK_KEY} {mask!r} is not a connect16 mask')
        phase = _pair(entry.get('material_phase'), f'{where} material_phase')
        if not all(0 <= p < n for p, n in zip(phase, period)):
            raise AtlasMapError(f'{where}: material_phase {list(phase)} is outside '
                                f'the period {list(period)}')
        slots_key = (mask, phase)
        if slots_key in slots:
            raise AtlasMapError(f'{where}: a second slot for mask {mask}, phase '
                                f'{list(phase)} — the map is ambiguous')
        slots[slots_key] = _atlas_cell(entry.get('atlas_cell'), columns, where)
    return AtlasMap(period, with_mask > 0, slots)


def mask_of(coord: Coord, filled: set[Coord]) -> int:
    """The connect16 mask of `coord`'s filled 4-neighbours."""
    x, y = coord
    return sum(bit for dx, dy, bit in NEIGHBOURS if (x + dx, y + dy) in filled)


def autotile(cells: dict[Coord, Tile], painted: list[Coord], source: int,
             amap: AtlasMap) -> dict[Coord, Tile]:
    """The tile every painted cell gets, plus every existing same-source
    neighbour whose slot the paint changes. Painted cells come first, in the
    caller's order; re-slotted neighbours follow in first-seen order."""
    painted_set = set(painted)
    filled = painted_set | {c for c, t in cells.items() if t.source == source}
    owned = set(amap.slots.values())
    targets = list(dict.fromkeys(painted))
    if amap.connects:
        for x, y in painted:
            for dx, dy, _ in NEIGHBOURS:
                near = (x + dx, y + dy)
                if near in filled and near not in painted_set and near not in targets:
                    targets.append(near)
    out: dict[Coord, Tile] = {}
    for coord in targets:
        if coord not in painted_set:
            held = cells[coord]
            if (held.atlas_x, held.atlas_y) not in owned or held.alternative:
                raise AtlasMapError(
                    f'neighbor {coord} holds {held}, which is not a slot of this '
                    f'atlas map — wrong --source, or a cell the map does not own; '
                    f'refusing to re-slot it')
        mask = mask_of(coord, filled) if amap.connects else BACKGROUND_MASK
        out[coord] = Tile(source, *amap.slot(coord, mask))
    return out


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _pair(value: object, what: str) -> Coord:
    if (not isinstance(value, list) or len(value) != 2
            or not all(_is_int(v) for v in value)):
        raise AtlasMapError(f'{what} {value!r} is not a pair of integers')
    return value[0], value[1]


def _atlas_cell(cell: object, columns: object, where: str) -> Coord:
    if not isinstance(cell, dict) or not _is_int(cell.get('x')) or not _is_int(cell.get('y')):
        raise AtlasMapError(f'{where}: atlas_cell {cell!r} needs integer x and y')
    x, y = cell['x'], cell['y']
    if min(x, y) < 0:
        raise AtlasMapError(f'{where}: atlas_cell ({x},{y}) is negative')
    index = cell.get('index')
    if index is not None and _is_int(columns) and (x, y) != (index % columns, index // columns):
        raise AtlasMapError(f'{where}: atlas_cell index {index} is ({index % columns},'
                            f'{index // columns}) at {columns} columns, not ({x},{y})')
    return x, y
