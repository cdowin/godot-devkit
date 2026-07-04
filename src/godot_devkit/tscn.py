"""godot_tscn.py — shared read-only .tscn/.tres parser.

The grammar-level pieces of Godot's text resource format (section/property
parsing, resource-ref resolution, tilemap cell decoding) factored out of
`scene_summary.py` so the rest of the `tools/dev/` family (scene_diff, refs,
orphans) composes one parser instead of re-rolling it. Pure parse — never
writes, never boots Godot.
"""
from __future__ import annotations

import base64
import re
import struct
from dataclasses import dataclass, field

# --- Godot .tscn grammar ----------------------------------------------------
SECTION_HEADER = re.compile(r'^\[(\w+)\s*(.*)\]\s*$')
HEADER_ATTR = re.compile(r'(\w+)=("(?:[^"\\]|\\.)*"|\w+\("[^"]*"\)|[^\s\]]+)')
PACKED_ARRAY = re.compile(r'^Packed\w+Array\(')
RESOURCE_REF = re.compile(r'(Ext|Sub)Resource\("([^"]*)"\)')
TILE_DATA_B64 = re.compile(r'PackedByteArray\("([^"]*)"\)')
REF_ARROW = '→'

# --- TileMapLayer binary layout (Godot 4 `tile_map_data`) -------------------
TILEMAP_HEADER_BYTES = 2     # leading uint16 format tag, before the cell stream
TILEMAP_CELL_BYTES = 12      # per cell: x,y,source,atlas_x,atlas_y,alt (6 × int16)
TILEMAP_CELL_XY = '<hh'      # we decode only each cell's leading x,y (for bounds)


@dataclass
class Section:
    """One `[...]` block of a .tscn/.tres: its kind, header attrs, and body props."""
    kind: str
    attrs: dict[str, str]
    props: list[tuple[str, str]] = field(default_factory=list)  # author order


def _strip_quotes(value: str) -> str:
    return value[1:-1] if len(value) >= 2 and value[0] == value[-1] == '"' else value


def _basename(path: str) -> str:
    return path.rsplit('/', 1)[-1]


def _is_unbalanced(value: str) -> bool:
    """True while a property value has an open bracket/paren/quote — i.e. it wraps
    onto the next line (rare: a multi-line array). Pragmatic, not a real lexer."""
    return (value.count('(') != value.count(')')
            or value.count('[') != value.count(']')
            or value.count('"') % 2 != 0)


def parse(path: str) -> list[Section]:
    """Parse a .tscn/.tres into its ordered sections. Continuation lines of a
    multi-line property value are folded back onto the property."""
    with open(path, encoding='utf-8', errors='replace') as handle:
        lines = handle.read().split('\n')

    sections: list[Section] = []
    current: Section | None = None
    index = 0
    while index < len(lines):
        line = lines[index]
        header = SECTION_HEADER.match(line)
        if header:
            attrs = {k: _strip_quotes(v) for k, v in HEADER_ATTR.findall(header.group(2))}
            current = Section(header.group(1), attrs)
            sections.append(current)
        elif current is not None and '=' in line and not line.lstrip().startswith('['):
            key, _, value = line.partition('=')
            key, value = key.strip(), value.strip()
            while _is_unbalanced(value) and index + 1 < len(lines):
                index += 1
                value += ' ' + lines[index].strip()
            current.props.append((key, value))
        index += 1
    return sections


def parse_text(text: str) -> list[Section]:
    """Same as `parse`, from an in-memory string (e.g. `git show <ref>:<path>`)."""
    sections: list[Section] = []
    current: Section | None = None
    lines = text.split('\n')
    index = 0
    while index < len(lines):
        line = lines[index]
        header = SECTION_HEADER.match(line)
        if header:
            attrs = {k: _strip_quotes(v) for k, v in HEADER_ATTR.findall(header.group(2))}
            current = Section(header.group(1), attrs)
            sections.append(current)
        elif current is not None and '=' in line and not line.lstrip().startswith('['):
            key, _, value = line.partition('=')
            key, value = key.strip(), value.strip()
            while _is_unbalanced(value) and index + 1 < len(lines):
                index += 1
                value += ' ' + lines[index].strip()
            current.props.append((key, value))
        index += 1
    return sections


def decode_tilemap_bounds(value: str) -> str:
    """Decode a `tile_map_data` PackedByteArray to `<N> cells, x[..] y[..]` — the
    used-cell count and tile bounds, without dumping the bytes."""
    match = TILE_DATA_B64.search(value)
    if not match:
        return 'PackedByteArray (unparsed)'
    data = base64.b64decode(match.group(1))
    count = (len(data) - TILEMAP_HEADER_BYTES) // TILEMAP_CELL_BYTES
    if count <= 0:
        return '0 cells'
    xs: list[int] = []
    ys: list[int] = []
    for cell in range(count):
        offset = TILEMAP_HEADER_BYTES + cell * TILEMAP_CELL_BYTES
        x, y = struct.unpack_from(TILEMAP_CELL_XY, data, offset)
        xs.append(x)
        ys.append(y)
    return f'{count} cells, x[{min(xs)}..{max(xs)}] y[{min(ys)}..{max(ys)}]'


def resolve_ref(value: str, ext: dict[str, dict]) -> str:
    """Render an Ext/SubResource("id") reference as `→<basename>` (Ext) or `→<id>`."""
    match = RESOURCE_REF.match(value)
    if not match:
        return value
    kind, ref_id = match.group(1), match.group(2)
    if kind == 'Ext' and ref_id in ext:
        target = ext[ref_id]
        return REF_ARROW + _basename(target.get('path') or target.get('uid', '?'))
    return REF_ARROW + ref_id


def node_own_path(node: Section) -> str:
    """A node's own scene path (what its children name in their `parent=`)."""
    parent = node.attrs.get('parent')
    name = node.attrs.get('name', '?')
    return name if parent == '.' else f'{parent}/{name}'
