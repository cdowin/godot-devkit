"""resource_canonical.py — what Godot's text saver would RE-SPELL or REORDER in a `.tres`.

The sibling of `resource_defaults.py`, from the same evidence: the section's own
script, read through `ScriptIndex`, plus the ClassDB snapshot. Where that says
DELETE (a value equal to its default), this says REWRITE, in two dimensions a
parse can prove and no others:

* **spelling** — a float the saver writes shorter (`0.30` -> `0.3`, a FLOAT
  slot's int as `1.0`), per `format/value_spelling.py`; and a bare `[a, b]`
  on an `@export var x: Array[T]` wrapped the way the saver writes a typed
  array, `Array[T]([a, b])`. `T` is spelled as the saver spells it: a builtin
  by name, an engine class by name, a `class_name` script as
  `ExtResource("<id>")` — and only when the file already carries that
  ext_resource, because minting one is a different edit.
* **order** — the saver writes `script` and then the script's properties in
  DECLARATION order, the base script's first. That is knowable only for a
  section whose every key is `script` or a declared `@export`: an engine
  property (`resource_name`) is written before `script` in an order the
  sorted ClassDB snapshot does not keep, so such a section is left alone and
  counted, never guessed at.

Everything is refused rather than approximated. A property whose type the
script does not settle is OPAQUE — its floats are counted, and named only when
no saver could have written them (`0.30`); an element type that is an enum, an
inner class or an addon class is refused by name; an export with an accessor
is refused whole, because the saver writes what the GETTER returns. A refused
property is never partly rewritten.
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field

from godot_devkit.godot.format import classdb
from godot_devkit.godot.format.tscn import EXT_RESOURCE_KIND, Prop, Section, ext_index, script_path
from godot_devkit.godot.format.value_spelling import (
    COMPONENT_CTORS,
    FLOAT_CONTEXT,
    IDENT,
    NUMBER,
    OPAQUE_CONTEXT,
    PUNCT,
    STRING,
    VARIANT_CONTEXT,
    Token,
    ValueSyntaxError,
    apply_edits,
    bare_list,
    is_float_text,
    looks_noncanonical,
    matching,
    respell,
    scan_value,
    split_items,
    typed_array,
)
from godot_devkit.godot.index.gd_declarations import Declaration
from godot_devkit.godot.index.gdscript import Resolution, ScriptIndex

CHECKED_KINDS = ('resource', 'sub_resource')
SCRIPT_PROP = 'script'
SCRIPT_TYPE = 'Script'
ASSIGN = '='
ARRAY_OF_RE = re.compile(r'^Array\[(.+)\]$')
UNTYPED_CONTAINERS = ('Array', 'Dictionary')
FLOAT_TYPE = 'float'
LIST_DEFAULT = '['
DICT_DEFAULT = '{'
WRAP_OPEN = 'Array[{element}]('
WRAP_CLOSE = ')'
EXT_REF = 'ExtResource("{id}")'
RESOURCE_REFS = ('ExtResource', 'SubResource')
NULL = 'null'
BOOLS = ('true', 'false')
STRING_NAME_PREFIX = '&'
NODE_PATH_CTOR = 'NodePath'
# The integer-component constructors: a typed-array element of these is a
# constructor like any other, its numbers are simply not floats.
INT_CTORS = frozenset(('Vector2i', 'Vector3i', 'Vector4i', 'Rect2i'))
SCALAR_ELEMENTS = frozenset(('int', 'float', 'bool', 'String', 'StringName', 'NodePath'))

# Census reasons — NOT findings: what a parse cannot settle, counted so a PASS
# says how much it did not judge.
NO_SCRIPT = 'section has no script (engine resource — types and order not knowable)'
SCRIPT_UNREADABLE = 'script not readable'
SCRIPT_OPAQUE = 'script declares dynamic properties or an unresolved extends'
NOT_DECLARED = 'not an @export of the script (engine built-in — type not knowable)'
HAS_ACCESSOR = 'export has a setter/getter (the saver writes what the getter returns)'
UNVERIFIED_FLOAT = 'float whose spelling depends on a type or precision a parse cannot see'
OUTSIDE_GRAMMAR = 'value outside the grammar the respell reads'
REFUSED = 'refused by name (the saver would re-spell it; the tool cannot prove how)'
ORDER_UNKNOWABLE = 'section holds an engine property or an undeclared key (order not knowable)'
ORDER_INTERLEAVED = 'section order drifts but a comment or blank line sits among its properties'
ORDER_DUPLICATE = 'section assigns one key twice'


@dataclass
class Rewrite:
    """One property the saver would spell differently, and its new lines."""
    section: Section
    prop: Prop
    where: str
    lines: list[str]              # same count as the property occupies
    changes: list[str]            # `0.30 -> 0.3`, `wrap Array[int]`, ...


@dataclass
class Refusal:
    """A property or section the saver would rewrite that this tool cannot prove."""
    where: str
    key: str
    reason: str


@dataclass
class Reorder:
    """One section whose properties the saver writes in a different order."""
    section: Section
    where: str
    order: list[Prop]
    moved: list[tuple[Prop, int]]   # each property whose position changes, 1-based


@dataclass
class Analysis:
    rewrites: list[Rewrite] = field(default_factory=list)
    reorders: list[Reorder] = field(default_factory=list)
    refusals: list[Refusal] = field(default_factory=list)


@dataclass(frozen=True)
class _Slot:
    """What the declaration says about the numbers and lists in one value."""
    scalar: str | None = OPAQUE_CONTEXT
    elements: str | None = OPAQUE_CONTEXT
    element_type: str | None = None       # T of a declared Array[T]


def label(section: Section) -> str:
    if section.kind == 'resource':
        return '[resource]'
    return f'[{section.kind} id="{section.attrs.get("id", "?")}"]'


def _slot(decl: Declaration | None) -> _Slot:
    """The contexts a declaration puts a value's positions in."""
    if decl is None:
        return _Slot()
    declared = decl.declared_type
    if declared is None:
        # `@export var x = 0.3` / `:= 0.3` — a float either way; an untyped or
        # inferred list or dictionary holds Variants.
        default = (decl.default or '').strip()
        if default.startswith((LIST_DEFAULT, DICT_DEFAULT)):
            return _Slot(elements=VARIANT_CONTEXT)
        try:
            tokens, _ = scan_value(default, 0)
        except ValueSyntaxError:
            return _Slot()
        if len(tokens) == 1 and tokens[0].kind == NUMBER and is_float_text(tokens[0].text):
            return _Slot(scalar=VARIANT_CONTEXT)
        return _Slot()
    if declared == FLOAT_TYPE:
        return _Slot(scalar=FLOAT_CONTEXT)
    if declared in UNTYPED_CONTAINERS:
        return _Slot(elements=VARIANT_CONTEXT)
    typed = ARRAY_OF_RE.match(declared)
    if typed:
        element = typed.group(1).strip()
        return _Slot(elements=FLOAT_CONTEXT if element == FLOAT_TYPE else OPAQUE_CONTEXT,
                     element_type=element)
    return _Slot()


