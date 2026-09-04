"""check hooks — the tracked hook corpus is ARMED, and every hook still runs.

`install-hooks` writes the guard corpus under `tools/hooks/`; writing it is not
arming it. git runs nothing there until `core.hooksPath` points at the
directory, and it silently skips any entry missing an exec bit — so a corpus
that is on disk, tracked and reviewed can be guarding nothing at all, with no
signal anywhere. This package told its consumers the corpus was self-hosted
HERE while `core.hooksPath` was unset in every checkout of it, for two releases
(0.24.0/bugs/self-hosting-has-no-arm-or-verify-target).

Four questions, and the last two are the ones a path check alone gets wrong:

  ARMED       `core.hooksPath` resolves to this repo's `tools/hooks`.
  A FILE      the entry is a regular file at all. Git's hook universe is every
              entry in the directory, so a directory or a broken symlink there
              is a name git tries and cannot exec — the guard that name stands
              for runs nothing. Enumerating only regular files does not merely
              miss it, it SUBTRACTS it: the census reads smaller than the
              directory and no line says why, which is the shape this gate was
              written against.
  EXECUTABLE  every entry carries an exec bit — git skips one that does not,
              in silence, which is a disarmed guard with nothing red.
  RUNS        the file still executes at all. Measured on this package's own
              history: grafting `cc-godot-sandbox.sh`'s 0.16.0 project-config
              header onto its current body drops four keys the body reads under
              `set -u`, so the hook dies on `unbound variable` before deciding
              anything and exits 1 — where only exit 2 is a BLOCK. It is on
              disk, it is executable, it looks installed, and it stops nothing.
              A gate that asks only where a path points calls that tree armed.

The RUNS probe is derived from each hook's SHAPE, never a roster — a roster
silently skips the hook added after it was written:

  `cc-*.sh`   a Claude Code hook. Every one documents the same contract for
              input it cannot act on: fail OPEN, exit 0, say why on stderr. Fed
              a payload that is not JSON it must exit 0 — and answering that
              runs the whole file, project-config header included, which is
              exactly what catches the header above.
  anything    a git hook. Its argv and stdin contract belong to git and differ
  else        per hook name, so there is no single call this gate could make
              that would be the real one. It is PARSED (`bash -n`), and the
              verdict says so rather than implying more was asked.

`_*` (sourced libraries) and `*.local` (config drop-ins) are excluded — the two
shapes doctor.sh excludes, for the same reason: neither is a hook git runs.

Deliberately NOT a second hook suite. Behaviour is proven by
`tests/test_hooks_payloads.py`, and for the three hooks that ship one by their
own `--self-test` corpus through `make hooks-self-test`. What is asked here is
the question none of those can answer, because every one of them runs a COPY in
a temp repo: is THIS checkout's corpus wired to git, and able to start.

No devkit.toml section. `tools/hooks/` is where `install-hooks` puts the corpus
in every consumer, so it is a fact about the package rather than a per-repo
choice, and a knob nobody sets is a knob that goes wrong unread.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from godot_devkit.core import walk
from godot_devkit.core.project import repo_root
from godot_devkit.core.walk import Kind, SkipReason, Walk

HOOKS_DIR = 'tools/hooks'
CC_PREFIX = 'cc-'
# The repair every finding prints. It must be runnable by a CONSUMER, not only
# here: `install-hooks` ships `tools/setup-hooks.sh` into every tree, while
# `make hooks` exists in this repo's own root Makefile and nowhere else. Naming
# the target would send a consumer to `No rule to make target`. This is the same
# wording `doctor.sh` prints, on purpose — two shipped surfaces, one repair.
ARM_COMMAND = 'bash tools/setup-hooks.sh'

# A payload no Claude Code hook can act on. Each one's own header promises the
# same answer to it: exit 0, and the reason on stderr.
UNREADABLE_PAYLOAD = 'not json {{{'
FAIL_OPEN = 0
# The finding column, wide enough for the longest label.
LABEL_WIDTH = len('NOT EXECUTABLE')


def _entries(directory: Path) -> Walk:
    """The hook entry points, asked of the DIRECTORY rather than of a list —
    a roster silently skips the hook added after it was written.

    `Kind.ANY`, deliberately. `Kind.FILE` is a UNIVERSE declaration and a
    universe reason never renders in `disclosures()`, so a directory or a
    broken symlink under `tools/hooks/` left the census with no line saying so
    and the number came out smaller than the directory — a gate PASSing over
    exactly the drift it was written to catch. Git's hook universe is every
    entry in the directory; so is this one, and a non-regular entry is a
    FINDING below rather than a subtraction here.

    Through `core.walk`, so the two shapes the filter removes are DISCLOSED in
    the count instead of subtracted from it: a directory holding nothing but
    `_*` libraries must not read as a corpus of that many hooks, and a `.local`
    that was meant to be a hook must be visible as the thing that was dropped.
    """
    return walk.children(directory, Kind.ANY).filter(
        lambda path: not path.name.startswith('_')
        and not path.name.endswith('.local'),
        SkipReason.EXCLUDED_PATH)


def _not_a_file(path: Path) -> str:
    """What an entry git cannot exec actually IS. Named, because 'not a regular
    file' sends nobody anywhere: the two real shapes are a checkout that lost a
    symlink's target and a directory that took a hook's name."""
    if path.is_dir():
        return 'is a directory'
    if path.is_symlink():
        return f'is a symlink to {os.readlink(path)}, which does not resolve'
    if not path.exists():
        return 'does not resolve'
    return 'is not a regular file'


def _hooks_path(root: Path) -> str:
    done = subprocess.run(['git', 'config', '--get', 'core.hooksPath'],
                          cwd=root, capture_output=True, text=True)
    return done.stdout.strip() if done.returncode == 0 else ''


def _runs(path: Path, root: Path) -> str:
    """'' when the hook started and answered; the finding text when it did not."""
    if path.name.startswith(CC_PREFIX):
        done = subprocess.run(['bash', str(path)], input=UNREADABLE_PAYLOAD,
                              text=True, capture_output=True, cwd=root)
        if done.returncode != FAIL_OPEN:
            said = (done.stderr or done.stdout).strip().splitlines()
            return (f'exited {done.returncode} on a payload it cannot read, '
                    f'where every Claude Code hook fails OPEN at '
                    f'{FAIL_OPEN} — it is installed and it stops nothing'
                    + (f': {said[-1]}' if said else ''))
        return ''
    done = subprocess.run(['bash', '-n', str(path)], capture_output=True,
                          text=True, cwd=root)
    if done.returncode != 0:
        return f'does not parse: {done.stderr.strip().splitlines()[-1]}'
    return ''


def run() -> int:
    root = repo_root()
    hooks = root / HOOKS_DIR
    # (label, sentence) pairs, so the column is one format string rather than
    # padding counted by hand into four literals.
    findings: list[tuple[str, str]] = []

    configured = _hooks_path(root)
    if not configured:
        findings.append((
            'UNARMED',
            f'core.hooksPath is unset, so git runs nothing under {HOOKS_DIR}/ '
            f'whatever is in it — `{ARM_COMMAND}`'))
    elif Path(os.path.normpath(root / configured)) != hooks:
        findings.append((
            'MISDIRECTED',
            f'core.hooksPath is {configured!r} — that is '
            f'{os.path.normpath(root / configured)}, not {hooks} — '
            f'`{ARM_COMMAND}`'))

    if not hooks.is_dir():
        print(f'[check:hooks] FAIL — there is no {HOOKS_DIR}/ directory; '
              f'`godot-devkit install-hooks` ships the corpus and '
              f'`{ARM_COMMAND}` arms it')
        return 1
    entries = _entries(hooks)
    census = entries.census(f'hook(s) under {HOOKS_DIR}/')
    if not entries.kept:
        # Rule 4 — a gate that scanned nothing says so. An empty corpus and a
        # guarded tree must never print the same word, and the census carries
        # what the filter removed so "empty" cannot mean "all excluded".
        print(f'[check:hooks] FAIL — {census}, so this reports on nothing; '
              f'`godot-devkit install-hooks` ships the corpus')
        return 1
    if shutil.which('bash') is None:
        # Not a soft skip: the corpus IS bash. A tree with no bash cannot run
        # a single one of these hooks, which is the finding, not a caveat.
        print(f'[check:hooks] FAIL — bash is not on PATH, so not one of the '
              f'{census} can run')
        return 1

    ran = parsed = 0
    for path in entries:
        rel = path.relative_to(root)
        if not path.is_file():
            # On disk, tracked, named like a hook, and git cannot start it.
            # DEAD by another route, and the one route where the entry never
            # even reaches the exec bit.
            findings.append((
                'NOT A FILE',
                f'{rel} {_not_a_file(path)} — git cannot exec it, so whatever '
                f'guard that name stands for runs nothing; `_`-prefix it if it '
                f'is not a hook — `{ARM_COMMAND}`'))
            continue
        if not os.access(path, os.X_OK):
            findings.append((
                'NOT EXECUTABLE',
                f'{rel} — core.hooksPath skips it in silence — '
                f'`{ARM_COMMAND}`'))
            continue
        broken = _runs(path, root)
        if broken:
            findings.append(('DEAD', f'{rel} {broken}'))
        elif path.name.startswith(CC_PREFIX):
            ran += 1
        else:
            parsed += 1

    scope = (f'{census}; {ran} fail open on a payload they cannot read, '
             f'{parsed} parse')
    if findings:
        for label, said in findings:
            print(f'  {label:<{LABEL_WIDTH}} {said}')
        print(f'[check:hooks] FAIL — {len(findings)} finding(s) across {scope}')
        return 1
    print(f'[check:hooks] PASS — armed at {configured}; {scope}')
    return 0
