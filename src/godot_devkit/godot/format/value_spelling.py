"""value_spelling.py — how Godot's text saver SPELLS a value, as far as a parse can prove it.

An editor save of a `.tres` re-spells values it did not change. This module
knows the float half of that, and the token grammar the typed-array half needs;
which property a value belongs to, and so what TYPE it holds, is the caller's
(`index/resource_canonical.py`), because only a script can say.

**Floats.** The saver writes the shortest decimal that reads back as the same
number: `0.30` is written `0.3`, `12.50` is `12.5`. Two styles, both visible in
the editor-written half of the committed corpus:

  * a FLOAT Variant — a bare `float` property, an element of an untyped Array or
    Dictionary — keeps a `.0` on an integral value: `anchor_right = 1.0`,
    `"values": [0.0, 6.2831855]`;
  * a real_t COMPONENT — inside `Vector2(...)`, `Color(...)`,
    `PackedFloat32Array(...)` and the other math constructors — does not:
    `Color(0.561, 0.89, 1, 1)`, `PackedFloat32Array(0, 0.08, 0.25)`.

**Precision is the trap, and it is refused rather than guessed.** A real_t is
32-bit in a stock build and 64-bit in a double-precision one, and the corpus
shows the saver writing a 32-bit value at 32-bit precision (`6.2831855`, TAU as
a float). A spelling is therefore only ever EMITTED when the 32-bit and the
64-bit shortest forms agree — true of every value a person types (`0.3`,
`1.25`, `0.561`), false of `0.123456789`, whose respelling depends on a build
this parse cannot see. Those, and any magnitude outside the plain positional
range (the saver switches to exponent notation somewhere past it), come back
`None`: not provable, so never written.

Nothing here reads a file or knows a property; `respell()` takes the context
each position is in and returns edits, never a re-serialised value, so every
byte it was not asked about survives.
"""
from __future__ import annotations

import math
import re
import struct
from dataclasses import dataclass

# --- the token grammar of one value ----------------------------------------
IDENT_RE = re.compile(r'[A-Za-z_]\w*')
NUMBER_RE = re.compile(r'-?(?:\d+\.\d*|\.\d+|\d+)(?:[eE][-+]?\d+)?')
INT_TEXT_RE = re.compile(r'^-?\d+$')
NUMBER_START = '0123456789-.'
IDENT_TAIL = re.compile(r'[\w.]')
WHITESPACE = ' \t\r\n'
QUOTE = '"'
ESCAPE = '\\'
COMMENT_CHAR = ';'
OPENERS = '([{'
CLOSERS = ')]}'
PAIRS = {'(': ')', '[': ']', '{': '}'}
LIST_OPEN = '['
CALL_OPEN = '('
DICT_OPEN = '{'
SEPARATOR = ','

IDENT = 'ident'
NUMBER = 'number'
STRING = 'string'
PUNCT = 'punct'

# --- contexts: what a number at a given position IS --------------------------
FLOAT_CONTEXT = 'float'          # a FLOAT slot: `.0` style, and an int is coerced
VARIANT_CONTEXT = 'variant'      # a Variant slot: `.0` style, an int stays an int
COMPONENT_CONTEXT = 'component'  # a real_t component: no `.0`
OPAQUE_CONTEXT = None            # type unknown: nothing is provable

# The constructors whose every numeric argument is a real_t (or a float
# channel), written by the saver without a `.0`. The `i` vectors, the other
# packed arrays and anything unknown are OPAQUE: their numbers are not ours.
COMPONENT_CTORS = frozenset((
    'Vector2', 'Vector3', 'Vector4', 'Rect2', 'Color', 'Quaternion', 'Plane',
    'Transform2D', 'Transform3D', 'Basis', 'AABB', 'Projection',
    'PackedFloat32Array', 'PackedVector2Array', 'PackedVector3Array',
    'PackedVector4Array', 'PackedColorArray',
))
TYPED_ARRAY = 'Array'
TYPED_CONTAINERS = frozenset((TYPED_ARRAY, 'Dictionary'))
FLOAT_TYPE = 'float'

