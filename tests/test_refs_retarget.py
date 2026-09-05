"""Tier 2 — `refs --retarget`: re-point every reference to a moved res:// path.

After a `git mv old.gd new.gd`, every `path="res://old"` ext_resource ref in
the tree strands. The verb rewrites those byte-surgically, plus exact
preload()/load() literals in .gd files — and REPORTS (never rewrites) the
occurrences it cannot prove: comments, substrings, quoted paths outside a
preload/load call. Three properties are load-bearing: only the asked-about
bytes change, a second run is a byte-level no-op, and a retarget onto a path
that does not exist is refused whole.
"""
from __future__ import annotations

import contextlib
import io
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from support import FIXTURES, temp_repo

from godot_devkit import cli

CORPUS_NB = FIXTURES / 'corpus' / 'editor_written'
OLD = 'res://scripts/old_helper.gd'
NEW = 'res://scripts/new_helper.gd'
CENSUS = re.compile(r'\[refs:retarget\] (\d+) file\(s\) scanned, '
                    r'(\d+) rewritten, (\d+) skipped')


def run_cli(*argv: str) -> tuple[int, str]:
    """Run the CLI with the module caches cleared around the cwd change."""
    from godot_devkit.core.project import load_config, repo_root
    repo_root.cache_clear()
    load_config.cache_clear()
    buffer = io.StringIO()
    try:
        with contextlib.redirect_stdout(buffer):
            code = cli.main(list(argv))
    except SystemExit as bail:  # argparse's spelling of a usage error
        code = int(bail.code or 0)
    finally:
        repo_root.cache_clear()
        load_config.cache_clear()
    return code, buffer.getvalue()


def census(output: str) -> tuple[int, int, int]:
    match = CENSUS.search(output)
    assert match is not None, f'no census line in output:\n{output}'
    return tuple(int(g) for g in match.groups())


