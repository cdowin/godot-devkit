"""markdown.py — reading agent-facing markdown without misreading it.

A fenced block is an ILLUSTRATION, not a claim: a rule file that quotes the
CLI's own refusal message is documenting the refusal, not instructing it. Any
checker that scans these documents line-by-line has to know that, and there is
no reason for each one to learn it separately.
"""
from __future__ import annotations

import re
from typing import NamedTuple

# CommonMark: an opening fence carries at most THREE leading spaces and at
# least three markers. Four spaces is INDENTED CODE, and what it holds is
# content, not a fence — a doc that shows how a fence is written indents the
# sample, and reading that sample as a real fence hid everything after it.
# The rest of the line is the INFO STRING; `fence_at` applies the rule that
# says which info strings a fence may carry.
FENCE = re.compile(r'^[ ]{0,3}(`{3,}|~{3,})(.*)$')
# A backtick span — the form in which a document quotes a COMMAND rather than
# using a word.
CODE_SPAN = re.compile(r'`([^`]+)`')
COMMENT_OPEN = '<!--'
COMMENT_CLOSE = '-->'


def fence_at(raw: str) -> tuple[str, str] | None:
    """(marker run, info string) when this line is a fence line, else None.

    CommonMark: the info string after a BACKTICK fence MAY NOT CONTAIN A
    BACKTICK. Without that rule a paragraph merely BEGINNING with a balanced
    ```inline``` span read as a fence opener, a later bare ``` "closed" it, and
    everything between was masked — in SILENCE, because a fence that opens and
    closes looks perfectly well-formed. That is the cardinal sin arrived at by
    a third route, and the reason this rule is applied here rather than left to
    the two-and-a-bit checkers that ask about fences.

    TILDES carry no such restriction: `~~~ a ``b`` c` is a real fence whose
    info string holds backticks, and over-applying the rule would mask a
    document's genuine sample instead.

    The info string is the WHOLE rest of the line, not its first word: it is
    the tail that carries the closing backticks of an inline span, and reading
    only the first token is what let one through.
    """
    match = FENCE.match(raw)
    if not match:
        return None
    marker, info = match.group(1), match.group(2).strip()
    if marker[0] == '`' and '`' in info:
        return None
    return marker, info


def mask_code_spans(raw: str) -> str:
    """The line with every inline `code span` blanked to spaces.

    Offsets are preserved, so the caller can go on searching the masked line
    and still report positions from the real one. A marker inside backticks is
    a marker being NAMED, not a comment being opened — which is exactly how a
    log documenting comment handling swallowed its own next three fields.
    """
    out = list(raw)
    i, n = 0, len(raw)
    while i < n:
        if raw[i] != '`':
            i += 1
            continue
        j = i
        while j < n and raw[j] == '`':
            j += 1
        close = raw.find(raw[i:j], j)
        if close < 0:  # an unpaired run opens no span
            i = j
            continue
        end = close + (j - i)
        for k in range(i, end):
            out[k] = ' '
        i = end
    return ''.join(out)


class BlockScan(NamedTuple):
    """Where a document's fenced blocks and HTML comments are.

    One scan for both, because the two markers hide each other and only
    document ORDER settles which: a ``` inside a `<!-- -->` is a fence being
    QUOTED (CommonMark puts it inside an HTML block), and a `<!--` inside a
    fenced sample is a marker being SHOWN. Deciding them in two passes gets one
    of the two wrong whichever pass runs first — computing fences first
    reported a perfectly well-formed document malformed.

    `fenced` and `unterminated` are what a fence-only reader needs;
    `comment_spans` (each `(opening line, closing line, offset just past the
    `-->`)`) and `unclosed` are the other half, collected only when the caller
    asked for comments — `check doc` and `check agents` scan comment text like
    `<!-- doc-scan:allow -->` and must keep reading it.
    """

    fenced: list[bool]
    unterminated: int
    comment_spans: list[tuple[int, int, int]]
    unclosed: int


