"""scene_canonicalize.py — put back what `PackedScene.pack()` throws away.

    godot-devkit scene canonicalize <file>... [--dry-run]

Authoring a scene offline (build a tree in a headless script, `PackedScene.pack()`,
`ResourceSaver.save()`) is the fastest way to produce a big scene and the fastest
way to produce a subtly broken one. `save()` writes a MINIMAL file; three things
it leaves out are load-bearing, and all three recur on every single pass:

1. **uid-in-refs.** Refs come out `path=`-only. The consuming repos require the
   canonical `uid=`+`path=` form (`check tres`), because any later import silently
   upgrades a path-only ref and the churn leaks into unrelated diffs. This is the
   one Chris named: *"I think we keep fighting that."*
2. **The file's OWN header uid.** A freshly packed scene has no uid, so the
   `[gd_scene uid="..."]` line vanishes — and every other file that referenced
   this scene by uid is now pointing at nothing.
3. **`index=` on instance-child overrides.** An override without it does not
   reload as an override: Godot creates a NEW SIBLING, and the base scene's real
   child leaks as an orphan on EVERY load. That is what stack-overflowed an
   unrelated unit test.

`--elide-defaults` adds the fourth, and it SUBTRACTS instead of restoring: a
hand-authored `.tres` spells out properties whose value equals the script's
`@export` default, and Godot's writer omits exactly those — so the file diffs on
every editor save until one form wins. It is opt-in because it deletes lines, and
because deleting them is only safe where the redundancy is PROVEN
(`resource_defaults`); anything unprovable is left alone. Unlike a load-and-
re-save it touches nothing else: comments, ordering, uids and value spellings all
survive, which is what makes it safe to run over a whole tree.

Each is restored from evidence, never invented: a uid comes from the target's own
`.uid` sidecar, its `[gd_scene/gd_resource]` header, or its `.import` file, and an
`index` is counted off the base scene's actual children. Anything that cannot be
resolved is REPORTED and left alone — a wrong uid is worse than a missing one.
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path

from godot_devkit.godot.index.gdscript import ScriptIndex
from godot_devkit.core import apply
from godot_devkit.core.project import git_lines, repo_root
from godot_devkit.godot.index.resource_defaults import DefaultAnalyzer
from godot_devkit.godot.format.tscn import Section, node_own_path, parse, split_path
from godot_devkit.godot.format.tscn_document import TscnDocument, read_scene_text
from godot_devkit.godot.index.uid_index import PATH_ATTR, RES_PREFIX, UID_ATTR, UidIndex
from godot_devkit.godot.write import render_diff, utf8_refusal_reason

TYPE_ATTR = re.compile(r'(\btype="[^"]*")')
RESOURCE_HEADER_KIND = 'gd_resource'
SCENE_HEADER_KINDS = ('gd_scene', RESOURCE_HEADER_KIND)
INSTANCE_ATTR = 'instance'
EDITABLE_KIND = 'editable'
EXIT_OK = 0
EXIT_FINDINGS = 1
EXIT_USAGE = 2


class BaseScenes:
    """Child ordering inside instanced scenes — the evidence `index=` needs."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self._parsed: dict[str, tuple[Section, ...]] = {}

    def _sections(self, res_path: str) -> tuple[Section, ...]:
        if res_path not in self._parsed:
            file = self.root / res_path[len(RES_PREFIX):]
            self._parsed[res_path] = (
                tuple(parse(str(file)))
                if res_path.startswith(RES_PREFIX) and file.is_file() else ())
        return self._parsed[res_path]

    def child_index(self, res_path: str, parent: list[str], name: str) -> int | None:
        """The ordinal of `name` among the children of `parent` in `res_path`."""
        sections = self._sections(res_path)
        if not sections:
            return None
        wanted = ['.'] if not parent else parent
        siblings = [s for s in sections if s.kind == 'node'
                    and s.attrs.get('parent') is not None
                    and split_path(s.attrs['parent']) == split_path('/'.join(wanted))]
        for ordinal, sibling in enumerate(siblings):
            if sibling.attrs.get('name') == name:
                return ordinal
        return None