# The plain positional range: inside it both the 32- and 64-bit writers print
# digits and a point, outside it the saver's exponent spelling is not proven.
# One decade inside `%g`'s own [1e-4, 1e6) at each end: a shortest-form writer
# may already spell 1e-04 or 1e+05 in exponent form, so the edge decades are
# unprovable, and an exponent-spelled token is never ours to respell.
POSITIONAL_MIN = 1e-3
POSITIONAL_MAX = 1e5
EXPONENT_MARKS = ('e', 'E')
FLOAT32_MAX_DIGITS = 9           # every float32 round-trips in 9 significant digits
FLOAT32 = struct.Struct('<f')
INTEGRAL_SUFFIX = '.0'
ZERO_COMPONENT = '0'
ZERO_VARIANT = '0.0'
EXACT_INT_LIMIT = 2 ** 53


@dataclass(frozen=True)
class Token:
    kind: str
    text: str
    start: int                   # offsets into the text handed to `scan_value`
    end: int


class ValueSyntaxError(ValueError):
    """The value is outside the grammar this module can respell safely."""


def scan_value(text: str, start: int) -> tuple[list[Token], int]:
    """Tokenize one value from `start`; -> (tokens, offset where the value ends).

    The value ends at a top-level `;` comment or at the end of `text` — the
    same rule the `.tres` parser uses, so a `;` inside a string or a bracket
    is data. Raises `ValueSyntaxError` on a spelling it cannot classify (an
    unterminated string, `0x1F`, unbalanced brackets): a value this cannot
    read is a value it must not touch.
    """
    tokens: list[Token] = []
    depth = 0
    index = start
    while index < len(text):
        char = text[index]
        if char in WHITESPACE:
            index += 1
            continue
        if char == COMMENT_CHAR and depth <= 0:
            break
        if char == QUOTE:
            end = _string_end(text, index)
            tokens.append(Token(STRING, text[index:end], index, end))
            index = end
            continue
        ident = IDENT_RE.match(text, index)
        if ident:
            tokens.append(Token(IDENT, ident.group(0), index, ident.end()))
            index = ident.end()
            continue
        number = NUMBER_RE.match(text, index) if char in NUMBER_START else None
        if number and any(c.isdigit() for c in number.group(0)):
            end = number.end()
            if end < len(text) and IDENT_TAIL.match(text[end]):
                raise ValueSyntaxError(f'unrecognised number spelling at {text[index:end + 1]!r}')
            tokens.append(Token(NUMBER, number.group(0), index, end))
            index = end
            continue
        if char in OPENERS:
            depth += 1
        elif char in CLOSERS:
            depth -= 1
            if depth < 0:
                raise ValueSyntaxError('unbalanced brackets')
        tokens.append(Token(PUNCT, char, index, index + 1))
        index += 1
    if depth != 0:
        raise ValueSyntaxError('unbalanced brackets')
    return tokens, index


def _string_end(text: str, start: int) -> int:
    escaped = False
    for index in range(start + 1, len(text)):
        char = text[index]
        if escaped:
            escaped = False
        elif char == ESCAPE:
            escaped = True
        elif char == QUOTE:
            return index + 1
    raise ValueSyntaxError('unterminated string')


def matching(tokens: list[Token], open_index: int) -> int:
    """Index of the token closing the bracket at `open_index`."""
    depth = 0
    for index in range(open_index, len(tokens)):
        token = tokens[index]
        if token.kind != PUNCT:
            continue
        if token.text in OPENERS:
            depth += 1
        elif token.text in CLOSERS:
            depth -= 1
            if depth == 0:
                if token.text != PAIRS[tokens[open_index].text]:
                    raise ValueSyntaxError('mismatched brackets')
                return index
    raise ValueSyntaxError('unbalanced brackets')


def split_items(tokens: list[Token], open_index: int, close_index: int) -> list[list[Token]]:
    """The comma-separated items directly inside one bracket pair."""
    items: list[list[Token]] = []
    current: list[Token] = []
    depth = 0
    for token in tokens[open_index + 1:close_index]:
        if token.kind == PUNCT and token.text in OPENERS:
            depth += 1
        elif token.kind == PUNCT and token.text in CLOSERS:
            depth -= 1
        if depth == 0 and token.kind == PUNCT and token.text == SEPARATOR:
            items.append(current)
            current = []
            continue
        current.append(token)
    if current:
        items.append(current)
    return items


