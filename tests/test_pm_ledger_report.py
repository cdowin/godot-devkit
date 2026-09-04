"""test_pm_ledger_report.py — `pm ledger report`, section 1 (spend per grain).

The ledger records and never judges; the report is the caller D3 and D4 left
the judgement to. What it may do is arithmetic over rows already on disk — sum,
count, subtract, group. What it may NOT do is D5: `size:` is a column and never
a divisor, there is no dollar figure, no score and no label. So the cases here
pin, in order:

  * the exact table and the exact JSON for one seeded tree + one seeded ledger
    — the line shapes are a consumer contract (hard rule 6);
  * absent is not zero: a row that carried no `cache_creation` contributes
    NOTHING to that column, and a column no row carried prints `-`. A grain no
    row names prints dashes across, because the tree is walked and not the
    ledger;
  * attribution is D3's snapshot, spelled once: a story by `stories_wip` /
    `stories_review`, a feature by `features_building` / `features_review` or
    by owning a named story, a row naming nothing in its own trailing block —
    counted, never dropped and never labelled beyond that heading;
  * the clock is a subtraction: seconds in each state between consecutive
    status rows — a column for EVERY state of the kind's vocabulary but the
    terminal one, `blocked` included, because time stuck there is the question
    the section exists to answer — and a first-row → terminal-row total only
    once the grain reached that terminal state (`ledger.terminal_state`, so
    the report and `pm ledger show` cannot disagree about where a grain
    ended);
  * the refusal matrix (SDLC § 5). Nothing exits non-zero on a NUMBER: the one
    content refusal is a ledger line that will not parse, by line number. No
    ledger at all is exit 0 and one line, because "nothing has been recorded
    yet" is a fact about the tree.
"""
from __future__ import annotations

import json
import unittest

from support.pm import (LEDGER_REL, bug, dispatch_line, ledger_lines,
                        put_ledger, run_cli, section_of, snapshot, status_line,
                        tree, write)

from godot_devkit.repo.pm import ledger

STORY = '0.1/alpha/s0'
QUIET = '0.1/alpha/s1'
FEATURE = '0.1/alpha'
BUG = '0.1/bugs/crash'


def report(root, *argv) -> tuple[int, str]:
    return run_cli(root, 'ledger', 'report', *argv)


def seeded(root) -> None:
    """The fixture every shape case reads: one story worked and closed, one
    story nothing ever touched, the feature that owns them, one closed bug, and
    three dispatch rows — two agent types on the story, one naming no grain."""
    write(root / 'pm/roadmap/0.1-demo/features/alpha/stories/s1.md',
          {'id': QUIET, 'feature': FEATURE, 'milestone': '"0.1"', 'name': 'S1',
           'status': 'todo', 'size': 'm'})
    bug(root, 'crash', 'closed')
    put_ledger(
        root,
        status_line('2026-09-03T10:00:00Z', STORY, 'todo', 'wip'),
        dispatch_line('2026-09-03T10:05:00Z', agent_type='developer',
                      tool_calls=37, duration_s=812,
                      usage={'input': 1200, 'output': 38000,
                             'cache_creation': 210000, 'cache_read': 9100000},
                      tree=snapshot(stories_wip=[STORY],
                                    features_building=[FEATURE])),
        status_line('2026-09-03T10:10:00Z', STORY, 'wip', 'review'),
        # No `tool_calls`, no `duration_s`, and one usage key only: absent is
        # not zero, and this row is what proves the columns say so.
        dispatch_line('2026-09-03T10:11:00Z', agent_type='reviewer',
                      usage={'output': 500},
                      tree=snapshot(stories_review=[STORY])),
        status_line('2026-09-03T10:12:00Z', STORY, 'review', 'done'),
        status_line('2026-09-03T10:20:00Z', BUG, 'open', 'fixed'),
        status_line('2026-09-03T10:20:30Z', BUG, 'fixed', 'closed'),
        # Nothing was `wip` when this one stopped. A true statement about
        # process discipline (D3's cost note), never a dropped row.
        dispatch_line('2026-09-03T10:30:00Z', usage={'input': 5}, tool_calls=2),
    )


