"""Tier 1 — `[<gate>] baseline`: a gate adopted frozen, then paid down.

`[test_shape] ledger` is the template: debt recorded per file at its current
measurement, failing only when it grows, and only ever shrinking. Here it is
generalised to the six gates whose findings belong to a file, and two claims
carry it. The ratchet's semantics are one function (`Baseline.judge`), proven
once at a function call. Each gate's WIRING is proven by the rule-4 probe
itself, on a scratch copy of its fixture: frozen at today's count it passes and
says how much it froze; an entry above what is left fails until lowered; and a
finding grown into a baselined file FAILS — the drift a frozen gate exists to
still catch.

No git here, deliberately: each gate's `git_lines` / `repo_root` are pointed at
the scratch tree, which keeps this proof in the no-spawn tier. The census those
two answer is what every other gate test proves through a real repo.
"""
from __future__ import annotations

import contextlib
import fnmatch
import io
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from support import FIXTURES

from godot_devkit.core.baseline import Baseline
from godot_devkit.core.config import ConfigError, path_count_table
from godot_devkit.godot.checks import (defaults, props, rng, tres, tres_comment,
                                       unit_disk)

LOAD_CONFIG = 'godot_devkit.core.config.load_config'


def _tracked_by(tracked: list[str]):
    """A `git_lines` answering `ls-files [--] <pathspec>...` from a list."""
    def git_lines(*args: str) -> list[str]:
        specs = [arg for arg in args[1:] if arg != '--']
        return [rel for rel in tracked if not specs or any(
            spec == '.' or fnmatch.fnmatch(rel, spec)
            or rel.startswith(spec.rstrip('/') + '/') for spec in specs)]
    return git_lines


def _run(module, root: Path, config: dict) -> tuple[int, str]:
    tracked = sorted(path.relative_to(root).as_posix()
                     for path in root.rglob('*') if path.is_file())
    out = io.StringIO()
    with mock.patch.object(module, 'git_lines', _tracked_by(tracked)), \
            mock.patch.object(module, 'repo_root', lambda: root), \
            mock.patch(LOAD_CONFIG, lambda: config), \
            contextlib.redirect_stdout(out):
        code = module.run()
    return code, out.getvalue()


class TheRatchet(unittest.TestCase):
    def test_equal_is_held_growth_is_unfrozen_and_an_entry_only_shrinks(self) -> None:
        baseline = Baseline('gate', {'held.gd': 2, 'grew.gd': 1,
                                     'shrunk.gd': 3, 'stale.gd': 1})
        found = [('grew.gd', 'g1'), ('held.gd', 'h1'), ('new.gd', 'n1'),
                 ('grew.gd', 'g2'), ('held.gd', 'h2'), ('shrunk.gd', 's1')]
        judged = baseline.judge(found)
        # Growth unfreezes EVERY finding of the file, in scan order: a count
        # cannot say which one is new. An unbaselined file is untouched.
        self.assertEqual(judged.open, ['g1', 'n1', 'g2'])
        self.assertEqual(judged.frozen, {'held.gd', 'shrunk.gd'})
        self.assertEqual(judged.held, 3)
        self.assertTrue(judged.failed)
        ratchet = '\n'.join(judged.ratchet)
        self.assertIn('GREW  grew.gd — 2 finding(s), over its [gate] baseline of 1', ratchet)
        self.assertIn('SHRUNK  shrunk.gd — 1 finding(s)', ratchet)
        self.assertIn('lower the entry to "shrunk.gd" = 1', ratchet)
        self.assertIn('STALE  stale.gd — no finding left', ratchet)
        self.assertEqual(judged.out_of_date, 2)          # GREW fails by its findings
        # Undeclared is invisible (rule 5): every finding open, in order, and
        # not one byte printed.
        bare = Baseline('gate', {}).judge(found)
        printed = io.StringIO()
        with contextlib.redirect_stdout(printed):
            bare.report()
        self.assertEqual(bare.open, [line for _, line in found])
        self.assertEqual(printed.getvalue(), '')
        self.assertFalse(bare.failed)

    def test_a_bad_baseline_shape_is_a_config_error_not_a_finding(self) -> None:
        for value, reason in (
                ('a.tres', 'must be a table'),
                ({'a.tres': '2'}, 'must be an integer'),
                ({'a.tres': True}, 'must be an integer'),
                ({'a.tres': 0}, 'at least one finding'),
                ({'/abs/a.tres': 1}, 'is absolute'),
                ({'res://a.tres': 1}, 'carries a scheme'),
                ({'data/../a.tres': 1}, 'dot or empty segment')):
            with self.subTest(value=value), self.assertRaises(ConfigError) as caught:
                path_count_table({'baseline': value}, 'gate', 'baseline')
            self.assertIn(reason, str(caught.exception))
        self.assertEqual(path_count_table({}, 'gate', 'baseline'), {})


