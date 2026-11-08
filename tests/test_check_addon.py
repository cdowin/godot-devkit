"""`check addon`: the rules a shared add-on keeps, each failing before and passing after."""
import shutil
import subprocess
import unittest

from support import FIXTURES, run_check, temp_repo

from godot_devkit.core.config import ConfigError
from godot_devkit.godot.checks import addon
from godot_devkit.godot.index.uid_codec import canonical

PANEL = 'addons/kit/panel.gd'
THEME = '[addon]\ntheme_keys_class = "KitThemeKeys"\n'

# rule id -> (a line that breaks it, the same line fixed)
CASES = {
    'root-add-child': ('\tget_tree().root.add_child(node)',
                       '\tadd_child(node)'),
    'tree-meta': ('\tEngine.get_main_loop().set_meta("kit", self)',
                  '\tset_meta("kit", self)'),
    'runtime-input-audio': ('\tInputMap.add_action("kit_ok")',
                            '\tvar ok := InputMap.has_action("kit_ok")'),
    'theme-key-literal': ('\tadd_theme_color_override("font_color", Color.RED)',
                          '\tadd_theme_color_override(KitThemeKeys.FONT_COLOR, Color.RED)'),
}


def _gate(edit=None, config=None):
    """Run the gate over a scratch copy of the add-on fixture; `edit(root)`
    shapes the tree first."""
    with temp_repo('addon_repo') as root:
        if config is not None:
            (root / 'godot-devkit.toml').write_text(config, encoding='utf-8')
        if edit is not None:
            edit(root)
        subprocess.run(['git', 'add', '-A'], cwd=root, check=True)
        return run_check(addon)


def _append(line):
    def edit(root):
        with (root / PANEL).open('a', encoding='utf-8') as handle:
            handle.write(line + '\n')
    return edit


class CodeRules(unittest.TestCase):
    def test_the_clean_add_on_passes_and_says_what_it_scanned(self) -> None:
        code, out = _gate(config=THEME)
        self.assertEqual(code, 0, out)
        self.assertIn('[check:addon] PASS — 5 rule(s) across 2 .gd and 1 .tscn/.tres', out)
        self.assertIn('[check:addon] root-add-child — 2 .gd scanned, 0 hit(s)', out)

    def test_each_rule_fails_before_and_passes_after(self) -> None:
        for rule, (bad, good) in CASES.items():
            with self.subTest(rule=rule):
                code, out = _gate(_append(bad), THEME)
                self.assertEqual(code, 1, out)
                self.assertIn(f'{PANEL}:8: {rule}: ', out)
                code, out = _gate(_append(good), THEME)
                self.assertEqual(code, 0, out)

    def test_an_opt_out_needs_the_rule_and_a_reason(self) -> None:
        bad = CASES['root-add-child'][0]
        code, out = _gate(_append(bad + '  # lint-allow: root-add-child -- the console outlives scenes'))
        self.assertEqual(code, 0, out)
        self.assertIn('0 hit(s), 1 opt-out(s) with a reason', out)
        code, out = _gate(_append(bad + '  # lint-allow: root-add-child'))
        self.assertEqual(code, 1, out)
        self.assertIn('the opt-out needs a reason', out)
        code, out = _gate(_append(bad + '  # lint-allow: tree-meta -- wrong rule'))
        self.assertEqual(code, 1, out)

    def test_the_spellings_each_rule_catches(self) -> None:
        rules = [addon.ROOT_ADD_CHILD, addon.TREE_META, addon.RUNTIME_INPUT_AUDIO,
                 addon.CodeRule('theme-key-literal', addon.THEME_KEY_RE, 'm')]
        hits = {
            'get_tree().get_root().add_child(n)': 'root-add-child',
            'get_tree().root.add_child.call_deferred(n)': 'root-add-child',
            'get_tree().root.call_deferred(&"add_child", n)': 'root-add-child',
            'get_tree().set_meta("k", 1)': 'tree-meta',
            'AudioServer.add_bus()': 'runtime-input-audio',
            'theme_type_variation = &"KitPanel"': 'theme-key-literal',
            'get_theme_color("font_color")': 'theme-key-literal',
        }
        misses = ('# get_tree().root.add_child(n)', 'var s := "#" # get_tree().set_meta(1)',
                  'add_child(n)', 'get_theme_color(KitThemeKeys.FONT_COLOR)')
        for line, rule in hits.items():
            found, _ = addon.scan_code(line, 'a.gd', rules)
            self.assertEqual([rule], [f.split(': ')[1] for f in found], line)
        for line in misses:
            self.assertEqual(([], 0), addon.scan_code(line, 'a.gd', rules), line)

    def test_theme_rule_is_off_unless_a_declared_class_is_named(self) -> None:
        code, out = _gate(_append(CASES['theme-key-literal'][0]))
        self.assertEqual(code, 0, out)
        self.assertIn('theme-key-literal — off', out)
        with self.assertRaises(ConfigError):
            _gate(config='[addon]\ntheme_keys_class = "NoSuchKeys"\n')

    def test_a_scope_with_no_gd_fails(self) -> None:
        code, out = _gate(config='[addon]\npaths = ["addons/none/**"]\n')
        self.assertEqual(code, 1, out)
        self.assertIn('scanned 0 .gd', out)
        with self.assertRaises(ConfigError):
            _gate(config='[addon]\npaths = "addons/**"\n')


