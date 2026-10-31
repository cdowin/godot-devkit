"""value_order.py — the ORDER Godot's text saver gives the items inside one value.

Two facts, measured on a Godot 4.7.2 editor save and pinned by the pairs under
`tests/fixtures/editor_parity/`:

* **Dictionary keys are written sorted.** Ints first, by value; then String
  and StringName keys together, by code point (`"10" < "9" < "B" < "_u" <
  &"a2" < "a3"`). Every dictionary, at every depth. A key of any other kind,
  StringName keys beside int keys, a duplicate key, or items that are not
  separated the same way is REFUSED: the order is not proven for it, or
  permuting it would reflow text.
* **SpriteFrames `animations` is rebuilt by the engine on save:** the array is
  sorted by each animation's `name` (code point), `"loop"` is written as an
  int (`true` -> `1`), and it is laid out the way the saver writes every
  value: a dictionary one key per line, an array inline.

A dictionary sort is a PERMUTATION of item texts that share one separator, so
the value keeps its length in lines and every item keeps its own bytes. The
`animations` rebuild alone re-lays the value out, and may change its line count.
"""
from __future__ import annotations

from godot_devkit.godot.format.value_spelling import (
    DICT_OPEN,
    ESCAPE,
    IDENT,
    LIST_OPEN,
    NUMBER,
    PUNCT,
    STRING,
    INT_TEXT_RE,
    Token,
    ValueSyntaxError,
    apply_edits,
    matching,
    scan_value,
    split_items,
)

KEY_COLON = ':'
STRING_NAME_PREFIX = '&'
INT_KEY = 0
STRING_KEY = 1
STRING_NAME_KEY = 2
LOOP_KEY = '"loop"'
NAME_KEY = '"name"'
BOOL_INTS = {'true': '1', 'false': '0'}


class OrderRefusal(ValueError):
    """The saver would reorder this value, but the tool cannot prove how."""


def _separators(text: str, items: list[list[Token]]) -> list[str]:
    """The exact text between consecutive items (comma and whitespace)."""
    return [text[items[i][-1].end:items[i + 1][0].start] for i in range(len(items) - 1)]


def _permute(text: str, items: list[list[Token]], order: list[int]) -> tuple[int, int, str]:
    """-> one edit that writes `items` in `order`, separators kept in place."""
    seps = _separators(text, items)
    if len(set(seps)) > 1:
        raise OrderRefusal('items are not separated the same way — reordering would reflow text')
    bodies = [text[item[0].start:item[-1].end] for item in items]
    sep = seps[0] if seps else ''
    return items[0][0].start, items[-1][-1].end, sep.join(bodies[i] for i in order)


def _key(item: list[Token]) -> tuple[int, object]:
    colon = next((i for i, t in enumerate(item) if t.kind == PUNCT and t.text == KEY_COLON), None)
    if colon is None:
        raise OrderRefusal('dictionary item without a key')
    key = item[:colon]
    if len(key) == 1 and key[0].kind == STRING and ESCAPE not in key[0].text:
        return STRING_KEY, key[0].text[1:-1]
    if (len(key) == 2 and key[0].kind == PUNCT and key[0].text == STRING_NAME_PREFIX
            and key[1].kind == STRING and ESCAPE not in key[1].text):
        return STRING_NAME_KEY, key[1].text[1:-1]
    if len(key) == 1 and key[0].kind == NUMBER and INT_TEXT_RE.match(key[0].text):
        return INT_KEY, int(key[0].text)
    raise OrderRefusal(f'dictionary key {" ".join(t.text for t in key)} is not a string or an '
                       f'int — its sort position is not proven')


def _dict_order(items: list[list[Token]]) -> list[int]:
    keys = [_key(item) for item in items]
    kinds = {kind for kind, _ in keys}
    if STRING_NAME_KEY in kinds and INT_KEY in kinds:
        raise OrderRefusal('dictionary mixes StringName and int keys — their relative order '
                           'is not proven')
    rank = {INT_KEY: 0, STRING_KEY: 1, STRING_NAME_KEY: 1}
    ranked = [(rank[kind], value) for kind, value in keys]
    if len(set(ranked)) != len(ranked):
        raise OrderRefusal('dictionary repeats a key (or a String and a StringName spell one key)')
    return sorted(range(len(items)), key=lambda i: ranked[i])


def _scan(text: str, start: int) -> list[Token]:
    try:
        return scan_value(text, start)[0]
    except ValueSyntaxError as err:
        raise OrderRefusal(f'value outside the grammar the reorder reads ({err})') from err