def _instance_host(doc: TscnDocument, path: tuple[str, ...]) -> tuple[Section, tuple] | None:
    """The nearest ancestor of `path` that instances another scene."""
    for cut in range(len(path) - 1, 0, -1):
        for node in doc.nodes:
            if doc.node_path(node) == path[:cut] and INSTANCE_ATTR in node.attrs:
                return node, path[cut:]
    return None


def _restore_ref_uids(doc: TscnDocument, uids: UidIndex) -> list[str]:
    fixed = []
    for index, line in enumerate(list(doc.lines)):
        if not line.startswith('[ext_resource ') or UID_ATTR.search(line):
            continue
        path_m = PATH_ATTR.search(line)
        if path_m is None:
            continue
        uid = uids.of(path_m.group(1))
        if uid is None:
            fixed.append(f'  UNRESOLVED  no uid found for {path_m.group(1)} — left path-only')
            continue
        # Godot's own attribute order: type, uid, path, id.
        doc.lines[index] = TYPE_ATTR.sub(rf'\1 uid="{uid}"', line, count=1)
        fixed.append(f'  UID  {path_m.group(1)} -> {uid}')
    return fixed


def _restore_header_uid(doc: TscnDocument, rel: str, uids: UidIndex) -> list[str]:
    header = next((s for s in doc.sections if s.kind in SCENE_HEADER_KINDS), None)
    if header is None or 'uid' in header.attrs:
        return []
    known = uids.from_repo_references(RES_PREFIX + rel)
    if known is None:
        # A .tscn always leaves the editor with a header uid, so a missing one
        # is a real pack() loss. A hand-authored .tres legitimately has none —
        # Godot writes one only for a registered resource — and with nothing
        # referencing it by uid there is nothing to restore and nothing broken.
        if header.kind == RESOURCE_HEADER_KIND:
            return []
        return [f'  UNRESOLVED  {rel} has no header uid and nothing references it by uid']
    line = doc.lines[header.header_line]
    doc.lines[header.header_line] = line[:-1] + f' uid="{known}"]'
    return [f'  HEADER UID  {rel} -> {known} (restored from existing references)']


def _restore_indexes(doc: TscnDocument, bases: BaseScenes) -> list[str]:
    fixed = []
    ext = doc.ext_resources()
    for node in list(doc.nodes):
        if 'type' in node.attrs or INSTANCE_ATTR in node.attrs or 'index' in node.attrs:
            continue
        host = _instance_host(doc, doc.node_path(node))
        if host is None:
            fixed.append(f'  UNRESOLVED  {node_own_path(node)} overrides an instance child '
                         f'but no instancing ancestor was found')
            continue
        parent_node, inner = host
        match = re.match(r'ExtResource\("([^"]*)"\)', parent_node.attrs[INSTANCE_ATTR])
        base = ext[match.group(1)].attrs.get('path') if match and match.group(1) in ext else None
        ordinal = bases.child_index(base, list(inner[:-1]), inner[-1]) if base else None
        if ordinal is None:
            fixed.append(f'  UNRESOLVED  cannot count {node_own_path(node)} in {base or "?"} '
                         f'— index= left off (this node WILL reload as a new sibling)')
            continue
        line = doc.lines[node.header_line]
        doc.lines[node.header_line] = line[:-1] + f' index="{ordinal}"]'
        fixed.append(f'  INDEX  {node_own_path(node)} -> index="{ordinal}"')
    return fixed


