"""test_runners_installable.py — the shell runners, RUN rather than read.

`gdk_runners.sh` is the library every Godot-booting gate in a consumer routes
through, and `import_cache.sh` is the one runner that ships with it. Neither is
Python and neither can boot an engine here, so the contract is proven the way
the hook corpus is: each script carries a `--self-test`, and this file drives
it through a subprocess and holds it to its published shape.

Two things this file adds on top of firing the corpus:

  - it MUTATES the verdict format and re-runs, so "the self-test passes" is
    evidence rather than a claim. A corpus that cannot fail is a green light
    wired to nothing.
  - it exercises the verdict line and its log path END TO END — sourcing the
    library into a scratch cwd and running a fake gate through
    gate_log -> gate_capture -> gate_verdict. That line shape is grepped by
    consumer Makefiles, so it is contract (CLAUDE.md rule 6), not cosmetics.

The runner's own boot path is deliberately NOT exercised: it needs Godot, and
this package never boots one (rule 2). What is exercised is everything the
runner owns around the boot — its argument surface and its outcome check,
which is written as a pure function over the filesystem exactly so it can be
fired at fake files.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from support import REPO_ROOT  # noqa: E402

from godot_devkit.repo import install  # noqa: E402

pytestmark = pytest.mark.skipif(shutil.which('bash') is None,
                                reason='needs bash')

INSTALLABLES = REPO_ROOT / 'src' / 'godot_devkit' / 'repo' / 'installables'
LIBRARY = INSTALLABLES / 'gdk_runners.sh'
RUNNER = INSTALLABLES / 'import_cache.sh'
# Every shell runner install-runners ships. Each one carries --help and
# --self-test, and the argument surface below is fired at all of them: a runner
# added to the plan and not here would be a runner nothing holds to the shape.
SCRIPTS = tuple(INSTALLABLES / name
                for name, _rel in install.PLANS['install-runners']
                if name.endswith('.sh'))

# The one line shape a consumer greps. Changing it is a minor bump at least.
VERDICT = '[PARSE] PASS (2 files) — full log: .gate-reports/parse.log'


def run(*argv: str, cwd: Path | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(['bash', *argv], cwd=cwd, text=True,
                          capture_output=True)


# --- the corpora, fired ------------------------------------------------------
@pytest.mark.parametrize('script', SCRIPTS, ids=lambda p: p.stem)
def test_the_self_test_corpus_passes_and_reports_its_case_count(script):
    done = run(str(script), '--self-test')
    assert done.returncode == 0, done.stdout + done.stderr
    assert 'SELF-TEST OK' in done.stdout, done.stdout
    count = done.stdout.split('—')[1].split('case')[0].strip()
    assert int(count) > 0, f'a corpus of {count} cases proves nothing'


def test_the_library_corpus_FAILS_when_the_verdict_shape_is_broken(tmp_path):
    """Rule 4, applied to the corpus itself: a self-test that cannot go red is
    a false PASS with extra steps. Swap the em dash for a hyphen — the one
    byte a consumer's grep would feel — and the corpus must catch it."""
    mutant = tmp_path / 'gdk_runners.sh'
    mutant.write_text(
        LIBRARY.read_text(encoding='utf-8')
        .replace("'[%s] %s — full log: %s\\n'", "'[%s] %s - full log: %s\\n'"),
        encoding='utf-8')
    done = run(str(mutant), '--self-test')
    assert done.returncode == 1, done.stdout + done.stderr
    assert 'SELF-TEST FAIL' in done.stderr, done.stderr
    assert 'the verdict line shape' in done.stderr, done.stderr


# --- the verdict line and its log, end to end --------------------------------
def test_a_gate_prints_one_verdict_line_naming_a_log_that_holds_the_stream(tmp_path):
    script = tmp_path / 'gate.sh'
    script.write_text(
        f'set -uo pipefail\n'
        f'source "{LIBRARY}"\n'
        'log="$(gdk_gate_log parse)"\n'
        'gdk_gate_capture "$log" -- printf "boot line\\nsweep line\\n"\n'
        'gdk_gate_verdict PARSE "PASS (2 files)" "$log"\n',
        encoding='utf-8')

    done = run(str(script), cwd=tmp_path)
    assert done.returncode == 0, done.stdout + done.stderr
    assert done.stdout.splitlines() == [VERDICT], done.stdout

    log = tmp_path / '.gate-reports' / 'parse.log'
    assert log.exists(), 'the verdict named a log that was never written'
    assert log.read_text(encoding='utf-8') == 'boot line\nsweep line\n'


