"""test_hermetic_scan.py — the hermeticity gate, held to being able to FAIL.

`hermetic_run_scan.sh` carries its own corpus, and the corpus fires each of its
three checks at BOTH shapes — the hermetic one, which must stay silent, and the
planted one, which must redden. That is a strong claim and it is worth exactly
nothing until something proves the corpus can go red: a self-test that cannot
fail is a green light wired to nothing (the same rule `test_runners_installable`
applies to the library).

So the mutant case below MUTATES one detector at a time, in a scratch copy, and
asserts the corpus catches it. Two directions, deliberately: a detector taught
to see NOTHING (the gate goes blind) and a detector taught to see EVERYTHING
(the gate cries wolf, which is how a gate gets switched off). Neither is
exercised by running the corpus on the shipped file.

The runner itself is not booted against a Godot project anywhere: it never
boots an engine, and its child probe is a shell.
"""
import os
import shutil
import subprocess

import pytest

from support import REPO_ROOT

pytestmark = pytest.mark.skipif(shutil.which('bash') is None,
                                reason='needs bash')

SCAN = REPO_ROOT / 'src/godot_devkit/godot/installables/hermetic_run_scan.sh'
LIBRARY = SCAN.parent / 'gdk_runners.sh'

# (label, what to replace, what to replace it with). Each one is a single
# detector, broken in one direction.
MUTANTS = (
    ('c1-blind-to-the-clobbering-trap',
     "BARE_EXIT_TRAP_RE='^[[:space:]]*trap[[:space:]].*[[:space:]]EXIT([[:space:]]|$)'",
     "BARE_EXIT_TRAP_RE='^[[:space:]]*trap[[:space:]]+__never__'"),
    ('c1-flags-the-sanctioned-hook-too',
     'BARE_EXIT_TRAP_RE=',
     "BARE_EXIT_TRAP_RE='EXIT|gdk_on_exit' # "),
    ('c3-exempts-every-sibling-of-the-spool',
     '\t\t\t"$GDK_SANDBOX_RUNS_SUBDIR") ;;',
     '\t\t\t"$GDK_SANDBOX_RUNS_SUBDIR"|*) ;;'),
)


def _run(script, *args, cwd=None):
    return subprocess.run(['bash', str(script), *args], cwd=cwd,
                          text=True, capture_output=True)


def mutate(scratch, old, new):
    # A scratch copy of the runner with one detector broken. The library
    # travels with it: the runner resolves `gdk_runners.sh` beside itself when
    # the installed layout is absent, which is how the corpus runs out of the
    # package's own source tree.
    scratch.mkdir()
    shutil.copy2(LIBRARY, scratch / LIBRARY.name)
    body = SCAN.read_text(encoding='utf-8')
    assert old in body, f'the mutation anchor moved: {old!r}'
    (scratch / SCAN.name).write_text(body.replace(old, new, 1), encoding='utf-8')
    return scratch / SCAN.name


def test_the_shipped_corpus_passes_and_leaves_no_sandbox_spool_in_the_cwd(tmp_path):
    # The baseline. Run from a COPY, so the pass is not an artifact of the
    # package layout the mutants are graded against — and from a cwd of its
    # own: the gate must not fail its own C3 by running. The corpus plants its
    # residue in a scratch repo of its own; a spool minted in whatever
    # directory the caller ran from is exactly the shape this gate exists to
    # report.
    shutil.copy2(LIBRARY, tmp_path / LIBRARY.name)
    shutil.copy2(SCAN, tmp_path / SCAN.name)
    workdir = tmp_path / 'cwd'
    workdir.mkdir()
    done = _run(tmp_path / SCAN.name, '--self-test', cwd=workdir)
    assert done.returncode == 0, done.stdout + done.stderr
    assert 'SELF-TEST OK' in done.stdout, done.stdout
    assert list(workdir.iterdir()) == [], sorted(p.name for p in workdir.iterdir())


def test_a_broken_detector_reddens_the_corpus(tmp_path):
    for label, old, new in MUTANTS:
        done = _run(mutate(tmp_path / label, old, new), '--self-test')
        assert done.returncode != 0, (
            f'{label}: the corpus passed with a detector broken — it proves '
            'nothing:\n' + done.stdout + done.stderr)
        assert 'MISS' in done.stderr, label + '\n' + done.stdout + done.stderr


def test_a_live_run_home_is_not_counted_as_a_leak(tmp_path):
    # MINOR-3. The gate proper (not `--self-test`) walks the runs/ spool and
    # counts a home whose owning pid is DEAD as a leak. It called
    # `_gdk_pid_is_live`, which nothing defines — the library exports
    # `gdk_pid_is_live` — so every home printed `command not found` on stderr
    # and was counted orphaned. The note said the opposite of what was true,
    # and `shellcheck -x` cannot see an undefined function.
    #
    # A concurrent run's home belongs to a process that is still alive. The
    # liveness test is the LIBRARY's, deliberately — a bare `kill -0` reads
    # another user's live process as dead. The pass must not be vacuous: put
    # the shipped spelling back — one underscore — and BOTH symptoms return:
    # the shell says `command not found` and the live home is counted
    # orphaned.
    #
    # Note what is NOT asserted here: a home whose pid is genuinely dead. The
    # library reaps one from `gdk_sandbox_home`, which this gate's own C2
    # probe calls before the leak loop runs, so a dead home is already gone
    # by then. The note exists for what survives that reap; a live home
    # misjudged dead was the only way it ever fired.
    #
    # The repo is at the stock layout, carrying one run home owned by this pid.
    runners = tmp_path / 'repo' / 'tools' / 'dev' / 'runners'
    runners.mkdir(parents=True)
    shutil.copy2(LIBRARY, runners.parent / LIBRARY.name)
    runner = shutil.copy2(SCAN, runners / SCAN.name)
    (runners.parents[2] / '.headless-userdata' / 'runs' / f'run-{os.getpid()}-live').mkdir(
        parents=True)
    done = _run(runner, cwd=runners.parents[2])
    assert 'command not found' not in done.stderr, done.stderr
    assert 'orphaned run home(s)' not in done.stdout, done.stdout
    assert done.returncode == 0, done.stdout + done.stderr
    runner.write_text(
        runner.read_text(encoding='utf-8')
        .replace('\tgdk_pid_is_live "$pid" || leaked',
                 '\t_gdk_pid_is_live "$pid" || leaked'),
        encoding='utf-8')
    done = _run(runner, cwd=runners.parents[2])
    assert 'command not found' in done.stderr, done.stderr
    assert '1 orphaned run home(s)' in done.stdout, done.stdout
