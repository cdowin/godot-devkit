"""tscn_document.py — a .tscn you can edit WITHOUT reformatting it.

The document owns the file's lines verbatim — INCLUDING each line's own ending.
Every edit is span surgery: replace the lines a property/section actually
occupies, leave every other byte alone. `TscnDocument.load(p).text` equal to the
file's bytes is the invariant the whole toolkit rests on, and it is what makes
these verbs safer than `sed` rather than a fancier way to be reckless.

Line-ending policy (pinned by test): an untouched line keeps its exact ending
(`\n`, `\r\n` or `\r`), a line rewritten in place keeps the ending it had, and
a line an edit INSERTS gets the file's dominant ending. A mixed-endings file
stays mixed everywhere the edit did not reach — normalizing it wholesale is a
diff nobody asked for.

Nodes are addressed BY PATH, because that is how .tscn addresses them:
`parent="Center"` + `name="Panel"` is the node `Center/Panel`, and the root is
`.`. Format 4's `unique_id=` is a serialisation detail, not an address.
An edit that cannot be expressed truthfully RAISES instead of writing a
plausible-looking wrong answer.
"""
from __future__ import annotations

import hashlib
import re
import zlib
from collections import Counter
from pathlib import Path
from typing import Callable
from godot_devkit.core import apply

from godot_devkit.godot.format.tscn import (
    COMMENT_CHAR,
    EXT_RESOURCE_KIND,
    NODE_KIND,
    PATH_SEP,
    PROP_ASSIGN,
    Section,
    TscnError,
    join_path,
    node_own_path,
    parse_lines,
    split_path,
)

SUB_RESOURCE_KIND = 'sub_resource'
RESOURCE_KIND = 'resource'
SCENE_KINDS = ('gd_scene', 'gd_resource')
SCRIPT_PROP = 'script'
LOAD_STEPS_ATTR = 'load_steps'
EXT_REF = 'ExtResource("{id}")'
PACKED_SCENE_TYPE = 'PackedScene'
UNIQUE_ID_ATTR = 'unique_id'
UNIQUE_ID_MASK = 0x7FFFFFFF          # Godot's node ids are positive int32
SUB_ID_CHARS = '0123456789abcdefghijklmnopqrstuvwxyz'
SUB_ID_LENGTH = 5                    # `Resource_x7k2q`, as the editor mints them

PathMap = dict[tuple[str, ...], tuple[str, ...]]

LINE_ENDING = re.compile('(\r\n|\r|\n)')
LF = '\n'


def read_scene_text(path: str | Path) -> str:
    """The file's text with its own line endings intact.

    `newline=''` disables universal-newline translation, so a CRLF (or mixed)
    file arrives byte-faithful and `TscnDocument.text` can reproduce it.
    Raises `UnicodeDecodeError` on a mis-encoded file — the write verbs turn
    that into a REFUSED line rather than guessing at bytes they cannot read.
    """
    with Path(path).open(encoding='utf-8', newline='') as handle:
        return handle.read()


class _Lines(list):
    """The document's line CONTENTS, with each line's own ending kept in step.

    The contents are exactly what `.split('\\n')` gives on translated text —
    the representation every parse span indexes — while `endings[i]` holds
    line i's terminator byte-for-byte (`\\n`, `\\r\\n`, `\\r`, or `''` for a
    final unterminated line). The policy the mutators implement: an untouched
    line keeps its ending, an equal-count in-place rewrite keeps the replaced
    lines' endings, and inserted lines get the file's dominant ending.
    """

    def __init__(self, text: str) -> None:
        parts = LINE_ENDING.split(text)
        super().__init__(parts[::2])
        self.endings: list[str] = parts[1::2] + ['']
        counts = Counter(e for e in self.endings if e)
        self.default_ending: str = counts.most_common(1)[0][0] if counts else LF

    def render(self) -> str:
        return ''.join(content + ending for content, ending in zip(self, self.endings))

    def _terminate_interior(self) -> None:
        # Only the LAST line may go unterminated. An insertion after a final
        # unterminated line gives that line the dominant ending, exactly as
        # typing there in an editor would.
        for index in range(len(self) - 1):
            if not self.endings[index]:
                self.endings[index] = self.default_ending

    def __setitem__(self, key, value) -> None:
        if not isinstance(key, slice):
            super().__setitem__(key, value)          # in-place: ending survives
            return
        start, stop, _ = key.indices(len(self))
        replacement = list(value)
        super().__setitem__(key, replacement)
        if len(replacement) != stop - start:
            self.endings[start:stop] = [self.default_ending] * len(replacement)
        self._terminate_interior()

    def __delitem__(self, key) -> None:
        super().__delitem__(key)
        del self.endings[key]
        self._terminate_interior()

    def insert(self, index: int, value: str) -> None:
        self[index:index] = [value]

    def append(self, value: str) -> None:
        self[len(self):len(self)] = [value]

    def extend(self, values) -> None:
        self[len(self):len(self)] = list(values)

    def pop(self, index: int = -1) -> str:
        value = self[index]
        del self[index]
        return value


