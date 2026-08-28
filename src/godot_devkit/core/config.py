"""config.py — typed `devkit.toml` reading.

Separate from `project.py` because they answer different questions: project.py
finds the repo and loads the file, this decides what a value is allowed to be.

Every coercion here refuses rather than converts. That is the whole point: a
BARE STRING is iterable, so `exclude_prefixes = "addons/"` under a plain
`tuple(...)` becomes ('a','d','d','o','n','s','/') and excludes almost the
entire tree — after which the gate scans nothing and prints PASS. That defect
shipped in v0.9.0 in seven of eight config sections, because the guard was
written once for `[pm]` and never carried across. One reader is the fix.
"""
from __future__ import annotations

from godot_devkit.core.project import load_config


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
