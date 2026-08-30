"""godot.write — the scene-surgery verbs, plus the one rendering they share.

Every write verb reports its work the same way: a unified diff with one line
of context — enough to see the edit, never a re-dump of the scene. That shape
is a consumer-grepped contract (CLAUDE.md rule 6), so it has exactly one home.
"""
from __future__ import annotations

import difflib

DIFF_CONTEXT = 1


def render_diff(before: str, after: str, name: str) -> str:
    return ''.join(difflib.unified_diff(
        before.splitlines(keepends=True), after.splitlines(keepends=True),
        fromfile=f'a/{name}', tofile=f'b/{name}', n=DIFF_CONTEXT))
