"""report.py — `pm ledger report`: the milestone's raw rows, added up.

The ledger writes and never judges (Chris, 2026-09-03: *"It just timestamps
transitions and stamps whatever hook data. Judgement/inference is left to the
caller."*). **This module is that caller**, and it lives outside `ledger.py`
for exactly that reason: one module appends rows and reads them back, another
one decides what a pile of rows MEANS. A report that grew inside the writer
would make the writer's contract negotiable.

WHAT IT MAY DO, AND WHAT IT MAY NOT (D5):

  * it may SUM (four token counts, tool calls, wall-clock), COUNT (dispatches,
    rows, grains), SUBTRACT (seconds between two status rows) and GROUP (by
    grain, by kind, by agent type);
  * it may not WEIGHT, ESTIMATE, PRICE or LABEL. `size:` is printed as a
    COLUMN and is never a divisor; there is no dollar figure, no efficiency
    score, no "expensive" and no leaderboard. A number here can always be
    re-derived from the rows, which is the whole reason the rows are raw.

THREE RULES THE TABLE KEEPS:

  * **Absent is not zero.** A row that carried no `cache_creation` contributes
    NOTHING to that column, and a column no row carried prints `-`. A `0` is a
    measurement — "the API returned none" — and printing one where nobody
    counted is hard rule 4's read-side sin with a column header on it.
  * **The tree is walked, not the ledger.** Every story, feature and bug under
    the milestone gets a row, whether or not any ledger row names it. A grain
    absent from the table because nothing measured it would read as a grain
    that does not exist.
  * **Nothing is dropped.** A dispatch row whose `tree` names no grain under
    this milestone is counted in its own trailing block — not hidden, and not
    labelled beyond the heading that says what is true of it: it names no
    grain.

Exit codes are the CLI's; the only failure this module can produce is a
`ledger.LedgerError` from a line that will not parse, and nothing here ever
fails on a NUMBER.
"""
from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import NamedTuple

from godot_devkit.repo.pm import ledger, model

# The two line shapes a consumer greps (hard rule 6): the heading and the
# summary. Both carry the milestone id, so a report of two milestones
# concatenated is still attributable line by line.
HEADING_PREFIX = '[ledger:report]'

# What a section calls itself in `--json` and in its own heading.
SECTION_SPEND = 'spend'
SPEND_TITLE = 'spend per grain'

# Printed for a NUMBER nobody recorded. A blank cell would read as zero at a
# glance and a `0` would BE a lie; `-` is the third thing, and it is the same
# character `pm list` already prints for an unowned story.
DASH = '-'

# The milestone has no `ledger.jsonl` at all — no rows have ever been written
# for it. A fact, not a failure: exit 0, one line, no table of dashes.
NO_LEDGER = 'no ledger'

# Two spaces between columns, `--` before a block heading — the shape
# `pm status` already uses for its phase buckets.
COLUMN_GAP = '  '
BLOCK_PREFIX = '--'
SUB_ROW_INDENT = '  '

# Frontmatter key printed as a column and used for nothing else (D5).
SIZE_FIELD = 'size'

# Grain kinds, in the order their tables print. `bug` is spelled by `ledger`
# because `terminal_state` reads the same word — a bug's last state is the one
# thing about a vocabulary this package lets a project rename.
KIND_STORY = 'story'
KIND_FEATURE = 'feature'
KIND_BUG = ledger.GRAIN_BUG
KIND_ORDER = (KIND_STORY, KIND_FEATURE, KIND_BUG)

# D3's snapshot buckets, by the kind of grain whose ids they hold. A dispatch
# row names a story by having it `wip` or at `review` when the hook fired, and
# a feature by being `building`/`review` — or, below, by owning one of the
# named stories. Nothing else on the row is attribution: `milestones_building`
# is on every row and would attribute every dispatch to every grain.
DISPATCH_BUCKETS = (
    (KIND_STORY, ('stories_wip', 'stories_review')),
    (KIND_FEATURE, ('features_building', 'features_review')),
)