def bare_list(tokens: list[Token]) -> tuple[int, int] | None:
    """(open, close) when the whole value is ONE `[...]` list, else None."""
    if not tokens or tokens[0].kind != PUNCT or tokens[0].text != LIST_OPEN:
        return None
    close = matching(tokens, 0)
    return (0, close) if close == len(tokens) - 1 else None


def typed_array(tokens: list[Token], source: str) -> str | None:
    """The element-type spelling when the value is `Array[T]([...])`, else None."""
    if len(tokens) < 2 or tokens[0].text != TYPED_ARRAY or tokens[1].text != LIST_OPEN:
        return None
    close = matching(tokens, 1)
    call = close + 1
    if call >= len(tokens) or tokens[call].text != CALL_OPEN \
            or matching(tokens, call) != len(tokens) - 1:
        return None
    return source[tokens[1].end:tokens[close].start].strip()


# --- floats -----------------------------------------------------------------
def _float32(value: float) -> float:
    return FLOAT32.unpack(FLOAT32.pack(value))[0]


def _shortest_float32(value: float) -> str | None:
    """The shortest decimal that reads back as the same float32 as `value`."""
    single = _float32(value)
    for digits in range(1, FLOAT32_MAX_DIGITS + 1):
        candidate = float(f'{single:.{digits - 1}e}')
        if _float32(candidate) == single:
            return repr(candidate)
    return None


def canonical_float(value: float, style: str) -> str | None:
    """The saver's spelling of `value` in `style`, or None when not provable."""
    if not math.isfinite(value):
        return None
    if value == 0.0:                               # -0.0 too: the saver writes "0"
        return ZERO_COMPONENT if style == COMPONENT_CONTEXT else ZERO_VARIANT
    if not POSITIONAL_MIN <= abs(value) < POSITIONAL_MAX:
        return None
    double = repr(value)
    if _shortest_float32(value) != double:
        return None                                # precision-dependent: refuse
    if style == COMPONENT_CONTEXT and double.endswith(INTEGRAL_SUFFIX):
        return double[:-len(INTEGRAL_SUFFIX)]
    return double


def looks_noncanonical(text: str) -> bool:
    """True when no style of the saver could have written this float token.

    What turns a position the tool cannot prove into a NAMED refusal instead
    of silence: `0.30` is wrong whatever its type, `0.123456789` may be right.
    """
    if any(mark in text for mark in EXPONENT_MARKS):
        return False
    value = float(text)
    if not math.isfinite(value):
        return False
    if value == 0.0:
        return text not in (ZERO_COMPONENT, ZERO_VARIANT)
    if not POSITIONAL_MIN <= abs(value) < POSITIONAL_MAX:
        return False
    double = repr(value)
    component = double[:-len(INTEGRAL_SUFFIX)] if double.endswith(INTEGRAL_SUFFIX) else double
    return text not in (double, component)


def is_float_text(text: str) -> bool:
    return not INT_TEXT_RE.match(text)


# --- the respell walk -------------------------------------------------------
@dataclass
class Respelling:
    edits: list[tuple[int, int, str]]    # (start, end, replacement), ascending
    refused: list[str]                   # tokens no saver writes, that it cannot fix
    unverified: int = 0                  # floats that may be right; unprovable


@dataclass(frozen=True)
class _TypedCall:
    """The `(...)` of `Array[T](...)`: its one list's elements are `element`."""
    element: str | None


_TOP = 'top'


def _opens(tokens: list[Token], index: int) -> bool:
    """Does the token at `index` open a container (a call, a list, a dict)?"""
    token = tokens[index]
    if token.kind == PUNCT:
        return token.text in OPENERS
    following = tokens[index + 1].text if index + 1 < len(tokens) else ''
    return token.kind == IDENT and (
        following == CALL_OPEN
        or (following == LIST_OPEN and token.text in TYPED_CONTAINERS))


