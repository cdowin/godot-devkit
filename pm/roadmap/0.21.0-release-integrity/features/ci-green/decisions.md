# Decisions — ci-green

## R1 — 2026-09-03 — review record

- **Evidence:** `verify.yml` red on v0.19.0 and v0.20.0; the v0.20.0 job log ends
  `[MATRIX] FAIL on 3.11 3.12 3.13 3.14`. Reproduced here: under `make test` every makefile test's
  sub-make announced `Entering directory` (MAKELEVEL inherited from the recipe); under bare pytest
  the same tests passed. Six shellcheck findings across three installables surfaced the moment
  shellcheck was on PATH, as it is on `ubuntu-latest`.
- **Resolved:** the two `make()` test helpers drop `MAKELEVEL`/`MAKEFLAGS`/`MFLAGS`; the hooks'
  `is_agent_context` lost its never-passed parameter (SC2120/SC2119); the hermetic scan's
  indirect-invocation directives also spell SC2317 (shellcheck < 0.10's code for SC2329).
- **Proof, this container:** `make test` under make 1079 passed with only the four
  chmod-unwritable tests failing as root; as a non-root user the matrix is 1084/1084 on 3.11, 3.12,
  3.13 and 3.14; `make smoke` with no consumer checkout exits 0 with its SKIPPED line; `make gates`
  PASS with shellcheck present.
- **Known, not fixed here:** the five `[shell] roots` config tests assert exit 2 but see SKIP on a
  host without shellcheck (pre-existing); the consumer smoke against nullbound is red once
  shellcheck is present because nullbound's own scripts carry findings (38 scripts) — a nullbound
  hygiene item its bootstrap hook already documents.
