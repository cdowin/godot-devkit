"""scene_edit.py — surgical write verbs for .tscn/.tres.

    godot-devkit scene set      <file> <node-path> <prop> <value>
    godot-devkit scene rename   <file> <node-path> <new-name>
    godot-devkit scene add      <file> <parent-path> <name> <type> [--script res://x.gd]
    godot-devkit scene rm       <file> <node-path>
    godot-devkit scene reparent <file> <node-path> <new-parent>

Every verb addresses nodes by PATH — the scene root is `.`, its child is `Name`,
deeper is `Parent/Name`. That is the address `.tscn` itself uses in `parent=`,
and the address `godot-devkit scene --paths` prints: read output is write input.

The point is that these put ZERO file content into the caller's context. Changing
one property in a scene carrying 100k tokens of packed tile bytes costs one
command and one line of output instead of a full read and a rewrite.

Two guarantees make that safe rather than merely cheap:
  * Untouched lines are never rewritten — the document keeps the file's bytes and
    replaces only the spans it was asked about (`tscn_document`).
  * A verb that cannot express the result truthfully REFUSES. `rename` in
    particular re-resolves every NodePath against the node that owns it, and
    raises rather than emit a path that points somewhere new — the failure a
    blanket `s/Sandbox/Vertical room/g` made silently.

`--dry-run` prints the unified diff instead of writing; every verb is idempotent,
so running one twice reports `unchanged` and touches nothing.
"""
from __future__ import annotations

import argparse
import difflib
from pathlib import Path

from godot_devkit.godot.format.tscn import TscnError, join_path, split_path
from godot_devkit.godot.format.tscn_document import TscnDocument

VERBS = ('set', 'rename', 'add', 'rm', 'reparent')
UNCHANGED = 'unchanged'
EXIT_OK = 0
EXIT_REFUSED = 1
EXIT_USAGE = 2
DIFF_CONTEXT = 1


def _diff(before: str, after: str, name: str) -> str:
    return ''.join(difflib.unified_diff(
        before.splitlines(keepends=True), after.splitlines(keepends=True),
        fromfile=f'a/{name}', tofile=f'b/{name}', n=DIFF_CONTEXT))


def _child_path(doc: TscnDocument, parent_path: str, name: str) -> str:
    """The canonical path of `name` under `parent_path`.

    Canonical, not concatenated: the root answers to `.` AND to its own name, so
    `Sandbox` + `Deep` is the path `Deep`, not `Sandbox/Deep`. Getting this wrong
    is how an idempotence check silently becomes a second edit.
    """
    return join_path(list(doc.node_path(doc.node(parent_path))) + [name])


def _do_set(doc: TscnDocument, args) -> str:
    node = doc.node(args.node_path)
    existing = node.prop(args.prop)
    if existing is not None and existing.value == args.value:
        return UNCHANGED
    return doc.set_prop(args.node_path, args.prop, args.value)


def _do_rename(doc: TscnDocument, args) -> str:
    if not doc.has_node(args.node_path):
        renamed = split_path(args.node_path)[:-1] + [args.new_name]
        if doc.has_node('/'.join(renamed) or '.'):
            return UNCHANGED                          # already renamed
    node = doc.node(args.node_path)
    if node.attrs.get('name') == args.new_name:
        return UNCHANGED
    doc.rename_node(args.node_path, args.new_name)
    return 'renamed'


def _do_add(doc: TscnDocument, args) -> str:
    path = _child_path(doc, args.parent_path, args.name)
    if doc.has_node(path):
        existing = doc.node(path)
        if existing.attrs.get('type') != args.type:
            raise TscnError(f'{path!r} already exists as a '
                            f'{existing.attrs.get("type") or "instance"}')
        return UNCHANGED
    doc.add_node(args.parent_path, args.name, args.type, args.script)
    return 'added'


def _do_rm(doc: TscnDocument, args) -> str:
    if not doc.has_node(args.node_path):
        return UNCHANGED
    doc.remove_node(args.node_path)
    return 'removed'


def _do_reparent(doc: TscnDocument, args) -> str:
    segments = split_path(args.node_path)
    if not segments:
        raise TscnError('cannot reparent the scene root')
    target = _child_path(doc, args.new_parent, segments[-1])
    if doc.has_node(target) and not doc.has_node(args.node_path):
        return UNCHANGED
    if doc.has_node(args.node_path) and doc.node_path(doc.node(args.node_path)) == tuple(
            split_path(target)):
        return UNCHANGED
    doc.reparent_node(args.node_path, args.new_parent)
    return 'reparented'


HANDLERS = {'set': _do_set, 'rename': _do_rename, 'add': _do_add,
            'rm': _do_rm, 'reparent': _do_reparent}


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog='godot-devkit scene', description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    subs = parser.add_subparsers(dest='verb', required=True)

    def add_verb(name: str, *fields: str) -> argparse.ArgumentParser:
        sub = subs.add_parser(name)
        sub.add_argument('file')
        for field in fields:
            sub.add_argument(field)
        sub.add_argument('--dry-run', action='store_true',
                         help='print the unified diff instead of writing')
        return sub

    add_verb('set', 'node_path', 'prop', 'value')
    add_verb('rename', 'node_path', 'new_name')
    add_verb('add', 'parent_path', 'name', 'type').add_argument(
        '--script', help='res:// path to a .gd; its .uid sidecar is used so the '
                         'new ext_resource ref is born canonical')
    add_verb('rm', 'node_path')
    add_verb('reparent', 'node_path', 'new_parent')
    return parser


def main(argv: list[str]) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    path = Path(args.file)
    if not path.is_file():
        print(f'godot-devkit scene {args.verb}: no such file: {path}')
        return EXIT_USAGE

    before = path.read_text(encoding='utf-8')
    doc = TscnDocument(before, path)
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
        print(_diff(before, after, path.name), end='')
    else:
        doc.save()
    changed = sum(1 for line in _diff(before, after, path.name).splitlines()
                  if line[:1] in '+-' and not line.startswith(('+++', '---')))
    print(f'{args.verb}  {path}  {outcome}  ({changed} line(s)'
          f'{", dry run" if args.dry_run else ""})')
    for note in doc.notes:
        print(f'  {note}')
    return EXIT_OK
