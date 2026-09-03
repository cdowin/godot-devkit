---
id: 0.22.0/bugs/installed-runners-lack-consumer-ergonomics
milestone: "0.22.0"
name: The installed runners lack four consumer ergonomics the ported originals had
status: open
caught_in: "0.22.0"
fix_milestone: "0.22.0"
---

# installed-runners-lack-consumer-ergonomics

<!-- A bug lives in the milestone that will FIX it. `caught_in:` keeps the
     provenance; `fix_milestone:` names the decision, and moving the file into
     that milestone's bugs/ is that decision made real. When a milestone is
     retired, `pm retire` reports any bug still open under it. -->

## Symptom

Diffed at adoption (2026-09-02) against the consumer copies they replaced: (1) no `require-godot`
fail-fast — a missing engine fails late with an unrelated error; (2) `smoke` lost the per-scenario
`steps=N errors=N` line (the runner prints only `SUMMARY: N passed`); (3) the failure path lost the
`↳ drill in: make scenario NAME=<failed>` hint; (4) `capture` dropped its REGION/MAP arguments
(recovered consumer-side by exporting them as env off the standard target).

## Root cause

Port scope stopped at the verdict line. Each is small; (1) and (3) are the ones an agent hits first.

## Fix

(5) **Concurrent gate runs clobber one log slot.** `.gate-reports/<gate>.log` is per gate, so two agents running `make unit` in one tree overwrite each other's transcript (seen 2026-09-02: a peer's run replaced the orchestrator's `unit.log` mid-read). The slot should carry a run id (PID or timestamp) with `<gate>.log` as a symlink/copy of the latest, and the verdict line names the exact file.
