"""test_fuzz_log_schema.py — differential fuzz over the one log-schema machine.

WHY THIS IS A COMMITTED TEST AND NOT A REPORT
D12 (a decisions.md) and D15 (a changelog.md) are ONE implementation over two
schemas — `entry_violations_in`, shared by both gates and by both writers
(`pm decide`, `pm changelog`). When two implementations were folded into one,
the question was whether D12's behaviour survived. It was answered by a 692-log
differential fuzz that ran once inside an agent's context and was reported as a
sentence. The answer is only worth anything if it can be re-obtained on demand,
so the harness lives here.

TWO AXES, and they catch different things:

  1. DIFFERENTIAL AGAINST INTENT. Each generated entry is built from a known
     list of injected defects, and the gate's findings are classified back into
     that vocabulary. The reported set must equal the injected set — for BOTH
     schemas, from the same abstract case. That is the shared-implementation
     property stated as an assertion: the machine treats a decision log and a
     changelog identically, differing only in the field names it was handed.
     A finding that does not classify FAILS the run; it is never ignored, which
     is how a harness quietly narrows into agreement.

  2. GOLDEN CORPUS. The exact findings for a fixed seeded corpus are committed
     under `tests/corpus/`. Axis 1 pins the classes; this pins the words, which
     is what a consumer greps. The file carries a checksum of the corpus it
     describes, so a change to the GENERATOR is reported as such rather than
     silently redescribing different inputs.
"""
from __future__ import annotations

import hashlib
import random
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from support import REPO_ROOT  # noqa: E402

sys.path.insert(0, str(REPO_ROOT / 'src'))
from godot_devkit.repo.pm.model import (  # noqa: E402
    CHANGELOG_SCHEMA, DECISION_SCHEMA, LogSchema,
    entry_violations_in, log_entries_in)

pytestmark = pytest.mark.fuzz

SEED = 20260829
CASES = 692            # the size of the run this replaces
GOLDEN = Path(__file__).resolve().parent / 'corpus' / 'log_schema.golden.txt'
SCHEMAS = (DECISION_SCHEMA, CHANGELOG_SCHEMA)

# The defect vocabulary. Every finding the gate can produce maps to exactly one
# of these, and a message that maps to none is a defect in this harness or a new
# finding nobody declared — both of which must be loud.
BAD_HEADER = 'BAD_HEADER'
BAD_DATE = 'BAD_DATE'
LONG_TITLE = 'LONG_TITLE'
MISSING = 'MISSING'
OUT_OF_ORDER = 'OUT_OF_ORDER'
LONG_VALUE = 'LONG_VALUE'
PROSE_EVIDENCE = 'PROSE_EVIDENCE'

_CLASSIFIERS = (
    ('header is not', BAD_HEADER),
    ('is not a real date', BAD_DATE),
    ('chars, over the', None),        # resolved below: title vs value
    ('missing **', MISSING),
    ('is out of order', OUT_OF_ORDER),
    ('is prose, not a reference', PROSE_EVIDENCE),
)


def classify(message: str) -> str:
    """A finding's defect class, or a failure. Never a shrug.

    An unclassifiable message is raised rather than dropped: a harness that
    silently ignores what it does not recognise converts a loud FAIL into a
    quiet PASS, which is the failure mode this whole file exists against.
    """
    if 'chars, over the' in message:
        return LONG_TITLE if message.startswith('title is') else LONG_VALUE
    for needle, kind in _CLASSIFIERS:
        if kind and needle in message:
            return kind
    raise AssertionError(f'unclassifiable finding: {message!r}')


# --- the corpus ---------------------------------------------------------------
GOOD_DATE = '2026-08-29'
GOOD_EVIDENCE = 'a1b2c3d'
PROSE = 'we discussed it and everyone agreed'
TITLES = ('the sweep verb belongs to the combat layer',
          'the hub remembers where you parked',
          'one reader is the fix')


