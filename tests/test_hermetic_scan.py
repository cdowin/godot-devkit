"""test_hermetic_scan.py — the hermeticity gate, held to being able to FAIL.

`hermetic_run_scan.sh` carries its own corpus, and the corpus fires each of its
three checks at BOTH shapes — the hermetic one, which must stay silent, and the
planted one, which must redden. That is a strong claim and it is worth exactly
nothing until something proves the corpus can go red: a self-test that cannot
fail is a green light wired to nothing (the same rule `test_runners_installable`
applies to the library).

So each case below MUTATES one detector, in a scratch copy, and asserts the
corpus catches it. Two directions, deliberately: a detector taught to see
NOTHING (the gate goes blind) and a detector taught to see EVERYTHING (the gate
cries wolf, which is how a gate gets switched off). Neither is exercised by
running the corpus on the shipped file.

The runner itself is not booted against a Godot project anywhere: it never
boots an engine, and its child probe is a shell.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from support import REPO_ROOT  # noqa: E402

pytestmark = pytest.mark.skipif(shutil.which('bash') is None,
                                reason='needs bash')

INSTALLABLES = REPO_ROOT / 'src' / 'godot_devkit' / 'repo' / 'installables'
SCAN = INSTALLABLES / 'hermetic_run_scan.sh'
LIBRARY = INSTALLABLES / 'gdk_runners.sh'

# (label, what to replace, what to replace it with). Each one is a single
# detector, broken in one direction.
MUTANTS = (
    pytest.param(
        "BARE_EXIT_TRAP_RE='^[[:space:]]*trap[[:space:]].*[[:space:]]EXIT([[:space:]]|$)'",
        "BARE_EXIT_TRAP_RE='^[[:space:]]*trap[[:space:]]+__never__'",
        id='c1-blind-to-the-clobbering-trap'),
    pytest.param(
        'BARE_EXIT_TRAP_RE=',
        "BARE_EXIT_TRAP_RE='EXIT|gdk_on_exit' # ",
        id='c1-flags-the-sanctioned-hook-too'),
    pytest.param(
        '\t\t\t"$GDK_SANDBOX_RUNS_SUBDIR") ;;',
        '\t\t\t"$GDK_SANDBOX_RUNS_SUBDIR"|*) ;;',
        id='c3-exempts-every-sibling-of-the-spool'),
)


def self_test(script: Path) -> subprocess.CompletedProcess:
    return subprocess.run(['bash', str(script), '--self-test'],
                          text=True, capture_output=True)


def mutate(tmp_path: Path, old: str, new: str) -> Path:
    """A scratch copy of the runner with one detector broken.

    The library travels with it: the runner resolves `gdk_runners.sh` beside
    itself when the installed layout is absent, which is how the corpus runs
    out of the package's own source tree.
    """
    shutil.copy2(LIBRARY, tmp_path / LIBRARY.name)
    body = SCAN.read_text(encoding='utf-8')
    assert old in body, f'the mutation anchor moved: {old!r}'
    mutant = tmp_path / SCAN.name
    mutant.write_text(body.replace(old, new, 1), encoding='utf-8')
    return mutant


def test_the_shipped_corpus_passes(tmp_path):
    """The baseline. Run from a COPY, so the pass is not an artifact of the
    package layout the mutants are graded against."""
    shutil.copy2(LIBRARY, tmp_path / LIBRARY.name)
    shutil.copy2(SCAN, tmp_path / SCAN.name)
    done = self_test(tmp_path / SCAN.name)
    assert done.returncode == 0, done.stdout + done.stderr
    assert 'SELF-TEST OK' in done.stdout, done.stdout


@pytest.mark.parametrize('old,new', MUTANTS)
def test_a_broken_detector_reddens_the_corpus(tmp_path, old, new):
    done = self_test(mutate(tmp_path, old, new))
    assert done.returncode != 0, (
        'the corpus passed with a detector broken — it proves nothing:\n'
        + done.stdout + done.stderr)
    assert 'MISS' in done.stderr, done.stdout + done.stderr


def test_the_corpus_leaves_no_sandbox_spool_in_the_cwd(tmp_path):
    """The gate must not fail its own C3 by running. The corpus plants its
    residue in a scratch repo of its own; a spool minted in whatever directory
    the caller ran from is exactly the shape this gate exists to report."""
    shutil.copy2(LIBRARY, tmp_path / LIBRARY.name)
    shutil.copy2(SCAN, tmp_path / SCAN.name)
    workdir = tmp_path / 'cwd'
    workdir.mkdir()
    done = subprocess.run(['bash', str(tmp_path / SCAN.name), '--self-test'],
                          cwd=workdir, text=True, capture_output=True)
    assert done.returncode == 0, done.stdout + done.stderr
    assert list(workdir.iterdir()) == [], sorted(p.name for p in workdir.iterdir())