def sort_dicts(text: str, start: int) -> tuple[str, int]:
    """-> (text with every dictionary's keys in saver order, dictionaries reordered).

    Rightmost-first: a permutation keeps its span, so an outer dictionary's
    braces never move while its inner ones are sorted.
    """
    opens = [t.start for t in _scan(text, start) if t.kind == PUNCT and t.text == DICT_OPEN]
    changed = 0
    for offset in sorted(opens, reverse=True):
        tokens = _scan(text, start)
        index = next(i for i, t in enumerate(tokens) if t.start == offset)
        items = split_items(tokens, index, matching(tokens, index))
        if len(items) < 2:
            continue
        order = _dict_order(items)
        if order == list(range(len(items))):
            continue
        text = apply_edits(text, [_permute(text, items, order)])
        changed += 1
    return text, changed


def _field(text: str, item: list[Token], name: str) -> list[Token] | None:
    """The value tokens of `name: value` directly inside one dictionary item."""
    if not (item and item[0].text == DICT_OPEN):
        return None
    for entry in split_items(item, 0, len(item) - 1):
        if entry and entry[0].kind == STRING and entry[0].text == name:
            return entry[2:]
    return None


def _laid_out(text: str, item: list[Token]) -> str:
    """One value as the saver lays it out: a dictionary one key per line, an
    array inline with `, ` between items, anything else as written."""
    head, last = item[0], len(item) - 1
    if head.kind == PUNCT and head.text in (DICT_OPEN, LIST_OPEN) and matching(item, 0) == last:
        entries = split_items(item, 0, last)
        if head.text == LIST_OPEN:
            return LIST_OPEN + ', '.join(_laid_out(text, e) for e in entries) + ']'
        if not entries:
            return '{}'
        pairs = []
        for entry in entries:
            colon = next((i for i, t in enumerate(entry)
                          if t.kind == PUNCT and t.text == KEY_COLON), None)
            if colon is None or colon == 0 or colon == len(entry) - 1:
                raise OrderRefusal('dictionary item without a key')
            key = text[entry[0].start:entry[colon - 1].end]
            pairs.append(f'{key}: {_laid_out(text, entry[colon + 1:])}')
        return '{\n' + ',\n'.join(pairs) + '\n}'
    if any(t.kind == PUNCT and t.text in (DICT_OPEN, LIST_OPEN) for t in item):
        raise OrderRefusal('a container inside a call — its layout is not measured')
    raw = text[head.start:item[-1].end]
    if '\n' in raw:
        raise OrderRefusal('a value broken across lines — its layout is not measured')
    return raw


def rebuild_animations(text: str, start: int) -> tuple[str, list[str]]:
    """-> (SpriteFrames `animations` as the engine writes it, what changed)."""
    tokens = _scan(text, start)
    if not tokens or tokens[0].text != LIST_OPEN or matching(tokens, 0) != len(tokens) - 1:
        raise OrderRefusal('animations is not one array literal')
    items = split_items(tokens, 0, len(tokens) - 1)
    edits, names = [], []
    for item in items:
        name = _field(text, item, NAME_KEY)
        if not (name and len(name) == 2 and name[0].text == STRING_NAME_PREFIX
                and name[1].kind == STRING and ESCAPE not in name[1].text):
            raise OrderRefusal('an animation has no &"name" — its sort position is not proven')
        names.append(name[1].text[1:-1])
        loop = _field(text, item, LOOP_KEY)
        if loop and len(loop) == 1 and loop[0].kind == IDENT and loop[0].text in BOOL_INTS:
            edits.append((loop[0].start, loop[0].end, BOOL_INTS[loop[0].text]))
    if len(set(names)) != len(names):
        raise OrderRefusal('two animations share a name')
    changes = [f'"loop": {text[s:e]} -> {new}' for s, e, new in edits]
    order = sorted(range(len(items)), key=lambda i: names[i])
    if order != list(range(len(items))):
        changes.append('animations sorted by name')
    text = apply_edits(text, edits)
    tokens = _scan(text, start)
    items = split_items(tokens, 0, len(tokens) - 1)
    body = LIST_OPEN + ', '.join(_laid_out(text, items[i]) for i in order) + ']'
    laid = text[:tokens[0].start] + body + text[tokens[-1].end:]
    if laid.count('\n') != text.count('\n'):
        changes.append('one key per line')
    return laid, changes


def animations_in_engine_order(text: str, start: int) -> str:
    """`animations`' items joined in the order the engine walks them: by name."""
    tokens = _scan(text, start)
    if not tokens or tokens[0].text != LIST_OPEN or matching(tokens, 0) != len(tokens) - 1:
        raise OrderRefusal('animations is not one array literal')
    items = split_items(tokens, 0, len(tokens) - 1)
    names = []
    for item in items:
        name = _field(text, item, NAME_KEY)
        if not (name and len(name) == 2 and name[1].kind == STRING):
            raise OrderRefusal('an animation has no &"name" — its sort position is not proven')
        names.append(name[1].text[1:-1])
    order = sorted(range(len(items)), key=lambda i: names[i])
    return ' '.join(text[items[i][0].start:items[i][-1].end] for i in order)
