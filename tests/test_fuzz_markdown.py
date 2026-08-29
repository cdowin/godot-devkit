"""test_fuzz_markdown.py — differential fuzz: the fence scanner vs the spec.

WHY THIS IS A COMMITTED TEST AND NOT A REPORT
Every checker in this package that reads agent-facing markdown decides, line by
line, whether it is looking at a claim or at an illustration. Get that wrong and
the gate prints PASS over the region it swallowed — the cardinal sin, arrived at
by parsing. That decision was fuzzed once against a spec-literal reference; the
run found 4,525 divergences in the scanner of the day and 0 in the one that
shipped. Then the harness evaporated with the context it ran in, and the 0 became
a sentence somebody had to trust.

So it lives here. Seeded, so a divergence reproduces exactly rather than being
re-derived, and deterministic, because a fuzz that varies run to run is not a
gate.

WHAT THE REFERENCE IS
`_reference_fenced` is an independent transcription of CommonMark 0.31 §4.5 —
written from the rule text, not from `core/markdown.py`. Two documented places
where the shipped scanner deliberately departs from a naive reading of the spec,
and the reference matches it on both because both are the CONTRACT, not
accidents:

  1. The fence LINES themselves count as inside the block. The spec calls them
     delimiters rather than content; every consumer here wants them masked.
  2. An UNTERMINATED fence masks NOTHING. The spec ends such a block at the end
     of the document; this package refuses to let a stray marker eat the tail of
     a file in silence, and reports the opening line instead.

Anything else that differs is a defect in one of the two, and the failure prints
the document that separated them.
"""
from __future__ import annotations

import random
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from support import REPO_ROOT  # noqa: E402

sys.path.insert(0, str(REPO_ROOT / 'src'))
from godot_devkit.core.markdown import (  # noqa: E402
    fenced_flags, non_fenced_lines)

pytestmark = pytest.mark.fuzz

# The seed is part of the gate. Changing it changes which documents are covered,
# so it moves only with a recorded reason.
SEED = 20260829
CASES = 60000
MAX_LINES = 12


# --- the reference ------------------------------------------------------------
def _leading_spaces(line: str) -> int:
    """How many SPACES open the line. A tab is not a space.

    CommonMark measures indentation in columns and expands tabs to a 4-column
    stop, which puts any tab-opened line at 4+ and therefore outside a fence's
    3-space allowance. Counting spaces only reaches the same verdict for every
    line either implementation is asked about.
    """
    n = 0
    while n < len(line) and line[n] == ' ':
        n += 1
    return n


def _fence_parts(line: str) -> tuple[str, str] | None:
    """(marker run, info string) if the line is a fence DELIMITER, else None.

    Spec: "a sequence of at least three consecutive backtick characters or
    tildes", indented no more than three spaces, and — for a backtick fence —
    "the info string may not contain any backtick characters".
    """
    indent = _leading_spaces(line)
    if indent > 3 or indent >= len(line):
        return None
    char = line[indent]
    if char not in '`~':
        return None
    end = indent
    while end < len(line) and line[end] == char:
        end += 1
    if end - indent < 3:
        return None
    marker, info = line[indent:end], line[end:].strip()
    if char == '`' and '`' in info:
        return None
    return marker, info


def _reference_fenced(lines: list[str]) -> tuple[list[bool], int]:
    """(is line i inside a fenced block?, the 1-based line of an open fence).

    A closing fence "uses the same character as the opening fence, is at least
    as long as the opening fence, and is indented no more than three spaces" and
    "may not have an info string".
    """
    inside = [False] * len(lines)
    opener = ''
    opened = 0
    for i, raw in enumerate(lines):
        parts = _fence_parts(raw)
        if not opener:
            if parts:
                opener, opened = parts[0], i
                inside[i] = True
            continue
        inside[i] = True
        if parts and parts[0][0] == opener[0] \
                and len(parts[0]) >= len(opener) and not parts[1]:
            opener = ''
    if opener:
        # Deviation 2: a fence nobody closed masks nothing, and is reported.
        for k in range(opened, len(lines)):
            inside[k] = False
        return inside, opened + 1
    return inside, 0


# --- the corpus ---------------------------------------------------------------
# Every line shape that has ever separated a fence reader from the spec, plus
# ordinary text to sit between them. Generated rather than listed so the
# ORDERING is fuzzed too: the bugs this catches are all about which marker is
# open when the next one arrives.
_INFOS = ('', ' ', 'toml', 'text', ' bash', 'py extra words',
          '`inline`', 'a `b` c', '``', 'x`', '~~~', '```')
