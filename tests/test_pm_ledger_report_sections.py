"""test_pm_ledger_report_sections.py — `pm ledger report`, sections 2-5.

Section 1 (spend per grain) is `test_pm_ledger_report.py`. The four questions
here read the same ledger plus two documents section 1 never opens — the review
records and the bug frontmatter — and each of them keeps the same three rules:

  * **it counts, and never judges.** Findings are counted per severity and per
    `disposition_kind` — never per the SHAPE of the disposition's value, so
    `landed <hash>` and `landed in-place` are one column, which is the whole
    reason a reviewer who fixes in place and never commits (SDLC § 2) is not
    counted as having landed nothing. A bug's cause is grouped by the id it
    names and the named feature's `status:` is printed verbatim; whether that
    is an escape worth worrying about is the reader's call, not a column's;
  * **absent is not zero, and no data is not a table of zeros.** A story with
    no status rows has no reopen count, not a count of 0; a section with
    nothing in it prints ONE line;
  * **the one refusal on content is a document that will not parse.** A review
    record whose verdict block exists and cannot be read correctly is exit 2,
    by record and by line — the same shape as a ledger line that is not JSON.
    A record with NO block is not that: it is a row saying so.
"""
from __future__ import annotations

import json
import unittest

from support.pm import (bug, decision_line, dispatch_line, put_ledger, run_cli,
                        section_of, session_line, snapshot, status_line, tree,
                        write)

from godot_devkit.repo.pm import verdict

ALPHA, BETA, GAMMA, DELTA = ('0.1/alpha', '0.1/beta', '0.1/gamma', '0.1/delta')
A_S0, A_S1, B_S0 = '0.1/alpha/s0', '0.1/alpha/s1', '0.1/beta/s0'
ALPHA_RECORD = 'docs/reviews/alpha.md'
BETA_RECORD = 'pm/roadmap/0.1-demo/features/beta/review.md'
DELTA_RECORD = 'pm/roadmap/0.1-demo/features/delta/review.md'

YIELD, REWORK, ESCAPES, OVERHEAD = (
    'yield per review pass', 'rework', 'escapes', 'overhead shape')

# A record as the installed agents write it: a fenced block, the header row,
# one row per finding. Both `landed` forms are here on purpose — the column
# counts `disposition_kind`, so a fix landed in place counts exactly like a
# fix landed as a commit.
ALPHA_BLOCK = """\
The pass, in prose.

```text
verdict: SHIP-WITH-FIXES
| id | severity | disposition |
| A1 | MAJOR | landed 0badc0f |
| A2 | MINOR | landed in-place |
| A3 | NIT | rejected: a surface decision, not a local correction |
| A4 | QUESTION | deferred: 0.1/beta |
```
"""
BETA_BLOCK = """\
```text
verdict: HOLD
| id | severity | disposition |
| B1 | CRITICAL | deferred: 0.1/beta |
| B2 | WARNING | deferred: 0.1/gamma |
```
"""
# A real review, written before the block existed. A FACT about the pass.
NO_BLOCK = 'LGTM. Ship it.\n'
# A block that exists and cannot be read: `WOMBAT` is not in the closed set.
BAD_BLOCK = """\
```text
verdict: SHIP
| X1 | WOMBAT | rejected: no such severity |
```
"""


def feature(root, fid: str, status: str, record: str = '',
            stories: tuple = ()) -> None:
    slug = fid.partition('/')[2]
    fdir = root / 'pm/roadmap/0.1-demo/features' / slug
    write(fdir / 'feature.md', {'id': fid, 'milestone': '"0.1"',
                                'name': slug, 'status': status,
                                'reviewed': ''})
    if record:
        (fdir / 'review.md').write_text(record, encoding='utf-8')
    for name, sstatus in stories:
        write(fdir / 'stories' / f'{name}.md',
              {'id': f'{fid}/{name}', 'feature': fid, 'milestone': '"0.1"',
               'name': name, 'status': sstatus})


