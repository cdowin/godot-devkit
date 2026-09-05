---
id: 0.25.0/the-extraction-finishes
milestone: "0.25.0"
name: The extraction finishes — a stock consumer gets a kit that works and describes itself
status: planning
reviewed:
risk: medium
size: m
phase: 1
depends_on: []
consumed_by: []
labels: ["extraction", "defect", "docs", "installables"]
---

# The extraction finishes

**Chris, 2026-09-04:** *"Whatever was broken in 0.1.0 let's fix in 0.2.0. I want to do this ONCE."*

0.1.0 shipped green — 1,430 tests pass — and green is not clean. The extraction left the package
working **for this repo** and broken for a stock one, plus a set of surfaces still describing the half
that left. All of it is measured, none inferred.

## The defect — a stock consumer's `check all` exits 2

`cli.py`'s `KNOWN_GATES` still names **eight removed gates**, and **three of them (`uid`, `tres`,
`props`) are in the DEFAULT roster.** Measured in a scratch repo with no `devkit.toml`:

```
agentic-sdlc: unknown check 'uid' (expected: uid, tres, props, doc, shell, defaults,
repo-hygiene, pm, hooks, rng, tres-comment, unit-disk, test-shape, all)
... exit 2
```

**The error message names the gate it just refused as a known one.** This repo is green only because
its own `devkit.toml` pins `[checks] all = ["doc","pm","shell","hooks"]` — the default path, which is
the path a new adopter takes, is the broken one.

**The real defect is the missing census, not the eight names.** Nothing in the suite asserts that the
declared roster equals the set of modules that actually dispatch, which is exactly why eight phantom
gates survived an extraction that touched every other surface. Prune the roster AND add
`roster == dispatchable` as a test, or the next removal reintroduces this.

## What still describes the half that left

Each verified present, and each visible to a first user:

- **`--help` advertises ~14 verbs that do not exist** — `scene set/rm/rename/add/reparent/connect/
  disconnect/canonicalize`, `scene-diff`, `refs`, `orphans`, `autoloads`, `tiles`. `_usage()` prints the
  same doc on any unknown command, so a typo hands the user a menu of nothing.
- **`src/agentic_sdlc/data/classdb.json`** — a 126 KB Godot ClassDB dump with **zero readers**, sitting
  inside the wheel root, so it ships.
- **`devkit.toml`** keeps `[uid]`, `[tres]`, `[props]` sections and prose about "four of the eight gates
  read `.tscn`/`.tres`".
- **`pyproject.toml`**'s `description` and `keywords` are entirely the other half's.
- **`CLAUDE.md`** hard rule 2 and § Where things live still describe `godot/`, the `.tscn` write verbs
  and the `refs` autoload blind spot.
- **Dead constants** — `RETARGET_FLAG`, and `FIXABLE_CHECKS = frozenset({'uid'})` naming a removed gate.
- **Orphaned fixtures** — `tests/fixtures/kitchen_sink.tscn`, `tilemap.tscn`, no readers.
- **`tests/support/temp_repo()`** has zero callers; it is held alive only by a census that lists it, so
  removing it means updating that census in the same change.

## One that needs a ruling, not a sweep

**`tools/hooks/cc-godot-sandbox.sh`** (51 Godot mentions) is self-hosted here and is one of three in
`HOOKS_WITH_CORPUS`, so `make hooks-self-test` replays a **Godot engine-boot guard in a repo with no
Godot**. That may be right — it is a consumer-facing installable and the kit should test what it ships —
or the hook belongs with the Godot kit. Same question, smaller, for `model.py`'s D8 default of
`version_file = 'project.godot'`: configurable, so not a defect, but a Godot default living in the
agentic half.

**This is the installables' middle tier in miniature** (see `milestone.md`), and answering it here is
worth more than sweeping it: whatever rule settles `cc-godot-sandbox.sh` settles `Makefile.devkit`,
`doctor.sh` and `ci-verify.yml` too.

## Why it belongs in 0.2.0 rather than a 0.1.1

Chris ruled it: do this once. A patch that pruned the roster would ship before the rule deciding where a
Godot-flavoured installable lives, and then the same files get touched twice — once to clean them and
again when the middle tier is settled. The defect is real but it is not urgent: it reaches a **new**
adopter, and there are none yet.

## Risks

1. **Pruning `KNOWN_GATES` preempts the middle-tier question** if done carelessly — the roster is where
   a check from another package would register. Prune to what dispatches TODAY and let the composition
   question change it later; do not design the extension point while removing dead names.
2. **The census test is the deliverable, not the pruning.** Ship the prune without
   `roster == dispatchable` and this recurs on the next removal, with the same eight-phantom shape.
