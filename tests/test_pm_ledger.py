"""test_pm_ledger.py — every status flip and every decision leaves a row.

The contract under test (D6 + D8):

  * a status verb appends `{ts, kind, grain, from, to}` to
    `pm/roadmap/<ms>/ledger.jsonl` — the grain's OWN milestone directory,
    beside `decisions.md` — AFTER its frontmatter write landed;
  * a REFUSED or failed flip appends nothing: a row is a record of a write
    that happened, and a ledger that claims a flip nobody made is rule 4's
    cardinal sin with a timestamp on it;
  * a NO-OP flip still appends. Somebody ran the verb; that is a fact;
  * `feature done --cascade` appends its own row, then one per closed story;
  * `pm decide` appends `{ts, kind, grain, entry, title}`;
  * the file is APPEND-ONLY — bytes already on disk are never rewritten;
  * `ledger.jsonl` is not a grain doc: `pm validate`, `check pm` and
    `pm status` are byte-identical with and without it, and `retire` removes
    it with the directory;
  * `pm init` ships the `merge=union` attribute that makes two branches' rows
    one file rather than one conflict.

The shared tree/run_cli/run_gate harness is tests/support/pm.py, and the ledger
is read back through `ledger_rows`/`ledger_lines` there — the raw LINES as well
as the parse, because compactness and key order are half the shape.
"""
from __future__ import annotations

import json
import unittest
from datetime import datetime, timedelta, timezone

from support.pm import (
    damage,
    ledger_lines,
    ledger_rows,
    run_cli,
    run_gate,
    tree,
    write,
)

from godot_devkit.repo.pm import ledger, model

BUG_ID = '0.1/bugs/b0'


def only_row(root) -> dict:
    rows = ledger_rows(root)
    assert len(rows) == 1, f'expected exactly one row, got {rows}'
    return rows[0]


def bug(root, status: str = 'open') -> None:
    write(root / 'pm/roadmap/0.1-demo/bugs/b0.md',
          {'id': BUG_ID, 'milestone': '"0.1"', 'name': 'B0',
           'status': status})


class RowShape(unittest.TestCase):
    """One row, exactly the five keys, in order, compact, UTC to the second."""

    def test_a_story_flip_writes_one_compact_line_with_the_five_keys(self):
        with tree(story_statuses=('todo',)) as root:
            code, out = run_cli(root, 'story', 'wip', '0.1/alpha/s0')
            self.assertEqual(code, 0, out)
            lines = ledger_lines(root)
            self.assertEqual(len(lines), 1, lines)
            row = json.loads(lines[0])
            self.assertEqual(list(row), ['ts', 'kind', 'grain', 'from', 'to'])
            self.assertEqual(row['kind'], 'status')
            self.assertEqual(row['grain'], '0.1/alpha/s0')
            self.assertEqual(row['from'], 'todo')
            self.assertEqual(row['to'], 'wip')
            # Compact and key-ordered, byte for byte — a report reads these
            # with `wc -l` and `readline`, so one row is one line and there
            # are no spaces after the separators.
            self.assertEqual(lines[0], json.dumps(row, separators=(',', ':')))

    def test_the_timestamp_is_full_utc_to_the_second_and_ends_in_Z(self):
        with tree() as root:
            self.assertEqual(run_cli(root, 'story', 'wip', '0.1/alpha/s0')[0], 0)
            ts = only_row(root)['ts']
        self.assertTrue(ts.endswith('Z'), ts)
        self.assertEqual(len(ts), len('2026-09-03T21:40:12Z'), ts)
        stamped = datetime.strptime(ts, ledger.TS_FORMAT).replace(
            tzinfo=timezone.utc)
        # A local-time stamp in a durable log is undetectable later; against
        # `now` in UTC it is detectable NOW, anywhere but UTC itself.
        self.assertLess(abs(stamped - datetime.now(timezone.utc)),
                        timedelta(minutes=5), ts)

    def test_rows_land_in_order_and_earlier_bytes_are_never_rewritten(self):
        with tree() as root:
            self.assertEqual(run_cli(root, 'story', 'wip', '0.1/alpha/s0')[0], 0)
            first = ledger_lines(root)[0]
            self.assertEqual(run_cli(root, 'story', 'review', '0.1/alpha/s0')[0], 0)
            self.assertEqual(run_cli(root, 'story', 'done', '0.1/alpha/s0')[0], 0)
            lines = ledger_lines(root)
        self.assertEqual(len(lines), 3, lines)
        self.assertEqual(lines[0], first, 'an earlier row was rewritten')
        self.assertEqual([json.loads(ln)['to'] for ln in lines],
                         ['wip', 'review', 'done'])
        self.assertEqual([json.loads(ln)['from'] for ln in lines],
                         ['todo', 'wip', 'review'])

    def test_a_foreign_row_already_on_disk_survives_byte_identical(self):
        """Append-only means append-only: a row this version cannot parse —
        another branch's, a later kind — is not read, not rewritten, not
        reordered. It is the property `merge=union` is worth having."""
        with tree() as root:
            path = root / 'pm/roadmap/0.1-demo' / ledger.LEDGER_FILE_NAME
            foreign = '{"ts":"2020-01-01T00:00:00Z","kind":"dispatch","x":[1,2]}'
            path.write_text(foreign + '\n', encoding='utf-8')
            self.assertEqual(run_cli(root, 'story', 'wip', '0.1/alpha/s0')[0], 0)
            lines = ledger_lines(root)
        self.assertEqual(lines[0], foreign)
        self.assertEqual(len(lines), 2, lines)


