"""refs / orphans / autoloads — config-through-core + refusal-not-traceback.

Two contracts, one per class of defect the 2026-08-30 audit found:

  * every config value goes through `core/config.py`'s guards, so a bad
    `devkit.toml` value is ALWAYS exit 2 — never a traceback (the import-time
    read in autoloads.py), never silently ignored (the unwired `[refs]` /
    `[orphans]` sections), and never a bare string iterated characterwise;
  * an unusable tree (no `project.godot`, no git repo) is a REFUSAL with a
    reason, exit 2, never a stack trace.

Two cases run the real CLI in a subprocess: the import-time defect class is
only reproducible across a process boundary, and a tree outside any git repo
is not a `temp_repo`. Everything else is the verb's `main()` in-process.
"""
import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from support import FIXTURES, REPO_ROOT, temp_repo

from godot_devkit.core.project import load_config, repo_root
from godot_devkit.godot import VENDORED_DEFAULT
from godot_devkit.godot.read import autoloads, orphans, refs


def run_main(module, argv=()):
    # One read verb's `main()` in-process against the cwd repo, the module
    # caches cleared on both sides of it.
    out, err = io.StringIO(), io.StringIO()
    for cache in (repo_root, load_config):
        cache.cache_clear()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = module.main(list(argv))
    for cache in (repo_root, load_config):
        cache.cache_clear()
    return code, out.getvalue(), err.getvalue()


def run_in(module, argv=(), toml=None, only=None):
    """`run_main` in a throwaway repo, under `toml` if given."""
    with temp_repo('read_repo', only=only) as root:
        if toml:
            (root / 'devkit.toml').write_text(toml, encoding='utf-8')
        return run_main(module, argv)


def run_cli(root, *argv):
    # The real CLI in a subprocess — the only honest probe for an import-time
    # crash, and it proves what a consumer's terminal sees.
    return subprocess.run(
        [sys.executable, '-m', 'godot_devkit.cli', *argv],
        cwd=root, capture_output=True, text=True,
        env={**os.environ, 'PYTHONPATH': str(REPO_ROOT / 'src')})


# Every `[section]` a read verb reads, declared as its stock defaults. (A
# JSON array of strings is a TOML array of strings.)
DECLARED_DEFAULTS = (
    (autoloads, (),
     f'[autoloads]\nexpected_prefixes = {json.dumps(list(autoloads.DEFAULT_EXPECTED_PREFIXES))}\n'
     'suffixes = { '
     + ', '.join(f'{k} = {json.dumps(list(v))}' for k, v in autoloads.DEFAULT_SUFFIXES.items())
     + ' }\n'),
    (refs, ('Player',),
     f'[refs]\nexclude_prefixes = {json.dumps(list(refs.DEFAULT_EXCLUDE))}\n'),
    (orphans, (),
     '[orphans]\n'
     f'vendored_prefixes = {json.dumps(list(VENDORED_DEFAULT))}\n'
     f'entry_point_prefixes = {json.dumps(list(orphans.DEFAULT_ENTRY_POINT_PREFIXES))}\n'
     f'auto_discovered_prefixes = {json.dumps(list(orphans.DEFAULT_AUTO_DISCOVERED))}\n'
     f'convention_files = {json.dumps(list(orphans.DEFAULT_CONVENTION_FILES))}\n'),
)

# One row per verb and config reader: a bare string is REFUSED, never
# iterated characterwise (pre-fix `tuple(str)` made `startswith` match almost
# anything and silently suppressed every layout flag); a non-string bucket
# and an unknown bucket name are refused by name.
BAD_CONFIG = (
    (autoloads, (), '[autoloads]\nexpected_prefixes = "autoloads/"\n',
     'must be a list of strings'),
    (autoloads, (), '[autoloads]\nsuffixes = { Manager = 5 }\n', 'suffixes.Manager'),
    (autoloads, (), '[autoloads]\nsuffixes = { Manager = "emit" }\n', 'unknown bucket'),
    (refs, ('Player',), '[refs]\nexclude_prefixes = "systems/"\n',
     'must be a list of strings'),
    (orphans, (), '[orphans]\nvendored_prefixes = "addons/"\n',
     'must be a list of strings'),
)


