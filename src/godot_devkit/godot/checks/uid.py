"""check uid — guard against Godot .uid sidecar drift and uid text churn.

Godot 4 references script dependencies in .tres/.tscn by BOTH uid and path:
    [ext_resource type="Script" uid="uid://X" path="res://Y.gd" id="..."]
When a .gd's .uid sidecar is regenerated / late-committed / moved without
resaving the .tres that reference it, the cached uid goes stale — Godot falls
back to the text path and warns on every COLD import ('invalid UID … using
text path instead'). The warm .godot cache masks it locally, so it only bites
on fresh checkouts and CI. This makes that drift a failing gate instead.

CHECK 1 (HARD): every Script ext_resource uid in every tracked .tres/.tscn
                (addons/ exempt) matches the referenced .gd's sidecar .uid.
CHECK 2 (HARD): every git-tracked .gd has a tracked .gd.uid.
CHECK 3 (HARD): every NEW .gd — untracked or staged, per git status porcelain,
                so .gitignore is respected — has a .uid sidecar ON DISK. A
                tracked-only census misses the exact moment of risk: the new
                script that sails through the gate, gets `git add`ed later
                without its sidecar, and fails the next cold import. The
                remedy is named in the finding, because minting a sidecar is
                an editor-import concern this package never performs (rule 2:
                pure parse, never boots Godot). A staged .gd with a sidecar
                on disk but not staged is CHECK 2's finding — `git ls-files`
                reads the index, so staged-new files are already "tracked".
CHECK 4 (HARD): every tracked .gd.uid on disk still has its .gd (tracked or
                on disk). A sidecar whose script is gone is pure cruft.
CHECK 5 (HARD): every .tres/.tscn HEADER uid and non-Script ext_resource uid
                is the canonical Godot spelling — id_to_text(text_to_id(uid))
                == uid, judged by the ported engine codec (index/uid_codec).
                A non-canonical spelling of a VALID id resolves fine but is
                rewritten by Godot on the next editor save, so the file (and
                every ref sharing the spelling) diffs forever. Script refs
                are exempt: their canonical home is the .gd.uid sidecar, and
                CHECK 1 already pins ref text to sidecar text.
All five checks read the SAME `[uid] exclude_prefixes` — one key, one scope.

`--fix` APPLIES the repairs the gate already knows: check 1's should-be uid,
check 5's canonical spelling (SAME id, so no ref breaks), and check 4's cruft
deletion (a file removal, nothing else). Rewrites are byte-surgical: only the
`uid="…"` attribute on the reported line changes.

Nothing else is repaired, deliberately. A ref whose target has NO .uid,
check 2's untracked sidecars, check 3's missing sidecars, and check 5's
UNDECODABLE uids all need a uid that does not exist yet — and minting one
here would be invention, not repair. Godot's ResourceUID.create_id() owns
that, and a fabricated uid is exactly the plausible-looking wrong answer
this package refuses to write.

devkit.toml: [uid] exclude_prefixes = ["addons/"]
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from godot_devkit.core.project import git_lines, repo_root
from godot_devkit.core import apply
from godot_devkit.core.config import config_section, str_tuple
from godot_devkit.godot.index.uid_codec import canonical
from godot_devkit.godot.index.uid_index import (EXT_RESOURCE_PREFIX,
                                                HEADER_PREFIXES, UID_ATTR)
from godot_devkit.godot import VENDORED_DEFAULT

# Attribute extraction is ORDER-INDEPENDENT — a reordered/hand-edited ref must
# be censused, not silently skipped (false-PASS discipline). UID_ATTR and the
# ext_resource line prefix come from `uid_index`, the module that owns where a
# uid lives — PATH_ATTR stays local because this check wants `.gd` targets only.
PATH_ATTR = re.compile(r'\bpath="res://([^"]+\.gd)"')
# CHECK 5 captures the uid attribute PERMISSIVELY where CHECK 1's UID_ATTR is
# strict: a uid with a character outside [0-9a-z] must be censused as INVALID,
# not fall outside the regex and silently pass.
UID_ANY_ATTR = re.compile(r'\buid="([^"]*)"')
SCRIPT_TYPE = 'type="Script"'
UID_SUFFIX = '.uid'
GD_SUFFIX = '.gd'
FIX_FLAG = '--fix'
LINE_SEP = '\n'
# git status --porcelain: XY <path>. '??' is untracked; an index-side A/R/C is
# a staged-new path. -uall lists FILES inside untracked directories — without
# it a new .gd inside a new folder is one opaque `?? folder/` line.
PORCELAIN_ARGS = ('status', '--porcelain', '--untracked-files=all')
UNTRACKED_CODE = '??'
STAGED_NEW_CODES = 'ARC'
RENAME_ARROW = ' -> '


@dataclass
class Rewrite:
    """A uid attribute whose text must become another text, byte-surgically."""
    rel: str
    line: int                 # index into the file's lines
    uid: str
    actual: str | None        # None: no should-be value exists — unrepairable

    @property
    def fixable(self) -> bool:
        return self.actual is not None


@dataclass
class Drift(Rewrite):
    """One stale Script ref: where it is, what it says, what it should say."""
    gd_rel: str = ''

    def report(self, fixed: bool) -> str:
        if self.actual is None:
            return f'  DRIFT  {self.rel} -> {self.gd_rel} has NO .uid file ' \
                   f'(referenced uid {self.uid})'
        if fixed:
            return f'  FIXED  {self.rel} : {self.uid} -> {self.actual}  ({self.gd_rel})'
        return f'  DRIFT  {self.rel} : {self.uid} -> should be {self.actual}  ' \
               f'({self.gd_rel})'


@dataclass
class Misspelt(Rewrite):
    """One header / non-Script uid whose TEXT is not the engine's spelling."""

    def report(self, fixed: bool) -> str:
        if self.actual is None:
            return f'  INVALID  {self.rel} : {self.uid} does not decode as a ' \
                   f'resource uid'
        if fixed:
            return f'  FIXED  {self.rel} : {self.uid} -> {self.actual}'
        return f'  NON-CANONICAL  {self.rel} : {self.uid} -> should be ' \
               f'{self.actual}  (Godot rewrites it on the next editor save)'


