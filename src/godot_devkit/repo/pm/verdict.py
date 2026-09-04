"""verdict.py — the machine-readable verdict block at the end of a review record.

A review record is prose written for a human. Exactly one thing in it is
written for a machine: a fenced block naming the pass's verdict and one row per
finding, with the severity it was graded and what was DONE about it.

    verdict: SHIP-WITH-FIXES
    | id | severity | disposition |
    | W1 | WARNING | landed 3a42f19ad |
    | S3 | SUGGESTION | rejected: pause regression |
    | D2 | DELTA | deferred: 0.90.3/throwable-as-behavior |
    | Q5 | QUESTION | open |

That block is what makes review YIELD computable — findings by severity and
disposition, per pass — without anyone tallying reports by hand. The four
reviewer-shaped agent definitions this package installs
(`reviewer`, `simplifier`, `milestone-reviewer`, `verification-reviewer`)
each carry the same paragraph instructing their author to emit it.

**Why a FENCE is part of the shape.** The corpus already contains prose verdict
lines — `**Verdict: RELEASE-WITH-FIXES**` heads two milestone records — and a
parser that read those would be reading the record's narration, the one source
this package's SDLC refuses to trust. The fence is what separates the claim the
report counts from the paragraph the human reads. An unfenced `verdict:` line
is therefore not a verdict block, and a record whose only verdict is in prose
honestly has none.

**Detection is generous; acceptance is strict.** Anything shaped like a verdict
block is DETECTED — the marker and every fixed keyword match case-insensitively,
cells are stripped, blank lines inside the block are ignored, and CRLF is fine.
Once detected, nothing is guessed: an unknown verdict, an unknown severity, a
row that is not exactly three cells, a disposition outside the three forms, a
second block, or a fence that never closes each raise `MalformedVerdict` naming
the line number and the offending line. The alternative — quietly reporting
"no verdict" over a block that was nearly right — is rule 4's read-side sin:
a miss that prints a clean number.

Two failures, deliberately different exceptions:

    NoVerdict         the record carries no block at all. A FACT about the
                      record, which the report LISTS; the caller must not
                      turn it into an error.
    MalformedVerdict  a block exists and cannot be read correctly. The caller
                      exits 2. Never a partial parse: no findings are returned
                      from a block with one bad row.

The closed sets below are the vocabulary in USE, not an invention. The verdicts
are the story's `SHIP` family plus the `RELEASE-SAFE` family the milestone
records and CLAUDE.md already use; the severities are the union of the grades
the four installed definitions actually ask their author to assign. A grade an
installed agent emits and this module rejected would be a parser that refuses
its own tooling's correct output.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from godot_devkit.core import markdown
from godot_devkit.repo.pm import model

# --- the closed sets ----------------------------------------------------------
# SHIP / SHIP-WITH-FIXES / HOLD are the story's. The RELEASE- family is what the
# existing records return: `**Verdict: RELEASE-WITH-FIXES**` heads both
# pm/roadmap/0.19.0-runners and 0.20.0-bootstrap, RELEASE-SAFE heads the v0.17.0
# pre-release review, and CLAUDE.md names NOT RELEASE-SAFE as the answer every
# minor bump's pre-release review has returned. Six, because a release review
# and a feature review answer different questions with the same three shapes.
VERDICTS = (
    'SHIP',
    'SHIP-WITH-FIXES',
    'HOLD',
    'RELEASE-SAFE',
    'RELEASE-WITH-FIXES',
    'NOT-RELEASE-SAFE',
)

# The union of what the four installed definitions grade with, in rough
# descending order. Sources, so a future trim can check before cutting one:
#   BLOCKER, SHOULD-FIX, CONSIDER, FUTURE-LEVERAGE  milestone-reviewer's counts
#   CRITICAL, MAJOR, MINOR, NIT, QUESTION           verification-reviewer
#   CRITICAL, WARNING, SUGGESTION, DELTA            reviewer's section headings
# The simplifier grades with this set rather than one of its own: DELETE /
# REPLACE / KEEP are KINDS of finding, on a different axis from severity, and
# admitting them here would make "findings by severity" mean two things.
SEVERITIES = (
    'BLOCKER',
    'CRITICAL',
    'MAJOR',
    'SHOULD-FIX',
    'WARNING',
    'MINOR',
    'CONSIDER',
    'SUGGESTION',
    'NIT',
    'DELTA',
    'FUTURE-LEVERAGE',
    'QUESTION',
)

LANDED = 'landed'
REJECTED = 'rejected'
DEFERRED = 'deferred'
# Raised and not yet acted on. A record written BEFORE the landing pass —
# every release review is — has findings with no honest home among the three
# above; without this kind the author misfiles them as `rejected:` and the
# yield column reads a lie. A bare token, or `open: <note>`; never free text.
OPEN = 'open'
DISPOSITION_KINDS = (LANDED, REJECTED, DEFERRED, OPEN)
# The second `landed` form, and it is not a convenience. Reviewers in this SDLC
# fix in place and NEVER commit (SDLC.md §2) — so at the moment the record is
# written, a landed fix genuinely has no hash. Admitting only `landed <hex>`
# under-counts exactly the findings that were acted on, which is the one column
# the yield number exists to read. A literal token, not free text: `landed
# <anything>` would make the column unreadable, the same reason the hash form
# is length-bounded.
IN_PLACE = 'in-place'

# --- the shape ----------------------------------------------------------------
MARKER = 'verdict'
HEADER_CELLS = ('id', 'severity', 'disposition')
CELLS_PER_ROW = len(HEADER_CELLS)
CELL_SEPARATOR = '|'

# git's short hash is 7; a full one is 40. Anything outside that is not a commit
# and `landed <not-a-commit>` is a disposition nobody can follow up.
HASH_MIN_LEN = 7
HASH_MAX_LEN = 40
# A finding id is an ordinal label (`W1`, `S3`, `D2`) — one token, bounded, so
# an over-long or whitespace-carrying cell refuses instead of becoming a key.
MAX_ID_LEN = 32
# milestone / feature / story — the deepest grain id the tree has.
MAX_ID_SEGMENTS = 3

_MARKER_LINE = re.compile(rf'^{MARKER}\s*:\s*(.*)$', re.IGNORECASE)
_LANDED = re.compile(
    rf'^{LANDED}\s+({IN_PLACE}|[0-9a-fA-F]{{{HASH_MIN_LEN},{HASH_MAX_LEN}}})$',
    re.IGNORECASE)
_REJECTED = re.compile(rf'^{REJECTED}\s*:\s*(\S.*)$', re.IGNORECASE)
_DEFERRED = re.compile(rf'^{DEFERRED}\s*:\s*(\S+)$', re.IGNORECASE)
_OPEN = re.compile(rf'^{OPEN}(?:\s*:\s*(\S.*))?$', re.IGNORECASE)
_DISPOSITIONS = ((_LANDED, LANDED), (_REJECTED, REJECTED), (_DEFERRED, DEFERRED),
                 (_OPEN, OPEN))

_VERDICT_BY_FOLD = {value.casefold(): value for value in VERDICTS}
_SEVERITY_BY_FOLD = {value.casefold(): value for value in SEVERITIES}

_DISPOSITION_FORMS = (f'`{LANDED} <commit-hash>`, `{LANDED} {IN_PLACE}`, '
                      f'`{REJECTED}: <why>`, `{DEFERRED}: <grain-id>`, '
                      f'`{OPEN}` or `{OPEN}: <note>`')

# How far below an UNFENCED `verdict:` line this looks for the header row before
# deciding the two are unrelated. Three: a blank line and a stray note between
# them is still obviously one block, and further apart the `verdict:` is a word
# in a paragraph. See `parse` for why this is not a general prose search.
NEAR_MISS_LOOKAHEAD = 3


class NoVerdict(Exception):
    """This record carries no verdict block.

    NOT an error and NOT a malformed record: a review written before the block
    existed, or one whose author skipped it, is a FACT the report lists beside
    the records that have one. A caller that maps this to a non-zero exit turns
    "we have not measured this pass" into "the tooling is broken", and the two
    need different answers from a human.
    """


class MalformedVerdict(Exception):
    """A block exists and cannot be read CORRECTLY. Nothing partial is returned.

    Carries the 1-based line number and the offending line, because "malformed
    verdict block" without them sends the reader to grep a 400-line record. The
    caller maps this to exit 2 — a usage error in the record, never a guess and
    never the findings that happened to parse before the bad row.
    """

    def __init__(self, lineno: int, line: str, why: str) -> None:
        self.lineno = lineno
        self.line = line
        self.why = why
        super().__init__(f'line {lineno}: {why}\n    {line}')


@dataclass
class Finding:
    """One row: what was raised, how it was graded, and what was DONE about it.

    `disposition_value` is carried RAW (D5 — no inference): the commit hash for
    `landed`, the reason text for `rejected`, the grain id for `deferred`, the
    note (or nothing) for `open`. The id and the reason are the author's
    words; only the closed-set tokens
    (`severity`, `disposition_kind`) are canonicalized.
    """

    id: str
    severity: str
    disposition_kind: str
    disposition_value: str


@dataclass
class Verdict:
    """One review pass: its verdict, and every finding it dispositioned."""

    verdict: str
    findings: list[Finding] = field(default_factory=list)


def _fenced_blocks(lines: list[str]) -> tuple[list[list[tuple[int, str]]], int]:
    """Each fenced block's BODY as (1-based lineno, text) pairs, plus the line
    of a fence that never closes, or 0.

    `core.markdown.fence_at` owns the CommonMark rules (indent, marker run,
    the no-backtick-in-a-backtick-info-string trap); the walk is here because
    this module needs a block's EXTENT — `non_fenced_lines` returns everything
    a fence hides, which is the exact complement of what a verdict block is.
    """
    blocks: list[list[tuple[int, str]]] = []
    body: list[tuple[int, str]] = []
    fence, opened = '', 0
    for lineno, raw in enumerate(lines, 1):
        here = markdown.fence_at(raw)
        if not fence:
            if here:
                fence, opened, body = here[0], lineno, []
            continue
        # A closing fence is the same character, at least as long, no info.
        if here and here[0][0] == fence[0] \
                and len(here[0]) >= len(fence) and not here[1]:
            blocks.append(body)
            fence, body = '', []
            continue
        body.append((lineno, raw))
    return blocks, opened if fence else 0


def _content(body: list[tuple[int, str]]) -> list[tuple[int, str]]:
    """The block's lines, stripped, with blank ones dropped."""
    return [(lineno, raw.strip()) for lineno, raw in body if raw.strip()]


