"""scene_edit.py — the narrow scene writer: `scene set` and `scene add`.

    godot-devkit scene set      <file> <node-path> <prop> <value>
    godot-devkit scene set      <file> --resource <prop> <value>
    godot-devkit scene set      <file> --sub-resource <id> <prop> <value>
    godot-devkit scene set      <file> <node-path> <prop> --new-sub-resource <res://x.gd|Type> [key=value ...]
    godot-devkit scene add      <file> <parent-path> <name> <type> [--script res://x.gd]
                                [--tile-set res://x.tres] [--z N] [--group G ...]
    godot-devkit scene add      <file> <parent-path> <name> --instance res://x.tscn

Godot writes scenes; these two verbs exist for the case its headless save
gets wrong: an inherited scene with overrides or local materials, where a
load-and-save drops shader parameters and tile overrides. Each edits only
its own lines.

Nodes are addressed by PATH — the scene root is `.`, its child is `Name`,
deeper is `Parent/Name`, as `godot-devkit scene --paths` prints. `--sub-resource`
takes the id `godot-devkit scene --props` prints; `--resource` is the one
`[resource]` body a .tres has. Untouched lines are never rewritten; a verb that
cannot express the result truthfully REFUSES. `--dry-run` prints the unified
diff instead of writing; running a verb twice touches nothing the second time.

`set --new-sub-resource` makes a `[sub_resource]` — of an engine type, or a
`Resource` carrying a res:// script — with the `key=value` properties given
as Godot literals (quote a string: `id='"spawn_a"'`), and points the property
at it. Run again, it finds the same sub_resource and is `unchanged`; a
property that already holds a different sub_resource is refused (edit that one
with `--sub-resource <id>`).

New nodes get a `unique_id=` when the file's nodes already carry Godot 4.6+'s
node ids; the id is derived from the node path, so a retry writes the same bytes.
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path

from godot_devkit.core.project import repo_root
from godot_devkit.godot.format.tscn import (EXT_RESOURCE_ONLY, Section,
                                            TscnError, join_path)
from godot_devkit.godot.format.tscn_document import TscnDocument
from godot_devkit.godot.index.uid_index import RES_PREFIX, UidIndex
from godot_devkit.godot.write import (file_exists, load_scene_or_refuse,
                                      render_diff)

VERBS = ('set', 'add')
UNCHANGED = 'unchanged'
EXIT_OK = 0
EXIT_REFUSED = 1
EXIT_USAGE = 2
PROJECT_FILE = 'project.godot'
TILEMAP_LAYER = 'TileMapLayer'
TILE_SET_TYPE = 'TileSet'
TILE_SET_PROP = 'tile_set'
Z_INDEX_PROP = 'z_index'
Z_INDEX_DEFAULT = 0
SCRIPT_TYPE = 'Script'
SCRIPTED_SUB_TYPE = 'Resource'
SUB_REF = 'SubResource("{id}")'
SUB_REF_ONLY = re.compile(r'^SubResource\("([^"]*)"\)$')
TYPE_NAME = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*$')
PROP_KEY = re.compile(r'^[A-Za-z_][A-Za-z0-9_/:]*$')
GROUPS_ATTR = re.compile(r'\bgroups=\[([^\]]*)\]')
GROUP_NAME = re.compile(r'"((?:[^"\\]|\\.)*)"')


def _project_root(scene_path: Path) -> Path:
    """The scene's own `project.godot` ancestor when it has one, the invoking
    repo otherwise — a scene being authored into a scratch directory still
    resolves its neighbours."""
    root = next((p for p in scene_path.resolve().parents
                 if (p / PROJECT_FILE).is_file()), None)
    return root or repo_root()


def uid_resolver(scene_path: Path):
    """The uid lookup a document needs when it mints an ext_resource ref.

    Injected from here because `format/` must not import `index/` (layers point
    downward). Built lazily on first call, so the verbs that mint no refs never
    pay for a repo scan.
    """
    def resolve(res_path: str) -> str | None:
        return UidIndex(_project_root(scene_path)).of(res_path)
    return resolve


def _child_path(doc: TscnDocument, parent_path: str, name: str) -> str:
    """The canonical path of `name` under `parent_path`.

    Canonical, not concatenated: the root answers to `.` AND to its own name, so
    `Sandbox` + `Deep` is the path `Deep`, not `Sandbox/Deep`. Getting this wrong
    is how an idempotence check silently becomes a second edit.
    """
    return join_path(list(doc.node_path(doc.node(parent_path))) + [name])


def _section_of(doc: TscnDocument, args) -> Section:
    if args.resource:
        return doc.resource_body()
    if args.sub_resource is not None:
        return doc.sub_resource(args.sub_resource)
    return doc.node(args.node_path)


def _do_set(doc: TscnDocument, args) -> str:
    if args.new_sub_resource is not None:
        return _do_set_new_sub_resource(doc, args)
    section = _section_of(doc, args)
    existing = section.prop(args.prop)
    if existing is not None and existing.value == args.value:
        return UNCHANGED
    return doc.set_section_prop(section, args.prop, args.value)


def _pairs(specs: list[str]) -> tuple[tuple[str, str], ...]:
    """`key=value` arguments -> ordered pairs; refuses a pair it cannot read."""
    pairs: dict[str, str] = {}
    for spec in specs:
        key, sep, value = spec.partition('=')
        key = key.strip()
        if not sep or not PROP_KEY.match(key) or not value.strip():
            raise TscnError(f'{spec!r} is not key=value')
        if key == 'script' or key in pairs:
            raise TscnError(f'{key!r} is given twice (a script is the type argument)')
        pairs[key] = value.strip()
    return tuple(pairs.items())


def _sub_resource_shape(doc: TscnDocument, kind: str) -> tuple[str, str | None]:
    """The sub_resource type for `kind`, and its script path when it is one."""
    if kind.startswith(RES_PREFIX):
        _refuse_missing(doc, kind)
        return SCRIPTED_SUB_TYPE, kind
    if not TYPE_NAME.match(kind):
        raise TscnError(f'{kind!r} is neither a res:// script nor a type name')
    return kind, None


def _same_sub_resource(doc: TscnDocument, sub: Section, sub_type: str,
                       script: str | None, props: tuple[tuple[str, str], ...]) -> bool:
    have = list(sub.props)
    if script is not None:
        if not have or have[0][0] != 'script':
            return False
        match = EXT_RESOURCE_ONLY.match(have.pop(0)[1].strip())
        ext = doc.ext_resources().get(match.group(1)) if match else None
        if ext is None or ext.attrs.get('path') != script:
            return False
    return sub.attrs.get('type') == sub_type and have == list(props)


def _do_set_new_sub_resource(doc: TscnDocument, args) -> str:
    kind, *specs = args.new_sub_resource
    props = _pairs(specs)
    sub_type, script = _sub_resource_shape(doc, kind)
    current = _section_of(doc, args).prop(args.prop)
    held = SUB_REF_ONLY.match(current.value.strip()) if current is not None else None
    if held is not None:
        sub = doc.sub_resource(held.group(1))
        if _same_sub_resource(doc, sub, sub_type, script, props):
            return UNCHANGED
        raise TscnError(f'{args.prop} already holds SubResource("{held.group(1)}") '
                        f'with other content — edit it with --sub-resource '
                        f'{held.group(1)}, or set the property first')
    if script is not None:
        props = (('script', doc.ext_ref(script, SCRIPT_TYPE)), *props)
    owner = args.node_path or args.sub_resource or 'resource'
    sub_id = doc.add_sub_resource(sub_type, f'{owner}:{args.prop}', props)
    doc.set_section_prop(_section_of(doc, args), args.prop, SUB_REF.format(id=sub_id))
    return 'added'


def _instanced_path(doc: TscnDocument, node: Section) -> str | None:
    """The res:// path an instance node's `instance=ExtResource(...)` names."""
    match = EXT_RESOURCE_ONLY.match(node.attrs.get('instance', ''))
    if match is None:
        return None
    ext = doc.ext_resources().get(match.group(1))
    return ext.attrs.get('path') if ext is not None else None


