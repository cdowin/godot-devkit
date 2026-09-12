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
             [tres] baseline = { "scenes/legacy/hub.tscn" = 7 }
             (existing debt, per file at its CURRENT count of path-only refs:
              held and counted on a BASELINED line; a file past its entry
              fails, and an entry above what is left fails until lowered — it
              only shrinks)
"""
from __future__ import annotations

from godot_devkit.core.baseline import Baseline
from godot_devkit.core.project import git_lines, repo_root
from godot_devkit.core.config import config_section, str_tuple
from godot_devkit.godot import VENDORED_DEFAULT

SECTION = 'tres'
TAG = '[check:tres]'


def run() -> int:
    root = repo_root()
    sect = config_section(SECTION)
    exclude = str_tuple(sect, SECTION, 'exclude_prefixes', VENDORED_DEFAULT)
    baseline = Baseline.read(sect, SECTION)
    checked = 0
    # Every line in scan order, `(rel, line)` for a finding and `(None, line)`
    # for a disclosed skip — collected before printing so a baselined file's
    # findings can be held without reordering anything around them.
    lines: list[tuple[str | None, str]] = []

    print('[check:tres] CHECK — every ext_resource ref carries a uid (canonical uid-in-refs)')
    for rel in git_lines('ls-files', '*.tres', '*.tscn'):
        if rel.startswith(exclude):
            continue
        try:
            text = (root / rel).read_text(encoding='utf-8', errors='replace')
        except OSError:
            # Tracked in the index but not readable on disk (partial checkout,
            # mid-rebase). No evidence to scan — a censused, disclosed skip
            # (rule 4), never a traceback and never a finding: a working-tree
            # gap is not ref-format drift.
            lines.append((None, f'  UNVERIFIED  {rel} — tracked in git but '
                                f'not readable on disk; not scanned'))
            continue
        checked += 1
        for n, line in enumerate(text.splitlines(), start=1):
            if (line.startswith('[ext_resource ') and 'path="' in line
                    and 'uid="uid://' not in line):
                lines.append((rel, f'  PATH-ONLY  {rel}:{n}:{line.strip()}'))

    judged = baseline.judge((rel, line) for rel, line in lines if rel is not None)
    hard = len(judged.open)
    for rel, line in lines:
        if rel is None or rel not in judged.frozen:
            print(line)
    judged.report()
    if hard:
        print(f'[check:tres] FAIL — {hard} path-only ext_resource ref(s) across {checked} file(s)')
        print('  Fix: rewrite each to uid-in-refs form; mint MISSING header uids with')
        print('  Godot\'s ResourceUID.create_id() (never hand-author a uid string).')
        return 1
    if not checked:
        # Rule 4 — a gate that scanned nothing must say so. A misconfigured
        # exclude or a wrong root is indistinguishable from a clean tree,
        # and that PASS is the most dangerous output this package emits.
        # "0 of 0" is a repo with no Godot resources in it; "0 of 13" is an
        # exclude that ate the whole census. The fix differs, so say which.
        print(f'[check:tres] FAIL — scanned 0 of '
              f'{len(git_lines("ls-files", "*.tres", "*.tscn"))} tracked '
              f'.tres/.tscn; check [tres] exclude_prefixes')
        return 1
    if judged.failed:
        print(judged.verdict(TAG, f'{checked} file(s)'))
        return 1
    print(f'[check:tres] PASS — all ext_resource refs canonical across {checked} .tres/.tscn')
    return 0
