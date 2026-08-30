"""refs / orphans / autoloads — config-through-core + refusal-not-traceback.

Two contracts, one per class of defect the 2026-08-30 audit found:

  * every config value goes through `core/config.py`'s guards, so a bad
    `devkit.toml` value is ALWAYS exit 2 — never a traceback (the import-time
    read in autoloads.py), never silently ignored (the unwired `[refs]` /
    `[orphans]` sections), and never a bare string iterated characterwise;
  * an unusable tree (no `project.godot`, no git repo) is a REFUSAL with a
    reason, exit 2, never a stack trace.

Exit-code assertions run the real CLI in a subprocess: the import-time defect
class is only reproducible across a process boundary, and the subprocess also
proves no traceback reaches the consumer.
"""
from __future__ import annotations

import contextlib
import io
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from support import FIXTURES, REPO_ROOT, temp_repo

from godot_devkit.godot.read import autoloads, orphans, refs


def run_main(module, argv=()) -> tuple[int, str, str]:
    """One read verb's `main()` in-process against the cwd repo."""
    from godot_devkit.core.project import load_config, repo_root
    repo_root.cache_clear()
    load_config.cache_clear()
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = module.main(list(argv))
    repo_root.cache_clear()
    load_config.cache_clear()
    return code, out.getvalue(), err.getvalue()


def run_cli(root: Path, *argv: str) -> tuple[int, str, str]:
    """The real CLI in a subprocess — the only honest probe for an
    import-time crash, and it proves what a consumer's terminal sees."""
    proc = subprocess.run(
        [sys.executable, '-m', 'godot_devkit.cli', *argv],
        cwd=root, capture_output=True, text=True,
        env={**os.environ, 'PYTHONPATH': str(REPO_ROOT / 'src')})
    return proc.returncode, proc.stdout, proc.stderr


def _toml(root: Path, text: str) -> None:
    (root / 'devkit.toml').write_text(text, encoding='utf-8')


def _quoted(values) -> str:
    return ', '.join('"{}"'.format(v) for v in values)


class AutoloadsCensus(unittest.TestCase):
    def test_census_groups_by_suffix_and_flags_layout(self) -> None:
        with temp_repo('read_repo'):
            code, out, _ = run_main(autoloads)
        self.assertEqual(code, 0, out)
        self.assertIn('# autoload census (2)', out)
        self.assertIn('GameManager  autoloads/core/game_manager.gd  <emits>', out)
        self.assertIn('DataRegistry', out)
        self.assertIn('non-standard location', out)

    def test_no_config_equals_declaring_the_defaults(self) -> None:
        """Rule 5: a repo with NO devkit.toml behaves byte-identically to one
        declaring the stock defaults."""
        with temp_repo('read_repo') as root:
            _, stock, _ = run_main(autoloads)
            prefixes = _quoted(autoloads.DEFAULT_EXPECTED_PREFIXES)
            suffixes = ', '.join(f'{k} = [{_quoted(v)}]'
                                 for k, v in autoloads.DEFAULT_SUFFIXES.items())
            _toml(root, f'[autoloads]\nexpected_prefixes = [{prefixes}]\n'
                        f'suffixes = {{ {suffixes} }}\n')
            _, declared, _ = run_main(autoloads)
        self.assertEqual(stock, declared)

    def test_a_scalar_suffix_value_is_honored_whole(self) -> None:
        """`suffixes = { Manager = "emits" }` is the form both live consumers
        declare — a scalar means ONE bucket name, never its characters."""
        with temp_repo('read_repo') as root:
            _toml(root, '[autoloads]\nsuffixes = { Manager = "inert" }\n')
            code, out, _ = run_main(autoloads)
        self.assertEqual(code, 0, out)
        self.assertIn('Manager suffix expects inert, source looks emits', out)

    def test_a_bare_string_expected_prefixes_is_exit_2(self) -> None:
        """Pre-fix this was `tuple(str)` — a tuple of characters that made
        `startswith` match almost anything and silently suppressed every
        layout flag."""
        with temp_repo('read_repo') as root:
            _toml(root, '[autoloads]\nexpected_prefixes = "autoloads/"\n')
            code, _, err = run_cli(root, 'autoloads')
        self.assertEqual(code, 2, err)
        self.assertIn('must be a list of strings', err)
        self.assertNotIn('Traceback', err)

    def test_a_non_string_suffix_value_is_exit_2(self) -> None:
        with temp_repo('read_repo') as root:
            _toml(root, '[autoloads]\nsuffixes = { Manager = 5 }\n')
            code, _, err = run_cli(root, 'autoloads')
        self.assertEqual(code, 2, err)
        self.assertIn('suffixes.Manager', err)
        self.assertNotIn('Traceback', err)

    def test_an_unknown_bucket_name_is_exit_2(self) -> None:
        with temp_repo('read_repo') as root:
            _toml(root, '[autoloads]\nsuffixes = { Manager = "emit" }\n')
            code, _, err = run_cli(root, 'autoloads')
        self.assertEqual(code, 2, err)
        self.assertIn('unknown bucket', err)

    def test_a_bad_section_is_exit_2_not_an_import_crash(self) -> None:
        """The config used to be read at module import, outside every
        ConfigError handler — a bad `[autoloads]` value stack-traced while
        cli.py was still importing."""
        with temp_repo('read_repo') as root:
            _toml(root, 'autoloads = 5\n')
            code, _, err = run_cli(root, 'autoloads')
        self.assertEqual(code, 2, err)
        self.assertIn('must be a table', err)
        self.assertNotIn('Traceback', err)

    def test_missing_project_godot_is_a_refusal_not_a_traceback(self) -> None:
        with temp_repo('read_repo', only=['systems/player.gd']) as root:
            code, _, err = run_cli(root, 'autoloads')
        self.assertEqual(code, 2, err)
        self.assertIn('project.godot', err)
        self.assertNotIn('Traceback', err)


