"""test_pm_ledger_report_git.py — `pm ledger report <ms> --from <rev>`.

D6 put a milestone's ledger inside the milestone directory and said the rest
out loud: `retire` removes it with the directory, and a retired milestone's
rows are read from GIT. So this verb's whole claim is an EQUALITY — the table a
reader gets out of history is the table they would have got the day before the
close — and an equality is only tested by capturing both sides and comparing
the bytes. Every shape case here does exactly that: run the live report, commit
the tree, tag it, retire the milestone, run `--from <tag>`, and compare
byte-for-byte after stripping the one thing that is meant to differ.

A paraphrase would not do. "The numbers match" is what a report with a whole
section missing also says, and a section that silently stopped printing is hard
rule 4's read-side sin — a gate that misses real drift and prints PASS.

The rest is SDLC § 5's matrix over a new input surface: `--from` takes a rev,
and everything that is not a rev refuses at exit 2 having written nothing. The
one input that is NOT a refusal is a milestone that exists at the rev with no
`ledger.jsonl` beside it — that is the `no ledger` line the live path already
prints, because "nothing was recorded" is a fact and not an error.

ALL of these fail at HEAD~: `--from` did not exist, so every case in `AtARev`
and every case in `Refusals` reported `unknown flag '--from'` at exit 2 — and
`test_the_table_at_the_tag_is_the_table_before_the_retire` is the one that
carries the claim.
"""
from __future__ import annotations

import json
import os
import unittest
from unittest import mock

from support.pm import (LEDGER_REL, bug, commit, dispatch_line, git,
                        porcelain, put_ledger, run_cli, snapshot, status_line,
                        tree, write)

from godot_devkit.repo.pm import skills

STORY, QUIET, FEATURE, BUG = ('0.1/alpha/s0', '0.1/alpha/s1', '0.1/alpha',
                              '0.1/bugs/crash')
MILESTONE_DIR = 'pm/roadmap/0.1-demo'
RECORD_REL = 'docs/reviews/alpha.md'
TAG = 'v9.9.9'

# A record as the installed reviewer writes one: prose, then the fenced block.
# Present so that sections 2 and 3 have something to print — a `--from` read
# that could not follow a feature's `reviewed:` pointer out of git would print
# an EMPTY yield table, which reads exactly like a milestone nobody reviewed.
RECORD = """\
The pass, in prose.

```text
verdict: SHIP-WITH-FIXES
| id | severity | disposition |
| A1 | MAJOR | landed 0badc0f |
| A2 | MINOR | landed in-place |
| A3 | QUESTION | deferred: 0.1/beta |
```
"""


def report(root, *argv) -> tuple[int, str]:
    return run_cli(root, 'ledger', 'report', *argv)


def seeded(root) -> None:
    """The tree every equality case reads: one story worked and closed, one
    story nothing touched, the feature that owns them, one bug naming a cause,
    a review record with a real verdict block, and rows of all four kinds.

    All five sections have content on purpose. A `--from` read that lost ONE
    of the file kinds it has to open — the milestone document, a feature, a
    story, a bug, a review record, the ledger — must fail loudly here, and a
    section with nothing in it prints `no data` rather than nothing at all.
    """
    write(root / MILESTONE_DIR / 'features/alpha/stories/s1.md',
          {'id': QUIET, 'feature': FEATURE, 'milestone': '"0.1"', 'name': 'S1',
           'status': 'todo', 'size': 'm'})
    bug(root, 'crash', 'closed', caused_by=FEATURE)
    (root / RECORD_REL).write_text(RECORD, encoding='utf-8')
    put_ledger(
        root,
        status_line('2026-09-03T10:00:00Z', STORY, 'todo', 'wip'),
        dispatch_line('2026-09-03T10:05:00Z', agent_type='developer',
                      tool_calls=37, duration_s=812,
                      tool_calls_before_first_write=9,
                      usage={'input': 1200, 'output': 38000,
                             'cache_creation': 210000, 'cache_read': 9100000},
                      tree=snapshot(stories_wip=[STORY],
                                    features_building=[FEATURE])),
        status_line('2026-09-03T10:10:00Z', STORY, 'wip', 'review'),
        dispatch_line('2026-09-03T10:11:00Z', agent_type='reviewer',
                      usage={'output': 500},
                      tree=snapshot(stories_review=[STORY])),
        status_line('2026-09-03T10:12:00Z', STORY, 'review', 'wip'),
        status_line('2026-09-03T10:14:00Z', STORY, 'wip', 'done'),
        status_line('2026-09-03T10:20:00Z', BUG, 'open', 'closed'),
        dispatch_line('2026-09-03T10:30:00Z', usage={'input': 5},
                      tool_calls=2),
    )


