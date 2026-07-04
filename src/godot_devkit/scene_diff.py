#!/usr/bin/env python3
"""scene_diff.py — compact, read-only diff of a Godot .tscn / .tres.

You hand-author scenes, and a raw `.tscn` diff is an unreadable wall of
re-serialized bytes (packed tile data, renumbered resource ids). This diffs
the *parsed structure* instead: nodes added / removed / reparented / prop-
changed, ext/sub resources added / removed, and `tile_map_data` compared as
decoded bounds + cell count rather than base64 bytes. Pure parse — never
writes, never boots Godot.

    make scene-diff FILE=scenes/main.tscn [ARGS=--git=HEAD~3]
    make scene-diff OLD=<old.tscn> NEW=<new.tscn>
    python3 tools/dev/introspect/scene_diff.py <file.tscn> [--git <ref>]
    python3 tools/dev/introspect/scene_diff.py <old.tscn> <new.tscn>
"""
from __future__ import annotations

import argparse
import subprocess
from dataclasses import dataclass

from godot_devkit.tscn import (
    PACKED_ARRAY,
    REF_ARROW,
    RESOURCE_REF,
    Section,
    _basename,
    decode_tilemap_bounds,
    node_own_path,
    parse,
    parse_text,
    resolve_ref,
)

# --- Presentation knobs -----------------------------------------------------
PROP_ELIDE_LEN = 70          # a scalar prop longer than this is summarized, not shown
ADD_MARK = '+'
REMOVE_MARK = '-'
CHANGE_MARK = '~'
DEFAULT_GIT_REF = 'HEAD'


@dataclass
class SceneModel:
    """The pieces of a parsed scene relevant to diffing."""
    ext_by_key: dict[tuple[str, str], dict]   # (type, basename) -> attrs
    subs_by_key: dict[tuple[str, str], Section]  # (type, id) -> section
    nodes_by_path: dict[str, Section]         # own scene path -> node
    ext: dict[str, dict]                      # id -> attrs (for resolving refs)


def _root_own_path(node: Section) -> str:
    return node.attrs.get('name', '?')


def build_model(sections: list[Section]) -> SceneModel:
    ext = {s.attrs['id']: s.attrs for s in sections if s.kind == 'ext_resource'}
    ext_by_key = {
        (a.get('type', '?'), _basename(a.get('path') or a.get('uid', '?'))): a
        for a in ext.values()
    }
    subs_by_key = {
        (s.attrs.get('type', '?'), s.attrs.get('id', '?')): s
        for s in sections if s.kind == 'sub_resource'
    }
    nodes = [s for s in sections if s.kind == 'node']
    root = next((n for n in nodes if 'parent' not in n.attrs), None)
    nodes_by_path = {
        (_root_own_path(n) if n is root else node_own_path(n)): n for n in nodes
    }
    return SceneModel(ext_by_key, subs_by_key, nodes_by_path, ext)


def format_value(key: str, value: str, ext: dict[str, dict]) -> str:
    """Render one scalar prop value for a diff line: decode tile data, resolve
    resource refs, elide long/packed values; pass short scalars through."""
    if key == 'tile_map_data':
        return decode_tilemap_bounds(value)
    if PACKED_ARRAY.match(value):
        return f'<{value.split("(", 1)[0]}, elided>'
    if RESOURCE_REF.match(value):
        return resolve_ref(value, ext)
    if len(value) > PROP_ELIDE_LEN:
        return f'<{len(value)} chars elided>'
    return value


def diff_props(old: Section, new: Section, old_ext: dict, new_ext: dict) -> list[str]:
    old_props = dict(old.props)
    new_props = dict(new.props)
    lines: list[str] = []
    for key in sorted(set(old_props) | set(new_props)):
        if key not in old_props:
            lines.append(f'    {ADD_MARK} {key}={format_value(key, new_props[key], new_ext)}')
        elif key not in new_props:
            lines.append(f'    {REMOVE_MARK} {key}={format_value(key, old_props[key], old_ext)}')
        elif old_props[key] != new_props[key]:
            before = format_value(key, old_props[key], old_ext)
            after = format_value(key, new_props[key], new_ext)
            if before != after:
                lines.append(f'    {CHANGE_MARK} {key}: {before} {REF_ARROW} {after}')
    return lines


def describe_node(node: Section, ext: dict[str, dict]) -> str:
    kind = node.attrs.get('type')
    if kind is None and 'instance' in node.attrs:
        kind = 'instance ' + resolve_ref(node.attrs['instance'], ext).lstrip(REF_ARROW)
    return f'{node.attrs.get("name", "?")} [{kind or "?"}]'