def _opens_a_verdict(body: list[tuple[int, str]]) -> bool:
    rows = _content(body)
    return bool(rows) and bool(_MARKER_LINE.match(rows[0][1]))


def _is_header(line: str) -> bool:
    """True for the header row, tolerantly — this one ASKS rather than refuses.

    `_cells` raises, which is right once a block is known to exist; here the
    question is whether these two lines ARE a block, and a refusal would answer
    it before it was asked.
    """
    stripped = line.strip()
    if len(stripped) < 2 or not (stripped.startswith(CELL_SEPARATOR)
                                 and stripped.endswith(CELL_SEPARATOR)):
        return False
    cells = [cell.strip().casefold()
             for cell in stripped[1:-1].split(CELL_SEPARATOR)]
    return tuple(cells) == HEADER_CELLS


def _unfenced_near_miss(lines: list[str],
                        fenced: list[bool]) -> tuple[int, str] | None:
    """An unfenced `verdict:` line with the header row right under it.

    A reviewer who forgot the fence still WROTE a verdict, and answering "this
    record has none" is rule 4's read-side sin by a second route: the report
    prints a clean number for a pass it never counted. The header row within
    `NEAR_MISS_LOOKAHEAD` lines is what separates that from prose — a lone
    `verdict:` in a sentence stays NoVerdict, because claiming it would turn
    every record that DISCUSSES the block into exit 2.
    """
    for idx, raw in enumerate(lines):
        if fenced[idx] or not _MARKER_LINE.match(raw.strip()):
            continue
        window = lines[idx + 1:idx + 1 + NEAR_MISS_LOOKAHEAD + 1]
        if any(_is_header(later) for later in window):
            return idx + 1, raw.strip()
    return None


