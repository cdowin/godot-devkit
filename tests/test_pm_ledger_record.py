"""test_pm_ledger_record.py — `pm ledger record` and `pm ledger show`.

The contract under test, in Chris's words (2026-09-03): *"the ledger is
actually very very simple. It shouldn't judge or infer or even guard really
anything … It just timestamps transitions and stamps whatever hook data.
Judgement/inference is left to the caller."* So:

  * a transcript's numbers are COPIED — sums, counts, first/last stamp, model —
    and a field the transcript lacks is an absent KEY, never a zero and never a
    label (no `unattributed`, no `?`, no weight, no cost);
  * every row carries D3's `tree` snapshot: the ACTIVE tree's live state at the
    instant of the write, every candidate id verbatim, empty lists when empty;
  * the refusals are input hygiene only (SDLC § 5) — a path that is not a file,
    a line that is not JSON, a number that is not a number, an unknown
    `--event`, a `--grain` that resolves to nothing — plus the one question the
    verb cannot answer, which milestone owns the row when two are building;
  * a transcript with NO assistant record REFUSES (exit 2). A row of zeros is
    indistinguishable afterwards from a cheap dispatch, which is hard rule 4's
    read-side sin with a timestamp on it;
  * `pm ledger show` is a subtraction over raw rows (D8), and prints a total
    only when the grain actually reached its vocabulary's last state.

THE FIXTURES (tests/fixtures/transcripts/):

  * `subagent-dispatch.jsonl` — the first 60 records of a REAL subagent
    transcript (`~/.claude/projects/…/subagents/agent-*.jsonl`, 2026-08-29),
    scrubbed: every key kept, every string value replaced by `"x"` except the
    ones the parser reads (`type`, `timestamp`, the ids, `message.model`, block
    `type`s and tool `name`s) and the `usage` numbers. Volume, not shape, was
    trimmed twice: the prefix is 60 of 120 records and only the FIRST assistant
    record keeps the whole `usage` subtree the API sends — that one record is
    what proves the extra keys are ignored rather than copied.
  * `main-session.jsonl` — the Stop shape, written by hand: `isSidechain:
    false`, no `agentId`, two models across the session, one assistant
    record with no `usage` at all, and one `<synthetic>` API-error record —
    the shape Claude Code writes when it generates an assistant turn itself
    (`isApiErrorMessage`, an all-zero `usage`, `model: "<synthetic>"`).
"""
from __future__ import annotations

import json
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from support.pm import ledger_lines, ledger_rows, run_cli, tree, write

from godot_devkit.repo.pm import ledger

FIXTURES = Path(__file__).parent / 'fixtures' / 'transcripts'
SUBAGENT = FIXTURES / 'subagent-dispatch.jsonl'
MAIN_SESSION = FIXTURES / 'main-session.jsonl'

STORY = '0.1/alpha/s0'
BUG = '0.1/bugs/b0'
LEDGER_REL = 'pm/roadmap/0.1-demo/ledger.jsonl'

# The tree `support.pm.tree()` builds: one milestone `building`, one feature
# `building`, and whatever story statuses the case asked for.
STOCK_TREE = {'milestones_building': ['0.1'], 'features_building': ['0.1/alpha'],
              'features_review': [], 'stories_wip': [], 'stories_review': []}


def fresh(**over) -> dict:
    snap = dict(STOCK_TREE)
    snap.update(over)
    return snap


def record(root, *argv) -> tuple[int, str]:
    return run_cli(root, 'ledger', 'record', *argv)


def only_row(root) -> dict:
    rows = ledger_rows(root)
    assert len(rows) == 1, f'expected one row, got {rows}'
    return rows[0]


def stamped(row: dict) -> dict:
    """The row minus `ts`, having asserted `ts` is a fresh full-UTC stamp."""
    when = datetime.strptime(row['ts'], ledger.TS_FORMAT).replace(
        tzinfo=timezone.utc)
    assert abs(when - datetime.now(timezone.utc)) < timedelta(minutes=5), row
    return {k: v for k, v in row.items() if k != 'ts'}


def put_ledger(root, *lines: str) -> None:
    path = root / LEDGER_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(''.join(line + '\n' for line in lines), encoding='utf-8')


def status_line(ts: str, grain: str, frm: str, to: str) -> str:
    return ledger.dumps(ledger.status_row(grain, frm, to, ts=ts))


def bug_doc(root, status: str = 'open') -> None:
    write(root / 'pm/roadmap/0.1-demo/bugs/b0.md',
          {'id': BUG, 'milestone': '"0.1"', 'name': 'B0', 'status': status})


