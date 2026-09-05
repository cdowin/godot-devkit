"""test_shell_mark.py — the `shell` census, and the refusals that keep it a fact.

`tests/conftest.py` decides, at collection, which modules spawn a process, and
S2's matrix skips them on three of four interpreters. That makes the derivation
load-bearing in a direction tests usually are not: a module that silently
leaves the marked side stops running on 3.12/3.13/3.14 and nothing goes red.
So the census is asserted here — the marked count, the unmarked modules by
name, and the support helpers the derivation reaches through.

Two failure modes, opposite in cost. Over-marking loses a module its skip and
costs seconds. UNDER-marking loses coverage silently, which is why three of
these tests attack the derivation rather than confirm it: prose that says
`subprocess.run` and spawns nothing, a helper imported from a spawning module
that spawns nothing itself, and any spelling of "start a process" the
derivation was never taught to read.

The scratch-tree tests run a real `pytest` against a copy of the conftest,
because the mark's whole job is to survive `-m shell` — and a refusal that has
never been raised is a message, not a gate.
"""
from __future__ import annotations

import ast
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import conftest
from support import REPO_ROOT

TESTS = REPO_ROOT / 'tests'
SUPPORT = TESTS / 'support'

# The census, as measured. `shell` is derived, so these are not a policy: they
# are what the modules under tests/ currently do, and a module that changes
# sides changes them. Marked is a COUNT — a peer adding a test to a spawning
# module must never have to touch this file. Unmarked is the roster, because
# the nine that do not spawn are the nine three interpreters still run, and
# each one is worth naming.
MARKED_MODULES = 36
UNMARKED_MODULES = (
    'test_apply.py',
    'test_boundaries.py',
    'test_consumer_independence.py',
    'test_fuzz_markdown.py',
    'test_scene_summary.py',
    'test_tiles.py',
    'test_tscn_roundtrip.py',
    'test_uid_codec.py',
    'test_verdict.py',
)

# The `tests/support` names whose use means a spawn. Five of the package's 23
# helpers: `temp_repo` and `tree` (`git init` a scratch repo), `git`, and
# `commit`/`porcelain`, which reach it through `git`. The other eighteen —
# `run_check`, `run_cli`, `run_gate`, the ledger line builders — run in
# process, which is exactly why the derivation reads the call graph instead of
# the module's import list.
SPAWNING_HELPERS = frozenset({'commit', 'git', 'porcelain', 'temp_repo', 'tree'})

# A broken SUPPORT path makes `support_spawn_names()` empty and silently
# unmarks a third of the suite, so the census asserts the package was found at
# all. A floor, not the exact 24: it is here to catch a moved root.
MIN_SUPPORT_HELPERS = 15

# Ways to start a process that the derivation does NOT read. Anything reached
# off the `subprocess` name is exempt — that import is the signal it DOES read.
# Every entry is a call name, so a docstring naming one is not an offence.
UNREAD_SPAWN_CALLS = frozenset({
    'system', 'popen', 'Popen', 'posix_spawn', 'posix_spawnp', 'fork', 'forkpty',
    'spawnl', 'spawnle', 'spawnlp', 'spawnv', 'spawnve', 'spawnvp',
    'execl', 'execle', 'execlp', 'execv', 'execve', 'execvp',
    'check_output', 'check_call', 'getoutput', 'getstatusoutput',
})

# A scratch suite covering the derivation's four answers, built under a copy of
# the real conftest. `quiet` is the sharp one: it comes out of a module that
# imports `subprocess`, and importing it is not a spawn.
SCRATCH_SUPPORT = '''\
import subprocess


def inner():
    subprocess.run(['true'], check=False)


def outer():
    inner()


def quiet():
    return 1
'''
SCRATCH_MODULES = {
    'test_pure.py': 'def test_pure():\n    assert True\n',
    'test_spawner.py': 'import subprocess\n\n\ndef test_spawner():\n    assert subprocess\n',
    'test_via_helper.py': 'from support import outer\n\n\ndef test_via_helper():\n    assert outer\n',
    'test_quiet_helper.py': 'from support import quiet\n\n\ndef test_quiet_helper():\n    assert quiet() == 1\n',
}
SCRATCH_SHELL = ('test_spawner.py', 'test_via_helper.py')
SCRATCH_NOT_SHELL = ('test_pure.py', 'test_quiet_helper.py')
SCRATCH_INI = '[pytest]\nmarkers =\n    shell: derived by conftest.py\n'


