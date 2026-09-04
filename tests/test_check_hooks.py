"""test_check_hooks.py — the gate that says whether THIS checkout is guarded.

`install-hooks` writes the corpus and `core.hooksPath` is what makes git run
it. Between those two facts sits the state this gate exists for: a tree whose
guards are on disk, tracked, executable and reviewed, and which git never
consults. This package sat in it for two releases while telling its consumers
the corpus was self-hosted here
(0.24.0/bugs/self-hosting-has-no-arm-or-verify-target).

Every case below builds a REAL repo, installs the REAL corpus into it and runs
the gate against it. Nothing disarms the checkout the suite is running in —
that would be a test that breaks the tree it is proving.

The sharp case is `test_a_hook_that_starts_and_dies_...`: armed, executable,
byte-present, and dead. It is the shape the installer measured on this
package's own history — a 0.16.0 project-config header under a current body
drops keys the body reads under `set -u`, so the hook exits 1 before deciding
anything where only 2 is a BLOCK. A gate that asks where a path points calls
that tree armed, which is why this one starts every hook.
"""
from __future__ import annotations

import contextlib
import os
import stat
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from support import REPO_ROOT, run_check                        # noqa: E402

sys.path.insert(0, str(REPO_ROOT / 'src'))
from godot_devkit.core.project import load_config, repo_root    # noqa: E402
from godot_devkit.repo import install                           # noqa: E402
from godot_devkit.repo.checks import hooks                      # noqa: E402

HOOKS_DIR = hooks.HOOKS_DIR
A_CC_HOOK = 'cc-godot-sandbox.sh'
A_GIT_HOOK = 'pre-push'
# Six `cc-*.sh` and two git hooks — asked of the plan, never restated, so the
# next hook to ship does not need this file edited.
SHIPPED = [rel for _, rel in install.PLANS['install-hooks']
           if rel.startswith(f'{HOOKS_DIR}/')]
CC_COUNT = sum(1 for rel in SHIPPED
               if Path(rel).name.startswith(hooks.CC_PREFIX))
GIT_COUNT = len(SHIPPED) - CC_COUNT


