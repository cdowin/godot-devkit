---
id: st-import-and-scenario-findings
kind: story
feature: ft-the-1-4-0-carry-forwards
milestone: "ms-refs-sees-what-godot-wires"
name: the import and scenario runner findings
status: building
owner:
depends_on: []
changelog:
---

# the import and scenario runner findings

The carry-forwards in `installables/import_cache.sh` and `installables/scenario.sh`, each named
by its review (`docs/reviews/2026-09-29-1.4.0-<review>.md`) and its line on 19ce2b0.

| row | where now | fix (decided) |
|---|---|---|
| import m3 | import_cache.sh:893-905 | a rewritten EXISTING `.uid` sidecar gets its own line, "NOT applied; the new cache expects them", never counted as import churn |
| import m4 | :205, :851, :863 | the copy label says what ran (`rsync`, `cp --reflink=auto (clone or copy)`, `cp`) plus bytes copied |
| import N5 | :369-385 | match the live process on the exact root path, not whitespace-split argv, so a root with a space matches |
| import N6 | :940-944 | record only: a comment at the two `mv`s naming the race and why the engine lease does not cover it. No lock |
| import N8 | :285, :967 | `--` before paths in every `cp` |
| import N7 + diff N8 | scenario.sh:1140-1158 | rung 1 inside a sweep declines the in-tree editor pass the way rung 2 already does (`IN_SWEEP`), and names `make import-cache`; outside a sweep both rungs are unchanged. The orphan-boots-tier cost (integration.sh:1632) is recorded, not fixed |
| integ N4 | scenario.sh:523, 530 | `GDK_LOG_CAP_BYTES` caps each slice's transcript, not the whole suite stream |
| integ N5 | scenario.sh:370-376, 446 | a verdict line counts for the current slice only when the name it carries is that slice's |

## Acceptance criteria

1. One new or amended `--self-test` case per row whose behaviour changed (N6 is a comment — no
   case); each fails on 19ce2b0's runner.
2. `import_cache.sh --self-test` and `scenario.sh --self-test` pass.
3. Installed copies stay byte-identical to the installables (tests/test_runners_installable.py).

## How this is proven

| criterion | tier | the case that proves it | existing? |
|---|---|---|---|
| 1–2 | shell | each runner's own `--self-test` corpus | amend |
| 3 | unit | tests/test_runners_installable.py | yes |

## Out of scope

`integration.sh`, `gdk_runners.sh`, `capture.sh`, `unit.sh` (other lanes). No engine boot.
CHANGELOG: report the sentence.
