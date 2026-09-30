---
id: ft-the-import-never-touches-the-tree
kind: feature
milestone: "1.4.0"
name: the import never touches the tree
status: done
reviewed: docs/reviews/2026-09-29-1.4.0-the-import-never-touches-the-tree.md
depends_on: []
consumed_by: []
changelog: make import-cache runs the editor pass in a scratch copy and never writes the tree's files; .godot comes back by rename (#20 #23).
---

# the import never touches the tree

Issues: #20, #23.

`import_cache.sh` runs a headless editor pass in the working tree, and that has two costs:

- **#20** The pass re-serialises authored `.tres` (value normalisation, `ext_resource` reorder,
  sub-resources extracted to new files). A killed run leaves the churn behind: 116 to 126 tracked
  files rewritten, and in one case a resource that lost its parts. The final diagnosis blamed an
  open EDITOR for some occurrences, but the kit's headless pass has the same shape and must not
  share it.
- **#23** `rm -rf .godot && make import-cache` in the checkout someone is PLAYING from breaks their
  session: the game fails to load `res://.godot/imported/*.ctex` mid-run.

## Decided (do not re-plan)

- **Import in a copy, bring back only what is new.** `import_cache.sh` builds the cache in a
  scratch copy of the project, under the sandbox runs dir, never `/tmp` directly. The copy is
  cheap: `cp -c` (APFS clone) on macOS, `cp --reflink=auto` on Linux, plain `cp -R` as the
  fallback. It holds the tracked files plus untracked-not-ignored ones, and the existing `.godot/`
  so the pass is incremental. After the pass, it brings back:
  1. `.godot/` as a whole, swapped in by rename (`mv .godot .godot.old.$$ && mv <copy>/.godot .godot
     && rm -rf .godot.old.$$`), so a running game's open handles keep the old inodes and no reader
     ever sees a half-written directory;
  2. `*.uid` and `*.import` sidecars that exist in the copy and NOT in the tree (new files only).
  Everything else the pass rewrote stays in the copy and is REPORTED, not applied, as a count plus
  the first few paths (`dropped N re-serialised files (import churn): …`). The working tree's
  tracked files are never written. `project.godot` restore logic becomes unnecessary: say so in the
  code and delete what the copy makes dead.
- **Signals.** The script traps INT/TERM/EXIT to remove its scratch copy. There is nothing in the
  tree to revert any more, which is the point.
- **A live process on the project (#23).** Before the swap, look for a godot process whose argv
  names this project root (`ps -axo pid=,args=`, matching the engine basename and the root path).
  If one is found, WARN with its pid and args, then swap anyway. The rename is safe for open
  handles, and refusing would make the import unusable while an editor is open, which is the
  normal case. Say plainly in the warning that a running game may need a restart to see new
  imports.
- **Contract with the diff-slice lane:** the CLI and exit codes do not change (0 refreshed, 1 not,
  2 harness error). `gdk_rebuild_import_cache` in `gdk_runners.sh` is the runners lane's file.
  Change how `import_cache.sh` calls it (for example with a `--path <copy>` argument) only if the
  function already takes a path. Otherwise wrap it in the copy's working directory. Do not edit
  `gdk_runners.sh`; if you cannot avoid it, stop and report.
- Not in scope: the #20 comment asking `check uid` to name a stale editor cache. It needs a
  `uid_cache.bin` reader and is a separate item.
- Minor bump: the output shape changes (dropped-churn line, live-process warning).

## Ship criterion

- `import_cache.sh --self-test`, with a stub godot that rewrites a tracked `.tres` and writes a new
  `.gd.uid` plus a `.godot/uid_cache.bin`: afterwards the tracked `.tres` is byte-identical, the
  new `.uid` is present, `.godot/uid_cache.bin` is the stub's, and the dropped line names the
  `.tres`.
- A stub killed mid-pass (SIGTERM) leaves the tree byte-identical and no scratch copy behind.

## Proof budget

  cases: 3 (churn dropped + new sidecar kept, killed run, live-process warning)
  tier: import_cache.sh --self-test (stub godot, temp tree)
  lands in: src/godot_devkit/godot/installables/import_cache.sh
  what already covers this: the self-test's argument and outcome cases; the churn report is proven today only as a listing
