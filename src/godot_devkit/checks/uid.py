"""check uid — guard against Godot .uid sidecar drift.

Godot 4 references script dependencies in .tres/.tscn by BOTH uid and path:
    [ext_resource type="Script" uid="uid://X" path="res://Y.gd" id="..."]
When a .gd's .uid sidecar is regenerated / late-committed / moved without
resaving the .tres that reference it, the cached uid goes stale — Godot falls
back to the text path and warns on every COLD import ('invalid UID … using
text path instead'). The warm .godot cache masks it locally, so it only bites
on fresh checkouts and CI. This makes that drift a failing gate instead.

CHECK 1 (HARD): every Script ext_resource uid in every tracked .tres/.tscn
                (addons/ exempt) matches the referenced .gd's sidecar .uid.
CHECK 2 (HARD): every git-tracked .gd (addons/ exempt) has a tracked .gd.uid.

devkit.toml: [uid] exclude_prefixes = ["addons/"]
"""
from __future__ import annotations

import re

from godot_devkit.project import git_lines, load_config, repo_root

DEFAULT_EXCLUDE = ('addons/',)
# Attribute extraction is ORDER-INDEPENDENT — a reordered/hand-edited ref must
# be censused, not silently skipped (false-PASS discipline).
UID_ATTR = re.compile(r'\buid="(uid://[0-9a-z]+)"')
PATH_ATTR = re.compile(r'\bpath="res://([^"]+\.gd)"')


def run() -> int:
    root = repo_root()
    exclude = tuple(load_config().get('uid', {}).get('exclude_prefixes', DEFAULT_EXCLUDE))
    hard = 0
    files = 0
    refs = 0

    print('[check:uid] CHECK 1 — .tres/.tscn Script ext_resource uid matches the script\'s .uid')
    for rel in git_lines('ls-files', '*.tres', '*.tscn'):
        if rel.startswith(exclude):
            continue
        files += 1
        text = (root / rel).read_text(encoding='utf-8', errors='replace')
        for line in text.splitlines():
            if not line.startswith('[ext_resource ') or 'type="Script"' not in line:
                continue
            path_m = PATH_ATTR.search(line)
            if path_m is None:
                continue
            gd_rel = path_m.group(1)
            uid_m = UID_ATTR.search(line)
            if uid_m is None:
                continue  # path-only ref — `check tres` owns that drift class
            refs += 1
            uid = uid_m.group(1)
            sidecar = root / f'{gd_rel}.uid'
            if not sidecar.is_file():
                print(f'  DRIFT  {rel} -> {gd_rel} has NO .uid file (referenced uid {uid})')
                hard += 1
                continue
            actual = sidecar.read_text(encoding='utf-8', errors='replace').strip()
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
    print(f'[check:uid] PASS — {refs} Script ref(s) across {files} file(s), no .uid drift; '
          f'all tracked .gd have tracked .uid')
    return 0
