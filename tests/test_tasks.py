"""test_tasks.py — the `[tasks]` role shape, and the gate that guarantees it.

The point of the role table is that ONE word reaches the same gate in every
repo. That only holds if a stale pointer is loud, so most of what is asserted
here is the gate FAILING: a renamed target, a missing required role, a program
that is not there. A gate proven only against a passing tree is a gate nobody
has watched fire.
"""
from __future__ import annotations

import contextlib
import io
import os
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from support import REPO_ROOT  # noqa: E402

sys.path.insert(0, str(REPO_ROOT / 'src'))
from godot_devkit.core.config import ConfigError  # noqa: E402
from godot_devkit.core.project import load_config, repo_root  # noqa: E402
from godot_devkit.repo import tasks  # noqa: E402

MAKEFILE = """\
.PHONY: precommit milestone
precommit:
\t@echo precommit ran
milestone:
\t@echo milestone ran
"""


@contextlib.contextmanager
def repo(config: str, makefile: str | None = MAKEFILE):
    """A throwaway git repo carrying a devkit.toml and (usually) a Makefile."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / 'repo'
        root.mkdir()
        (root / 'devkit.toml').write_text(config, encoding='utf-8')
        if makefile is not None:
            (root / 'Makefile').write_text(makefile, encoding='utf-8')
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


def gate() -> tuple[int, str]:
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        code = tasks.run()
    return code, buffer.getvalue()


def verb(argv: list[str]) -> tuple[int, str]:
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        code = tasks.main(argv)
    return code, buffer.getvalue()


BOTH_ROLES = ('[tasks]\n'
              'quick = "make precommit"\n'
              'verify = "make milestone"\n')


def test_gate_passes_when_both_roles_resolve():
    with repo(BOTH_ROLES):
        code, out = gate()
    assert code == 0, out
    assert 'PASS' in out
    assert 'precommit resolve' in out


def test_gate_fails_when_a_target_is_renamed():
    """The perturbation. A PASS that survives renaming the target is not a gate.

    This is the whole defect the table exists to catch: a project renames a
    Makefile target, `[tasks]` still names the old one, and nothing says so
    until an agent runs `task quick` inside a dispatch days later.
    """
    with repo(BOTH_ROLES, makefile=MAKEFILE.replace('precommit', 'check')):
        code, out = gate()
    assert code == 1, out
    assert 'UNRESOLVED' in out
    assert 'quick' in out and 'precommit' in out


def test_gate_fails_on_a_missing_required_role():
    with repo('[tasks]\nquick = "make precommit"\n'):
        code, out = gate()
    assert code == 1, out
    assert "no 'verify' role" in out


def test_gate_fails_when_the_program_is_not_on_path():
    with repo('[tasks]\nquick = "nosuchtool-9wq run"\n'
              'verify = "make milestone"\n'):
        code, out = gate()
    assert code == 1, out
    assert 'not on PATH' in out


def test_the_no_tasks_finding_is_stated_once():
    """The f-string prepended a phrase `_no_tasks_message()` already opens
    with, so the gate said `no [tasks] table in devkit.toml; no [tasks] table
    in devkit.toml. Declare...`. A gate that says a finding twice reads as two
    findings. Exit 1 stays: `tasks` is in EXPLICIT_CHECKS, so `check all` never
    reaches it, and explicitly asking about something unconfigured is a real
    finding."""
    with repo('[other]\nx = 1\n'):
        code, out = gate()
    assert code == 1
    assert out.count('no [tasks] table') == 1, out


def test_gate_fails_on_no_tasks_table_rather_than_passing_over_nothing():
    """Rule 4. A gate with nothing to scan says so; it never prints PASS."""
    with repo('[checks]\nall = ["doc"]\n'):
        code, out = gate()
    assert code == 1, out
    assert 'PASS' not in out
    assert 'no [tasks] table' in out


def test_an_empty_role_is_a_config_error_not_a_finding():
    with repo('[tasks]\nquick = ""\nverify = "make milestone"\n'):
        try:
            tasks.roles()
        except ConfigError as err:
            assert 'quick' in str(err)
        else:  # pragma: no cover - the assertion IS that this does not happen
            raise AssertionError('an empty role command was accepted')


def test_a_non_string_role_is_a_config_error():
    with repo('[tasks]\nquick = ["make", "precommit"]\n'
              'verify = "make milestone"\n'):
        code, _ = verb(['quick'])
    assert code == 2


def test_task_runs_the_declared_command_and_propagates_its_code():
    with repo('[tasks]\nquick = "make precommit"\n'
              'verify = "exit 3"\n'):
        assert tasks.run_role('quick') == 0
        assert tasks.run_role('verify') == 3


def test_task_refuses_an_undeclared_role():
    with repo(BOTH_ROLES):
        assert tasks.run_role('nope') == 2
        code, _ = verb(['quick', 'verify'])
        assert code == 2


def test_list_reports_a_missing_required_role_as_failure():
    with repo('[tasks]\nquick = "make precommit"\n'):
        code, out = verb(['--list'])
    assert code == 1
    assert 'MISSING required role(s): verify' in out


def test_this_repo_declares_and_resolves_both_roles():
    """Self-hosting: the toolkit's own table is the first consumer of the rule."""
    repo_root.cache_clear()
    load_config.cache_clear()
    previous = Path.cwd()
    os.chdir(REPO_ROOT)
    try:
        table = tasks.roles()
        assert set(tasks.REQUIRED_ROLES) <= set(table)
        code, out = gate()
        assert code == 0, out
    finally:
        os.chdir(previous)
        repo_root.cache_clear()
        load_config.cache_clear()