class TranscriptRow(unittest.TestCase):
    """The scrubbed fixture in, one exact row out — every key asserted."""

    def test_the_subagent_fixture_produces_this_exact_dispatch_row(self):
        with tree(story_statuses=('wip',)) as root:
            code, out = record(root, '--from-transcript', str(SUBAGENT),
                               '--event', 'SubagentStop',
                               '--agent-type', 'developer')
            self.assertEqual(code, 0, out)
            row = only_row(root)
        self.assertEqual(stamped(row), {
            'kind': 'dispatch',
            'session_id': '406aac76-fb60-4d90-9383-5b0af2163067',
            'agent_id': 'a0c097f0217026051',
            'agent_type': 'developer',
            'model': 'claude-sonnet-5',
            'started_at': '2026-08-29T03:38:09Z',
            'ended_at': '2026-08-29T03:39:29Z',
            'duration_s': 80,
            'messages': 36,
            'tool_calls': 23,
            'tools': {'Bash': 22, 'Write': 1},
            'tool_calls_before_first_write': 20,
            'usage': {'input': 72, 'output': 5829, 'cache_creation': 165473,
                      'cache_read': 1820260},
            'tree': fresh(stories_wip=[STORY]),
        })

    def test_the_row_keys_are_in_the_order_feature_md_writes_them(self):
        with tree() as root:
            self.assertEqual(record(root, '--from-transcript', str(SUBAGENT),
                                    '--event', 'SubagentStop')[0], 0)
            row = only_row(root)
        self.assertEqual(list(row), [
            'ts', 'kind', 'session_id', 'agent_id', 'model', 'started_at',
            'ended_at', 'duration_s', 'messages', 'tool_calls', 'tools',
            'tool_calls_before_first_write', 'usage', 'tree'])

    def test_a_field_nothing_supplied_is_an_absent_key_never_a_label(self):
        """No `--agent-type` and no transcript field for it: no key at all."""
        with tree() as root:
            self.assertEqual(record(root, '--from-transcript', str(SUBAGENT),
                                    '--event', 'SubagentStop')[0], 0)
            row = only_row(root)
        self.assertNotIn('agent_type', row)
        self.assertNotIn('grain', row)
        self.assertNotIn('unattributed', json.dumps(row))
        self.assertNotIn('?', json.dumps(row))

    def test_one_row_is_one_compact_line(self):
        with tree() as root:
            self.assertEqual(record(root, '--from-transcript', str(SUBAGENT),
                                    '--event', 'SubagentStop')[0], 0)
            lines = ledger_lines(root)
        self.assertEqual(len(lines), 1)
        self.assertEqual(lines[0], json.dumps(json.loads(lines[0]),
                                              separators=(',', ':')))

    def test_the_flags_win_over_the_transcripts_own_ids(self):
        with tree() as root:
            self.assertEqual(record(root, '--from-transcript', str(SUBAGENT),
                                    '--event', 'SubagentStop',
                                    '--session-id', 'S', '--agent-id', 'A')[0], 0)
            row = only_row(root)
        self.assertEqual((row['session_id'], row['agent_id']), ('S', 'A'))

    def test_the_main_session_fixture_produces_a_session_row(self):
        with tree() as root:
            code, out = record(root, '--from-transcript', str(MAIN_SESSION),
                               '--event', 'Stop')
            self.assertEqual(code, 0, out)
            row = only_row(root)
        self.assertEqual(stamped(row), {
            'kind': 'session',
            'session_id': '11111111-2222-3333-4444-555555555555',
            # Two models in one session is a LIST, raw — never a pick. The
            # fixture's `<synthetic>` record is not a third: it is Claude
            # Code's marker for an assistant turn IT generated, not a model
            # identifier (0.23.0/ledger D3).
            'model': ['claude-opus-5', 'claude-sonnet-5'],
            'started_at': '2026-09-03T10:00:00Z',
            'ended_at': '2026-09-03T10:07:36Z',
            'duration_s': 456,
            # Four assistant records: one carries no `usage` at all and the
            # `<synthetic>` one carries an all-zero usage. Both count as a
            # message and add zero — dropped from `model`, counted everywhere
            # else, because the record HAPPENED.
            'messages': 4,
            'tool_calls': 3,
            'tools': {'Read': 1, 'Edit': 1, 'Bash': 1},
            'tool_calls_before_first_write': 1,
            'usage': {'input': 15, 'output': 1240, 'cache_creation': 5000,
                      'cache_read': 181000},
            'tree': fresh(),
        })

    def test_a_main_session_row_carries_no_agent_id_because_there_is_none(self):
        with tree() as root:
            self.assertEqual(record(root, '--from-transcript',
                                    str(MAIN_SESSION), '--event', 'Stop')[0], 0)
            self.assertNotIn('agent_id', only_row(root))

    # --- `<synthetic>` is not a model (0.23.0/ledger D3) ----------------------
    # A spelling, not a judgement: Claude Code writes `model: "<synthetic>"` on
    # an assistant record IT generated (an API-error notice, with an all-zero
    # `usage`). D4's "never interpret `message.model`" is about not
    # second-guessing a real identifier; a bracketed pseudo-name is not one.
    def assistant(self, model: str, ts: str = '2026-09-03T10:00:00Z') -> dict:
        return {'type': 'assistant', 'timestamp': ts,
                'message': {'model': model,
                            'usage': {'input_tokens': 1, 'output_tokens': 2}}}

    def test_the_synthetic_pseudo_name_is_dropped_from_the_model_list(self):
        summary = ledger.transcript_summary(enumerate([
            self.assistant('claude-fable-5-1'),
            self.assistant('<synthetic>', '2026-09-03T10:00:30Z'),
        ], 1))
        self.assertEqual(summary['model'], 'claude-fable-5-1')

    def test_the_synthetic_record_still_counts_as_a_message_and_its_usage(self):
        """Dropped from ONE field, not from the row. The record happened; a
        summary that also stopped counting it would answer "what did this
        session cost" with a number that is quietly short (hard rule 4)."""
        summary = ledger.transcript_summary(enumerate([
            self.assistant('claude-fable-5-1'),
            self.assistant('<synthetic>', '2026-09-03T10:00:30Z'),
        ], 1))
        self.assertEqual(summary['messages'], 2)
        self.assertEqual(summary['usage']['input'], 2)
        self.assertEqual(summary['usage']['output'], 4)

    def test_a_transcript_of_only_synthetic_records_carries_no_model_key(self):
        """No model ran, so the row says nothing about one. `None` is what
        `usage_row` omits — the absence rule already in force for every field
        the source did not state, never a placeholder."""
        summary = ledger.transcript_summary(enumerate([
            self.assistant('<synthetic>')], 1))
        self.assertIsNone(summary['model'])
        self.assertEqual(summary['messages'], 1)
        self.assertNotIn('model', ledger.usage_row('session', **summary))

    def test_a_genuine_model_name_is_never_dropped(self):
        """Every model identifier the corpus actually carries, each proven to
        survive. The rule removes ONE non-value; a rule that also swallowed a
        real name would silently rewrite the answer to "which model ran"."""
        for name in ('claude-opus-5', 'claude-sonnet-5', 'claude-fable-5',
                     'claude-fable-5-1', 'claude-opus-4-8',
                     'claude-haiku-4-5-20251001'):
            with self.subTest(model=name):
                summary = ledger.transcript_summary(enumerate([
                    self.assistant('<synthetic>'),
                    self.assistant(name, '2026-09-03T10:00:30Z'),
                ], 1))
                self.assertEqual(summary['model'], name)

    def test_another_bracketed_pseudo_name_is_still_carried_raw(self):
        """The rule is the ONE string, not the `<…>` shape, and that is the
        decision (D3): a census of 734 real transcripts found `<synthetic>` and
        no other bracketed value in this position. Dropping the shape would
        make the next pseudo-name — whatever Claude Code invents — vanish from
        the one field that would have reported it, which is narrowing the
        census instead of reading it. So an unknown one comes through raw, and
        gets decided the same way `<synthetic>` was."""
        summary = ledger.transcript_summary(enumerate([
            self.assistant('<compaction>')], 1))
        self.assertEqual(summary['model'], '<compaction>')

    def test_only_the_exact_token_is_the_pseudo_name(self):
        """Substring, prefix, suffix and case-folding are all wrong readings of
        an exact token. Each name below is one a looser rule would swallow."""
        for name in ('<synthetic', 'synthetic>', 'x<synthetic>y',
                     'claude-synthetic-5', '<SYNTHETIC>'):
            with self.subTest(model=name):
                summary = ledger.transcript_summary(
                    enumerate([self.assistant(name)], 1))
                self.assertEqual(summary['model'], name)

    def test_a_dispatch_that_never_wrote_reports_its_whole_tool_count(self):
        """`tool_calls_before_first_write` is the whole count when no write ever
        happened — not zero. A read-only dispatch did all of its work before a
        write that never came, and a 0 there would read as 'wrote immediately'."""
        summary = ledger.transcript_summary(enumerate([
            {'type': 'assistant', 'timestamp': '2026-09-03T10:00:00Z',
             'message': {'content': [{'type': 'tool_use', 'name': 'Read'},
                                     {'type': 'tool_use', 'name': 'Bash'}]}},
        ], 1))
        self.assertEqual(summary['tool_calls'], 2)
        self.assertEqual(summary['tool_calls_before_first_write'], 2)

    def test_milliseconds_are_truncated_not_rounded(self):
        self.assertEqual(ledger.normalise_ts('2026-08-29T03:38:09.719Z', 'x'),
                         '2026-08-29T03:38:09Z')

    def test_an_offset_stamp_is_converted_to_utc_not_relabelled(self):
        self.assertEqual(ledger.normalise_ts('2026-08-29T05:38:09+02:00', 'x'),
                         '2026-08-29T03:38:09Z')