def seeded(root) -> None:
    """Four features, three stories, three bugs, and one ledger.

    `alpha` points at its record through `reviewed:` and `beta`/`delta` are
    read from the slot beside the feature document — the two ways a record is
    found, both exercised, and both printed as the path that answered.
    """
    (root / ALPHA_RECORD).write_text(ALPHA_BLOCK, encoding='utf-8')
    feature(root, BETA, 'building', BETA_BLOCK, (('s0', 'wip'),))
    feature(root, GAMMA, 'planning')
    feature(root, DELTA, 'review', NO_BLOCK)
    bug(root, 'crash', 'open', caused_by=ALPHA)
    bug(root, 'wobble', 'closed', caused_by=BETA)
    bug(root, 'quiet', 'open')
    put_ledger(
        root,
        status_line('2026-09-03T10:00:00Z', A_S0, 'todo', 'wip'),
        dispatch_line('2026-09-03T10:05:00Z', agent_type='developer',
                      tool_calls=37, tool_calls_before_first_write=12,
                      tree=snapshot(stories_wip=[A_S0])),
        status_line('2026-09-03T10:10:00Z', A_S0, 'wip', 'review'),
        dispatch_line('2026-09-03T10:11:00Z', agent_type='reviewer',
                      tool_calls_before_first_write=3,
                      tree=snapshot(stories_review=[A_S0])),
        # The reopen: `review` back to `wip`, one row, nothing inferred.
        status_line('2026-09-03T10:12:00Z', A_S0, 'review', 'wip'),
        # No `tool_calls_before_first_write`: absent, so it is neither in the
        # sum nor in the list.
        dispatch_line('2026-09-03T10:13:00Z', agent_type='developer',
                      tree=snapshot(stories_wip=[A_S0])),
        status_line('2026-09-03T10:20:00Z', A_S0, 'wip', 'done'),
        # A feature-grained decision with no status row of alpha's after it,
        # and a milestone-grained one whose scope is every grain here.
        decision_line('2026-09-03T10:21:00Z', ALPHA, 'D1'),
        decision_line('2026-09-03T10:22:00Z', '0.1', 'D2'),
        status_line('2026-09-03T10:25:00Z', B_S0, 'todo', 'wip'),
        session_line('2026-09-03T11:00:00Z', session_id='sess-1',
                     tool_calls=10, usage={'output': 1000}),
        session_line('2026-09-03T11:05:00Z', session_id='sess-1',
                     tool_calls=26, usage={'output': 2500}),
    )


def report(root, *argv) -> tuple[int, str]:
    return run_cli(root, 'ledger', 'report', *argv)


def block_rows(out: str, title: str, block: str) -> list[list[str]]:
    """The data rows of ONE block of ONE section, split into cells.

    Scoped twice on purpose: `0.1/alpha/s0` heads a row in three different
    sections, and a case that grepped the whole report for it would assert
    against whichever section happened to print first.
    """
    lines = section_of(out, title).splitlines()
    start = lines.index(f'-- {block}')
    rows = []
    for line in lines[start + 2:]:
        if not line.strip():
            break
        rows.append(line.split())
    return rows


def row_of(out: str, title: str, block: str, first: str) -> list[str]:
    rows = [r for r in block_rows(out, title, block) if r[0] == first]
    if len(rows) != 1:
        raise AssertionError(f'{len(rows)} rows start with {first!r} in '
                             f'{block!r} — the fixture is not what it claims')
    return rows[0]


def seeded_report(test, *argv) -> str:
    with tree(feature_status='done', story_statuses=('done', 'todo')) as root:
        seeded(root)
        code, out = report(root, '0.1', *argv)
    test.assertEqual(code, 0, out)
    return out


YIELD_TABLE = """\
[ledger:report] 0.1 — yield per review pass — 3 record(s), 6 finding(s)

-- verdict (3)
feature    record                                        verdict           findings  landed  rejected  deferred
0.1/alpha  docs/reviews/alpha.md                         SHIP-WITH-FIXES          4       2         1         1
0.1/beta   pm/roadmap/0.1-demo/features/beta/review.md   HOLD                     2       0         0         2
0.1/delta  pm/roadmap/0.1-demo/features/delta/review.md  no verdict block         -       -         -         -

-- findings by severity (6)
feature    severity  findings
0.1/alpha  MAJOR            1
0.1/alpha  MINOR            1
0.1/alpha  NIT              1
0.1/alpha  QUESTION         1
0.1/beta   CRITICAL         1
0.1/beta   WARNING          1

-- deferred to (3)
target     feature    findings
0.1/beta   0.1/alpha         1
0.1/beta   0.1/beta          1
0.1/gamma  0.1/beta          1"""