def _restore_editable_markers(doc: TscnDocument) -> list[str]:
    """An instance whose children are overridden is an editable instance; Godot
    writes the marker, `pack()` does not."""
    declared = {s.attrs.get('path') for s in doc.sections if s.kind == EDITABLE_KIND}
    missing: list[str] = []
    for node in doc.nodes:
        if 'type' in node.attrs or INSTANCE_ATTR in node.attrs:
            continue
        host = _instance_host(doc, doc.node_path(node))
        if host is None:
            continue
        host_path = '/'.join(doc.node_path(host[0]))
        if host_path not in declared:
            declared.add(host_path)
            missing.append(host_path)
    if not missing:
        return []
    end = len(doc.lines)
    while end > 0 and not doc.lines[end - 1].strip():
        end -= 1                                     # keep the file's trailing newline
    markers = [line for host in missing for line in ('', f'[{EDITABLE_KIND} path="{host}"]')]
    doc.lines[end:end] = markers
    doc._reparse()
    return [f'  EDITABLE  added [editable path="{host}"]' for host in missing]


def _elide_redundant_defaults(doc: TscnDocument, analyzer: DefaultAnalyzer) -> list[str]:
    """Delete assignments PROVEN equal to the script's declared default."""
    redundant = analyzer.analyze(doc.sections)
    report = [f'  DEFAULT  {item.where}.{item.prop.key} = {item.prop.value} '
              f'(declared default {item.default}) — removed' for item in redundant]
    doc.delete_props([item.prop for item in redundant])
    return report


def canonicalize(path: Path, root: Path, uids: UidIndex, bases: BaseScenes,
                 analyzer: DefaultAnalyzer | None = None) -> tuple[str, list[str]]:
    """-> (canonical text, one report line per restoration or refusal)."""
    doc = TscnDocument(read_scene_text(path), path)
    try:
        rel = str(path.resolve().relative_to(root))
    except ValueError:
        rel = path.name
    report = _restore_ref_uids(doc, uids)
    report += _restore_header_uid(doc, rel, uids)
    report += _restore_indexes(doc, bases)
    report += _restore_editable_markers(doc)
    if analyzer is not None:
        report += _elide_redundant_defaults(doc, analyzer)
    return doc.text, report


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog='godot-devkit scene canonicalize', description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('files', nargs='+')
    parser.add_argument('--dry-run', action='store_true',
                        help='print the unified diff instead of writing')
    parser.add_argument('--elide-defaults', action='store_true',
                        help='also DELETE assignments proven equal to the '
                             'script\'s @export default (what Godot\'s writer '
                             'omits); see `check defaults`')
    args = parser.parse_args(argv)

    root = repo_root()
    uids = UidIndex(root)
    bases = BaseScenes(root)
    analyzer = None
    if args.elide_defaults:
        analyzer = DefaultAnalyzer(ScriptIndex(root, git_lines('ls-files', '*.gd')))
    unresolved = 0
    refused = 0
    for name in args.files:
        path = Path(name)
        if not path.is_file():
            print(f'godot-devkit scene canonicalize: no such file: {path}')
            return EXIT_USAGE
        try:
            before = read_scene_text(path)
            after, report = canonicalize(path, root, uids, bases, analyzer)
        except UnicodeDecodeError as err:
            print(f'REFUSED  {path}: {utf8_refusal_reason(err)}')
            refused += 1
            continue
        unresolved += sum(1 for line in report if 'UNRESOLVED' in line)
        if after == before and not report:
            print(f'canonicalize  {path}  already canonical')
            continue
        if args.dry_run:
            print(render_diff(before, after, path.name), end='')
        elif after != before:
            # Raw write: `after` carries the file's own line endings (the
            # document preserves them), and translating here would normalize
            # every ending in a file we promised to touch surgically.
            apply.raise_on_error(apply.write(path, after))
        # "changes", not "restored": with --elide-defaults a change can be a
        # deletion, and a count that lies about its own direction is worse than
        # no count.
        changes = sum(1 for line in report if 'UNRESOLVED' not in line)
        print(f'canonicalize  {path}  {changes} change(s), '
              f'{sum(1 for line in report if "UNRESOLVED" in line)} unresolved'
              f'{" (dry run)" if args.dry_run else ""}')
        for line in report:
            print(line)
    return EXIT_FINDINGS if unresolved or refused else EXIT_OK
