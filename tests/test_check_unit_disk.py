"""Tier 2 — `check unit-disk`, ported from a consumer's shell scan.

The scan it replaces had five checks against one project's save/settings
owners; here the owners are config and the gate is the shape. Every one of the
five is reproduced below through `forbidden_calls` / `min_args`, alongside the
one thing the stock gate knows without being told: a `user://` path in a
no-boot test is a real path in a tier that claims it cannot reach one.

The false-positive cases matter as much: a call NAMED in an assert message or a
doc comment is not a call, and a call given its throwaway root explicitly is
the shape the gate exists to ask for.
"""
from __future__ import annotations

import unittest

from support import run_check, temp_repo

from godot_devkit.core.config import ConfigError
from godot_devkit.godot.checks import unit_disk

BASE = ['project.godot']
CLEAN = [*BASE, 'tests/unit/clean.gd', 'tests/support/helper.gd']
PLANTED = [
    *CLEAN,
    'tests/unit/planted_user_path.gd',
    'tests/unit/planted_slot.gd',
    'tests/unit/planted_path_const.gd',
    'tests/unit/planted_save.gd',
    'tests/unit/planted_scan.gd',
    'tests/unit/planted_settings.gd',
]
# The consumer's five checks, restated as config. The prose that used to live
# in the scan's header is the label — it rides every finding.
CONSUMER = r'''[unit_disk]
min_args = { "SaveService.save" = 2, "SaveService.load" = 2, "SaveSlotIndex.scan" = 1 }

# A sub-table, not an inline one: TOML inline tables are single-line, and a
# roster of regexes that has to fit on one line is a roster nobody reads. The
# key is the LABEL — it rides every finding, so the prose that used to live in
# the scan's header is the thing a reader gets back.
[unit_disk.forbidden_calls]
"a real save slot, minted through the live manager" = [
    'SaveSlotManager\.(create_new_slot|load_slot)\(']
"a real persistent-path constant" = [
    'PathConstants\.(SETTINGS_PATH|SAVE_DIR|PLAYER_SAVE_DIR_PATTERN)\b']
"the live settings autoload's disk calls" = [
    'SettingsManager\.(save_settings|load_settings|reset_to_defaults)\(']
'''


def _config(root, body: str) -> None:
    (root / 'devkit.toml').write_text(body, encoding='utf-8')


class TheStockGate(unittest.TestCase):
    """What it knows with no config at all: `user://` is a real path."""

    def test_a_user_path_literal_is_a_finding(self) -> None:
        with temp_repo('unit_disk_repo', only=[*CLEAN, 'tests/unit/planted_user_path.gd']):
            code, out = run_check(unit_disk)
        self.assertEqual(code, 1, out)
        self.assertIn('DISK-WRITE  tests/unit/planted_user_path.gd:4', out)
        self.assertIn('a real user:// path', out)

    def test_the_clean_test_passes(self) -> None:
        with temp_repo('unit_disk_repo', only=CLEAN):
            code, out = run_check(unit_disk)
        self.assertEqual(code, 0, out)
        self.assertIn('[check:unit-disk] PASS — 1 test file(s)', out)

    def test_a_file_outside_the_roots_is_not_scanned(self) -> None:
        """The shared helper lives outside the scan root ON PURPOSE — it is the
        thing tests are supposed to route through."""
        with temp_repo('unit_disk_repo', only=CLEAN):
            code, out = run_check(unit_disk)
        self.assertEqual(code, 0)
        self.assertNotIn('tests/support/helper.gd', out)


class TheConsumersFiveChecks(unittest.TestCase):
    def test_every_planted_violation_is_caught(self) -> None:
        with temp_repo('unit_disk_repo', only=PLANTED) as root:
            _config(root, CONSUMER)
            code, out = run_check(unit_disk)
        self.assertEqual(code, 1, out)
        for planted in ('planted_user_path', 'planted_slot', 'planted_path_const',
                        'planted_save', 'planted_scan', 'planted_settings'):
            self.assertIn(planted, out)
        self.assertIn('6 violation(s)', out)

    def test_a_default_root_call_names_the_arity_it_needed(self) -> None:
        with temp_repo('unit_disk_repo', only=PLANTED) as root:
            _config(root, CONSUMER)
            code, out = run_check(unit_disk)
        self.assertEqual(code, 1)
        self.assertIn('SaveService.save given 1 argument(s), needs 2', out)
        self.assertIn('SaveSlotIndex.scan given 0 argument(s), needs 1', out)

    def test_the_sanctioned_redirect_shape_is_spared(self) -> None:
        """An explicit throwaway root, a call named in an assert message, a doc
        comment naming `user://`, and a lone STRING argument — none is a
        finding. The last one is why quoted spans are masked rather than
        deleted: `scan("res://throwaway")` is one argument, not zero."""
        with temp_repo('unit_disk_repo', only=CLEAN) as root:
            _config(root, CONSUMER)
            code, out = run_check(unit_disk)
        self.assertEqual(code, 0, out)


class RefusesRatherThanGuesses(unittest.TestCase):
    def test_an_unbalanced_call_is_declined_not_guessed_at(self) -> None:
        with temp_repo('unit_disk_repo', only=CLEAN) as root:
            (root / 'tests/unit/wrapped.gd').write_text(
                'func _s(uuid: String) -> bool:\n\treturn SaveService.save(\n\t\tuuid)\n',
                encoding='utf-8')
            _config(root, CONSUMER)
            code, out = run_check(unit_disk)
        self.assertEqual(code, 0, out)

    def test_a_min_args_floor_below_one_is_refused(self) -> None:
        with temp_repo('unit_disk_repo', only=PLANTED) as root:
            _config(root, '[unit_disk]\nmin_args = { "SaveService.save" = 0 }\n')
            with self.assertRaises(ConfigError) as caught:
                run_check(unit_disk)
        self.assertIn('at least 1', str(caught.exception))

    def test_a_non_integer_floor_is_refused(self) -> None:
        with temp_repo('unit_disk_repo', only=PLANTED) as root:
            _config(root, '[unit_disk]\nmin_args = { "SaveService.save" = "2" }\n')
            with self.assertRaises(ConfigError):
                run_check(unit_disk)

    def test_a_broken_regex_is_exit_two_not_a_traceback(self) -> None:
        with temp_repo('unit_disk_repo', only=PLANTED) as root:
            _config(root, '[unit_disk]\nforbidden_calls = { "bad" = ["Save((" ] }\n')
            with self.assertRaises(ConfigError) as caught:
                run_check(unit_disk)
        self.assertIn('not a valid regex', str(caught.exception))

    def test_a_root_holding_no_tests_fails_loudly(self) -> None:
        with temp_repo('unit_disk_repo', only=CLEAN) as root:
            _config(root, '[unit_disk]\nroots = ["tests/nowhere"]\n')
            code, out = run_check(unit_disk)
        self.assertEqual(code, 1, out)
        self.assertIn('[unit_disk] roots', out)


if __name__ == '__main__':
    unittest.main()
