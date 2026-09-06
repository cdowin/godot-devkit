"""scene-diff — read output is write input, and exit codes are contract.

Two audit findings pinned here: the root row used to be keyed by the root's
NAME (so a root rename rendered as remove+add and the row was not a valid
write address — the write verbs spell the root `.`), and a bad git ref exited
1, which the exit-code contract reserves for findings (environment errors
are 2).
"""
from __future__ import annotations

import contextlib
import io
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import support  # noqa: F401 — puts src/ on sys.path

from godot_devkit.godot.read import scene_diff
from godot_devkit.godot.format.tscn import REF_ARROW

OLD_SCENE = ('[gd_scene format=3]\n'
             '\n'
             '[node name="OldRoot" type="Node2D"]\n'
             '\n'
             '[node name="Child" type="Node2D" parent="."]\n')
NEW_SCENE = OLD_SCENE.replace('OldRoot', 'NewRoot')


class SceneDiffContract(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)

    def diff(self, *argv: str) -> str:
        """Run a diff that must exit 0; its report."""
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(scene_diff.main([*argv]), 0)
        return out.getvalue()

    def test_a_root_rename_is_a_change_on_dot_not_a_remove_add(self) -> None:
        old = self.tmp / 'old.tscn'
        new = self.tmp / 'new.tscn'
        old.write_text(OLD_SCENE, encoding='utf-8')
        new.write_text(NEW_SCENE, encoding='utf-8')
        text = self.diff(str(old), str(new))
        self.assertIn('~ .', text)                    # the write verbs' root address
        self.assertIn(f'name: OldRoot {REF_ARROW} NewRoot', text)
        self.assertNotIn('+ NewRoot', text)           # not a whole-tree swap
        self.assertNotIn('- OldRoot', text)
        # The other output shape: identical scenes still say so.
        self.assertIn('no structural differences', self.diff(str(old), str(old)))

    def test_a_ref_git_cannot_serve_exits_2_not_1(self) -> None:
        scene = self.tmp / 'scene.tscn'
        scene.write_text(OLD_SCENE, encoding='utf-8')
        subprocess.run(['git', 'init', '-q'], cwd=self.tmp, check=True)
        self.addCleanup(os.chdir, Path.cwd())
        os.chdir(self.tmp)                            # a repo with NO commits: HEAD is unservable
        with contextlib.redirect_stderr(io.StringIO()), \
                contextlib.redirect_stdout(io.StringIO()), \
                self.assertRaises(SystemExit) as caught:
            scene_diff.main(['scene.tscn', '--git', 'HEAD'])
        self.assertEqual(caught.exception.code, 2)
