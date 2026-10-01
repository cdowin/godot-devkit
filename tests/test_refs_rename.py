"""`refs --rename`: a class_name, method, signal or autoload renamed everywhere, or nowhere.

`main(argv)` in-process over temp copies of `tests/fixtures/read_repo/` (and
one corpus scene). Four properties are load-bearing: every typed hit is
rewritten and nothing else is (`refs <new>` afterwards counts what `refs <old>`
counted before); any blocking site refuses the whole plan, names every site
and leaves every byte where it was; the same rename twice is a no-op; and a
corpus scene round-trips byte-identical outside the renamed token.
"""
import re
import types
import unittest

from support import run_check, temp_repo

from godot_devkit import cli
from godot_devkit.godot.read import refs


def run_cli(*argv):
    # `cli.main(argv)` wearing a check's `run()` face, so `run_check` clears
    # the repo-root/config caches around the cwd change and captures stdout.
    return run_check(types.SimpleNamespace(run=lambda: cli.main(list(argv))))


def refs_count(symbol):
    """Every hit `refs <symbol>` prints, across all its buckets."""
    _, out = run_check(types.SimpleNamespace(run=lambda: refs.main([symbol])))
    return sum(int(n) for n in re.findall(r'^## .* \((\d+)\)$', out, re.M))


def snapshot(root):
    return {p: p.read_bytes() for p in sorted(root.rglob('*'))
            if p.is_file() and '.git' not in p.parts}


class RenameRewrites(unittest.TestCase):
    # (old, new, the file a dry run must show) — a `[connection] method=` plus
    # its handler's definition, and an autoload's `project.godot` key plus a use.
    RENAMES = (
        ('_on_button_pressed', '_on_button_clicked', 'scenes/main.tscn'),
        ('DataRegistry', 'Registry', 'project.godot'),
    )

    def test_every_typed_hit_is_rewritten_once_and_a_retry_is_a_no_op(self) -> None:
        for old, new, shown in self.RENAMES:
            with self.subTest(old=old), temp_repo('read_repo') as root:
                counted = refs_count(old)
                before = snapshot(root)
                code, dry = run_cli('refs', '--rename', old, new, '--dry-run')
                self.assertEqual((code, snapshot(root)), (0, before), dry)
                self.assertIn(f'+++ b/{shown}', dry)
                code, out = run_cli('refs', '--rename', old, new)
                after = snapshot(root)
                self.assertEqual(code, 0, out)
                # Only the token moved: every file is its old bytes with the
                # name swapped, and nothing outside the hit set changed.
                self.assertEqual(after, {p: b.replace(old.encode(), new.encode())
                                         for p, b in before.items()})
                self.assertNotEqual(after, before)
                self.assertEqual((refs_count(new), refs_count(old)), (counted, 0))
                code, again = run_cli('refs', '--rename', old, new)
                self.assertEqual((code, snapshot(root)), (0, after), again)
                self.assertIn('already renamed', again)
                self.assertIn('0 rewritten, 0 blocked', again)

    def test_a_corpus_scene_round_trips_outside_the_renamed_token(self) -> None:
        old, new = '_on_detector_body_entered', '_on_detector_entered'
        scene = 'systems/hazards/hazard.tscn'
        with temp_repo('corpus/editor_written', only=[scene]) as root:
            (root / 'systems/hazards/hazard.gd').write_text(
                f'extends Area2D\n\n\nfunc {old}(body: Node2D) -> void:\n\tpass\n',
                encoding='utf-8')
            before = (root / scene).read_bytes()
            code, out = run_cli('refs', '--rename', old, new)
            after = (root / scene).read_bytes()
        self.assertEqual(code, 0, out)
        self.assertEqual(after, before.replace(f'method="{old}"'.encode(),
                                               f'method="{new}"'.encode()))
        changed = [a for a, b in zip(before.splitlines(), after.splitlines()) if a != b]
        self.assertEqual(len(changed), 1)


class RenameRefuses(unittest.TestCase):
    EXTRA_GD = ('extends Node\n'
                '\n'
                'var s := "x.hurt(1)"\n'          # 3: a claimed token in a string
                'func go(p) -> void:\n'
                '\tp.call("hurt")\n'              # 5: a string that IS the name
                '\tvar cb := hurt\n'              # 6: a callable reference, unproven
                '\tself.hurt(wound)\n')           # 7: the line carries <new>
    EXTRA_TRES = '[gd_resource type="Resource" format=3]\n\n[resource]\nmethod = &"hurt"\n'

    # (extra files, old, new, every phrase the refusal must name)
    REFUSALS = (
        ({}, 'died', 'perished', ('systems/player.gd:21', 'systems/player.gd:24',
                                  'systems/player.gd:25', 'systems/player.gd:26',
                                  '4 blocked')),
        ({}, 'Player', 'Hero', ('scenes/main.tscn  a res:// path',)),
        ({}, 'GameManager', 'Manager', ('systems/spawner.gd:10  a dynamic hit',)),
        ({'systems/extra.gd': EXTRA_GD, 'data/anim.tres': EXTRA_TRES}, 'hurt', 'wound',
         ('systems/extra.gd:3  inside a string literal', 'systems/extra.gd:5  a string that IS',
          'systems/extra.gd:6  an occurrence no typed arm proves',
          'systems/extra.gd:7  the line already carries wound',
          'data/anim.tres:4  a StringName', '5 blocked')),
        ({}, 'hurt', 'watch', ('systems/player.gd:20  watch is already defined',)),
        ({}, 'pressed', 'clicked', ('scenes/main.tscn:12  a reference to pressed, which '
                                    'nothing here defines',)),
        ({}, 'nothing_here', 'anything', ('nothing to rename',)),
    )

    def test_each_refusal_names_every_blocking_site_and_writes_nothing(self) -> None:
        for extra, old, new, phrases in self.REFUSALS:
            with self.subTest(old=old, new=new), temp_repo('read_repo') as root:
                for rel, text in extra.items():
                    (root / rel).parent.mkdir(parents=True, exist_ok=True)
                    (root / rel).write_text(text, encoding='utf-8')
                before = snapshot(root)
                code, out = run_cli('refs', '--rename', old, new)
                self.assertEqual((code, snapshot(root)), (1, before), out)
                self.assertIn('REFUSED', out)
                for phrase in phrases:
                    self.assertIn(phrase, out)

    def test_a_name_that_is_not_an_identifier_is_a_usage_error(self) -> None:
        with temp_repo('read_repo'):
            for argv in (('hurt', '1bad'), ('hurt', 'hurt'), ('res://x.gd', 'y')):
                with self.subTest(argv=argv), self.assertRaises(SystemExit) as raised:
                    run_cli('refs', '--rename', *argv)
                self.assertEqual(raised.exception.code, 2)


if __name__ == '__main__':
    unittest.main()