# The CAP is where an off-by-one lives, and a generator that never lands within
# ±2 of one cannot see it. Mutation testing caught 8 of 9 injected mutations;
# the survivor was `>=` for `>` in the title cap, because every long title this
# produced was ~140 chars and every short one ~40 — measured, at the caps: 0.
# So a slice of cases is rendered at exactly the cap and one either side, and
# the expected set is derived from the SAME number the schema holds.
BOUNDARY_DELTAS = (-1, 0, 1)


# The seed an `Evidence:` boundary value is padded from. It has to stay a
# REFERENCE at any length: one token, word characters, and a `/` — a path
# without one is prose, and padding that injected a second, real finding would
# make the case test two things while claiming to test one.
EVIDENCE_SEED = 'docs/specs/reference'


def _at_length(seed: str, length: int) -> str:
    """`seed` padded to EXACTLY `length` characters, ending in a non-space so
    the header parser measures what was written."""
    return (seed + 'x' * length)[:length]


class Case:
    """One abstract entry: the defects to inject, and what must be reported.

    Abstract because the SAME case is rendered under both schemas. The whole
    point is that the field names differ and nothing else does.
    """

    def __init__(self, rng: random.Random) -> None:
        self.ordinal = rng.randrange(1, 40)
        self.title = rng.choice(TITLES)
        self.bad_header = rng.random() < 0.20
        self.bad_date = (not self.bad_header) and rng.random() < 0.20
        self.long_title = (not self.bad_header) and rng.random() < 0.20
        # Boundary cases: the title (or the value) is rendered at exactly the
        # cap, one under, or one over. `None` is every other case, which is what
        # it was before.
        self.title_delta = (rng.choice(BOUNDARY_DELTAS)
                            if rng.random() < 0.25 else None)
        self.value_delta = (rng.choice(BOUNDARY_DELTAS)
                            if rng.random() < 0.25 else None)
        # At most ONE structural defect, so the expected set stays exact: a
        # missing field cannot also be out of order.
        structural = rng.random()
        self.missing = structural < 0.25
        self.reorder = 0.25 <= structural < 0.45
        self.long_value = rng.random() < 0.20
        self.prose_evidence = rng.random() < 0.25
        self.drop = rng.randrange(0, 4)     # which field, modulo the schema's

    def _fields(self, schema: LogSchema) -> list[tuple[str, str]]:
        names = list(schema.fields)
        if self.missing:
            names.pop(self.drop % len(names))
        elif self.reorder and len(names) > 1:
            names[0], names[1] = names[1], names[0]
        out = []
        for name in names:
            if name == 'Evidence':
                value = PROSE if self.prose_evidence else GOOD_EVIDENCE
            else:
                value = f'the {name.lower()} of this entry'
            if (self.value_delta is not None and names
                    and name == names[-1] and not self.prose_evidence):
                # Exactly at the cap, or one either side of it. Never combined
                # with the gross-over padding below: one defect at a time.
                seed = EVIDENCE_SEED if name == 'Evidence' else value
                out.append((name, _at_length(
                    seed, schema.value_max + self.value_delta)))
                continue
            if self.long_value and name == names[-1]:
                # ONE defect at a time. Padding an `Evidence:` value with prose
                # would inject a second, real finding (evidence is a reference,
                # not a sentence) and the case would then be testing two things
                # while claiming to test one — so the padding stays valid
                # evidence and only the LENGTH is wrong.
                value = value + (' a1b2c3d' * 30 if name == 'Evidence'
                                 else ' x' * 120)
            out.append((name, value))
        return out

    def _rendered_title(self, schema: LogSchema) -> str:
        if self.title_delta is not None:
            return _at_length(self.title, schema.title_max + self.title_delta)
        return self.title + (' and then some' * 6 if self.long_title else '')

    def render(self, schema: LogSchema) -> str:
        eid = f'{schema.prefix}{self.ordinal}'
        title = self._rendered_title(schema)
        date = '2026-13-45' if self.bad_date else GOOD_DATE
        dash = '-' if self.bad_header else '—'
        lines = [f'## {eid} {dash} {date} {dash} {title}']
        lines += [f'**{n}:** {v}' for n, v in self._fields(schema)]
        return '\n'.join(lines)

    def expected(self, schema: LogSchema) -> set[str]:
        out: set[str] = set()
        if self.bad_header:
            # The date and title checks live behind a conforming header — an
            # entry whose header did not parse has no date and no title to hold
            # to anything, and reporting three findings for one defect is noise.
            out.add(BAD_HEADER)
        else:
            if self.bad_date:
                out.add(BAD_DATE)
            # Over the cap is a finding; AT the cap is not. Stated as the
            # comparison the schema states, so a `>` mutated to `>=` disagrees.
            if len(self._rendered_title(schema)) > schema.title_max:
                out.add(LONG_TITLE)
        fields = self._fields(schema)
        names = [n for n, _ in fields]
        if self.missing and len(schema.fields) > len(names):
            out.add(MISSING)
        if self.reorder and len(schema.fields) > 1:
            out.add(OUT_OF_ORDER)
        if any(len(value) > schema.value_max for name, value in fields
               if name in schema.fields):
            out.add(LONG_VALUE)
        if self.prose_evidence and 'Evidence' in names:
            out.add(PROSE_EVIDENCE)
        return out


