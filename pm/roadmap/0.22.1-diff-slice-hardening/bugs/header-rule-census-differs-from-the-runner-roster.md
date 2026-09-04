---
id: 0.22.1/bugs/header-rule-census-differs-from-the-runner-roster
milestone: "0.22.1"
name: check test-shape scans git ls-files tests/integration minus infra basenames (160 on nullbound) while integration.sh discovers via find minus
status: fixed
caught_in: "0.22.1"
fix_milestone:
---

# header-rule-census-differs-from-the-runner-roster

<!-- A bug lives in the milestone that will FIX it. `caught_in:` keeps the
     provenance; `fix_milestone:` names the decision, and moving the file into
     that milestone's bugs/ is that decision made real. When a milestone is
     retired, `pm retire` reports any bug still open under it. -->

## Symptom

MINOR — check test-shape scans git ls-files tests/integration minus infra basenames (160 on nullbound) while integration.sh discovers via find minus */support/* and _capture$ (137) — the opt-in header rule demands Boots-because/covers on 22 *_capture.gd tools and a support stub that --diff can never slice to. One roster, owned by one place, read by both. From the v0.22.0 release review.

## Root cause

Two censuses of one question. The gate derived "the scenarios" from `git ls-files -- <scenario_root>` minus `[test_shape] infra`; the runner derives them from `find` minus `*/support/*`, `GDK_CAPTURE_SUFFIX_RE` (less `GDK_CAPTURE_GATE_RE`) and `GDK_INTEGRATION_INFRA_RE`. The runner's inputs live in its own config block and the consumer's exported env — neither is readable from `devkit.toml` — so any census the gate computes on its own is a second answer by construction, and it drifts the moment a consumer edits the runner or exports a keep-list.

## Fix

fixed: c0dc460 — the roster lives in the runner (`integration.sh --list`: `discover_gate_files`, one repo-relative path per line, sorted, booting nothing, EMPTY = exit 1) and the gate asks it (`[test_shape] runner`, stock `tools/dev/runners/integration.sh`). Why that home: the runner is the thing that boots the set and already owns every input to the rule, so "what the runner would run" has exactly one authoritative answer — the runner's — and the gate stating it a second time is this bug. Refusals: no runner there → exit 2 naming the path + `install-runners`; a runner older than `--list` → exit 2 naming `install-runners --force`; a roster of nothing → FAIL; a hostile `runner` value → ConfigError. STALE = "not a scenario the runner boots". CHECK 1/2 keep the tracked census (the cap prices tier weight, booted or not). Consumer adoption: `install-runners --force`, drop the STALE ledger lines (nullbound: 23 bare / 13 under its keep-list). Red first: 6 gate cases, 3 e2e, 2 corpus MISSes (91 → 94).
