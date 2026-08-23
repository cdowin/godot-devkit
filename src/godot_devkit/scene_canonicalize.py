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

Each is restored from evidence, never invented: a uid comes from the target's own
`.uid` sidecar, its `[gd_scene/gd_resource]` header, or its `.import` file, and an
`index` is counted off the base scene's actual children. Anything that cannot be
resolved is REPORTED and left alone — a wrong uid is worse than a missing one.
"""
from __future__ import annotations

import argparse
import difflib
import re
from pathlib import Path

from godot_devkit.project import git_lines, repo_root
from godot_devkit.tscn import Section, node_own_path, parse, split_path
from godot_devkit.tscn_document import TscnDocument

RES_PREFIX = 'res://'
UID_ATTR = re.compile(r'\buid="(uid://[0-9a-z]+)"')
PATH_ATTR = re.compile(r'\bpath="(res://[^"]+)"')
TYPE_ATTR = re.compile(r'(\btype="[^"]*")')
SCENE_HEADER_KINDS = ('gd_scene', 'gd_resource')
UID_SIDECAR_SUFFIX = '.uid'
IMPORT_SUFFIX = '.import'
INSTANCE_ATTR = 'instance'
EDITABLE_KIND = 'editable'
EXIT_OK = 0
EXIT_FINDINGS = 1
EXIT_USAGE = 2
DIFF_CONTEXT = 1


class UidIndex:
    """Where a Godot resource's uid lives, by resource kind.

    Three homes, and a fourth resort: a `.gd` keeps it in a `.gd.uid` sidecar, a
    `.tscn`/`.tres` in its own header, an imported asset (`.png`, `.ttf`, `.ogg`)
    in its `.import` file. If none of those exist — the file is untracked, or
    generated — we fall back to what the rest of the repo already says about it,
    which is evidence rather than invention.
    """

    def __init__(self, root: Path) -> None:
        self.root = root
        self._cross_reference: dict[str, str] | None = None
        self._resolved: dict[str, str | None] = {}

    def of(self, res_path: str) -> str | None:
        if res_path not in self._resolved:
            self._resolved[res_path] = self._resolve(res_path)
        return self._resolved[res_path]

    def _resolve(self, res_path: str) -> str | None:
        if not res_path.startswith(RES_PREFIX):
            return None
        file = self.root / res_path[len(RES_PREFIX):]
        sidecar = file.with_suffix(file.suffix + UID_SIDECAR_SUFFIX)
        if sidecar.is_file():
            return sidecar.read_text(encoding='utf-8').strip() or None
        importer = file.with_suffix(file.suffix + IMPORT_SUFFIX)
        for candidate in (file, importer):
            if candidate.is_file() and candidate.suffix in ('.tscn', '.tres', IMPORT_SUFFIX):
                match = UID_ATTR.search(candidate.read_text(
                    encoding='utf-8', errors='replace')[:4096])
                if match:
                    return match.group(1)
        return self._from_cross_reference(res_path)

    def _from_cross_reference(self, res_path: str) -> str | None:
        if self._cross_reference is None:
            self._cross_reference = {}
            for rel in git_lines('ls-files', '*.tscn', '*.tres'):
                for line in (self.root / rel).read_text(
                        encoding='utf-8', errors='replace').splitlines():
                    if not line.startswith('[ext_resource '):
                        continue
                    path_m, uid_m = PATH_ATTR.search(line), UID_ATTR.search(line)
                    if path_m and uid_m:
                        self._cross_reference.setdefault(path_m.group(1), uid_m.group(1))
        return self._cross_reference.get(res_path)


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
    known = uids._from_cross_reference(RES_PREFIX + rel)
    if known is None:
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


def canonicalize(path: Path, root: Path, uids: UidIndex, bases: BaseScenes
                 ) -> tuple[str, list[str]]:
    """-> (canonical text, one report line per restoration or refusal)."""
    doc = TscnDocument(path.read_text(encoding='utf-8'), path)
    try:
        rel = str(path.resolve().relative_to(root))
    except ValueError:
        rel = path.name
    report = _restore_ref_uids(doc, uids)
    report += _restore_header_uid(doc, rel, uids)
    report += _restore_indexes(doc, bases)
    report += _restore_editable_markers(doc)
    return doc.text, report


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog='godot-devkit scene canonicalize', description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('files', nargs='+')
    parser.add_argument('--dry-run', action='store_true',
                        help='print the unified diff instead of writing')
    args = parser.parse_args(argv)

    root = repo_root()
    uids = UidIndex(root)
    bases = BaseScenes(root)
    unresolved = 0
    for name in args.files:
        path = Path(name)
        if not path.is_file():
            print(f'godot-devkit scene canonicalize: no such file: {path}')
            return EXIT_USAGE
        before = path.read_text(encoding='utf-8')
        after, report = canonicalize(path, root, uids, bases)
        unresolved += sum(1 for line in report if 'UNRESOLVED' in line)
        if after == before and not report:
            print(f'canonicalize  {path}  already canonical')
            continue
        if args.dry_run:
            print(''.join(difflib.unified_diff(
                before.splitlines(keepends=True), after.splitlines(keepends=True),
                fromfile=f'a/{path.name}', tofile=f'b/{path.name}', n=DIFF_CONTEXT)), end='')
        elif after != before:
            path.write_text(after, encoding='utf-8')
        restored = sum(1 for line in report if 'UNRESOLVED' not in line)
        print(f'canonicalize  {path}  {restored} restored, '
              f'{sum(1 for line in report if "UNRESOLVED" in line)} unresolved'
              f'{" (dry run)" if args.dry_run else ""}')
        for line in report:
            print(line)
    return EXIT_FINDINGS if unresolved else EXIT_OK