class TreeSnapshot(unittest.TestCase):
    """D3: the ACTIVE tree's live state, verbatim, on every row."""

    def build(self, root) -> None:
        """A second feature at `review` over a story at `review`."""
        beta = root / 'pm/roadmap/0.1-demo/features/beta'
        write(beta / 'feature.md',
              {'id': '0.1/beta', 'milestone': '"0.1"', 'name': 'Beta',
               'status': 'review', 'reviewed': ''})
        write(beta / 'stories/b0.md',
              {'id': '0.1/beta/b0', 'feature': '0.1/beta', 'milestone': '"0.1"',
               'name': 'B0', 'status': 'review'})

    def test_one_wip_one_review_one_building_feature_one_review_feature(self):
        with tree(story_statuses=('wip', 'done')) as root:
            self.build(root)
            self.assertEqual(record(root, '--from-transcript', str(SUBAGENT),
                                    '--event', 'SubagentStop')[0], 0)
            snap = only_row(root)['tree']
        self.assertEqual(snap, {
            'milestones_building': ['0.1'],
            'features_building': ['0.1/alpha'],
            'features_review': ['0.1/beta'],
            'stories_wip': [STORY],
            'stories_review': ['0.1/beta/b0'],
        })

    def test_every_bucket_is_present_and_empty_rather_than_absent(self):
        with tree(story_statuses=('todo',)) as root:
            self.assertEqual(record(root, '--from-transcript', str(SUBAGENT),
                                    '--event', 'SubagentStop')[0], 0)
            snap = only_row(root)['tree']
        self.assertEqual(snap, fresh())
        self.assertEqual([k for k, v in snap.items() if v == []],
                         ['features_review', 'stories_wip', 'stories_review'])

    def test_the_archived_tree_is_not_the_live_tree(self):
        """`zz_archive/` is excluded by the same walkers `check pm` uses."""
        with tree() as root:
            archived = root / 'pm/roadmap/zz_archive/0.0-old'
            write(archived / 'milestone.md',
                  {'id': '"0.0"', 'name': 'Old', 'status': 'building'})
            write(archived / 'features/gamma/feature.md',
                  {'id': '0.0/gamma', 'milestone': '"0.0"', 'name': 'G',
                   'status': 'building', 'reviewed': ''})
            self.assertEqual(record(root, '--from-transcript', str(SUBAGENT),
                                    '--event', 'SubagentStop')[0], 0)
            snap = only_row(root)['tree']
        self.assertEqual(snap, fresh())

    def test_the_ids_are_sorted_so_two_rows_of_one_state_compare(self):
        with tree(story_statuses=('wip', 'wip', 'wip')) as root:
            self.assertEqual(record(root, '--from-transcript', str(SUBAGENT),
                                    '--event', 'SubagentStop')[0], 0)
            wip = only_row(root)['tree']['stories_wip']
        self.assertEqual(wip, sorted(wip))
        self.assertEqual(wip, ['0.1/alpha/s0', '0.1/alpha/s1', '0.1/alpha/s2'])


