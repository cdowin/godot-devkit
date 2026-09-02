"""gdscript.py — a repo-wide index of what each .gd script EXPORTS.

`check props` asks one question per assigned scene property: "does the script on
this node actually declare you?" Answering it needs three facts per .gd — its
`@export` names, its `extends` target (exports are inherited), and its
`class_name` (so another script's `extends Foo` resolves). This module is the
only place that reads GDScript source; everything else consumes `ScriptIndex`.

Deliberately a regex scanner, not a parser. The failure mode is handled instead
of avoided: anything the scanner cannot fully account for — a script that
synthesizes properties in `_get_property_list`/`_set`, an `extends` we cannot
resolve — marks the resolution OPAQUE, and an opaque script's nodes are reported
as UNVERIFIED rather than failed.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from godot_devkit.godot.index.gd_declarations import (
    Declaration,
    DeclarationFacts,
    scan_declarations,
)
from godot_devkit.godot.format.tscn import scan_line

RES_PREFIX = 'res://'

CLASS_NAME_RE = re.compile(r'^\s*class_name\s+([A-Za-z_]\w*)')
EXTENDS_RE = re.compile(r'^\s*extends\s+(.+?)\s*(?:#.*)?$')
EXPORT_RE = re.compile(r'^\s*@export')
VAR_RE = re.compile(r'\bvar\s+([A-Za-z_]\w*)')
GDSCRIPT_COMMENT = '#'
QUOTED_RE = re.compile(r'"([^"]+)"')
# `@export_group("A")` and friends annotate the inspector; they declare nothing.
NON_DECLARING_EXPORTS = ('@export_group', '@export_subgroup', '@export_category')
# A script implementing either of these can answer to property names that appear
# nowhere in its source — we must not call such a name dead.
DYNAMIC_PROPERTY_HOOKS = ('func _get_property_list', 'func _set')
# A quoted span, either GDScript quote style. Stripped before a line is
# pattern-matched: a call NAMED in an assert message or a log string is not a
# call, and a scanner that cannot tell those apart reports prose as code.
QUOTED_SPAN_RE = re.compile(r'"[^"]*"|\'[^\']*\'')
TRAILING_COMMENT_RE = re.compile(r'#.*$')
# What a masked quoted span is filled WITH. Neither an identifier character nor
# a bracket, quote or comma, so nothing a scanner counts can hide inside it.
MASK_CHAR = '~'


@dataclass
class ScriptFacts:
    """What one .gd file declares, before inheritance is resolved."""
    res_path: str
    class_name: str | None = None
    extends: str | None = None
    exports: set[str] = field(default_factory=set)
    dynamic_properties: bool = False
    # What each export is DECLARED as (type + initializer) and the script's
    # enum tables — the value grammar `check defaults` compares against.
    declared: DeclarationFacts = field(default_factory=DeclarationFacts)


@dataclass
class Resolution:
    """A script's exports WITH inheritance folded in."""
    exports: frozenset[str]
    engine_base: str | None       # the Godot class the `extends` chain lands on
    opaque: bool                  # True => do not call anything on it "dead"
    # Inheritance-folded declarations; a subclass re-declaring a name wins.
    declarations: dict[str, Declaration] = field(default_factory=dict)
    enum_members: dict[str, int] = field(default_factory=dict)
    consts: dict[str, str] = field(default_factory=dict)
    aliases: dict[str, str] = field(default_factory=dict)


def code_only(line: str) -> str:
    """One source line with its quoted spans MASKED and its comment removed.

    What is left is the part a scanner may match against without confusing
    prose for code. Masked, not deleted, and that is load-bearing twice: column
    offsets survive, so a caller counting arguments reads the same positions
    the line has; and a lone string argument stays ONE argument instead of
    vanishing into an empty call. Strings are masked before the comment is cut,
    because a `#` inside a string is not a comment.

    Length is preserved up to the comment, so `line[:len(code_only(line))]` is
    the same line with its comment gone and its strings intact — which is what
    a caller matching a PATH literal needs.
    """
    masked = QUOTED_SPAN_RE.sub(lambda m: MASK_CHAR * len(m.group(0)), line)
    return TRAILING_COMMENT_RE.sub('', masked)


