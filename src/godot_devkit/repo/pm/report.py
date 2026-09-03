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

Exit codes are the CLI's, and this module can fail in exactly two ways, both
of them about a document that will not PARSE and neither of them about a
number: a `ledger.LedgerError` from a ledger line, and a `RecordError` from a
review record whose verdict block exists and cannot be read correctly. A
record with no block at all is neither — it is listed, by name, as a pass
nobody wrote a block for.
"""
from __future__ import annotations

from collections.abc import Callable, Iterable
from pathlib import Path
from typing import NamedTuple

from godot_devkit.repo.pm import ledger, model, verdict

# The two line shapes a consumer greps (hard rule 6): the heading and the
# summary. Both carry the milestone id, so a report of two milestones
# concatenated is still attributable line by line.
HEADING_PREFIX = '[ledger:report]'

# What a section calls itself in `--json` and in its own heading. The five
# questions of `pm/roadmap/<ms>/milestone.md`, in the order it asks them.
SECTION_SPEND = 'spend'
SPEND_TITLE = 'spend per grain'
SECTION_YIELD = 'yield'
YIELD_TITLE = 'yield per review pass'
SECTION_REWORK = 'rework'
REWORK_TITLE = 'rework'
SECTION_ESCAPES = 'escapes'
ESCAPES_TITLE = 'escapes'
SECTION_OVERHEAD = 'overhead'
OVERHEAD_TITLE = 'overhead shape'

# Printed for a NUMBER nobody recorded. A blank cell would read as zero at a
# glance and a `0` would BE a lie; `-` is the third thing, and it is the same
# character `pm list` already prints for an unowned story.
DASH = '-'

# The milestone has no `ledger.jsonl` at all — no rows have ever been written
# for it. A fact, not a failure: exit 0, one line, no table of dashes.
NO_LEDGER = 'no ledger'

# A section that found nothing to count. One line, never a table of zeros: a
# `0` in a column is a measurement, and a grid of them under a heading reads
# as one — which is the same lie an empty census printing PASS tells.
NO_DATA = 'no data'

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

# Section 2's columns and block titles. `verdict.DISPOSITION_KINDS` supplies
# the three disposition columns, so a fourth kind added there appears here
# rather than being counted into nothing.
FEATURE_COLUMN = 'feature'
RECORD_COLUMN = 'record'
VERDICT_COLUMN = 'verdict'
FINDINGS_COLUMN = 'findings'
SEVERITY_COLUMN = 'severity'
TARGET_COLUMN = 'target'
VERDICT_TITLE = 'verdict'
SEVERITY_TITLE = 'findings by severity'
DEFERRED_TITLE = 'deferred to'

# Section 3's. The two story states a reopen is made of are NAMED, and checked
# against the configured vocabulary before the column is filled: a project that
# renamed either gets `-`, because a `0` would say "nothing was reopened" about
# a transition this rule cannot see.
REVIEW_STATE = 'review'
WIP_STATE = 'wip'
STORY_COLUMN = 'story'
REOPENS_COLUMN = 'reopens'
AFTER_REVIEW_COLUMN = 'after_review'
RECORDS_COLUMN = 'records'
REOPEN_TITLE = 'story'
DISTRIBUTION_TITLE = 'verdict distribution'

# Section 4's. `caused_by:` is the bug frontmatter field the review-record
# feature added; `caught_in:` is a different fact and is not read here.
CAUSED_BY_FIELD = 'caused_by'
CAUSE_COLUMN = 'caused_by'
BUG_COLUMN = 'bug'
STATUS_COLUMN = 'status'
FEATURE_STATUS_COLUMN = 'feature_status'
ESCAPE_TITLE = 'bugs naming a cause'

# Section 5's. The three row keys it reads by name, and the separator that
# turns the per-dispatch list into one cell.
BEFORE_WRITE_KEY = 'tool_calls_before_first_write'
TOOL_CALLS_KEY = 'tool_calls'
OUTPUT_KEY = 'output'
LIST_SEPARATOR = ','
DISPATCHES_COLUMN = 'dispatches'
BEFORE_WRITE_COLUMN = 'before_first_write'
CALLS_COLUMN = 'calls'
DECISIONS_COLUMN = 'decisions'
ENTRY_COLUMN = 'entry'
TS_COLUMN = 'ts'
NEXT_STATUS_COLUMN = 'next_status_s'
SESSION_COLUMN = 'session_id'
# The delta columns are HEADED by the keys they diff — `out` is section 1's
# spelling of `usage.output`, taken from its table rather than respelled, so a
# reader comparing the two sections is reading one word.
OUT_DELTA_COLUMN = USAGE_LABELS[OUTPUT_KEY]
TOOL_CALLS_COLUMN = TOOL_CALLS_KEY
BEFORE_WRITE_TITLE = 'story'
DECISION_COUNT_TITLE = 'decisions per grain'
DECISION_GAP_TITLE = 'decision to next status row'
SESSION_TITLE = 'session deltas'

LEFT, RIGHT = 'left', 'right'


class Grain(NamedTuple):
    """One story, feature or bug under the milestone, as the TREE holds it."""
    gid: str
    kind: str
    size: str


class Section(NamedTuple):
    """One of the milestone's five questions: its data, and its lines.

    The registry at the foot of this file holds one entry per section and
    `build`/`render` walk it, so section 1 (spend), 2 (yield), 3 (rework), 4
    (escapes) and 5 (overhead shape) are each ONE pair of functions and one row
    there — never another branch inside one of them. `data` returns the
    section's own keys and `lines` reads the WHOLE object back, so a section
    may print a number another section computed and none of them may recompute
    one.
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