# --- what `make -n` actually does, and what the gate is allowed to claim -------
# The docstring used to say GNU make "is the one program whose targets can be
# verified WITHOUT running them" and that the gate "cannot execute the very
# suite it is checking for". The first half is false and the second is narrower
# than it read. Both are measured below rather than argued: the probe writes
# witness files, and the gate is asserted to warn about exactly what the probe
# proves.
SIDE_EFFECT_MAKEFILE = """\
PARSED := $(shell echo ran > parse.witness)

quick:
\t@echo quick
\t$(shell echo ran > expand.witness)

verify:
\t+@echo plus > plus.witness
"""


def test_make_n_runs_parse_time_shell_expanded_shell_and_plus_lines():
    """The measurement. `-n` holds back the RECIPE and nothing else.

    This is a property of make, not of this package — asserted here so the
    claim in `tasks.py` is held to something that fails when make changes.
    """
    with repo('[tasks]\nquick = "make quick"\nverify = "make verify"\n',
              SIDE_EFFECT_MAKEFILE) as root:
        code, out = gate()
        assert code == 0, out
        ran = sorted(p.name for p in root.glob('*.witness'))
    assert ran == ['expand.witness', 'parse.witness', 'plus.witness'], (
        f'`make -n` ran {ran} — the gate\'s claim about what it executes has '
        f'to match whatever this run actually did')


def test_the_gate_says_out_loud_that_resolving_a_make_role_runs_shell():
    """A side effect a user cannot predict from the tool's own words is a
    surprise the tool owns. The warning prints on every run that will do it."""
    with repo('[tasks]\nquick = "make precommit"\nverify = "make milestone"\n'):
        code, out = gate()
    assert code == 0, out
    assert 'parses this repo' in out and 'parse-time' in out, out
    assert '`+`-prefixed' in out, out


def test_the_warning_is_absent_when_no_role_is_a_make_role():
    """A gate that warns about something it is not about to do is noise."""
    with repo('[tasks]\nquick = "echo one"\nverify = "echo two"\n',
              makefile=None):
        code, out = gate()
    assert code == 0, out
    assert 'parse-time' not in out, out


def test_no_user_facing_text_claims_make_n_runs_nothing():
    """The exact wording that was false, kept out of the three places it lived:
    the module docstring, the usage text, and the README table."""
    sources = [(REPO_ROOT / 'src/godot_devkit/repo/tasks.py'),
               (REPO_ROOT / 'README.md')]
    for path in sources:
        body = path.read_text(encoding='utf-8')
        for claim in ('without running them', 'parses without running',
                      'cannot execute the very suite'):
            assert claim not in body, f'{path.name} still claims: {claim!r}'
    assert 'parse-time' in tasks.USAGE, tasks.USAGE
    # The half that IS true stays: a sub-make inherits -n.
    assert 'inherits `-n`' in (REPO_ROOT / 'src/godot_devkit/repo/tasks.py'
                               ).read_text(encoding='utf-8')
