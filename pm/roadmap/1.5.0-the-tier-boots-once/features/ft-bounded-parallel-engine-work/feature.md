---
id: ft-bounded-parallel-engine-work
kind: feature
milestone: "1.5.0"
name: Bounded parallel engine work
status: done
reviewed: pm/roadmap/1.5.0-the-tier-boots-once/features/ft-bounded-parallel-engine-work/decisions.md
depends_on: []
consumed_by: []
changelog: Scratch imports exclude nested lanes and Godot-ignored trees; resource references use target headers; engine admission prevents competing boots.
---

# Bounded parallel engine work

Import traversal prunes explicit Godot-ignored directories and registered nested worktrees.
The exact manifest preserves installed runtime addons and ordinary nested clones. Optional rsync accelerates copying.
Target resource headers define UID identity. The shared OS lease admits one integration batch or standalone engine boot.

## Ship criterion

All 20 import-copy/interruption regressions pass. UID header regression and four bounded contention/fanout tests pass.
Release review precedes one full regression gate. Publish an immutable wheel.

## Proof budget

Extend the existing import self-test and runner test module. Add one target-header UID matrix test.
No real-engine boot required in this toolkit; consumer adoption proves integration separately.