class HandEntry(unittest.TestCase):
    """`--grain`: the same row shape, from a person, for a dispatch no hook saw."""

    def test_a_hand_row_round_trips_with_exactly_the_keys_given(self):
        with tree(story_statuses=('wip',)) as root:
            code, out = record(root, '--grain', STORY, '--agent-type',
                               'reviewer', '--tokens-in', '1200',
                               '--tokens-out', '38000', '--tool-calls', '37',
                               '--duration-s', '812')
            self.assertEqual(code, 0, out)
            row = only_row(root)
        self.assertEqual(stamped(row), {
            'kind': 'dispatch',
            'grain': STORY,
            'agent_type': 'reviewer',
            'duration_s': 812,
            'tool_calls': 37,
            # `cache_creation`/`cache_read` are ABSENT, not 0 — nobody counted
            # them, and a 0 would say they were counted and were none.
            'usage': {'input': 1200, 'output': 38000},
            'tree': fresh(stories_wip=[STORY]),
        })

    def test_a_number_not_given_is_a_key_the_row_does_not_carry(self):
        with tree() as root:
            self.assertEqual(record(root, '--grain', STORY)[0], 0)
            row = only_row(root)
        for absent in ('usage', 'tool_calls', 'duration_s', 'messages',
                       'tools', 'model', 'started_at', 'ended_at'):
            self.assertNotIn(absent, row)
        self.assertEqual(row['grain'], STORY)

    def test_zero_is_recorded_because_zero_is_a_measurement(self):
        with tree() as root:
            self.assertEqual(record(root, '--grain', STORY, '--tool-calls',
                                    '0', '--tokens-in', '0')[0], 0)
            row = only_row(root)
        self.assertEqual(row['tool_calls'], 0)
        self.assertEqual(row['usage'], {'input': 0})

    def test_the_grain_recorded_is_the_files_own_id(self):
        with tree() as root:
            self.assertEqual(record(root, '--grain', '0.1')[0], 0)
            # The milestone doc's `id: "0.1"` — unquoted, as every other row
            # in this file spells it.
            self.assertEqual(only_row(root)['grain'], '0.1')

    def test_the_event_flag_switches_a_hand_row_to_a_session_row(self):
        with tree() as root:
            self.assertEqual(record(root, '--grain', STORY,
                                    '--event', 'Stop')[0], 0)
            self.assertEqual(only_row(root)['kind'], 'session')


