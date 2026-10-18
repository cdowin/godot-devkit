"""check warnings — the GDScript analyzer warnings a project holds at ERROR level.

The engine reports an analyzer warning only when a script loads, and a warning
at level 1 scrolls past unread. This gate reads `project.godot` as text and
requires every named warning to be an ERROR (`2`), so the editor and every
headless boot fail on it. Pure parse: it never starts the engine.

CHECK (HARD): for each name in `[warnings] errors`, `project.godot` carries
              `gdscript/warnings/<name>=2` under `[debug]`.

godot-devkit.toml: [warnings] errors = ["unused_variable", ...]
             (stock: unused_variable shadowed_variable unused_signal
              integer_division standalone_expression)

On failure the gate prints the lines to paste under `[debug]`.
"""
from __future__ import annotations

import re

from godot_devkit.core.config import ConfigError, config_section, str_tuple
from godot_devkit.core.project import repo_root

SECTION = 'warnings'
TAG = '[check:warnings]'
ERROR_LEVEL = 2
STOCK_ERRORS = ('unused_variable', 'shadowed_variable', 'unused_signal',
                'integer_division', 'standalone_expression')
_PREFIX = 'gdscript/warnings/'
_NAME = re.compile(r'[a-z][a-z0-9_]*')


def debug_levels(text: str) -> dict[str, str]:
    """`{warning name: raw value}` for every `gdscript/warnings/*` key under `[debug]`."""
    levels: dict[str, str] = {}
    section = ''
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith('[') and line.endswith(']'):
            section = line[1:-1].strip()
        elif section == 'debug' and line.startswith(_PREFIX) and '=' in line:
            key, _, value = line.partition('=')
            levels[key.strip()[len(_PREFIX):]] = value.strip()
    return levels


def paste_lines(names) -> list[str]:
    """The `[debug]` lines that make every name an error."""
    return [f'{_PREFIX}{name}={ERROR_LEVEL}' for name in names]


def required() -> tuple[str, ...]:
    """The configured warning names; a name that is not a plain identifier exits 2."""
    names = str_tuple(config_section(SECTION), SECTION, 'errors', STOCK_ERRORS)
    bad = [n for n in names if not _NAME.fullmatch(n)]
    if bad:
        raise ConfigError(f'[{SECTION}] errors names {", ".join(bad)} — a warning '
                          f'name is lowercase letters, digits and underscores')
    return tuple(dict.fromkeys(names))


def run() -> int:
    names = required()
    path = repo_root() / 'project.godot'
    print(f'{TAG} CHECK — {len(names)} analyzer warning(s) are errors in project.godot')
    try:
        text = path.read_text(encoding='utf-8')
    except OSError:
        print(f'{TAG} FAIL — project.godot is not readable at the repo root; scanned 0 files')
        return 1
    levels = debug_levels(text)
    missing = [n for n in names if levels.get(n) != str(ERROR_LEVEL)]
    for name in missing:
        have = levels.get(name)
        print(f'  WARN-LEVEL  project.godot:{_PREFIX}{name} is '
              f'{have if have is not None else "unset"}, want {ERROR_LEVEL}')
    if missing:
        print(f'{TAG} FAIL — {len(missing)} of {len(names)} warning(s) below error level')
        print('  Fix: paste under [debug] in project.godot:')
        for line in paste_lines(missing):
            print(f'    {line}')
        return 1
    print(f'{TAG} PASS — {len(names)} warning(s) at error level in 1 project.godot')
    return 0