def _scan(root, exclude: tuple[str, ...],
          ) -> tuple[list[Drift], list[Misspelt], int, int, int]:
    """Every stale Script ref and every non-canonical header / non-Script uid,
    plus the census that proves what was scanned."""
    drifts: list[Drift] = []
    misspellings: list[Misspelt] = []
    files = 0
    refs = 0
    uids = 0
    for rel in git_lines('ls-files', '*.tres', '*.tscn'):
        if rel.startswith(exclude):
            continue
        files += 1
        text = (root / rel).read_text(encoding='utf-8', errors='replace')
        for index, line in enumerate(text.split(LINE_SEP)):
            is_ext = line.startswith(EXT_RESOURCE_PREFIX)
            if line.startswith(HEADER_PREFIXES) or (is_ext and SCRIPT_TYPE not in line):
                uid_m = UID_ANY_ATTR.search(line)
                if uid_m is None:
                    continue  # a header/ref without a uid attr owns no spelling
                uids += 1
                spelt, canon = uid_m.group(1), canonical(uid_m.group(1))
                if canon != spelt:
                    misspellings.append(Misspelt(rel, index, spelt, canon))
                continue
            if not is_ext:
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
                drifts.append(Drift(rel, index, uid_m.group(1), actual, gd_rel))
    return drifts, misspellings, files, refs, uids


def _apply(root, rewrites: list[Rewrite]) -> tuple[list[Rewrite], list[str]]:
    """Rewrite each fixable finding in place; returns (repaired, refusal lines).

    Byte-surgical by construction: the file is split into its own lines, ONE
    line is rebuilt by swapping the uid attribute, and the rest are the original
    strings — so a repair cannot reformat, reorder or renumber anything. A line
    that does not contain the uid we read from it is left alone rather than
    guessed at (the tree moved under us mid-run).

    The write path reads STRICT where the scan read with `errors='replace'`:
    writing replacement characters back would silently mangle the very bytes
    that failed to decode. A file that does not decode is REFUSED — its
    findings stay reported and untouched — never crashed on and never
    rewritten lossily.
    """
    fixed: list[Rewrite] = []
    refused: list[str] = []
    by_file: dict[str, list[Rewrite]] = {}
    for rewrite in rewrites:
        by_file.setdefault(rewrite.rel, []).append(rewrite)
    for rel, entries in by_file.items():
        path = root / rel
        try:
            lines = path.read_text(encoding='utf-8').split(LINE_SEP)
        except UnicodeDecodeError as err:
            refused.append(f'  REFUSED  {rel} — not valid UTF-8 ({err}); '
                           f'repair skipped, drift still reported')
            continue
        touched = False
        for rewrite in entries:
            needle = f'uid="{rewrite.uid}"'
            line = lines[rewrite.line]
            if needle not in line:
                continue
            lines[rewrite.line] = line.replace(needle, f'uid="{rewrite.actual}"', 1)
            touched = True
            fixed.append(rewrite)
        if touched:
            apply.raise_on_error(
                apply.write_translated(path, LINE_SEP.join(lines)))
    return fixed, refused


