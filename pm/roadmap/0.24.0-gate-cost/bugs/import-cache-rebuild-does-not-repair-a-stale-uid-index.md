---
id: 0.24.0/bugs/import-cache-rebuild-does-not-repair-a-stale-uid-index
milestone: "0.24.0"
name: "`gdk_rebuild_import_cache` cannot repair a stale uid index, so the cold-cache auto-recovery retries the same failure and every scenario fails green-inside"
status: open
caught_in: "0.24.0"
fix_milestone:
caused_by:
---

# import-cache-rebuild-does-not-repair-a-stale-uid-index

## Symptom

Found in nullbound 2026-09-04 during `0.90.3.2/one-shape-for-every-kind` S5. **All 147 scenarios
FAILED** on the runner's `invalid UID … using text path instead` sweep while **every scenario's own
assertions passed** — each report carried its `[SCENARIO] <name> PASS steps=N errors=0`. The verdict
was entirely the engine-noise gate; nothing under test was broken.

56 tracked `.uid` sidecars were absent from the index, including `entity_definition.gd` and
`body_shape.gd` (both landed earlier in the same feature), 17 shaders and 25 test scripts.

## Root cause

`gdk_rebuild_import_cache` re-runs the engine's import pass against the EXISTING `.godot/`. That
mints sidecars for new files but does not rebuild the uid index for tracked files already missing
from it — measured: three runs, including one after deleting `uid_cache.bin` alone, each left the
cache at 1780 entries with the same 56 missing. `rm -rf .godot && make import-cache` repairs it
(1822 entries, 21 s).

`tools/dev/runners/scenario.sh` (~:435-441) makes this worse rather than better. Its cold-cache
auto-recovery is correctly gated — it fires only when the report shows the UID class AND the
scenario itself PASSED AND did not hang — but the remedy it calls is `gdk_rebuild_import_cache`, the
rebuild that cannot repair this state. So the runner detects the condition precisely, applies a
non-remedy, retries once, and re-fails. Every scenario pays the retry.

## Fix

The recovery must escalate: rebuild first, and when the retry reports the SAME uid class, remove
`.godot/` and rebuild once more before the final retry — the difference between a *cold* cache
(rebuild repairs) and a *stale* index (only removal does). A third failure is a real failure and
must stay fast.

Removing `.godot/` is destructive to a local editor's state, so it belongs behind an explicit
verdict line naming what it is about to do, and the escalation must be bounded — never a loop.

A `doctor`-style check is the cheaper companion: count tracked `.uid` sidecars against index
entries and report the shortfall as one verdict line, so an unrepairable tree is a red line before
a 147-scenario sweep rather than after it.

Test: a fixture tree whose index is missing a tracked sidecar — the first rebuild does not repair
it, the escalation does, and a genuinely failing scenario is still not retried.