def scan_script(text: str, res_path: str) -> ScriptFacts:
    """Extract class_name / extends / @export names from one .gd source."""
    facts = ScriptFacts(res_path=res_path, declared=scan_declarations(text))
    pending_export = False
    lines = text.split('\n')
    index = -1
    while index + 1 < len(lines):
        index += 1
        line = lines[index]
        stripped = line.strip()
        if facts.class_name is None:
            match = CLASS_NAME_RE.match(line)
            if match:
                facts.class_name = match.group(1)
        if facts.extends is None:
            match = EXTENDS_RE.match(line)
            if match:
                facts.extends = match.group(1).strip()
        if stripped.startswith(DYNAMIC_PROPERTY_HOOKS):
            facts.dynamic_properties = True
        if EXPORT_RE.match(line):
            if stripped.startswith(NON_DECLARING_EXPORTS):
                continue
            # `@export_flags(\n  "A:1",\n) var x` — fold the annotation's
            # argument list back onto one line before looking for the `var`.
            folded = line
            depth, in_string, escaped, _ = scan_line(line, comment_char=GDSCRIPT_COMMENT)
            while (depth > 0 or in_string) and index + 1 < len(lines):
                index += 1
                folded += ' ' + lines[index].strip()
                depth, in_string, escaped, _ = scan_line(
                    lines[index], depth, in_string, escaped, GDSCRIPT_COMMENT)
            line = folded
            match = VAR_RE.search(line)
            if match:
                facts.exports.add(match.group(1))
                pending_export = False
            else:
                pending_export = True      # bare `@export` on its own line
            continue
        if pending_export:
            if not stripped or stripped.startswith('#'):
                continue
            match = VAR_RE.search(line)
            if match:
                facts.exports.add(match.group(1))
            pending_export = False
    return facts


class ScriptIndex:
    """Every .gd in a repo, keyed by `res://` path and by `class_name`."""

    def __init__(self, root: Path, rel_paths: list[str]) -> None:
        self.root = root
        self.by_path: dict[str, ScriptFacts] = {}
        self.by_class: dict[str, str] = {}
        for rel in rel_paths:
            file = root / rel
            try:
                text = file.read_text(encoding='utf-8', errors='replace')
            except OSError:
                continue
            res_path = RES_PREFIX + rel
            facts = scan_script(text, res_path)
            self.by_path[res_path] = facts
            if facts.class_name:
                self.by_class[facts.class_name] = res_path
        self._cache: dict[str, Resolution] = {}

    def has(self, res_path: str) -> bool:
        return res_path in self.by_path

    def resolve(self, res_path: str) -> Resolution:
        """Fold the `extends` chain into one export set + engine base class."""
        cached = self._cache.get(res_path)
        if cached is None:
            cached = self._resolve(res_path, set())
            self._cache[res_path] = cached
        return cached

    def _resolve(self, res_path: str, seen: set[str]) -> Resolution:
        from godot_devkit.godot.format import classdb

        facts = self.by_path.get(res_path)
        if facts is None or res_path in seen:
            return Resolution(frozenset(), None, opaque=True)
        seen.add(res_path)
        exports = set(facts.exports)
        opaque = facts.dynamic_properties
        base: str | None = None
        declarations: dict[str, Declaration] = {}
        enum_members: dict[str, int] = {}
        consts: dict[str, str] = {}
        aliases: dict[str, str] = {}

        def inherit(parent: Resolution) -> None:
            declarations.update(parent.declarations)
            enum_members.update(parent.enum_members)
            consts.update(parent.consts)
            aliases.update(parent.aliases)

        target = facts.extends
        if target is None:
            base = 'RefCounted'                    # implicit base of a bare script
        elif target.startswith(('"', 'preload')):
            match = QUOTED_RE.search(target)
            parent = self._resolve(match.group(1), seen) if match else None
            if parent is None:
                opaque = True
            else:
                exports |= parent.exports
                base = parent.engine_base
                opaque = opaque or parent.opaque
                inherit(parent)
        elif target in self.by_class:
            parent = self._resolve(self.by_class[target], seen)
            exports |= parent.exports
            base = parent.engine_base
            opaque = opaque or parent.opaque
            inherit(parent)
        elif classdb.is_known(target):
            base = target
        else:
            opaque = True                          # e.g. `extends SomeAddonClass`
        declarations.update(facts.declared.declarations)
        enum_members.update(facts.declared.enum_members)
        consts.update(facts.declared.consts)
        aliases.update(facts.declared.aliases)
        for enum_name, members in facts.declared.enums.items():
            for member, value in members.items():
                enum_members[f'{enum_name}.{member}'] = value
        return Resolution(frozenset(exports), base, opaque, declarations,
                          enum_members, consts, aliases)