# --- the review records (sections 2 and 3) ------------------------------------
# Where one feature's record is, in the order this looks: the `reviewed:`
# pointer `model.review_record_for` resolves — the mechanism `check pm` and
# `pm validate` already own, including the slug fallback a project may turn on
# — and then `features/<slug>/review.md` beside the feature document, the slot
# `pm new` scaffolds and `model.FEATURE_OPTIONAL_SLOTS` names. Not a guess and
# not a search: two named slots, tried in one order, and the table PRINTS the
# path it read, so a reader never has to ask which of the two answered.
NO_VERDICT = 'no verdict block'


class RecordError(Exception):
    """A review record whose verdict block will not parse. Names record + line.

    The one refusal sections 2-5 make on content, and it is not a number. A
    block that EXISTS and cannot be read correctly (`verdict.MalformedVerdict`)
    reported as a yield of nothing would be hard rule 4's read-side sin with a
    column header on it — a pass that raised five findings printed as a pass
    that raised none. A record with NO block is the other thing entirely: that
    is `verdict.NoVerdict`, it is a fact about the pass, and it is listed.
    """


def review_records(cfg: model.PmConfig, mid: str,
                   mdir: Path) -> list[tuple[str, str, Path]]:
    """(feature id, the path as the report prints it, the path) per record."""
    out: list[tuple[str, str, Path]] = []
    for ffile in model.feature_files(mdir):
        fid = (model.unquote(model.field_of(ffile, 'id'))
               or f'{mid}/{ffile.parent.name}')
        rel = model.review_record_for(cfg, fid)
        path = (cfg.root / rel) if rel else None
        if path is None:
            beside = ffile.parent / model.REVIEW_FILE_NAME
            if beside.is_file():
                path, rel = beside, cfg.rel(beside)
        if path is not None and rel is not None:
            out.append((fid, rel, path))
    # By feature id, not by the order the walker returned: the table's order
    # is a contract of this file, and a walker's is a fact about a filesystem.
    out.sort(key=lambda found: found[0])
    return out


def parsed_records(cfg: model.PmConfig, mid: str,
                   mdir: Path) -> list[tuple[str, str, object]]:
    """Every record, parsed: `None` in the third slot when it carries no block.

    Sections 2 and 3 both call this and both parse the same handful of files.
    That is the registry's shape holding — one section is one pair of functions
    over the tree and the rows, never a pipeline stage that has to run first —
    and re-reading a record cannot produce two answers, because `verdict.parse`
    is the only reader either of them has.
    """
    out: list[tuple[str, str, object]] = []
    for fid, rel, path in review_records(cfg, mid, mdir):
        try:
            text = model.read_raw(path)
        except (OSError, UnicodeDecodeError) as err:
            raise RecordError(f'{rel} could not be read ({err})') from err
        try:
            out.append((fid, rel, verdict.parse(text)))
        except verdict.NoVerdict:
            out.append((fid, rel, None))
        except verdict.MalformedVerdict as err:
            raise RecordError(f'{rel}: line {err.lineno}: {err.why}\n'
                              f'    {err.line}') from err
    return out