class EveryGateFreezesAndStillCatchesGrowth(unittest.TestCase):
    """The rule-4 probe, once per gate: drift grown into a frozen file FAILS."""

    def _probe(self, module, fixture: str, only: list[str], section: str,
               rel: str, count: int, grow, marker: str, prepare) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in only:
                (root / name).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(FIXTURES / fixture / name, root / name)
            target = root / rel
            if prepare:
                target.write_text(prepare(target.read_text(encoding='utf-8')),
                                  encoding='utf-8')

            def at(ceiling: int) -> tuple[int, str]:
                return _run(module, root, {section: {'baseline': {rel: ceiling}}})

            code, out = at(count)
            self.assertEqual(code, 0, out)
            self.assertIn(f'  BASELINED  {count} finding(s) in 1 file(s) frozen '
                          f'by [{section}] baseline', out)
            self.assertNotIn(marker, out)
            code, out = at(count + 1)
            self.assertEqual(code, 1, out)
            self.assertIn(f'  SHRUNK  {rel} — {count} finding(s)', out)
            self.assertIn(f'1 [{section}] baseline entry above the findings left', out)
            target.write_text(grow(target.read_text(encoding='utf-8')),
                              encoding='utf-8')
            code, out = at(count)
            self.assertEqual(code, 1, out)
            self.assertIn(f'  GREW  {rel} — {count + 1} finding(s)', out)
            self.assertIn(marker, out)

    def test_each_gate_freezes_today_and_fails_a_finding_grown_past_it(self) -> None:
        # (gate, fixture, files copied, section, baselined file, its count
        #  today, the drift grown into it, the finding marker, a prepare step)
        user_path = 'tests/unit/planted_user_path.gd'
        for probe in (
                (tres_comment, 'tres_comment_repo',
                 ['project.godot', 'data/clean.tres', 'data/planted.tres'],
                 'tres_comment', 'data/planted.tres', 1,
                 lambda text: text + '; grown\n', 'STRIPPED  data/planted.tres', None),
                (unit_disk, 'unit_disk_repo',
                 ['project.godot', 'tests/unit/clean.gd', user_path],
                 'unit_disk', user_path, 1,
                 lambda text: text + '\nfunc _grown() -> String:\n'
                                     '\treturn "user://grown"\n',
                 f'DISK-WRITE  {user_path}', None),
                (rng, 'rng_repo',
                 ['project.godot', 'systems/clean.gd', 'systems/loot.gd'],
                 'rng', 'systems/loot.gd', 2,
                 lambda text: text + '\nfunc _grown() -> int:\n\treturn randi()\n',
                 'BARE-RNG  systems/loot.gd', None),
                (defaults, 'defaults_repo',
                 ['project.godot', 'data/redundant.tres', 'systems/rule.gd',
                  'systems/base_rule.gd', 'systems/ids.gd'],
                 'defaults', 'data/redundant.tres', 15,
                 lambda text: text + 'untouched = 0\n',
                 'REDUNDANT  data/redundant.tres', None),
                (props, 'props_repo',
                 ['project.godot', 'systems/contract.gd', 'scenes/clean.tscn',
                  'scenes/drift.tscn'],
                 'props', 'scenes/drift.tscn', 2,
                 lambda text: text + 'phantom_grown = 1\n',
                 'DEAD  scenes/drift.tscn', None),
                # No fixture carries a path-only ref, so the probe makes one:
                # strip the uid from one ref, then — the growth — the other.
                (tres, 'uid_repo',
                 ['project.godot', 'systems/rule.gd', 'systems/rule.gd.uid',
                  'scenes/clean.tscn', 'scenes/drifted.tscn'],
                 'tres', 'scenes/drifted.tscn', 1,
                 lambda text: text.replace('uid="uid://dstaleuid000" ', '', 1),
                 'PATH-ONLY  scenes/drifted.tscn',
                 lambda text: text.replace('uid="uid://dcleanscene0" ', '', 1))):
            with self.subTest(gate=probe[3]):
                self._probe(*probe)