_PROSE = ('the pm story lifecycle', '', '   ', 'a `code span` in prose',
          '<!-- a comment -->', '| a | b |', '#### heading',
          'text with ``double`` spans', '\ta tab-opened line',
          'trailing backticks ```', '- a list item')


def _fence_line(rng: random.Random) -> str:
    char = rng.choice('`~')
    return (' ' * rng.randrange(0, 6)
            + char * rng.randrange(2, 6)
            + rng.choice(_INFOS))


def _document(rng: random.Random) -> list[str]:
    out = []
    for _ in range(rng.randrange(1, MAX_LINES)):
        out.append(_fence_line(rng) if rng.random() < 0.55
                   else rng.choice(_PROSE))
    return out


def _documents(count: int) -> list[list[str]]:
    rng = random.Random(SEED)
    return [_document(rng) for _ in range(count)]


# --- the differential ---------------------------------------------------------
def test_fence_scanner_matches_a_spec_literal_reference():
    divergences = []
    for case, lines in enumerate(_documents(CASES)):
        got_flags, got_open = fenced_flags(lines)
        want_flags, want_open = _reference_fenced(lines)
        if got_flags != want_flags or got_open != want_open:
            divergences.append(
                f'case {case}: fenced={got_flags} unterminated={got_open}\n'
                f'  reference: fenced={want_flags} unterminated={want_open}\n'
                + '\n'.join(f'    {n:>2} | {line!r}'
                            for n, line in enumerate(lines, 1)))
    assert not divergences, (
        f'{len(divergences)} of {CASES} documents scanned differently from the '
        f'CommonMark reference (seed {SEED}):\n\n'
        + '\n\n'.join(divergences[:5]))


def test_the_corpus_actually_exercises_both_verdicts():
    """A fuzz whose corpus is all one answer proves nothing.

    The census, printed as an assertion rather than trusted: the generated
    documents have to contain masked lines, unmasked lines, and unterminated
    fences, or the differential above is comparing two functions that both
    return the same constant.
    """
    masked = unmasked = unterminated = 0
    for lines in _documents(CASES):
        flags, open_at = _reference_fenced(lines)
        masked += sum(flags)
        unmasked += len(flags) - sum(flags)
        unterminated += 1 if open_at else 0
    assert masked > 1000, masked
    assert unmasked > 1000, unmasked
    assert unterminated > 100, unterminated


def _naive_parity_fenced(lines: list[str]) -> tuple[list[bool], int]:
    """The WRONG scanner, kept on purpose: toggle on anything fence-shaped.

    This is the implementation the differential was built to reject — it lets a
    `~~~` close a ``` fence, counts an indented sample, and on an odd number of
    fence-looking lines drops every remaining line of the document.
    """
    inside = [False] * len(lines)
    open_ = False
    for i, raw in enumerate(lines):
        if raw.lstrip(' ').startswith(('```', '~~~')):
            open_ = not open_
            inside[i] = True
            continue
        inside[i] = open_
    return inside, 0


def test_the_differential_separates_a_known_bad_scanner():
    """The harness proven to have teeth, not just to be green.

    A probe that does not perturb anything is indistinguishable from a gate that
    works. So the same corpus is run against the scanner this package rejected,
    and the run must find divergences — many of them.
    """
    found = 0
    for lines in _documents(CASES // 10):
        if _naive_parity_fenced(lines) != _reference_fenced(lines):
            found += 1
    assert found > 100, (
        f'the corpus separated the naive parity scanner from the reference in '
        f'only {found} of {CASES // 10} documents — the fuzz has lost its teeth')


def test_non_fenced_lines_drops_exactly_what_the_scanner_masked():
    """The wrapper every checker actually calls, held to the scanner beneath it.

    Two readers of one fact is where a mask and its census go out of step, and
    the shape of that defect is a gate reporting a line it never scanned.
    """
    for lines in _documents(CASES // 4):
        text = '\n'.join(lines)
        kept, unterminated = non_fenced_lines(text)
        flags, want_open = _reference_fenced(text.split('\n'))
        assert unterminated == want_open
        assert [n for n, _ in kept] == [
            n for n, hidden in enumerate(flags, 1) if not hidden]
