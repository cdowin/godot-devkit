"""project.py — consuming-repo resolution + devkit.toml config.

Every tool operates on the Godot repo the user invokes it FROM: the repo
root is the git toplevel of the current working directory (falling back to
the cwd itself outside a repo). Per-project variation lives in an optional
`devkit.toml` at that root — tools read their section with sensible
defaults, so a config-less repo gets the stock behavior.
"""
from __future__ import annotations

import subprocess
import sys
import tomllib
from functools import lru_cache
from pathlib import Path

CONFIG_NAME = 'devkit.toml'


@lru_cache(maxsize=1)
def repo_root() -> Path:
    try:
        out = subprocess.run(
            ['git', 'rev-parse', '--show-toplevel'],
            capture_output=True, text=True, check=True)
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
        out = subprocess.run(
            ['git', *args], cwd=repo_root(),
            capture_output=True, text=True, check=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        return []
    return [ln for ln in out.stdout.splitlines() if ln.strip()]