class EveryStatusVerb(unittest.TestCase):
    """One test per verb. Each writes to the grain's OWN milestone directory."""

    def test_story(self):
        with tree(story_statuses=('todo',)) as root:
            self.assertEqual(run_cli(root, 'story', 'review', '0.1/alpha/s0')[0], 0)
            self.assertEqual(
                only_row(root),
                {'ts': only_row(root)['ts'], 'kind': 'status',
                 'grain': '0.1/alpha/s0', 'from': 'todo', 'to': 'review'})

    def test_bug(self):
        with tree() as root:
            bug(root, 'open')
            code, out = run_cli(root, 'bug', 'fixed', BUG_ID)
            self.assertEqual(code, 0, out)
            row = only_row(root)
        self.assertEqual((row['kind'], row['grain'], row['from'], row['to']),
                         ('status', BUG_ID, 'open', 'fixed'))

    def test_feature_simple_status(self):
        with tree(feature_status='ready') as root:
            code, out = run_cli(root, 'feature', 'building', '0.1/alpha')
            self.assertEqual(code, 0, out)
            row = only_row(root)
        self.assertEqual((row['grain'], row['from'], row['to']),
                         ('0.1/alpha', 'ready', 'building'))

    def test_feature_review(self):
        with tree(feature_status='building') as root:
            code, out = run_cli(root, 'feature', 'review', '0.1/alpha')
            self.assertEqual(code, 0, out)
            row = only_row(root)
        self.assertEqual((row['grain'], row['from'], row['to']),
                         ('0.1/alpha', 'building', 'review'))

    def test_feature_done(self):
        with tree(feature_status='review') as root:
            code, out = run_cli(root, 'feature', 'done', '0.1/alpha')
            self.assertEqual(code, 0, out)
            row = only_row(root)
        self.assertEqual((row['grain'], row['from'], row['to']),
                         ('0.1/alpha', 'review', 'done'))

    def test_milestone(self):
        with tree(milestone_status='ready') as root:
            code, out = run_cli(root, 'milestone', 'building', '0.1')
            self.assertEqual(code, 0, out)
            row = only_row(root)
        self.assertEqual((row['grain'], row['from'], row['to']),
                         ('0.1', 'ready', 'building'))

    def test_the_row_lands_in_the_grains_OWN_milestone_directory(self):
        """A story two milestones deep in the tree stamps ITS milestone, not
        the first one the walker finds."""
        with tree() as root:
            other = root / 'pm/roadmap/0.2-next'
            write(other / 'milestone.md',
                  {'id': '"0.2"', 'name': 'Next', 'status': 'planning'})
            self.assertEqual(run_cli(root, 'story', 'wip', '0.1/alpha/s0')[0], 0)
            self.assertEqual(len(ledger_rows(root)), 1)
            self.assertFalse((other / ledger.LEDGER_FILE_NAME).exists())

    def test_the_verbs_output_and_exit_code_are_unchanged(self):
        """Hard rule 6: the shipped line shapes are a contract. The ledger is
        a side effect on disk and never a line on stdout."""
        with tree(story_statuses=('todo',)) as root:
            code, out = run_cli(root, 'story', 'wip', '0.1/alpha/s0')
        self.assertEqual(code, 0)
        self.assertEqual(out, '[pm] story 0.1/alpha/s0: todo -> wip\n')