class ConfigThroughCore(unittest.TestCase):
    def test_no_config_equals_declaring_the_defaults(self) -> None:
        # Rule 5: a repo with NO devkit.toml behaves byte-identically to one
        # declaring the stock defaults — for every verb that reads a section.
        for module, argv, declared_toml in DECLARED_DEFAULTS:
            self.assertEqual(run_in(module, argv)[1],
                             run_in(module, argv, declared_toml)[1], module.__name__)

    def test_a_bad_config_value_is_exit_2_with_a_reason(self) -> None:
        for module, argv, toml, reason in BAD_CONFIG:
            code, _, err = run_in(module, argv, toml)
            self.assertEqual(code, 2, (toml, err))
            self.assertIn(reason, err, toml)

    def test_a_bad_section_is_exit_2_not_an_import_crash(self) -> None:
        # The config used to be read at module import, outside every
        # ConfigError handler — a bad `[autoloads]` value stack-traced while
        # cli.py was still importing.
        with temp_repo('read_repo') as root:
            (root / 'devkit.toml').write_text('autoloads = 5\n', encoding='utf-8')
            done = run_cli(root, 'autoloads')
        self.assertEqual(done.returncode, 2, done.stderr)
        self.assertIn('must be a table', done.stderr)
        self.assertNotIn('Traceback', done.stderr)


class AutoloadsCensus(unittest.TestCase):
    def test_census_groups_by_suffix_and_flags_layout(self) -> None:
        code, out, _ = run_in(autoloads)
        self.assertEqual(code, 0, out)
        for phrase in ('# autoload census (2)',
                       'GameManager  autoloads/core/game_manager.gd  <emits>',
                       'DataRegistry', 'non-standard location'):
            self.assertIn(phrase, out)

    def test_missing_project_godot_is_a_refusal_not_a_traceback(self) -> None:
        code, _, err = run_in(autoloads, only=['systems/player.gd'])
        self.assertEqual(code, 2, err)
        self.assertIn('project.godot', err)
        self.assertNotIn('Traceback', err)


class RefsScope(unittest.TestCase):
    # One script holding every call-site grammar class: a receiverless
    # same-file call (COUNTS — every alternative required a leading `.`, so a
    # method called only from its own script reported ZERO references, the
    # answer that gets a method deleted); a commented-out call (does not); a
    # signal declaration with arguments (a definition, not a call); a longer
    # name ending in the symbol (another name); and the defining line itself
    # (`func name(` IS `name(` — counted once, as a definition).
    GRAMMAR = (
        'extends Node\n'
        '\n'
        'signal shard_taken(id: int)\n'
        '\n'
        '\n'
        'func resync_active_variant() -> void:\n'
        '\tpass\n'
        '\n'
        '\n'
        'func lonesome() -> void:\n'
        '\tpass\n'
        '\n'
        '\n'
        'func _ready() -> void:\n'
        '\tresync_active_variant()\n'
        '\t# lonesome()\n'
        '\tshard_taken.emit(1)\n'
        '\t_on_hurt()\n'
        '\trehurt()\n'
        '\n'
        '\n'
        'func on_gear_changed() -> void:\n'
        '\tresync_active_variant()\n'
    )
    # (symbol, lines its report carries, lines it must not)
    EXPECTED = (
        ('resync_active_variant', ('## definitions (1)', '## call / emit sites (2)'), ()),
        ('lonesome', ('## definitions (1)',), ('## call / emit sites',)),
        ('shard_taken', ('## definitions (1)', '## call / emit sites (1)'), ()),
        ('hurt', (), ('grammar.gd',)),
    )

    def test_finds_the_symbol_grouped_by_kind(self) -> None:
        code, out, _ = run_in(refs, ['Player'])
        self.assertEqual(code, 0, out)
        self.assertIn('systems/player.gd', out)          # definition
        self.assertIn('systems/spawner.gd', out)         # typed ref
        self.assertIn('scenes/main.tscn', out)           # scene resource ref

    def test_exclude_prefixes_scopes_the_scan(self) -> None:
        # Pre-fix `[refs]` did not exist: the exclusion list was a hardcoded
        # constant and the declared key was silently ignored.
        code, out, _ = run_in(refs, ['Player'],
                              '[refs]\nexclude_prefixes = [".git/", ".godot/", "systems/"]\n')
        self.assertEqual(code, 0, out)
        # The excluded dir's files are out of the scan: no definition from
        # player.gd, no typed ref from spawner.gd. (The surviving scene-ref
        # LINE still names the res:// path it points at — that is the hit's
        # text, not a scanned file.)
        for gone in ('## definitions', '## typed refs', 'spawner.gd'):
            self.assertNotIn(gone, out)
        self.assertIn('scenes/main.tscn', out)

    def test_the_call_site_grammar(self) -> None:
        with temp_repo('read_repo') as root:
            (root / 'systems/grammar.gd').write_text(self.GRAMMAR, encoding='utf-8')
            for symbol, present, absent in self.EXPECTED:
                code, out, _ = run_main(refs, [symbol])
                self.assertEqual(code, 0, out)
                for phrase in present:
                    self.assertIn(phrase, out)
                for phrase in absent:
                    self.assertNotIn(phrase, out)

    def test_an_empty_or_blank_symbol_is_exit_2_not_a_scan(self) -> None:
        # Every pattern is built around the symbol, so an empty one is a
        # match-anything: the bare-call arm alone claimed 880 call sites in a
        # consumer. There is no scan whose answer that could be.
        for blank in ('', ' ', '\t', '\n'):
            code, out, err = run_in(refs, [blank])
            self.assertEqual(code, 2, (repr(blank), out + err))
            self.assertIn('a symbol is required', err, repr(blank))
            self.assertNotIn('# refs:', out, repr(blank))