def _tally(values: Iterable) -> dict:
    """Count per distinct value. The only thing this module does to a label."""
    counts: dict = {}
    for value in values:
        counts[value] = counts.get(value, 0) + 1
    return counts


def _section(mid: str, title: str, census: str,
             blocks: list[tuple[str, tuple, tuple, list]]) -> list[str]:
    """One section: its heading, then its blocks — or ONE line when it has none.

    `no data` rather than a table of zeros is the story's gotcha, and it is the
    same distinction the columns keep: a section with nothing in it has not
    measured zero of anything, and a grid of `0`s would read as if it had.
    Inside a section that DID find rows, an empty block still prints its
    `-- <title> (0)` heading, exactly as section 1's do — there the census is
    beside the blocks that have content, so it says "and none of these".
    """
    out = ['', f'{HEADING_PREFIX} {mid} — {title} — {census}']
    if not any(rows for _, _, _, rows in blocks):
        out.append(NO_DATA)
        return out
    for btitle, headers, aligns, rows in blocks:
        out.append('')
        out.extend(_table(btitle, headers, aligns, rows))
    return out


# --- section 2: yield per review pass -----------------------------------------
def yield_data(cfg: model.PmConfig, mid: str, mdir: Path,
               rows: list) -> dict:
    """Section 2 as data: one entry per review record under the milestone.

    Counting only, over the block's own closed sets: findings per severity,
    dispositions per kind, deferrals per target grain. The disposition is read
    as `disposition_kind` and NEVER as the shape of its value — `landed <hash>`
    and `landed in-place` are one column, because a reviewer in this SDLC fixes
    in place and never commits (SDLC § 2), so counting only the hash form would
    under-count exactly the findings that were acted on.

    Spend is NOT joined in here. Section 1 already splits every grain's tokens
    by `agent_type`, and picking the types that are "reviewer-shaped" out of
    that split would be a LABEL over an open set of agent names (D5) — the one
    thing this module may not do. The reviewer's spend is in section 1, under
    the feature, beside its own agent type.
    """
    records = []
    for fid, rel, parsed in parsed_records(cfg, mid, mdir):
        entry = {'feature': fid, 'record': rel, 'verdict': None,
                 'findings': None, 'severities': {}, 'deferred': [],
                 'dispositions': {kind: None
                                  for kind in verdict.DISPOSITION_KINDS}}
        if parsed is not None:
            found = parsed.findings
            entry['verdict'] = parsed.verdict
            entry['findings'] = len(found)
            entry['severities'] = {
                sev: n for sev, n in
                sorted(_tally(f.severity for f in found).items(),
                       key=lambda kv: verdict.SEVERITIES.index(kv[0]))}
            entry['dispositions'] = {
                kind: sum(1 for f in found if f.disposition_kind == kind)
                for kind in verdict.DISPOSITION_KINDS}
            entry['deferred'] = [
                {'target': target, 'findings': n} for target, n in
                sorted(_tally(f.disposition_value for f in found
                              if f.disposition_kind == verdict.DEFERRED
                              ).items())]
        records.append(entry)
    return {SECTION_YIELD: {
        'records': records,
        'totals': {'records': len(records),
                   'findings': sum(r['findings'] or 0 for r in records)}}}