class ANoOpIsAFact(unittest.TestCase):
    """Same-status flips append too (D2's cost note, carried by D8)."""

    def test_a_story_no_op_appends_a_from_equals_to_row(self):
        with tree(story_statuses=('wip',)) as root:
            code, out = run_cli(root, 'story', 'wip', '0.1/alpha/s0')
            self.assertEqual(code, 0, out)
            self.assertIn('already wip (no-op)', out)
            row = only_row(root)
        self.assertEqual((row['from'], row['to']), ('wip', 'wip'))

    def test_a_feature_no_op_appends(self):
        with tree(feature_status='building') as root:
            self.assertEqual(run_cli(root, 'feature', 'building', '0.1/alpha')[0], 0)
            self.assertEqual(only_row(root)['from'], 'building')

    def test_a_feature_review_no_op_appends(self):
        with tree(feature_status='review') as root:
            self.assertEqual(run_cli(root, 'feature', 'review', '0.1/alpha')[0], 0)
            row = only_row(root)
        self.assertEqual((row['from'], row['to']), ('review', 'review'))

    def test_a_feature_done_no_op_appends(self):
        with tree(feature_status='done') as root:
            code, out = run_cli(root, 'feature', 'done', '0.1/alpha')
            self.assertEqual(code, 0, out)
            self.assertIn('already done (no-op)', out)
            row = only_row(root)
        self.assertEqual((row['from'], row['to']), ('done', 'done'))

    def test_a_milestone_no_op_appends(self):
        with tree(milestone_status='building') as root:
            self.assertEqual(run_cli(root, 'milestone', 'building', '0.1')[0], 0)
            self.assertEqual(only_row(root)['to'], 'building')

    def test_a_bug_no_op_appends(self):
        with tree() as root:
            bug(root, 'open')
            self.assertEqual(run_cli(root, 'bug', 'open', BUG_ID)[0], 0)
            self.assertEqual(only_row(root)['from'], 'open')


class Cascade(unittest.TestCase):
    """`feature done --cascade`: the feature's row, then one per closed story."""

    def test_the_feature_row_comes_first_then_one_row_per_closed_story(self):
        with tree(feature_status='review',
                  story_statuses=('review', 'review', 'todo')) as root:
            code, out = run_cli(root, 'feature', 'done', '0.1/alpha', '--cascade')
            self.assertEqual(code, 0, out)
            rows = ledger_rows(root)
        self.assertEqual(len(rows), 3, rows)
        self.assertEqual((rows[0]['grain'], rows[0]['from'], rows[0]['to']),
                         ('0.1/alpha', 'review', 'done'))
        self.assertEqual([(r['grain'], r['from'], r['to']) for r in rows[1:]],
                         [('0.1/alpha/s0', 'review', 'done'),
                          ('0.1/alpha/s1', 'review', 'done')])

    def test_a_story_the_cascade_did_not_touch_gets_no_row(self):
        with tree(feature_status='review',
                  story_statuses=('review', 'todo')) as root:
            self.assertEqual(
                run_cli(root, 'feature', 'done', '0.1/alpha', '--cascade')[0], 0)
            grains = [r['grain'] for r in ledger_rows(root)]
        self.assertNotIn('0.1/alpha/s1', grains)
        self.assertEqual(grains, ['0.1/alpha', '0.1/alpha/s0'])

    def test_without_the_flag_only_the_feature_gets_a_row(self):
        with tree(feature_status='review', story_statuses=('review',)) as root:
            self.assertEqual(run_cli(root, 'feature', 'done', '0.1/alpha')[0], 0)
            self.assertEqual([r['grain'] for r in ledger_rows(root)],
                             ['0.1/alpha'])

    def test_the_second_cascade_run_adds_only_its_own_no_op_row(self):
        with tree(feature_status='review', story_statuses=('review',)) as root:
            self.assertEqual(
                run_cli(root, 'feature', 'done', '0.1/alpha', '--cascade')[0], 0)
            self.assertEqual(
                run_cli(root, 'feature', 'done', '0.1/alpha', '--cascade')[0], 0)
            rows = ledger_rows(root)
        self.assertEqual([(r['grain'], r['from'], r['to']) for r in rows],
                         [('0.1/alpha', 'review', 'done'),
                          ('0.1/alpha/s0', 'review', 'done'),
                          ('0.1/alpha', 'done', 'done')])


