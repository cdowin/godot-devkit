"""tscn.py — the shared .tscn/.tres grammar: read it, and edit it in place.

Two layers, one parser.

READ (unchanged, what `scene`/`scene-diff`/`refs`/`orphans` have always used):
`parse()` / `parse_text()` return the ordered `[...]` sections with their header
attributes and body properties.

EDIT (`TscnDocument`): the same parse, but every section and every property also
remembers the LINE SPAN it came from. Edits rewrite only the spans they were
asked about; every other byte of the file is carried through verbatim.

That is the toolkit's load-bearing property: parse -> serialise with no mutation
is BYTE-IDENTICAL, because serialising is `'\\n'.join(self.lines)` and untouched
lines are the original strings. A writer that re-serialises from a model instead
would be more dangerous than `sed`, since it silently normalises lines nobody
asked it to touch.

Value scanning is string-aware: brackets and `;` inside a quoted string do not
count, so `text = "a (b"` does not read as an unterminated value and
`layer = 16 ; note` keeps its comment out of the value. Godot 4 spellings the
format's own docs omit — `&"StringName"` literals, `^"NodePath"` literals,
multi-line dictionaries, inline `;` comments — all fall out of that scan.
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
NODE_PATH_LITERAL = re.compile(r'(\^?)NodePath\("([^"]*)"\)')
REF_ARROW = '→'

COMMENT_CHAR = ';'
OPENERS = '([{'
CLOSERS = ')]}'
ROOT_PATH = '.'
PATH_SEP = '/'
PARENT_SEG = '..'
SELF_SEG = '.'
SUBNAME_SEP = ':'
ABSOLUTE_PATH_PREFIX = '/'
PROP_ASSIGN = ' = '

# --- TileMapLayer binary layout (Godot 4 `tile_map_data`) -------------------
TILEMAP_HEADER_BYTES = 2     # leading uint16 format tag, before the cell stream
TILEMAP_CELL_BYTES = 12      # per cell: x,y,source,atlas_x,atlas_y,alt (6 × int16)
TILEMAP_CELL_XY = '<hh'      # we decode only each cell's leading x,y (for bounds)


class TscnError(Exception):
    """A refusal: the requested edit is not expressible without guessing."""


@dataclass
class Prop:
    """One `key = value` assignment, with the exact lines it occupies."""
    key: str
    value: str            # folded onto one line, comment stripped
    start: int            # first line index (inclusive)
    end: int              # last line index (exclusive)
    prefix: str           # raw text up to and including '=', e.g. 'position ='
    comment: str          # trailing '; ...' from the final line, '' if none

    def render(self, value: str | None = None) -> str:
        """Re-emit as a single line, preserving the original spacing + comment."""
        body = self.value if value is None else value
        tail = f' {self.comment}' if self.comment else ''
        return f'{self.prefix} {body}{tail}'


@dataclass
class Section:
    """One `[...]` block: its kind, header attrs, body props, and line span."""
    kind: str
    attrs: dict[str, str]
    entries: list[Prop] = field(default_factory=list)
    header_line: int = -1
    body_end: int = -1    # exclusive; last property line + 1 (header + 1 if none)

    @property
    def props(self) -> list[tuple[str, str]]:
        """Author-order `(key, value)` pairs — the long-standing read API."""
        return [(entry.key, entry.value) for entry in self.entries]

    def prop(self, key: str) -> Prop | None:
        return next((entry for entry in self.entries if entry.key == key), None)


def _strip_quotes(value: str) -> str:
    return value[1:-1] if len(value) >= 2 and value[0] == value[-1] == '"' else value


def _basename(path: str) -> str:
    return path.rsplit(PATH_SEP, 1)[-1]


def scan_line(text: str, depth: int = 0, in_string: bool = False, escaped: bool = False,
              comment_char: str = COMMENT_CHAR) -> tuple[int, bool, bool, int]:
    """Consume one line, tracking bracket depth with STRING AWARENESS.

    Returns the carried (depth, in_string, escaped) plus the index at which a
    top-level comment starts (-1 if none). Brackets and comment characters
    inside a quoted string do not count — which is the whole reason this exists
    rather than a `line.count('(')` heuristic. `comment_char` is `;` for the
    resource format and `#` for GDScript, whose exports this also scans.
    """
    for index, char in enumerate(text):
        if in_string:
            if escaped:
                escaped = False
            elif char == '\\':
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char in OPENERS:
            depth += 1
        elif char in CLOSERS:
            depth -= 1
        elif char == comment_char and depth <= 0:
            return depth, in_string, escaped, index
    return depth, in_string, escaped, -1


def _parse_lines(lines: list[str]) -> list[Section]:
    """The one parse. Sections carry line spans; callers that only want the
    (key, value) view read `Section.props` and never notice."""
    sections: list[Section] = []
    current: Section | None = None
    index = 0
    while index < len(lines):
        line = lines[index]
        header = SECTION_HEADER.match(line)
        if header:
            attrs = {k: _strip_quotes(v) for k, v in HEADER_ATTR.findall(header.group(2))}
            current = Section(header.group(1), attrs,
                              header_line=index, body_end=index + 1)
            sections.append(current)
            index += 1
            continue
        stripped = line.lstrip()
        # Not a property line: outside any section, blank, a comment, a
        # continuation we already folded, or a bracketed form we do not own.
        if (current is None or '=' not in line
                or stripped.startswith((COMMENT_CHAR, '['))):
            index += 1
            continue

        key, _, raw_value = line.partition('=')
        prefix = line[:len(key) + 1]
        start = index
        depth, in_string, escaped, comment_at = scan_line(raw_value)
        value = raw_value[:comment_at] if comment_at >= 0 else raw_value
        comment = raw_value[comment_at:].strip() if comment_at >= 0 else ''
        while (depth > 0 or in_string) and index + 1 < len(lines):
            index += 1
            follow = lines[index]
            depth, in_string, escaped, comment_at = scan_line(
                follow, depth, in_string, escaped)
            body = follow[:comment_at] if comment_at >= 0 else follow
            comment = follow[comment_at:].strip() if comment_at >= 0 else comment
            value += ' ' + body.strip()
        current.entries.append(Prop(key=key.strip(), value=value.strip(),
                                    start=start, end=index + 1,
                                    prefix=prefix.rstrip(), comment=comment))
        current.body_end = index + 1
        index += 1
    return sections


def parse(path: str) -> list[Section]:
    """Parse a .tscn/.tres file into its ordered sections."""
    with open(path, encoding='utf-8', errors='replace') as handle:
        return _parse_lines(handle.read().split('\n'))


def parse_text(text: str) -> list[Section]:
    """Same as `parse`, from an in-memory string (e.g. `git show <ref>:<path>`)."""
    return _parse_lines(text.split('\n'))


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
    """A node's scene path — exactly what its children spell in `parent=`.
    The root (no `parent` attr) is `.`, as .tscn itself writes it."""
    parent = node.attrs.get('parent')
    name = node.attrs.get('name', '?')
    if parent is None:
        return ROOT_PATH
    return name if parent == ROOT_PATH else f'{parent}{PATH_SEP}{name}'


def split_path(path: str) -> list[str]:
    """`"."` -> [], `"A/B"` -> ["A", "B"] — a scene path as segments from root."""
    if path in ('', ROOT_PATH):
        return []
    return [seg for seg in path.split(PATH_SEP) if seg]


def join_path(segments: list[str]) -> str:
    return PATH_SEP.join(segments) if segments else ROOT_PATH


def resolve_node_path(owner: list[str], literal: str) -> list[str] | None:
    """Resolve a relative NodePath literal against the node that carries it.

    Returns absolute segments from the scene root, or None when the path is
    absolute (`/root/...`) or walks above the root — neither is a scene-local
    reference and neither may be rewritten by a rename.
    """
    if literal.startswith(ABSOLUTE_PATH_PREFIX):
        return None
    segments = list(owner)
    for part in literal.split(PATH_SEP):
        if part in ('', SELF_SEG):
            continue
        if part == PARENT_SEG:
            if not segments:
                return None
            segments.pop()
            continue
        segments.append(part)
    return segments
