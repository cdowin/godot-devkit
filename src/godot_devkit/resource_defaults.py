"""resource_defaults.py — which `.tres` assignments Godot's writer would DROP.

Two writers produce different-but-equivalent text for the same resource, and a
repo that holds one form while the editor emits the other diffs forever:

  * **hand-authored** `.tres` spell every property out, defaults included;
  * **Godot's writer** omits any property whose value equals the declared
    default (`ResourceFormatSaverText` skips it), so `trigger = 0` for
    `@export var trigger: Trigger = Trigger.ALL_PLAYERS_DOWN` vanishes on the
    first editor save. Same meaning, different bytes, churn on every session.

This module answers one question per assignment: **is this value PROVABLY the
declared default?** Deleting such a line cannot change what loads — the
initializer supplies the same value — which is what makes the fix safe in bulk
where a load-and-re-save is not (that reorders properties, respells typed arrays
and floats, mints `ext_resource` ids, and deletes every `;` comment in the file).

Proof, not inference. Both sides normalise into one small CLOSED value language
(bool / number / string / empty array / empty dict / null / numeric
constructor), and only two values that both landed inside it are ever compared.
Everything else — an accessor on the export, an engine built-in with no default
table, a `preload()` default, an unresolvable `extends` — is censused as
UNVERIFIED and left strictly alone. A missed redundancy costs a diff; a wrong
one costs a data file.
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass

from godot_devkit.gd_declarations import Declaration
from godot_devkit.gdscript import Resolution, ScriptIndex
from godot_devkit.tscn import Prop, Section, ext_index, script_path

CHECKED_KINDS = ('resource', 'sub_resource')
SCRIPT_PROP = 'script'
PATH_FORM_KEY = '/'
INTERNAL_PREFIX = '_'

INT_RE = re.compile(r'^-?\d+$')
FLOAT_RE = re.compile(r'^-?(?:\d+\.\d*|\.\d+|\d+)(?:[eE][-+]?\d+)?$')
STRING_RE = re.compile(r'^"((?:[^"\\]|\\.)*)"$')
STRING_NAME_RE = re.compile(r'^&"((?:[^"\\]|\\.)*)"$')
TYPED_EMPTY_ARRAY_RE = re.compile(r'^Array\[.+\]\(\s*\[\s*\]\s*\)$')
TYPED_EMPTY_DICT_RE = re.compile(r'^Dictionary\[.+\]\(\s*\{\s*\}\s*\)$')
CTOR_RE = re.compile(r'^([A-Z]\w*)\(([^()]*)\)$')
QUALIFIED_RE = re.compile(r'^([A-Za-z_]\w*)\.([A-Za-z_]\w*)$')
BARE_NAME_RE = re.compile(r'^[A-Za-z_]\w*$')
DOTTED_RE = re.compile(r'^[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)+$')
ARRAY_TYPE_RE = re.compile(r'^Array(\[.+\])?$')
DICT_TYPE_RE = re.compile(r'^Dictionary(\[.+\])?$')

# The constructors whose arguments are plain numbers, so two spellings of the
# same value ("Vector2(0, 0)" vs "Vector2.ZERO") compare by arithmetic.
NUMERIC_CTORS = frozenset((
    'Vector2', 'Vector2i', 'Vector3', 'Vector3i', 'Vector4', 'Vector4i',
    'Rect2', 'Rect2i', 'Color', 'Quaternion', 'Plane',
))
# GDScript's zero value per declared type — what an `@export var x: T` with no
# initializer holds, and therefore what the writer compares against.
ZERO_BY_TYPE: dict[str, tuple] = {
    'int': ('num', 0.0),
    'float': ('num', 0.0),
    'bool': ('bool', False),
    'String': ('str', ''),
    'StringName': ('str', ''),
    'NodePath': ('str', ''),
    'Array': ('arr',),
    'Dictionary': ('dict',),
    'Vector2': ('ctor', 'Vector2', (0.0, 0.0)),
    'Vector2i': ('ctor', 'Vector2i', (0.0, 0.0)),
    'Vector3': ('ctor', 'Vector3', (0.0, 0.0, 0.0)),
    'Vector3i': ('ctor', 'Vector3i', (0.0, 0.0, 0.0)),
    'Vector4': ('ctor', 'Vector4', (0.0, 0.0, 0.0, 0.0)),
    'Vector4i': ('ctor', 'Vector4i', (0.0, 0.0, 0.0, 0.0)),
    'Rect2': ('ctor', 'Rect2', (0.0, 0.0, 0.0, 0.0)),
    'Rect2i': ('ctor', 'Rect2i', (0.0, 0.0, 0.0, 0.0)),
    'Color': ('ctor', 'Color', (0.0, 0.0, 0.0, 1.0)),
}
# Named constants a default is allowed to spell. Deliberately short: each entry
# is a claim about the engine, and a wrong one deletes a line that mattered.
NAMED_CONSTANTS: dict[str, tuple] = {
    'Vector2.ZERO': ('ctor', 'Vector2', (0.0, 0.0)),
    'Vector2.ONE': ('ctor', 'Vector2', (1.0, 1.0)),
    'Vector2i.ZERO': ('ctor', 'Vector2i', (0.0, 0.0)),
    'Vector2i.ONE': ('ctor', 'Vector2i', (1.0, 1.0)),
    'Vector3.ZERO': ('ctor', 'Vector3', (0.0, 0.0, 0.0)),
    'Vector3.ONE': ('ctor', 'Vector3', (1.0, 1.0, 1.0)),
    'Color.WHITE': ('ctor', 'Color', (1.0, 1.0, 1.0, 1.0)),
    'Color.BLACK': ('ctor', 'Color', (0.0, 0.0, 0.0, 1.0)),
    'Color.TRANSPARENT': ('ctor', 'Color', (0.0, 0.0, 0.0, 0.0)),
    'Vector2.UP': ('ctor', 'Vector2', (0.0, -1.0)),
    'Vector2.DOWN': ('ctor', 'Vector2', (0.0, 1.0)),
    'Vector2.LEFT': ('ctor', 'Vector2', (-1.0, 0.0)),
    'Vector2.RIGHT': ('ctor', 'Vector2', (1.0, 0.0)),
}
# `const A = preload(...)` chains are walked, not guessed; the cap only stops a
# cyclic `const A = preload(self)` from spinning.
MAX_SYMBOL_HOPS = 6

NO_SCRIPT = 'section has no script (engine resource — no default table)'
SCRIPT_UNREADABLE = 'script not readable'
SCRIPT_OPAQUE = 'script declares dynamic properties or an unresolved extends'
NOT_DECLARED = 'not an @export of the script (engine built-in — no default table)'
HAS_ACCESSOR = 'export has a setter/getter (stored value need not be the assigned one)'
DEFAULT_UNKNOWN = 'default expression outside the comparable value language'
VALUE_UNKNOWN = 'assigned value outside the comparable value language'
DIFFERS = 'value differs from the default (correctly written out)'


@dataclass
class Redundant:
    """One assignment Godot's writer would omit — and the evidence for saying so."""
    section: Section
    prop: Prop
    where: str                 # `[resource]` / `[sub_resource id="X"]`
    default: str               # the declared default, as the .gd spells it


