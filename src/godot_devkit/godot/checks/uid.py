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
CHECK 2 (HARD): every git-tracked .gd has a tracked .gd.uid. Both checks read
                the SAME `[uid] exclude_prefixes` — one key, one scope.

`--fix` APPLIES check 1's repair. The gate already knows the should-be value —
it prints it in every DRIFT line — so making a human copy that string back into
the file by hand is busywork with a typo in it. The rewrite is byte-surgical:
only the `uid="…"` attribute on the drifted line changes, and only where the
target's sidecar says what the value must be.

Nothing else is repaired, deliberately. A ref whose target has NO .uid, and
check 2's untracked sidecars, both need a uid that does not exist yet — and
minting one here would be invention, not repair. Godot's ResourceUID.create_id()
owns that, and a fabricated uid is exactly the plausible-looking wrong answer
this package refuses to write.

devkit.toml: [uid] exclude_prefixes = ["addons/"]
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from godot_devkit.core.project import git_lines, repo_root
from godot_devkit.core.config import config_section, str_tuple

DEFAULT_EXCLUDE = ('addons/',)
# Attribute extraction is ORDER-INDEPENDENT — a reordered/hand-edited ref must
# be censused, not silently skipped (false-PASS discipline).
UID_ATTR = re.compile(r'\buid="(uid://[0-9a-z]+)"')
PATH_ATTR = re.compile(r'\bpath="res://([^"]+\.gd)"')
EXT_RESOURCE_PREFIX = '[ext_resource '
SCRIPT_TYPE = 'type="Script"'
UID_SUFFIX = '.uid'
GD_SUFFIX = '.gd'
FIX_FLAG = '--fix'
LINE_SEP = '\n'


@dataclass
class Drift:
    """One stale Script ref: where it is, what it says, what it should say."""
    rel: str
    line: int                 # index into the file's lines
    gd_rel: str
    uid: str
    actual: str | None        # None: the target has no .uid — unrepairable here

    @property
    def fixable(self) -> bool:
        return self.actual is not None

    def report(self, fixed: bool) -> str:
        if self.actual is None:
            return f'  DRIFT  {self.rel} -> {self.gd_rel} has NO .uid file ' \
                   f'(referenced uid {self.uid})'
        if fixed:
            return f'  FIXED  {self.rel} : {self.uid} -> {self.actual}  ({self.gd_rel})'
        return f'  DRIFT  {self.rel} : {self.uid} -> should be {self.actual}  ' \
               f'({self.gd_rel})'


def _scan(root, exclude: tuple[str, ...]) -> tuple[list[Drift], int, int]:
    """Every stale Script ref, plus the census that proves what was scanned."""
    drifts: list[Drift] = []
    files = 0
    refs = 0
    for rel in git_lines('ls-files', '*.tres', '*.tscn'):
        if rel.startswith(exclude):
            continue
        files += 1
        text = (root / rel).read_text(encoding='utf-8', errors='replace')
        for index, line in enumerate(text.split(LINE_SEP)):
            if not line.startswith(EXT_RESOURCE_PREFIX) or SCRIPT_TYPE not in line:
                continue
            path_m = PATH_ATTR.search(line)
            if path_m is None:
                continue
            gd_rel = path_m.group(1)
            uid_m = UID_ATTR.search(line)
            if uid_m is None:
                continue  # path-only ref — `check tres` owns that drift class
            refs += 1
            sidecar = root / f'{gd_rel}{UID_SUFFIX}'
            actual = (sidecar.read_text(encoding='utf-8', errors='replace').strip()
                      if sidecar.is_file() else None)
            if actual != uid_m.group(1):
                drifts.append(Drift(rel, index, gd_rel, uid_m.group(1), actual))
    return drifts, files, refs