def _cells(lineno: int, line: str) -> list[str]:
    """The three stripped cells of a table row, or a refusal.

    Whitespace-tolerant, shape-strict: a row opens and closes with a pipe and
    carries exactly three cells. An empty cell survives the split (it is a
    finding about the row, decided by the caller) — which is why this slices
    the delimiters off rather than stripping them.
    """
    if len(line) < 2 or not (line.startswith(CELL_SEPARATOR)
                             and line.endswith(CELL_SEPARATOR)):
        raise MalformedVerdict(
            lineno, line,
            f'a verdict-block row opens and closes with {CELL_SEPARATOR!r} — '
            f'a block holds the header row and one row per finding, nothing else')
    cells = [cell.strip() for cell in line[1:-1].split(CELL_SEPARATOR)]
    if len(cells) != CELLS_PER_ROW:
        raise MalformedVerdict(
            lineno, line,
            f'{len(cells)} cell(s); a row carries exactly {CELLS_PER_ROW} '
            f'({CELL_SEPARATOR.join(HEADER_CELLS)})')
    return cells


def _is_grain_id(value: str) -> bool:
    """A milestone / feature / story id, by the tree's own segment guard.

    `model.segment_is_literal` is what the resolvers use, so a `deferred:`
    naming `..`, an absolute path, a backslash or a glob is refused here for
    the same reason it is refused there rather than by a second rule that can
    drift away from it.
    """
    segments = value.split('/')
    return (len(segments) <= MAX_ID_SEGMENTS
            and all(model.segment_is_literal(segment) for segment in segments))


