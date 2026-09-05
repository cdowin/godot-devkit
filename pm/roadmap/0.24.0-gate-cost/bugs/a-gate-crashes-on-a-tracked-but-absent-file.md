---
id: 0.24.0/bugs/a-gate-crashes-on-a-tracked-but-absent-file
milestone: "0.24.0"
name: "`check defaults` and `orphans` traceback on a file that is tracked but absent from the worktree, where `check tres` and `check props` correctly degrade it to UNVERIFIED"
status: open
caught_in: "0.24.0"
fix_milestone:
caused_by:
---

# a-gate-crashes-on-a-tracked-but-absent-file

## Symptom

Three independent agents hit this in one afternoon on the nullbound consumer, each while doing
ordinary work: deleting files as part of a feature, before staging them.

```
FileNotFoundError: data/run_policies/practice.tres
FileNotFoundError: scenes/ui/hud/bars/boss_hp_bar.gd
FileNotFoundError: data/bestiary/tier_01_boss.tres
```

The tools enumerate paths with `git ls-files` and then open each one. A file that is **tracked but
deleted in the worktree** — the normal state of an in-progress deletion, and the permanent state
between `rm` and `git add` — satisfies the enumeration and fails the open.

Affected: `check defaults`, `orphans`, and (in the consumer's own `[gates] extra`)
`behavior-fan-scan`, which fails the same way through awk.

## Why it is a bug and not the user's problem

**The toolkit already disagrees with itself.** Given the identical tree, `check tres` and
`check props` degrade the same file to `UNVERIFIED` and carry on — the documented posture for
something the check cannot read. `check defaults` and `orphans` traceback instead.

A traceback is also not a verdict. The whole contract of these gates is a clean exit code and a
`PASS`/`FAIL` line; an uncaught exception is neither, and it stops the run before the checks behind
it report at all. In a shared worktree the blast radius is worse: agent A's unstaged deletion
crashes agent B's gate, and B has no way to tell a real failure from a peer's mid-write. All three
agents that hit it today correctly guessed "peer artifact" and moved on, but each spent a report
paragraph on it, and a less careful reader would have chased a phantom.

## Repro

```
cd <any consumer>
rm <some tracked .tres>          # do NOT stage it
<devkit> check defaults          # traceback
<devkit> check tres              # UNVERIFIED, exit 0 — the correct behaviour
git add -A -- <that path>
<devkit> check defaults          # clean
```

## Fix

Make the absent-file posture uniform: a tracked path that cannot be opened is `UNVERIFIED`, named in
the report, never an exception. `check tres` / `check props` already have the shape to copy.

Worth deciding at the same time whether `UNVERIFIED` should be silent or counted — a consumer with a
large in-progress deletion will see a long list, and the useful signal is "N unreadable, all of them
deleted-but-tracked" rather than N separate lines.

**Not urgent for the 0.24.0 tag** — it is a developer-experience defect in a state the developer
resolves by staging, and it does not affect a clean checkout or CI, where the worktree always matches
the index. It should not ride a release that is already carrying a vocabulary migration.