def _do_add(doc: TscnDocument, args) -> str:
    path = _child_path(doc, args.parent_path, args.name)
    if args.instance is None:
        if doc.has_node(path):
            existing = doc.node(path)
            if existing.attrs.get('type') != args.type:
                raise TscnError(f'{path!r} already exists as a '
                                f'{existing.attrs.get("type") or "instance"}')
            _refuse_other_layer_settings(doc, existing, path, args)
            return UNCHANGED
        props: list[tuple[str, str]] = []
        if args.z not in (None, Z_INDEX_DEFAULT):   # the saver omits a default
            props.append((Z_INDEX_PROP, str(args.z)))
        if args.tile_set is not None:
            _refuse_missing(doc, args.tile_set)
            props.append((TILE_SET_PROP, doc.ext_ref(args.tile_set, TILE_SET_TYPE)))
        doc.add_node(args.parent_path, args.name, args.type, args.script,
                     groups=tuple(args.group or ()), props=tuple(props))
        return 'added'
    if doc.has_node(path):
        existing = doc.node(path)
        if existing.attrs.get('type') is not None:
            raise TscnError(f'{path!r} already exists as a '
                            f'{existing.attrs["type"]}')
        current = _instanced_path(doc, existing)
        if current == args.instance:
            return UNCHANGED
        raise TscnError(f'{path!r} already instances {current or "another scene"!r}')
    _refuse_bad_instance_target(doc, args.instance)
    doc.add_instance_node(args.parent_path, args.name, args.instance)
    return 'added'


