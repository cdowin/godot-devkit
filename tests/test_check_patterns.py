"""`check patterns`: a project declares its own forbidden patterns."""
import subprocess
import unittest

from support import run_check, temp_repo

from godot_devkit.core.config import ConfigError
from godot_devkit.godot.checks import patterns

RULE = '''[[patterns.rule]]
id = "no-print"
regex = "\\\\bprint\\\\("
paths = ["src/**/*.gd"]
exclude = ["src/debug/**"]
message = "Use the logger."
'''


def _gate(files, config=None):
    with temp_repo('rng_repo', only=['project.godot']) as root:
        for rel, body in files.items():
            (root / rel).parent.mkdir(parents=True, exist_ok=True)
            (root / rel).write_text(body, encoding='utf-8')
        if config is not None:
            (root / 'godot-devkit.toml').write_text(config, encoding='utf-8')
        subprocess.run(['git', 'add', '-A'], cwd=root, check=True)
        return run_check(patterns)


class Patterns(unittest.TestCase):
    def test_a_hit_prints_path_line_id_message(self) -> None:
        code, out = _gate({'src/a.gd': 'var x\nprint("hi")\n'}, RULE)
        self.assertEqual(code, 1, out)
        self.assertIn('src/a.gd:2: no-print: Use the logger.', out)

    def test_a_miss_passes(self) -> None:
        code, out = _gate({'src/a.gd': 'var x\n'}, RULE)
        self.assertEqual(code, 0, out)

    def test_an_excluded_path_is_skipped(self) -> None:
        code, out = _gate({'src/a.gd': 'var x\n', 'src/debug/b.gd': 'print(1)\n'}, RULE)
        self.assertEqual(code, 0, out)

    def test_an_opt_out_comment_naming_the_id_silences_the_line(self) -> None:
        code, out = _gate({'src/a.gd': 'print(1)  # lint-allow: no-print\n'}, RULE)
        self.assertEqual(code, 0, out)
        code, out = _gate({'src/a.gd': 'print(1)  # lint-allow: other\n'}, RULE)
        self.assertEqual(code, 1, out)

    def test_no_rules_does_nothing(self) -> None:
        code, out = _gate({'src/a.gd': 'print(1)\n'})
        self.assertEqual(code, 0, out)

    def test_a_rule_matching_no_file_fails(self) -> None:
        code, out = _gate({'other/a.gd': 'x\n'}, RULE)
        self.assertEqual(code, 1, out)
        self.assertIn('EMPTY  no-print', out)

    def test_a_bad_regex_is_a_config_error(self) -> None:
        bad = RULE.replace('"\\\\bprint\\\\("', '"("')
        with self.assertRaises(ConfigError):
            _gate({'src/a.gd': 'x\n'}, bad)


if __name__ == '__main__':
    unittest.main()