class RefsScope(unittest.TestCase):
    def test_finds_the_symbol_grouped_by_kind(self) -> None:
        with temp_repo('read_repo'):
            code, out, _ = run_main(refs, ['Player'])
        self.assertEqual(code, 0, out)
        self.assertIn('systems/player.gd', out)          # definition
        self.assertIn('systems/spawner.gd', out)         # typed ref
        self.assertIn('scenes/main.tscn', out)           # scene resource ref

    def test_exclude_prefixes_scopes_the_scan(self) -> None:
        """Pre-fix `[refs]` did not exist: the exclusion list was a hardcoded
        constant and the declared key was silently ignored."""
        with temp_repo('read_repo') as root:
            _toml(root, '[refs]\nexclude_prefixes = '
                        '[".git/", ".godot/", "systems/"]\n')
            code, out, _ = run_main(refs, ['Player'])
        self.assertEqual(code, 0, out)
        # The excluded dir's files are out of the scan: no definition from
        # player.gd, no typed ref from spawner.gd. (The surviving scene-ref
        # LINE still names the res:// path it points at — that is the hit's
        # text, not a scanned file.)
        self.assertNotIn('## definitions', out)
        self.assertNotIn('## typed refs', out)
        self.assertNotIn('spawner.gd', out)
        self.assertIn('scenes/main.tscn', out)

    def test_no_config_equals_declaring_the_defaults(self) -> None:
        with temp_repo('read_repo') as root:
            _, stock, _ = run_main(refs, ['Player'])
            _toml(root, f'[refs]\nexclude_prefixes = [{_quoted(refs.DEFAULT_EXCLUDE)}]\n')
            _, declared, _ = run_main(refs, ['Player'])
        self.assertEqual(stock, declared)

    def test_a_bare_string_exclude_is_exit_2(self) -> None:
        with temp_repo('read_repo') as root:
            _toml(root, '[refs]\nexclude_prefixes = "systems/"\n')
            code, _, err = run_cli(root, 'refs', 'Player')
        self.assertEqual(code, 2, err)
        self.assertIn('must be a list of strings', err)
        self.assertNotIn('Traceback', err)