def _untracked_sidecars(tracked: set[str], exclude: tuple[str, ...]) -> list[str]:
    return [gd for gd in sorted(f for f in tracked if f.endswith(GD_SUFFIX))
            if not gd.startswith(exclude) and f'{gd}{UID_SUFFIX}' not in tracked]


def _new_gd(exclude: tuple[str, ...]) -> list[str]:
    """Every untracked or staged-new .gd — the files CHECK 2's tracked census
    cannot see yet (untracked) or sees only as of this commit (staged)."""
    found: set[str] = set()
    for entry in git_lines(*PORCELAIN_ARGS):
        if len(entry) < 4:
            continue
        code, path = entry[:2], entry[3:]
        if RENAME_ARROW in path:
            path = path.rsplit(RENAME_ARROW, 1)[1]
        path = path.strip('"')  # git C-quotes unusual paths
        if not path.endswith(GD_SUFFIX) or path.startswith(exclude):
            continue
        if code == UNTRACKED_CODE or code[0] in STAGED_NEW_CODES:
            found.add(path)
    return sorted(found)


def _orphan_sidecars(root, tracked: set[str],
                     exclude: tuple[str, ...]) -> list[str]:
    """Tracked, on-disk .gd.uid whose .gd is neither tracked nor on disk.

    Both absences are required: an untracked .gd sitting on disk is CHECK 3's
    business, not cruft — deleting its sidecar would break the script about to
    be committed. And a sidecar already deleted on disk is a deletion pending
    commit, not a finding — which is also what makes `--fix` converge.
    """
    orphans = []
    for rel in sorted(tracked):
        if not rel.endswith(f'{GD_SUFFIX}{UID_SUFFIX}') or rel.startswith(exclude):
            continue
        gd = rel[:-len(UID_SUFFIX)]
        if gd in tracked or (root / gd).is_file() or not (root / rel).is_file():
            continue
        orphans.append(rel)
    return orphans


def _delete(root: Path, orphans: list[str]) -> tuple[list[str], list[str]]:
    """Remove each orphan sidecar — a file deletion only, nothing else."""
    deleted: list[str] = []
    refused: list[str] = []
    for rel in orphans:
        try:
            apply.raise_on_error(apply.remove_file(root / rel))
            deleted.append(rel)
        except OSError as err:
            refused.append(f'  REFUSED  {rel} — could not delete ({err}); '
                           f'orphan still reported')
    return deleted, refused


