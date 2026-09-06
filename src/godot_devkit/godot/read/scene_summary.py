#!/usr/bin/env python3
"""scene_summary.py — compact, read-only view of a Godot .tscn / .tres.

Turns a scene (often 100k+ tokens of packed tile bytes) into a few-hundred-token
structured summary: ext/sub resources, the node tree with scalar @export props,
and a decoded bounds line per TileMapLayer. `--props` additionally renders the
PROPERTY VALUES of every `[resource]`/`[sub_resource]` body (default: key names
only), with each printed sub_resource id verbatim — the address the scene write
verbs take. Big PackedXxxArray values are summarized, never dumped. Pure parse —
never writes, never boots Godot.

    make scene FILE=scenes/map/map.tscn
    python3 tools/dev/introspect/scene_summary.py <path> [--props]
"""
from __future__ import annotations

import argparse
import re
from collections import defaultdict

from godot_devkit.godot.format.tilemap import decode_tilemap_bounds
from godot_devkit.godot.format.tscn import (
    PACKED_ARRAY,
    REF_ARROW,
    RESOURCE_REF,
    TILE_MAP_DATA_PROP,
    Section,
    basename,
    node_own_path,
    parse,
    resolve_ref,
)

# An array literal whose members are ALL Ext/SubResource refs — with or
# without a typed `Array[T](...)` wrapper. Rendered as a ref list rather than
# elided: the member ids are the addresses the scene write verbs take.
REF_ARRAY = re.compile(r'^(?:Array\[[\w. ]+\]\()?\[(?P<body>.+)\]\)?$')

# --- Presentation knobs -----------------------------------------------------
PROP_ELIDE_LEN = 70          # a scalar prop longer than this is summarized, not shown
SUBRES_KEY_PREVIEW = 6       # how many sub_resource field names to preview
INDENT = '  '
# Curated placement/composition props shown by default (`--props` shows all).
KEY_PROPS = frozenset((
    'position', 'facing', 'rotation', 'scale', 'definition', 'zone_type',
    'script', 'shape', 'tile_set', 'size', 'init_spawn', 'unlock_level',
    TILE_MAP_DATA_PROP,
))


def format_value(key: str, value: str, ext: dict[str, dict]) -> str:
    """Render one scalar prop value for display: decode tile data, resolve
    resource refs, elide long/packed values; pass short scalars through."""
    if key == TILE_MAP_DATA_PROP:
        return decode_tilemap_bounds(value)
    if PACKED_ARRAY.match(value):
        return f'<{value.split("(", 1)[0]}, elided>'
    if RESOURCE_REF.match(value):
        return resolve_ref(value, ext)
    if len(value) > PROP_ELIDE_LEN:
        return f'<{len(value)} chars elided>'
    return value


def format_prop(key: str, value: str, ext: dict[str, dict]) -> str:
    """`format_value`, with its key: `key=value` for a scalar or a resolved
    ref, `key: <summary>` when the value was decoded, summarized or elided."""
    rendered = format_value(key, value, ext)
    if RESOURCE_REF.match(value) or rendered == value:
        return f'{key}={rendered}'
    return f'{key}: {rendered}'


def format_resource_prop(key: str, value: str, ext: dict[str, dict]) -> str:
    """`format_prop`, plus one case node props rarely hit: an array whose
    members are all resource refs renders as `key: [→a, →b]` instead of
    eliding — inside a `[resource]`/`[sub_resource]` body those ids ARE the
    structure (and the write-verb addresses), not bulk."""
    match = REF_ARRAY.match(value)
    if match:
        members = [m.strip() for m in match.group('body').split(',')]
        if all(RESOURCE_REF.fullmatch(m) for m in members):
            refs = ', '.join(resolve_ref(m, ext) for m in members)
            return f'{key}: [{refs}]'
    return format_prop(key, value, ext)


def key_preview(section: Section) -> str:
    """The first few property NAMES — the default (no `--props`) view of a
    `[resource]`/`[sub_resource]` body."""
    return ', '.join(k for k, _ in section.props[:SUBRES_KEY_PREVIEW])