def yield_lines(cfg: model.PmConfig, data: dict) -> list[str]:
    """Section 2 as lines: the pass, its severities, and where it deferred."""
    section = data[SECTION_YIELD]
    records = section['records']
    passes = [(r['feature'], r['record'], r['verdict'] or NO_VERDICT,
               _cell(r['findings']),
               *(_cell(r['dispositions'][kind])
                 for kind in verdict.DISPOSITION_KINDS))
              for r in records]
    severities = [(r['feature'], sev, str(n))
                  for r in records for sev, n in r['severities'].items()]
    deferred = sorted((d['target'], r['feature'], str(d['findings']))
                      for r in records for d in r['deferred'])
    totals = section['totals']
    return _section(
        data['milestone'], YIELD_TITLE,
        f'{totals["records"]} record(s), {totals["findings"]} finding(s)',
        [(f'{VERDICT_TITLE} ({len(passes)})',
          (FEATURE_COLUMN, RECORD_COLUMN, VERDICT_COLUMN, FINDINGS_COLUMN,
           *verdict.DISPOSITION_KINDS),
          (LEFT, LEFT, LEFT) + (RIGHT,) * (1 + len(verdict.DISPOSITION_KINDS)),
          passes),
         (f'{SEVERITY_TITLE} ({len(severities)})',
          (FEATURE_COLUMN, SEVERITY_COLUMN, FINDINGS_COLUMN),
          (LEFT, LEFT, RIGHT), severities),
         (f'{DEFERRED_TITLE} ({len(deferred)})',
          (TARGET_COLUMN, FEATURE_COLUMN, FINDINGS_COLUMN),
          (LEFT, LEFT, RIGHT), deferred)])


# --- section 3: rework --------------------------------------------------------
def _after(row, moment) -> bool:
    """True when this row's stamp is later than `moment`, and it parses."""
    ts = ledger.parse_ts(row.data.get('ts'))
    return ts is not None and ts > moment


def rework_data(cfg: model.PmConfig, mid: str, mdir: Path,
                rows: list) -> dict:
    """Section 3 as data: reopens, dispatches after review, verdict spread.

    A reopen is one status row: `from` the review state, `to` the working one.
    Both names are read out of the story vocabulary rather than assumed — a
    project that renamed either gets `-` in that column and never a `0`, since
    a zero there would say "nothing was reopened" about a machine this rule
    cannot see (hard rule 4).

    "After review" counts DISPATCH rows, by D3's snapshot and the same
    `named_grains` rule section 1 attributes by — so the two sections cannot
    disagree about which dispatches were a story's. The moment compared against
    is the story's FIRST row into the review state; a story that never reached
    it has no such moment, and `-` is the honest column.
    """
    grains, owned = walk_grains(cfg, mid, mdir)
    kinds = {g.gid: g.kind for g in grains}
    status = [r for r in rows if r.data.get('kind') == ledger.KIND_STATUS]
    dispatch = [r for r in rows if r.data.get('kind') == ledger.KIND_DISPATCH]
    reopenable = (REVIEW_STATE in cfg.story_states
                  and WIP_STATE in cfg.story_states)
    feature_of = {sid: fid for fid, sids in owned.items() for sid in sids}
    out = []
    for grain in sorted((g for g in grains if g.kind == KIND_STORY),
                        key=lambda g: g.gid):
        mine = [r for r in status if r.data.get('grain') == grain.gid]
        reopens = None
        if mine and reopenable:
            reopens = sum(1 for r in mine
                          if r.data.get('from') == REVIEW_STATE
                          and r.data.get('to') == WIP_STATE)
        moment = next((ts for ts in
                       (ledger.parse_ts(r.data.get('ts')) for r in mine
                        if r.data.get('to') == REVIEW_STATE)
                       if ts is not None), None)
        after = None if moment is None else sum(
            1 for r in dispatch
            if grain.gid in named_grains(r.data, kinds, owned)
            and _after(r, moment))
        out.append({'grain': grain.gid, 'feature': feature_of.get(grain.gid),
                    'reopens': reopens, 'after_review': after})
    spread = _tally(parsed.verdict
                    for _, _, parsed in parsed_records(cfg, mid, mdir)
                    if parsed is not None)
    reopened = [e['reopens'] for e in out if e['reopens'] is not None]
    return {SECTION_REWORK: {
        'stories': out,
        'verdicts': [{'verdict': name, 'records': spread[name]}
                     for name in verdict.VERDICTS if name in spread],
        'totals': {'stories': len(out),
                   'reopens': sum(reopened) if reopened else None,
                   'records': sum(spread.values())}}}