def roadmap(root) -> None:
    """The index `pm retire` appends its prune row to."""
    (root / 'pm/roadmap/ROADMAP.md').write_text(skills.ROADMAP_SEED,
                                                encoding='utf-8')


def stripped(out: str, rev: str = TAG) -> str:
    """The report with the one thing that is MEANT to differ taken back out.

    ` — at <rev>` on every heading is the whole visible difference between the
    two reads, and stripping it is what turns "looks the same" into an
    assertion. Anything else that differs survives the strip and fails the
    comparison, which is the only reason this helper is a `replace` and not a
    per-line rewrite.
    """
    return out.replace(f' — at {rev}', '')


class AtARev(unittest.TestCase):
    """The equality: history reads back as the tree read before the close."""

    def capture(self, root, *argv) -> tuple[int, str]:
        code, out = report(root, *argv)
        self.assertEqual(code, 0, out)
        return code, out

    def test_the_table_at_the_tag_is_the_table_before_the_retire(self):
        with tree(story_statuses=('done', 'todo')) as root:
            seeded(root)
            roadmap(root)
            _, live = self.capture(root, '0.1')
            commit(root, 'the milestone, still in the tree')
            git(root, 'tag', TAG)
            # The real close, through the real verb: `retire` removes the
            # directory and the ledger with it (D6), which is exactly the
            # state this whole story exists for.
            code, out = run_cli(root, 'retire', '0.1')
            self.assertEqual(code, 0, out)
            self.assertFalse((root / MILESTONE_DIR).exists(), out)
            commit(root, 'retire 0.1')
            _, at_tag = self.capture(root, '0.1', '--from', TAG)
        self.assertIn(f' — at {TAG} — ', at_tag)
        self.assertEqual(stripped(at_tag), live)

    def test_the_json_at_the_tag_is_the_json_before_the_retire(self):
        with tree(story_statuses=('done', 'todo')) as root:
            seeded(root)
            roadmap(root)
            _, live = self.capture(root, '0.1', '--json')
            commit(root, 'seed')
            git(root, 'tag', TAG)
            run_cli(root, 'retire', '0.1')
            commit(root, 'retire')
            _, at_tag = self.capture(root, '0.1', '--json', '--from', TAG)
        payload = json.loads(at_tag)
        # `rev` is the ONLY key `--from` adds, and it is absent from a live
        # payload: a `"rev": null` in every report would be a key every
        # consumer has to learn to keep reading (hard rule 6).
        self.assertEqual(payload.pop('rev'), TAG)
        self.assertEqual(payload, json.loads(live))
        self.assertNotIn('rev', json.loads(live))

    def test_a_directory_suffix_that_changed_since_the_rev(self):
        """The id is the version; the suffix is a human's note about it.

        `model.milestone_dir` globs `<mid>-*` on disk for exactly that reason,
        and a rev read that matched the directory NAME would answer "no such
        milestone" for every milestone anybody ever renamed.
        """
        with tree(story_statuses=('done', 'todo')) as root:
            seeded(root)
            _, live = self.capture(root, '0.1')
            commit(root, 'as 0.1-demo')
            git(root, 'tag', TAG)
            git(root, 'mv', MILESTONE_DIR, 'pm/roadmap/0.1-renamed-since')
            commit(root, 'rename the milestone directory')
            _, at_tag = self.capture(root, '0.1', '--from', TAG)
            _, now = self.capture(root, '0.1')
        # Today resolves the NEW suffix and the rev resolves the old one, and
        # both are the same milestone saying the same thing.
        self.assertEqual(stripped(at_tag), live)
        self.assertEqual(now, live)

    def test_no_ledger_at_the_rev_is_one_line_and_exit_zero(self):
        """Not an error. A milestone nothing was recorded for has no file, and
        that is the same fact from history as it is from disk."""
        with tree() as root:
            commit(root, 'a milestone nothing was recorded for')
            git(root, 'tag', TAG)
            code, out = report(root, '0.1', '--from', TAG)
        self.assertEqual(code, 0, out)
        self.assertEqual(out.strip(),
                         f'[ledger:report] 0.1 — at {TAG} — no ledger')

    def test_the_archive_is_searched_after_the_active_tree(self):
        """`model.milestone_dir`'s two places, in its order, out of git."""
        with tree(story_statuses=('done', 'todo')) as root:
            seeded(root)
            _, live = self.capture(root, '0.1')
            archive = root / 'pm/roadmap/zz_archive'
            archive.mkdir(parents=True, exist_ok=True)
            (root / MILESTONE_DIR).rename(archive / '0.1-demo')
            commit(root, 'archive the milestone')
            git(root, 'tag', TAG)
            _, at_tag = self.capture(root, '0.1', '--from', TAG)
        self.assertEqual(stripped(at_tag), live)

    def test_the_census_at_a_rev_narrows_exactly_as_the_disk_walk_does(self):
        """The claim `GitSource._grain_docs` makes, staged against a tree that
        exercises every one of `model.slot_walk`'s decisions at once.

        A census read out of git that quietly counted MORE than the disk walk
        (a note, a hidden document) or LESS (a nested bug, an uppercase
        extension) would be hard rule 4 exactly: a table whose grain list is
        not the tree's, printed with no sign that it isn't. So the tree here
        holds one of each, and the assertion is still the byte comparison —
        the same one that catches a whole section going missing.
        """
        with tree(story_statuses=('done', 'todo')) as root:
            seeded(root)
            base = root / MILESTONE_DIR
            # In scope, and only the recursive walk finds it.
            write(base / 'bugs/regressions/nested.md',
                  {'id': '0.1/bugs/regressions/nested', 'milestone': '"0.1"',
                   'name': '', 'status': 'open', 'caused_by': FEATURE})
            # In scope: `.md` is compared case-INSENSITIVELY.
            write(base / 'features/alpha/stories/LOUD.MD',
                  {'id': '0.1/alpha/LOUD', 'feature': FEATURE,
                   'milestone': '"0.1"', 'name': 'Loud', 'status': 'todo'})
            # Out of scope: a note beside the grains, no frontmatter at all.
            (base / 'bugs/README.md').write_text(
                'How bugs are filed here.\n', encoding='utf-8')
            # Out of scope: dot-prefixed, files and directories alike.
            write(base / 'bugs/.hold/parked.md',
                  {'id': '0.1/bugs/parked', 'milestone': '"0.1"', 'name': '',
                   'status': 'open'})
            _, live = self.capture(root, '0.1')
            commit(root, 'a tree with one of each narrowing')
            git(root, 'tag', TAG)
            _, at_tag = self.capture(root, '0.1', '--from', TAG)
        # The two grains that ARE in scope reached the table; the two that are
        # not, did not — and the rev read agrees with the disk read on all four.
        self.assertIn('0.1/bugs/regressions/nested', live)
        self.assertIn('0.1/alpha/LOUD', live)
        self.assertNotIn('README', live)
        self.assertNotIn('parked', live)
        self.assertEqual(stripped(at_tag), live)

    def test_a_directory_at_the_rev_is_not_a_file(self):
        """`git show <rev>:<a-directory>` SUCCEEDS and hands back a listing,
        which a reader expecting a document parses as one. `is_file` asks git
        for the object TYPE for exactly that reason, and a `reviewed:` pointing
        at a directory must resolve to no record rather than to a yield built
        out of `git ls-tree` output."""
        with tree(story_statuses=('done', 'todo')) as root:
            seeded(root)
            (root / 'docs/reviews/alpha.md').unlink()
            write(root / 'docs/reviews/alpha.md/inside.md',
                  {'id': '0.1/nope', 'name': 'not a record'})
            commit(root, 'a pointer that names a directory')
            git(root, 'tag', TAG)
            code, out = report(root, '0.1', '--from', TAG)
        self.assertEqual(code, 0, out)
        # The pointer resolved to nothing, so the record is absent — never a
        # verdict table assembled from a directory listing.
        self.assertNotIn('alpha.md', out)
        self.assertNotIn('not a record', out)

    def test_an_absolute_reviewed_pointer_never_reads_todays_disk(self):
        """An absolute path is in no rev. Answering it from the working tree
        would put a file the milestone never shipped with into a report about
        history — the live tree leaking into a historical read."""
        with tree(story_statuses=('done', 'todo')) as root:
            seeded(root)
            outside = root / 'todays-record.md'
            outside.write_text(RECORD.replace('SHIP-WITH-FIXES', 'HOLD'),
                               encoding='utf-8')
            # Resolved: the pointer must be spelled the way git names the
            # root (`rev-parse --show-toplevel` follows symlinks; a macOS
            # tempdir is one), or the mismatch alone hides the file from the
            # rev read and the case passes for the wrong reason. `commit`
            # adds `-A`, so the record IS in the rev — an absolute pointer
            # must still not reach it.
            write(root / f'{MILESTONE_DIR}/features/alpha/feature.md',
                  {'id': FEATURE, 'milestone': '"0.1"', 'name': 'Alpha',
                   'status': 'done', 'reviewed': str(outside.resolve())})
            commit(root, 'an absolute pointer')
            git(root, 'tag', TAG)
            code, out = report(root, '0.1', '--from', TAG)
        self.assertEqual(code, 0, out)
        self.assertNotIn('HOLD', out)
        self.assertNotIn(str(outside), out)

    def test_crlf_terminators_read_the_same_from_git_as_from_disk(self):
        """`git show` hands over the bytes as they are; `Path.read_text` — the
        reader `ledger.read_rows` uses — translates. A ledger and a record
        whose terminators are CRLF must still produce ONE table either way, or
        the same milestone has two reports and nothing says which is which."""
        with tree(story_statuses=('done', 'todo')) as root:
            seeded(root)
            for rel in (LEDGER_REL, RECORD_REL):
                path = root / rel
                path.write_bytes(path.read_text(encoding='utf-8')
                                 .replace('\n', '\r\n').encode('utf-8'))
            _, live = self.capture(root, '0.1')
            commit(root, 'CRLF terminators on both documents')
            git(root, 'tag', TAG)
            _, at_tag = self.capture(root, '0.1', '--from', TAG)
        self.assertIn('SHIP-WITH-FIXES', live)
        self.assertEqual(stripped(at_tag), live)

    def test_the_verb_writes_nothing_and_checks_nothing_out(self):
        """The claim in the docstring, asserted against the tree itself."""
        with tree(story_statuses=('done', 'todo')) as root:
            seeded(root)
            roadmap(root)
            commit(root, 'seed')
            git(root, 'tag', TAG)
            before = git(root, 'rev-parse', 'HEAD')
            self.capture(root, '0.1', '--from', TAG)
            self.capture(root, '0.1', '--from', TAG, '--json')
            self.assertEqual(porcelain(root), '')
            self.assertEqual(git(root, 'rev-parse', 'HEAD'), before)
            self.assertEqual(git(root, 'stash', 'list'), '')


