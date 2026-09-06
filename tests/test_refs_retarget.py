"""Tier 2 — `refs --retarget`: re-point every reference to a moved res:// path.

After a `git mv old.gd new.gd`, every `path="res://old"` ext_resource ref in
the tree strands. The verb rewrites those byte-surgically, plus exact
preload()/load() literals in .gd files — and REPORTS (never rewrites) the
occurrences it cannot prove: comments, substrings, quoted paths outside a
preload/load call. Three properties are load-bearing: only the asked-about
bytes change, a second run is a byte-level no-op, and a retarget onto a path
that does not exist is refused whole.
"""
import os
import re
import types
import unittest

from support import run_check, temp_repo

from godot_devkit import cli

OLD = 'res://scripts/old_helper.gd'
NEW = 'res://scripts/new_helper.gd'
OLD_ZONE = 'res://systems/spatial_zones/zone.gd'
NEW_ZONE = 'res://systems/spatial_zones/zone2.gd'


def run_cli(*argv):
    # The CLI in-process through `run_check`'s scaffolding (stdout captured,
    # the module caches cleared around the cwd change): `cli.main(argv)`
    # wearing a check's `run()` face. A usage error is argparse's SystemExit,
    # left to propagate for the caller to assert on.
    return run_check(types.SimpleNamespace(run=lambda: cli.main(list(argv))))


def census(output):
    """(files scanned, rewritten, skipped) from the verdict line."""
    return tuple(int(g) for g in re.search(
        r'\[refs:retarget\] (\d+) file\(s\) scanned, (\d+) rewritten, (\d+) skipped',
        output).groups())


def snapshot(root):
    return {p: p.read_bytes() for p in sorted(root.rglob('*')) if p.is_file()}


