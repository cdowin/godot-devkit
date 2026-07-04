"""check tres — .tres/.tscn reference-format guard (canonical uid-in-refs).

Godot 4.4+ writes ext_resource references in the canonical uid-in-refs form:
    [ext_resource type="Script" uid="uid://X" path="res://Y" id="..."]
A repo should be migrated to this format ONCE, deliberately. The hazard this
guards: any editor / import / capture pass silently UPGRADES a path-only ref
(one lacking uid=) to uid-in-refs — churn that leaks into unrelated changes.
Keeping the committed tree fully canonical means an incidental upgrade has
nothing left to rewrite.

CHECK (HARD): every ext_resource ref in a tracked non-excluded .tres/.tscn
              carries a uid= (no path-only refs remain).

devkit.toml: [tres] exclude_prefixes = ["addons/", ...]
"""
from __future__ import annotations

from godot_devkit.project import git_lines, load_config, repo_root

DEFAULT_EXCLUDE = ('addons/',)


def run() -> int:
    root = repo_root()
    exclude = tuple(load_config().get('tres', {}).get('exclude_prefixes', DEFAULT_EXCLUDE))
    hard = 0
    checked = 0

    print('[check:tres] CHECK — every ext_resource ref carries a uid (canonical uid-in-refs)')
    for rel in git_lines('ls-files', '*.tres', '*.tscn'):
        if rel.startswith(exclude):
            continue
        checked += 1
        for n, line in enumerate((root / rel).read_text(
                encoding='utf-8', errors='replace').splitlines(), start=1):
            if (line.startswith('[ext_resource ') and 'path="' in line
                    and 'uid="uid://' not in line):
                print(f'  PATH-ONLY  {rel}:{n}:{line.strip()}')
                hard += 1

    if hard:
        print(f'[check:tres] FAIL — {hard} path-only ext_resource ref(s) across {checked} file(s)')
        print('  Fix: rewrite each to uid-in-refs form; mint MISSING header uids with')
        print('  Godot\'s ResourceUID.create_id() (never hand-author a uid string).')
        return 1
    print(f'[check:tres] PASS — all ext_resource refs canonical across {checked} .tres/.tscn')
    return 0
