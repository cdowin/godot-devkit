---
id: 0.19.0/install-runners/devkit-make-targets-are-quiet
feature: 0.19.0/install-runners
milestone: "0.19.0"
name: The devkit's own make targets print one verdict line and name their log
status: review
owner: developer
depends_on: []
---

# The devkit's own make targets print one verdict line and name their log

<!-- What is observable when this ships. A story is an observation, not a task. -->

## Acceptance criteria

## Out of scope

## Done

done: 4043693 — `test`/`gates`/`fuzz`/`matrix`/`smoke` route through the shipped
`gdk_gate_capture` + `gdk_gate_verdict`, sourced from `src/`. Default output:
gates 7->1, test 14->1, fuzz 3->1, matrix 69->1, smoke 28->1, milestone 104->3.
Red still prints the failing lines verbatim; `VERBOSE=1` streams (exported, so
both spellings work). `tests/test_makefile_gates.py` — 6 cases, the census
proven red against an appended loud target. CLAUDE.md states the convention.