def _modules() -> list[Path]:
    return sorted(TESTS.glob('test_*.py'))


def _census() -> tuple[list[str], list[str]]:
    marked, unmarked = [], []
    for path in _modules():
        (marked if conftest.module_spawns(path) else unmarked).append(path.name)
    return marked, unmarked


class Census(unittest.TestCase):
    """What the derivation says about this repo, right now."""

    def test_the_module_census_is_what_the_matrix_will_skip(self):
        marked, unmarked = _census()
        self.assertEqual(tuple(unmarked), UNMARKED_MODULES,
                         'a module changed sides: it now spawns, or it stopped. '
                         'Update the census only after deciding which.')
        self.assertEqual(len(marked), MARKED_MODULES)
        self.assertEqual(len(marked) + len(unmarked), len(_modules()))

    def test_the_derivation_reaches_every_spawning_support_helper(self):
        self.assertEqual(conftest.support_spawn_names(), SPAWNING_HELPERS)

    def test_the_support_package_was_actually_found(self):
        helpers = [n for path in sorted(SUPPORT.glob('*.py'))
                   for n in ast.parse(path.read_text(encoding='utf-8')).body
                   if isinstance(n, ast.FunctionDef)]
        self.assertGreaterEqual(
            len(helpers), MIN_SUPPORT_HELPERS,
            f'{SUPPORT} yielded {len(helpers)} helpers — a moved or renamed '
            'support package empties the spawn set and unmarks the suite in '
            'silence.')

    def test_the_mark_is_declared_beside_fuzz(self):
        markers = (REPO_ROOT / 'pyproject.toml').read_text(encoding='utf-8')
        self.assertIn('"shell: ', markers)


class NotEveryMentionIsASpawn(unittest.TestCase):
    """The over-marking side: what the derivation must NOT be fooled by."""

    def test_subprocess_in_prose_is_not_a_spawn(self):
        boundaries = TESTS / 'test_boundaries.py'
        self.assertIn('subprocess', boundaries.read_text(encoding='utf-8'),
                      'this test is pointless if the docstring stopped saying it')
        self.assertFalse(conftest.module_spawns(boundaries),
                         '`grep -l subprocess` counts this module; it spawns nothing')

    def test_a_module_importing_only_the_repo_root_is_not_a_spawn(self):
        # `from support import REPO_ROOT` is how half the suite puts src/ on
        # the path. Naming the spawning package is not using it.
        self.assertFalse(conftest.module_spawns(TESTS / 'test_verdict.py'))


class NoUnreadSpawnSpelling(unittest.TestCase):
    """The under-marking side: a spawn the derivation cannot see is a hole.

    Scoped to where a hole can exist — the unmarked modules, and every support
    file, since a helper that shells out by an unread spelling leaves its
    callers unmarked too. A module that already carries the mark cannot hide a
    spawn: it is skipped on three interpreters either way.
    """

    def test_no_unmarked_module_spawns_by_a_spelling_the_derivation_skips(self):
        unmarked = [p for p in _modules() if not conftest.module_spawns(p)]
        offenders = []
        for path in unmarked + sorted(SUPPORT.glob('*.py')):
            for node in ast.walk(ast.parse(path.read_text(encoding='utf-8'))):
                if not isinstance(node, ast.Call):
                    continue
                function = node.func
                if isinstance(function, ast.Attribute):
                    through_subprocess = (isinstance(function.value, ast.Name)
                                          and function.value.id == 'subprocess')
                    name = '' if through_subprocess else function.attr
                elif isinstance(function, ast.Name):
                    name = function.id
                else:
                    name = ''
                if name in UNREAD_SPAWN_CALLS:
                    offenders.append(f'{path.name}:{node.lineno} {name}()')
        self.assertEqual(offenders, [],
                         'these start a process by a route tests/conftest.py does '
                         'not read, so the module stays unmarked and stops running '
                         'on three interpreters in silence. Teach the derivation, '
                         'or spawn through `subprocess`.')


