"""uid_codec.py — Godot's ResourceUID text codec, ported bit for bit.

Godot 4 encodes a resource uid (a non-negative 63-bit integer) as `uid://`
plus a base-34 string. The engine's constants are off by one — char_count is
('z' - 'a') = 25 and base is char_count + ('9' - '0') = 34 — so the ENCODER
never emits 'z' or '9' (or a leading 'a'), while the DECODER accepts the full
[a-z0-9] range and wraps any overflow through uint64 before masking to 63
bits. GH-97516 froze that asymmetry for compatibility, and the asymmetry is
why this module exists: many text spellings decode to one id, exactly one of
them is what `ResourceUID::id_to_text` produces, and Godot rewrites every
other spelling on the next editor save — permanent diff churn that no regex
can detect, because `uid://wkcycles00001` and `uid://c8bmebsj60m77` share
length and charset yet decode to the same id.

`text_to_id` / `id_to_text` mirror ResourceUID::text_to_id / id_to_text
exactly (including the uint64 overflow wrap and the 63-bit mask); `canonical`
is the round trip `check uid` judges spellings by. Ported so canonicality is
a pure-parse verdict — nullbound's resource_uid_scan.sh booted a sandboxed
Godot for exactly this, and this package never boots the engine.
"""
from __future__ import annotations

UID_PREFIX = 'uid://'
INVALID_TEXT = f'{UID_PREFIX}<invalid>'
INVALID_ID = -1

_A, _Z, _ZERO, _NINE = ord('a'), ord('z'), ord('0'), ord('9')
_CHAR_COUNT = _Z - _A                       # 25, not 26 — the engine's off-by-one
_BASE = _CHAR_COUNT + (_NINE - _ZERO)       # 34, not 36 — likewise
_ID_MASK = (1 << 63) - 1                    # ids are non-negative int64


def text_to_id(text: str) -> int:
    """ResourceUID::text_to_id — INVALID_ID for anything undecodable.

    Faithful to the engine, which means permissive: 'z', '9' and leading 'a'
    all decode (to values the encoder spells differently), and a payload too
    large for 63 bits wraps rather than failing. Only a missing prefix, the
    literal invalid form, or a character outside [a-z0-9] is INVALID_ID.
    """
    if not text.startswith(UID_PREFIX) or text == INVALID_TEXT:
        return INVALID_ID
    uid = 0
    for char in text[len(UID_PREFIX):]:
        point = ord(char)
        if _A <= point <= _Z:
            uid = uid * _BASE + (point - _A)
        elif _ZERO <= point <= _NINE:
            uid = uid * _BASE + (point - _ZERO + _CHAR_COUNT)
        else:
            return INVALID_ID
    # The engine accumulates in uint64 (wrapping) and masks to 63 bits at the
    # end. Because 2**63 divides 2**64, masking the unbounded Python int once
    # is arithmetic-identical to wrapping every intermediate step.
    return uid & _ID_MASK


def id_to_text(uid: int) -> str:
    """ResourceUID::id_to_text — the ONE spelling the engine will not rewrite."""
    if uid < 0:
        return INVALID_TEXT
    text = ''
    while uid:
        digit = uid % _BASE
        text = (chr(_A + digit) if digit < _CHAR_COUNT
                else chr(_ZERO + digit - _CHAR_COUNT)) + text
        uid //= _BASE
    return UID_PREFIX + text


def canonical(text: str) -> str | None:
    """id_to_text(text_to_id(text)) — None when the text does not decode."""
    uid = text_to_id(text)
    return None if uid == INVALID_ID else id_to_text(uid)
