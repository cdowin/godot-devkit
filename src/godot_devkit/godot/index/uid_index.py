"""uid_index.py — where a Godot resource's uid actually lives.

Godot 4 stores a resource's uid in a different place for every resource kind,
and both `scene canonicalize` (restoring refs a packed save dropped) and
`scene add --script` (minting a new ref) need the same answer. Four routes, in
order of authority:

    res://x.gd            -> the `x.gd.uid` sidecar
    res://x.tscn|.tres    -> the file's own `[gd_scene]` / `[gd_resource]` header
    res://x.png|.ttf|.ogg -> the `x.png.import` file written by the importer
    (none of the above)   -> whatever the rest of the repo already says about
                             that path, which is evidence rather than invention

Returning `None` is a legitimate answer and callers must handle it: a wrong uid
poisons Godot's cache far worse than a missing one does.
"""
from __future__ import annotations

import re
from pathlib import Path

from godot_devkit.core.project import git_lines

RES_PREFIX = 'res://'
UID_ATTR = re.compile(r'\buid="(uid://[0-9a-z]+)"')
PATH_ATTR = re.compile(r'\bpath="(res://[^"]+)"')
UID_SIDECAR_SUFFIX = '.uid'
IMPORT_SUFFIX = '.import'
HEADER_SCAN_BYTES = 4096          # the uid is always in the first header line
EXT_RESOURCE_PREFIX = '[ext_resource '


class UidIndex:
    """Where a Godot resource's uid lives, by resource kind.

    Three homes, and a fourth resort: a `.gd` keeps it in a `.gd.uid` sidecar, a
    `.tscn`/`.tres` in its own header, an imported asset (`.png`, `.ttf`, `.ogg`)
    in its `.import` file. If none of those exist — the file is untracked, or
    generated — we fall back to what the rest of the repo already says about it,
    which is evidence rather than invention.
    """

    def __init__(self, root: Path) -> None:
        self.root = root
        self._cross_reference: dict[str, str] | None = None
        self._resolved: dict[str, str | None] = {}

    def of(self, res_path: str) -> str | None:
        if res_path not in self._resolved:
            self._resolved[res_path] = self._resolve(res_path)
        return self._resolved[res_path]

    def _resolve(self, res_path: str) -> str | None:
        if not res_path.startswith(RES_PREFIX):
            return None
        file = self.root / res_path[len(RES_PREFIX):]
        sidecar = file.with_suffix(file.suffix + UID_SIDECAR_SUFFIX)
        if sidecar.is_file():
            return sidecar.read_text(encoding='utf-8').strip() or None
        importer = file.with_suffix(file.suffix + IMPORT_SUFFIX)
        for candidate in (file, importer):
            if candidate.is_file() and candidate.suffix in ('.tscn', '.tres', IMPORT_SUFFIX):
                match = UID_ATTR.search(candidate.read_text(
                    encoding='utf-8', errors='replace')[:HEADER_SCAN_BYTES])
                if match:
                    return match.group(1)
        return self.from_repo_references(res_path)

    def from_repo_references(self, res_path: str) -> str | None:
        """The uid every OTHER file in the repo already uses for this path."""
        if self._cross_reference is None:
            self._cross_reference = {}
            for rel in git_lines('ls-files', '*.tscn', '*.tres'):
                try:
                    text = (self.root / rel).read_text(
                        encoding='utf-8', errors='replace')
                except OSError:
                    continue  # tracked but locally deleted — no evidence to read
                for line in text.splitlines():
                    if not line.startswith(EXT_RESOURCE_PREFIX):
                        continue
                    path_m, uid_m = PATH_ATTR.search(line), UID_ATTR.search(line)
                    if path_m and uid_m:
                        self._cross_reference.setdefault(path_m.group(1), uid_m.group(1))
        return self._cross_reference.get(res_path)