def rework_lines(cfg: model.PmConfig, data: dict) -> list[str]:
    """Section 3 as lines: one row per story, one per verdict that was given."""
    section = data[SECTION_REWORK]
    stories = [(e['feature'] or DASH, e['grain'], _cell(e['reopens']),
                _cell(e['after_review'])) for e in section['stories']]
    spread = [(v['verdict'], str(v['records'])) for v in section['verdicts']]
    totals = section['totals']
    return _section(
        data['milestone'], REWORK_TITLE,
        f'{totals["stories"]} story(s), {_cell(totals["reopens"])} reopen(s), '
        f'{totals["records"]} record(s) with a verdict',
        [(f'{REOPEN_TITLE} ({len(stories)})',
          (FEATURE_COLUMN, STORY_COLUMN, REOPENS_COLUMN, AFTER_REVIEW_COLUMN),
          (LEFT, LEFT, RIGHT, RIGHT), stories),
         (f'{DISTRIBUTION_TITLE} ({len(spread)})',
          (VERDICT_COLUMN, RECORDS_COLUMN), (LEFT, RIGHT), spread)])


# --- section 4: escapes -------------------------------------------------------
def escapes_data(cfg: model.PmConfig, mid: str, mdir: Path,
                 rows: list) -> dict:
    """Section 4 as data: every bug here whose `caused_by:` names a feature.

    Grouped by the id the bug NAMES, resolved wherever it lives — an escape's
    cause is usually a feature of an earlier milestone, and a cause that
    resolves to nothing (retired, or a typo `pm validate` reports) still gets
    its row with `-` in the feature's column. The feature's own `status:` is
    copied verbatim from the tree at report time; whether that word is the
    terminal one is the reader's question, and `feature_done` answers it in
    `--json` as the equality it is. Neither is a judgement about the bug.
    """
    out = []
    for bfile in model.bug_files(mdir):
        cause = model.field_of(bfile, CAUSED_BY_FIELD)
        if not cause:
            continue
        gid = (model.unquote(model.field_of(bfile, 'id'))
               or f'{mid}/bugs/{_bug_slug(mdir, bfile)}')
        ffile = model.feature_file(cfg, cause)
        fstatus = model.field_of(ffile, 'status') if ffile is not None else ''
        out.append({
            'caused_by': cause, 'bug': gid,
            'status': model.field_of(bfile, 'status') or None,
            'feature_status': fstatus or None,
            'feature_done': (None if not fstatus
                             else fstatus == ledger.TERMINAL_STATE)})
    out.sort(key=lambda e: (e['caused_by'], e['bug']))
    return {SECTION_ESCAPES: {
        'bugs': out,
        'totals': {'bugs': len(out),
                   'features': len({e['caused_by'] for e in out})}}}


def escapes_lines(cfg: model.PmConfig, data: dict) -> list[str]:
    """Section 4 as lines: cause, bug, the bug's state, the feature's."""
    section = data[SECTION_ESCAPES]
    bugs = [(e['caused_by'], e['bug'], _cell(e['status']),
             _cell(e['feature_status'])) for e in section['bugs']]
    totals = section['totals']
    return _section(
        data['milestone'], ESCAPES_TITLE,
        f'{totals["bugs"]} bug(s) naming a cause, '
        f'{totals["features"]} feature(s)',
        [(f'{ESCAPE_TITLE} ({len(bugs)})',
          (CAUSE_COLUMN, BUG_COLUMN, STATUS_COLUMN, FEATURE_STATUS_COLUMN),
          (LEFT, LEFT, LEFT, LEFT), bugs)])


# --- section 5: overhead shape ------------------------------------------------
def _int(value: object) -> int | None:
    """The integer on the row, or None for anything that is not one."""
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _delta(earlier: object, later: object) -> int | None:
    """`later - earlier`, or None unless BOTH ends are integers.

    A delta over one measured end and one absent one would be the absent end
    read as zero — the whole reading of a cumulative session row inverted.
    """
    a, b = _int(earlier), _int(later)
    return None if a is None or b is None else b - a


