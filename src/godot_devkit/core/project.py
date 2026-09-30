"""project.py — consuming-repo resolution + devkit.toml config.

Every tool operates on the Godot repo the user invokes it FROM: the repo
root is the git toplevel of the current working directory (falling back to
the cwd itself outside a repo). Per-project variation lives in an optional
`devkit.toml` at that root — tools read their section with sensible
defaults, so a config-less repo gets the stock behavior.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tomllib
from functools import lru_cache
from pathlib import Path

CONFIG_NAME = 'devkit.toml'
# Every git read this package makes is a READ: it must never take the index
# lock a `git status`-style refresh would, or a gate run beside a commit (a
# hook, a parallel agent) can fail that commit on `index.lock` (#35).
GIT_ENV = {'GIT_OPTIONAL_LOCKS': '0'}


def run_git(args: list[str], cwd: Path | str | None = None,
            check: bool = True) -> subprocess.CompletedProcess:
    """The ONE way this package spawns git: text output captured, and
    `GIT_OPTIONAL_LOCKS=0` in its env. Raises what `subprocess.run` raises."""
    return subprocess.run(['git', *args], cwd=cwd, capture_output=True,
                          text=True, check=check, env={**os.environ, **GIT_ENV})


@lru_cache(maxsize=1)
def repo_root() -> Path:
    try:
        out = run_git(['rev-parse', '--show-toplevel'])
        return Path(out.stdout.strip())
    except (subprocess.CalledProcessError, FileNotFoundError):
        return Path.cwd()


@lru_cache(maxsize=1)
def load_config() -> dict:
    path = repo_root() / CONFIG_NAME
    if not path.is_file():
        return {}
    try:
        with path.open('rb') as fh:
            return tomllib.load(fh)
    except tomllib.TOMLDecodeError as err:
        # Config error, not drift: exit 2 per the contract (1 is reserved for
        # findings — CI must not read a toml typo as "drift found").
        print(f'godot-devkit: invalid {CONFIG_NAME}: {err}', file=sys.stderr)
        raise SystemExit(2) from err


def git_lines(*args: str) -> list[str]:
    """Run git in the repo root; return non-empty stdout lines ([] on error)."""
    try:
        out = run_git(list(args), cwd=repo_root())
    except (subprocess.CalledProcessError, FileNotFoundError):
        return []
    return [ln for ln in out.stdout.splitlines() if ln.strip()]
