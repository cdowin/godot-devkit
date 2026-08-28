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


class ConfigError(Exception):
    """A malformed `devkit.toml` value. Exit 2 — a typo is NOT a finding.

    Exit 1 is reserved for findings, so CI must never read a config mistake as
    "drift found". Worse is the silent case this class exists to prevent: a
    BARE STRING is iterable, so `exclude_prefixes = "addons/"` coerced with
    `tuple(...)` becomes ('a','d','d','o','n','s','/') and excludes almost the
    whole tree — the gate then scans nothing and prints PASS.
    """


def config_section(name: str) -> dict:
    """One `devkit.toml` section, or {}. Refuses a non-table."""
    value = load_config().get(name, {})
    if not isinstance(value, dict):
        raise ConfigError(f'[{name}] must be a table, got {value!r}')
    return value


def str_tuple(sect: dict, name: str, key: str,
              fallback: tuple[str, ...]) -> tuple[str, ...]:
    """A list-of-strings setting. A bare string is REFUSED, never iterated."""
    value = sect.get(key)
    if value is None:
        return fallback
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise ConfigError(
            f'[{name}] {key} must be a list of strings, got {value!r}'
            + (f' — write {key} = [{value!r}]' if isinstance(value, str) else ''))
    return tuple(value)


def text(sect: dict, name: str, key: str, fallback: str) -> str:
    value = sect.get(key, fallback)
    if not isinstance(value, str):
        raise ConfigError(f'[{name}] {key} must be a string, got {value!r}')
    return value


def flag(sect: dict, name: str, key: str, fallback: bool) -> bool:
    value = sect.get(key, fallback)
    if not isinstance(value, bool):
        raise ConfigError(f'[{name}] {key} must be true/false, got {value!r}')
    return value


def number(sect: dict, name: str, key: str, fallback: int) -> int:
    value = sect.get(key, fallback)
    if not isinstance(value, int) or isinstance(value, bool):
        raise ConfigError(f'[{name}] {key} must be an integer, got {value!r}')
    return value


def git_lines(*args: str) -> list[str]:
    """Run git in the repo root; return non-empty stdout lines ([] on error)."""
    try:
        out = subprocess.run(
            ['git', *args], cwd=repo_root(),
            capture_output=True, text=True, check=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        return []
    return [ln for ln in out.stdout.splitlines() if ln.strip()]
