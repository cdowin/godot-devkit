"""`autoloads add` / `autoloads rm` — the one write verb over `project.godot`.

Five properties, one case each: an `add` lands as exactly one line the census
then reads (plus the header when the section was absent); `rm` is its exact
inverse, byte for byte, on LF and CRLF alike; every refusal leaves the file
byte-identical; a repeat is a no-op; `--dry-run` prints and writes nothing.

Altitude: `main(argv)` over a temp copy of `tests/fixtures/read_repo/`, with
the repo root pointed at the copy — the verb's own git lookup would be the only
process in the file, and it is not what is under test.
"""
from __future__ import annotations

import contextlib
import difflib
import io
import shutil
import tempfile
import unittest
import unittest.mock
from pathlib import Path

from support import FIXTURES

from godot_devkit.godot.read import autoloads
from godot_devkit.godot.write import autoloads_edit

PLAYER = 'res://systems/player.gd'
SPAWNER = 'res://systems/spawner.gd'
# Not `Player`: that is the fixture's `class_name`, and an autoload may not
# shadow one.
NAME = 'Hero'
ENTRY = f'{NAME}="*{PLAYER}"'


class AutoloadsEdit(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name) / 'repo'
        shutil.copytree(FIXTURES / 'read_repo', self.root)
        self.project = self.root / 'project.godot'
        patch = unittest.mock.patch.object(autoloads_edit, 'repo_root', lambda: self.root)
        patch.start()
        self.addCleanup(patch.stop)

    def run_verb(self, *argv: str) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = autoloads_edit.main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def bytes_(self) -> bytes:
        return self.project.read_bytes()

    def variants(self) -> dict[str, bytes]:
        """The fixture as-is, as CRLF, with no `[autoload]` section at all, and
        that last with no final newline."""
        lf = self.bytes_()
        bare = lf.split(b'[autoload]')[0].rstrip(b'\n') + b'\n'
        return {'lf': lf, 'crlf': lf.replace(b'\n', b'\r\n'), 'no section': bare,
                'no section, no final newline': bare.rstrip(b'\n')}

    def test_add_is_one_line_the_census_reads_and_rm_restores_the_bytes(self) -> None:
        for label, before in self.variants().items():
            with self.subTest(label):
                self.project.write_bytes(before)
                self.assertEqual(self.run_verb('add', NAME, PLAYER)[0], 0)
                after = self.bytes_()
                added = [line for line in difflib.ndiff(
                    before.decode().splitlines(), after.decode().splitlines())
                    if line.startswith(('+ ', '- '))]
                expected = (['+ [autoload]', f'+ {ENTRY}'] if label.startswith('no section')
                            else [f'+ {ENTRY}'])
                self.assertEqual([line for line in added if line[2:].strip()],
                                 expected)
                if label == 'crlf':
                    self.assertIn(ENTRY.encode() + b'\r\n', after)
                    self.assertNotIn(b'\r\r', after)
                self.assertEqual(autoloads.list_autoloads(self.root)[-1],
                                 (NAME, 'systems/player.gd'))
                self.assertEqual(self.run_verb('rm', NAME)[0], 0)
                self.assertEqual(self.bytes_(), before)

    def test_rm_removes_exactly_that_line(self) -> None:
        before = self.bytes_()
        self.assertEqual(self.run_verb('rm', 'GameManager')[0], 0)
        expected = b''.join(line for line in before.splitlines(keepends=True)
                            if not line.startswith(b'GameManager='))
        self.assertEqual(self.bytes_(), expected)

    def test_each_refusal_leaves_the_file_byte_identical(self) -> None:
        cases = [
            (('add', 'GameManager', SPAWNER), 1, 'res://autoloads/core/game_manager.gd'),
            (('add', 'Spawner', 'res://systems/missing.gd'), 1, 'does not exist'),
            (('add', '1Spawner', SPAWNER), 1, 'not a valid autoload name'),
            (('add', 'Spawner', 'systems/spawner.gd'), 1, 'not a res:// path'),
            (('add', 'Spawner', 'res://../outside.gd'), 1, 'inside the project'),
            # Declared without `*`: `unchanged` would claim a singleton that
            # does not exist.
            (('add', 'Dormant', SPAWNER), 1, 'declared but disabled'),
            # A second spelling of one file would make the next `add` of the
            # canonical one refuse as a "different path".
            (('add', 'Spawner', 'res://systems//spawner.gd'), 1, SPAWNER),
            (('add', 'Spawner', 'res://systems/./spawner.gd'), 1, SPAWNER),
            (('add', 'Spawner', 'res://autoloads/../systems/spawner.gd'), 1, SPAWNER),
            # Names the editor refuses: an engine class, a project class_name.
            (('add', 'Input', SPAWNER), 1, 'engine class'),
            (('add', 'Player', PLAYER), 1, f'class_name of {PLAYER}'),
            # A wrong-case path: a case-insensitive filesystem finds the file,
            # a case-sensitive export does not. Refused on either, naming the
            # on-disk spelling.
            (('add', 'Spawner', 'res://Systems/Spawner.gd'), 1, SPAWNER),
        ]
        self.project.write_bytes(self.bytes_() + f'Dormant="{SPAWNER}"\n'.encode())
        before = self.bytes_()
        for argv, code, reason in cases:
            with self.subTest(argv=argv):
                got, out, _ = self.run_verb(*argv)
                self.assertEqual((got, self.bytes_()), (code, before))
                self.assertIn('REFUSED', out)
                self.assertIn(reason, out)
        for label, content in (('not utf-8', b'[autoload]\n\nA="*res://\xff.gd"\n'),
                               ('missing', None)):
            with self.subTest(label):
                if content is None:
                    self.project.unlink()
                else:
                    self.project.write_bytes(content)
                got, _, err = self.run_verb('add', 'Spawner', SPAWNER)
                self.assertEqual(got, 2, err)
                self.assertIn('project.godot', err)
                self.assertEqual(self.project.read_bytes() if content else None, content)

    def test_the_class_name_scan_sees_what_the_editor_sees(self) -> None:
        # Godot's own rule: a dot-prefixed directory and one holding a
        # `.gdignore` are invisible to the editor; `addons/` is not.
        for where, gdignore, code in (('.claude/worktrees/x', False, 0),
                                      ('addons/foo', False, 1),
                                      ('vendor/raw', True, 0)):
            with self.subTest(where):
                name = f'Ghost{code}{int(gdignore)}{len(where)}'
                script = self.root / where / 'ghost.gd'
                script.parent.mkdir(parents=True)
                script.write_text(f'class_name {name}\nextends Node\n',
                                  encoding='utf-8')
                if gdignore:
                    (self.root / where.split('/')[0] / '.gdignore').write_text('')
                got, out, _ = self.run_verb('add', name, SPAWNER, '--dry-run')
                self.assertEqual(got, code, out)
                if code:
                    self.assertIn(f'class_name of res://{where}/ghost.gd', out)

    def test_the_same_add_or_rm_twice_is_a_no_op(self) -> None:
        for argv in (('add', NAME, PLAYER), ('rm', NAME)):
            with self.subTest(argv=argv):
                self.assertEqual(self.run_verb(*argv)[0], 0)
                settled = self.bytes_()
                code, out, _ = self.run_verb(*argv)
                self.assertEqual((code, self.bytes_()), (0, settled))
                self.assertIn('unchanged', out)
        self.assertIn('not declared', self.run_verb('rm', NAME)[1])

    def test_dry_run_prints_the_diff_and_writes_nothing(self) -> None:
        before = self.bytes_()
        code, out, _ = self.run_verb('add', NAME, PLAYER, '--dry-run')
        self.assertEqual((code, self.bytes_()), (0, before))
        self.assertIn(f'+{ENTRY}', out)
        self.assertIn('dry run', out)


if __name__ == '__main__':
    unittest.main()