TABLE = """\
[ledger:report] 0.1 — spend per grain — 3 dispatch row(s), 5 status row(s), 4 grain(s)

-- story (2)
grain         size  dispatches    in    out  cache_create  cache_read  tool_calls  duration_s  todo  wip  review  blocked  total_s
0.1/alpha/s0                 2  1200  38500        210000     9100000          37         812     -  600     120        -      720
  developer                  1  1200  38000        210000     9100000          37         812
  reviewer                   1     -    500             -           -           -           -
0.1/alpha/s1  m              0     -      -             -           -           -           -     -    -       -        -        -

-- feature (1)
grain        size  dispatches    in    out  cache_create  cache_read  tool_calls  duration_s  planning  ready  building  review  total_s
0.1/alpha                   2  1200  38500        210000     9100000          37         812         -      -         -       -        -
  developer                 1  1200  38000        210000     9100000          37         812
  reviewer                  1     -    500             -           -           -           -

-- bug (1)
grain           size  dispatches  in  out  cache_create  cache_read  tool_calls  duration_s  open  fixed  total_s
0.1/bugs/crash                 0   -    -             -           -           -           -     -     30       30

-- rows naming no grain (1)
dispatches  in  out  cache_create  cache_read  tool_calls  duration_s
         1   5    -             -           -           2           -

[ledger:report] 0.1 — 38500 out / 39 tool calls / 812 s across 3 dispatch row(s)"""

SPEND_TITLE = 'spend per grain'
# Section 1's keys in `--json`, and the one key each later section adds.
SPEND_KEYS = ('milestone', 'section', 'grains', 'unattributed', 'totals')
SECTION_KEYS = ('yield', 'rework', 'escapes', 'overhead')


def blank_usage() -> dict:
    return {key: None for key, _ in ledger.USAGE_FIELDS}


