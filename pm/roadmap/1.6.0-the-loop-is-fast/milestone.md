---
id: "1.6.0"
kind: milestone
name: the loop is fast
status: done
depends_on: []
branch: speed-the-loop-is-fast
mode:
version: 1.6.0
changelog: A competing engine run queues for the lease, and unit, parse and lint reuse a recorded PASS over unchanged tree content.
---

# 1.6.0 — the loop is fast

A second engine run waits for the lease instead of failing with exit 75.
unit, parse and lint file a receipt on PASS, keyed on the tree's content; a repeat run over the same content boots nothing.
The planned stats, connection, capture-focus, and carry-forward features move to version 1.7.0.

## Ship criterion

The queue regression proves a waiter admits after the owner releases. The receipt regression proves prose edits reuse a PASS and worktrees share it.
The release artifact contains both patches and consumers can lock its immutable wheel.

## Risks

A receipt key that misses an input reuses a stale PASS. `GDK_RECEIPTS=0` turns receipts off; `GDK_ENGINE_GATE_WAIT=0` restores fail-fast.
