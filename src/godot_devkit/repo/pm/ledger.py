"""ledger.py — the milestone's append-only row log (`ledger.jsonl`).

One JSON object per line, in `pm/roadmap/<milestone>/ledger.jsonl`, beside
`decisions.md` (D6). `decisions.md` is the prose sibling — a person writes it
and a person reads it; this is the machine one: the verbs write it and a report
reads it, and neither file is ever a copy of the other.

THREE PROPERTIES, AND EVERY CALLER DEPENDS ON ALL THREE:

  * **Append-only.** `append_row` opens `'a'` and writes one line. It never
    reads, never parses, never rewrites a byte that is already there — so a
    row landed by another process, another branch, or an older version of this
    package survives a shape change here, and a `merge=union` on the file makes
    two branches' rows one file rather than one conflict.
  * **One line per row, compact.** `separators=(',',':')` and no newline inside
    the line, so a row is exactly one `readline()` and a `wc -l` is a row count.
    `ensure_ascii=False` because a decision title is prose and a `\\u2014` in
    the durable log helps nobody read it.
  * **The timestamp is the whole point** (D8). Full UTC ISO-8601 at second
    resolution, `Z`-suffixed — never a local time and never a bare date: time
    in each state is a SUBTRACTION over two rows, and a date cannot answer
    "how long was this at `review`".

Nothing here decides WHEN a row is written; that is the verb's business, and
the verbs write theirs only after their own write to the tree has landed.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

# Beside `decisions.md`, inside the milestone directory that owns it — so
# `retire` removes it with the directory and git is the archive (D6).
LEDGER_FILE_NAME = 'ledger.jsonl'

# The row kinds this module mints. `dispatch` and `session` rows arrive from
# `pm ledger record` and are not built here.
KIND_STATUS = 'status'
KIND_DECISION = 'decision'

# `2026-09-03T21:40:12Z`. `datetime.isoformat()` spells the offset `+00:00`,
# and two spellings of one instant in a durable log is a parser's problem
# forever, so the format is stated rather than inherited.
TS_FORMAT = '%Y-%m-%dT%H:%M:%SZ'

# U+2028 and U+2029 are LINE TERMINATORS to `str.splitlines()` (and to a
# browser's JSON reader), and `ensure_ascii=False` writes them out raw — so one
# row carrying either, in a hand-edited id or a pasted decision title, would
# read back as two rows, one of them invalid. Escaped to their `\uXXXX` form,
# which is still exactly the same JSON: every structural character is ASCII, so
# these two can only ever occur inside a string.
LINE_BREAKERS = {'\u2028': '\\u2028', '\u2029': '\\u2029'}


def dumps(row: dict) -> str:
    """ONE row as ONE line — the whole serialisation contract, in one place."""
    line = json.dumps(row, separators=(',', ':'), ensure_ascii=False)
    for char, escaped in LINE_BREAKERS.items():
        line = line.replace(char, escaped)
    return line


def utc_now() -> str:
    """The current instant, full UTC ISO-8601 at second resolution."""
    return datetime.now(timezone.utc).strftime(TS_FORMAT)


def status_row(grain_id: str, frm: str, to: str, ts: str = '') -> dict:
    """One status transition. `from` is what the file HELD, `to` what it holds.

    A no-op flip (`from == to`) is a row like any other: somebody ran the verb,
    and that is a fact about the work (D2's cost note, carried by D8).
    """
    return {'ts': ts or utc_now(), 'kind': KIND_STATUS, 'grain': grain_id,
            'from': frm, 'to': to}


def decision_row(grain_id: str, entry: str, title: str, ts: str = '') -> dict:
    """One decision heading, as `pm decide` stamped it into `decisions.md`."""
    return {'ts': ts or utc_now(), 'kind': KIND_DECISION, 'grain': grain_id,
            'entry': entry, 'title': title}


def ledger_path(milestone_dir: Path) -> Path:
    """Where one milestone's ledger lives. The only place this name is joined."""
    return milestone_dir / LEDGER_FILE_NAME


def append_row(milestone_dir: Path, row: dict) -> None:
    """Append ONE row to `<milestone_dir>/ledger.jsonl`, creating it if absent.

    Minted on first write, like `decisions.md` — an empty ledger in every
    milestone directory would be the sprawl the scaffolder was cured of. The
    FILE is created; the DIRECTORY is never created here, because every caller
    has just written a grain document that lives in it — and mkdir is one of
    the mutations `core.apply` single-homes (tests/test_boundaries.py).

    The write itself is `open('a')` rather than a `core.apply` overwrite, and
    that is the point: an overwrite is read-modify-write, which drops rows when
    two appenders (two milestone branches, an async SubagentStop hook and a
    verb) land in the same instant, and rewrites bytes `merge=union` is relying
    on nobody rewriting. Append is a different primitive, not a shortcut past
    the one plan.

    Raises `OSError` when the line cannot be written. It does NOT swallow that:
    the caller has already changed the tree, and "the row is missing" is a fact
    its report has to carry rather than one this function hides.
    """
    line = dumps(row) + '\n'
    with ledger_path(milestone_dir).open('a', encoding='utf-8',
                                         newline='\n') as handle:
        handle.write(line)