class ARefusedFlipAppendsNothing(unittest.TestCase):
    """The row records a write that LANDED. No write, no row — ever."""

    def test_a_review_record_naming_no_file_refuses_and_writes_no_row(self):
        with tree(feature_status='review', with_record=False) as root:
            code, out = run_cli(root, 'feature', 'done', '0.1/alpha',
                                '--review-record', 'docs/reviews/nope.md')
            self.assertEqual(code, 1, out)
            self.assertEqual(ledger_lines(root), [])

    def test_a_status_outside_the_vocabulary_writes_no_row(self):
        with tree() as root:
            code, out = run_cli(root, 'story', 'wombat', '0.1/alpha/s0')
            self.assertEqual(code, 2, out)
            self.assertEqual(ledger_lines(root), [])

    def test_an_id_that_resolves_to_nothing_writes_no_row(self):
        with tree() as root:
            self.assertEqual(run_cli(root, 'story', 'wip', '0.1/alpha/ghost')[0], 2)
            self.assertEqual(run_cli(root, 'feature', 'done', '0.1/ghost')[0], 2)
            self.assertEqual(run_cli(root, 'milestone', 'done', '9.9')[0], 2)
            self.assertEqual(run_cli(root, 'bug', 'fixed', '0.1/bugs/ghost')[0], 2)
            self.assertEqual(ledger_lines(root), [])

    def test_a_frontmatter_write_that_FAILS_writes_no_row(self):
        """The one ordering that matters: the row is written after the write
        succeeded. Damaged frontmatter is where `set_field` returns False —
        the file is untouched, so the ledger must be too."""
        with tree() as root:
            damage(root / 'pm/roadmap/0.1-demo/features/alpha/stories/s0.md',
                   'no-closing-fence')
            code, out = run_cli(root, 'story', 'wip', '0.1/alpha/s0')
            self.assertEqual(code, 2, out)
            self.assertEqual(ledger_lines(root), [])

    def test_a_cascade_that_cannot_close_a_story_still_records_what_landed(self):
        """The half that DID land is a fact. The cascade aborts on the
        unwritable story, and the story it already closed keeps its row — with
        no row for the feature, whose own flip never happened."""
        with tree(feature_status='review',
                  story_statuses=('review', 'review')) as root:
            blocked = root / 'pm/roadmap/0.1-demo/features/alpha/stories/s1.md'
            blocked.chmod(0o444)
            try:
                code, out = run_cli(root, 'feature', 'done', '0.1/alpha',
                                    '--cascade')
            finally:
                blocked.chmod(0o644)
            self.assertEqual(code, 2, out)
            rows = ledger_rows(root)
        self.assertEqual([(r['grain'], r['from'], r['to']) for r in rows],
                         [('0.1/alpha/s0', 'review', 'done')])