class OrphansScope(unittest.TestCase):
    def test_reports_the_unreferenced_files(self) -> None:
        with temp_repo('read_repo'):
            code, out, _ = run_main(orphans)
        self.assertEqual(code, 0, out)
        self.assertIn('systems/unused.gd', out)
        self.assertIn('systems/spawner.gd', out)
        self.assertNotIn('player.gd', out)               # referenced by main.tscn

    def test_auto_discovered_prefixes_scopes_candidates(self) -> None:
        """Pre-fix `[orphans]` did not exist — the dir roster was hardcoded."""
        with temp_repo('read_repo') as root:
            _toml(root, '[orphans]\nauto_discovered_prefixes = ["systems/"]\n')
            code, out, _ = run_main(orphans)
        self.assertEqual(code, 0, out)
        self.assertIn('(none found)', out)

    def test_entry_point_prefixes_hold_even_under_dash_dash_tests(self) -> None:
        """`--tests` re-includes the auto-discovered dirs, never the
        entry-point ones — the two keys must stay distinct."""
        with temp_repo('read_repo') as root:
            _toml(root, '[orphans]\nentry_point_prefixes = ["systems/"]\n')
            code, out, _ = run_main(orphans, ['--tests'])
        self.assertEqual(code, 0, out)
        self.assertIn('(none found)', out)

    def test_convention_files_are_never_candidates(self) -> None:
        with temp_repo('read_repo') as root:
            _toml(root, '[orphans]\nconvention_files = ["systems/unused.gd"]\n')
            code, out, _ = run_main(orphans)
        self.assertEqual(code, 0, out)
        self.assertNotIn('unused.gd', out)
        self.assertIn('systems/spawner.gd', out)

    def test_no_config_equals_declaring_the_defaults(self) -> None:
        with temp_repo('read_repo') as root:
            _, stock, _ = run_main(orphans)
            _toml(root, '[orphans]\n'
                        f'vendored_prefixes = [{_quoted(orphans.DEFAULT_VENDORED)}]\n'
                        f'entry_point_prefixes = [{_quoted(orphans.DEFAULT_ENTRY_POINT_PREFIXES)}]\n'
                        f'auto_discovered_prefixes = [{_quoted(orphans.DEFAULT_AUTO_DISCOVERED)}]\n'
                        f'convention_files = [{_quoted(orphans.DEFAULT_CONVENTION_FILES)}]\n')
            _, declared, _ = run_main(orphans)
        self.assertEqual(stock, declared)

    def test_a_bare_string_vendored_prefixes_is_exit_2(self) -> None:
        with temp_repo('read_repo') as root:
            _toml(root, '[orphans]\nvendored_prefixes = "addons/"\n')
            code, _, err = run_cli(root, 'orphans')
        self.assertEqual(code, 2, err)
        self.assertIn('must be a list of strings', err)
        self.assertNotIn('Traceback', err)

    def test_missing_project_godot_is_a_refusal_not_a_traceback(self) -> None:
        with temp_repo('read_repo', only=['systems/unused.gd']) as root:
            code, _, err = run_cli(root, 'orphans')
        self.assertEqual(code, 2, err)
        self.assertIn('project.godot', err)
        self.assertNotIn('Traceback', err)

    def test_outside_a_git_repo_is_a_refusal_not_a_traceback(self) -> None:
        """An empty census here would read as "no orphans" — the reverse of
        the truth — so a failed `git ls-files` must refuse, not crash and
        not report clean."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'not_a_repo'
            root.mkdir()
            (root / 'project.godot').write_text(
                (FIXTURES / 'read_repo' / 'project.godot').read_text(encoding='utf-8'),
                encoding='utf-8')
            code, _, err = run_cli(root, 'orphans')
        self.assertEqual(code, 2, err)
        self.assertIn('git', err)
        self.assertNotIn('Traceback', err)


if __name__ == '__main__':
    unittest.main()
