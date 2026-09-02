---
id: 0.19.0/install-runners/gate-log-and-verdict
feature: 0.19.0/install-runners
milestone: "0.19.0"
name: Every gate prints one verdict line and names its full log
status: review
owner: developer
depends_on: []
---

# Every gate prints one verdict line and names its full log

## Goal

A consumer gate prints one verdict line that names its full log, and `VERBOSE=1` streams.

## Observable

`make parse` in an installed consumer prints exactly one line on success
(`[PARSE] PASS (… ) — full log: .gate-reports/parse.log`) and the engine's error lines plus the
verdict on failure; the log slot is per gate and cleared per run (bounded by construction).

## Port from nullbound `tools/dev/_common.sh` (`271baf4ec`)

`nullbound_gate_log`, `nullbound_gate_capture`, `nullbound_gate_publish`, `nullbound_gate_verdict`
→ `gdk_gate_log/_capture/_publish/_verdict`. The `.gate-reports/` dir name is a documented
variable with that default. `shellcheck` clean; a `--self-test` that runs a fake gate through
capture → verdict and asserts the one-line shape.

## Verification

`make test` (a Python test drives `bash installables/gdk_runners.sh --self-test`), `make gates`.

## Commit prefix

`feat(0.19.0/install-runners/S1):`

## Size

s

## Done

done: 572ff8b — `gdk_runners.sh`: gate_log/_capture/_publish/_verdict + the
sandbox/bounded block S3 needs; `GDK_GATE_REPORT_DIR`, `GDK_LOG_CAP_BYTES`,
`GDK_TIMEOUT_KILL_AFTER`, `GDK_SANDBOX_DIRNAME` documented with defaults.
`--self-test` 18 cases (mutation-proven red); `tests/test_runners_installable.py`
10 passed; shellcheck -x clean on bash 3.2.