class TscnDocument:
    """A parsed .tscn/.tres whose text survives a no-op round trip byte-for-byte."""

    def __init__(self, text: str, path: Path | None = None,
                 uid_resolver: Callable[[str], str | None] | None = None) -> None:
        self.path = path
        self.lines = _Lines(text)
        self.sections = parse_lines(self.lines)
        self.notes: list[str] = []
        self.uid_resolver = uid_resolver

    # --- construction / serialisation --------------------------------------
    @classmethod
    def load(cls, path: str | Path) -> TscnDocument:
        file = Path(path)
        return cls(read_scene_text(file), file)

    @property
    def text(self) -> str:
        return self.lines.render()

    def save(self, path: str | Path | None = None) -> Path:
        target = Path(path) if path is not None else self.path
        if target is None:
            raise TscnError('no path to save to')
        # `apply.write` (newline='') — the text carries its own endings, and
        # translating them here is how every verb once normalized whole files.
        apply.raise_on_error(apply.write(target, self.text))
        return target

    def _reparse(self) -> None:
        self.sections = parse_lines(self.lines)

    # --- lookups ------------------------------------------------------------
    @property
    def nodes(self) -> list[Section]:
        return [s for s in self.sections if s.kind == NODE_KIND]

    def node(self, path: str) -> Section:
        wanted = split_path(path)
        match = next((s for s in self.nodes
                      if split_path(node_own_path(s)) == wanted), None)
        # Convenience: address the root by its own name as well as by `.` —
        # unless a CHILD of the root carries that name too, in which case the
        # address means two nodes and answering with either is a silent wrong
        # edit. Refuse; `.` is always unambiguous.
        root = self.root
        if root is not None and wanted == [root.attrs.get('name')]:
            if match is not None:
                raise TscnError(
                    f'{path!r} is ambiguous: it names both the scene root and '
                    f"a child of it — address the root as '.'")
            return root
        if match is not None:
            return match
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

    def resource_body(self) -> Section:
        """The `[resource]` body of a .tres — the one section a resource file
        keeps its properties in. A scene has none, and saying so beats
        guessing at which sub_resource the caller might have meant."""
        match = next((s for s in self.sections if s.kind == RESOURCE_KIND), None)
        if match is None:
            raise TscnError('this file has no [resource] body '
                            '(a .tscn scene has none — address a [sub_resource] '
                            'by id, or a node by path)')
        return match

    def sub_resource(self, sub_id: str) -> Section:
        """The `[sub_resource]` addressed by the id `scene --props` prints,
        verbatim. An unknown id names the known ones — the same read-output-
        is-write-input contract node paths follow."""
        subs = {s.attrs['id']: s for s in self.sections
                if s.kind == SUB_RESOURCE_KIND and 'id' in s.attrs}
        if sub_id in subs:
            return subs[sub_id]
        known = ', '.join(subs) or '(none)'
        raise TscnError(f'no sub_resource with id {sub_id!r}; '
                        f'this file has: {known}')

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
        return self.set_section_prop(self.node(node_path), key, value)

    def set_section_prop(self, section: Section, key: str, value: str,
                         before: tuple[str, ...] = ()) -> str:
        """Assign `key = value` on any property-bodied section (a node, the
        `[resource]` body, a `[sub_resource]`): replace the existing span in
        place — inline comment preserved — or append to the section's body.
        A NEW key lands above the first of `before` the section has, which is
        how a caller that knows the saver's order keeps a fresh line in it."""
        existing = section.prop(key)
        if existing is not None:
            self._splice(existing.start, existing.end, [existing.render(value)])
            return 'set'
        anchor = next((section.prop(k).start for k in before
                       if section.prop(k) is not None), section.body_end)
        self._splice(anchor, anchor, [f'{key}{PROP_ASSIGN}{value}'])
        return 'added'

    def add_node(self, parent_path: str, name: str, node_type: str,
                 script: str | None = None, *, groups: tuple[str, ...] = (),
                 props: tuple[tuple[str, str], ...] = ()) -> None:
        """Add a typed node. `props` are written in the order given, then the
        script, which is where the saver puts `script` on a node: after the
        engine properties, before the exports."""
        parent = self.node(parent_path)
        parent_abs = self.node_path(parent)
        if any(self.node_path(n) == parent_abs + (name,) for n in self.nodes):
            raise TscnError(f'{parent_path!r} already has a child named {name!r}')
        header = (f'[node name="{name}" type="{node_type}" '
                  f'parent="{join_path(list(parent_abs))}"'
                  f'{self._unique_id_attr(parent_abs + (name,))}{_groups_attr(groups)}]')
        body = [header, *(f'{key}{PROP_ASSIGN}{value}' for key, value in props)]
        if script:
            ref_id = self._ensure_ext_resource(script, 'Script')
            body.append(f'{SCRIPT_PROP}{PROP_ASSIGN}{EXT_REF.format(id=ref_id)}')
        insert = self._subtree_end(self.node(parent_path))
        self._splice(insert, insert, ['', *body])

    def add_instance_node(self, parent_path: str, name: str, res_path: str) -> None:
        """Add an instance-of-a-scene node: `instance=ExtResource(...)`, and
        deliberately NO `type=` — the type lives in the instanced scene, and
        writing one here is how a hand edit forks the two."""
        parent = self.node(parent_path)
        parent_abs = self.node_path(parent)
        if any(self.node_path(n) == parent_abs + (name,) for n in self.nodes):
            raise TscnError(f'{parent_path!r} already has a child named {name!r}')
        ref_id = self._ensure_ext_resource(res_path, PACKED_SCENE_TYPE)
        header = (f'[node name="{name}" parent="{join_path(list(parent_abs))}"'
                  f'{self._unique_id_attr(parent_abs + (name,))} '
                  f'instance={EXT_REF.format(id=ref_id)}]')
        insert = self._subtree_end(self.node(parent_path))
        self._splice(insert, insert, ['', header])

    def ext_ref(self, res_path: str, res_type: str) -> str:
        """`ExtResource("id")` for `res_path`, reusing or minting its ext_resource."""
        return EXT_REF.format(id=self._ensure_ext_resource(res_path, res_type))

    def add_sub_resource(self, sub_type: str, seed: str,
                         props: tuple[tuple[str, str], ...]) -> str:
        """Append a `[sub_resource]` after the last one (or after the
        ext_resources) and return its id. The id is Godot's `Type_xxxxx` shape,
        derived from `seed` rather than drawn at random, so the same command on
        the same file mints the same id."""
        taken = {s.attrs.get('id') for s in self.sections if s.kind == SUB_RESOURCE_KIND}
        sub_id = next(candidate for salt in range(len(taken) + 1)
                      for candidate in [f'{sub_type}_{_short_hash(f"{seed}#{salt}")}']
                      if candidate not in taken)
        body = [f'[{SUB_RESOURCE_KIND} type="{sub_type}" id="{sub_id}"]',
                *(f'{key}{PROP_ASSIGN}{value}' for key, value in props)]
        anchor = max((s.body_end for s in self.sections
                      if s.kind in (SUB_RESOURCE_KIND, EXT_RESOURCE_KIND, *SCENE_KINDS)),
                     default=0)
        self._splice(anchor, anchor, ['', *body])
        self._bump_load_steps()
        return sub_id

    def _unique_id_attr(self, path: tuple[str, ...]) -> str:
        """` unique_id=N` when this file's nodes carry Godot 4.6+'s node ids,
        else nothing — a file that does not use them is not upgraded by one
        new node. N is derived from the node's path (deterministic, so a retry
        mints the same bytes) and moved past any id the file already holds."""
        held = {s.attrs['unique_id'] for s in self.nodes if 'unique_id' in s.attrs}
        if not held:
            return ''
        return f' {UNIQUE_ID_ATTR}={mint_unique_id(join_path(list(path)), held)}'

    def _subtree_end(self, section: Section) -> int:
        """The line index just past a node's own block and all its descendants'."""
        spans = [self._block_span(s) for s in (section, *self.descendants(section))]
        end = max(span[1] for span in spans)
        while end > 0 and not self.lines[end - 1].strip():
            end -= 1
        return end

    def _ensure_ext_resource(self, res_path: str, res_type: str) -> str:
        """Reuse or append an ext_resource for `res_path`; returns its id.
        The uid comes from the resource's committed `.uid` sidecar, so a scene
        authored here is born canonical (`check tres` demands uid-in-refs)."""
        for ref_id, section in self.ext_resources().items():
            if section.attrs.get('path') == res_path:
                return ref_id
        ref_id = mint_ext_id(res_path, self.ext_resources())
        self.add_ext_resource(res_path, res_type, ref_id)
        return ref_id

    def add_ext_resource(self, res_path: str, res_type: str, ref_id: str) -> None:
        """Append `[ext_resource]` for `res_path` under `ref_id`, uid from the sidecar."""
        used = self.ext_resources()
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
        # The first ext_resource opens its own block below the header, the way
        # the saver writes it; later ones join that block.
        line = f'[{EXT_RESOURCE_KIND} {attrs}]'
        self._splice(anchor, anchor, [line] if used else ['', line])
        self._bump_load_steps()

    def _uid_of(self, res_path: str) -> str | None:
        """The uid to write into a new ref, via the resolver the caller injected.

        `format/` sits below `index/`, so the resolver arrives from the write
        verb (`scene_edit.uid_resolver`) instead of being imported from here —
        the one upward import this layer ever had. No resolver means no uid:
        the ref is minted path-only and `_ensure_ext_resource` says so.
        """
        return self.uid_resolver(res_path) if self.uid_resolver is not None else None

    def _bump_load_steps(self) -> None:
        scene = next((s for s in self.sections if s.kind in SCENE_KINDS), None)
        if scene is None or LOAD_STEPS_ATTR not in scene.attrs:
            return                                   # format 4 omits load_steps
        steps = 1 + sum(1 for s in self.sections
                        if s.kind in (EXT_RESOURCE_KIND, SUB_RESOURCE_KIND))
        line = self.lines[scene.header_line]
        self._splice(scene.header_line, scene.header_line + 1,
                     [re.sub(rf'\b{LOAD_STEPS_ATTR}=\d+', f'{LOAD_STEPS_ATTR}={steps}', line)])


