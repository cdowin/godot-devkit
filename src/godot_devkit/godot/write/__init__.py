"""godot.write — the scene-surgery verbs, plus the one rendering they share.

Every write verb reports its work the same way: a unified diff with one line
of context — enough to see the edit, never a re-dump of the scene. That shape
is a consumer-grepped contract (CLAUDE.md rule 6), so it has exactly one home.

The UTF-8 refusal is the other shared output shape: a write verb never
rewrites bytes it cannot read, and every verb says so in the same sentence —
`load_scene_or_refuse` / `utf8_refusal_reason` below are its one home, so a
tenth write verb gets the contract for free instead of pasting the paragraph.
"""
from __future__ import annotations

import difflib
from pathlib import Path

from godot_devkit.godot.format.tscn_document import read_scene_text

DIFF_CONTEXT = 1


def render_diff(before: str, after: str, name: str) -> str:
    return ''.join(difflib.unified_diff(
        before.splitlines(keepends=True), after.splitlines(keepends=True),
        fromfile=f'a/{name}', tofile=f'b/{name}', n=DIFF_CONTEXT))


def utf8_refusal_reason(err: UnicodeDecodeError) -> str:
    """The one sentence for bytes no write verb can read.

    `refs_retarget` composes it under a SKIPPED line (a sweep steps over the
    file and keeps going); the single-file verbs put it under REFUSED via
    `load_scene_or_refuse`. Same fact, one spelling.
    """
    return (f'not valid UTF-8 ({err.reason} at byte {err.start}) — '
            f'refusing to rewrite bytes this tool cannot read')


def load_scene_or_refuse(path: str | Path) -> str | None:
    """`read_scene_text`, or None with the shared REFUSED line printed."""
    try:
        return read_scene_text(path)
    except UnicodeDecodeError as err:
        print(f'REFUSED  {path}: {utf8_refusal_reason(err)}')
        return None


def file_exists(path: Path) -> bool:
    """`Path.is_file()` that answers False for a path the FILESYSTEM refuses.

    A component longer than the filesystem's NAME_MAX raises `OSError` out of
    `stat` on 3.11, 3.12 and 3.13, and is swallowed into False from 3.14 on —
    so a write verb handed an over-long path came out as a raw traceback or as
    a refusal depending on which interpreter `uvx` picked. False is the answer
    both readings want: nothing is there, and the caller's own missing-file
    refusal names the path. The write plane's copy of the guard the pm plane
    grew for exactly this (`repo/pm/cli._exists`).
    """
    try:
        return path.is_file()
    except OSError:
        return False