def _refuse_other_layer_settings(doc: TscnDocument, node: Section, path: str,
                                 args) -> None:
    """An existing node is the requested one only if every flag agrees: a
    retry is a no-op, a different request is a refusal, never a silent pass."""
    differs = []
    if args.z is not None:
        held = node.prop(Z_INDEX_PROP)
        current = held.value.strip() if held else str(Z_INDEX_DEFAULT)
        if current != str(args.z):
            differs.append(f'{Z_INDEX_PROP}={current}')
    if args.tile_set is not None:
        held = node.prop(TILE_SET_PROP)
        match = EXT_RESOURCE_ONLY.match(held.value.strip()) if held else None
        ext = doc.ext_resources().get(match.group(1)) if match else None
        if ext is None or ext.attrs.get('path') != args.tile_set:
            differs.append(f'{TILE_SET_PROP}={ext.attrs.get("path") if ext else "unset"}')
    # Read off the header line: the attr parser stops a bare value at the
    # first space, and `groups=["a", "b"]` has one.
    held = GROUPS_ATTR.search(doc.lines[node.header_line])
    groups = set(GROUP_NAME.findall(held.group(1))) if held else set()
    missing = [g for g in args.group or () if g not in groups]
    if missing:
        differs.append(f'not in group(s) {", ".join(missing)}')
    if differs:
        raise TscnError(f'{path!r} already exists with {"; ".join(differs)} — '
                        f'change it with `scene set`')


def _refuse_missing(doc: TscnDocument, res_path: str) -> None:
    """A ref to a file that is not there is refused, not written."""
    if not res_path.startswith(RES_PREFIX):
        raise TscnError(f'{res_path!r} is not a {RES_PREFIX} path')
    if doc.path is None or not file_exists(
            _project_root(doc.path) / res_path[len(RES_PREFIX):]):
        raise TscnError(f'{res_path} does not exist on disk — refusing to '
                        f'reference a file that is not there')


def _refuse_bad_instance_target(doc: TscnDocument, res_path: str) -> None:
    """The two lies an instance ref could be born with, refused up front: a
    target that is not there (retargeting a scene onto nothing), and a ref
    with no uid — Godot writes instance refs uid+path, and minting a uid here
    would be invention, not repair."""
    _refuse_missing(doc, res_path)
    if doc.uid_resolver is None or doc.uid_resolver(res_path) is None:
        raise TscnError(f'{res_path} has no resolvable uid (header, sidecar, '
                        f'or existing repo ref) — minting one is invention; '
                        f'save it once in the editor to give it a uid')


