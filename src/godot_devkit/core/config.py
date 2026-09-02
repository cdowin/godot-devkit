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


def section_declared(name: str) -> bool:
    """Is `[name]` PRESENT in devkit.toml at all — even declared empty?

    `config_section` cannot answer this: an absent table and an empty one both
    read as {}. A section a release RETIRED has to be named on either spelling,
    because the author of the empty one believes it took effect just as much.
    """
    return name in load_config()


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
    if not value:
        # An empty list reads as "nothing", but downstream it usually means the
        # opposite: `git ls-files` with no pathspec is the ENTIRE repo. Refuse
        # rather than let a value mean the reverse of what it looks like.
        raise ConfigError(
            f'[{name}] {key} is empty — remove the key to take the default '
            f'({" ".join(fallback) or "none"}) rather than declaring nothing')
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


def table(sect: dict, name: str, key: str, fallback: dict) -> dict:
    """A table-of-tables setting. A string or list is REFUSED, never walked."""
    value = sect.get(key, fallback)
    if not isinstance(value, dict):
        raise ConfigError(f'[{name}] {key} must be a table, got {value!r}')
    return value


def str_tuple_table(sect: dict, name: str, key: str,
                    fallback: dict[str, tuple[str, ...]]) -> dict[str, tuple[str, ...]]:
    """A table mapping names to lists of strings — `str_tuple`, one level down.

    A bare-string VALUE is accepted as a ONE-ELEMENT list: it is the documented
    shorthand (`suffixes = { Manager = "emits" }`) and, taken whole, it cannot
    fall into the character-iteration trap this module exists to prevent —
    nothing here ever iterates it. Anything else non-list is REFUSED, and so is
    an empty list (remove the entry rather than declaring nothing).
    """
    raw = sect.get(key)
    if raw is None:
        return dict(fallback)
    if not isinstance(raw, dict):
        raise ConfigError(f'[{name}] {key} must be a table, got {raw!r}')
    out: dict[str, tuple[str, ...]] = {}
    for entry, names in raw.items():
        if isinstance(names, str):
            out[entry] = (names,)
        elif (isinstance(names, list) and names
              and all(isinstance(n, str) for n in names)):
            out[entry] = tuple(names)
        else:
            raise ConfigError(
                f'[{name}] {key}.{entry} must be a string or a non-empty list '
                f'of strings, got {names!r}')
    return out


def number_table(sect: dict, name: str, key: str,
                 fallback: dict[str, int]) -> dict[str, int]:
    """A table mapping names to INTEGERS — `number`, one level down.

    A ledger (`{path = 956}`) and an arity floor (`{"Save.write" = 2}`) are the
    same shape, and both are read as "how many" by code that would otherwise
    silently compare an int against a string. A bool is refused with everything
    else: `true` is an `int` in Python and would arrive as 1.
    """
    raw = sect.get(key)
    if raw is None:
        return dict(fallback)
    if not isinstance(raw, dict):
        raise ConfigError(f'[{name}] {key} must be a table, got {raw!r}')
    out: dict[str, int] = {}
    for entry, value in raw.items():
        if not isinstance(value, int) or isinstance(value, bool):
            raise ConfigError(
                f'[{name}] {key}.{entry} must be an integer, got {value!r}')
        out[entry] = value
    return out


def pattern(sect: dict, name: str, key: str, fallback: str) -> str:
    """A regex setting, COMPILED at load so a bad one is exit 2, not a finding."""
    import re as _re
    value = text(sect, name, key, fallback)
    try:
        _re.compile(value)
    except _re.error as err:
        raise ConfigError(f'[{name}] {key} is not a valid regex: {err}') from err
    return value


def number(sect: dict, name: str, key: str, fallback: int) -> int:
    value = sect.get(key, fallback)
    if not isinstance(value, int) or isinstance(value, bool):
        raise ConfigError(f'[{name}] {key} must be an integer, got {value!r}')
    return value