def run(fix: bool = False) -> int:
    root = repo_root()
    exclude = str_tuple(config_section('uid'), 'uid', 'exclude_prefixes',
                        VENDORED_DEFAULT)
    drifts, misspellings, files, refs, uids = _scan(root, exclude)
    tracked = set(git_lines('ls-files'))
    new_gd = _new_gd(exclude)
    missing = [gd for gd in new_gd
               if not (root / f'{gd}{UID_SUFFIX}').is_file()]
    orphans = _orphan_sidecars(root, tracked, exclude)
    sidecars = sum(1 for f in tracked
                   if f.endswith(f'{GD_SUFFIX}{UID_SUFFIX}')
                   and not f.startswith(exclude))

    # The CONFIGURED exclude, not VENDORED_DEFAULT. `[uid] exclude_prefixes` is
    # one documented key and it scoped only half the gate: a tree excluded from
    # CHECK 1 still had every .gd in it reported by CHECK 2, so the key a
    # consumer set to scope this gate did not scope this gate.
    untracked = _untracked_sidecars(tracked, exclude)

    rewrites: list[Rewrite] = [*(d for d in drifts if d.fixable),
                               *(m for m in misspellings if m.fixable)]
    repaired, refused = _apply(root, rewrites) if fix else ([], [])
    deleted, undeletable = _delete(root, orphans) if fix else ([], [])
    was_repaired = {id(entry) for entry in repaired}
    drift_fixed = sum(1 for entry in repaired if isinstance(entry, Drift))
    canon_fixed = len(repaired) - drift_fixed

    # One structure per check: (header, finding lines, findings STILL
    # standing). The report loop, the verdict sum and the FAIL count all read
    # from it — a sixth check is a new tuple here, and a check whose findings
    # never reach the verdict cannot be written (the hand-summed arithmetic
    # this replaces was the one place that rule-4 lie was one forgotten term
    # away).
    sections: list[tuple[str, list[str], int]] = [
        ('[check:uid] CHECK 1 — .tres/.tscn Script ext_resource uid matches '
         'the script\'s .uid',
         [drift.report(id(drift) in was_repaired) for drift in drifts]
         + list(refused),
         len(drifts) - drift_fixed),
        (f'[check:uid] CHECK 2 — every tracked .gd has a tracked .gd.uid '
         f'({", ".join(exclude)} exempt)',
         [f'  UNTRACKED  {gd} has no tracked {gd}{UID_SUFFIX}'
          for gd in untracked],
         len(untracked)),
        ('[check:uid] CHECK 3 — every new (untracked/staged) .gd has a .uid '
         'sidecar on disk',
         [f'  MISSING  {gd} is new and has no {gd}{UID_SUFFIX} — mint it '
          f'(open the project in the editor once, or run the consumer\'s '
          f'sandboxed `godot --headless --import`), then commit both together'
          for gd in missing],
         len(missing)),
        ('[check:uid] CHECK 4 — every tracked .gd.uid still has its .gd',
         [f'  FIXED  deleted {rel} — its script is gone' if rel in deleted
          else f'  ORPHAN  {rel} is tracked but {rel[:-len(UID_SUFFIX)]} '
               f'is gone — cruft; {FIX_FLAG} deletes it'
          for rel in orphans] + list(undeletable),
         len(orphans) - len(deleted)),
        ('[check:uid] CHECK 5 — every .tres/.tscn header + non-Script '
         'ext_resource uid is the canonical Godot spelling (Script refs are '
         'CHECK 1\'s domain)',
         [misspelt.report(id(misspelt) in was_repaired)
          for misspelt in misspellings],
         len(misspellings) - canon_fixed),
    ]

    for header, findings, _ in sections:
        print(header)
        for line in findings:
            print(line)

    # The buckets the three new checks censused, so a scan of nothing is
    # visible (rule 4) and grep-shaped consumers can count what was covered.
    print(f'[check:uid] census — {len(new_gd)} new (untracked/staged) .gd, '
          f'{sidecars} tracked .uid sidecar(s), '
          f'{uids} header/non-Script uid(s) canonicality-checked')

    hard = sum(outstanding for _, _, outstanding in sections)

    if fix:
        # Say what was repaired even when nothing was: a `--fix` that silently
        # does nothing is indistinguishable from one that failed to write.
        if drift_fixed:
            print(f'[check:uid] FIX — repaired {drift_fixed} stale uid ref(s)')
        if canon_fixed:
            print(f'[check:uid] FIX — canonicalized {canon_fixed} uid '
                  f'spelling(s) (same id, no ref break)')
        if deleted:
            print(f'[check:uid] FIX — deleted {len(deleted)} orphan .uid '
                  f'sidecar(s)')
        if not repaired and not deleted:
            print('[check:uid] FIX — nothing to repair; no fixable uid drift found')
    if hard:
        # The census rides the FAIL line as much as the PASS line (rule 4) —
        # and the smoke harness greps `across N file(s)` on both verdicts.
        print(f'[check:uid] FAIL — {hard} .uid drift / tracking violation(s) '
              f'across {files} file(s)')
        if not fix and (any(d.fixable for d in drifts)
                        or any(m.fixable for m in misspellings)):
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
