"""fit_sweep_plan.py — what the `fit-sweep` runner boots, from `[fit_sweep]`.

The runner (tools/dev/runners/fit_sweep.sh, from `install-runners`) boots
Godot; this verb does not. It reads the size-class table `[fit_sweep] table`
names, resolves `[fit_sweep] scenes` and prints the plan the runner's helper
reads, one line each:

    size <w> <h> <class>-<role>   every size in the table, in table order:
                                  per class `worst`, then `floor`, then each
                                  of `also`; a size already listed is dropped
    touch <px>                    only when the table names a touch target
    scene <res://x.tscn>          every scene in scope, sorted

The table has the format of a design system `layout.json` (format 1):
`sizeClasses` maps a class name to `worst` and `also` (and optionally `floor`),
each a landscape `[width, height]` in logical px; `widthClasses` maps a website
width class to its least width. Both are validated; only `sizeClasses` is swept.
The touch target is `components.button.size.min.h` when it is a number of px; a
token reference (`"{size.touch-target}"`) carries no px and names none.

`make fit-sweep` pipes the two together. Pure parse: it reads the table and
lists files git knows (tracked, plus untracked files that are not ignored).

godot-devkit.toml:
  [fit_sweep]
  table = "design/layout.json"          # required: the repo-relative table
  scenes = ["res://ui/title.tscn",      # required: res:// scenes, or globs
            "res://ui/screens/**"]      # (`**` crosses folders, `*` and `?`
                                        # do not) over the project's .tscn files

Exit: 0 the plan printed | 1 a scenes entry matched no scene (a census of 0
FAILS) | 2 a usage or config error, or a table that is not the format.
"""
from __future__ import annotations

import json
import re
import sys

from godot_devkit.core.config import (
    ConfigError, config_section, repo_path_defect, str_tuple, text)
from godot_devkit.core.project import git_lines, repo_root
from godot_devkit.core.walk import glob_re

CONFIG_SECTION = 'fit_sweep'
TAG = '[fit-sweep]'
SCENE_SUFFIX = '.tscn'
RES = 'res://'
TABLE_FORMAT = 1
ROLES = ('worst', 'floor', 'also')
NAME = re.compile(r'^[a-z][a-z0-9-]*$')
USAGE = 'usage: godot-devkit fit-sweep-plan'


class Census(Exception):
    """A scenes entry that matched no scene: a finding, exit 1."""


def _px(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 1


def _size(value: object, where: str) -> tuple[int, int]:
    if not (isinstance(value, list) and len(value) == 2 and all(_px(v) for v in value)):
        raise ConfigError(f'{where} must be [width, height] in px of at least 1, got {value!r}')
    return value[0], value[1]


def table_sizes(data: object, where: str) -> tuple[list[str], int | None]:
    """The `size` lines and the touch target of one parsed table, or ConfigError."""
    if not isinstance(data, dict):
        raise ConfigError(f'{where} must be a JSON object')
    if data.get('format') != TABLE_FORMAT:
        raise ConfigError(f'{where} format must be {TABLE_FORMAT}, got {data.get("format")!r}')
    widths = data.get('widthClasses')
    if not (isinstance(widths, dict) and widths and all(
            NAME.match(k) and isinstance(v, int) and not isinstance(v, bool) and v >= 0
            for k, v in widths.items())):
        raise ConfigError(f'{where} widthClasses must map class names to least widths in px')
    classes = data.get('sizeClasses')
    if not (isinstance(classes, dict) and classes):
        raise ConfigError(f'{where} sizeClasses must name at least one class')
    lines: list[str] = []
    seen: set[tuple[int, int]] = set()
    for name, cls in classes.items():
        at = f'{where} sizeClasses.{name}'
        if not NAME.match(name) or not isinstance(cls, dict):
            raise ConfigError(f'{at} must be a lowercase class name holding an object')
        if 'worst' not in cls or not isinstance(cls.get('also'), list):
            raise ConfigError(f'{at} must have worst and an also list')
        sizes = [('worst', _size(cls['worst'], f'{at}.worst'))]
        if 'floor' in cls:
            sizes.append(('floor', _size(cls['floor'], f'{at}.floor')))
        sizes += [('also', _size(v, f'{at}.also[{i}]')) for i, v in enumerate(cls['also'])]
        for role, (w, h) in sizes:
            if (w, h) not in seen:
                seen.add((w, h))
                lines.append(f'size {w} {h} {name}-{role}')
    touch: object = data
    for key in ('components', 'button', 'size', 'min', 'h'):
        touch = touch.get(key) if isinstance(touch, dict) else None
    return lines, touch if _px(touch) else None


def _scenes(entries: tuple[str, ...]) -> list[str]:
    for entry in entries:
        rel = entry[len(RES):] if entry.startswith(RES) else ''
        why = repo_path_defect(rel) if rel else 'is not a res:// path'
        if why:
            raise ConfigError(f'[{CONFIG_SECTION}] scenes entry {entry!r} {why}')
    known = git_lines('ls-files', '--cached', '--others', '--exclude-standard',
                      f'*{SCENE_SUFFIX}')
    found: set[str] = set()
    for entry in entries:
        rel = entry[len(RES):]
        hits = ({k for k in known if glob_re(rel).match(k)} if any(c in rel for c in '*?')
                else {rel} & set(known))
        if not hits:
            raise Census(f'{TAG} FAIL — scenes entry {entry!r} matches 0 of the '
                         f'{len(known)} {SCENE_SUFFIX} file(s) git knows')
        found |= hits
    return sorted(found)


def plan_lines() -> list[str]:
    """The plan, or ConfigError / Census."""
    sect = config_section(CONFIG_SECTION)
    rel = text(sect, CONFIG_SECTION, 'table', '')
    if not rel:
        raise ConfigError(f'[{CONFIG_SECTION}] table is not set — name the repo-relative '
                          f'size-class table (a design system layout.json)')
    why = repo_path_defect(rel)
    if why:
        raise ConfigError(f'[{CONFIG_SECTION}] table {rel!r} {why}')
    if 'scenes' not in sect:
        raise ConfigError(f'[{CONFIG_SECTION}] scenes is not set — list res:// scenes or globs')
    entries = str_tuple(sect, CONFIG_SECTION, 'scenes', ())
    path = repo_root() / rel
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except FileNotFoundError:
        raise ConfigError(f'[{CONFIG_SECTION}] table {rel!r} does not exist') from None
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as err:
        raise ConfigError(f'[{CONFIG_SECTION}] table {rel!r} is not readable JSON: {err}') from None
    sizes, touch = table_sizes(data, f'table {rel}')
    lines = sizes + ([f'touch {touch}'] if touch else [])
    return lines + [f'scene {RES}{s}' for s in _scenes(entries)]


def main(argv: list[str]) -> int:
    if argv in (['-h'], ['--help']):
        print(__doc__.strip())
        return 0
    if argv:
        print(USAGE, file=sys.stderr)
        return 2
    try:
        lines = plan_lines()
    except ConfigError as err:
        print(f'godot-devkit: {err}', file=sys.stderr)
        return 2
    except Census as err:
        print(err, file=sys.stderr)
        return 1
    print('\n'.join(lines))
    return 0