HANDLERS = {'set': _do_set, 'add': _do_add}


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog='godot-devkit scene', description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    subs = parser.add_subparsers(dest='verb', required=True)

    def add_verb(name: str, *fields: str) -> argparse.ArgumentParser:
        # EVERY subverb goes through here, so `file` and `--dry-run` are
        # attached in one place and a new subverb cannot forget either —
        # `set`/`add` add their optional positionals/flags on the result.
        sub = subs.add_parser(name)
        sub.add_argument('file')
        for field in fields:
            sub.add_argument(field)
        sub.add_argument('--dry-run', action='store_true',
                         help='print the unified diff instead of writing')
        return sub

    setter = add_verb('set')
    setter.add_argument('node_path', nargs='?',
                        help='the node to set on (omit with --resource / '
                             '--sub-resource)')
    setter.add_argument('prop')
    setter.add_argument('value', nargs='?')
    setter.add_argument('--resource', action='store_true',
                        help='address the [resource] body of a .tres')
    setter.add_argument('--sub-resource', dest='sub_resource', metavar='ID',
                        help='address a [sub_resource] by the id '
                             '`scene <file> --props` prints')
    setter.add_argument('--new-sub-resource', dest='new_sub_resource', nargs='+',
                        metavar='ARG',
                        help='<res://script.gd | Type> [key=value ...]: make a '
                             '[sub_resource] (values are Godot literals) and point '
                             'the property at it, in place of <value>')
    adder = add_verb('add', 'parent_path', 'name')
    adder.add_argument('type', nargs='?',
                       help='the node type (omit with --instance)')
    adder.add_argument('--script',
                       help='res:// path to a .gd; its .uid sidecar is used so '
                            'the new ext_resource ref is born canonical')
    adder.add_argument('--instance', metavar='RES_PATH',
                       help='instance this res:// scene instead of typing the '
                            'node; the ref is minted from the scene\'s own uid')
    adder.add_argument('--tile-set', dest='tile_set', metavar='RES_PATH',
                       help='a TileMapLayer\'s res:// TileSet')
    adder.add_argument('--z', type=int, metavar='N', help='the node\'s z_index')
    adder.add_argument('--group', action='append', metavar='G',
                       help='add the node to group G (repeatable)')
    return parser


def _check_usage(parser: argparse.ArgumentParser, args) -> None:
    """The exactly-one rules argparse cannot spell (exit 2, before any I/O)."""
    if args.verb == 'set':
        # `value` is optional (`--new-sub-resource` stands in for it), so with
        # a resource-plane address after the positionals, argparse hands the
        # prop to `node_path`: shift it back.
        if (args.value is None and args.new_sub_resource is None
                and (args.resource or args.sub_resource is not None)):
            args.node_path, args.prop, args.value = None, args.node_path, args.prop
        modes = [args.node_path is not None, args.resource,
                 args.sub_resource is not None]
        if sum(modes) != 1:
            parser.error('set takes exactly one address: a <node-path>, '
                         '--resource, or --sub-resource <id>')
        if (args.value is None) == (args.new_sub_resource is None):
            parser.error('set takes exactly one of <value> or --new-sub-resource')
    if args.verb == 'add':
        if (args.type is None) == (args.instance is None):
            parser.error('add takes exactly one of <type> or '
                         '--instance <res://scene.tscn>')
        if args.instance is not None and args.script is not None:
            parser.error('--script cannot combine with --instance — the '
                         'instanced scene owns its script')
        if args.instance is not None and (args.tile_set or args.z is not None
                                          or args.group):
            parser.error('--tile-set, --z and --group are for a typed node, '
                         'not --instance')
        if args.tile_set is not None and args.type != TILEMAP_LAYER:
            parser.error(f'--tile-set is for a {TILEMAP_LAYER}, not {args.type}')


def main(argv: list[str]) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    _check_usage(parser, args)
    path = Path(args.file)
    if not file_exists(path):
        print(f'godot-devkit scene {args.verb}: no such file: {path}')
        return EXIT_USAGE

    before = load_scene_or_refuse(path)
    if before is None:
        return EXIT_REFUSED
    doc = TscnDocument(before, path, uid_resolver=uid_resolver(path))
    try:
        outcome = HANDLERS[args.verb](doc, args)
    except TscnError as err:
        print(f'REFUSED  {path}: {err}')
        return EXIT_REFUSED

    after = doc.text
    if outcome == UNCHANGED or after == before:
        print(f'{args.verb}  {path}  {UNCHANGED}')
        return EXIT_OK
    if args.dry_run:
        print(render_diff(before, after, path.name), end='')
    else:
        doc.save()
    changed = sum(1 for line in render_diff(before, after, path.name).splitlines()
                  if line[:1] in '+-' and not line.startswith(('+++', '---')))
    print(f'{args.verb}  {path}  {outcome}  ({changed} line(s)'
          f'{", dry run" if args.dry_run else ""})')
    for note in doc.notes:
        print(f'  {note}')
    return EXIT_OK