class Show(unittest.TestCase):
    """`pm ledger show` — a subtraction over raw rows, and nothing more."""

    TIMELINE = ('2026-09-03T10:00:00Z', '2026-09-03T10:13:32Z',
                '2026-09-03T10:20:00Z')

    def timeline(self, root, last_to: str = 'done') -> None:
        one, two, three = self.TIMELINE
        put_ledger(root,
                   status_line(one, STORY, 'todo', 'wip'),
                   status_line(two, STORY, 'wip', 'review'),
                   status_line(three, STORY, 'review', last_to))

    def test_the_human_form_is_one_line_per_row_with_the_gap_after_the_first(self):
        with tree() as root:
            self.timeline(root)
            code, out = run_cli(root, 'ledger', 'show', STORY)
        self.assertEqual(code, 0, out)
        self.assertEqual(out.strip().splitlines(), [
            '2026-09-03T10:00:00Z  status    todo -> wip',
            '2026-09-03T10:13:32Z  status    wip -> review  +812s',
            '2026-09-03T10:20:00Z  status    review -> done  +388s',
            # `done` is terminal for a story, so the run ends with the total.
            'first row → terminal row: 1200s',
        ])

    def test_the_total_line_prints_when_the_grain_reached_its_last_state(self):
        """A bug's vocabulary ends `closed`, so its terminal row is unambiguous."""
        with tree() as root:
            bug_doc(root, 'closed')
            put_ledger(root,
                       status_line('2026-09-03T10:00:00Z', BUG, 'open', 'fixed'),
                       status_line('2026-09-03T10:00:30Z', BUG, 'fixed',
                                   'closed'))
            code, out = run_cli(root, 'ledger', 'show', BUG)
        self.assertEqual(code, 0, out)
        self.assertIn('first row → terminal row: 30s', out)

    def test_no_total_line_while_the_grain_is_still_in_flight(self):
        with tree() as root:
            bug_doc(root)
            put_ledger(root,
                       status_line('2026-09-03T10:00:00Z', BUG, 'open',
                                   'fixed'))
            code, out = run_cli(root, 'ledger', 'show', BUG)
        self.assertEqual(code, 0, out)
        self.assertNotIn('terminal row', out)

    def test_done_ends_a_story_and_blocked_does_not(self):
        """`done` is NAMED, never `story_states[-1]` — which is `blocked`.

        The stock vocabulary is `todo wip review done blocked`, so reading the
        tuple's last entry would have printed a total for a story that STALLED
        and none for a story that finished. The order is `pm vocabulary`'s
        output and a consumer contract, so the state is named instead — and
        `done` is the one every drift rule in model.py already treats as
        terminal (D2, D3, D5).
        """
        with tree() as root:
            self.timeline(root, last_to='done')
            done_out = run_cli(root, 'ledger', 'show', STORY)[1]
            self.timeline(root, last_to='blocked')
            blocked_out = run_cli(root, 'ledger', 'show', STORY)[1]
        self.assertIn('first row → terminal row: 1200s', done_out)
        self.assertNotIn('terminal row', blocked_out)

    def test_only_status_rows_bound_the_total(self):
        """R3: a `decision` row names a grain; it does not move one.

        The total is the grain's first STATUS row to its terminal one. A
        decision logged before work started, or a dispatch that stopped after
        it closed, are both rows ABOUT the grain and neither is a transition —
        counting them would print a duration the per-row gaps above contradict.
        """
        with tree() as root:
            put_ledger(root,
                       ledger.dumps(ledger.decision_row(
                           STORY, 'D1', 'why', ts='2026-09-03T09:00:00Z')),
                       status_line('2026-09-03T10:00:00Z', STORY, 'todo',
                                   'wip'),
                       status_line('2026-09-03T10:15:00Z', STORY, 'wip',
                                   'done'))
            out = run_cli(root, 'ledger', 'show', STORY)[1]
        self.assertIn('first row → terminal row: 900s', out)
        self.assertNotIn('4500s', out)

    def test_a_dispatch_after_the_terminal_row_does_not_extend_the_total(self):
        with tree() as root:
            put_ledger(root,
                       status_line('2026-09-03T10:00:00Z', STORY, 'todo',
                                   'wip'),
                       status_line('2026-09-03T10:15:00Z', STORY, 'wip',
                                   'done'))
            before = run_cli(root, 'ledger', 'show', STORY)[1]
            self.assertEqual(record(root, '--grain', STORY,
                                    '--duration-s', '30')[0], 0)
            after = run_cli(root, 'ledger', 'show', STORY)[1]
        self.assertIn('first row → terminal row: 900s', before)
        self.assertIn('first row → terminal row: 900s', after)

    def test_a_bug_ends_at_its_configured_last_state(self):
        """The one kind D8 leaves to the config: `[pm] bug_states[-1]`."""
        with tree() as root:
            bug_doc(root, 'closed')
            put_ledger(root,
                       status_line('2026-09-03T10:00:00Z', BUG, 'open', 'done'),
                       status_line('2026-09-03T10:00:30Z', BUG, 'done',
                                   'closed'))
            out = run_cli(root, 'ledger', 'show', BUG)[1]
        self.assertIn('first row → terminal row: 30s', out)

    def test_the_rule_lives_in_ledger_py_and_nowhere_else(self):
        cfg = type('C', (), {'bug_states': ('open', 'fixed', 'shut')})()
        self.assertEqual(ledger.terminal_state(cfg, 'story'), 'done')
        self.assertEqual(ledger.terminal_state(cfg, 'feature'), 'done')
        self.assertEqual(ledger.terminal_state(cfg, 'milestone'), 'done')
        self.assertEqual(ledger.terminal_state(cfg, ledger.GRAIN_BUG), 'shut')

    def test_json_prints_the_raw_lines_and_nothing_else(self):
        with tree() as root:
            self.timeline(root)
            code, out = run_cli(root, 'ledger', 'show', STORY, '--json')
            expected = ledger_lines(root)
        self.assertEqual(code, 0, out)
        self.assertEqual(out.strip().splitlines(), expected)

    def test_a_dispatch_row_is_found_through_the_tree_snapshot(self):
        with tree(story_statuses=('wip',)) as root:
            self.assertEqual(record(root, '--from-transcript', str(SUBAGENT),
                                    '--event', 'SubagentStop')[0], 0)
            story_out = run_cli(root, 'ledger', 'show', STORY)[1]
            milestone_out = run_cli(root, 'ledger', 'show', '0.1')[1]
        self.assertIn('dispatch', story_out)
        self.assertIn('dispatch', milestone_out)

    def test_a_row_naming_another_grain_is_not_this_grains_row(self):
        with tree() as root:
            bug_doc(root)
            put_ledger(root,
                       status_line('2026-09-03T10:00:00Z', BUG, 'open',
                                   'fixed'))
            code, out = run_cli(root, 'ledger', 'show', STORY)
        self.assertEqual(code, 0, out)
        self.assertIn(f'no rows for {STORY}', out)

    def test_no_rows_is_exit_zero_because_it_is_a_fact(self):
        with tree() as root:
            code, out = run_cli(root, 'ledger', 'show', STORY)
        self.assertEqual(code, 0, out)
        self.assertIn(f'no rows for {STORY}', out)

    def test_a_malformed_ledger_line_refuses_and_names_the_line(self):
        with tree() as root:
            put_ledger(root,
                       status_line('2026-09-03T10:00:00Z', STORY, 'todo',
                                   'wip'),
                       '{not json',
                       status_line('2026-09-03T10:01:00Z', STORY, 'wip',
                                   'review'))
            code, out = run_cli(root, 'ledger', 'show', STORY)
        self.assertEqual(code, 2, out)
        self.assertIn('line 2', out)


