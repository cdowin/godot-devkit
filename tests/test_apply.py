"""core/apply — the honesty contract of the one module that mutates disk.

The module's promise (its own docstring, line 21): there is no way to get a
partial result that does not say so. Two findings from the 2026-08-30 audit
broke it — DELETE_TREE swallowed failures via `ignore_errors=True`, and the
case-only-rename carve-out was both too narrow (mixed-case renames falsely
Blocked) and too wide (a DIFFERENT file matching `src.name.upper()` was
silently overwritable). Both are pinned here.
"""
from __future__ import annotations

import os
import shutil
import tempfile
import unittest
from pathlib import Path

import support  # noqa: F401 — puts src/ on sys.path

from godot_devkit.core import apply


class TmpCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)


class DeleteTreeHonesty(TmpCase):
    def test_a_failed_delete_is_reported_not_landed(self) -> None:
        if os.geteuid() == 0:
            self.skipTest('root ignores permission bits')
        tree = self.tmp / 'tree'
        sub = tree / 'sub'
        sub.mkdir(parents=True)
        (sub / 'grain.md').write_text('x', encoding='utf-8')
        sub.chmod(0o555)                             # rmtree cannot unlink inside
        self.addCleanup(sub.chmod, 0o755)
        applied = apply.Plan().delete_tree(tree).apply(decide=False)
        self.assertIsNotNone(applied.failed, 'delete failed on disk but reported landed')
        self.assertTrue((sub / 'grain.md').exists())

    def test_a_tree_already_gone_is_the_desired_end_state(self) -> None:
        applied = apply.Plan().delete_tree(self.tmp / 'never-existed').apply(decide=False)
        self.assertIsNone(applied.failed)
        self.assertEqual(len(applied.landed), 1)


class CaseOnlyRenamePredicate(TmpCase):
    """The carve-out exists for ONE situation: renaming a file to a
    case-variant of itself on a case-insensitive filesystem, where
    `dest.exists()` is true because it IS the source."""

    def test_a_mixed_case_respelling_of_the_same_file_is_not_a_collision(self) -> None:
        src = self.tmp / 'grain.md'
        src.write_text('x', encoding='utf-8')
        dest = self.tmp / 'GrAiN.md'                 # ≠ lower() ≠ upper()
        applied = apply.Plan().move(src, dest).apply()
        self.assertEqual(applied.blocked, ())
        self.assertIsNone(applied.failed)
        self.assertIn('GrAiN.md', os.listdir(self.tmp))

    def test_a_case_matching_but_different_file_is_a_collision(self) -> None:
        src = self.tmp / 'a' / 'foo.txt'
        dest = self.tmp / 'b' / 'FOO.TXT'            # matches src.name.upper()…
        src.parent.mkdir()
        dest.parent.mkdir()
        src.write_text('source', encoding='utf-8')
        dest.write_text('someone else\'s file', encoding='utf-8')
        blocked = apply.Plan().move(src, dest).decide()
        self.assertEqual([entry.reason for entry in blocked],
                         [apply.Obstruction.EXISTS],
                         '…but it is a DIFFERENT file, and overwriting it is not a rename')
        self.assertEqual(dest.read_text(encoding='utf-8'), "someone else's file")

    def test_an_unrelated_existing_destination_is_still_a_collision(self) -> None:
        src = self.tmp / 'foo.txt'
        dest = self.tmp / 'bar.txt'
        src.write_text('x', encoding='utf-8')
        dest.write_text('y', encoding='utf-8')
        blocked = apply.Plan().move(src, dest).decide()
        self.assertEqual([entry.reason for entry in blocked], [apply.Obstruction.EXISTS])


if __name__ == '__main__':
    unittest.main()


class DeleteFileContract(TmpCase):
    """DELETE_FILE joined apply for the uid ORPHAN fix — same honesty terms."""

    def test_a_file_already_gone_is_the_desired_end_state(self) -> None:
        applied = apply.remove_file(self.tmp / 'gone.gd.uid')
        self.assertEqual(applied.failed, None)
        self.assertEqual(len(applied.landed), 1)

    def test_a_directory_is_a_decided_obstruction_not_a_surprise(self) -> None:
        target = self.tmp / 'not_a_file'
        target.mkdir()
        blocked = apply.Plan().delete_file(target).decide()
        self.assertEqual([b.reason for b in blocked],
                         [apply.Obstruction.NOT_A_REGULAR_FILE])
        self.assertTrue(target.is_dir(), 'decide() must not touch disk')

    def test_an_unwritable_parent_is_decided_before_any_byte(self) -> None:
        if os.geteuid() == 0:
            self.skipTest('root ignores permission bits')
        parent = self.tmp / 'ro'
        parent.mkdir()
        victim = parent / 'orphan.gd.uid'
        victim.write_text('uid://abc\n', encoding='utf-8')
        parent.chmod(0o555)
        self.addCleanup(parent.chmod, 0o755)
        blocked = apply.Plan().delete_file(victim).decide()
        self.assertEqual([b.reason for b in blocked],
                         [apply.Obstruction.PARENT_NOT_WRITABLE])
        self.assertTrue(victim.is_file(), 'decide() must not touch disk')