class Decide(unittest.TestCase):
    """`pm decide` appends `{ts, kind, grain, entry, title}` after the heading."""

    def test_a_milestone_decision_row(self):
        with tree() as root:
            code, out = run_cli(root, 'decide', '0.1', 'The ledger is one file')
            self.assertEqual(code, 0, out)
            lines = ledger_lines(root)
            self.assertEqual(len(lines), 1, lines)
            row = json.loads(lines[0])
        self.assertEqual(list(row), ['ts', 'kind', 'grain', 'entry', 'title'])
        self.assertEqual((row['kind'], row['grain'], row['entry'], row['title']),
                         ('decision', '0.1', 'D1', 'The ledger is one file'))

    def test_a_feature_decision_lands_in_the_MILESTONE_ledger(self):
        """`decisions.md` is per-grain; the ledger is per-milestone (D6)."""
        with tree() as root:
            self.assertEqual(run_cli(root, 'decide', '0.1/alpha', 'Ship it')[0], 0)
            fdir = root / 'pm/roadmap/0.1-demo/features/alpha'
            self.assertTrue((fdir / 'decisions.md').is_file())
            self.assertFalse((fdir / ledger.LEDGER_FILE_NAME).exists())
            row = only_row(root)
        self.assertEqual((row['grain'], row['entry']), ('0.1/alpha', 'D1'))

    def test_the_ordinal_on_the_row_is_the_one_written_into_the_log(self):
        with tree() as root:
            self.assertEqual(run_cli(root, 'decide', '0.1', 'First')[0], 0)
            self.assertEqual(run_cli(root, 'decide', '0.1', 'Second')[0], 0)
            rows = ledger_rows(root)
            log = (root / 'pm/roadmap/0.1-demo/decisions.md').read_text()
        self.assertEqual([(r['entry'], r['title']) for r in rows],
                         [('D1', 'First'), ('D2', 'Second')])
        self.assertIn('## D2 — ', log)

    def test_a_refused_decide_appends_nothing(self):
        with tree() as root:
            # A story has no decision log; a heading a shell cut in half is
            # refused whole. Neither is a row.
            self.assertEqual(run_cli(root, 'decide', '0.1/alpha/s0', 'x')[0], 1)
            self.assertEqual(run_cli(root, 'decide', '0.1', 'first half;')[0], 1)
            self.assertEqual(run_cli(root, 'decide', '0.1')[0], 2)
            self.assertEqual(ledger_lines(root), [])

    def test_a_title_with_quotes_unicode_and_backslashes_stays_ONE_line(self):
        title = 'the "ledger" — a\\b, not c'
        with tree() as root:
            self.assertEqual(run_cli(root, 'decide', '0.1', title)[0], 0)
            lines = ledger_lines(root)
        self.assertEqual(len(lines), 1, lines)
        self.assertEqual(json.loads(lines[0])['title'], title)
        # ensure_ascii=False: the em dash is written as itself.
        self.assertIn('—', lines[0])

    def test_a_unicode_line_separator_in_a_title_stays_ONE_row(self):
        """U+2028 is a line terminator to `str.splitlines()` and `ensure_ascii
        =False` writes it raw — a row carrying one would read back as two, the
        second of them invalid JSON. `decide` refuses \\n and \\r; nothing
        refuses this, so the serialiser escapes it."""
        title = 'a\u2028b\u2029c'
        with tree() as root:
            self.assertEqual(run_cli(root, 'decide', '0.1', title)[0], 0)
            raw = (root / 'pm/roadmap/0.1-demo'
                   / ledger.LEDGER_FILE_NAME).read_text(encoding='utf-8')
        self.assertEqual(len(raw.splitlines()), 1, raw)
        self.assertEqual(json.loads(raw)['title'], title)


