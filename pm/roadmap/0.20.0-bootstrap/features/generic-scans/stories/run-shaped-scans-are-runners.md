---
id: 0.20.0/generic-scans/run-shaped-scans-are-runners
feature: 0.20.0/generic-scans
milestone: "0.20.0"
name: hermetic and warnings scans ship as runners
status: todo
owner:
depends_on: []
---

# hermetic and warnings scans ship as runners

## Goal
`hermetic_run_scan.sh` (a headless run's sandbox HOME self-destructs; only declared caches persist) ships as an installable runner with `--self-test`, beside `warnings.sh` from `generic-runners` S1.
## Verification
`make test`; `--self-test` green on bash 3.2.
## Commit prefix
`feat(0.20.0/generic-scans/S2):`
## Size
s