def _is_call(item: list[Token], names) -> bool:
    return (len(item) >= 3 and item[0].kind == IDENT and item[0].text in names
            and item[1].text == '(' and matching(item, 1) == len(item) - 1)


def _element_fits(element_type: str, is_object: bool, item: list[Token]) -> bool:
    """Is this list item already in the form the saver writes for `element_type`?"""
    if is_object:
        return ((len(item) == 1 and item[0].text == NULL)
                or (_is_call(item, RESOURCE_REFS) and len(item) == 4
                    and item[2].kind == STRING))
    if element_type in COMPONENT_CTORS or element_type in INT_CTORS:
        return _is_call(item, (element_type,))
    kinds = [(t.kind, t.text if t.kind != STRING else '') for t in item]
    if element_type == 'int':
        return len(item) == 1 and item[0].kind == NUMBER and not is_float_text(item[0].text)
    if element_type == FLOAT_TYPE:
        return len(item) == 1 and item[0].kind == NUMBER
    if element_type == 'bool':
        return len(item) == 1 and item[0].kind == IDENT and item[0].text in BOOLS
    if element_type == 'String':
        return kinds == [(STRING, '')]
    if element_type == 'StringName':
        return kinds == [(PUNCT, STRING_NAME_PREFIX), (STRING, '')]
    if element_type == NODE_PATH_CTOR:
        return _is_call(item, (NODE_PATH_CTOR,)) and len(item) == 4 and item[2].kind == STRING
    return False