def _unescape(text: str) -> str:
    return text.replace('\\"', '"').replace('\\\\', '\\')


def _numbers(argument_text: str) -> tuple[float, ...] | None:
    parts = [p.strip() for p in argument_text.split(',') if p.strip()]
    values: list[float] = []
    for part in parts:
        if not FLOAT_RE.match(part):
            return None
        values.append(float(part))
    return tuple(values)


def literal(text: str) -> tuple | None:
    """Normalise ONE spelling — .tres or GDScript — into the closed language.

    Returns None for anything outside it, which is the refusal path: the caller
    must never compare a value it could not fully parse.
    """
    value = text.strip()
    if value in ('true', 'false'):
        return ('bool', value == 'true')
    if value == 'null':
        return ('null',)
    if INT_RE.match(value) or FLOAT_RE.match(value):
        return ('num', float(value))
    match = STRING_RE.match(value) or STRING_NAME_RE.match(value)
    if match:
        return ('str', _unescape(match.group(1)))
    if value == '[]' or TYPED_EMPTY_ARRAY_RE.match(value):
        return ('arr',)
    if value == '{}' or TYPED_EMPTY_DICT_RE.match(value):
        return ('dict',)
    if value in NAMED_CONSTANTS:
        return NAMED_CONSTANTS[value]
    ctor = CTOR_RE.match(value)
    if ctor and ctor.group(1) in NUMERIC_CTORS:
        numbers = _numbers(ctor.group(2))
        if numbers is not None:
            return ('ctor', ctor.group(1), numbers)
    return None