class OrphansScope(unittest.TestCase):
    # Pre-fix `[orphans]` did not exist — the dir roster was hardcoded. Each
    # scope key narrows the candidates on its own: `--tests` re-includes the
    # auto-discovered dirs, never the entry-point ones — the two keys must
    # stay distinct — and a convention file is never a candidate.
    SCOPE_KEYS = (
        ('[orphans]\nauto_discovered_prefixes = ["systems/"]\n', (), ('(none found)',), ()),
        ('[orphans]\nentry_point_prefixes = ["systems/"]\n', ('--tests',), ('(none found)',), ()),
        ('[orphans]\nconvention_files = ["systems/unused.gd"]\n', (),
         ('systems/spawner.gd',), ('unused.gd',)),
    )

    def test_reports_the_unreferenced_files(self) -> None:
        code, out, _ = run_in(orphans)
        self.assertEqual(code, 0, out)
        self.assertIn('systems/unused.gd', out)
        self.assertIn('systems/spawner.gd', out)
        self.assertNotIn('player.gd', out)               # referenced by main.tscn

    def test_each_scope_key_narrows_the_candidates(self) -> None:
        for toml, argv, present, absent in self.SCOPE_KEYS:
            code, out, _ = run_in(orphans, argv, toml)
            self.assertEqual(code, 0, out)
            for phrase in present:
                self.assertIn(phrase, out)
            for phrase in absent:
                self.assertNotIn(phrase, out)

    def test_missing_project_godot_is_a_refusal_not_a_traceback(self) -> None:
        code, _, err = run_in(orphans, only=['systems/unused.gd'])
        self.assertEqual(code, 2, err)
        self.assertIn('project.godot', err)
        self.assertNotIn('Traceback', err)

    def test_outside_a_git_repo_is_a_refusal_not_a_traceback(self) -> None:
        # An empty census here would read as "no orphans" — the reverse of the
        # truth — so a failed `git ls-files` must refuse, not crash and not
        # report clean.
        with tempfile.TemporaryDirectory() as not_a_repo:
            (Path(not_a_repo) / 'project.godot').write_bytes(
                (FIXTURES / 'read_repo' / 'project.godot').read_bytes())
            done = run_cli(not_a_repo, 'orphans')
        self.assertEqual(done.returncode, 2, done.stderr)
        self.assertIn('git', done.stderr)
        self.assertNotIn('Traceback', done.stderr)
