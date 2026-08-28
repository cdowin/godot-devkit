"""markdown.py — reading agent-facing markdown without misreading it.

A fenced block is an ILLUSTRATION, not a claim: a rule file that quotes the
CLI's own refusal message is documenting the refusal, not instructing it. Any
checker that scans these documents line-by-line has to know that, and there is
no reason for each one to learn it separately.
"""
from __future__ import annotations

import re

FENCE = re.compile(r'^\s*(```|~~~)')
# A backtick span, or a line that begins with a shell prompt / bare command —
# the forms in which a document is quoting a COMMAND rather than using a word.
CODE_SPAN = re.compile(r'`([^`]+)`')
COMMAND_LINE = re.compile(r'^\s*(?:[$>]\s*)?(\S.*)$')


def non_fenced_lines(text: str) -> list[tuple[int, str]]:
    """(1-indexed lineno, line) pairs with fenced code-block bodies dropped."""
    kept: list[tuple[int, str]] = []
    in_fence = False
    for lineno, line in enumerate(text.split('\n'), 1):
        if FENCE.match(line):
            in_fence = not in_fence
            continue
        if not in_fence:
            kept.append((lineno, line))
    return kept


def code_spans(line: str) -> list[str]:
    """The backticked spans on a line — where a document quotes a command.

    Prose that merely uses the same words ("the pm story lifecycle") is not a
    command and must not be read as one; requiring the span is what separates
    them.
    """
    return CODE_SPAN.findall(line)
