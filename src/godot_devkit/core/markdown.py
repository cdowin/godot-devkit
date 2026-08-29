"""markdown.py — reading agent-facing markdown without misreading it.

A fenced block is an ILLUSTRATION, not a claim: a rule file that quotes the
CLI's own refusal message is documenting the refusal, not instructing it. Any
checker that scans these documents line-by-line has to know that, and there is
no reason for each one to learn it separately.
"""
from __future__ import annotations

import re

# CommonMark: an opening fence carries at most THREE leading spaces and at
# least three markers. Four spaces is INDENTED CODE, and what it holds is
# content, not a fence — a doc that shows how a fence is written indents the
# sample, and reading that sample as a real fence hid everything after it.
FENCE = re.compile(r'^[ ]{0,3}(`{3,}|~{3,})[ \t]*(\S*)')
# A backtick span, or a line that begins with a shell prompt / bare command —
# the forms in which a document is quoting a COMMAND rather than using a word.
CODE_SPAN = re.compile(r'`([^`]+)`')
COMMAND_LINE = re.compile(r'^\s*(?:[$>]\s*)?(\S.*)$')


def fenced_flags(lines: list[str]) -> tuple[list[bool], int]:
    """(per line: is it part of a fenced code block?, the 1-based line of a
    fence that is never terminated, or 0).

    A closing fence is the same character, at least as long, and carries no
    info string. A parity toggle over "any line that looks like a fence" gets
    all three wrong: it lets `~~~` close a ```` ``` ````, counts an indented
    sample, and — the reason this is not a style point — an ODD number of
    fence-looking lines drops every remaining line of the document.

    An UNTERMINATED fence therefore masks NOTHING here. Left masked it would
    drop the rest of the file and the gate would print PASS over the lines it
    ate: a checker cannot both skip a region and claim it scanned the file.
    It is returned to be REPORTED instead — the same resolution
    `decision_fence_defect` reaches for a decision log, because it is the same
    defect.
    """
    fenced = [False] * len(lines)
    fence, opened = '', 0
    for idx, raw in enumerate(lines):
        match = FENCE.match(raw.rstrip('\r'))
        if fence:
            fenced[idx] = True
            # Same character, at least as long, no info string.
            if match and match.group(1)[0] == fence[0] \
                    and len(match.group(1)) >= len(fence) and not match.group(2):
                fence = ''
            continue
        if match:
            fence, opened = match.group(1), idx
            fenced[idx] = True
    if not fence:
        return fenced, 0
    for k in range(opened, len(lines)):  # never terminated: it masked nothing
        fenced[k] = False
    return fenced, opened + 1


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