def _usage_of(row: dict, key: str) -> object:
    usage = row.get('usage')
    return usage.get(key) if isinstance(usage, dict) else None


def overhead_data(cfg: model.PmConfig, mid: str, mdir: Path,
                  rows: list) -> dict:
    """Section 5 as data: looking before writing, deciding, and stopping.

    Three counts and one subtraction, and the attribution of each is named:

      * a story's dispatches are D3's snapshot, `named_grains`, section 1's
        rule — and `tool_calls_before_first_write` is SUMMED and also LISTED,
        because one dispatch that looked at 90 files and nine that looked at
        ten are the same sum and not the same shape;
      * a decision row counts against the grain its own `grain` field names.
        `pm decide` writes a FEATURE id for a feature's `decisions.md` and the
        MILESTONE id for the milestone's, so those are the two rows the block
        holds — a milestone-grained decision is never divided among features
        (that would be a weight) and never attributed to one (that would be a
        guess);
      * the seconds after a decision are the gap to the next status row of any
        grain in that decision's scope — the feature and its stories for a
        feature-grained row, every grain under the milestone for a
        milestone-grained one. `-` when no status row follows it.

    Session rows are diffed per `session_id` and nothing else: consecutive
    stops carry cumulative totals (D4), so the delta is what the turn cost, and
    which grain it was about is a question this row cannot answer.
    """
    grains, owned = walk_grains(cfg, mid, mdir)
    kinds = {g.gid: g.kind for g in grains}
    dispatch = [r for r in rows if r.data.get('kind') == ledger.KIND_DISPATCH]
    status = [r for r in rows if r.data.get('kind') == ledger.KIND_STATUS
              and isinstance(r.data.get('grain'), str)]
    decisions = [r for r in rows if r.data.get('kind') == ledger.KIND_DECISION]
    sessions = [r for r in rows if r.data.get('kind') == ledger.KIND_SESSION]

    stories = []
    for grain in sorted((g for g in grains if g.kind == KIND_STORY),
                        key=lambda g: g.gid):
        mine = [r for r in dispatch
                if grain.gid in named_grains(r.data, kinds, owned)]
        calls = [n for n in (_int(r.data.get(BEFORE_WRITE_KEY)) for r in mine)
                 if n is not None]
        stories.append({'grain': grain.gid, 'dispatches': len(mine),
                        'before_first_write': sum(calls) if calls else None,
                        'calls': calls})

    scopes = {mid: {g.gid for g in grains} | {mid}}
    for fid, sids in owned.items():
        scopes[fid] = {fid} | sids
    # Every feature under the milestone, and the milestone itself — but only
    # once SOMETHING has been decided. A column of zeros under a ledger with no
    # decision row in it says nothing the census (`0 decision row(s)`) does not
    # already say, and it says it in the shape of a measurement.
    per_grain = ([{'grain': gid,
                   'decisions': sum(1 for r in decisions
                                    if r.data.get('grain') == gid)}
                  for gid in [mid, *sorted(owned)]] if decisions else [])
    events = []
    for row in decisions:
        gid = row.data.get('grain')
        gid = gid if isinstance(gid, str) else None
        scope = scopes.get(gid, {gid} if gid else set())
        moment = ledger.parse_ts(row.data.get('ts'))
        seconds = None
        if moment is not None:
            later = [ts for ts in (ledger.parse_ts(r.data.get('ts'))
                                   for r in status
                                   if r.data['grain'] in scope)
                     if ts is not None and ts > moment]
            if later:
                seconds = int((min(later) - moment).total_seconds())
        entry = row.data.get('entry')
        title = row.data.get('title')
        stamp = row.data.get('ts')
        events.append({'grain': gid,
                       'entry': entry if isinstance(entry, str) else None,
                       'title': title if isinstance(title, str) else None,
                       'ts': stamp if isinstance(stamp, str) else None,
                       'next_status_s': seconds})

    grouped: dict = {}
    for row in sessions:
        sid = row.data.get('session_id')
        grouped.setdefault(sid if isinstance(sid, str) and sid else None,
                           []).append(row)
    deltas = []
    for sid in sorted(grouped, key=lambda s: (s is None, s or '')):
        for earlier, later in zip(grouped[sid], grouped[sid][1:]):
            stamp = later.data.get('ts')
            deltas.append({
                'session_id': sid,
                'ts': stamp if isinstance(stamp, str) else None,
                'output': _delta(_usage_of(earlier.data, OUTPUT_KEY),
                                 _usage_of(later.data, OUTPUT_KEY)),
                'tool_calls': _delta(earlier.data.get(TOOL_CALLS_KEY),
                                     later.data.get(TOOL_CALLS_KEY))})
    return {SECTION_OVERHEAD: {
        'stories': stories, 'decisions': per_grain, 'gaps': events,
        'sessions': deltas,
        'totals': {'dispatch_rows': len(dispatch),
                   'decision_rows': len(decisions),
                   'session_rows': len(sessions)}}}


