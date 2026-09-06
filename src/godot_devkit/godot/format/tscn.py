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

import re
from dataclasses import dataclass, field

# --- Godot .tscn grammar ----------------------------------------------------
SECTION_HEADER = re.compile(r'^\[(\w+)\s*(.*)\]\s*$')
HEADER_ATTR = re.compile(r'(\w+)=("(?:[^"\\]|\\.)*"|\w+\("[^"]*"\)|[^\s\]]+)')
PACKED_ARRAY = re.compile(r'^Packed\w+Array\(')
RESOURCE_REF = re.compile(r'(Ext|Sub)Resource\("([^"]*)"\)')
NODE_PATH_LITERAL = re.compile(r'(\^?)NodePath\("([^"]*)"\)')
REF_ARROW = '→'

EXT_RESOURCE_ONLY = re.compile(r'^ExtResource\("([^"]*)"\)$')
EXT_RESOURCE_KIND = 'ext_resource'
NODE_KIND = 'node'
SCRIPT_PROP = 'script'

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
TILE_MAP_DATA_PROP = 'tile_map_data'
TILEMAP_LAYER_TYPE = 'TileMapLayer'


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


def strip_quotes(value: str) -> str:
    return value[1:-1] if len(value) >= 2 and value[0] == value[-1] == '"' else value


def basename(path: str) -> str:
    return path.rsplit(PATH_SEP, 1)[-1]


def scan_line(text: str, depth: int = 0, in_string: bool = False, escaped: bool = False,
              comment_char: str = COMMENT_CHAR,
              comment_in_brackets: bool = False) -> tuple[int, bool, bool, int]:
    """Consume one line, tracking bracket depth with STRING AWARENESS.

    Returns the carried (depth, in_string, escaped) plus the index at which a
    top-level comment starts (-1 if none). Brackets and comment characters
    inside a quoted string do not count — which is the whole reason this exists
    rather than a `line.count('(')` heuristic. `comment_char` is `;` for the
    resource format and `#` for GDScript, whose exports this also scans.
    `comment_in_brackets` is the one place the two grammars differ: a `;` inside
    a multi-line `.tres` value is DATA, a `#` inside a multi-line GDScript
    `enum {}` or array literal is a COMMENT.
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
        elif char == comment_char and (comment_in_brackets or depth <= 0):
            return depth, in_string, escaped, index
    return depth, in_string, escaped, -1


def parse_lines(lines: list[str]) -> list[Section]:
    """The one parse. Sections carry line spans; callers that only want the
    (key, value) view read `Section.props` and never notice."""
    sections: list[Section] = []
    current: Section | None = None
    index = 0
    while index < len(lines):
        line = lines[index]
        header = SECTION_HEADER.match(line)
        if header:
            attrs = {k: strip_quotes(v) for k, v in HEADER_ATTR.findall(header.group(2))}
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
        return parse_lines(handle.read().split('\n'))


def parse_text(text: str) -> list[Section]:
    """Same as `parse`, from an in-memory string (e.g. `git show <ref>:<path>`)."""
    return parse_lines(text.split('\n'))


def tilemap_layers(sections: list[Section]) -> list[Section]:
    """Every TileMapLayer node in a scene, in file order.

    A node qualifies by TYPE or by carrying `tile_map_data`: an instanced or
    scripted layer has no `type=` of its own, and skipping it would let `tiles`
    report a map as layer-less while its cells sit right there in the file.
    """
    return [s for s in sections
            if s.kind == NODE_KIND and (s.attrs.get('type') == TILEMAP_LAYER_TYPE
                                        or s.prop(TILE_MAP_DATA_PROP) is not None)]


def find_tilemap_layer(sections: list[Section], name: str) -> Section:
    """The one TileMapLayer addressed by `name` — a node name OR a full path.

    A full PATH wins over a bare name, because a path is unique and a name is
    not: that is what keeps `Sandbox/WallLayer` addressable in a scene that also
    has a root-level `WallLayer`. Failing that, refuses on both failure modes
    rather than picking — an unknown name, and a name two layers answer to
    (legal in a scene, and exactly when a silent choice paints the wrong grid).
    """
    layers = tilemap_layers(sections)
    exact = [s for s in layers if node_own_path(s) == name]
    if len(exact) == 1:
        return exact[0]
    matches = [s for s in layers if s.attrs.get('name') == name]
    if not matches:
        known = ', '.join(node_own_path(s) for s in layers) or '(none)'
        raise TscnError(f'no TileMapLayer named {name!r}; this scene has: {known}')
    if len(matches) > 1:
        paths = ', '.join(node_own_path(s) for s in matches)
        raise TscnError(f'{name!r} is ambiguous — {len(matches)} layers answer to it '
                        f'({paths}); address one by its full path')
    return matches[0]


def resolve_ref(value: str, ext: dict[str, dict]) -> str:
    """Render an Ext/SubResource("id") reference as `→<basename>` (Ext) or `→<id>`."""
    match = RESOURCE_REF.match(value)
    if not match:
        return value
    kind, ref_id = match.group(1), match.group(2)
    if kind == 'Ext' and ref_id in ext:
        target = ext[ref_id]
        return REF_ARROW + basename(target.get('path') or target.get('uid', '?'))
    return REF_ARROW + ref_id


def ext_index(sections: list[Section]) -> dict[str, dict]:
    """`{ext_resource id: its header attrs}` — how a `ExtResource("id")` resolves."""
    return {s.attrs['id']: s.attrs for s in sections
            if s.kind == EXT_RESOURCE_KIND and 'id' in s.attrs}


def ref_path(value: str, ext: dict[str, dict]) -> str | None:
    """The `res://` path an `ExtResource("id")` value points at, or None."""
    match = EXT_RESOURCE_ONLY.match(value.strip())
    return ext.get(match.group(1), {}).get('path') if match else None


def script_path(section: Section, ext: dict[str, dict]) -> str | None:
    """The `res://` path of the section's `script = ExtResource(...)`, or None."""
    prop = section.prop(SCRIPT_PROP)
    return ref_path(prop.value, ext) if prop is not None else None


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
