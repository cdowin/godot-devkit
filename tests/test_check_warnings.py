"""Tier 2 — `check warnings`: analyzer warnings held at error level in project.godot."""
import unittest

from support import run_check, temp_repo

from godot_devkit.core.config import ConfigError
from godot_devkit.godot.checks import warnings

STOCK = ('unused_variable', 'shadowed_variable', 'unused_signal',
         'integer_division', 'standalone_expression')


def _gate(debug_lines, config=None):
    """One run in a throwaway repo whose project.godot carries `debug_lines` under [debug]."""
    with temp_repo('godot_project', only=['project.godot']) as root:
        head = (root / 'project.godot').read_text(encoding='utf-8').split('[debug]')[0]
        (root / 'project.godot').write_text(head + '[debug]\n\n' + debug_lines, encoding='utf-8')
        if config:
            (root / 'godot-devkit.toml').write_text(config, encoding='utf-8')
        return run_check(warnings)


def _lines(names, level=2):
    return ''.join(f'gdscript/warnings/{n}={level}\n' for n in names)


class TheWarningsGate(unittest.TestCase):
    def test_every_stock_warning_at_error_level_passes(self) -> None:
        code, out = _gate(_lines(STOCK))
        self.assertEqual(code, 0, out)
        self.assertIn('[check:warnings] PASS', out)

    def test_a_missing_or_low_warning_fails_and_prints_the_lines_to_paste(self) -> None:
        code, out = _gate(_lines(STOCK[1:]) + 'gdscript/warnings/unused_variable=1\n')
        self.assertEqual(code, 1, out)
        self.assertIn('unused_variable is 1, want 2', out)
        self.assertIn('    gdscript/warnings/unused_variable=2', out)
        code, out = _gate(_lines(STOCK[1:]))
        self.assertIn('unused_variable is unset', out)

    def test_a_key_outside_debug_does_not_count(self) -> None:
        with temp_repo('godot_project', only=['project.godot']) as root:
            (root / 'project.godot').write_text(
                '[other]\n' + _lines(STOCK) + '[debug]\n', encoding='utf-8')
            code, out = run_check(warnings)
        self.assertEqual(code, 1, out)

    def test_errors_config_narrows_the_list_and_a_bad_name_is_exit_two(self) -> None:
        code, out = _gate(_lines(['unused_variable']), '[warnings]\nerrors = ["unused_variable"]\n')
        self.assertEqual(code, 0, out)
        with self.assertRaises(ConfigError):
            _gate('', '[warnings]\nerrors = ["Bad Name"]\n')
        with self.assertRaises(ConfigError):
            _gate('', '[warnings]\nerrors = "unused_variable"\n')

    def test_no_project_godot_fails_loudly(self) -> None:
        with temp_repo('godot_project', only=['project.godot']) as root:
            (root / 'project.godot').unlink()
            code, out = run_check(warnings)
        self.assertEqual(code, 1, out)
        self.assertIn('scanned 0', out)
