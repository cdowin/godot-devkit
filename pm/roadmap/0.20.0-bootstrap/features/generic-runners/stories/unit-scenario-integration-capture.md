---
id: 0.20.0/generic-runners/unit-scenario-integration-capture
feature: 0.20.0/generic-runners
milestone: "0.20.0"
name: GUT unit, scenario, integration and capture run through the installed runners
status: done
owner: developer
depends_on: []
---

# GUT unit, scenario, integration and capture run through the installed runners

## Goal
`unit.sh` (GUT, `SYS=` slicing, the `N/N scripts loaded` silent-skip guard), `scenario.sh`, `integration.sh` (parallel per-process), `capture.sh` are installables.
## Port
nullbound `tools/dev/runners/unit.sh|scenario.sh|integration.sh|capture.sh` at `d3df6e5cb`. Gotchas: the silent-skip guard is the load-bearing line (a parse-failed test file must still fail the run); the scenario report quarantine paths become `GDK_*` defaults; `boot_to_hub` (the smoke scenario name) is a consumer variable.
## Verification
`make test`; each runner `--help` + `--self-test` on argument handling and the coverage-count parser against a fixture log.
## Commit prefix
`feat(0.20.0/generic-runners/S2):`
## Size
m
## Done
`unit.sh`, `scenario.sh`, `integration.sh`, `capture.sh` ship on `gdk_runners.sh` at
`tools/dev/runners/`. The silent-skip guard survived whole: the skip belt plus the disk-vs-`Totals
→ Scripts` count, and a transcript with no totals block is exit 2, never a pass. Report quarantine,
retention, the noise allowlist and `GDK_SMOKE_SCENARIO` (fed by `integration.sh --smoke`) are all
`GDK_*` defaults. Self-tests: unit 15, scenario 16, integration 12, capture 10 cases; no Godot boots.
