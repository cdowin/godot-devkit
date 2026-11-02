"""`check ui-layout`: the three finding kinds, the census, the baseline, the config."""
import contextlib
import io
import subprocess
import unittest

from support import run_check, temp_repo

from godot_devkit import cli
from godot_devkit.godot.checks import roster, ui_layout

GOOD = ['project.godot', 'scenes/good_modal.tscn', 'scenes/action_bar.tscn',
        'scenes/inherited_modal.tscn']
CYCLE = ['scenes/cycle_a.tscn', 'scenes/cycle_b.tscn']
CONFIG = '''[ui_layout]
action_bar_types = ["ActionBar"]
modal_types = ["Modal"]
panel_types = ["Panel"]
role_property = "ui_role"
action_roles = ["primary", "destructive", "cancel"]
'''


def _gate(scenes, extra='', config=CONFIG):
    with temp_repo('ui_layout_repo', only=scenes) as root:
        if config is not None:
            (root / 'godot-devkit.toml').write_text(config + extra, encoding='utf-8')
        subprocess.run(['git', 'add', '-A'], cwd=root, check=True)
        return run_check(ui_layout)


def _cli(config):
    with temp_repo('ui_layout_repo', only=GOOD) as root:
        (root / 'godot-devkit.toml').write_text(config, encoding='utf-8')
        subprocess.run(['git', 'add', '-A'], cwd=root, check=True)
        from godot_devkit.core.project import load_config, repo_root
        repo_root.cache_clear()
        load_config.cache_clear()
        with contextlib.redirect_stdout(io.StringIO()), \
                contextlib.redirect_stderr(io.StringIO()):
            code = cli.main(['check', 'ui-layout'])
        repo_root.cache_clear()
        load_config.cache_clear()
        return code


class UiLayout(unittest.TestCase):
    def test_good_scenes_pass_and_cycles_are_unverified_not_crashes(self) -> None:
        code, out = _gate(GOOD + CYCLE)
        self.assertEqual(code, 0, out)
        self.assertIn('missing or cyclic', out)

    def test_each_bad_scene_reports_its_kind(self) -> None:
        for scene, kind in (('bad_action', 'action-outside-bar'),
                            ('bad_button_in_scroll', 'button-in-modal-scroll'),
                            ('bad_label', 'label-no-overflow')):
            code, out = _gate(GOOD + [f'scenes/{scene}.tscn'])
            self.assertEqual(code, 1, out)
            self.assertIn(f'  {kind}  scenes/{scene}.tscn : ', out)
            other = {'action-outside-bar', 'button-in-modal-scroll',
                     'label-no-overflow'} - {kind}
            self.assertFalse(any(f'  {o}  ' in out for o in other), out)

    def test_instanced_bar_covers_and_instanced_non_bar_is_judged(self) -> None:
        # inherited_modal.tscn adds a primary Button under the instanced Bar.
        code, out = _gate(GOOD)
        self.assertEqual(code, 0, out)
        with temp_repo('ui_layout_repo', only=GOOD) as root:
            (root / 'godot-devkit.toml').write_text(
                CONFIG.replace('["ActionBar"]', '["Elsewhere"]'), encoding='utf-8')
            subprocess.run(['git', 'add', '-A'], cwd=root, check=True)
            code, out = run_check(ui_layout)
        self.assertEqual(code, 1, out)
        self.assertIn('scenes/good_modal.tscn : Bar/Primary', out)

    def test_baseline_holds_then_ratchets(self) -> None:
        scenes = GOOD + ['scenes/bad_action.tscn']
        key = '"scenes/bad_action.tscn"'
        code, out = _gate(scenes, f'baseline = {{ {key} = 2 }}\n')
        self.assertEqual(code, 0, out)
        self.assertIn('BASELINED  2 finding(s) in 1 file(s)', out)
        code, out = _gate(scenes, f'baseline = {{ {key} = 1 }}\n')
        self.assertEqual(code, 1, out)
        self.assertIn('GREW', out)
        code, out = _gate(scenes, f'baseline = {{ {key} = 3 }}\n')
        self.assertEqual(code, 1, out)
        self.assertIn('SHRUNK', out)

    def test_zero_file_and_zero_match_census_fail(self) -> None:
        code, out = _gate(GOOD, 'include_prefixes = ["nowhere/"]\n')
        self.assertEqual(code, 1, out)
        self.assertIn('scanned 0 files', out)
        code, out = _gate(GOOD, config=CONFIG.replace('["Modal"]', '["Nope"]')
                          .replace('["ActionBar"]', '["Nope"]')
                          .replace('["Panel"]', '["Nope"]'))
        self.assertEqual(code, 1, out)
        self.assertIn('no node matched', out)

    def test_bad_config_exits_2(self) -> None:
        self.assertEqual(_cli(CONFIG.replace('["primary", "destructive", "cancel"]',
                                             '"primary"')), 2)
        self.assertEqual(_cli(CONFIG.replace('modal_types = ["Modal"]\n', '')), 2)

    def test_unconfigured_passes_and_is_not_in_check_all(self) -> None:
        code, out = _gate(GOOD, config=None)
        self.assertEqual(code, 0, out)
        self.assertIn('no [ui_layout] declared', out)
        with temp_repo('ui_layout_repo', only=['project.godot']):
            self.assertNotIn('ui-layout', roster.all_roster())
        self.assertIn('ui-layout', roster.OPT_IN_GATES)


if __name__ == '__main__':
    unittest.main()