def print_resource_props(section: Section, ext: dict[str, dict]) -> None:
    """Every property of a resource-bodied section, one value per indented
    line — the `--props` view. Additive: the preview line above it stays."""
    for key, value in section.props:
        print(f'{INDENT * 2}{format_resource_prop(key, value, ext)}')


def describe_node(node: Section, ext: dict[str, dict]) -> str:
    kind = node.attrs.get('type')
    if kind is None and 'instance' in node.attrs:
        kind = 'instance ' + resolve_ref(node.attrs['instance'], ext).lstrip(REF_ARROW)
    return f'{node.attrs.get("name", "?")} [{kind or "?"}]'


def print_tree(nodes: list[Section], ext: dict[str, dict], show_all: bool,
               show_paths: bool = False) -> None:
    children: dict[str, list[Section]] = defaultdict(list)
    root: Section | None = None
    for node in nodes:
        parent = node.attrs.get('parent')
        if parent is None:
            root = node
        else:
            children[parent].append(node)

    def describe(node: Section) -> str:
        shown = node.props if show_all else [p for p in node.props if p[0] in KEY_PROPS]
        suffix = ('  ' + '  '.join(format_prop(k, v, ext) for k, v in shown)) if shown else ''
        return f'{describe_node(node, ext)}{suffix}'

    def walk(node: Section, depth: int) -> None:
        if show_paths:
            # The address the write verbs take, so read output is write input.
            print(f'{INDENT}{node_own_path(node):<48} {describe(node)}')
        else:
            print(f'{INDENT * (depth + 1)}{describe(node)}')
        lookup = '.' if node is root else node_own_path(node)
        for child in children.get(lookup, []):
            walk(child, depth + 1)

    if root is not None:
        walk(root, 0)
    else:  # a .tres / headerless node set — no single root
        for node in nodes:
            walk(node, 0)


def print_summary(sections: list[Section], path: str, show_all: bool,
                  show_paths: bool = False) -> None:
    scene = next((s for s in sections if s.kind in ('gd_scene', 'gd_resource')), None)
    ext = {s.attrs['id']: s.attrs for s in sections if s.kind == 'ext_resource'}
    subs = [s for s in sections if s.kind == 'sub_resource']
    resources = [s for s in sections if s.kind == 'resource']
    nodes = [s for s in sections if s.kind == 'node']

    print(f'# {path}')
    if scene is not None:
        fmt = scene.attrs.get('format', '?')
        print(f'{scene.kind}  format={fmt}  uid={scene.attrs.get("uid", "-")}')

    print(f'\n## ext_resources ({len(ext)})')
    for res in ext.values():
        name = basename(res.get('path') or res.get('uid', '?'))
        print(f'  [{res["id"]}] {res.get("type", "?")}  {name}')

    if subs:
        print(f'\n## sub_resources ({len(subs)})')
        for sub in subs:
            # The [id] is verbatim from the file — the exact address
            # `scene set --sub-resource <id>` takes. Read output is write input.
            print(f'  [{sub.attrs.get("id", "?")}] {sub.attrs.get("type", "?")}'
                  f'  {key_preview(sub)}')
            if show_all:
                print_resource_props(sub, ext)

    if resources:  # the [resource] body of a .tres; its type lives on the header
        rtype = '?'
        if scene is not None:
            rtype = scene.attrs.get('script_class') or scene.attrs.get('type', '?')
        print(f'\n## resource ({rtype})')
        for res in resources:
            print(f'{INDENT}{key_preview(res)}')
            if show_all:
                print_resource_props(res, ext)

    if nodes:
        print(f'\n## node tree ({len(nodes)})')
        print_tree(nodes, ext, show_all, show_paths)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('file', help='path to a .tscn or .tres')
    parser.add_argument('--props', action='store_true',
                        help='show ALL scalar props per node, and property '
                             'VALUES per [resource]/[sub_resource] body '
                             '(default: a curated subset / key names)')
    parser.add_argument('--paths', action='store_true',
                        help='print each node\'s full path — the address the '
                             'scene write verbs take')
    args = parser.parse_args(argv)
    try:
        sections = parse(args.file)
    except OSError as err:
        parser.error(str(err))
    print_summary(sections, args.file, args.props, args.paths)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
