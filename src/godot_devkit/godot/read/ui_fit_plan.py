"""ui_fit_plan.py — what the `ui-fit` runner boots, from `[ui_fit]`.

The runner (tools/dev/runners/ui_fit.sh, from `install-runners`) boots Godot;
this verb does not. It resolves `[ui_fit]` in godot-devkit.toml and prints the
plan the runner's helper reads, one line each:

    window <w> <h>                  the smallest window, then the largest
    large_text <res://x.gd> <func>  only when large_text_hook is set
    scene <res://x.tscn>            every scene in scope, sorted

`make ui-fit` pipes the two together. Pure parse: it lists files git knows
(tracked, plus untracked files that are not ignored) and reads nothing else.

godot-devkit.toml (every key optional; no section behaves as these defaults):
  [ui_fit]
  scenes = ["ui/gallery/"]        # .tscn files, or folders (ending "/") whose
                                  # .tscn files are all booted, subfolders too;
                                  # a game names its parts gallery here
  smallest_window = [1280, 720]
  largest_window = [3840, 2160]
  large_text_hook = ""            # "res://ui/text_size.gd:use_large_text": a
                                  # static func the runner calls with no
                                  # arguments before it boots every scene again

Exit: 0 the plan printed | 1 no scene in scope (a census of 0 FAILS) |
2 a usage or config error.
"""
from __future__ import annotations

import re
import sys

from godot_devkit.core.config import (
    ConfigError, config_section, repo_path_defect, size_pair, str_tuple, text)
from godot_devkit.core.project import git_lines

CONFIG_SECTION = 'ui_fit'
TAG = '[ui-fit]'
DEFAULT_SCENES = ('ui/gallery/',)
DEFAULT_SMALLEST = (1280, 720)
DEFAULT_LARGEST = (3840, 2160)
SCENE_SUFFIX = '.tscn'
HOOK = re.compile(r'^res://[^\s:]+\.gd:[A-Za-z_]\w*$')
USAGE = 'usage: godot-devkit ui-fit-plan'


def plan_lines() -> list[str]:
    """The plan, or ConfigError. An empty scene list is the caller's census."""
    sect = config_section(CONFIG_SECTION)
    scopes = str_tuple(sect, CONFIG_SECTION, 'scenes', DEFAULT_SCENES)
    for scope in scopes:
        why = repo_path_defect(scope.rstrip('/'))
        if why:
            raise ConfigError(f'[{CONFIG_SECTION}] scenes entry {scope!r} {why}')
        if not scope.endswith(('/', SCENE_SUFFIX)):
            raise ConfigError(f'[{CONFIG_SECTION}] scenes entry {scope!r} is '
                              f'neither a {SCENE_SUFFIX} file nor a folder ending "/"')
    small = size_pair(sect, CONFIG_SECTION, 'smallest_window', DEFAULT_SMALLEST)
    large = size_pair(sect, CONFIG_SECTION, 'largest_window', DEFAULT_LARGEST)
    hook = text(sect, CONFIG_SECTION, 'large_text_hook', '')
    if hook and not HOOK.match(hook):
        raise ConfigError(f'[{CONFIG_SECTION}] large_text_hook must be '
                          f'"res://path.gd:function", got {hook!r}')
    known = git_lines('ls-files', '--cached', '--others', '--exclude-standard',
                      f'*{SCENE_SUFFIX}')
    scenes = sorted({rel for rel in known
                     if any(rel == s or (s.endswith('/') and rel.startswith(s))
                            for s in scopes)})
    lines = [f'window {small[0]} {small[1]}', f'window {large[0]} {large[1]}']
    if hook:
        lines.append('large_text ' + ' '.join(hook.rsplit(':', 1)))
    return lines + [f'scene res://{rel}' for rel in scenes]


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
    if not any(line.startswith('scene ') for line in lines):
        scopes = ' '.join(str_tuple(config_section(CONFIG_SECTION), CONFIG_SECTION,
                                    'scenes', DEFAULT_SCENES))
        print(f'{TAG} FAIL — 0 scenes under [{CONFIG_SECTION}] scenes ({scopes}); '
              f'name the folder that holds your parts gallery', file=sys.stderr)
        return 1
    print('\n'.join(lines))
    return 0
