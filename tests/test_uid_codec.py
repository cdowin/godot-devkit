"""index/uid_codec — the ResourceUID port, proven against the real world.

A codec proven only against itself proves nothing: every assertion here is
anchored outside the module. The golden pair was adjudicated by the ENGINE — a
sandboxed Godot run recorded that `uid://wkcycles00001` round-trips to
`uid://c8bmebsj60m77`, a pair that also exercises the uint64 overflow wrap
since 'w' leads a 13-char payload past 2^63. That verdict is VENDORED here as
two constants rather than re-derived, because this package never boots the
engine. The differential sweep runs every uid harvested from the committed
corpus and cross-checks the round-trip verdict against an INDEPENDENT
positional formulation of canonicality — two derivations of the same predicate
that would disagree if either the base, the alphabet split, the leading-zero
rule or the overflow mask were wrong. Corpus scale is the corpus's job: vendor
a scrubbed file carrying a spelling the sweep cannot reach, never a path
outside this checkout (CLAUDE.md rule 8).
"""
from __future__ import annotations

import re
import unittest

from support import FIXTURES

from godot_devkit.godot.index.uid_codec import (INVALID_ID, INVALID_TEXT,
                                                UID_PREFIX, canonical,
                                                id_to_text, text_to_id)

UID_TEXT = re.compile(r'uid://[0-9a-z]+')
CORPUS = FIXTURES / 'corpus'
# The committed corpus carries ~266 distinct uids today; a harvest below the
# floor means the harvest broke, not that the corpus shrank quietly (rule 4).
CORPUS_UID_FLOOR = 200
# Two committed real-world non-canonical spellings the corpus is known to
# hold: uid://22otqvw07khz (the encoder never emits 'z') and
# uid://b0g4m1trscaffold00 (19 chars — overflows 63 bits and wraps).
CORPUS_NONCANONICAL_FLOOR = 2

# The engine's constants, restated independently of the module under test.
BASE = 34
CHAR_COUNT = 25
ID_BITS = 63

# Adjudicated by a real sandboxed Godot run, recorded as a constant: it is the
# outside anchor for everything below, and this package boots no engine.
# (`text_to_id`/`id_to_text` are ports of ResourceUID's; the shell scans that
# asked the engine for this verdict are what the codec supersedes.)
ENGINE_NONCANONICAL = 'uid://wkcycles00001'
ENGINE_CANONICAL = 'uid://c8bmebsj60m77'

# One spelling per CLAUSE of the canonicality predicate, because a corpus does
# not carry them: real files hold what the engine emitted, and the engine emits
# no 'z', no '9' and no leading 'a' — so a sweep over real uids alone reaches
# the alias clauses never, and pins them not at all. Measured: dropping '9'
# from the rule left every corpus uid and the whole encoder id space agreeing.
PREDICATE_VECTORS = (
    'uid://z',                    # 'z' is an alias of 0 and never emitted
    'uid://9',                    # '9' decodes to the base and carries
    'uid://ab',                   # a LEADING 'a' is a leading zero
    'uid://ba',                   # ...an INTERIOR 'a' is a legitimate digit
    'uid://0',                    # the canonical twin of 'z'
    ENGINE_NONCANONICAL,          # 13 chars led by 'w': past 2^63, wraps
    ENGINE_CANONICAL,
    'uid://b0g4m1trscaffold00',   # 19 chars: overflows on width alone
)


HARVEST_SUFFIXES = ('.tscn', '.tres', '.uid', '.import')


def _harvest(root) -> set[str]:
    uids: set[str] = set()
    for path in root.rglob('*'):
        if (not path.is_file() or path.suffix not in HARVEST_SUFFIXES
                or '.git' in path.parts or '.godot' in path.parts):
            continue
        try:
            text = path.read_text(encoding='utf-8', errors='replace')
        except OSError:
            continue
        uids.update(UID_TEXT.findall(text))
    return uids


def _independently_canonical(text: str) -> bool:
    """Positional restatement: alphabet a-y / 0-8, no leading 'a', fits 63
    bits. Shares NO code with the codec's round trip — that is the point."""
    body = text[len(UID_PREFIX):]
    if not body or body[0] == 'a' or any(c in 'z9' for c in body):
        return False
    value = 0
    for char in body:
        value = value * BASE + (
            ord(char) - ord('a') if char.isalpha()
            else ord(char) - ord('0') + CHAR_COUNT)
    return value < (1 << ID_BITS)