class RowsThisVersionNeverWrote(unittest.TestCase):
    """`ledger.jsonl` is `merge=union`, so the reader meets shapes it never emitted.

    Another milestone branch's rows, a newer version of this package's rows and
    a hand edit all land in this file without passing through `usage_row`, and
    `read_rows` deliberately accepts any JSON OBJECT as a row. So the matcher
    above it has to answer "does this row name the grain" for values that are
    not strings at all. `{} in names` raises `TypeError`; the honest answer is
    False — a value that cannot be a grain id does not name one — and a
    traceback would take out the whole timeline over one line, at exit 1, which
    hard rule 6 spells "findings".
    """

    def show(self, *rows: str, grain: str = STORY):
        with tree() as root:
            put_ledger(root,
                       status_line('2026-09-03T10:00:00Z', STORY, 'todo',
                                   'wip'),
                       *rows)
            return run_cli(root, 'ledger', 'show', grain)

    def test_a_tree_bucket_holding_an_object_does_not_crash_the_timeline(self):
        code, out = self.show(
            '{"ts":"2026-09-03T10:01:00Z","kind":"dispatch",'
            '"tree":{"stories_wip":[{"id":"' + STORY + '"}]}}')
        self.assertEqual(code, 0, out)
        self.assertIn('todo -> wip', out)

    def test_a_tree_bucket_holding_a_list_or_null_does_not_crash(self):
        code, out = self.show(
            '{"ts":"2026-09-03T10:01:00Z","kind":"dispatch",'
            '"tree":{"stories_wip":[null,3,["' + STORY + '"]]}}')
        self.assertEqual(code, 0, out)
        self.assertIn('todo -> wip', out)

    def test_a_grain_key_that_is_not_a_string_does_not_crash(self):
        code, out = self.show(
            '{"ts":"2026-09-03T10:01:00Z","kind":"status",'
            '"grain":{"id":"' + STORY + '"},"from":"a","to":"b"}')
        self.assertEqual(code, 0, out)
        self.assertIn('todo -> wip', out)

    def test_such_a_row_does_not_become_this_grains_row(self):
        """Not crashing is half of it: the match must still be False.

        A dict whose `id` happens to spell the grain is not the grain being
        named — reading it as one would put another row's cost on this
        timeline, which is the same lie the crash was hiding.
        """
        self.assertFalse(ledger.row_names(
            {'grain': {'id': STORY}, 'tree': {'stories_wip': [{'id': STORY}]}},
            {STORY}))
        self.assertTrue(ledger.row_names(
            {'tree': {'stories_wip': [STORY]}}, {STORY}))