# Our column label ← the row's `usage` key. The ORDER is `ledger.USAGE_FIELDS`,
# so a field added there appears here rather than being silently dropped; only
# the display name lives in this file.
USAGE_KEYS = tuple(name for name, _ in ledger.USAGE_FIELDS)
USAGE_LABELS = {'input': 'in', 'output': 'out',
                'cache_creation': 'cache_create', 'cache_read': 'cache_read'}

# The two summed keys a dispatch row carries outside `usage`.
COUNT_KEYS = ('tool_calls', 'duration_s')

# The columns every spend table opens with, before the per-state ones.
SPEND_COLUMNS = ('dispatches',) + tuple(
    USAGE_LABELS[key] for key in USAGE_KEYS) + COUNT_KEYS
GRAIN_COLUMN = 'grain'
SIZE_COLUMN = 'size'
TOTAL_COLUMN = 'total_s'
NO_GRAIN_TITLE = 'rows naming no grain'

LEFT, RIGHT = 'left', 'right'


class Grain(NamedTuple):
    """One story, feature or bug under the milestone, as the TREE holds it."""
    gid: str
    kind: str
    size: str


class Section(NamedTuple):
    """One of the milestone's five questions: its data, and its lines.

    The registry below holds one entry per section and `build`/`render` walk
    it, so section 2 (yield), 3 (rework), 4 (escapes) and 5 (overhead shape)
    are each ONE pair of functions and one row here — never another branch
    inside this one. Section 1 is all that ships in this story.
    """
    name: str
    data: Callable[[model.PmConfig, str, Path, list], dict]
    lines: Callable[[model.PmConfig, dict], list[str]]


# --- the numbers --------------------------------------------------------------
def _blank() -> dict:
    """An accumulator that has seen nothing. Every sum starts ABSENT, not 0."""
    return {'dispatches': 0, 'usage': {key: None for key in USAGE_KEYS},
            'tool_calls': None, 'duration_s': None}


def _plus(running: int | None, value: object) -> int | None:
    """`running` plus `value`, where an absent or unreadable value adds nothing.

    The asymmetry is the point: `None + absent` stays None (nobody counted),
    `None + 5` is 5, and `0 + absent` stays 0 (somebody counted none). A value
    that is not an integer — a hand-edited row, a shape a later version
    writes — is treated as absent rather than crashing the report or being
    coerced: exit 2 is reserved for a line that will not PARSE, and no number
    in a ledger is ever this module's reason to fail.
    """
    if isinstance(value, bool) or not isinstance(value, int):
        return running
    return value if running is None else running + value


def _add(acc: dict, row: dict) -> None:
    """Fold one dispatch row into an accumulator. One row, counted once."""
    acc['dispatches'] += 1
    usage = row.get('usage')
    usage = usage if isinstance(usage, dict) else {}
    for key in USAGE_KEYS:
        acc['usage'][key] = _plus(acc['usage'][key], usage.get(key))
    for key in COUNT_KEYS:
        acc[key] = _plus(acc[key], row.get(key))


# --- the tree -----------------------------------------------------------------
def _grain(path: Path, kind: str, fallback: str) -> Grain:
    """One grain document as a row: its own id, its kind, its `size:`.

    The id is the file's OWN claim, the same one `_ledger_id` writes into every
    row — that is what a report joins on. A grain whose frontmatter carries no
    `id:` (the drift V2 reports) still gets a row, under the id its PATH spells,
    because a grain missing from the table reads as a grain that never existed.
    """
    gid = model.unquote(model.field_of(path, 'id')) or fallback
    return Grain(gid, kind, model.field_of(path, SIZE_FIELD))


def _bug_slug(mdir: Path, path: Path) -> str:
    """`bugs/` is walked recursively, so a bug's slug may carry a directory."""
    return path.relative_to(mdir / 'bugs').with_suffix('').as_posix()


