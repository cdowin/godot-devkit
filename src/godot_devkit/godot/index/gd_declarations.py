"""gd_declarations.py — the DECLARATION half of a GDScript `@export`.

`gdscript.py` answers "does this script export a property called X?". Deciding
whether a `.tres` assignment is REDUNDANT needs three more facts about the same
declaration, and all three come from the one folded source line:

    @export var trigger: Trigger = Trigger.ALL_PLAYERS_DOWN
                 ^name   ^type      ^default expression

plus the script's `enum` tables, because an enum member is the single most
common default spelling in hand-authored data (`trigger = 0` IS
`Trigger.ALL_PLAYERS_DOWN`, and no regex over the `.tres` can know that).

Split out of `gdscript.py` rather than folded into it because the two answer
different questions on different grains: `ScriptFacts` is a NAME SET the props
gate consumes, this is a per-name value grammar. The scanner shares
`gdscript.py`'s honesty valve: a declaration it cannot fully account for — an
accessor, a call, an unresolved identifier — leaves `default` unusable, and an
unusable default can never justify deleting a line.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from godot_devkit.godot.format.tscn import scan_line

GDSCRIPT_COMMENT = '#'
VAR_KEYWORD = 'var'
ENUM_KEYWORD = 'enum'
INFER_ASSIGN = ':='
EXPORT_ANNOTATION = '@export'
DECL_RE = re.compile(r'\bvar\s+([A-Za-z_]\w*)\s*(.*)$')
ENUM_RE = re.compile(r'^enum\s*([A-Za-z_]\w*)?\s*\{')
ENUM_MEMBER_RE = re.compile(r'^([A-Za-z_]\w*)\s*(?:=\s*(-?\d+))?$')
# `[^=]*` (not `+`) so the inferred form `const X := 1` parses too.
CONST_RE = re.compile(r'^const\s+([A-Za-z_]\w*)\s*(?::\s*[^=]*)?=\s*(.+)$')
PRELOAD_RE = re.compile(r'^preload\(\s*"([^"]+)"\s*\)$')
CONST_KEYWORD = 'const'
OPEN_BRACKETS = '([{'
CLOSE_BRACKETS = ')]}'


@dataclass
class Declaration:
    """One `@export var` as written: its type annotation and its initializer."""
    name: str
    declared_type: str | None = None     # 'int', 'Array[Foo]', 'Trigger', ...
    default: str | None = None           # initializer source, comment-stripped
    has_accessor: bool = False           # `: set = f` / `: set(v):` / `: get:`


@dataclass
class DeclarationFacts:
    """Everything one .gd says about the VALUES of its exports."""
    declarations: dict[str, Declaration] = field(default_factory=dict)
    enums: dict[str, dict[str, int]] = field(default_factory=dict)
    # Every enum member, unqualified — GDScript lets a default spell either
    # `Trigger.ALL_PLAYERS_DOWN` or the bare `ALL_PLAYERS_DOWN`.
    enum_members: dict[str, int] = field(default_factory=dict)
    # `const SPEED := 300.0` — a default is allowed to name one.
    consts: dict[str, str] = field(default_factory=dict)
    # `const PlayerIdentity = preload("res://…")` — how `Alias.MEMBER` resolves.
    aliases: dict[str, str] = field(default_factory=dict)


def fold(lines: list[str], index: int) -> tuple[str, int]:
    """Join a statement that spans lines into one comment-stripped string.

    Continues while brackets are open or a string is unterminated — the same
    string-aware scan the .tres grammar uses, so a `#` inside a default string
    literal and a `{` inside a Dictionary default both behave.
    """
    depth, in_string, escaped, comment_at = scan_line(
        lines[index], comment_char=GDSCRIPT_COMMENT, comment_in_brackets=True)
    folded = lines[index][:comment_at] if comment_at >= 0 else lines[index]
    while (depth > 0 or in_string) and index + 1 < len(lines):
        index += 1
        depth, in_string, escaped, comment_at = scan_line(
            lines[index], depth, in_string, escaped, GDSCRIPT_COMMENT,
            comment_in_brackets=True)
        body = lines[index][:comment_at] if comment_at >= 0 else lines[index]
        folded += ' ' + body.strip()
    return folded.rstrip(), index


def top_level(text: str, wanted: str) -> int:
    """Index of `wanted` at bracket depth 0 and outside any string, else -1."""
    depth = 0
    in_string = False
    escaped = False
    for position, char in enumerate(text):
        if in_string:
            if escaped:
                escaped = False
            elif char == '\\':
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char in OPEN_BRACKETS:
            depth += 1
        elif char in CLOSE_BRACKETS:
            depth -= 1
        elif depth == 0 and text.startswith(wanted, position):
            return position
    return -1


def _cut_accessor(text: str, decl: Declaration) -> str:
    """Drop a `: set = f` / `: get(): ...` tail, flagging that it existed.

    Anything after a top-level `:` in a var declaration is an accessor clause,
    and an accessor means the STORED value need not be the assigned one — so
    the flag is what makes the caller refuse rather than compare.
    """
    colon = top_level(text, ':')
    if colon < 0:
        return text
    decl.has_accessor = True
    return text[:colon]


def parse_declaration(folded: str) -> Declaration | None:
    """`@export var x: T = expr` -> a Declaration, or None if there is no `var`."""
    match = DECL_RE.search(folded)
    if match is None:
        return None
    decl = Declaration(name=match.group(1))
    rest = match.group(2).strip()
    if rest.startswith(INFER_ASSIGN):
        body = rest[len(INFER_ASSIGN):]
    elif rest.startswith(':'):
        typed = rest[1:]
        assign = top_level(typed, '=')
        if assign < 0:
            decl.declared_type = _cut_accessor(typed, decl).strip() or None
            return decl
        decl.declared_type = typed[:assign].strip() or None
        body = typed[assign + 1:]
    elif rest.startswith('='):
        body = rest[1:]
    else:
        return decl                       # bare `var x` — untyped, no default
    decl.default = _cut_accessor(body, decl).strip() or None
    return decl


def parse_enum(folded: str) -> tuple[str | None, dict[str, int]] | None:
    """`enum Trigger { A, B = 3, C }` -> ('Trigger', {'A': 0, 'B': 3, 'C': 4}).

    Returns None when any member is an expression we cannot evaluate — a
    partially-known enum would silently mis-resolve every member after it.
    """
    header = ENUM_RE.match(folded)
    if header is None:
        return None
    body = folded[folded.index('{') + 1:]
    close = body.rfind('}')
    if close < 0:
        return None
    members: dict[str, int] = {}
    following = 0
    for raw in body[:close].split(','):
        item = raw.strip()
        if not item:
            continue
        entry = ENUM_MEMBER_RE.match(item)
        if entry is None:
            return None                   # `A = SOME_CONST` / a bit expression
        value = following if entry.group(2) is None else int(entry.group(2))
        members[entry.group(1)] = value
        following = value + 1
    return header.group(1), members


def scan_declarations(text: str) -> DeclarationFacts:
    """Every `@export` declaration and every `enum` in one .gd source."""
    facts = DeclarationFacts()
    lines = text.split('\n')
    index = -1
    pending_export = False
    while index + 1 < len(lines):
        index += 1
        stripped = lines[index].strip()
        if stripped.startswith(CONST_KEYWORD + ' '):
            folded, index = fold(lines, index)
            entry = CONST_RE.match(folded.strip())
            if entry is not None:
                name, expression = entry.group(1), entry.group(2).strip()
                preload = PRELOAD_RE.match(expression)
                if preload:
                    facts.aliases[name] = preload.group(1)
                else:
                    facts.consts[name] = expression
            continue
        if ENUM_RE.match(stripped):
            folded, index = fold(lines, index)
            parsed = parse_enum(folded.strip())
            if parsed is not None:
                name, members = parsed
                if name:
                    facts.enums[name] = members
                facts.enum_members.update(members)
            continue
        if not (stripped.startswith(EXPORT_ANNOTATION) or pending_export):
            continue
        if stripped.startswith(EXPORT_ANNOTATION):
            folded, index = fold(lines, index)
            stripped = folded.strip()
            if VAR_KEYWORD not in stripped:
                # `@export_group("x")` declares nothing; a bare `@export` on its
                # own line declares the NEXT line's var.
                pending_export = not stripped.startswith(
                    (EXPORT_ANNOTATION + '_group', EXPORT_ANNOTATION + '_subgroup',
                     EXPORT_ANNOTATION + '_category'))
                continue
        else:
            folded, index = fold(lines, index)
            stripped = folded.strip()
            if not stripped or stripped.startswith(GDSCRIPT_COMMENT):
                continue
        pending_export = False
        declaration = parse_declaration(stripped)
        if declaration is not None:
            facts.declarations[declaration.name] = declaration
    return facts