def mint_ext_id(res_path: str, used) -> str:
    """`<n>_<stem>`: one past the highest numbered id in `used`; the editor keeps it."""
    ordinal = max((int(k.split('_')[0]) for k in used if k.split('_')[0].isdigit()),
                  default=0) + 1
    stem = res_path.rsplit(PATH_SEP, 1)[-1].rsplit('.', 1)[0]
    return f'{ordinal}_{stem}'


def mint_unique_id(seed: str, held: set[str]) -> str:
    """A positive int32 node id derived from `seed`, stepped past `held`."""
    value = zlib.crc32(seed.encode('utf-8')) & UNIQUE_ID_MASK or 1
    while str(value) in held:
        value = value % UNIQUE_ID_MASK + 1
    return str(value)


def _short_hash(seed: str) -> str:
    number = int.from_bytes(hashlib.sha1(seed.encode('utf-8')).digest()[:8], 'big')
    chars = []
    for _ in range(SUB_ID_LENGTH):
        number, digit = divmod(number, len(SUB_ID_CHARS))
        chars.append(SUB_ID_CHARS[digit])
    return ''.join(chars)


def _groups_attr(groups: tuple[str, ...]) -> str:
    if not groups:
        return ''
    return ' groups=[' + ', '.join(f'"{g}"' for g in groups) + ']'
