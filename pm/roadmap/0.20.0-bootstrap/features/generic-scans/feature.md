---
id: 0.20.0/generic-scans
milestone: "0.20.0"
name: The project-agnostic scans move into the devkit
status: done
reviewed: pm/roadmap/0.20.0-bootstrap/features/generic-scans//decisions.md
phase: 1
depends_on: ["0.19.0/install-runners"]
consumed_by: ["0.20.0/makefile-include", "0.20.0/init-verb"]
---

# The project-agnostic scans move into the devkit

What it makes true: a scan that reads only files (no engine boot) is a devkit `check` gate in
Python; a scan that needs a run ships as a runner. Candidates measured on nullbound
(`tools/dev/checks/`, 27 scripts): pure-parse — `rng_scan.sh` (+ allowlist), `tres_comment_scan.sh`,
`unit_disk_scan.sh`, `test_shape_scan.sh` (+ allowlist); run-shaped — `hermetic_run_scan.sh`,
`warnings.sh`. The other 19 (`game_shell_scan`, `z_layer_scan`, `capability_scan`, …) are
nullbound's architecture and stay.

## Existing-construct audit

`check` already hosts `uid`, `tres`, `props`, `defaults`, `pm`, `doc`, `shell` — the four
pure-parse scans are more of the same, config-driven (`[rng] allowlist`, `[test_shape] …` in
`devkit.toml`) so a consumer keeps its exceptions without forking the scan.

## Ship criterion

The six scans exist once, in the devkit; both consumers delete their copies; every consumer
exception that was in an allowlist file is now in `devkit.toml`.