def diff_nodes(old: SceneModel, new: SceneModel) -> list[str]:
    old_paths, new_paths = set(old.nodes_by_path), set(new.nodes_by_path)
    # A name -> [paths] index, not name -> path: sibling names must be unique
    # in Godot, but the SAME name is common across different subtrees in this
    # codebase (repeated "ControlSlot"/"UiSlider" rows, "CollisionShape2D"
    # under different enemies, …). A reparent match is only trustworthy when
    # exactly one old candidate shares the name — otherwise guessing which
    # one moved would silently pair the wrong node.
    old_paths_by_name: dict[str, list[str]] = {}
    for p, n in old.nodes_by_path.items():
        old_paths_by_name.setdefault(n.attrs.get('name'), []).append(p)
    lines: list[str] = []

    for path in sorted(old_paths & new_paths):
        prop_lines = diff_props(old.nodes_by_path[path], new.nodes_by_path[path], old.ext, new.ext)
        if prop_lines:
            lines.append(f'  {CHANGE_MARK} {path}')
            lines.extend(prop_lines)

    only_new = new_paths - old_paths
    only_old = old_paths - new_paths
    reparented_old_paths: set[str] = set()
    for path in sorted(only_new):
        node = new.nodes_by_path[path]
        name = node.attrs.get('name')
        candidates = [p for p in old_paths_by_name.get(name, []) if p in only_old]
        if len(candidates) == 1:
            old_path = candidates[0]
            reparented_old_paths.add(old_path)
            lines.append(f'  {CHANGE_MARK} {old_path} {REF_ARROW} {path}  (reparented)')
            prop_lines = diff_props(old.nodes_by_path[old_path], node, old.ext, new.ext)
            lines.extend(prop_lines)
        else:
            lines.append(f'  {ADD_MARK} {path}  {describe_node(node, new.ext)}')

    for path in sorted(only_old - reparented_old_paths):
        node = old.nodes_by_path[path]
        lines.append(f'  {REMOVE_MARK} {path}  {describe_node(node, old.ext)}')

    return lines


def diff_resources(old: SceneModel, new: SceneModel) -> list[str]:
    lines: list[str] = []
    ext_added = sorted(new.ext_by_key.keys() - old.ext_by_key.keys())
    ext_removed = sorted(old.ext_by_key.keys() - new.ext_by_key.keys())
    if ext_added or ext_removed:
        lines.append('  ext_resources:')
        lines.extend(f'    {ADD_MARK} {t} {name}' for t, name in ext_added)
        lines.extend(f'    {REMOVE_MARK} {t} {name}' for t, name in ext_removed)

    sub_added = sorted(new.subs_by_key.keys() - old.subs_by_key.keys())
    sub_removed = sorted(old.subs_by_key.keys() - new.subs_by_key.keys())
    if sub_added or sub_removed:
        lines.append('  sub_resources:')
        lines.extend(f'    {ADD_MARK} {t} [{sub_id}]' for t, sub_id in sub_added)
        lines.extend(f'    {REMOVE_MARK} {t} [{sub_id}]' for t, sub_id in sub_removed)

    return lines


def print_diff(old_sections: list[Section], new_sections: list[Section],
               old_label: str, new_label: str) -> bool:
    """Print the diff; return True if anything differed."""
    old_model = build_model(old_sections)
    new_model = build_model(new_sections)

    resource_lines = diff_resources(old_model, new_model)
    node_lines = diff_nodes(old_model, new_model)

    if not resource_lines and not node_lines:
        print(f'# {old_label} {REF_ARROW} {new_label}: no structural differences')
        return False

    print(f'# {old_label} {REF_ARROW} {new_label}')
    if resource_lines:
        print('\n## resources')
        print('\n'.join(resource_lines))
    if node_lines:
        print('\n## nodes')
        print('\n'.join(node_lines))
    return True


def read_at_git_ref(path: str, ref: str) -> str:
    result = subprocess.run(
        ['git', 'show', f'{ref}:{path}'], capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise SystemExit(f"error: 'git show {ref}:{path}' failed: {result.stderr.strip()}")
    return result.stdout


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('file', help='path to a .tscn or .tres (or the OLD file in two-file mode)')
    parser.add_argument('new_file', nargs='?',
                        help='the NEW file, for two-file mode (omit to diff against --git)')
    parser.add_argument('--git', metavar='REF', nargs='?', const=DEFAULT_GIT_REF,
                        help=f'diff FILE@REF vs the working tree (default ref: {DEFAULT_GIT_REF})')
    args = parser.parse_args(argv)

    if args.new_file:
        if args.git:
            parser.error('--git is not compatible with a two-file diff')
        try:
            old_sections = parse(args.file)
            new_sections = parse(args.new_file)
        except OSError as err:
            parser.error(str(err))
        old_label, new_label = args.file, args.new_file
    else:
        ref = args.git or DEFAULT_GIT_REF
        old_sections = parse_text(read_at_git_ref(args.file, ref))
        try:
            new_sections = parse(args.file)
        except OSError as err:
            parser.error(str(err))
        old_label, new_label = f'{args.file}@{ref}', f'{args.file}@working-tree'

    print_diff(old_sections, new_sections, old_label, new_label)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