REWORK_TABLE = """\
[ledger:report] 0.1 — rework — 3 story(s), 1 reopen(s), 2 record(s) with a verdict

-- story (3)
feature    story         reopens  after_review
0.1/alpha  0.1/alpha/s0        1             2
0.1/alpha  0.1/alpha/s1        -             -
0.1/beta   0.1/beta/s0         0             -

-- verdict distribution (2)
verdict          records
SHIP-WITH-FIXES        1
HOLD                   1"""

ESCAPES_TABLE = """\
[ledger:report] 0.1 — escapes — 2 bug(s) naming a cause, 2 feature(s)

-- bugs naming a cause (2)
caused_by  bug              status  feature_status
0.1/alpha  0.1/bugs/crash   open    done
0.1/beta   0.1/bugs/wobble  closed  building"""

OVERHEAD_TABLE = """\
[ledger:report] 0.1 — overhead shape — 3 dispatch row(s), 2 decision row(s), 2 session row(s)

-- story (3)
story         dispatches  before_first_write  calls
0.1/alpha/s0           3                  15  12,3
0.1/alpha/s1           0                   -  -
0.1/beta/s0            0                   -  -

-- decisions per grain (5)
grain      decisions
0.1                1
0.1/alpha          1
0.1/beta           0
0.1/delta          0
0.1/gamma          0

-- decision to next status row (2)
grain      entry  ts                    next_status_s
0.1/alpha  D1     2026-09-03T10:21:00Z              -
0.1        D2     2026-09-03T10:22:00Z            180

-- session deltas (1)
session_id  ts                     out  tool_calls
sess-1      2026-09-03T11:05:00Z  1500          16"""


class Tables(unittest.TestCase):
    """The exact lines, for the exact fixture. Rule 6: the shape is the API."""

    def test_section_two_yield_prints_this_exact_table(self):
        self.assertEqual(section_of(seeded_report(self), YIELD), YIELD_TABLE)

    def test_section_three_rework_prints_this_exact_table(self):
        self.assertEqual(section_of(seeded_report(self), REWORK), REWORK_TABLE)

    def test_section_four_escapes_prints_this_exact_table(self):
        self.assertEqual(section_of(seeded_report(self), ESCAPES),
                         ESCAPES_TABLE)

    def test_section_five_overhead_prints_this_exact_table(self):
        self.assertEqual(section_of(seeded_report(self), OVERHEAD),
                         OVERHEAD_TABLE)

    def test_the_report_never_writes(self):
        with tree(feature_status='done',
                  story_statuses=('done', 'todo')) as root:
            seeded(root)
            before = {p: p.read_bytes() for p in sorted(root.rglob('*'))
                      if p.is_file()}
            self.assertEqual(report(root, '0.1')[0], 0)
            self.assertEqual(report(root, '0.1', '--json')[0], 0)
            after = {p: p.read_bytes() for p in sorted(root.rglob('*'))
                     if p.is_file()}
        self.assertEqual(after, before)


class Yield(unittest.TestCase):
    """Section 2: the verdict block, counted and never re-judged."""

    def test_both_landed_forms_count_in_the_one_landed_column(self):
        """A2 is `landed in-place`, A1 is `landed <hash>`; the column is the
        DISPOSITION KIND, so a reviewer who fixed in place and never committed
        (SDLC § 2) is not counted as having landed nothing."""
        parsed = verdict.parse(ALPHA_BLOCK)
        kinds = [f.disposition_kind for f in parsed.findings]
        self.assertEqual(kinds.count(verdict.LANDED), 2)
        self.assertNotEqual(*[f.disposition_value for f in parsed.findings
                              if f.disposition_kind == verdict.LANDED])
        row = row_of(seeded_report(self), YIELD, 'verdict (3)', ALPHA)
        self.assertEqual(row[-4:], ['4', '2', '1', '1'])

    def test_a_record_with_no_block_is_listed_and_never_counted_as_zero(self):
        row = row_of(seeded_report(self), YIELD, 'verdict (3)', DELTA)
        self.assertEqual(row[2:], ['no', 'verdict', 'block', '-', '-', '-',
                                   '-'])

    def test_a_feature_with_no_record_at_all_is_not_a_review_pass(self):
        """`gamma` has no record: there was no pass, so there is no row."""
        out = section_of(seeded_report(self), YIELD)
        self.assertNotIn(GAMMA, out.split('-- deferred to')[0])

    def test_deferrals_group_by_the_target_the_finding_names(self):
        out = section_of(seeded_report(self), YIELD)
        rows = block_rows(out, YIELD, 'deferred to (3)')
        self.assertEqual(rows, [['0.1/beta', ALPHA, '1'],
                                ['0.1/beta', BETA, '1'],
                                ['0.1/gamma', BETA, '1']])

    def test_the_pointer_is_read_first_and_the_slot_beside_it_second(self):
        """Both paths PRINT, so a reader never has to ask which one answered."""
        out = section_of(seeded_report(self), YIELD)
        self.assertIn(ALPHA_RECORD, out)
        self.assertIn(BETA_RECORD, out)