def _finding(lineno: int, line: str) -> Finding:
    fid, severity, disposition = _cells(lineno, line)
    if not fid:
        raise MalformedVerdict(lineno, line, 'the id cell is empty')
    if len(fid) > MAX_ID_LEN:
        raise MalformedVerdict(
            lineno, line,
            f'the id is {len(fid)} characters; a finding id is a label of at '
            f'most {MAX_ID_LEN} (the report groups by it, it is not the claim)')
    if any(char.isspace() for char in fid):
        raise MalformedVerdict(
            lineno, line, f'the id {fid!r} carries whitespace — it is one token')

    canonical = _SEVERITY_BY_FOLD.get(severity.casefold())
    if canonical is None:
        raise MalformedVerdict(
            lineno, line,
            f'unknown severity {severity!r}; one of {", ".join(SEVERITIES)}')

    for pattern, kind in _DISPOSITIONS:
        match = pattern.match(disposition)
        if match:
            value = (match.group(1) or '').strip()  # `open` alone has none
            if kind == LANDED and value.casefold() == IN_PLACE:
                value = IN_PLACE  # a fixed token folds; a hash stays raw
            break
    else:
        raise MalformedVerdict(
            lineno, line,
            f'unreadable disposition {disposition!r}; one of {_DISPOSITION_FORMS}')

    if kind == DEFERRED and not _is_grain_id(value):
        raise MalformedVerdict(
            lineno, line,
            f'{DEFERRED}: {value!r} is not a grain id — a deferral names the '
            f'grain that will carry it, at most {MAX_ID_SEGMENTS} segments')
    return Finding(fid, canonical, kind, value)


def _parse_block(body: list[tuple[int, str]]) -> Verdict:
    rows = _content(body)
    lineno, line = rows[0]
    raw = _MARKER_LINE.match(line).group(1).strip()  # _opens_a_verdict matched
    canonical = _VERDICT_BY_FOLD.get(raw.casefold())
    if canonical is None:
        raise MalformedVerdict(
            lineno, line,
            f'unknown verdict {raw!r}; one of {", ".join(VERDICTS)}')

    if len(rows) < 2:
        raise MalformedVerdict(
            lineno, line,
            f'the block carries no header row — a pass that raised nothing '
            f'still writes {CELL_SEPARATOR} '
            f'{f" {CELL_SEPARATOR} ".join(HEADER_CELLS)} {CELL_SEPARATOR}')
    header_lineno, header_line = rows[1]
    header = _cells(header_lineno, header_line)
    if tuple(cell.casefold() for cell in header) != HEADER_CELLS:
        raise MalformedVerdict(
            header_lineno, header_line,
            f'the header row must read {CELL_SEPARATOR} '
            f'{f" {CELL_SEPARATOR} ".join(HEADER_CELLS)} {CELL_SEPARATOR}')

    return Verdict(canonical, [_finding(lineno, line) for lineno, line in rows[2:]])


def parse(text: str) -> Verdict:
    """The one verdict block in a review record.

    Raises `NoVerdict` when the record has none and `MalformedVerdict` when it
    has one that cannot be read correctly — including when it has TWO, because
    "the verdict of this pass" is a single fact and picking either one of a pair
    is the guess this parser exists not to make.
    """
    lines = [line.rstrip('\r') for line in text.split('\n')]
    blocks, unterminated = _fenced_blocks(lines)

    if unterminated:
        # The fence masked nothing (core/markdown.py), so the block is not in
        # `blocks` at all — and reporting NoVerdict over a record whose verdict
        # is sitting under an unclosed fence is exactly the quiet miss this
        # module refuses. Only a fence that OPENS a verdict is this module's
        # business; any other stray fence is `check doc`'s finding, not ours.
        rest = list(enumerate(lines[unterminated:], unterminated + 1))
        if _opens_a_verdict(rest):
            raise MalformedVerdict(
                unterminated, lines[unterminated - 1],
                'the verdict block opens a code fence that is never closed')

    found = [block for block in blocks if _opens_a_verdict(block)]
    if not found:
        # Only on the path that would otherwise report NONE. A record carrying
        # a real block AND quoting the shape in prose beside it must still
        # parse — refusing there would redden every record that documents the
        # block, including the four agent definitions that teach it.
        near_miss = _unfenced_near_miss(lines, markdown.fenced_flags(lines)[0])
        if near_miss:
            raise MalformedVerdict(
                *near_miss,
                f'the verdict block is not fenced — the report reads a FENCED '
                f'block, so wrap these lines in a code fence')
        raise NoVerdict(
            f'no verdict block: no fenced block in these {len(lines)} line(s) '
            f'opens with `{MARKER}:` ({len(blocks)} fenced block(s) read)')
    if len(found) > 1:
        lineno, line = _content(found[1])[0]
        raise MalformedVerdict(
            lineno, line,
            f'a second verdict block — a record carries exactly one per pass, '
            f'and the first is at line {_content(found[0])[0][0]}')
    return _parse_block(found[0])
