"""test_shell_mark.py — the derived `shell` mark, and the refusal that keeps it a fact.

`tests/conftest.py` decides, at collection, which modules spawn a process, and
the matrix skips them on three of four interpreters. That makes the derivation
load-bearing in a direction tests usually are not: a module that silently
leaves the marked side stops running on 3.12/3.13/3.14 and nothing goes red.

Three facts hold it. What the derivation says of a module that spawns by
import, one that spawns through a support helper, and one that does not —
asked of the function, over scratch files. That `-m shell` really partitions a
suite, against a real pytest, because that is the only consumer and the mark
has to land before pytest's own `-m` filtering or `-m shell` selects nothing.
And that a hand-applied mark is refused by name, true or false, because one
mechanism is the whole point.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import conftest
from support import REPO_ROOT

# A scratch suite covering the derivation's four answers, built under a copy
# of the real conftest. `quiet` is the sharp one: it comes out of a module
# that imports `subprocess`, and importing it is not a spawn.
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


def scratch_suite(root: Path, hand_mark: dict[str, str] | None = None) -> None:
    shutil.copy2(REPO_ROOT / 'tests' / 'conftest.py', root / 'conftest.py')
    (root / 'pytest.ini').write_text('[pytest]\nmarkers =\n    shell: derived\n', encoding='utf-8')
    (root / 'support').mkdir()
    (root / 'support' / '__init__.py').write_text(SCRATCH_SUPPORT, encoding='utf-8')
    for name, body in SCRATCH_MODULES.items():
        (root / name).write_text((hand_mark or {}).get(name, '') + body, encoding='utf-8')


def run_pytest(root: Path, *argv: str) -> tuple[int, str]:
    done = subprocess.run([sys.executable, '-m', 'pytest', '-q', '--no-header',
                           '-p', 'no:cacheprovider', *argv],
                          cwd=root, capture_output=True, text=True)
    return done.returncode, done.stdout + done.stderr


def test_the_derivation_reads_imports_and_support_helpers_not_prose(tmp_path):
    # Against the REAL support package: `temp_repo` shells out (`git init`),
    # `run_check` runs in process, and a docstring is not an import.
    for name, body, spawns in (('by_import.py', 'import subprocess\n', True),
                               ('via_helper.py', 'from support import temp_repo\n', True),
                               ('quiet_helper.py', 'from support import run_check\n', False),
                               ('prose.py', '"""subprocess.run, in a docstring"""\n', False)):
        (tmp_path / name).write_text(body, encoding='utf-8')
        assert conftest.module_spawns(tmp_path / name) is spawns, name


def test_the_two_slices_partition_a_real_collection(tmp_path):
    scratch_suite(tmp_path)
    for expression, expected, absent in (('shell', SCRATCH_SHELL, SCRATCH_NOT_SHELL),
                                         ('not shell', SCRATCH_NOT_SHELL, SCRATCH_SHELL)):
        code, out = run_pytest(tmp_path, '-m', expression, '--co', '-q')
        assert code == 0, out
        assert all(name in out for name in expected), (expression, out)
        assert not any(name in out for name in absent), (expression, out)


def test_a_hand_applied_mark_is_refused_by_name(tmp_path):
    # One spelling is fired: `pytestmark`, a decorator and a TRUE claim on a
    # module that really spawns all reach the same `get_closest_marker` refusal.
    scratch_suite(tmp_path, {'test_pure.py': 'import pytest\n\npytestmark = pytest.mark.shell\n\n'})
    code, out = run_pytest(tmp_path)
    assert code != 0, f'the hand-applied mark ran anyway:\n{out}'
    assert 'test_pure.py' in out and 'DERIVED' in out and 'no tests ran' in out, out