class Table(unittest.TestCase):
    """The exact lines, for the exact fixture. Rule 6: the shape is the API."""

    def test_the_seeded_ledger_prints_this_exact_table(self):
        with tree(story_statuses=('done', 'todo')) as root:
            seeded(root)
            code, out = report(root, '0.1')
        self.assertEqual(code, 0, out)
        # Section 1 alone, byte for byte. Sections 2-5 follow it and are pinned
        # in test_pm_ledger_report_sections.py; the summary line below is the
        # end of this one, and it is what the slice stops at.
        self.assertEqual(section_of(out, SPEND_TITLE), TABLE)

    def test_the_report_prints_the_five_sections_in_the_milestones_order(self):
        """The five questions of milestone.md, once each, in its order."""
        with tree(story_statuses=('done', 'todo')) as root:
            seeded(root)
            out = report(root, '0.1')[1]
        heads = [line for line in out.splitlines()
                 if line.startswith('[ledger:report] 0.1 — ')
                 and line.count(' — ') >= 2]
        self.assertEqual([h.split(' — ')[1] for h in heads],
                         [SPEND_TITLE, 'yield per review pass', 'rework',
                          'escapes', 'overhead shape'])

    def test_the_report_never_writes(self):
        with tree(story_statuses=('done', 'todo')) as root:
            seeded(root)
            before = ledger_lines(root)
            paths = sorted(p.name for p in (root / 'pm/roadmap/0.1-demo')
                           .iterdir())
            self.assertEqual(report(root, '0.1')[0], 0)
            self.assertEqual(report(root, '0.1', '--json')[0], 0)
            self.assertEqual(ledger_lines(root), before)
            self.assertEqual(sorted(p.name for p in
                                    (root / 'pm/roadmap/0.1-demo').iterdir()),
                             paths)

    def test_a_grain_no_row_names_is_present_and_dashed(self):
        """Walk the tree, not the ledger — a grain nothing measured EXISTS."""
        with tree(story_statuses=('done', 'todo')) as root:
            seeded(root)
            out = report(root, '0.1')[1]
        line = next(ln for ln in out.splitlines() if ln.startswith(QUIET))
        # `size:` verbatim as a COLUMN (D5), then dashes: no zero anywhere.
        self.assertEqual(line.split(), [QUIET, 'm', '0'] + ['-'] * 11)

    def test_an_absent_usage_key_prints_a_dash_and_never_a_zero(self):
        """The reviewer row carried `output` only. A `0` under `in` would read
        forever after as a dispatch that consumed no input."""
        with tree(story_statuses=('done', 'todo')) as root:
            seeded(root)
            out = report(root, '0.1')[1]
        line = next(ln for ln in out.splitlines()
                    if ln.strip().startswith('reviewer'))
        self.assertEqual(line.split(),
                         ['reviewer', '1', '-', '500', '-', '-', '-', '-'])

    def test_two_agent_types_split_into_sub_rows_one_does_not(self):
        with tree(story_statuses=('done', 'todo')) as root:
            seeded(root)
            both = report(root, '0.1')[1]
            put_ledger(root,
                       dispatch_line('2026-09-03T10:05:00Z',
                                     agent_type='developer', tool_calls=37,
                                     tree=snapshot(stories_wip=[STORY])))
            alone = report(root, '0.1')[1]
        self.assertEqual(
            [ln.strip().split()[0] for ln in both.splitlines()
             if ln.startswith('  ') and ln.strip()[:1].isalpha()],
            ['developer', 'reviewer'] * 2)
        self.assertNotIn('developer', alone)

    def test_a_bugs_states_come_from_the_bug_vocabulary(self):
        """`open`/`fixed` — the states BEFORE `[pm] bug_states[-1]`, which is
        where the bug ended and so where its total stops."""
        with tree(story_statuses=('done', 'todo')) as root:
            seeded(root)
            out = report(root, '0.1')[1]
        header, row = out.split('-- bug (1)')[1].splitlines()[1:3]
        # `closed` gets no column: it is where the bug ENDED, and the seconds
        # after it are a running clock rather than a duration.
        self.assertEqual(header.split()[-3:], ['open', 'fixed', 'total_s'])
        # Nothing measured `open` — nobody recorded when the bug was filed —
        # and 30s is the whole of `fixed`, which is the total too.
        self.assertEqual(row.split()[-3:], ['-', '30', '30'])

    def test_a_non_terminal_grain_has_no_total(self):
        """A running clock is not a duration — the same rule `show` prints by."""
        with tree(story_statuses=('review', 'todo')) as root:
            seeded(root)
            put_ledger(root,
                       status_line('2026-09-03T10:00:00Z', STORY, 'todo',
                                   'wip'),
                       status_line('2026-09-03T10:10:00Z', STORY, 'wip',
                                   'review'))
            out = report(root, '0.1')[1]
        line = next(ln for ln in out.splitlines() if ln.startswith(STORY))
        self.assertEqual(line.split()[-5:], ['-', '600', '-', '-', '-'])

    def test_one_row_is_an_instant_and_never_a_zero_second_total(self):
        """A span needs two rows. A grain whose only row is its own terminal
        flip has an instant and no duration, and `0` there reads as "this was
        done in no time at all" — a measurement nobody made, in the one column
        a reader compares grains by. This repo's own tree prints it: a story
        flipped straight to `done` shows every state column `-` and `total_s`
        `0`."""
        with tree(story_statuses=('done', 'todo')) as root:
            put_ledger(root, status_line('2026-09-03T10:00:00Z', STORY,
                                         'review', 'done'))
            out = report(root, '0.1')[1]
        line = next(ln for ln in out.splitlines() if ln.startswith(STORY))
        self.assertEqual(line.split()[-5:], ['-', '-', '-', '-', '-'])

    def test_rows_out_of_time_order_never_fabricate_an_interval(self):
        """`merge=union` (D6) interleaves two branches' appends by BRANCH, so
        the file's order is not the clock's. The subtraction is over the rows
        in TIME order or it is not a measurement: read in file order, this
        fixture bills 3600s of `review` backwards and 10800s to a `wip` the
        story spent 7200s in — two numbers that look like measurements and are
        not (hard rule 4, read side)."""
        with tree(story_statuses=('done', 'todo')) as root:
            put_ledger(
                root,
                status_line('2026-09-03T12:00:00Z', STORY, 'wip', 'review'),
                status_line('2026-09-03T10:00:00Z', STORY, 'todo', 'wip'),
                status_line('2026-09-03T13:00:00Z', STORY, 'review', 'done'))
            out = report(root, '0.1')[1]
        line = next(ln for ln in out.splitlines() if ln.startswith(STORY))
        self.assertNotIn('-7200', line)
        # todo, wip, review, blocked, total_s — the story's real life.
        self.assertEqual(line.split()[-5:],
                         ['-', '7200', '3600', '-', '10800'])

    def test_an_unparseable_stamp_leaves_the_state_absent_not_zero(self):
        """A row whose `ts` will not parse contributes no arithmetic, and no
        arithmetic is `-`. A `0` there would say the story passed through the
        state in no time at all."""
        with tree(story_statuses=('wip', 'todo')) as root:
            put_ledger(root,
                       status_line('2026-09-03T10:00:00Z', STORY, 'todo',
                                   'wip'),
                       status_line('not-a-timestamp', STORY, 'wip', 'review'))
            out = report(root, '0.1')[1]
        line = next(ln for ln in out.splitlines() if ln.startswith(STORY))
        self.assertEqual(line.split()[-5:], ['-', '-', '-', '-', '-'])

    def test_a_snapshot_id_from_another_milestone_names_nothing_here(self):
        """D3 puts every live candidate on the row; the rule that reads it is
        this module's. An id that is not a grain of THIS milestone attributes
        to no grain, and the row lands in the trailing block rather than being
        dropped or inventing a grain."""
        with tree(story_statuses=('wip', 'todo')) as root:
            put_ledger(root, dispatch_line(
                '2026-09-03T10:00:00Z',
                tree=snapshot(stories_wip=['0.9/other/s0'],
                              features_building=['0.9/other']),
                usage={'input': 7}, tool_calls=1))
            out = report(root, '0.1')[1]
        line = next(ln for ln in out.splitlines() if ln.startswith(STORY))
        # dispatches, then the four token sums — nothing was attributed here.
        self.assertEqual(line.split()[1:6], ['0', '-', '-', '-', '-'])
        self.assertIn('-- rows naming no grain (1)', out)
        self.assertNotIn('0.9/other', out)

    def test_a_grain_with_no_id_frontmatter_gets_the_id_its_path_spells(self):
        """A grain missing from the table reads as a grain that never existed
        (hard rule 4's census clause), so the path's id stands in for the
        absent claim rather than the row being dropped or blank."""
        with tree(story_statuses=('todo',)) as root:
            write(root / 'pm/roadmap/0.1-demo/features/alpha/stories/s9.md',
                  {'feature': FEATURE, 'milestone': '"0.1"', 'name': 'S9',
                   'status': 'todo'})
            put_ledger(root, status_line('2026-09-03T10:00:00Z', STORY,
                                         'todo', 'wip'))
            out = report(root, '0.1')[1]
        self.assertIn('0.1/alpha/s9', out)

    def test_no_ledger_still_reports_what_the_ledger_never_held(self):
        """Sections 2 and 4 read the review records and the bug frontmatter —
        documents `ledger.jsonl` has nothing to do with. Saying `no ledger` and
        stopping there hides a yield of real findings and a real escape behind
        a line about a different file, which is the read-side sin: the reader
        is told there is nothing and there is something."""
        with tree() as root:
            bug(root, 'esc', caused_by=FEATURE)
            (root / 'docs/reviews/alpha.md').write_text(
                'x\n\n```text\nverdict: SHIP-WITH-FIXES\n'
                '| id | severity | disposition |\n'
                '| W1 | WARNING | landed in-place |\n```\n', encoding='utf-8')
            code, out = report(root, '0.1')
        self.assertEqual(code, 0, out)
        self.assertIn('[ledger:report] 0.1 — no ledger', out)
        self.assertIn('SHIP-WITH-FIXES', out)
        self.assertIn('0.1/bugs/esc', out)

    def test_the_no_grain_block_counts_the_rows_it_names_nothing_about(self):
        with tree(story_statuses=('done', 'todo')) as root:
            seeded(root)
            out = report(root, '0.1')[1]
        block = out.split('-- rows naming no grain (1)')[1].splitlines()
        self.assertEqual(block[1].split(),
                         ['dispatches', 'in', 'out', 'cache_create',
                          'cache_read', 'tool_calls', 'duration_s'])
        # The row's numbers, whole: nothing about it is dropped, and nothing
        # about it is labelled beyond the heading.
        self.assertEqual(block[2].split(), ['1', '5', '-', '-', '-', '2', '-'])

    def test_an_empty_no_grain_block_still_says_zero(self):
        """A census that saw nothing says so; silence reads as never scanned."""
        with tree(story_statuses=('done', 'todo')) as root:
            put_ledger(root, status_line('2026-09-03T10:00:00Z', STORY, 'todo',
                                         'wip'))
            out = report(root, '0.1')[1]
        self.assertIn('-- rows naming no grain (0)', out)


