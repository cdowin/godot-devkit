---
id: 0.20.0/generic-scans/run-shaped-scans-are-runners
feature: 0.20.0/generic-scans
milestone: "0.20.0"
name: hermetic and warnings scans ship as runners
status: done
owner: developer
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

## Done

done: 539fe9a — `hermetic_run_scan.sh` on `gdk_runners.sh`, C1/C2/C3 ported;
C4 dropped with reason (`gdk_gate_log` bounds the report dir by construction).
`--self-test` 10 cases, each check fired at the hermetic AND the planted shape,
in its own scratch repo; 5 Python cases mutation-prove it goes red. Green on
bash 3.2.57, shellcheck -x clean, PASS on nullbound d3df6e5cb with the runners
installed. `warnings.sh` left to generic-runners S1, which shipped it in
21194b8. The `install.PLANS`/`DESTINATIONS` row is in the tree, uncommitted —
both files were carrying a peer's in-flight edits.