class ScratchSuite:
    """A throwaway suite under a copy of the real conftest."""

    @staticmethod
    def build(root: Path, hand_mark: dict[str, str] | None = None) -> None:
        shutil.copy2(TESTS / 'conftest.py', root / 'conftest.py')
        (root / 'pytest.ini').write_text(SCRATCH_INI, encoding='utf-8')
        (root / 'support').mkdir()
        (root / 'support' / '__init__.py').write_text(SCRATCH_SUPPORT, encoding='utf-8')
        for name, body in SCRATCH_MODULES.items():
            extra = (hand_mark or {}).get(name, '')
            (root / name).write_text(extra + body, encoding='utf-8')

    @staticmethod
    def run(root: Path, *argv: str) -> tuple[int, str]:
        done = subprocess.run([sys.executable, '-m', 'pytest', '-q', '--no-header',
                               '-p', 'no:cacheprovider', *argv],
                              cwd=root, capture_output=True, text=True)
        return done.returncode, done.stdout + done.stderr


class DerivationEndToEnd(unittest.TestCase):
    """`-m shell` against a real pytest, because that is the only consumer."""

    def test_the_two_slices_partition_the_scratch_suite(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ScratchSuite.build(root)
            for expression, expected, absent in (
                    ('shell', SCRATCH_SHELL, SCRATCH_NOT_SHELL),
                    ('not shell', SCRATCH_NOT_SHELL, SCRATCH_SHELL)):
                code, out = ScratchSuite.run(root, '-m', expression, '--co', '-q')
                self.assertEqual(code, 0, out)
                for name in expected:
                    self.assertIn(name, out, f'-m "{expression}" dropped {name}\n{out}')
                for name in absent:
                    self.assertNotIn(name, out, f'-m "{expression}" kept {name}\n{out}')

    def test_an_unmarked_run_still_collects_everything(self):
        # `make test` and `make fuzz` do not pass `-m shell`; the mark must
        # cost the default run nothing.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ScratchSuite.build(root)
            code, out = ScratchSuite.run(root)
            self.assertEqual(code, 0, out)
            self.assertIn(f'{len(SCRATCH_MODULES)} passed', out)


class HandApplicationIsRefused(unittest.TestCase):
    """The mark is a fact, so asserting it is an error — true or false."""

    def _refuses(self, hand_mark: dict[str, str], named: str) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ScratchSuite.build(root, hand_mark=hand_mark)
            code, out = ScratchSuite.run(root)
            self.assertNotEqual(code, 0, f'the hand-applied mark ran anyway:\n{out}')
            self.assertIn(named, out, out)
            self.assertIn('DERIVED', out, out)
            self.assertIn('no tests ran', out, out)

    def test_a_pytestmark_on_a_module_that_does_not_spawn_names_the_file(self):
        self._refuses({'test_pure.py': 'import pytest\n\npytestmark = pytest.mark.shell\n\n'},
                      'test_pure.py')

    def test_a_decorator_on_a_module_that_does_not_spawn_names_the_file(self):
        self._refuses({'test_pure.py': 'import pytest\n\n\n@pytest.mark.shell\n'},
                      'test_pure.py')

    def test_a_TRUE_hand_applied_mark_is_refused_too(self):
        # test_spawner.py really does spawn, so the mark is not a lie — it is a
        # second mechanism, and then `-m shell` no longer means one thing.
        self._refuses({'test_spawner.py': 'import pytest\n\npytestmark = pytest.mark.shell\n\n'},
                      'test_spawner.py')


if __name__ == '__main__':
    unittest.main()