class Refusals(unittest.TestCase):
    """SDLC § 5's matrix. Every one of these refuses WITHOUT writing a row."""

    def refuses(self, root, *argv, needle: str = '') -> str:
        before = ledger_lines(root)
        code, out = record(root, *argv)
        self.assertEqual(code, 2, out)
        self.assertEqual(ledger_lines(root), before,
                         f'a refusal wrote a row: {argv}')
        if needle:
            self.assertIn(needle, out)
        return out

    def test_a_path_that_is_not_a_file(self):
        with tree() as root:
            self.refuses(root, '--from-transcript', str(root / 'nope.jsonl'),
                         '--event', 'Stop', needle='is not a file')
            self.refuses(root, '--from-transcript', str(root),
                         '--event', 'Stop', needle='is not a file')

    def test_a_line_that_is_not_json_names_its_line_number(self):
        with tree() as root:
            bad = root / 'bad.jsonl'
            lines = SUBAGENT.read_text(encoding='utf-8').splitlines()[:5]
            lines.insert(3, '{"type": "assistant"')
            bad.write_text('\n'.join(lines) + '\n', encoding='utf-8')
            self.refuses(root, '--from-transcript', str(bad),
                         '--event', 'SubagentStop', needle='line 4')

    def test_a_transcript_with_no_assistant_record_is_never_a_row_of_zeros(self):
        with tree() as root:
            empty = root / 'empty.jsonl'
            empty.write_text(json.dumps(
                {'type': 'user', 'timestamp': '2026-09-03T10:00:00Z',
                 'message': {'role': 'user', 'content': 'x'}}) + '\n',
                encoding='utf-8')
            self.refuses(root, '--from-transcript', str(empty),
                         '--event', 'Stop',
                         needle='no assistant record — nothing to sum')

    def test_a_token_count_that_is_not_a_number_fails_loudly(self):
        with tree() as root:
            shaped = root / 'shaped.jsonl'
            shaped.write_text(json.dumps(
                {'type': 'assistant', 'timestamp': '2026-09-03T10:00:00Z',
                 'message': {'model': 'm',
                             'usage': {'input_tokens': '12'}}}) + '\n',
                encoding='utf-8')
            self.refuses(root, '--from-transcript', str(shaped),
                         '--event', 'Stop', needle='is not a number')

    def test_a_timestamp_that_is_not_a_timestamp_fails_loudly(self):
        with tree() as root:
            shaped = root / 'shaped.jsonl'
            shaped.write_text(json.dumps(
                {'type': 'assistant', 'timestamp': 'yesterday',
                 'message': {'model': 'm', 'usage': {'input_tokens': 1}}}) + '\n',
                encoding='utf-8')
            self.refuses(root, '--from-transcript', str(shaped),
                         '--event', 'Stop', needle='not ISO-8601')

    def test_no_building_milestone_says_so_rather_than_picking_one(self):
        with tree(milestone_status='planning') as root:
            self.refuses(root, '--from-transcript', str(SUBAGENT),
                         '--event', 'SubagentStop', needle='is `building`')

    def test_two_building_milestones_are_named_never_chosen(self):
        with tree() as root:
            write(root / 'pm/roadmap/0.2-next/milestone.md',
                  {'id': '"0.2"', 'name': 'Next', 'status': 'building'})
            out = self.refuses(root, '--from-transcript', str(SUBAGENT),
                               '--event', 'SubagentStop',
                               needle='2 milestones are building')
            self.assertIn('0.1 0.2', out)
            self.assertEqual(ledger_lines(root, 'pm/roadmap/0.2-next/'
                                                'ledger.jsonl'), [])

    def test_an_unknown_event(self):
        with tree() as root:
            self.refuses(root, '--from-transcript', str(SUBAGENT),
                         '--event', 'Wombat', needle='is not a hook event')
            self.refuses(root, '--grain', STORY, '--event', 'subagentstop',
                         needle='is not a hook event')

    def test_a_transcript_run_without_an_event(self):
        with tree() as root:
            self.refuses(root, '--from-transcript', str(SUBAGENT),
                         needle='--event is required')

    def test_bad_numbers_on_every_numeric_flag(self):
        bad = ('-1', '3.5', 'twelve', '', ' 7', '1_0', '٣', '0x10', '1e3')
        with tree() as root:
            for flag in ('--tokens-in', '--tokens-out', '--tool-calls',
                         '--duration-s'):
                for value in bad:
                    self.refuses(root, '--grain', STORY, f'{flag}={value}',
                                 needle='non-negative integer')

    def test_both_sources_at_once(self):
        with tree() as root:
            self.refuses(root, '--grain', STORY, '--from-transcript',
                         str(SUBAGENT), '--event', 'Stop',
                         needle='are exclusive')

    def test_neither_source(self):
        with tree() as root:
            self.refuses(root, '--agent-type', 'developer',
                         needle='needs --from-transcript')

    def test_a_grain_that_resolves_to_nothing(self):
        with tree() as root:
            self.refuses(root, '--grain', '0.1/alpha/nope',
                         needle='no grain resolves')

    def test_the_grain_grammar_refuses_traversal_absolutes_globs_backslashes(self):
        hostile = (
            '0.1/bugs/../features/alpha/feature',
            '0.1/bugs/sub/../../features/alpha/feature',
            '0.1/../0.1/alpha/s0',
            '0.1/alpha/../../0.1/bugs/crash',
            '../repo/pm/roadmap/0.1-demo/features/alpha/feature',
            '/etc/hosts',
            '0.1/alpha/s*',
            '0.1/alpha/[s]0',
            '0.1\\alpha\\s0',
            '0.1/./s0',
            '0.1//s0',
            '0.1/bugs/',
            '',
            ' ',
            'x' * 300,
        )
        with tree() as root:
            outside = root.parent / 'outside.md'
            outside.write_text('---\nid: outside\n---\n', encoding='utf-8')
            for gid in hostile:
                self.refuses(root, '--grain', gid)
            self.assertEqual(outside.read_text(encoding='utf-8'),
                             '---\nid: outside\n---\n')

    def test_a_positional_argument_is_not_a_flag(self):
        with tree() as root:
            self.refuses(root, STORY, '--tokens-in', '5',
                         needle='takes flags only')
            self.refuses(root, '--grain', STORY, '--wombat', '5',
                         needle='takes flags only')

    def test_an_unknown_subcommand(self):
        with tree() as root:
            code, out = run_cli(root, 'ledger', 'wombat')
        self.assertEqual(code, 2, out)
        self.assertIn('unknown ledger subcommand', out)

    def test_show_refuses_an_id_that_resolves_to_nothing(self):
        with tree() as root:
            for gid in ('0.1/alpha/nope', '0.1/../outside', '/etc/hosts'):
                code, out = run_cli(root, 'ledger', 'show', gid)
                self.assertEqual(code, 2, out)


if __name__ == '__main__':  # pragma: no cover
    unittest.main()