@contextlib.contextmanager
def corpus_repo():
    """A throwaway repo holding a copy of the nb corpus slice, cwd'd into."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / 'repo'
        shutil.copytree(CORPUS_NB, root)
        (root / 'project.godot').write_text('config_version=5\n', encoding='utf-8')
        target = root / 'systems/spatial_zones/zone2.gd'
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text('extends Node\n', encoding='utf-8')
        subprocess.run(['git', 'init', '-q'], cwd=root, check=True)
        previous = Path.cwd()
        os.chdir(root)
        try:
            yield root
        finally:
            os.chdir(previous)


class RetargetRewrites(unittest.TestCase):
    def test_rewrites_ext_resource_paths_and_preload_load_literals(self) -> None:
        with temp_repo('retarget_repo') as root:
            code, output = run_cli('refs', '--retarget', OLD, NEW)
            tscn = (root / 'scenes/user.tscn').read_text(encoding='utf-8')
            gd = (root / 'systems/consumer.gd').read_text(encoding='utf-8')
        files, rewritten, skipped = census(output)
        self.assertEqual((files, rewritten, skipped), (5, 3, 3), output)
        self.assertEqual(code, 1)                     # skips are findings
        self.assertIn(f'path="{NEW}"', tscn)
        self.assertNotIn(OLD, tscn)
        self.assertIn(f'preload("{NEW}")', gd)
        self.assertIn(f'load("{NEW}")', gd)

    def test_uid_attr_and_text_spelling_survive_the_rewrite(self) -> None:
        with temp_repo('retarget_repo') as root:
            before = (root / 'scenes/user.tscn').read_text(encoding='utf-8')
            run_cli('refs', '--retarget', OLD, NEW)
            after = (root / 'scenes/user.tscn').read_text(encoding='utf-8')
        self.assertIn('uid="uid://roldhelper0"', after)
        changed = [pair for pair in zip(before.splitlines(), after.splitlines())
                   if pair[0] != pair[1]]
        self.assertEqual(len(changed), 1)
        self.assertEqual(changed[0][0].replace(OLD, NEW), changed[0][1])

    def test_untouchable_occurrences_are_skipped_with_reasons(self) -> None:
        with temp_repo('retarget_repo') as root:
            _, output = run_cli('refs', '--retarget', OLD, NEW)
            gd = (root / 'systems/consumer.gd').read_text(encoding='utf-8')
        self.assertIn(f'# preload("{OLD}") stays put', gd)     # comment intact
        self.assertIn(f'var mention := "{OLD}"', gd)           # not a preload
        self.assertIn(f'var backup := "{OLD}.bak"', gd)        # substring
        self.assertIn('comment', output)
        self.assertIn('outside a preload/load', output)
        self.assertIn('substring', output)
        for line in output.splitlines():
            if 'SKIPPED' in line:
                self.assertRegex(line, r'consumer\.gd:\d+')

    def test_an_unreadable_file_is_skipped_not_a_traceback(self) -> None:
        # v0.16.0 release review: only UnicodeDecodeError was caught, so a
        # permission error mid-sweep stranded a partial rewrite behind a
        # stack trace with no census. The contract is skip-and-continue.
        if os.geteuid() == 0:
            self.skipTest('root ignores permission bits')
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

    def test_a_bystander_file_is_byte_identical(self) -> None:
        with temp_repo('retarget_repo') as root:
            before = (root / 'scenes/bystander.tscn').read_bytes()
            run_cli('refs', '--retarget', OLD, NEW)
            after = (root / 'scenes/bystander.tscn').read_bytes()
        self.assertEqual(before, after)

    def test_a_clean_retarget_exits_0(self) -> None:
        with temp_repo('retarget_repo'):
            code, output = run_cli('refs', '--retarget',
                                   'res://scripts/bystander.gd', NEW)
        self.assertEqual(census(output), (5, 1, 0), output)
        self.assertEqual(code, 0)

    def test_second_run_is_a_byte_level_no_op(self) -> None:
        with temp_repo('retarget_repo') as root:
            run_cli('refs', '--retarget', OLD, NEW)
            snapshot = {p: p.read_bytes() for p in sorted(root.rglob('*')) if p.is_file()}
            _, output = run_cli('refs', '--retarget', OLD, NEW)
            again = {p: p.read_bytes() for p in sorted(root.rglob('*')) if p.is_file()}
        self.assertEqual(census(output)[1], 0)        # nothing left to rewrite
        self.assertEqual(snapshot, again)

    def test_crlf_files_keep_their_endings(self) -> None:
        with temp_repo('retarget_repo') as root:
            scene = root / 'scenes/user.tscn'
            crlf = scene.read_text(encoding='utf-8').replace('\n', '\r\n').encode()
            scene.write_bytes(crlf)
            run_cli('refs', '--retarget', OLD, NEW)
            raw = scene.read_bytes()
        self.assertNotIn(b'\n', raw.replace(b'\r\n', b''))
        changed = [pair for pair in zip(crlf.split(b'\r\n'), raw.split(b'\r\n'))
                   if pair[0] != pair[1]]
        self.assertEqual(len(changed), 1)


class RetargetRefusals(unittest.TestCase):
    def test_refuses_when_the_new_target_does_not_exist(self) -> None:
        with temp_repo('retarget_repo') as root:
            before = (root / 'scenes/user.tscn').read_bytes()
            code, output = run_cli('refs', '--retarget', OLD, 'res://scripts/ghost.gd')
            after = (root / 'scenes/user.tscn').read_bytes()
        self.assertEqual(code, 1)
        self.assertIn('REFUSED', output)
        self.assertEqual(before, after)

    def test_usage_errors_exit_2(self) -> None:
        with temp_repo('retarget_repo'):
            for argv in ((OLD,),                       # one path
                         ('scripts/old.gd', NEW),      # not res://
                         (OLD, OLD)):                  # retarget onto itself
                buffer = io.StringIO()
                with contextlib.redirect_stderr(buffer):
                    code, _ = run_cli('refs', '--retarget', *argv)
                self.assertEqual(code, 2, argv)


class RetargetDryRun(unittest.TestCase):
    def test_dry_run_lists_every_site_and_writes_nothing(self) -> None:
        with temp_repo('retarget_repo') as root:
            before = {p: p.read_bytes() for p in sorted(root.rglob('*')) if p.is_file()}
            _, output = run_cli('refs', '--retarget', OLD, NEW, '--dry-run')
            after = {p: p.read_bytes() for p in sorted(root.rglob('*')) if p.is_file()}
        self.assertEqual(before, after)
        self.assertEqual(census(output)[1], 3)         # would rewrite
        self.assertIn('dry run', output)
        self.assertRegex(output, r'REWRITE\s+scenes/user\.tscn:3')
        self.assertRegex(output, r'REWRITE\s+systems/consumer\.gd:3')


class RetargetCorpusFidelity(unittest.TestCase):
    """The realistic bed: a moved script referenced by several real scenes."""

    OLD_ZONE = 'res://systems/spatial_zones/zone.gd'
    NEW_ZONE = 'res://systems/spatial_zones/zone2.gd'

    def test_only_the_referencing_lines_change_across_the_tree(self) -> None:
        needle = f'path="{self.OLD_ZONE}"'
        with corpus_repo() as root:
            files = [p for p in sorted(root.rglob('*'))
                     if p.suffix in ('.tscn', '.tres', '.gd')]
            before = {p.relative_to(root): p.read_bytes() for p in files}
            expected = sum(text.decode('utf-8').count(needle)
                           for text in before.values())
            self.assertGreaterEqual(expected, 3, 'corpus lost its zone.gd refs')
            code, output = run_cli('refs', '--retarget', self.OLD_ZONE, self.NEW_ZONE)
            after = {rel: (root / rel).read_bytes() for rel in before}
        _, rewritten, skipped = census(output)
        self.assertEqual((rewritten, skipped), (expected, 0), output)
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
                        old_line.replace(self.OLD_ZONE.encode(), self.NEW_ZONE.encode()),
                        new_line, f'{rel} rewrote more than the path attr')


if __name__ == '__main__':
    unittest.main()
