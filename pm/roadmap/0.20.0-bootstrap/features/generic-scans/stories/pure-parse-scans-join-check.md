---
id: 0.20.0/generic-scans/pure-parse-scans-join-check
feature: 0.20.0/generic-scans
milestone: "0.20.0"
name: rng, tres-comment, unit-disk and test-shape scans become check gates
status: todo
owner:
depends_on: []
---

# rng, tres-comment, unit-disk and test-shape scans become check gates

## Goal
`check rng`, `check tres-comment`, `check unit-disk`, `check test-shape` exist, config-driven.
## Port
nullbound `tools/dev/checks/rng_scan.sh` + `rng_allowlist.txt`, `tres_comment_scan.sh`, `unit_disk_scan.sh`, `test_shape_scan.sh` + `test_shape_allowlist.txt` → Python under `repo/checks/`, allowlists as `devkit.toml` sections. Same exit semantics as the existing gates (0 clean / 1 findings / 2 config).
## Verification
`make test` with fixtures reproducing each scan's block + allow cases; `make gates`.
## Commit prefix
`feat(0.20.0/generic-scans/S1):`
## Size
m