def _drop(root):
    (root / 'addons/kit/panel.gd.uid').unlink()
    scene = root / 'addons/kit/panel.tscn'
    scene.write_text(scene.read_text().replace(' uid="uid://dkitpanelscn1"', '', 1))


class UidMinting(unittest.TestCase):
    def test_missing_uids_fail_and_fix_mints_them_once(self) -> None:
        code, out = _gate(_drop)
        self.assertEqual(code, 1, out)
        self.assertIn(f'{PANEL}: uid-missing: no {PANEL}.uid sidecar', out)
        self.assertIn('addons/kit/panel.tscn: uid-missing: its header has no uid', out)

        def drop_fix_twice(root):
            _drop(root)
            subprocess.run(['git', 'add', '-A'], cwd=root, check=True)
            code, out = run_check(addon, fix=True)
            self.assertEqual(code, 0, out)
            self.assertIn('FIX — minted 2 uid(s)', out)
            sidecar = (root / f'{PANEL}.uid').read_text()
            self.assertEqual(canonical(sidecar.strip()), sidecar.strip())
            self.assertTrue(sidecar.endswith('\n'))
            first = (root / 'addons/kit/panel.tscn').read_text().split('\n')[0]
            self.assertRegex(first, r'^\[gd_scene format=3 uid="uid://[a-y0-8]+"\]$')
            before = {p: p.read_bytes() for p in root.rglob('*') if p.is_file()}
            code, out = run_check(addon, fix=True)
            self.assertIn('FIX — nothing to mint', out)
            self.assertEqual(before, {p: p.read_bytes() for p in root.rglob('*') if p.is_file()})
        _gate(drop_fix_twice)

    def test_a_header_it_cannot_prove_is_refused_and_nothing_is_written(self) -> None:
        def old_format(root):
            _drop(root)
            scene = root / 'addons/kit/panel.tscn'
            scene.write_text(scene.read_text().replace('format=3', 'format=2'))
        captured = {}

        def run(root):
            old_format(root)
            subprocess.run(['git', 'add', '-A'], cwd=root, check=True)
            captured['scene'] = (root / 'addons/kit/panel.tscn').read_bytes()
            captured['code'], captured['out'] = run_check(addon, fix=True)
            captured['after'] = (root / 'addons/kit/panel.tscn').read_bytes()
        _gate(run)
        self.assertEqual(captured['code'], 1, captured['out'])
        self.assertIn('REFUSED — its header has no format=3', captured['out'])
        self.assertEqual(captured['scene'], captured['after'])

    def test_an_exemption_needs_a_reason_and_a_file(self) -> None:
        exempt = '[addon]\nuid_exempt = { "addons/kit/panel.gd" = "%s" }\n'
        code, out = _gate(lambda r: (r / f'{PANEL}.uid').unlink(), exempt % 'built later')
        self.assertEqual(code, 0, out)
        self.assertIn('1 exempt with a reason', out)
        with self.assertRaises(ConfigError):
            _gate(config=exempt % ' ')
        code, out = _gate(config=exempt.replace('panel.gd', 'gone.gd') % 'x')
        self.assertEqual(code, 1, out)
        self.assertIn('STALE', out)

    def test_minting_a_header_changes_only_its_line_on_a_real_editor_file(self) -> None:
        source = FIXTURES / 'corpus/editor_written/default_bus_layout.tres'

        def run(root):
            shutil.copy2(source, root / 'addons/kit/default_bus_layout.tres')
            subprocess.run(['git', 'add', '-A'], cwd=root, check=True)
            code, out = run_check(addon, fix=True)
            self.assertEqual(code, 0, out)
            old = source.read_bytes().split(b'\n')
            new = (root / 'addons/kit/default_bus_layout.tres').read_bytes().split(b'\n')
            self.assertEqual(old[1:], new[1:])
            self.assertRegex(new[0].decode(), r'^\[gd_resource type="AudioBusLayout" '
                                              r'format=3 uid="uid://[a-y0-8]+"\]$')
        _gate(run)


if __name__ == '__main__':
    unittest.main()