def walk_grains(cfg: model.PmConfig, mid: str,
                mdir: Path) -> tuple[list[Grain], dict[str, set[str]]]:
    """Every grain under the milestone, and which stories each feature owns.

    The walkers are `check pm`'s and `pm status`'s, so the report's census and
    the gate's cannot disagree about what is in the tree.
    """
    grains: list[Grain] = []
    owned: dict[str, set[str]] = {}
    for ffile in model.feature_files(mdir):
        feature = _grain(ffile, KIND_FEATURE, f'{mid}/{ffile.parent.name}')
        grains.append(feature)
        stories = set()
        for sfile in model.story_files(ffile):
            slug = model.story_slug_of(cfg, sfile.stem)
            story = _grain(sfile, KIND_STORY, f'{feature.gid}/{slug}')
            grains.append(story)
            stories.add(story.gid)
        owned[feature.gid] = stories
    for bfile in model.bug_files(mdir):
        grains.append(_grain(bfile, KIND_BUG,
                             f'{mid}/bugs/{_bug_slug(mdir, bfile)}'))
    return grains, owned


def named_grains(row: dict, kinds: dict[str, str],
                 owned: dict[str, set[str]]) -> set[str]:
    """The grains under THIS milestone that one dispatch row's `tree` names.

    D3 put every live candidate on the row and left the rule here, so the rule
    is spelled once and re-derivable: a story is named by being `wip` or at
    `review`, a feature by being `building`/at `review` OR by owning a named
    story. An id in the snapshot that is not a grain of this milestone (a
    parallel milestone's story) names nothing here, and a row that names
    nothing is not dropped — it is counted in the trailing block.

    A row naming SEVERAL grains is added to each of them whole. Splitting one
    dispatch's tokens across two stories would be a weight, and D5 says the
    report does not weight; the per-grain columns therefore sum to MORE than
    the totals line, which counts every row exactly once.
    """
    tree = row.get('tree')
    if not isinstance(tree, dict):
        return set()
    named: set[str] = set()
    for kind, buckets in DISPATCH_BUCKETS:
        for bucket in buckets:
            ids = tree.get(bucket)
            for gid in ids if isinstance(ids, list) else ():
                if kinds.get(gid) == kind:
                    named.add(gid)
    for fid, stories in owned.items():
        if stories & named:
            named.add(fid)
    return named


# --- the clock ----------------------------------------------------------------
def state_columns(cfg: model.PmConfig, kind: str) -> tuple[str, ...]:
    """Every state of the kind's vocabulary except the terminal one, in order.

    EVERY one, not the ones before it in the tuple: a vocabulary is a closed
    SET with no transition graph, so its ORDER is a reading order and never a
    claim about which states a grain passes through. Stock: `todo wip review
    blocked` for a story, `planning ready building review` for a feature, `open
    fixed` for a bug. Time stuck in `blocked` is the question this section
    exists to answer (Chris, 2026-09-03: *"figure out which ones are taking the
    most time"*), and it sits PAST `done` in the tuple — a column set cut at
    the terminal state would have dropped exactly the number worth looking at.

    The terminal state alone has no column: it is where the grain ENDED, so
    the seconds after it are a running clock rather than a duration, and
    `total_s` beside these columns is the span that ends there.
    `ledger.terminal_state` is the one home for which state that is, so the
    columns and the total cannot come to different answers. A vocabulary that
    does not contain its terminal state at all (a consumer without `done`)
    gets a column for every state rather than none.

    A grain that RE-ENTERED a state — reopened, unblocked and blocked again —
    sums both stints into the one column. That is addition over the rows the
    ledger already holds, and the stints themselves are `pm ledger show`.
    """
    states = {KIND_STORY: cfg.story_states, KIND_FEATURE: cfg.feature_states,
              KIND_BUG: cfg.bug_states}[kind]
    terminal = ledger.terminal_state(cfg, kind)
    return tuple(state for state in states if state != terminal)


