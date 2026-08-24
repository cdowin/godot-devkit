"""tscn_document.py — a .tscn you can edit WITHOUT reformatting it.

The document owns the file's lines verbatim. Every edit is span surgery: replace
the lines a property/section actually occupies, leave every other byte alone.
`TscnDocument.load(p).text == p.read_text()` is the invariant the whole toolkit
rests on, and it is what makes these verbs safer than `sed` rather than a
fancier way to be reckless.

Nodes are addressed BY PATH, because that is how .tscn addresses them:
`parent="Center"` + `name="Panel"` is the node `Center/Panel`, and the root is
`.`. Format 4's `unique_id=` is a serialisation detail, not an address — nothing
here keys off it.

The hard part is not moving lines, it is keeping REFERENCES true. A rename or a
reparent changes the absolute path of a whole subtree, so this module rewrites,
in one pass driven by a single old-path -> new-path map:
  * every `parent=` on a descendant,
  * every `[connection from=/to=]` and `[editable path=]`,
  * every relative `NodePath("...")` literal that resolved into the moved
    subtree — resolved against the node that OWNS it, never text-matched.
A blanket `s/Sandbox/Vertical room/g` cannot tell `NodePath("Sandbox/X")` from
prose; that is the incident this module exists to make impossible. When a
reference cannot be re-expressed truthfully, the edit RAISES instead of writing
a plausible-looking wrong answer.
"""
from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path

from godot_devkit.tscn import (
    NODE_PATH_LITERAL,
    PATH_SEP,
    PROP_ASSIGN,
    ROOT_PATH,
    SUBNAME_SEP,
    Prop,
    Section,
    TscnError,
    _parse_lines,
    join_path,
    node_own_path,
    resolve_node_path,
    split_path,
)

NODE_KIND = 'node'
CONNECTION_KIND = 'connection'
EDITABLE_KIND = 'editable'
EXT_RESOURCE_KIND = 'ext_resource'
SUB_RESOURCE_KIND = 'sub_resource'
RESOURCE_KIND = 'resource'
SCENE_KINDS = ('gd_scene', 'gd_resource')
COMMENT_CHAR = ';'
PARENT_SEG = '..'

# Header attributes whose value is a scene-relative NODE PATH (so a rename or a
# reparent has to rewrite them). `node_paths=` is deliberately absent: it lists
# PROPERTY names, not paths, and rewriting it is a classic blanket-sed bug.
PATH_ATTRS = {
    NODE_KIND: ('parent',),
    CONNECTION_KIND: ('from', 'to'),
    EDITABLE_KIND: ('path',),
}
SUB_RESOURCE_REF = re.compile(r'SubResource\("([^"]*)"\)')
# An AnimationPlayer's track paths resolve against `root_node`, NOT against the
# player — and Godot omits the property when it holds the default `..`.
ANIMATION_HOSTS = ('AnimationPlayer',)
ROOT_NODE_PROP = 'root_node'
DEFAULT_ROOT_NODE = '..'
SCRIPT_PROP = 'script'
LOAD_STEPS_ATTR = 'load_steps'
EXT_REF = 'ExtResource("{id}")'

PathMap = dict[tuple[str, ...], tuple[str, ...]]


def _attr_pattern(name: str) -> re.Pattern:
    return re.compile(rf'(\b{name}=")((?:[^"\\]|\\.)*)(")')