def resolve_symbol(scripts: ScriptIndex, resolution: Resolution, name: str,
                   hops: int = 0) -> tuple | None:
    """Normalise a NAMED default — an enum member, a `const`, or either of those
    reached through a `const Alias = preload(...)` — or None if unprovable.

    `RoomType.Type.COMBAT` is the shape that makes this worth having: an alias
    to another script, an enum inside it, a member inside that. Every hop is
    evidence from a file we parsed; nothing is guessed.
    """
    if hops > MAX_SYMBOL_HOPS:
        return None
    member = resolution.enum_members.get(name)
    if member is not None:
        return ('num', float(member))
    expression = resolution.consts.get(name)
    if expression is not None:
        return literal(expression) or resolve_symbol(
            scripts, resolution, expression, hops + 1)
    head, separator, tail = name.partition('.')
    if not separator:
        return None
    target = resolution.aliases.get(head) or scripts.by_class.get(head)
    if target is None or not scripts.has(target):
        return None
    return resolve_symbol(scripts, scripts.resolve(target), tail, hops + 1)


def default_of(decl: Declaration, resolution: Resolution,
               scripts: ScriptIndex, enum_types: frozenset[str]) -> tuple | None:
    """The declared default of one export, normalised — or None if unprovable."""
    if decl.default is None:
        return _zero_of(decl.declared_type, enum_types)
    parsed = literal(decl.default)
    if parsed is not None:
        return parsed
    if QUALIFIED_RE.match(decl.default) or BARE_NAME_RE.match(decl.default) \
            or DOTTED_RE.match(decl.default):
        return resolve_symbol(scripts, resolution, decl.default)
    return None


def _zero_of(declared_type: str | None, enum_types: frozenset[str]) -> tuple | None:
    """`@export var x: T` with no initializer holds T's zero value."""
    if declared_type is None:
        return None                       # untyped, uninitialised: Variant null,
                                          # but the writer's view is not provable
    if declared_type in ZERO_BY_TYPE:
        return ZERO_BY_TYPE[declared_type]
    if ARRAY_TYPE_RE.match(declared_type):
        return ('arr',)
    if DICT_TYPE_RE.match(declared_type):
        return ('dict',)
    if declared_type in enum_types:
        return ('num', 0.0)
    if declared_type[:1].isupper():
        return ('null',)                  # an Object/Resource type defaults null
    return None


def _label(section: Section) -> str:
    if section.kind == 'resource':
        return '[resource]'
    return f'[{section.kind} id="{section.attrs.get("id", "?")}"]'


class DefaultAnalyzer:
    """Answers `analyze()` for every section of one parsed `.tres`."""

    def __init__(self, scripts: ScriptIndex) -> None:
        self.scripts = scripts

    def analyze(self, sections: list[Section],
                census: Counter | None = None) -> list[Redundant]:
        """-> the redundant assignments; everything else lands in `census`."""
        census = Counter() if census is None else census
        ext = ext_index(sections)
        findings: list[Redundant] = []
        for section in sections:
            if section.kind not in CHECKED_KINDS:
                continue
            findings += self._analyze_section(section, ext, census)
        return findings

    def _analyze_section(self, section: Section, ext: dict[str, dict],
                         census: Counter) -> list[Redundant]:
        entries = [e for e in section.entries if not _is_skipped_key(e.key)]
        census['engine-synthesized key (script / _x / a/b form)'] += (
            len(section.entries) - len(entries))
        if not entries:
            return []
        script_rel = script_path(section, ext)
        if script_rel is None:
            census[NO_SCRIPT] += len(entries)
            return []
        if not self.scripts.has(script_rel):
            census[SCRIPT_UNREADABLE] += len(entries)
            return []
        resolved = self.scripts.resolve(script_rel)
        if resolved.opaque:
            census[SCRIPT_OPAQUE] += len(entries)
            return []
        enum_types = frozenset(
            key.split('.', 1)[0] for key in resolved.enum_members if '.' in key)
        findings: list[Redundant] = []
        for entry in entries:
            decl = resolved.declarations.get(entry.key)
            if decl is None:
                census[NOT_DECLARED] += 1
                continue
            if decl.has_accessor:
                census[HAS_ACCESSOR] += 1
                continue
            declared = default_of(decl, resolved, self.scripts, enum_types)
            if declared is None:
                census[DEFAULT_UNKNOWN] += 1
                continue
            assigned = literal(entry.value)
            if assigned is None:
                census[VALUE_UNKNOWN] += 1
                continue
            if assigned != declared:
                census[DIFFERS] += 1
                continue
            findings.append(Redundant(section, entry, _label(section),
                                      decl.default or f'{decl.declared_type}()'))
        return findings


def _is_skipped_key(key: str) -> bool:
    return (key == SCRIPT_PROP or PATH_FORM_KEY in key
            or key.startswith(INTERNAL_PREFIX))