def state_seconds(rows: list) -> dict[str, int]:
    """Seconds in each state, by subtraction over consecutive status rows.

    The interval between two rows belongs to the state the EARLIER one moved
    to. The time before the first row is not measured (nobody recorded when the
    grain came into being) and the time after the last one is not a duration —
    a running clock has no end — which is the rule `pm ledger show` prints its
    per-row gaps by. A row whose `ts` will not parse contributes no arithmetic;
    a fabricated interval is worse than a missing one.
    """
    seconds: dict[str, int] = {}
    for earlier, later in zip(rows, rows[1:]):
        state = earlier.data.get('to')
        start = ledger.parse_ts(earlier.data.get('ts'))
        end = ledger.parse_ts(later.data.get('ts'))
        if not isinstance(state, str) or not state or None in (start, end):
            continue
        seconds[state] = seconds.get(state, 0) + int(
            (end - start).total_seconds())
    return seconds


def total_seconds(cfg: model.PmConfig, kind: str, rows: list,
                  status: list) -> int | None:
    """First row → terminal row, or None while the grain is still in flight.

    The same subtraction `pm ledger show` prints as its total line, over the
    same row set (every row that NAMES the grain, `show`'s rule), so one grain
    cannot have two durations depending on which verb asked.
    """
    if not rows or not status:
        return None
    if status[-1].data.get('to') != ledger.terminal_state(cfg, kind):
        return None
    start = ledger.parse_ts(rows[0].data.get('ts'))
    end = ledger.parse_ts(status[-1].data.get('ts'))
    if start is None or end is None:
        return None
    return int((end - start).total_seconds())


# --- section 1: spend per grain -----------------------------------------------
def spend_data(cfg: model.PmConfig, mid: str, mdir: Path,
               rows: list) -> dict:
    """Section 1 as data: one entry per grain, the strays, and the totals."""
    grains, owned = walk_grains(cfg, mid, mdir)
    kinds = {g.gid: g.kind for g in grains}
    dispatch = [r for r in rows if r.data.get('kind') == ledger.KIND_DISPATCH]
    status = [r for r in rows if r.data.get('kind') == ledger.KIND_STATUS]
    per_grain = {g.gid: _blank() for g in grains}
    per_type: dict[str, dict[str | None, dict]] = {g.gid: {} for g in grains}
    unattributed, totals = _blank(), _blank()
    for row in dispatch:
        # Every row lands in the totals exactly once, whether or not it names
        # a grain — so the summary line is a statement about the FILE.
        _add(totals, row.data)
        named = named_grains(row.data, kinds, owned)
        if not named:
            _add(unattributed, row.data)
            continue
        agent = row.data.get('agent_type')
        agent = agent if isinstance(agent, str) and agent else None
        for gid in named:
            _add(per_grain[gid], row.data)
            _add(per_type[gid].setdefault(agent, _blank()), row.data)
    out = []
    for grain in sorted(grains, key=lambda g: (KIND_ORDER.index(g.kind),
                                               g.gid)):
        names = {grain.gid}
        mine = [r for r in rows if ledger.row_names(r.data, names)]
        my_status = [r for r in status if r.data.get('grain') in names]
        seconds = state_seconds(my_status)
        out.append({
            'grain': grain.gid, 'kind': grain.kind,
            'size': grain.size or None,
            **per_grain[grain.gid],
            'agent_types': [{'agent_type': agent, **spend}
                            for agent, spend in sorted(
                                per_type[grain.gid].items(),
                                key=lambda kv: (kv[0] is None, kv[0] or ''))],
            'states': {state: seconds.get(state)
                       for state in state_columns(cfg, grain.kind)},
            'total_s': total_seconds(cfg, grain.kind, mine, my_status),
        })
    return {'section': SECTION_SPEND, 'grains': out,
            'unattributed': unattributed,
            'totals': {'dispatch_rows': len(dispatch),
                       'status_rows': len(status), 'grains': len(grains),
                       **{k: v for k, v in totals.items()
                          if k != 'dispatches'}}}


def _cell(value: object) -> str:
    """One number as a cell: the integer, or `-` when nobody recorded it."""
    return DASH if value is None else str(value)