class TscnDocument:
    """A parsed .tscn/.tres whose text survives a no-op round trip byte-for-byte."""

    def __init__(self, text: str, path: Path | None = None) -> None:
        self.path = path
        self.lines = text.split('\n')
        self.sections = _parse_lines(self.lines)
        self.notes: list[str] = []

    # --- construction / serialisation --------------------------------------
    @classmethod
    def load(cls, path: str | Path) -> TscnDocument:
        file = Path(path)
        return cls(file.read_text(encoding='utf-8'), file)

    @property
    def text(self) -> str:
        return '\n'.join(self.lines)

    def save(self, path: str | Path | None = None) -> Path:
        target = Path(path) if path is not None else self.path
        if target is None:
            raise TscnError('no path to save to')
        target.write_text(self.text, encoding='utf-8')
        return target

    def _reparse(self) -> None:
        self.sections = _parse_lines(self.lines)

    # --- lookups ------------------------------------------------------------
    @property
    def nodes(self) -> list[Section]:
        return [s for s in self.sections if s.kind == NODE_KIND]

    def node(self, path: str) -> Section:
        wanted = split_path(path)
        for section in self.nodes:
            if split_path(node_own_path(section)) == wanted:
                return section
        # Convenience: address the root by its own name as well as by `.`.
        root = self.root
        if root is not None and wanted == [root.attrs.get('name')]:
            return root
        raise TscnError(f'no node at path {path!r}')

    def has_node(self, path: str) -> bool:
        try:
            self.node(path)
        except TscnError:
            return False
        return True

    @property
    def root(self) -> Section | None:
        return next((s for s in self.nodes if 'parent' not in s.attrs), None)

    def node_path(self, section: Section) -> tuple[str, ...]:
        return tuple(split_path(node_own_path(section)))

    def descendants(self, section: Section) -> list[Section]:
        """Every node under `section`, in file order (the section excluded)."""
        base = self.node_path(section)
        return [n for n in self.nodes
                if len(self.node_path(n)) > len(base) and self.node_path(n)[:len(base)] == base]

    def ext_resources(self) -> dict[str, Section]:
        return {s.attrs['id']: s for s in self.sections
                if s.kind == EXT_RESOURCE_KIND and 'id' in s.attrs}

    # --- line surgery -------------------------------------------------------
    def _splice(self, start: int, end: int, replacement: list[str]) -> None:
        self.lines[start:end] = replacement
        self._reparse()

    def _block_span(self, section: Section) -> tuple[int, int]:
        """The lines a section owns for move/delete: its header and body, any
        contiguous comment lines directly above it (they document THIS section),
        and the blank separator lines below it."""
        start = section.header_line
        while start > 0 and self.lines[start - 1].lstrip().startswith(COMMENT_CHAR):
            start -= 1
        end = section.body_end
        while end < len(self.lines) and not self.lines[end].strip():
            end += 1
        return start, end

    # --- properties ---------------------------------------------------------
    def set_prop(self, node_path: str, key: str, value: str) -> str:
        """Assign `key = value` on a node. Returns 'set' or 'added'."""
        section = self.node(node_path)
        existing = section.prop(key)
        if existing is not None:
            self._splice(existing.start, existing.end, [existing.render(value)])
            return 'set'
        self._splice(section.body_end, section.body_end, [f'{key}{PROP_ASSIGN}{value}'])
        return 'added'

    def remove_prop(self, node_path: str, key: str) -> None:
        section = self.node(node_path)
        existing = section.prop(key)
        if existing is None:
            raise TscnError(f'node {node_path!r} has no property {key!r}')
        self._splice(existing.start, existing.end, [])

    def delete_props(self, props: list[Prop]) -> int:
        """Delete whole property assignments by their line spans, bottom-up.

        Batch, because every deletion shifts the spans below it — one pass in
        reverse file order keeps the surviving spans valid without a reparse
        per line. Multi-line values come out whole: the span is what the parser
        folded, not one line of it.
        """
        for prop in sorted(props, key=lambda entry: entry.start, reverse=True):
            self.lines[prop.start:prop.end] = []
        if props:
            self._reparse()
        return len(props)

    # --- structure ----------------------------------------------------------
    def rename_node(self, node_path: str, new_name: str) -> None:
        section = self.node(node_path)
        old = self.node_path(section)
        if not new_name or PATH_SEP in new_name:
            raise TscnError(f'invalid node name {new_name!r}')
        if not old:                                   # the scene root
            self._rewrite_attr(section, 'name', new_name)
            return
        new = old[:-1] + (new_name,)
        if any(self.node_path(n) == new for n in self.nodes):
            raise TscnError(f'a sibling named {new_name!r} already exists')
        self._apply_path_map({old: new})
        self._rewrite_attr(self.node(join_path(list(old))), 'name', new_name)

    def reparent_node(self, node_path: str, new_parent_path: str) -> None:
        section = self.node(node_path)
        old = self.node_path(section)
        if not old:
            raise TscnError('cannot reparent the scene root')
        parent = self.node(new_parent_path)
        target = self.node_path(parent)
        if target[:len(old)] == old:
            raise TscnError('cannot reparent a node under itself')
        new = target + (old[-1],)
        if new == old:
            return
        if any(self.node_path(n) == new for n in self.nodes):
            raise TscnError(f'{new_parent_path!r} already has a child named {old[-1]!r}')

        self._apply_path_map({old: new})
        moved = self.node(join_path(list(old)))
        self._rewrite_attr(moved, 'parent', join_path(list(target)))
        self._move_subtree(join_path(list(new)), parent_path=join_path(list(target)))

    def remove_node(self, node_path: str) -> None:
        section = self.node(node_path)
        if self.node_path(section) == ():
            raise TscnError('cannot remove the scene root')
        doomed = {self.node_path(section)}
        doomed.update(self.node_path(n) for n in self.descendants(section))
        self._warn_dangling(doomed)
        for block in sorted(self._blocks_referencing(doomed), reverse=True):
            self._splice(block[0], block[1], [])
        self._prune_unreferenced_ext_resources()

    def add_node(self, parent_path: str, name: str, node_type: str,
                 script: str | None = None) -> None:
        parent = self.node(parent_path)
        parent_abs = self.node_path(parent)
        if any(self.node_path(n) == parent_abs + (name,) for n in self.nodes):
            raise TscnError(f'{parent_path!r} already has a child named {name!r}')
        header = (f'[node name="{name}" type="{node_type}" '
                  f'parent="{join_path(list(parent_abs))}"]')
        body = [header]
        if script:
            ref_id = self._ensure_ext_resource(script, 'Script')
            body.append(f'{SCRIPT_PROP}{PROP_ASSIGN}{EXT_REF.format(id=ref_id)}')
        insert = self._subtree_end(self.node(parent_path))
        self._splice(insert, insert, ['', *body])

    # --- reference bookkeeping ---------------------------------------------
    def _rewrite_attr(self, section: Section, attr: str, value: str) -> None:
        line = self.lines[section.header_line]
        pattern = _attr_pattern(attr)
        if not pattern.search(line):
            raise TscnError(f'section header has no {attr}= attribute: {line}')
        self._splice(section.header_line, section.header_line + 1,
                     [pattern.sub(lambda m: m.group(1) + value + m.group(3), line, count=1)])

    def _apply_path_map(self, mapping: PathMap) -> None:
        """Rewrite every reference affected by `old -> new` subtree moves.

        Edits are computed from ONE snapshot of the parse and then applied
        bottom-up, so no edit invalidates another's line span and no edit is
        re-derived from a half-updated document.
        """
        edits = self._path_attr_edits(mapping) + self._node_path_edits(mapping)
        for start, end, replacement in sorted(edits, reverse=True):
            self.lines[start:end] = replacement
        self._reparse()

    def _path_attr_edits(self, mapping: PathMap) -> list[tuple[int, int, list[str]]]:
        edits = []
        for section in self.sections:
            for attr in PATH_ATTRS.get(section.kind, ()):
                current = section.attrs.get(attr)
                if current is None:
                    continue
                moved = _map_path(tuple(split_path(current)), mapping)
                if moved == tuple(split_path(current)):
                    continue
                line = self.lines[section.header_line]
                pattern = _attr_pattern(attr)
                if not pattern.search(line):
                    raise TscnError(f'section header has no {attr}= attribute: {line}')
                replacement = join_path(list(moved))
                edits.append((section.header_line, section.header_line + 1, [pattern.sub(
                    lambda m, value=replacement: m.group(1) + value + m.group(3),
                    line, count=1)]))
        return edits

    def _node_path_edits(self, mapping: PathMap) -> list[tuple[int, int, list[str]]]:
        """Retarget relative NodePath literals so they still point where they did.

        Covers sub_resources too — an Animation's `tracks/N/path` is a NodePath
        like any other, and a rename that misses it breaks the animation
        silently.
        """
        edits = []
        frames = self._sub_resource_frames()
        for section in self.sections:
            if section.kind in (SUB_RESOURCE_KIND, RESOURCE_KIND):
                owner_old = frames.get(section.attrs.get('id', ''))
                if owner_old is None:
                    self._note_unowned_node_paths(section)
                    continue
            elif section.kind == NODE_KIND:
                owner_old = self.node_path(section)
            else:
                continue
            owner_new = _map_path(owner_old, mapping)
            for prop in section.entries:
                if not NODE_PATH_LITERAL.search(prop.value):
                    continue
                rewritten = NODE_PATH_LITERAL.sub(
                    lambda m, old=owner_old, new=owner_new: (
                        m.group(1) + 'NodePath("'
                        + _retarget(m.group(2), old, new, mapping) + '")'),
                    prop.value)
                if rewritten != prop.value:
                    edits.append((prop.start, prop.end, [prop.render(rewritten)]))
        return edits

    def _resolution_frame(self, node: Section) -> tuple[str, ...]:
        """The node path a node's sub-resources resolve their NodePaths against.

        Usually the node itself. An AnimationPlayer is the exception that makes
        this worth having: its Animation tracks are spelled relative to
        `root_node`, which defaults to `..` and is omitted when default.
        """
        path = self.node_path(node)
        prop = node.prop(ROOT_NODE_PROP)
        literal = None
        if prop is not None:
            match = NODE_PATH_LITERAL.search(prop.value)
            literal = match.group(2) if match else None
        elif node.attrs.get('type') in ANIMATION_HOSTS:
            literal = DEFAULT_ROOT_NODE
        if literal is None:
            return path
        resolved = resolve_node_path(list(path), literal)
        return tuple(resolved) if resolved is not None else path

    def _sub_resource_frames(self) -> dict[str, tuple[str, ...] | None]:
        """sub_resource id -> the frame its NodePaths resolve in.

        A sub_resource has no path of its own, so it borrows the frame of the
        node that uses it, followed transitively (node -> AnimationLibrary ->
        Animation). `None` means two different nodes use it in two different
        frames — ambiguous, so we report instead of rewriting.
        """
        subs = {s.attrs['id']: s for s in self.sections
                if s.kind == SUB_RESOURCE_KIND and 'id' in s.attrs}
        frames: dict[str, set[tuple[str, ...]]] = defaultdict(set)
        pending: list[tuple[str, tuple[str, ...]]] = []
        for node in self.nodes:
            frame = self._resolution_frame(node)
            for prop in node.entries:
                for match in SUB_RESOURCE_REF.finditer(prop.value):
                    frames[match.group(1)].add(frame)
                    pending.append((match.group(1), frame))
        seen: set[tuple[str, tuple[str, ...]]] = set()
        while pending:
            entry = pending.pop()
            if entry in seen:
                continue
            seen.add(entry)
            section = subs.get(entry[0])
            if section is None:
                continue
            for prop in section.entries:
                for match in SUB_RESOURCE_REF.finditer(prop.value):
                    frames[match.group(1)].add(entry[1])
                    pending.append((match.group(1), entry[1]))
        return {sid: (next(iter(f)) if len(f) == 1 else None) for sid, f in frames.items()}

    def _note_unowned_node_paths(self, section: Section) -> None:
        """A NodePath inside a sub_resource resolves against whatever node uses
        it — unknowable from this file, so we say so instead of guessing."""
        for prop in section.entries:
            if NODE_PATH_LITERAL.search(prop.value):
                self.notes.append(
                    f'NOT REWRITTEN  {section.kind} {section.attrs.get("id", "?")}.'
                    f'{prop.key} holds a NodePath; its owning node is unknowable '
                    f'from this file — verify by hand')

    def _move_subtree(self, node_path: str, parent_path: str) -> None:
        """Relocate a node's block (and its descendants') after the new parent's."""
        section = self.node(node_path)
        blocks = [self._block_span(s) for s in (section, *self.descendants(section))]
        moved_lines: list[str] = []
        for start, end in sorted(blocks):
            moved_lines.extend(self.lines[start:end])
        while moved_lines and not moved_lines[-1].strip():
            moved_lines.pop()                        # separators are re-added below
        for start, end in sorted(blocks, reverse=True):
            self.lines[start:end] = []
        self._reparse()
        insert = self._subtree_end(self.node(parent_path))
        self._splice(insert, insert, ['', *moved_lines])

    def _subtree_end(self, section: Section) -> int:
        """The line index just past a node's own block and all its descendants'."""
        spans = [self._block_span(s) for s in (section, *self.descendants(section))]
        end = max(span[1] for span in spans)
        while end > 0 and not self.lines[end - 1].strip():
            end -= 1
        return end

    def _blocks_referencing(self, doomed: set[tuple[str, ...]]) -> list[tuple[int, int]]:
        blocks = []
        for section in self.sections:
            if section.kind == NODE_KIND:
                if self.node_path(section) in doomed:
                    blocks.append(self._block_span(section))
                continue
            for attr in PATH_ATTRS.get(section.kind, ()):
                value = section.attrs.get(attr)
                if value is not None and tuple(split_path(value)) in doomed:
                    blocks.append(self._block_span(section))
                    break
        return blocks

    def _warn_dangling(self, doomed: set[tuple[str, ...]]) -> None:
        for section in self.nodes:
            owner = self.node_path(section)
            if owner in doomed:
                continue
            for prop in section.entries:
                for match in NODE_PATH_LITERAL.finditer(prop.value):
                    target = resolve_node_path(list(owner), match.group(2).split(SUBNAME_SEP)[0])
                    if target is not None and _longest_prefix(tuple(target), doomed):
                        self.notes.append(
                            f'DANGLING  {join_path(list(owner))}.{prop.key} = '
                            f'NodePath("{match.group(2)}") now points at nothing')

    def _prune_unreferenced_ext_resources(self) -> None:
        """Drop ext_resources the removal left with no referent — what Godot
        does on the next resave anyway. Reported, never silent."""
        for ref_id, section in reversed(list(self.ext_resources().items())):
            needle = EXT_REF.format(id=ref_id)
            if any(needle in line for index, line in enumerate(self.lines)
                   if index != section.header_line):
                continue
            self.notes.append(f'PRUNED  ext_resource {ref_id} '
                              f'({section.attrs.get("path", "?")}) is no longer referenced')
            self._splice(section.header_line, section.header_line + 1, [])
        self._bump_load_steps()

    def _ensure_ext_resource(self, res_path: str, res_type: str) -> str:
        """Reuse or append an ext_resource for `res_path`; returns its id.
        The uid comes from the resource's committed `.uid` sidecar, so a scene
        authored here is born canonical (`check tres` demands uid-in-refs)."""
        for ref_id, section in self.ext_resources().items():
            if section.attrs.get('path') == res_path:
                return ref_id
        used = self.ext_resources()
        ordinal = max((int(k.split('_')[0]) for k in used if k.split('_')[0].isdigit()),
                      default=0) + 1
        stem = res_path.rsplit(PATH_SEP, 1)[-1].rsplit('.', 1)[0]
        ref_id = f'{ordinal}_{stem}'
        uid = self._uid_of(res_path)
        if uid is None:
            self.notes.append(f'NO UID  {res_path} has no resolvable uid (.uid sidecar, '
                              f'resource header, .import, or an existing repo ref) — '
                              f'the ref is path-only and `check tres` will flag it')
            attrs = f'type="{res_type}" path="{res_path}" id="{ref_id}"'
        else:
            attrs = f'type="{res_type}" uid="{uid}" path="{res_path}" id="{ref_id}"'
        anchor = max((s.body_end for s in self.sections
                      if s.kind in (EXT_RESOURCE_KIND, *SCENE_KINDS)), default=1)
        self._splice(anchor, anchor, [f'[{EXT_RESOURCE_KIND} {attrs}]'])
        self._bump_load_steps()
        return ref_id

    def _uid_of(self, res_path: str) -> str | None:
        """The uid to write into a new ref, via the one uid resolver.

        The project root is the document's own `project.godot` ancestor when it
        has one, and the invoking repo otherwise — a scene being authored into a
        scratch directory still resolves its script's uid.
        """
        from godot_devkit.project import repo_root
        from godot_devkit.uid_index import UidIndex

        root = _repo_root_for(self.path) if self.path is not None else None
        return UidIndex(root or repo_root()).of(res_path)

    def _bump_load_steps(self) -> None:
        scene = next((s for s in self.sections if s.kind in SCENE_KINDS), None)
        if scene is None or LOAD_STEPS_ATTR not in scene.attrs:
            return                                   # format 4 omits load_steps
        steps = 1 + sum(1 for s in self.sections
                        if s.kind in (EXT_RESOURCE_KIND, SUB_RESOURCE_KIND))
        line = self.lines[scene.header_line]
        self._splice(scene.header_line, scene.header_line + 1,
                     [re.sub(rf'\b{LOAD_STEPS_ATTR}=\d+', f'{LOAD_STEPS_ATTR}={steps}', line)])