class Refusals(unittest.TestCase):
    """SDLC § 5's matrix for `--from`. Exit 2, and nothing written."""

    def refuses(self, root, *argv, needle: str = '') -> str:
        code, out = report(root, *argv)
        self.assertEqual(code, 2, out)
        if needle:
            self.assertIn(needle, out)
        # Every refusal is also a claim that the tree is untouched; a verb that
        # refused AFTER writing would pass an exit-code assertion alone.
        self.assertEqual(porcelain(root), '')
        return out

    def test_a_rev_that_does_not_resolve_carries_gits_own_words(self):
        with tree() as root:
            commit(root, 'seed')
            out = self.refuses(root, '0.1', '--from', 'nosuchrev')
        # Verbatim, not paraphrased: git explains a bad rev better than a
        # re-wording would, and a re-wording is one more thing to keep in step.
        self.assertIn('fatal:', out)

    def test_a_milestone_that_is_not_in_the_tree_at_that_rev(self):
        """The ordinary mistake: a rev from AFTER the close that retired it.

        Both spellings of a rev, because both are things a caller types: the
        tag and the raw hash. The message says which rev to reach for instead,
        since "it is not there" alone leaves the reader nowhere to go.
        """
        with tree() as root:
            commit(root, 'the milestone, in the tree')
            git(root, 'rm', '-r', '-q', MILESTONE_DIR)
            gone = commit(root, 'retired')
            git(root, 'tag', TAG)
            for rev in (gone, TAG):
                out = self.refuses(root, '0.1', '--from', rev,
                                   needle='no milestone directory 0.1-*')
                self.assertIn('release tag', out)

    def test_a_path_the_report_needs_and_the_rev_does_not_hold(self):
        """The directory is there and `milestone.md` is not. Say which."""
        with tree() as root:
            git(root, 'add', '-A')
            (root / MILESTONE_DIR / 'milestone.md').unlink()
            commit(root, 'a milestone directory with no milestone document')
            git(root, 'tag', TAG)
            out = self.refuses(root, '0.1', '--from', TAG,
                               needle=f'{MILESTONE_DIR}/milestone.md')
            self.assertIn(f'{TAG}:', out)

    def test_from_with_no_milestone_id(self):
        with tree() as root:
            commit(root, 'seed')
            self.refuses(root, '--from', 'HEAD', needle='needs a milestone id')

    def test_from_with_no_value_at_all_does_not_fall_back_to_the_tree(self):
        """The defect this case was written against: an empty value read as
        "no rev", and the verb answered from the working tree at exit 0 —
        a live report standing in for a question about history."""
        with tree(story_statuses=('done', 'todo')) as root:
            seeded(root)
            commit(root, 'seed')
            self.refuses(root, '0.1', '--from', needle='needs a rev')

    def test_a_rev_that_starts_with_a_dash_is_a_flag_and_not_a_rev(self):
        with tree() as root:
            commit(root, 'seed')
            for rev in ('-x', '--upload-pack=touch /tmp/pwned', '--help', '-'):
                self.refuses(root, '0.1', '--from', rev,
                             needle='starts with `-`')

    def test_a_rev_holding_whitespace_or_nul(self):
        with tree() as root:
            commit(root, 'seed')
            for rev in ('HEAD x', ' HEAD', 'HEAD\n', 'HEAD\t', 'HEAD\x00',
                        '\x00', 'a b c'):
                self.refuses(root, '0.1', '--from', rev,
                             needle='whitespace or NUL')

    def test_from_given_twice(self):
        with tree() as root:
            commit(root, 'seed')
            self.refuses(root, '0.1', '--from', 'HEAD', '--from', 'HEAD',
                         needle='was given 2 times')

    def test_git_not_on_path_says_so_plainly(self):
        with tree() as root:
            commit(root, 'seed')
            git(root, 'tag', TAG)
            with mock.patch.dict(os.environ, {'PATH': ''}):
                code, out = report(root, '0.1', '--from', TAG)
        self.assertEqual(code, 2, out)
        self.assertIn('git is not on PATH', out)

    def test_a_ledger_line_that_will_not_parse_at_the_rev(self):
        """Still by LINE NUMBER, and now naming `<rev>:<path>` — the string a
        reader can paste after `git show` to see the line for themselves."""
        with tree(story_statuses=('done', 'todo')) as root:
            put_ledger(root,
                       status_line('2026-09-03T10:00:00Z', STORY, 'todo',
                                   'wip'),
                       '{not json')
            commit(root, 'a ledger with a bad line')
            git(root, 'tag', TAG)
            out = self.refuses(root, '0.1', '--from', TAG, needle='line 2')
            self.assertIn(f'{TAG}:{LEDGER_REL}', out)

    def test_an_id_that_is_not_a_milestone_id(self):
        with tree() as root:
            commit(root, 'seed')
            for gid in (FEATURE, STORY, BUG, '0.1/..', '../0.1', '/etc/hosts',
                        '0.*', '.', '..', ''):
                self.refuses(root, gid, '--from', 'HEAD',
                             needle='resolves from id')

    def test_two_positional_arguments_beside_from(self):
        with tree() as root:
            commit(root, 'seed')
            self.refuses(root, '0.1', '0.2', '--from', 'HEAD',
                         needle='one milestone id')


if __name__ == '__main__':  # pragma: no cover
    unittest.main()
