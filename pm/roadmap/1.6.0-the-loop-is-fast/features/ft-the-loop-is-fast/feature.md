---
id: ft-the-loop-is-fast
kind: feature
milestone: "1.6.0"
name: the loop is fast
status: done
reviewed: pm/roadmap/1.6.0-the-loop-is-fast/features/ft-the-loop-is-fast/decisions.md
depends_on: []
consumed_by: []
changelog: The engine gate waits instead of exiting 75; unit, parse and lint file content-keyed proof receipts shared by every worktree.
---

# the loop is fast

The engine gate queues: a competing engine run waits on the shared lease, bounded by `GDK_ENGINE_GATE_WAIT` (#41).
unit, parse and lint record a proof receipt on PASS in the git common dir. The key is the tier, its arguments, the engine binary and the tree's content minus prose and the PM tree (#42).

## Ship criterion

The queue and receipt regressions pass. The full pytest suite and `make check` pass. Publish an immutable wheel.

## Proof budget

  cases: 2
  tier: pytest, stub engine
  lands in: tests/test_runners_installable.py
  what already covers this: the lease contention tests cover refusal; nothing covered waiting or reuse.