def block_scan(lines: list[str], *, comments: bool = False) -> BlockScan:
    """Walk the document once, in order, tracking which block is open.

    A closing fence is the same character, at least as long, and carries no
    info string. A parity toggle over "any line that looks like a fence" gets
    all three wrong: it lets `~~~` close a ```` ``` ````, counts an indented
    sample, and — the reason this is not a style point — an ODD number of
    fence-looking lines drops every remaining line of the document.

    An UNTERMINATED fence therefore masks NOTHING here. Left masked it would
    drop the rest of the file and the gate would print PASS over the lines it
    ate: a checker cannot both skip a region and claim it scanned the file.
    It is returned to be REPORTED instead — the same resolution
    `log_fence_defect` reaches for a decisions.md or a changelog.md, because it
    is the same defect. An unclosed `<!--` suppresses nothing for the same
    reason, and is returned the same way.
    """
    fenced = [False] * len(lines)
    spans: list[tuple[int, int, int]] = []
    fence, opened = '', 0
    inside, start = False, 0
    for idx, raw in enumerate(lines):
        here = fence_at(raw.rstrip('\r'))
        if fence:
            fenced[idx] = True
            # Same character, at least as long, no info string.
            if here and here[0][0] == fence[0] \
                    and len(here[0]) >= len(fence) and not here[1]:
                fence = ''
            continue
        # A comment already open swallows the fence marker: the ``` is text
        # inside an HTML block, not a block of its own.
        if not inside and here:
            fence, opened = here[0], idx
            fenced[idx] = True
            continue
        if not comments:
            continue
        # Masked so that a marker inside backticks is a marker being NAMED, not
        # a comment being opened. Blanking preserves length, so a marker
        # OUTSIDE the masked ranges still lands at its real offset.
        line = mask_code_spans(raw)
        i = 0
        while i < len(line):
            if inside:
                j = line.find(COMMENT_CLOSE, i)
                if j < 0:
                    break
                spans.append((start, idx, j + len(COMMENT_CLOSE)))
                inside, i = False, j + len(COMMENT_CLOSE)
            else:
                j = line.find(COMMENT_OPEN, i)
                if j < 0:
                    break
                inside, start, i = True, idx, j + len(COMMENT_OPEN)
    unterminated = 0
    if fence:
        for k in range(opened, len(lines)):  # never terminated: it masked nothing
            fenced[k] = False
        unterminated = opened + 1
    return BlockScan(fenced, unterminated, spans,
                     start + 1 if inside else 0)


def fenced_flags(lines: list[str]) -> tuple[list[bool], int]:
    """(per line: is it part of a fenced code block?, the 1-based line of a
    fence that is never terminated, or 0).

    The fence half of `block_scan`, for the readers that do not treat an HTML
    comment as a region of its own.
    """
    scan = block_scan(lines)
    return scan.fenced, scan.unterminated


def non_fenced_lines(text: str) -> tuple[list[tuple[int, str]], int]:
    """((1-indexed lineno, line) pairs with fenced code-block bodies dropped,
    the 1-based line of a fence that is never terminated, or 0).

    The second half of the pair is not decoration the caller may drop: an
    unterminated fence is the one input under which the first half is not the
    whole document, and a gate that does not report it prints PASS over
    whatever the stray marker covered.
    """
    lines = text.split('\n')
    fenced, unterminated = fenced_flags(lines)
    kept = [(n, line)
            for n, (line, hidden) in enumerate(zip(lines, fenced), 1)
            if not hidden]
    return kept, unterminated


def code_spans(line: str) -> list[str]:
    """The backticked spans on a line — where a document quotes a command.

    Prose that merely uses the same words ("the pm story lifecycle") is not a
    command and must not be read as one; requiring the span is what separates
    them.
    """
    return CODE_SPAN.findall(line)
