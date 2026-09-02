"""test_gates_extra.py — `[gates] extra`, and everything it refuses.

The value this verb reads is INTERPOLATED INTO A MAKE COMMAND LINE by
Makefile.devkit's `check`, so the grammar has to be narrow and every rejection
has to be loud: a dropped entry is a gate that silently left the roster, which
is this package's cardinal sin with a config file in front of it.

So the bulk below is the refusal matrix — hostile input generated AGAINST the
docstring's own claims ("a make goal, and nothing that could be anything
else"), not a re-run of the intended path.
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from support import REPO_ROOT  # noqa: E402

sys.path.insert(0, str(REPO_ROOT / 'src'))
from godot_devkit.core.config import ConfigError  # noqa: E402
from godot_devkit.core.project import load_config, repo_root  # noqa: E402
from godot_devkit.repo import gates_extra  # noqa: E402


@contextlib.contextmanager
def repo_with(config: str | None):
    """A throwaway repo whose devkit.toml is exactly `config` (or absent)."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / 'repo'
        root.mkdir()
        (root / 'project.godot').write_text('config_version=5\n', encoding='utf-8')
        if config is not None:
            (root / 'devkit.toml').write_text(config, encoding='utf-8')
        subprocess.run(['git', 'init', '-q'], cwd=root, check=True)
        previous = Path.cwd()
        os.chdir(root)
        repo_root.cache_clear()
        load_config.cache_clear()
        try:
            yield root
        finally:
            os.chdir(previous)
            repo_root.cache_clear()
            load_config.cache_clear()


def run(*argv: str) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = gates_extra.main(list(argv))
    return code, out.getvalue(), err.getvalue()


# --- the intended path --------------------------------------------------------
def test_the_targets_are_printed_one_per_line_in_declaration_order():
    with repo_with('[gates]\nextra = ["codex-check", "behaviors-check"]\n'):
        code, out, _ = run()
    assert code == 0
    assert out.splitlines() == ['codex-check', 'behaviors-check']


@pytest.mark.parametrize('config', [
    None,                       # no devkit.toml at all
    '',                         # a devkit.toml with nothing in it
    '[checks]\nall = ["doc"]\n',  # a devkit.toml with no [gates] section
    '[gates]\n',                # a [gates] section with no key
])
def test_a_repo_that_declares_nothing_prints_nothing_and_passes(config):
    """The default is the stock one: the devkit gates and no more. A project
    with no gates of its own must not be told it has a config error."""
    with repo_with(config):
        code, out, err = run()
    assert (code, out, err) == (0, '', '')


def test_a_name_repeated_is_run_once():
    with repo_with('[gates]\nextra = ["a-scan", "b-scan", "a-scan"]\n'):
        code, out, _ = run()
    assert (code, out.split()) == (0, ['a-scan', 'b-scan'])


# --- the refusal matrix -------------------------------------------------------
# Each is a value that, interpolated into `make GDK_IN_CHECK=1 <value>`, would
# do something other than run one gate target.
REFUSED = {
    'two goals in one string': 'lint scan',
    'a tab': 'lint\tscan',
    'a newline': 'lint\nscan',
    'a command separator': 'lint; rm -rf /',
    'a pipeline': 'lint | tee /tmp/x',
    'a background fork': 'lint & sleep 9',
    'command substitution': 'lint$(whoami)',
    'a backtick': 'lint`whoami`',
    'a shell variable': 'lint$HOME',
    'a make variable': '$(DEVKIT)',
    'a make assignment': 'DEVKIT=/bin/false',
    'a quote': "lint'",
    'a double quote': 'lint"',
    'a redirect': 'lint > /etc/passwd',
    'a glob': '*',
    'a path': 'tools/dev/checks/lint.sh',
    'traversal': '../../../etc/passwd',
    'an absolute path': '/bin/sh',
    'a home reference': '~/lint',
    'a backslash': 'lint\\scan',
    'a flag': '--always-make',
    'a leading dash': '-j99',
    'a dot target': '.PHONY',
    'an empty name': '',
    'a space': ' ',
    'an over-long name': 'a' * 65,
    'a colon (a rule, not a goal)': 'lint:scan',
    'a percent (a pattern rule)': '%.o',
    'a carriage return': 'lint\rscan',
}


@pytest.mark.parametrize('value', REFUSED.values(), ids=list(REFUSED))
def test_a_value_that_is_not_a_make_goal_is_refused_and_named(value):
    # json.dumps is exactly TOML's basic-string escaping for these values, so
    # the hostile bytes survive the round trip into the parser under test.
    with repo_with(f'[gates]\nextra = [{json.dumps(value)}]\n'):
        code, out, err = run()
    assert code == 2, f'{value!r} was accepted: {out!r}'
    assert out == '', 'a refused roster still printed something to run'
    assert 'not make targets' in err, err
    # The offending value is IN the message: a refusal that names no repair is
    # a refusal a reader has to go and derive.
    assert repr(value) in err, err


def test_every_bad_value_is_named_in_one_refusal_not_the_first_one():
    with repo_with('[gates]\nextra = ["ok-scan", "bad one", "also;bad"]\n'):
        code, _, err = run()
    assert code == 2
    assert '2 value(s)' in err, err
    assert 'bad one' in err and 'also;bad' in err, err


@pytest.mark.parametrize('config', [
    '[gates]\nextra = "codex-check"\n',      # a bare string is iterable
    '[gates]\nextra = []\n',                 # declaring nothing
    '[gates]\nextra = ["ok", 3]\n',          # a non-string member
    '[gates]\nextra = { a = "b" }\n',        # a table
])
def test_a_malformed_value_is_a_config_error_not_a_narrowed_roster(config):
    """`core.config` owns these three refusals; this asserts they are not
    caught and swallowed on the way to a make command line."""
    with repo_with(config):
        code, out, err = run()
    assert (code, out) == (2, '')
    assert 'godot-devkit:' in err, err


def test_a_non_table_gates_section_is_a_config_error():
    with repo_with('gates = "nope"\n'):
        code, _, err = run()
    assert code == 2 and 'gates' in err


# --- the verb's own surface ---------------------------------------------------
def test_help_prints_the_contract_and_passes():
    with repo_with(None):
        code, out, _ = run('--help')
    assert code == 0 and 'usage: godot-devkit gates-extra' in out


def test_an_unexpected_argument_is_a_usage_error():
    with repo_with(None):
        code, out, err = run('--force')
    assert (code, out) == (2, '')
    assert '--force' in err


def test_targets_raises_rather_than_returning_a_short_roster():
    """The library function refuses by EXCEPTION, so no caller can mistake a
    trimmed tuple for the whole roster."""
    with repo_with('[gates]\nextra = ["fine", "not fine"]\n'):
        with pytest.raises(ConfigError):
            gates_extra.targets()