def _cases(count: int = CASES) -> list[Case]:
    rng = random.Random(SEED)
    return [Case(rng) for _ in range(count)]


def _findings(case: Case, schema: LogSchema) -> list[tuple[int, str, str]]:
    return entry_violations_in(log_entries_in(case.render(schema)), schema)


# --- axis 1: the differential -------------------------------------------------
def test_both_schemas_report_exactly_the_injected_defects():
    mismatches = []
    for n, case in enumerate(_cases()):
        for schema in SCHEMAS:
            found = {classify(msg) for _, _, msg in _findings(case, schema)}
            want = case.expected(schema)
            if found != want:
                mismatches.append(
                    f'case {n} / {schema.rule}: reported {sorted(found)}, '
                    f'injected {sorted(want)}\n' + case.render(schema))
    assert not mismatches, (
        f'{len(mismatches)} of {CASES * len(SCHEMAS)} renders disagreed with '
        f'the defects injected into them (seed {SEED}):\n\n'
        + '\n\n'.join(mismatches[:5]))


def test_the_two_schemas_are_one_machine():
    """The property the consolidation had to preserve, as an assertion.

    Every defect class the decision schema reports, the changelog schema
    reports for the same abstract case. Stated the other way round: the machine
    differs between D12 and D15 in DATA, never in behaviour.

    Scoped to cases with no STRUCTURAL defect, and the scoping is the honest
    part: dropping or reordering a field means the two schemas are no longer
    being handed the same shape (a 4-field list loses a different field than a
    2-field one), so an equality there would be comparing two different
    questions. Those cases are covered by the injected-defect differential
    above, which knows exactly which field each schema lost.
    """
    compared = 0
    for n, case in enumerate(_cases()):
        if case.missing or case.reorder:
            continue
        compared += 1
        shapes = [{classify(msg) for _, _, msg in _findings(case, schema)}
                  for schema in SCHEMAS]
        assert shapes[0] == shapes[1], f'case {n}: {shapes}'
    assert compared > 300, f'only {compared} cases were comparable'


def test_the_corpus_actually_produces_findings_and_clean_entries():
    """The census. A corpus that is all defects, or none, tests one branch."""
    clean = dirty = total = 0
    for case in _cases():
        for schema in SCHEMAS:
            found = _findings(case, schema)
            total += len(found)
            if found:
                dirty += 1
            else:
                clean += 1
    assert clean > 50, clean
    assert dirty > 500, dirty
    assert total > 1000, total