class Json(unittest.TestCase):
    """The same numbers, `null` where the table prints `-`."""

    def payload(self, root) -> dict:
        code, out = report(root, '0.1', '--json')
        self.assertEqual(code, 0, out)
        self.assertEqual(len(out.strip().splitlines()), 1, out)
        return json.loads(out)

    def test_the_seeded_ledger_produces_this_exact_object(self):
        full = {'input': 1200, 'output': 38500, 'cache_creation': 210000,
                'cache_read': 9100000}
        dev = {'agent_type': 'developer', 'dispatches': 1,
               'usage': {'input': 1200, 'output': 38000,
                         'cache_creation': 210000, 'cache_read': 9100000},
               'tool_calls': 37, 'duration_s': 812}
        rev = {'agent_type': 'reviewer', 'dispatches': 1,
               'usage': dict(blank_usage(), output=500),
               'tool_calls': None, 'duration_s': None}
        with tree(story_statuses=('done', 'todo')) as root:
            seeded(root)
            data = self.payload(root)
        # Section 1's own keys, exactly — sections 2-5 add one key each and are
        # pinned in test_pm_ledger_report_sections.py. Compared as a SLICE
        # rather than by deleting keys, so a key section 1 stopped emitting
        # still fails here.
        self.assertEqual({k: data[k] for k in SPEND_KEYS if k in data}, {
            'milestone': '0.1',
            'section': 'spend',
            'grains': [
                {'grain': STORY, 'kind': 'story', 'size': None,
                 'dispatches': 2, 'usage': full, 'tool_calls': 37,
                 'duration_s': 812, 'agent_types': [dev, rev],
                 'states': {'todo': None, 'wip': 600, 'review': 120,
                            'blocked': None},
                 'total_s': 720},
                {'grain': QUIET, 'kind': 'story', 'size': 'm',
                 'dispatches': 0, 'usage': blank_usage(), 'tool_calls': None,
                 'duration_s': None, 'agent_types': [],
                 'states': {'todo': None, 'wip': None, 'review': None,
                            'blocked': None},
                 'total_s': None},
                {'grain': FEATURE, 'kind': 'feature', 'size': None,
                 'dispatches': 2, 'usage': full, 'tool_calls': 37,
                 'duration_s': 812, 'agent_types': [dev, rev],
                 'states': {'planning': None, 'ready': None, 'building': None,
                            'review': None},
                 'total_s': None},
                {'grain': BUG, 'kind': 'bug', 'size': None, 'dispatches': 0,
                 'usage': blank_usage(), 'tool_calls': None,
                 'duration_s': None, 'agent_types': [],
                 'states': {'open': None, 'fixed': 30}, 'total_s': 30},
            ],
            'unattributed': {'dispatches': 1,
                             'usage': dict(blank_usage(), input=5),
                             'tool_calls': 2, 'duration_s': None},
            'totals': {'dispatch_rows': 3, 'status_rows': 5, 'grains': 4,
                       'usage': dict(full, input=1205), 'tool_calls': 39,
                       'duration_s': 812},
        })
        self.assertEqual(sorted(data), sorted(SPEND_KEYS + SECTION_KEYS))

    def test_json_prints_an_object_even_with_no_ledger_at_all(self):
        with tree(story_statuses=('done', 'todo')) as root:
            data = self.payload(root)
        self.assertEqual(data['totals'],
                         {'dispatch_rows': 0, 'status_rows': 0, 'grains': 3,
                          'usage': blank_usage(), 'tool_calls': None,
                          'duration_s': None})