def _apply(root, drifts: list[Drift]) -> list[Drift]:
    """Rewrite each fixable drift in place; returns the ones actually repaired.

    Byte-surgical by construction: the file is split into its own lines, ONE
    line is rebuilt by swapping the uid attribute, and the rest are the original
    strings — so a repair cannot reformat, reorder or renumber anything. A line
    that does not contain the uid we read from it is left alone rather than
    guessed at (the tree moved under us mid-run).
    """
    fixed: list[Drift] = []
    by_file: dict[str, list[Drift]] = {}
    for drift in drifts:
        by_file.setdefault(drift.rel, []).append(drift)
    for rel, entries in by_file.items():
        path = root / rel
        lines = path.read_text(encoding='utf-8').split(LINE_SEP)
        touched = False
        for drift in entries:
            needle = f'uid="{drift.uid}"'
            line = lines[drift.line]
            if needle not in line:
                continue
            lines[drift.line] = line.replace(needle, f'uid="{drift.actual}"', 1)
            touched = True
            fixed.append(drift)
        if touched:
            path.write_text(LINE_SEP.join(lines), encoding='utf-8')
    return fixed


def _untracked_sidecars(tracked: set[str], exclude: tuple[str, ...]) -> list[str]:
    return [gd for gd in sorted(f for f in tracked if f.endswith(GD_SUFFIX))
            if not gd.startswith(exclude) and f'{gd}{UID_SUFFIX}' not in tracked]


def run(fix: bool = False) -> int:
    root = repo_root()
    exclude = str_tuple(config_section('uid'), 'uid', 'exclude_prefixes',
                        DEFAULT_EXCLUDE)
    drifts, files, refs = _scan(root, exclude)
    repaired = _apply(root, [d for d in drifts if d.fixable]) if fix else []
    hard = len(drifts) - len(repaired)

    print('[check:uid] CHECK 1 — .tres/.tscn Script ext_resource uid matches the script\'s .uid')
    was_repaired = {id(drift) for drift in repaired}
    for drift in drifts:
        print(drift.report(id(drift) in was_repaired))

    print(f'[check:uid] CHECK 2 — every tracked .gd has a tracked .gd.uid '
          f'({", ".join(exclude)} exempt)')
    # The CONFIGURED exclude, not DEFAULT_EXCLUDE. `[uid] exclude_prefixes` is
    # one documented key and it scoped only half the gate: a tree excluded from
    # CHECK 1 still had every .gd in it reported by CHECK 2, so the key a
    # consumer set to scope this gate did not scope this gate.
    untracked = _untracked_sidecars(set(git_lines('ls-files')), exclude)
    for gd in untracked:
        print(f'  UNTRACKED  {gd} has no tracked {gd}{UID_SUFFIX}')
    hard += len(untracked)

    if fix:
        # Say what was repaired even when nothing was: a `--fix` that silently
        # does nothing is indistinguishable from one that failed to write.
        print(f'[check:uid] FIX — repaired {len(repaired)} stale uid ref(s)'
              if repaired else
              '[check:uid] FIX — nothing to repair; no fixable uid drift found')
    if hard:
        print(f'[check:uid] FAIL — {hard} .uid drift / tracking violation(s)')
        if not fix and any(d.fixable for d in drifts):
            print(f'  Fix: re-run with {FIX_FLAG} to apply the should-be uids above.')
        return 1
    if not files:
        # Rule 4 — a gate that scanned nothing must say so. A misconfigured
        # exclude or a wrong root is indistinguishable from a clean tree,
        # and that PASS is the most dangerous output this package emits.
        # Say which of the two it was: "0 of 0" is a repo with no Godot
        # resources in it, "0 of 13" is an exclude that ate the whole census,
        # and the fix is different for each.
        print(f'[check:uid] FAIL — scanned 0 of '
              f'{len(git_lines("ls-files", "*.tres", "*.tscn"))} tracked '
              f'.tres/.tscn; check [uid] exclude_prefixes')
        return 1
    print(f'[check:uid] PASS — {refs} Script ref(s) across {files} file(s), no .uid drift; '
          f'all tracked .gd have tracked .uid')
    return 0
