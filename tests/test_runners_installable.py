"""test_runners_installable.py — the shell runners, RUN rather than read.

`gdk_runners.sh` is the library every Godot-booting gate in a consumer routes
through. It is not Python and it cannot boot an engine here, so the contract is
proven the way the hook corpus is: the script carries a `--self-test`, and this
file drives it through a subprocess and holds it to its published shape.

Two things this file adds on top of firing the corpus:

  - it MUTATES the verdict format and re-runs, so "the self-test passes" is
    evidence rather than a claim. A corpus that cannot fail is a green light
    wired to nothing.
  - it exercises the verdict line and its log path END TO END — sourcing the
    library into a scratch cwd and running a fake gate through
    gate_log -> gate_capture -> gate_verdict. That line shape is grepped by
    consumer Makefiles, so it is contract (CLAUDE.md rule 6), not cosmetics.

No engine is ever booted: this package never starts one (rule 2), so every
case here is either the library's own shell logic or a fake gate command.
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
LIBRARY = INSTALLABLES / 'gdk_runners.sh'

# The one line shape a consumer greps. Changing it is a minor bump at least.
VERDICT = '[PARSE] PASS (2 files) — full log: .gate-reports/parse.log'


def run(*argv: str, cwd: Path | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(['bash', *argv], cwd=cwd, text=True,
                          capture_output=True)


# --- the corpora, fired ------------------------------------------------------
def test_the_self_test_corpus_passes_and_reports_its_case_count():
    script = LIBRARY
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


# --- the argument surface: what the library REFUSES ---------------------------
@pytest.mark.parametrize('argv', [
    ('--nope',),                 # an unknown verb
    ('-x',),                     # an unknown short flag
    ('--self-test', 'extra'),    # a known verb with an argument it does not take
    ('--help', '--self-test'),   # two verbs
    ('',),                       # an empty argument is not "no argument"
], ids=['unknown', 'short', 'verb-plus-extra', 'two-verbs', 'empty'])
def test_an_argument_the_library_does_not_take_is_refused_as_a_usage_error(argv):
    script = LIBRARY
    done = run(str(script), *argv)
    assert done.returncode == 2, (
        f'{script.name} {argv} -> {done.returncode}\n{done.stdout}{done.stderr}')
    # Exit 2 for the RIGHT reason: a refusal names the remedy. Without this the
    # empty-argument case passed off a downstream "library not found" as the
    # argument check working.
    assert '--help' in done.stdout + done.stderr, done.stdout + done.stderr


def test_help_exits_zero_and_names_the_script():
    script = LIBRARY
    done = run(str(script), '--help')
    assert done.returncode == 0, done.stdout + done.stderr
    assert script.name in done.stdout, done.stdout