def test_verbose_streams_the_same_transcript_the_log_holds(tmp_path):
    """VERBOSE is the escape hatch the quiet default is only safe because of:
    it must add the stream, not replace the verdict or skip the file."""
    script = tmp_path / 'gate.sh'
    script.write_text(
        f'set -uo pipefail\n'
        f'source "{LIBRARY}"\n'
        'log="$(gdk_gate_log parse)"\n'
        'gdk_gate_capture "$log" -- printf "boot line\\n"\n'
        'gdk_gate_verdict PARSE "PASS (2 files)" "$log"\n',
        encoding='utf-8')

    done = subprocess.run(['bash', str(script)], cwd=tmp_path, text=True,
                          capture_output=True, env={'PATH': '/usr/bin:/bin',
                                                    'VERBOSE': '1'})
    assert done.returncode == 0, done.stdout + done.stderr
    assert done.stdout.splitlines() == ['boot line', VERDICT], done.stdout
    assert (tmp_path / '.gate-reports' / 'parse.log').read_text(
        encoding='utf-8') == 'boot line\n'


# --- the argument surface: what each script REFUSES --------------------------
@pytest.mark.parametrize('script', SCRIPTS, ids=lambda p: p.stem)
@pytest.mark.parametrize('argv', [
    ('--nope',),                 # an unknown verb
    ('-x',),                     # an unknown short flag
    ('--self-test', 'extra'),    # a known verb with an argument it does not take
    ('--help', '--self-test'),   # two verbs
    ('',),                       # an empty argument is not "no argument"
], ids=['unknown', 'short', 'verb-plus-extra', 'two-verbs', 'empty'])
def test_an_argument_neither_script_takes_is_refused_as_a_usage_error(script, argv):
    done = run(str(script), *argv)
    assert done.returncode == 2, (
        f'{script.name} {argv} -> {done.returncode}\n{done.stdout}{done.stderr}')
    # Exit 2 for the RIGHT reason: a refusal names the remedy. Without this the
    # empty-argument case passed off a downstream "library not found" as the
    # argument check working.
    assert '--help' in done.stdout + done.stderr, done.stdout + done.stderr


@pytest.mark.parametrize('script', SCRIPTS, ids=lambda p: p.stem)
def test_help_exits_zero_and_names_the_script(script):
    done = run(str(script), '--help')
    assert done.returncode == 0, done.stdout + done.stderr
    assert script.name in done.stdout, done.stdout


def test_the_runner_refuses_when_the_library_is_not_where_it_was_installed(tmp_path):
    """The runner sources the library by a configured relative path. A repo
    that moved one and not the other must be told, not left to run a rebuild
    with no sandbox — that is the incident the runner exists to prevent."""
    runner = tmp_path / 'import_cache.sh'
    shutil.copy2(RUNNER, runner)
    done = subprocess.run(['bash', str(runner)], cwd=tmp_path, text=True,
                          capture_output=True,
                          env={'PATH': '/usr/bin:/bin',
                               'GDK_RUNNERS_LIB': 'nowhere/gdk_runners.sh'})
    assert done.returncode == 2, done.stdout + done.stderr
    assert 'gdk_runners.sh not found' in done.stderr, done.stderr


# --- the 0.19.0 release review's findings, each pinned ------------------------
# The shell-side findings are cases in the scripts' own --self-test corpora
# (fired above). These three are not reachable from bash: two live in the
# Python install verb, and one is the runner refusing a repo it cannot serve.
def test_the_runner_refuses_a_root_that_is_not_a_godot_project(tmp_path):
    """MINOR-6. `REPO_ROOT_FROM_HERE` is a hardcoded depth: installed anywhere
    else it resolves to an arbitrary ancestor, and the run used to mint a
    sandbox there and boot `--path .` in it — reporting the failure as "the
    import pass hit the bound", which sends the reader to raise a timeout that
    was never the problem. The usage text promises exit 2 for an unusable repo;
    this is the path that produces it."""
    root = tmp_path / 'repo'
    (root / 'tools' / 'dev' / 'runners').mkdir(parents=True)
    shutil.copy2(LIBRARY, root / 'tools' / 'dev' / 'gdk_runners.sh')
    runner = root / 'tools' / 'dev' / 'runners' / 'import_cache.sh'
    shutil.copy2(RUNNER, runner)

    done = subprocess.run(['bash', str(runner)], cwd=root, text=True,
                          capture_output=True, env={'PATH': '/usr/bin:/bin'})
    assert done.returncode == 2, done.stdout + done.stderr
    assert 'not a Godot project' in done.stderr, done.stderr
    assert 'REPO_ROOT_FROM_HERE' in done.stderr, done.stderr
    # And it refused BEFORE minting anything: a sandbox in a directory that is
    # not the project is the residue this refusal exists to prevent.
    assert not (root / '.headless-userdata').exists()