class NotAGrainDoc(unittest.TestCase):
    """`ledger.jsonl` is not `.md` and carries no frontmatter. Every reader
    that walks the tree must be byte-identical with it and without it."""

    def test_validate_and_the_gate_and_status_are_unchanged_by_the_ledger(self):
        with tree(story_statuses=('wip',), feature_status='building',
                  milestone_status='building') as root:
            before = (run_cli(root, 'validate'), run_gate(root),
                      run_cli(root, 'status'))
            self.assertEqual(run_cli(root, 'story', 'wip', '0.1/alpha/s0')[0], 0)
            self.assertTrue(
                (root / 'pm/roadmap/0.1-demo' / ledger.LEDGER_FILE_NAME).is_file())
            after = (run_cli(root, 'validate'), run_gate(root),
                     run_cli(root, 'status'))
        self.assertEqual(before[0], after[0], 'pm validate saw the ledger')
        self.assertEqual(before[1], after[1], 'check pm saw the ledger')
        self.assertEqual(before[2], after[2], 'pm status saw the ledger')
        self.assertEqual(after[0][0], 0)
        self.assertEqual(after[1][0], 0)
        self.assertNotIn(ledger.LEDGER_FILE_NAME, after[2][1])

    def test_the_slot_walk_never_yields_it(self):
        """Even parked inside a slot directory, where a `.md` note would at
        least be COUNTED as skipped, it is not a document the walk knows."""
        with tree() as root:
            sdir = root / 'pm/roadmap/0.1-demo/features/alpha/stories'
            (sdir / ledger.LEDGER_FILE_NAME).write_text(
                '{"ts":"2026-01-01T00:00:00Z"}\n', encoding='utf-8')
            walk = model.slot_walk(sdir)
            self.assertEqual([p.name for p in walk.kept], ['s0.md'])
            self.assertNotIn(ledger.LEDGER_FILE_NAME, walk.census('doc(s)'))

    def test_retire_removes_the_ledger_with_the_directory(self):
        with tree(milestone_status='done', feature_status='done',
                  story_statuses=('done',)) as root:
            (root / 'pm/roadmap/ROADMAP.md').write_text(
                '# Roadmap\n\n| Version | Name | Delivered | What shipped |\n'
                '|---|---|---|---|\n', encoding='utf-8')
            self.assertEqual(run_cli(root, 'story', 'done', '0.1/alpha/s0')[0], 0)
            path = root / 'pm/roadmap/0.1-demo' / ledger.LEDGER_FILE_NAME
            self.assertTrue(path.is_file())
            code, out = run_cli(root, 'retire', '0.1', 'shipped')
            self.assertEqual(code, 0, out)
            self.assertFalse(path.exists())
            self.assertFalse((root / 'pm/roadmap/0.1-demo').exists())


class MergeAttribute(unittest.TestCase):
    """`pm/roadmap/*/ledger.jsonl merge=union` — the one file two milestone
    branches can both append to, and the only way that is a merge rather than
    a conflict."""

    def test_pm_init_writes_the_file_when_there_is_none(self):
        with tree() as root:
            (root / '.gitattributes').unlink(missing_ok=True)
            code, out = run_cli(root, 'init')
            self.assertEqual(code, 0, out)
            body = (root / '.gitattributes').read_text(encoding='utf-8')
        self.assertIn(skills_attribute_line(), body)
        self.assertIn('.gitattributes', out)

    def test_it_is_APPENDED_to_a_gitattributes_that_already_exists(self):
        with tree() as root:
            (root / '.gitattributes').write_text('*.png binary\n',
                                                 encoding='utf-8')
            self.assertEqual(run_cli(root, 'init')[0], 0)
            body = (root / '.gitattributes').read_text(encoding='utf-8')
        self.assertTrue(body.startswith('*.png binary\n'),
                        'the project\'s own attributes were lost')
        self.assertIn(skills_attribute_line(), body)

    def test_a_file_already_carrying_the_line_is_left_alone_and_says_so(self):
        with tree() as root:
            target = root / '.gitattributes'
            target.write_text(f'{skills_attribute_line()}\n', encoding='utf-8')
            before = target.read_bytes()
            code, out = run_cli(root, 'init')
            self.assertEqual(code, 0, out)
            self.assertEqual(target.read_bytes(), before)
        self.assertIn('already carries', out)

    def test_a_second_run_does_not_duplicate_the_line(self):
        with tree() as root:
            self.assertEqual(run_cli(root, 'init')[0], 0)
            self.assertEqual(run_cli(root, 'init')[0], 0)
            body = (root / '.gitattributes').read_text(encoding='utf-8')
        self.assertEqual(body.count(skills_attribute_line()), 1, body)

    def test_the_pattern_names_the_configured_roadmap_dir(self):
        """`[pm] roadmap_dir` is config, so the attribute cannot be a literal
        that is right only for the stock path."""
        with tree() as root:
            (root / 'devkit.toml').write_text(
                '[pm]\nroadmap_dir = "planning/ms"\n', encoding='utf-8')
            self.assertEqual(run_cli(root, 'init')[0], 0)
            body = (root / '.gitattributes').read_text(encoding='utf-8')
        self.assertIn(f'planning/ms/*/{ledger.LEDGER_FILE_NAME} merge=union',
                      body)


def skills_attribute_line() -> str:
    from godot_devkit.repo.pm import skills
    return skills.attribute_line('pm/roadmap')


if __name__ == '__main__':  # pragma: no cover
    unittest.main()
