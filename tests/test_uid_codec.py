"""index/uid_codec — the ResourceUID port, proven against the real world.

A codec proven only against itself proves nothing: every assertion here is
anchored outside the module. The golden pair was adjudicated by the ENGINE — a
sandboxed Godot run recorded that `uid://wkcycles00001` round-trips to
`uid://c8bmebsj60m77`, a pair that also exercises the uint64 overflow wrap
since 'w' leads a 13-char payload past 2^63. That verdict is VENDORED here as
two constants rather than re-derived, because this package never boots the
engine. The alias clauses ('z', '9', a leading 'a') are pinned by one vector
each, because a corpus does not carry them: real files hold what the engine
emitted, and the engine emits none of the three — measured: dropping '9' from
the rule left every corpus uid and the whole encoder id space agreeing. Corpus
scale is the corpus's job (test_check_uid.py's fixtures carry two real
non-canonical spellings), never a path outside this checkout (rule 8).
"""
from __future__ import annotations

import unittest

from godot_devkit.godot.index.uid_codec import (INVALID_ID, INVALID_TEXT,
                                                UID_PREFIX, canonical,
                                                id_to_text, text_to_id)

# The engine's constants, restated independently of the module under test.
BASE = 34
ID_BITS = 63
# Adjudicated by a real sandboxed Godot run, recorded as a constant: it is the
# outside anchor for everything below, and this package boots no engine.
ENGINE_NONCANONICAL = 'uid://wkcycles00001'
ENGINE_CANONICAL = 'uid://c8bmebsj60m77'
# (spelling, its canonical form) — one row per CLAUSE of the predicate.
CANONICAL_FORMS = (
    (ENGINE_NONCANONICAL, ENGINE_CANONICAL),   # 13 chars led by 'w': wraps
    (ENGINE_CANONICAL, ENGINE_CANONICAL),
    ('uid://z', 'uid://0'),                    # 'z' is an alias of 0, never emitted
    ('uid://9', 'uid://ba'),                   # '9' decodes to the base and carries
    ('uid://ab', 'uid://b'),                   # a LEADING 'a' is a leading zero...
    ('uid://ba', 'uid://ba'),                  # ...an INTERIOR 'a' is a digit
    ('uid://22otqvw07khz', 'uid://22otqvw07kh0'),   # real, corpus-held: trailing 'z'
)
# Real, corpus-held, 19 chars: overflows 63 bits on width alone. Its canonical
# spelling has no outside anchor, so only the verdict and its stability are
# pinned — a repair target that is not itself stable makes `--fix` churn.
REAL_OVERFLOW = 'uid://b0g4m1trscaffold00'


class CanonicalForm(unittest.TestCase):
    def test_every_spelling_has_the_engines_canonical_twin(self) -> None:
        # Each pair decodes to ONE id, canonicalizes as the engine does, and
        # the repair target is itself stable — or `check uid --fix` churns.
        self.assertEqual(text_to_id('uid://9'), BASE)
        for spelt, canon in CANONICAL_FORMS:
            with self.subTest(spelt):
                self.assertEqual(text_to_id(spelt), text_to_id(canon))
                self.assertEqual(canonical(spelt), canon)
                self.assertEqual(canonical(canon), canon)
        overflow = canonical(REAL_OVERFLOW)
        self.assertNotEqual(overflow, REAL_OVERFLOW)
        self.assertEqual(canonical(overflow), overflow)


class Invalids(unittest.TestCase):
    def test_undecodable_texts_have_no_canonical_form(self) -> None:
        for text in ('res://x.gd', 'uid://<invalid>', 'uid://UPPER',
                     'uid://has_underscore', 'uid://spaced out', 'plain'):
            with self.subTest(text):
                self.assertEqual(text_to_id(text), INVALID_ID)
                self.assertIsNone(canonical(text))
        self.assertEqual(id_to_text(INVALID_ID), INVALID_TEXT)


class EncoderProperties(unittest.TestCase):
    # Dense low range + every base-power boundary + the id-space ceiling.
    IDS = (list(range(0, 3000))
           + [BASE ** k + delta for k in range(1, 13) for delta in (-1, 0, 1)]
           + [(1 << ID_BITS) - 1])

    def test_encode_decode_is_identity_and_never_emits_an_alias(self) -> None:
        for uid in self.IDS:
            body = id_to_text(uid)[len(UID_PREFIX):]
            self.assertEqual(text_to_id(UID_PREFIX + body), uid)
            self.assertNotIn('z', body)
            self.assertNotIn('9', body)
            self.assertNotEqual(body[:1], 'a')