def _repo_root_for(path: Path) -> Path | None:
    for parent in path.resolve().parents:
        if (parent / 'project.godot').is_file():
            return parent
    return None


def _longest_prefix(path: tuple[str, ...], keys) -> tuple[str, ...] | None:
    """The longest key in `keys` that is `path` or one of its ancestors."""
    best = None
    for key in keys:
        if path[:len(key)] == key and (best is None or len(key) > len(best)):
            best = key
    return best


def _map_path(path: tuple[str, ...], mapping: PathMap) -> tuple[str, ...]:
    key = _longest_prefix(path, mapping.keys())
    return path if key is None else mapping[key] + path[len(key):]


def _retarget(literal: str, owner_old: tuple[str, ...], owner_new: tuple[str, ...],
              mapping: PathMap) -> str:
    """Re-spell one NodePath literal so it still resolves to the same node.

    Tries the minimal edit first (swap the renamed segment in place, keeping the
    author's `../` style); falls back to recomputing the relative path when the
    owner itself moved. Refuses rather than emit a path that resolves elsewhere.
    """
    main, sep, subname = literal.partition(SUBNAME_SEP)
    target_old = resolve_node_path(list(owner_old), main)
    if target_old is None:
        return literal                               # absolute or above-root
    target_new = _map_path(tuple(target_old), mapping)
    if tuple(target_old) == target_new and owner_old == owner_new:
        return literal

    candidate = _swap_in_place(main, owner_old, mapping)
    if candidate is not None:
        resolved = resolve_node_path(list(owner_new), candidate)
        if resolved is not None and tuple(resolved) == target_new:
            return candidate + sep + subname
    candidate = _relative_path(owner_new, target_new)
    resolved = resolve_node_path(list(owner_new), candidate)
    if resolved is None or tuple(resolved) != target_new:
        raise TscnError(f'cannot re-express NodePath("{literal}") after the move')
    return candidate + sep + subname


def _swap_in_place(main: str, owner: tuple[str, ...], mapping: PathMap) -> str | None:
    """Rebuild a literal by renaming only the segments it spells out itself."""
    walk = list(owner)
    parts = main.split(PATH_SEP)
    rebuilt: list[str] = []
    for part in parts:
        if part in ('', '.'):
            rebuilt.append(part)
            continue
        if part == PARENT_SEG:
            if not walk:
                return None
            walk.pop()
            rebuilt.append(part)
            continue
        walk.append(part)
        moved = _map_path(tuple(walk), mapping)
        rebuilt.append(moved[len(walk) - 1] if len(moved) == len(walk) else part)
    return PATH_SEP.join(rebuilt)


def _relative_path(owner: tuple[str, ...], target: tuple[str, ...]) -> str:
    common = 0
    while common < min(len(owner), len(target)) and owner[common] == target[common]:
        common += 1
    hops = [PARENT_SEG] * (len(owner) - common)
    rest = list(target[common:])
    return PATH_SEP.join(hops + rest) if (hops or rest) else ROOT_PATH