class Rework(unittest.TestCase):
    """Section 3: reopens, dispatches after review, verdicts given."""

    def test_a_reopen_is_one_status_row_and_the_dispatches_after_it_count(self):
        row = next(r for r in block_rows(seeded_report(self), REWORK,
                                         'story (3)') if r[1] == A_S0)
        self.assertEqual(row, [ALPHA, A_S0, '1', '2'])

    def test_a_story_with_no_status_rows_has_no_reopen_count_not_zero(self):
        row = next(r for r in block_rows(seeded_report(self), REWORK,
                                         'story (3)') if r[1] == A_S1)
        self.assertEqual(row, [ALPHA, A_S1, '-', '-'])

    def test_a_story_that_never_reached_review_has_no_after_count(self):
        """`0`, not `-`, for reopens: its rows WERE read and none was one."""
        row = row_of(seeded_report(self), REWORK, 'story (3)', BETA)
        self.assertEqual(row, [BETA, B_S0, '0', '-'])


class Escapes(unittest.TestCase):
    """Section 4: the bug's cause, and the cause's own state at report time."""

    def test_a_done_cause_and_a_still_building_one_print_their_status(self):
        rows = block_rows(seeded_report(self), ESCAPES,
                          'bugs naming a cause (2)')
        self.assertEqual(rows, [[ALPHA, '0.1/bugs/crash', 'open', 'done'],
                                [BETA, '0.1/bugs/wobble', 'closed',
                                 'building']])

    def test_a_bug_with_no_caused_by_is_not_an_escape(self):
        self.assertNotIn('quiet', section_of(seeded_report(self), ESCAPES))

    def test_a_cause_that_resolves_to_nothing_still_gets_its_row(self):
        """A retired or mistyped cause is a fact `pm validate` reports; the
        report prints the row with `-` rather than dropping the bug."""
        with tree(feature_status='done',
                  story_statuses=('done', 'todo')) as root:
            seeded(root)
            bug(root, 'ghost', 'open', caused_by='0.9/vanished')
            out = report(root, '0.1')[1]
        row = row_of(out, ESCAPES, 'bugs naming a cause (3)', '0.9/vanished')
        self.assertEqual(row, ['0.9/vanished', '0.1/bugs/ghost', 'open', '-'])
        self.assertIn('3 bug(s) naming a cause, 3 feature(s)', out)


class Overhead(unittest.TestCase):
    """Section 5: looking before writing, deciding, and stopping."""

    def test_before_first_write_is_summed_and_listed(self):
        """One dispatch that looked at 15 files and two that looked at 12 and
        3 are the same sum and not the same shape, so both print."""
        row = row_of(seeded_report(self), OVERHEAD, 'story (3)', A_S0)
        self.assertEqual(row, [A_S0, '3', '15', '12,3'])

    def test_a_decision_gap_is_measured_inside_its_own_grains_scope(self):
        rows = block_rows(seeded_report(self), OVERHEAD,
                          'decision to next status row (2)')
        # D1 is alpha's: no status row of alpha or its stories follows it.
        # D2 is the milestone's: beta's story flip at 10:25 is 180s later.
        self.assertEqual([r[0] for r in rows], [ALPHA, '0.1'])
        self.assertEqual([r[-1] for r in rows], ['-', '180'])

    def test_session_rows_are_diffed_per_session_and_never_attributed(self):
        row = row_of(seeded_report(self), OVERHEAD, 'session deltas (1)',
                     'sess-1')
        self.assertEqual(row[-2:], ['1500', '16'])

    def test_one_session_row_alone_is_a_count_and_no_delta(self):
        """A cumulative total with nothing to subtract from it is not a delta,
        and the census still says the row is there."""
        with tree(feature_status='done',
                  story_statuses=('done', 'todo')) as root:
            seeded(root)
            put_ledger(root, session_line('2026-09-03T11:00:00Z',
                                          session_id='sess-1', tool_calls=10,
                                          usage={'output': 1000}))
            out = section_of(report(root, '0.1')[1], OVERHEAD)
        self.assertIn('0 dispatch row(s), 0 decision row(s), 1 session row(s)',
                      out)
        self.assertIn('-- session deltas (0)', out)

    def test_a_delta_needs_both_ends_measured(self):
        """One end absent is not a delta of the other end minus zero."""
        with tree(feature_status='done',
                  story_statuses=('done', 'todo')) as root:
            seeded(root)
            put_ledger(
                root,
                session_line('2026-09-03T11:00:00Z', session_id='sess-1',
                             usage={'output': 1000}),
                session_line('2026-09-03T11:05:00Z', session_id='sess-1',
                             tool_calls=26, usage={'output': 2500}))
            out = report(root, '0.1')[1]
        row = row_of(out, OVERHEAD, 'session deltas (1)', 'sess-1')
        self.assertEqual(row[-2:], ['1500', '-'])


