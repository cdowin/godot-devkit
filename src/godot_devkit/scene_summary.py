#!/usr/bin/env python3
"""scene_summary.py — compact, read-only view of a Godot .tscn / .tres.

Turns a scene (often 100k+ tokens of packed tile bytes) into a few-hundred-token
structured summary: ext/sub resources, the node tree with scalar @export props,
and a decoded bounds line per TileMapLayer. Big PackedXxxArray values are
summarized, never dumped. Pure parse — never writes, never boots Godot.

    make scene FILE=scenes/map/map.tscn
    python3 tools/dev/introspect/scene_summary.py <path> [--props]
"""
from __future__ import annotations

import argparse
from collections import defaultdict

from godot_devkit.tscn import (
    PACKED_ARRAY,
    REF_ARROW,
    RESOURCE_REF,
    Section,
    _basename,
    decode_tilemap_bounds,
    node_own_path,
    parse,
    resolve_ref,
)

# --- Presentation knobs -----------------------------------------------------
PROP_ELIDE_LEN = 70          # a scalar prop longer than this is summarized, not shown
SUBRES_KEY_PREVIEW = 6       # how many sub_resource field names to preview
INDENT = '  '
# Curated placement/composition props shown by default (`--props` shows all).
KEY_PROPS = frozenset((
    'position', 'facing', 'rotation', 'scale', 'definition', 'zone_type',
    'script', 'shape', 'tile_set', 'size', 'init_spawn', 'unlock_level',
    'tile_map_data',
))


def format_prop(key: str, value: str, ext: dict[str, dict]) -> str:
    """Render one `key = value` for display: decode tile data, summarize packed
    arrays, resolve resource refs, elide long scalars; pass short scalars through."""
    if key == 'tile_map_data':
        return f'{key}: {decode_tilemap_bounds(value)}'
    if PACKED_ARRAY.match(value):
        return f'{key}: <{value.split("(", 1)[0]}, elided>'
    if RESOURCE_REF.match(value):
        return f'{key}={resolve_ref(value, ext)}'
    if len(value) > PROP_ELIDE_LEN:
        return f'{key}: <{len(value)} chars elided>'
    return f'{key}={value}'


def print_tree(nodes: list[Section], ext: dict[str, dict], show_all: bool) -> None:
    children: dict[str, list[Section]] = defaultdict(list)
    root: Section | None = None
    for node in nodes:
        parent = node.attrs.get('parent')
        if parent is None:
            root = node
        else:
            children[parent].append(node)

    def describe(node: Section) -> str:
        kind = node.attrs.get('type')
        if kind is None and 'instance' in node.attrs:
            kind = 'instance ' + resolve_ref(node.attrs['instance'], ext).lstrip(REF_ARROW)
        shown = node.props if show_all else [p for p in node.props if p[0] in KEY_PROPS]
        suffix = ('  ' + '  '.join(format_prop(k, v, ext) for k, v in shown)) if shown else ''
        return f'{node.attrs.get("name", "?")} [{kind or "?"}]{suffix}'

    def walk(node: Section, depth: int) -> None:
        print(f'{INDENT * (depth + 1)}{describe(node)}')
        lookup = '.' if node is root else node_own_path(node)
        for child in children.get(lookup, []):
            walk(child, depth + 1)

    if root is not None:
        walk(root, 0)
    else:  # a .tres / headerless node set — no single root
        for node in nodes:
            walk(node, 0)


def print_summary(sections: list[Section], path: str, show_all: bool) -> None:
    scene = next((s for s in sections if s.kind in ('gd_scene', 'gd_resource')), None)
    ext = {s.attrs['id']: s.attrs for s in sections if s.kind == 'ext_resource'}
    subs = [s for s in sections if s.kind == 'sub_resource']
    nodes = [s for s in sections if s.kind == 'node']

    print(f'# {path}')
    if scene is not None:
        fmt = scene.attrs.get('format', '?')
        print(f'{scene.kind}  format={fmt}  uid={scene.attrs.get("uid", "-")}')

    print(f'\n## ext_resources ({len(ext)})')
    for res in ext.values():
        name = _basename(res.get('path') or res.get('uid', '?'))
        print(f'  [{res["id"]}] {res.get("type", "?")}  {name}')

    if subs:
        print(f'\n## sub_resources ({len(subs)})')
        for sub in subs:
            keys = ', '.join(k for k, _ in sub.props[:SUBRES_KEY_PREVIEW])
            print(f'  [{sub.attrs.get("id", "?")}] {sub.attrs.get("type", "?")}  {keys}')

    if nodes:
        print(f'\n## node tree ({len(nodes)})')
        print_tree(nodes, ext, show_all)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('file', help='path to a .tscn or .tres')
    parser.add_argument('--props', action='store_true',
                        help='show ALL scalar props per node (default: a curated subset)')
    args = parser.parse_args(argv)
    try:
        sections = parse(args.file)
    except OSError as err:
        parser.error(str(err))
    print_summary(sections, args.file, args.props)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