def _table(title: str, headers: tuple[str, ...], aligns: tuple[str, ...],
           rows: list[tuple[str, ...]]) -> list[str]:
    """One `-- <title> (n)` block, columns padded to their widest cell.

    The heading prints even when there are no rows: a census that says `(0)`
    is a fact, and silence there is the one thing that reads the same as a
    scan that never happened (hard rule 4).
    """
    lines = [f'{BLOCK_PREFIX} {title}']
    if not rows:
        return lines
    widths = [max(len(header), *(len(row[i]) for row in rows))
              for i, header in enumerate(headers)]
    for cells in [headers, *rows]:
        lines.append(COLUMN_GAP.join(
            cell.ljust(width) if align == LEFT else cell.rjust(width)
            for cell, align, width in zip(cells, aligns, widths)).rstrip())
    return lines


def _spend_cells(entry: dict) -> tuple[str, ...]:
    """The columns every spend row shares: dispatches, four sums, two counts."""
    return (_cell(entry['dispatches']),
            *(_cell(entry['usage'][key]) for key in USAGE_KEYS),
            *(_cell(entry[key]) for key in COUNT_KEYS))


def spend_lines(cfg: model.PmConfig, data: dict) -> list[str]:
    """Section 1 as lines: a heading, one table per kind, the strays, a total."""
    totals = data['totals']
    out = [f'{HEADING_PREFIX} {data["milestone"]} — {SPEND_TITLE} — '
           f'{totals["dispatch_rows"]} dispatch row(s), '
           f'{totals["status_rows"]} status row(s), '
           f'{totals["grains"]} grain(s)']
    for kind in KIND_ORDER:
        entries = [e for e in data['grains'] if e['kind'] == kind]
        states = state_columns(cfg, kind)
        headers = (GRAIN_COLUMN, SIZE_COLUMN, *SPEND_COLUMNS, *states,
                   TOTAL_COLUMN)
        aligns = (LEFT, LEFT) + (RIGHT,) * (len(headers) - 2)
        rows: list[tuple[str, ...]] = []
        for entry in entries:
            rows.append((entry['grain'], entry['size'] or '',
                         *_spend_cells(entry),
                         *(_cell(entry['states'][state]) for state in states),
                         _cell(entry['total_s'])))
            # One agent type is the grain's own row said twice; the split is
            # printed only where there is something to split.
            if len(entry['agent_types']) > 1:
                for split in entry['agent_types']:
                    rows.append((
                        f'{SUB_ROW_INDENT}{split["agent_type"] or DASH}', '',
                        *_spend_cells(split), *('',) * (len(states) + 1)))
        out.append('')
        out.extend(_table(f'{kind} ({len(entries)})', headers, aligns, rows))
    stray = data['unattributed']
    out.append('')
    out.extend(_table(f'{NO_GRAIN_TITLE} ({stray["dispatches"]})',
                      SPEND_COLUMNS, (RIGHT,) * len(SPEND_COLUMNS),
                      [_spend_cells(stray)] if stray['dispatches'] else []))
    out.append('')
    out.append(f'{HEADING_PREFIX} {data["milestone"]} — '
               f'{_cell(totals["usage"]["output"])} out / '
               f'{_cell(totals["tool_calls"])} tool calls / '
               f'{_cell(totals["duration_s"])} s across '
               f'{totals["dispatch_rows"]} dispatch row(s)')
    return out


# The registry section 2 extends: one row per question, one pair of functions.
SECTIONS = (Section(SECTION_SPEND, spend_data, spend_lines),)


def build(cfg: model.PmConfig, mid: str, mdir: Path, rows: list) -> dict:
    """The whole report as ONE object — what `--json` prints, verbatim.

    Every section contributes its own keys; `section` names the one this
    release ships. Adding sections 2-5 changes that key to a list, and that is
    an output-format change — a minor bump, hard rule 6 — not a patch.
    """
    out: dict = {'milestone': mid}
    for section in SECTIONS:
        out.update(section.data(cfg, mid, mdir, rows))
    return out


def render(cfg: model.PmConfig, data: dict) -> list[str]:
    """The whole report as lines, in section order."""
    lines: list[str] = []
    for section in SECTIONS:
        lines.extend(section.lines(cfg, data))
    return lines