def overhead_lines(cfg: model.PmConfig, data: dict) -> list[str]:
    """Section 5 as lines: four blocks, one per thing the shape is made of."""
    section = data[SECTION_OVERHEAD]
    stories = [(e['grain'], str(e['dispatches']),
                _cell(e['before_first_write']),
                LIST_SEPARATOR.join(str(n) for n in e['calls']) or DASH)
               for e in section['stories']]
    decisions = [(e['grain'], str(e['decisions']))
                 for e in section['decisions']]
    gaps = [(_cell(e['grain']), _cell(e['entry']), _cell(e['ts']),
             _cell(e['next_status_s'])) for e in section['gaps']]
    deltas = [(_cell(e['session_id']), _cell(e['ts']), _cell(e['output']),
               _cell(e['tool_calls'])) for e in section['sessions']]
    totals = section['totals']
    return _section(
        data['milestone'], OVERHEAD_TITLE,
        f'{totals["dispatch_rows"]} dispatch row(s), '
        f'{totals["decision_rows"]} decision row(s), '
        f'{totals["session_rows"]} session row(s)',
        [(f'{BEFORE_WRITE_TITLE} ({len(stories)})',
          (STORY_COLUMN, DISPATCHES_COLUMN, BEFORE_WRITE_COLUMN, CALLS_COLUMN),
          (LEFT, RIGHT, RIGHT, LEFT), stories),
         (f'{DECISION_COUNT_TITLE} ({len(decisions)})',
          (GRAIN_COLUMN, DECISIONS_COLUMN), (LEFT, RIGHT), decisions),
         (f'{DECISION_GAP_TITLE} ({len(gaps)})',
          (GRAIN_COLUMN, ENTRY_COLUMN, TS_COLUMN, NEXT_STATUS_COLUMN),
          (LEFT, LEFT, LEFT, RIGHT), gaps),
         (f'{SESSION_TITLE} ({len(deltas)})',
          (SESSION_COLUMN, TS_COLUMN, OUT_DELTA_COLUMN, TOOL_CALLS_COLUMN),
          (LEFT, LEFT, RIGHT, RIGHT), deltas)])


# The registry: one row per question, one pair of functions each. A section is
# added HERE and nowhere else — never as another branch inside one of them.
SECTIONS = (Section(SECTION_SPEND, spend_data, spend_lines),
            Section(SECTION_YIELD, yield_data, yield_lines),
            Section(SECTION_REWORK, rework_data, rework_lines),
            Section(SECTION_ESCAPES, escapes_data, escapes_lines),
            Section(SECTION_OVERHEAD, overhead_data, overhead_lines))


def build(cfg: model.PmConfig, mid: str, mdir: Path, rows: list) -> dict:
    """The whole report as ONE object — what `--json` prints, verbatim.

    Every section contributes its own keys: section 1's sit at the top level
    (`section`, `grains`, `unattributed`, `totals` — the shape it shipped, kept
    byte-for-byte because a consumer already reads it), and sections 2-5 each
    add ONE key named for the question (`yield`, `rework`, `escapes`,
    `overhead`). Adding a key is an output-format change and so a minor bump
    (hard rule 6); removing or renaming one is not a thing this file does.
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
