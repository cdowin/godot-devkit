"""check uid — guard against Godot .uid sidecar drift.

Godot 4 references script dependencies in .tres/.tscn by BOTH uid and path:
    [ext_resource type="Script" uid="uid://X" path="res://Y.gd" id="..."]
When a .gd's .uid sidecar is regenerated / late-committed / moved without
resaving the .tres that reference it, the cached uid goes stale — Godot falls
back to the text path and warns on every COLD import ('invalid UID … using
text path instead'). The warm .godot cache masks it locally, so it only bites
on fresh checkouts and CI. This makes that drift a failing gate instead.

CHECK 1 (HARD): every Script ext_resource uid under the shipping dirs matches
                the referenced .gd's sidecar .uid.
CHECK 2 (HARD): every git-tracked .gd (addons/ exempt) has a tracked .gd.uid.

devkit.toml: [uid] scan_dirs = ["data", "scenes", ...]
"""
from __future__ import annotations

import re

from godot_devkit.project import git_lines, load_config, repo_root

DEFAULT_SCAN_DIRS = ('data', 'scenes', 'resources', 'systems', 'autoloads', 'shared')
SCRIPT_REF = re.compile(
    r'ext_resource type="Script" uid="(uid://[0-9a-z]+)" path="res://([^"]+\.gd)"')


def run() -> int:
    root = repo_root()
    scan_dirs = tuple(load_config().get('uid', {}).get('scan_dirs', DEFAULT_SCAN_DIRS))
    hard = 0

    print('[check:uid] CHECK 1 — .tres/.tscn Script ext_resource uid matches the script\'s .uid')
    for rel in git_lines('ls-files', *(f'{d}/**.tres' for d in scan_dirs),
                         *(f'{d}/**.tscn' for d in scan_dirs)):
        text = (root / rel).read_text(encoding='utf-8', errors='replace')
        for uid, gd_rel in SCRIPT_REF.findall(text):
            sidecar = root / f'{gd_rel}.uid'
            if not sidecar.is_file():
                print(f'  DRIFT  {rel} -> {gd_rel} has NO .uid file (referenced uid {uid})')
                hard += 1
                continue
            actual = sidecar.read_text(encoding='utf-8').strip()
            if uid != actual:
                print(f'  DRIFT  {rel} : {uid} -> should be {actual}  ({gd_rel})')
                hard += 1

    print('[check:uid] CHECK 2 — every tracked .gd has a tracked .gd.uid (addons/ exempt)')
    tracked = set(git_lines('ls-files'))
    for gd in sorted(f for f in tracked if f.endswith('.gd')):
        if gd.startswith('addons/'):
            continue
        if f'{gd}.uid' not in tracked:
            print(f'  UNTRACKED  {gd} has no tracked {gd}.uid')
            hard += 1

    if hard:
        print(f'[check:uid] FAIL — {hard} .uid drift / tracking violation(s)')
        return 1
    print('[check:uid] PASS — no .uid drift; all tracked .gd have tracked .uid')
    return 0