@contextlib.contextmanager
def hooked_repo(arm: bool = True):
    """A git repo with the corpus installed, armed or not, cwd'd into."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / 'repo'
        root.mkdir()
        subprocess.run(['git', 'init', '-q', '-b', 'main'], cwd=root, check=True)
        previous = Path.cwd()
        os.chdir(root)
        repo_root.cache_clear()
        load_config.cache_clear()
        try:
            assert install.main('install-hooks', []) == 0
            if arm:
                armed = subprocess.run(['bash', 'tools/setup-hooks.sh'],
                                       cwd=root, capture_output=True, text=True)
                assert armed.returncode == 0, armed.stderr
            yield root
        finally:
            os.chdir(previous)
            repo_root.cache_clear()
            load_config.cache_clear()


def gate() -> tuple[int, str]:
    return run_check(hooks)


def disarm_exec_bit(path: Path) -> None:
    path.chmod(path.stat().st_mode & ~(stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH))


# --- the three states -------------------------------------------------------
def test_an_unarmed_checkout_is_a_red_line_naming_the_repair():
    """The bug itself. The corpus is installed and every exec bit is on; git
    has simply never been told, so not one guard runs."""
    with hooked_repo(arm=False):
        code, out = gate()
    assert code == 1, out
    assert 'UNARMED' in out, out
    assert 'core.hooksPath is unset' in out, out
    assert hooks.ARM_COMMAND in out, out


def test_arming_the_same_tree_turns_it_green():
    """The other half: the gate must be satisfiable by the repair it names,
    or it is a red line nobody can clear."""
    with hooked_repo(arm=True):
        code, out = gate()
    assert code == 0, out
    assert '[check:hooks] PASS' in out, out
    assert f'armed at {HOOKS_DIR}' in out, out


def test_a_hooks_path_pointing_somewhere_else_names_both_paths():
    """Set, and set wrong, is not armed — and the operator needs to see the
    value that is there, not only the one that should be."""
    with hooked_repo(arm=True) as root:
        subprocess.run(['git', 'config', 'core.hooksPath', '.githooks'],
                       cwd=root, check=True)
        code, out = gate()
    assert code == 1, out
    assert 'MISDIRECTED' in out, out
    assert '.githooks' in out and HOOKS_DIR in out, out


# --- armed is not the same as working ----------------------------------------
def test_a_hook_without_its_exec_bit_is_named():
    """core.hooksPath skips a non-executable hook in SILENCE — a checkout onto
    a filesystem that drops the bit disarms one guard and nothing else moves."""
    with hooked_repo(arm=True) as root:
        disarm_exec_bit(root / HOOKS_DIR / A_GIT_HOOK)
        code, out = gate()
    assert code == 1, out
    assert 'NOT EXECUTABLE' in out and A_GIT_HOOK in out, out
    assert hooks.ARM_COMMAND in out, out


def test_a_hook_that_starts_and_dies_is_a_finding_though_it_looks_installed():
    """THE case a path check cannot make. The hook is present, tracked, armed
    and executable; its project-config header reads a variable the body never
    sets, so under `set -u` it dies before deciding anything and exits 1 —
    where only 2 is a BLOCK. Every raw boot walks straight through a guard
    that looks installed."""
    with hooked_repo(arm=True) as root:
        hook = root / HOOKS_DIR / A_CC_HOOK
        body = hook.read_text(encoding='utf-8')
        hook.write_text(body.replace('set -eu\n',
                                     'set -eu\necho "$NEVER_SET_BY_THIS_BODY"\n',
                                     1), encoding='utf-8')
        # It is still armed and still executable: the two things a path check
        # asks. Proven here so the case cannot pass for the other reason.
        assert os.access(hook, os.X_OK)
        code, out = gate()
    assert code == 1, out
    assert 'DEAD' in out and A_CC_HOOK in out, out
    assert 'fails OPEN' in out, out


def test_a_git_hook_that_does_not_parse_is_a_finding():
    """A git hook's argv contract is git's, so the gate asks the one question
    it can ask honestly of any of them: does the file still parse."""
    with hooked_repo(arm=True) as root:
        hook = root / HOOKS_DIR / A_GIT_HOOK
        hook.write_text(hook.read_text(encoding='utf-8') + '\nif then fi\n',
                        encoding='utf-8')
        code, out = gate()
    assert code == 1, out
    assert 'DEAD' in out and A_GIT_HOOK in out, out
    assert 'does not parse' in out, out


# --- what it counts, and what it refuses to count -----------------------------
def test_the_verdict_says_which_shape_proved_what():
    """`bash -n` is not the fail-open probe, and the line must not let one read
    as the other — a reader has to be able to tell what was actually asked."""
    with hooked_repo(arm=True):
        code, out = gate()
    assert code == 0, out
    assert f'{len(SHIPPED)} hook(s)' in out, out
    assert f'{CC_COUNT} fail open' in out, out
    assert f'{GIT_COUNT} parse' in out, out


def test_a_corpus_of_nothing_is_a_FAIL_not_a_PASS_over_nothing():
    """Rule 4. An empty directory and a guarded tree must never print the same
    word — that PASS is the most dangerous output this gate could emit."""
    with hooked_repo(arm=True) as root:
        for entry in (root / HOOKS_DIR).iterdir():
            entry.unlink()
        code, out = gate()
    assert code == 1, out
    assert '0 hook(s)' in out, out


def test_sourced_libraries_and_local_dropins_are_not_hooks():
    """`_*` is sourced by a hook and `*.local` is config — git runs neither, so
    neither needs an exec bit and neither may redden the gate."""
    with hooked_repo(arm=True) as root:
        (root / HOOKS_DIR / '_lib.sh').write_text('true\n', encoding='utf-8')
        (root / HOOKS_DIR / 'pre-push.local').write_text('X=1\n', encoding='utf-8')
        code, out = gate()
    assert code == 0, out
    assert f'{len(SHIPPED)} hook(s)' in out, out
    # DISCLOSED, not subtracted: the two are named in the count they left.
    assert '2 path(s) excluded from scope' in out, out


# --- the wiring: the gate runs here, and the repair it names is the target ----
def test_this_repo_runs_the_gate_in_its_own_aggregate():
    """A gate registered and never rostered is a gate that runs nowhere. This
    repo is the one that shipped the claim, so it is the one that must be red
    when it is unarmed."""
    config = tomllib.loads((REPO_ROOT / 'devkit.toml').read_text(encoding='utf-8'))
    roster = config.get('checks', {}).get('all', [])
    assert 'hooks' in roster, roster


def test_the_repair_the_gate_names_is_runnable_by_a_CONSUMER():
    """The repair has to work in the tree that TRIPS the gate. `make hooks` is
    this repo's own target and no consumer has it, so naming it sends a consumer
    to `No rule to make target`. The script is shipped by `install-hooks` into
    every tree, which is why it is the one named."""
    assert hooks.ARM_COMMAND == 'bash tools/setup-hooks.sh'
    shipped = REPO_ROOT / 'src/godot_devkit/repo/installables/setup-hooks.sh'
    assert shipped.is_file(), shipped
    install = (REPO_ROOT / 'src/godot_devkit/repo/install.py').read_text(encoding='utf-8')
    assert "'tools/setup-hooks.sh'" in install, 'the arm script must be an installable'


def test_the_two_shipped_surfaces_name_the_SAME_repair():
    """`check hooks` and `doctor.sh` both tell an operator how to arm the corpus.
    Two surfaces disagreeing is how a consumer learns to trust neither."""
    doctor = (REPO_ROOT / 'src/godot_devkit/repo/installables/doctor.sh').read_text(encoding='utf-8')
    assert 'tools/setup-hooks.sh' in doctor
    assert 'make hooks' not in doctor