class EngineAdjudicated(unittest.TestCase):
    def test_the_golden_pair_decodes_to_one_id(self) -> None:
        self.assertEqual(text_to_id(ENGINE_NONCANONICAL),
                         text_to_id(ENGINE_CANONICAL))
        self.assertNotEqual(text_to_id(ENGINE_CANONICAL), INVALID_ID)

    def test_the_golden_pair_canonicalizes_the_way_the_engine_did(self) -> None:
        # 'w' leads a 13-char payload: the value passes 2^63 and wraps, so
        # this single vector pins the overflow semantics to the engine's.
        self.assertEqual(canonical(ENGINE_NONCANONICAL), ENGINE_CANONICAL)
        self.assertEqual(canonical(ENGINE_CANONICAL), ENGINE_CANONICAL)


class Aliases(unittest.TestCase):
    """The engine's off-by-one leaves 'z', '9' and leading 'a' decodable but
    never emitted — every spelling using them has a different canonical twin."""

    def test_z_is_an_alias_of_zero(self) -> None:
        self.assertEqual(text_to_id('uid://z'), text_to_id('uid://0'))
        self.assertEqual(canonical('uid://z'), 'uid://0')

    def test_nine_decodes_to_the_base_and_carries(self) -> None:
        self.assertEqual(text_to_id('uid://9'), BASE)
        self.assertEqual(canonical('uid://9'), 'uid://ba')

    def test_a_leading_a_is_a_leading_zero(self) -> None:
        self.assertEqual(canonical('uid://ab'), 'uid://b')
        # …but an INTERIOR 'a' is a legitimate digit.
        self.assertEqual(canonical('uid://ba'), 'uid://ba')


class Invalids(unittest.TestCase):
    def test_undecodable_texts(self) -> None:
        for text in ('res://x.gd', 'uid://<invalid>', 'uid://UPPER',
                     'uid://has_underscore', 'uid://spaced out', 'plain'):
            with self.subTest(text):
                self.assertEqual(text_to_id(text), INVALID_ID)
                self.assertIsNone(canonical(text))

    def test_a_negative_id_encodes_as_the_invalid_text(self) -> None:
        self.assertEqual(id_to_text(INVALID_ID), INVALID_TEXT)


class EncoderProperties(unittest.TestCase):
    # Dense low range + every base-power boundary + the id-space ceiling.
    IDS = (list(range(0, 3000))
           + [BASE ** k + delta for k in range(1, 13) for delta in (-1, 0, 1)]
           + [(1 << ID_BITS) - 1])

    def test_encode_decode_is_identity_on_every_id(self) -> None:
        for uid in self.IDS:
            self.assertEqual(text_to_id(id_to_text(uid)), uid)

    def test_the_encoder_never_emits_an_alias_spelling(self) -> None:
        for uid in self.IDS:
            body = id_to_text(uid)[len(UID_PREFIX):]
            self.assertNotIn('z', body)
            self.assertNotIn('9', body)
            if body:
                self.assertNotEqual(body[0], 'a')


class RealWorldDifferential(unittest.TestCase):
    """Every uid the committed corpus carries, both verdict formulations, zero
    disagreements allowed."""

    def _sweep(self, uids: set[str]) -> int:
        noncanonical = 0
        for text in sorted(uids):
            with self.subTest(text):
                uid = text_to_id(text)
                self.assertNotEqual(uid, INVALID_ID)
                round_tripped = canonical(text)
                self.assertEqual(round_tripped == text,
                                 _independently_canonical(text))
                if round_tripped != text:
                    noncanonical += 1
                    # A repair target must itself be stable, or --fix churns.
                    self.assertEqual(canonical(round_tripped), round_tripped)
        return noncanonical

    def test_the_committed_corpus(self) -> None:
        uids = _harvest(CORPUS)
        self.assertGreaterEqual(len(uids), CORPUS_UID_FLOOR,
                                'harvest broke — corpus census below floor')
        self.assertGreaterEqual(self._sweep(uids), CORPUS_NONCANONICAL_FLOOR)


if __name__ == '__main__':
    unittest.main()
