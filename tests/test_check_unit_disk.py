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
import subprocess
import unittest

from support import run_check, temp_repo

from godot_devkit.core.config import ConfigError
from godot_devkit.godot.checks import unit_disk

CLEAN = ['project.godot', 'tests/unit/clean.gd', 'tests/support/helper.gd']
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


def _gate(only, config=None):
    """One run of the gate in a throwaway repo holding `only`, under `config`."""
    with temp_repo('unit_disk_repo', only=only) as root:
        if config:
            (root / 'devkit.toml').write_text(config, encoding='utf-8')
        return run_check(unit_disk)


class TheStockGate(unittest.TestCase):
    # What it knows with no config at all: `user://` is a real path.

    def test_a_user_path_literal_is_a_finding(self) -> None:
        code, out = _gate([*CLEAN, 'tests/unit/planted_user_path.gd'])
        self.assertEqual(code, 1, out)
        self.assertIn('DISK-WRITE  tests/unit/planted_user_path.gd:4', out)
        self.assertIn('a real user:// path', out)

    def test_the_clean_test_passes_and_a_file_outside_the_roots_is_not_scanned(self) -> None:
        # The shared helper lives outside the scan root ON PURPOSE — it is the
        # thing tests are supposed to route through.
        code, out = _gate(CLEAN)
        self.assertEqual(code, 0, out)
        self.assertIn('[check:unit-disk] PASS — 1 test file(s)', out)
        self.assertNotIn('tests/support/helper.gd', out)


class TheConsumersFiveChecks(unittest.TestCase):
    def test_every_planted_violation_is_caught_and_names_the_arity_it_needed(self) -> None:
        code, out = _gate([*CLEAN, 'tests/unit/planted_user_path.gd', 'tests/unit/planted_slot.gd',
                           'tests/unit/planted_path_const.gd', 'tests/unit/planted_save.gd',
                           'tests/unit/planted_scan.gd', 'tests/unit/planted_settings.gd'],
                          CONSUMER)
        self.assertEqual(code, 1, out)
        for phrase in ('planted_user_path', 'planted_slot', 'planted_path_const',
                       'planted_save', 'planted_scan', 'planted_settings',
                       '6 violation(s)',
                       'SaveService.save given 1 argument(s), needs 2',
                       'SaveSlotIndex.scan given 0 argument(s), needs 1'):
            self.assertIn(phrase, out)

    def test_the_sanctioned_redirect_shape_and_an_unbalanced_call_are_spared(self) -> None:
        # An explicit throwaway root, a call named in an assert message, a doc
        # comment naming `user://`, and a lone STRING argument — none is a
        # finding. The last one is why quoted spans are masked rather than
        # deleted: `scan("res://throwaway")` is one argument, not zero. Nor
        # is a call whose parenthesis closes on a later line: declined, not
        # guessed at. (Staged, because the gate scans `git ls-files`.)
        with temp_repo('unit_disk_repo', only=CLEAN) as root:
            (root / 'tests/unit/wrapped.gd').write_text(
                'func _s(uuid: String) -> bool:\n\treturn SaveService.save(\n\t\tuuid)\n',
                encoding='utf-8')
            subprocess.run(['git', 'add', 'tests/unit/wrapped.gd'], cwd=root, check=True)
            (root / 'devkit.toml').write_text(CONSUMER, encoding='utf-8')
            code, out = run_check(unit_disk)
        self.assertEqual(code, 0, out)
        self.assertIn('2 test file(s)', out)


class RefusesRatherThanGuesses(unittest.TestCase):
    BAD_CONFIG = (
        ('[unit_disk]\nmin_args = { "SaveService.save" = 0 }\n', 'at least 1'),
        ('[unit_disk]\nmin_args = { "SaveService.save" = "2" }\n', 'must be an integer'),
        ('[unit_disk]\nforbidden_calls = { "bad" = ["Save((" ] }\n', 'not a valid regex'),
    )

    def test_a_bad_config_value_is_exit_two_not_a_traceback(self) -> None:
        for body, reason in self.BAD_CONFIG:
            with self.subTest(config=body), self.assertRaises(ConfigError) as caught:
                _gate(CLEAN, body)
            self.assertIn(reason, str(caught.exception))

    def test_a_root_holding_no_tests_fails_loudly(self) -> None:
        code, out = _gate(CLEAN, '[unit_disk]\nroots = ["tests/nowhere"]\n')
        self.assertEqual(code, 1, out)
        self.assertIn('[unit_disk] roots', out)