def test_a_godot_project_at_the_root_gets_past_that_refusal(tmp_path):
    """The other half of the same claim: the guard must not refuse a repo it
    was installed into correctly. With a stub `godot` that writes nothing the
    run reaches its own outcome check and fails there (exit 1) — a different
    verdict, which is the point."""
    root = tmp_path / 'repo'
    (root / 'tools' / 'dev' / 'runners').mkdir(parents=True)
    (root / 'project.godot').write_text('config_version=5\n', encoding='utf-8')
    shutil.copy2(LIBRARY, root / 'tools' / 'dev' / 'gdk_runners.sh')
    runner = root / 'tools' / 'dev' / 'runners' / 'import_cache.sh'
    shutil.copy2(RUNNER, runner)
    stub = tmp_path / 'bin'
    stub.mkdir()
    (stub / 'godot').write_text('#!/bin/sh\nexit 0\n', encoding='utf-8')
    (stub / 'godot').chmod(0o755)

    done = subprocess.run(['bash', str(runner)], cwd=root, text=True,
                          capture_output=True,
                          env={'PATH': f'{stub}:/usr/bin:/bin'})
    assert done.returncode == 1, done.stdout + done.stderr
    assert 'not a Godot project' not in done.stderr, done.stderr
    assert 'did not refresh the cache' in done.stdout, done.stdout


@pytest.mark.skipif(shutil.which('shellcheck') is None,
                    reason='needs shellcheck')
def test_a_consumer_sourcing_the_library_shellchecks_clean(tmp_path):
    """A consumer's `shellcheck -x` follows the `source` and lints the library
    INLINE, so anything the library does to a name it also publishes lands as a
    finding in the consumer's file. The library's own self-test used to assign
    HOME, GDK_PROJECT_FILE and GDK_LOG_CAP_BYTES inside subshells, and every
    consumer script that later READ one of the three got SC2031 on a line its
    author wrote correctly — three sites in one adoption, each repaired with a
    local disable comment. The self-test scopes those values to a child process
    instead. This is the fixture that keeps it that way."""
    dev = tmp_path / 'tools' / 'dev'
    (dev / 'runners').mkdir(parents=True)
    shutil.copy2(LIBRARY, dev / 'gdk_runners.sh')
    consumer = dev / 'runners' / 'consumer.sh'
    consumer.write_text(
        '#!/usr/bin/env bash\n'
        'set -uo pipefail\n'
        '# shellcheck source=../gdk_runners.sh\n'
        'source "$(dirname "${BASH_SOURCE[0]}")/../gdk_runners.sh"\n'
        'gdk_sandbox_home\n'
        'echo "home $HOME cap $GDK_LOG_CAP_BYTES project $GDK_PROJECT_FILE"\n'
        'echo "engine $GDK_GODOT timeout $GDK_TIMEOUT"\n',
        encoding='utf-8')

    # cwd is the script's directory so `source=../gdk_runners.sh` resolves.
    done = subprocess.run(['shellcheck', '-x', consumer.name],
                          cwd=consumer.parent, text=True, capture_output=True)
    assert done.returncode == 0, done.stdout + done.stderr


@pytest.mark.skipif(shutil.which('shellcheck') is None,
                    reason='needs shellcheck')
@pytest.mark.parametrize('script', SCRIPTS, ids=lambda p: p.stem)
def test_every_shipped_runner_shellchecks_clean(script):
    """`shellcheck -x` on the installables themselves. They land in consumer
    trees whose own `check shell` gate runs over tools/ — a finding shipped
    from here reddens somebody else's commit gate."""
    done = subprocess.run(['shellcheck', '-x', script.name],
                          cwd=script.parent, text=True, capture_output=True)
    assert done.returncode == 0, done.stdout + done.stderr