def _child_context(tokens: list[Token], index: int, source: str,
                   parent: object, elements: str | None) -> tuple[object, int]:
    """The context for what sits directly inside the container opened at `index`.

    -> (context, index of the next token to read). A constructor fixes its own
    arguments' type whatever surrounds it; a list or dictionary inherits a
    Variant context and nothing else — inside anything typed, it is OPAQUE.
    """
    token = tokens[index]
    if token.kind == IDENT:
        if tokens[index + 1].text == LIST_OPEN:           # Array[T]( / Dictionary[K, V](
            close = matching(tokens, index + 1)
            if close + 1 >= len(tokens) or tokens[close + 1].text != CALL_OPEN:
                raise ValueSyntaxError(f'{token.text}[...] with no constructor call')
            element = source[tokens[index + 1].end:tokens[close].start].strip()
            floats = token.text == TYPED_ARRAY and element == FLOAT_TYPE
            return _TypedCall(FLOAT_CONTEXT if floats else OPAQUE_CONTEXT), close + 2
        own = COMPONENT_CONTEXT if token.text in COMPONENT_CTORS else OPAQUE_CONTEXT
        return own, index + 2
    if token.text == CALL_OPEN:
        return OPAQUE_CONTEXT, index + 1
    if isinstance(parent, _TypedCall):
        return (parent.element if token.text == LIST_OPEN else OPAQUE_CONTEXT), index + 1
    if parent == VARIANT_CONTEXT:
        return VARIANT_CONTEXT, index + 1
    if parent == _TOP:
        if token.text == LIST_OPEN:
            return elements, index + 1
        return (VARIANT_CONTEXT if elements == VARIANT_CONTEXT else OPAQUE_CONTEXT), index + 1
    return OPAQUE_CONTEXT, index + 1


def respell(tokens: list[Token], source: str, scalar: str | None,
            elements: str | None) -> Respelling:
    """Every float the saver would spell differently, as edits into `source`.

    `scalar` is the context of a number at the top of the value (a bare
    `x = 0.30`), `elements` the context of what sits inside a top-level list
    or dictionary; both come from the property's declared type, and either
    may be OPAQUE. Constructors decide for themselves.
    """
    result = Respelling([], [])
    stack: list[object] = []
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if _opens(tokens, index):
            parent = stack[-1] if stack else _TOP
            context, index = _child_context(tokens, index, source, parent, elements)
            stack.append(context)
            continue
        if token.kind == PUNCT and token.text in CLOSERS:
            stack.pop()
        elif token.kind == NUMBER:
            context = stack[-1] if stack else scalar
            wanted = _wanted(token.text, context)
            if wanted is None:
                # Unprovable. Named when no saver could have written it this
                # way (`0.30`), merely counted when it may be right as it is.
                if not is_float_text(token.text) or looks_noncanonical(token.text):
                    result.refused.append(token.text)
                else:
                    result.unverified += 1
            elif wanted != token.text:
                result.edits.append((token.start, token.end, wanted))
        index += 1
    return result


def _wanted(text: str, context: object) -> str | None:
    """The saver's spelling of one number token in `context`; None if unprovable.

    An int is the token's own spelling everywhere but a FLOAT slot, where the
    saver stores — and so writes — the coerced float (`1` -> `1.0`).
    """
    if not is_float_text(text):
        if context != FLOAT_CONTEXT:
            return text
        whole = int(text)
        return (canonical_float(float(whole), VARIANT_CONTEXT)
                if abs(whole) < EXACT_INT_LIMIT else None)
    if context not in (FLOAT_CONTEXT, VARIANT_CONTEXT, COMPONENT_CONTEXT):
        return None
    if any(mark in text for mark in EXPONENT_MARKS):
        return None
    style = COMPONENT_CONTEXT if context == COMPONENT_CONTEXT else VARIANT_CONTEXT
    return canonical_float(float(text), style)


def apply_edits(text: str, edits: list[tuple[int, int, str]]) -> str:
    """`text` with each (start, end, replacement) applied; edits must not overlap."""
    for start, end, replacement in sorted(edits, reverse=True):
        text = text[:start] + replacement + text[end:]
    return text