class NoData(unittest.TestCase):
    """A section with nothing in it prints ONE line, never a table of zeros."""

    def quiet(self) -> str:
        with tree(feature_status='building', story_statuses=(),
                  with_record=False) as root:
            put_ledger(root, status_line('2026-09-03T10:00:00Z', ALPHA,
                                         'ready', 'building'))
            code, out = report(root, '0.1')
        self.assertEqual(code, 0, out)
        return out

    def test_every_section_says_no_data_rather_than_printing_zeros(self):
        out = self.quiet()
        for title in (YIELD, REWORK, ESCAPES, OVERHEAD):
            section = section_of(out, title)
            self.assertEqual(len(section.splitlines()), 2, section)
            self.assertEqual(section.splitlines()[1], 'no data')
            self.assertNotIn('--', section.splitlines()[1])

    def test_the_censuses_still_say_what_was_counted(self):
        out = self.quiet()
        self.assertIn('yield per review pass — 0 record(s), 0 finding(s)', out)
        self.assertIn('rework — 0 story(s), - reopen(s), 0 record(s)', out)
        self.assertIn('escapes — 0 bug(s) naming a cause, 0 feature(s)', out)
        self.assertIn('overhead shape — 0 dispatch row(s), 0 decision row(s), '
                      '0 session row(s)', out)

    def test_json_carries_the_four_keys_with_empty_lists_behind_them(self):
        with tree(feature_status='building', story_statuses=(),
                  with_record=False) as root:
            put_ledger(root, status_line('2026-09-03T10:00:00Z', ALPHA,
                                         'ready', 'building'))
            data = json.loads(report(root, '0.1', '--json')[1])
        self.assertEqual(data['yield']['records'], [])
        self.assertEqual(data['rework']['stories'], [])
        self.assertEqual(data['escapes']['bugs'], [])
        self.assertEqual(data['overhead']['sessions'], [])


