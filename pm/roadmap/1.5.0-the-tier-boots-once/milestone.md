---
id: "1.5.0"
kind: milestone
name: Bounded parallel engine work
status: packaging
depends_on: []
branch: milestone/1.5.0-bounded-parallel-engine-work
mode:
version: 1.5.0
changelog: Import copies stay bounded across lanes, target resource headers define identity, and shared engine admission prevents competing boots.
---

# 1.5.0 — Bounded parallel engine work

Import inputs remain constant as parallel checkouts grow. Each checkout owns mutable caches.
Target resource headers define UID identity. One host lease admits integration fanout or independent engine boots.
The planned stats, connection, capture-focus, and prior carry-forward features move to version 1.6.0.

## Ship criterion

Import growth, interruption, addon preservation, and fallback regressions pass. Contention tests refuse competitors and admit descendants.
The release artifact contains all patches and consumers can lock its immutable wheel.

## Risks

Copy time remains above the five-second target. Standalone runners acquire admission per boot; integration holds its entire batch.