def test_the_corpus_lands_on_the_caps_and_on_both_sides_of_them():
    """The boundary census, and it is the reason the boundary cases exist.

    Mutation testing caught 8 of 9 injected mutations. The survivor was `>=`
    for `>` in the title cap — not because the assertion was weak but because
    the corpus never produced a title within +-2 of it: measured, exactly at
    the title cap: 0, exactly at the value cap: 0. A count of 0 in either
    column here means the boundary is inert again and the next off-by-one
    lives.
    """
    seen: dict[tuple[str, int], int] = {}
    for case in _cases():
        for schema in SCHEMAS:
            title = case._rendered_title(schema)
            for delta in BOUNDARY_DELTAS:
                if len(title) == schema.title_max + delta:
                    seen[('title', delta)] = seen.get(('title', delta), 0) + 1
                for name, value in case._fields(schema):
                    if (name in schema.fields
                            and len(value) == schema.value_max + delta):
                        seen[('value', delta)] = seen.get(('value', delta), 0) + 1
    missing = [key for key in ((what, delta) for what in ('title', 'value')
                               for delta in BOUNDARY_DELTAS)
               if seen.get(key, 0) == 0]
    assert not missing, f'no case lands at {missing}; census: {sorted(seen.items())}'


def test_a_cap_comparison_mutated_to_ge_is_caught():
    """The survivor, as an assertion. `>` becomes `>=`: an entry exactly AT the
    cap is then reported, and the corpus has to disagree with that.

    Run against the real predicate through a patched schema rather than by
    editing model.py: a cap one LOWER makes an at-the-cap entry over it, which
    is the same difference the mutation makes, and it needs no source edit."""
    import dataclasses
    caught = 0
    for case in _cases():
        for schema in SCHEMAS:
            mutated = dataclasses.replace(schema,
                                          title_max=schema.title_max - 1,
                                          value_max=schema.value_max - 1)
            found = {classify(msg) for _, _, msg
                     in entry_violations_in(log_entries_in(case.render(schema)),
                                            mutated)}
            if found != case.expected(schema):
                caught += 1
    assert caught > 100, (
        f'only {caught} of {CASES * len(SCHEMAS)} cases disagree with a cap '
        f'shifted by one — the corpus cannot see an off-by-one at the cap')


# --- axis 2: the golden corpus ------------------------------------------------
def _corpus_checksum() -> str:
    digest = hashlib.sha256()
    for case in _cases():
        for schema in SCHEMAS:
            digest.update(case.render(schema).encode('utf-8'))
            digest.update(b'\0')
    return digest.hexdigest()[:16]


def _golden_lines() -> list[str]:
    out = [f'corpus {_corpus_checksum()} seed {SEED} cases {CASES}']
    for n, case in enumerate(_cases()):
        for schema in SCHEMAS:
            for ordinal, eid, message in _findings(case, schema):
                out.append(f'{n:04d}|{schema.rule}|{ordinal}|{eid}|{message}')
    return out


def test_findings_match_the_committed_golden_corpus():
    """The exact words, pinned. A baseline in the tree, not in an old revision.

    A wording change here is a real change — consumers grep these lines — so it
    is meant to fail, be read, and be re-recorded with
    `python3 tests/test_fuzz_log_schema.py --write`.
    """
    assert GOLDEN.is_file(), f'{GOLDEN} is missing — regenerate it'
    want = GOLDEN.read_text(encoding='utf-8').splitlines()
    got = _golden_lines()
    if want[:1] != got[:1]:
        raise AssertionError(
            f'the CORPUS changed, not just the behaviour: golden header '
            f'{want[:1]} vs {got[:1]}. A golden that silently redescribes '
            f'different inputs proves nothing — regenerate deliberately.')
    first = next((i for i, (a, b) in enumerate(zip(want, got)) if a != b), None)
    assert first is None and len(want) == len(got), (
        f'golden corpus diverged at line {first} '
        f'({len(want)} recorded, {len(got)} produced)\n'
        f'  recorded: {want[first] if first is not None else "<missing>"}\n'
        f'  produced: {got[first] if first is not None else "<missing>"}')


if __name__ == '__main__':
    if '--write' in sys.argv:
        GOLDEN.parent.mkdir(parents=True, exist_ok=True)
        GOLDEN.write_text('\n'.join(_golden_lines()) + '\n', encoding='utf-8')
        print(f'wrote {GOLDEN} ({len(_golden_lines())} lines)')
    else:
        print(__doc__)