class RetargetRewrites(unittest.TestCase):
    def test_a_dry_run_lists_every_site_then_the_sweep_rewrites_what_it_can_prove(self) -> None:
        # `--dry-run` lists every file+line and writes nothing. The sweep:
        # ext_resource paths and preload/load literals change; the uid attr,
        # its text spelling and every other line of the scene are carried
        # through; a bystander file is byte-identical; a comment, a quoted
        # mention outside a call and a substring are SKIPPED, each with its
        # reason and its line — and skips are findings, exit 1.
        with temp_repo('retarget_repo') as root:
            scene, gd = root / 'scenes/user.tscn', root / 'systems/consumer.gd'
            before = snapshot(root)
            _, dry = run_cli('refs', '--retarget', OLD, NEW, '--dry-run')
            self.assertEqual(before, snapshot(root))
            code, output = run_cli('refs', '--retarget', OLD, NEW)
            after = snapshot(root)
        self.assertEqual(census(dry)[1], 3)            # would rewrite
        self.assertIn('dry run', dry)
        self.assertRegex(dry, r'REWRITE\s+scenes/user\.tscn:3')
        self.assertRegex(dry, r'REWRITE\s+systems/consumer\.gd:3')
        self.assertEqual(census(output), (5, 3, 3), output)
        self.assertEqual(code, 1)
        tscn, script = after[scene].decode('utf-8'), after[gd].decode('utf-8')
        self.assertEqual(before[root / 'scenes/bystander.tscn'],
                         after[root / 'scenes/bystander.tscn'])
        self.assertIn(f'path="{NEW}"', tscn)
        self.assertNotIn(OLD, tscn)
        self.assertIn('uid="uid://roldhelper0"', tscn)
        changed = [pair for pair in zip(before[scene].decode('utf-8').splitlines(),
                                        tscn.splitlines()) if pair[0] != pair[1]]
        self.assertEqual(len(changed), 1)
        self.assertEqual(changed[0][0].replace(OLD, NEW), changed[0][1])
        for phrase in (f'preload("{NEW}")', f'load("{NEW}")',
                       f'# preload("{OLD}") stays put',            # comment intact
                       f'var mention := "{OLD}"',                  # not a preload
                       f'var backup := "{OLD}.bak"'):              # substring
            self.assertIn(phrase, script)
        for reason in ('comment', 'outside a preload/load', 'substring'):
            self.assertIn(reason, output)
        for line in output.splitlines():
            if 'SKIPPED' in line:
                self.assertRegex(line, r'consumer\.gd:\d+')

    @unittest.skipIf(os.geteuid() == 0, 'root ignores permission bits')
    def test_an_unreadable_file_is_skipped_not_a_traceback(self) -> None:
        # v0.16.0 release review: only UnicodeDecodeError was caught, so a
        # permission error mid-sweep stranded a partial rewrite behind a
        # stack trace with no census. The contract is skip-and-continue.
        with temp_repo('retarget_repo') as root:
            locked = root / 'scenes/user.tscn'
            locked.chmod(0o000)
            try:
                code, output = run_cli('refs', '--retarget', OLD, NEW)
            finally:
                locked.chmod(0o644)      # before the tempdir teardown
            gd = (root / 'systems/consumer.gd').read_text(encoding='utf-8')
        self.assertEqual(code, 1, output)                       # skips exit 1
        self.assertIn(f'preload("{NEW}")', gd)                  # sweep went on
        self.assertRegex(output, r'SKIPPED  scenes/user\.tscn  unreadable')
        _, rewritten, skipped = census(output)
        self.assertGreater(rewritten, 0)
        # consumer.gd's three deliberate skip sites, plus the locked file.
        self.assertEqual(skipped, 4)

    def test_crlf_endings_survive_and_a_second_run_is_a_byte_level_no_op(self) -> None:
        with temp_repo('retarget_repo') as root:
            scene = root / 'scenes/user.tscn'
            crlf = scene.read_text(encoding='utf-8').replace('\n', '\r\n').encode()
            scene.write_bytes(crlf)
            run_cli('refs', '--retarget', OLD, NEW)
            raw = scene.read_bytes()
            once = snapshot(root)
            _, output = run_cli('refs', '--retarget', OLD, NEW)
            self.assertEqual(once, snapshot(root))
        self.assertEqual(census(output)[1], 0)        # nothing left to rewrite
        self.assertNotIn(b'\n', raw.replace(b'\r\n', b''))
        changed = [pair for pair in zip(crlf.split(b'\r\n'), raw.split(b'\r\n'))
                   if pair[0] != pair[1]]
        self.assertEqual(len(changed), 1)

    def test_a_missing_target_is_refused_whole_and_usage_errors_exit_2(self) -> None:
        with temp_repo('retarget_repo') as root:
            for argv in ((OLD,),                       # one path
                         ('scripts/old.gd', NEW),      # not res://
                         (OLD, OLD)):                  # retarget onto itself
                with self.assertRaises(SystemExit) as usage:
                    run_cli('refs', '--retarget', *argv)
                self.assertEqual(usage.exception.code, 2, argv)
            # (The refusal run below also clears the caches a usage exit
            # left behind, so nothing stale outlives this repo.)
            before = snapshot(root)
            code, output = run_cli('refs', '--retarget', OLD, 'res://scripts/ghost.gd')
            self.assertEqual(before, snapshot(root))
        self.assertEqual(code, 1)
        self.assertIn('REFUSED', output)

    def test_only_the_referencing_lines_change_across_the_corpus(self) -> None:
        # The realistic bed: a moved script referenced by several real scenes
        # of the editor-written corpus slice. A clean retarget — nothing
        # skipped — exits 0 with its census.
        needle = f'path="{OLD_ZONE}"'
        with temp_repo('corpus/editor_written') as root:
            (root / 'project.godot').write_text('config_version=5\n', encoding='utf-8')
            (root / 'systems/spatial_zones').mkdir(parents=True)
            (root / 'systems/spatial_zones/zone2.gd').write_text('extends Node\n', encoding='utf-8')
            before = {p.relative_to(root): p.read_bytes() for p in sorted(root.rglob('*'))
                      if p.suffix in ('.tscn', '.tres', '.gd')}
            expected = sum(text.decode('utf-8').count(needle) for text in before.values())
            self.assertGreaterEqual(expected, 3, 'corpus lost its zone.gd refs')
            code, output = run_cli('refs', '--retarget', OLD_ZONE, NEW_ZONE)
            after = {rel: (root / rel).read_bytes() for rel in before}
        self.assertEqual(census(output)[1:], (expected, 0), output)
        self.assertEqual(code, 0)
        for rel, text in before.items():
            if needle.encode() not in text:
                self.assertEqual(text, after[rel], f'{rel} was not asked about')
            else:
                changed = [pair for pair in zip(text.split(b'\n'), after[rel].split(b'\n'))
                           if pair[0] != pair[1]]
                self.assertEqual(len(changed), text.decode('utf-8').count(needle),
                                 f'{rel} changed off-target lines')
                for old_line, new_line in changed:
                    self.assertEqual(
                        old_line.replace(OLD_ZONE.encode(), NEW_ZONE.encode()),
                        new_line, f'{rel} rewrote more than the path attr')