class CanonicalAnalyzer:
    """Answers `analyze()` for every section of one parsed `.tres`."""

    def __init__(self, scripts: ScriptIndex) -> None:
        self.scripts = scripts

    def analyze(self, lines: list[str], sections: list[Section],
                census: Counter | None = None, *, spelling: bool = True,
                order: bool = True) -> Analysis:
        """-> what the saver would rewrite; everything unsettled lands in `census`.

        `lines` are the document's line contents — the spans every `Prop`
        indexes — so a rewrite is computed against the bytes, never against
        the parser's folded view of them.
        """
        census = Counter() if census is None else census
        ext = ext_index(sections)
        script_refs = self._script_refs(sections)
        analysis = Analysis()
        for section in sections:
            if section.kind not in CHECKED_KINDS:
                continue
            resolved, why = self._resolution(section, ext)
            if spelling:
                for entry in section.entries:
                    if entry.key != SCRIPT_PROP:
                        self._spell(lines, section, entry, resolved, why,
                                    script_refs, census, analysis)
            if order:
                self._order(section, resolved, why, census, analysis)
        return analysis

    # --- evidence -------------------------------------------------------------
    def _resolution(self, section: Section,
                    ext: dict[str, dict]) -> tuple[Resolution | None, str | None]:
        script_rel = script_path(section, ext)
        if script_rel is None:
            return None, NO_SCRIPT
        if not self.scripts.has(script_rel):
            return None, SCRIPT_UNREADABLE
        resolved = self.scripts.resolve(script_rel)
        if resolved.opaque:
            return None, SCRIPT_OPAQUE
        return resolved, None

    @staticmethod
    def _script_refs(sections: list[Section]) -> dict[str, list[str]]:
        """`{script res:// path: [ext_resource ids]}` — how an element type is spelled."""
        refs: dict[str, list[str]] = {}
        for section in sections:
            if (section.kind == EXT_RESOURCE_KIND and section.attrs.get('type') == SCRIPT_TYPE
                    and 'id' in section.attrs and 'path' in section.attrs):
                refs.setdefault(section.attrs['path'], []).append(section.attrs['id'])
        return refs

    def _element_spelling(self, element_type: str,
                          script_refs: dict[str, list[str]]) -> tuple[str | None, bool, str]:
        """-> (how the saver spells `Array[T]`'s T, is it an object type, why not)."""
        if element_type in SCALAR_ELEMENTS or element_type in COMPONENT_CTORS \
                or element_type in INT_CTORS:
            return element_type, False, ''
        script = self.scripts.by_class.get(element_type)
        if script is not None:
            ids = script_refs.get(script, [])
            if len(ids) == 1:
                return EXT_REF.format(id=ids[0]), True, ''
            return None, True, (f'element type {element_type} is a script the file '
                                f'{"has no" if not ids else "has several"} ext_resource '
                                f'for — the saver would mint or choose one')
        if classdb.is_known(element_type):
            return element_type, True, ''
        return None, False, (f'element type {element_type} is not knowable by parse '
                             f'(an enum, an inner class or an addon class)')

    # --- spelling -------------------------------------------------------------
    def _spell(self, lines: list[str], section: Section, entry: Prop,
               resolved: Resolution | None, why: str | None,
               script_refs: dict[str, list[str]], census: Counter,
               analysis: Analysis) -> None:
        where = label(section)
        raw = list(lines[entry.start:entry.end])
        text = '\n'.join(raw)
        start = raw[0].index(ASSIGN) + 1
        try:
            tokens, _ = scan_value(text, start)
        except ValueSyntaxError:
            census[OUTSIDE_GRAMMAR] += 1
            return
        decl = resolved.declarations.get(entry.key) if resolved is not None else None
        if decl is not None and decl.has_accessor:
            suspects = [t.text for t in tokens if t.kind == NUMBER
                        and is_float_text(t.text) and looks_noncanonical(t.text)]
            if suspects:
                analysis.refusals.append(Refusal(where, entry.key, HAS_ACCESSOR))
                census[REFUSED] += 1
            elif any(t.kind == NUMBER for t in tokens):
                census[HAS_ACCESSOR] += 1
            return
        slot = _slot(decl)
        result = respell(tokens, text, slot.scalar, slot.elements)
        if decl is not None:
            unsettled = f'{decl.declared_type or "untyped"} export — precision or type unsettled'
        else:
            unsettled = why if resolved is None else NOT_DECLARED
        reasons = [f'{token} has no provable spelling ({unsettled})' for token in result.refused]
        changes = [f'{text[s:e]} -> {new}' for s, e, new in result.edits]
        edits = list(result.edits)
        if slot.element_type is not None:
            self._wrap(tokens, text, slot.element_type, script_refs, edits, changes, reasons)
        if reasons:
            analysis.refusals.append(Refusal(where, entry.key, '; '.join(reasons)))
            census[REFUSED] += 1
            return
        if result.unverified:
            if decl is not None:
                reason = UNVERIFIED_FLOAT
            else:
                reason = why if resolved is None else NOT_DECLARED
            census[reason] += result.unverified
        if not edits:
            return
        rewritten = apply_edits(text, edits).split('\n')
        if len(rewritten) != len(raw):             # an edit never adds a line
            census[OUTSIDE_GRAMMAR] += 1
            return
        analysis.rewrites.append(Rewrite(section, entry, where, rewritten, changes))

    def _wrap(self, tokens: list[Token], text: str, element_type: str,
              script_refs: dict[str, list[str]], edits: list, changes: list[str],
              reasons: list[str]) -> None:
        """Wrap a bare list on an `Array[T]` export the way the saver writes it."""
        span = bare_list(tokens)
        existing = None if span is not None else typed_array(tokens, text)
        if span is None and existing is None:
            return                                  # not a list at all: not ours
        spelling, is_object, why = self._element_spelling(element_type, script_refs)
        if spelling is None:
            reasons.append(why)
            return
        if existing is not None:
            if existing != spelling:
                reasons.append(f'typed Array[{existing}], but the saver writes '
                               f'Array[{spelling}] — retyping is not a respell')
            return
        items = split_items(tokens, *span)
        misfits = [text[item[0].start:item[-1].end] for item in items
                   if not _element_fits(element_type, is_object, item)]
        if misfits:
            reasons.append(f'element(s) {", ".join(misfits)} are not in the form the '
                           f'saver writes for {element_type} — conversion is not a respell')
            return
        opening = WRAP_OPEN.format(element=spelling)
        edits.append((tokens[0].start, tokens[0].start, opening))
        edits.append((tokens[-1].end, tokens[-1].end, WRAP_CLOSE))
        changes.append(f'wrap {opening}...{WRAP_CLOSE}')

    # --- order ----------------------------------------------------------------
    def _order(self, section: Section, resolved: Resolution | None, why: str | None,
               census: Counter, analysis: Analysis) -> None:
        entries = section.entries
        if len(entries) < 2:
            return
        if resolved is None:
            census[f'order: {why}'] += 1
            return
        keys = [entry.key for entry in entries]
        if len(set(keys)) != len(keys):
            census[ORDER_DUPLICATE] += 1
            return
        rank = {name: position for position, name in enumerate(resolved.declarations)}
        if any(key != SCRIPT_PROP and key not in rank for key in keys):
            census[ORDER_UNKNOWABLE] += 1
            return
        ordered = sorted(entries, key=lambda entry: -1 if entry.key == SCRIPT_PROP
                         else rank[entry.key])
        if [e.key for e in ordered] == keys:
            return
        body = section.body_end - (section.header_line + 1)
        if sum(entry.end - entry.start for entry in entries) != body:
            analysis.refusals.append(Refusal(label(section), '', ORDER_INTERLEAVED))
            census[ORDER_INTERLEAVED] += 1
            return
        moved = [(entry, ordered.index(entry) + 1)
                 for position, entry in enumerate(entries) if ordered[position] is not entry]
        analysis.reorders.append(Reorder(section, label(section), ordered, moved))
