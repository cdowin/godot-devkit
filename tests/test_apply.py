"""core/apply — the honesty contract of the one module that mutates disk.

The module's promise (its own docstring, line 21): there is no way to get a
partial result that does not say so. Two findings from the 2026-08-30 audit
broke it — DELETE_TREE swallowed failures via `ignore_errors=True`, and the
case-only-rename carve-out was both too narrow (mixed-case renames falsely
Blocked) and too wide (a DIFFERENT file matching `src.name.upper()` was
silently overwritable). Both are pinned here, with DELETE_FILE (which joined
apply for the uid ORPHAN fix) held to the same terms.
"""
import os
import shutil
import tempfile
import unittest
from pathlib import Path

import support  # noqa: F401 — puts src/ on sys.path

from godot_devkit.core import apply


class ApplyHonesty(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def read_only(self, directory: Path) -> None:
        if os.geteuid() == 0:
            self.skipTest('root ignores permission bits')
        directory.chmod(0o555)
        self.addCleanup(directory.chmod, 0o755)

    def test_a_delete_that_cannot_happen_is_decided_or_reported_never_landed(self) -> None:
        sub = self.tmp / 'tree' / 'sub'
        sub.mkdir(parents=True)
        (sub / 'grain.md').write_text('x', encoding='utf-8')
        self.read_only(sub)                          # rmtree cannot unlink inside
        applied = apply.Plan().delete_tree(sub.parent).apply(decide=False)
        self.assertIsNotNone(applied.failed, 'delete failed on disk but reported landed')
        self.assertTrue((sub / 'grain.md').exists())
        # DELETE_FILE decides the same two obstructions before touching a byte:
        # an unlink writes the DIRECTORY, and a directory is not a file.
        self.assertEqual([b.reason for b in apply.Plan().delete_file(sub / 'grain.md').decide()],
                         [apply.Obstruction.PARENT_NOT_WRITABLE])
        self.assertTrue((sub / 'grain.md').is_file(), 'decide() must not touch disk')
        target = self.tmp / 'not_a_file'
        target.mkdir()
        self.assertEqual([b.reason for b in apply.Plan().delete_file(target).decide()],
                         [apply.Obstruction.NOT_A_REGULAR_FILE])
        self.assertTrue(target.is_dir(), 'decide() must not touch disk')
        # A target already gone is the desired end state (idempotent), tree or file.
        for applied in (apply.Plan().delete_tree(self.tmp / 'never-existed').apply(decide=False),
                        apply.remove_file(self.tmp / 'gone.gd.uid')):
            self.assertIsNone(applied.failed)
            self.assertEqual(len(applied.landed), 1)

    # The case-only-rename carve-out exists for ONE situation: renaming a file
    # to a case-variant of itself on a case-insensitive filesystem, where
    # `dest.exists()` is true because it IS the source.
    def test_a_mixed_case_respelling_of_the_same_file_is_not_a_collision(self) -> None:
        src = self.tmp / 'grain.md'
        src.write_text('x', encoding='utf-8')
        dest = self.tmp / 'GrAiN.md'                 # ≠ lower() ≠ upper()
        applied = apply.Plan().move(src, dest).apply()
        self.assertEqual(applied.blocked, ())
        self.assertIsNone(applied.failed)
        self.assertIn('GrAiN.md', os.listdir(self.tmp))

    def test_a_different_existing_file_is_a_collision_whatever_its_case(self) -> None:
        src = self.tmp / 'foo.txt'
        src.write_text('source', encoding='utf-8')
        for dest in (self.tmp / 'b' / 'FOO.TXT',      # matches src.name.upper()…
                     self.tmp / 'bar.txt'):           # …or is unrelated
            dest.parent.mkdir(exist_ok=True)
            dest.write_text('someone else\'s file', encoding='utf-8')
            self.assertEqual([entry.reason for entry in apply.Plan().move(src, dest).decide()],
                             [apply.Obstruction.EXISTS],
                             '…but it is a DIFFERENT file, and overwriting it is not a rename')
            self.assertEqual(dest.read_text(encoding='utf-8'), "someone else's file")