class Json(unittest.TestCase):
    """The same numbers, `null` where the table prints `-`."""

    def payload(self) -> dict:
        out = seeded_report(self, '--json')
        self.assertEqual(len(out.strip().splitlines()), 1, out)
        return json.loads(out)

    def test_section_two_yield(self):
        blank = {kind: None for kind in verdict.DISPOSITION_KINDS}
        self.assertEqual(self.payload()['yield'], {
            'records': [
                {'feature': ALPHA, 'record': ALPHA_RECORD,
                 'verdict': 'SHIP-WITH-FIXES', 'findings': 4,
                 'severities': {'MAJOR': 1, 'MINOR': 1, 'NIT': 1,
                                'QUESTION': 1},
                 'deferred': [{'target': BETA, 'findings': 1}],
                 'dispositions': {'landed': 2, 'rejected': 1, 'deferred': 1}},
                {'feature': BETA, 'record': BETA_RECORD, 'verdict': 'HOLD',
                 'findings': 2,
                 'severities': {'CRITICAL': 1, 'WARNING': 1},
                 'deferred': [{'target': BETA, 'findings': 1},
                              {'target': GAMMA, 'findings': 1}],
                 'dispositions': {'landed': 0, 'rejected': 0, 'deferred': 2}},
                {'feature': DELTA, 'record': DELTA_RECORD, 'verdict': None,
                 'findings': None, 'severities': {}, 'deferred': [],
                 'dispositions': blank},
            ],
            'totals': {'records': 3, 'findings': 6}})

    def test_section_three_rework(self):
        self.assertEqual(self.payload()['rework'], {
            'stories': [
                {'grain': A_S0, 'feature': ALPHA, 'reopens': 1,
                 'after_review': 2},
                {'grain': A_S1, 'feature': ALPHA, 'reopens': None,
                 'after_review': None},
                {'grain': B_S0, 'feature': BETA, 'reopens': 0,
                 'after_review': None},
            ],
            'verdicts': [{'verdict': 'SHIP-WITH-FIXES', 'records': 1},
                         {'verdict': 'HOLD', 'records': 1}],
            'totals': {'stories': 3, 'reopens': 1, 'records': 2}})

    def test_section_four_escapes(self):
        self.assertEqual(self.payload()['escapes'], {
            'bugs': [
                {'caused_by': ALPHA, 'bug': '0.1/bugs/crash', 'status': 'open',
                 'feature_status': 'done', 'feature_done': True},
                {'caused_by': BETA, 'bug': '0.1/bugs/wobble',
                 'status': 'closed', 'feature_status': 'building',
                 'feature_done': False},
            ],
            'totals': {'bugs': 2, 'features': 2}})

    def test_section_five_overhead(self):
        self.assertEqual(self.payload()['overhead'], {
            'stories': [
                {'grain': A_S0, 'dispatches': 3, 'before_first_write': 15,
                 'calls': [12, 3]},
                {'grain': A_S1, 'dispatches': 0, 'before_first_write': None,
                 'calls': []},
                {'grain': B_S0, 'dispatches': 0, 'before_first_write': None,
                 'calls': []},
            ],
            'decisions': [{'grain': '0.1', 'decisions': 1},
                          {'grain': ALPHA, 'decisions': 1},
                          {'grain': BETA, 'decisions': 0},
                          {'grain': DELTA, 'decisions': 0},
                          {'grain': GAMMA, 'decisions': 0}],
            'gaps': [
                {'grain': ALPHA, 'entry': 'D1', 'title': 'why',
                 'ts': '2026-09-03T10:21:00Z', 'next_status_s': None},
                {'grain': '0.1', 'entry': 'D2', 'title': 'why',
                 'ts': '2026-09-03T10:22:00Z', 'next_status_s': 180},
            ],
            'sessions': [{'session_id': 'sess-1',
                          'ts': '2026-09-03T11:05:00Z', 'output': 1500,
                          'tool_calls': 16}],
            'totals': {'dispatch_rows': 3, 'decision_rows': 2,
                       'session_rows': 2}})


class Refusals(unittest.TestCase):
    """The one refusal on content: a block that will not parse. Exit 2."""

    def malformed(self, *argv) -> str:
        with tree(feature_status='done',
                  story_statuses=('done', 'todo')) as root:
            seeded(root)
            (root / ALPHA_RECORD).write_text(BAD_BLOCK, encoding='utf-8')
            code, out = report(root, '0.1', *argv)
        self.assertEqual(code, 2, out)
        return out

    def test_a_malformed_block_names_the_record_and_the_line(self):
        out = self.malformed()
        self.assertIn(ALPHA_RECORD, out)
        self.assertIn('line 3', out)
        self.assertIn('WOMBAT', out)

    def test_it_refuses_in_json_too_and_prints_no_object(self):
        out = self.malformed('--json')
        self.assertNotIn('"milestone"', out)

    def test_nothing_partial_is_printed_before_the_refusal(self):
        """Section 1's table would otherwise be on stdout with a broken
        section 2 behind it — a report half-printed reads as a report."""
        self.assertNotIn('-- story (', self.malformed())

    def test_a_record_with_no_block_is_never_a_refusal(self):
        """`NoVerdict` is a fact about the pass. Mapping it to exit 2 would
        turn "we have not measured this" into "the tooling is broken"."""
        with tree(feature_status='done',
                  story_statuses=('done', 'todo')) as root:
            seeded(root)
            (root / ALPHA_RECORD).write_text(NO_BLOCK, encoding='utf-8')
            code, out = report(root, '0.1')
        self.assertEqual(code, 0, out)
        self.assertEqual(out.count('no verdict block'), 2)


if __name__ == '__main__':  # pragma: no cover
    unittest.main()