class Resolution(unittest.TestCase):
    """Which milestone's ledger — the building one, or the one you named."""

    def test_the_default_is_the_building_milestone(self):
        with tree(story_statuses=('done', 'todo')) as root:
            seeded(root)
            named = report(root, '0.1')
            default = report(root)
        self.assertEqual(default[0], 0, default[1])
        self.assertEqual(section_of(default[1], SPEND_TITLE), TABLE)
        self.assertEqual(default, named)

    def test_an_explicit_id_reads_that_milestone_not_the_building_one(self):
        with tree(story_statuses=('done', 'todo')) as root:
            seeded(root)
            write(root / 'pm/roadmap/0.2-next/milestone.md',
                  {'id': '"0.2"', 'name': 'Next', 'status': 'planning'})
            code, out = report(root, '0.2')
        self.assertEqual(code, 0, out)
        self.assertEqual(out.strip(), '[ledger:report] 0.2 — no ledger')

    def test_no_ledger_file_is_exit_zero_and_one_line(self):
        with tree(story_statuses=('done', 'todo')) as root:
            code, out = report(root, '0.1')
        self.assertEqual(code, 0, out)
        self.assertEqual(out.strip(), '[ledger:report] 0.1 — no ledger')


class Refusals(unittest.TestCase):
    """SDLC § 5's matrix. Exit 2 on input, never on a number."""

    def refuses(self, root, *argv, needle: str = '') -> str:
        code, out = report(root, *argv)
        self.assertEqual(code, 2, out)
        if needle:
            self.assertIn(needle, out)
        return out

    def test_a_malformed_ledger_line_names_its_line_number(self):
        with tree(story_statuses=('done', 'todo')) as root:
            put_ledger(root,
                       status_line('2026-09-03T10:00:00Z', STORY, 'todo',
                                   'wip'),
                       '{not json',
                       status_line('2026-09-03T10:01:00Z', STORY, 'wip',
                                   'review'))
            self.refuses(root, '0.1', needle='line 2')
            self.refuses(root, '0.1', '--json', needle='line 2')

    def test_an_unknown_milestone_id(self):
        with tree() as root:
            self.refuses(root, '0.9', needle='no grain resolves')

    def test_two_building_milestones_with_no_id_are_named_never_chosen(self):
        with tree() as root:
            write(root / 'pm/roadmap/0.2-next/milestone.md',
                  {'id': '"0.2"', 'name': 'Next', 'status': 'building'})
            out = self.refuses(root, needle='2 milestones are building')
            self.assertIn('0.1 0.2', out)
            self.assertIn('pm ledger report <milestone-id>', out)
            self.assertEqual(report(root, '0.1')[0], 0)

    def test_no_building_milestone_and_no_id(self):
        with tree(milestone_status='planning') as root:
            self.refuses(root, needle='is `building`')

    def test_a_flag_that_is_not_json(self):
        # `--from` left this list when it became a flag this verb HAS; its own
        # refusals (a rev that will not resolve, a rev that is a flag, a rev
        # with whitespace in it, `--from` with no milestone id) are the matrix
        # in test_pm_ledger_report_git.py. `--json=1` and `-j` stay: neither
        # spelling is a flag here, and a verb that quietly accepted one would
        # be inventing a grammar its own --help does not print.
        with tree() as root:
            for flag in ('--wombat', '-j', '--json=1', '-'):
                self.refuses(root, flag, needle='unknown flag')

    def test_two_positional_arguments(self):
        with tree() as root:
            self.refuses(root, '0.1', '0.2', needle='one milestone id')

    def test_a_grain_that_is_not_a_milestone(self):
        with tree() as root:
            bug(root, 'crash')
            for gid in (FEATURE, STORY, BUG):
                self.refuses(root, gid, needle='not a milestone')

    def test_the_id_grammar_refuses_traversal_absolutes_globs_backslashes(self):
        hostile = ('0.1/../0.1', '../0.1', '/etc/hosts', '0.*', '0.1/',
                   '[0].1', '0.1\\x', '.', '..', '', ' ', 'x' * 300)
        with tree() as root:
            for mid in hostile:
                # The resolver `pm get`/`pm set`/`ledger show` already use, so
                # the grammar cannot refuse differently here than there.
                self.refuses(root, mid, needle='resolves from id')


if __name__ == '__main__':  # pragma: no cover
    unittest.main()
