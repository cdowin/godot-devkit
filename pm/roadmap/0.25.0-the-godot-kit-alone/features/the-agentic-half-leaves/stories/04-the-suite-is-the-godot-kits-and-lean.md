---
id: 0.25.0/the-agentic-half-leaves/04-the-suite-is-the-godot-kits-and-lean
feature: 0.25.0/the-agentic-half-leaves
milestone: "0.25.0"
name: The tests that leave go with the family, and what remains bites at the cheapest tier
status: done
owner:
depends_on: []
---

# The tests that leave go with the family, and what remains bites at the cheapest tier

## Acceptance criteria

- The thirteen modules that proved the repo family (`test_pm_*`, `test_check_hooks`, `test_ci_workflows`, `test_consumer_independence`'s repo half, `test_fresh_project`, `test_gates_extra`, `test_hooks_payloads`' shared-hook half, `test_init_verb`, `test_install`, `test_makefile_include`, `test_pm_guidance`, `test_verdict`, `test_replay_migration` where it replays pm) leave in story 01's commit, each named there.
- What remains bites: a case gates a Godot write verb, a scene gate, the runners installer, or one of rule 4's two sins; a case proving a rule at a second altitude goes; a spawn stays only where the thing under test is a process. Every deletion or merge names its subsumer or the reason it proved nothing, in the commit.
- A deliberately-broken probe per Godot gate and per write verb (`scene` edits, `tiles`, `refs`, `install-runners`) reddens the reduced suite; recorded in the commit.
- Measured before and after: collected cases, unit and test tier wall time, test-to-source statements; `[tests] budget` and `[tests] cases` declared just above the result; `check budget` runs in `make milestone`.
- The `shell` mark stays derived; `unit` is the story rung and `test` the feature rung.

## How this is proven

| criterion | tier | the case that proves it | existing? |
|---|---|---|---|
| 1 | unit | the census after the pass, and the ceilings in devkit.toml | the tiers' own verdict lines; check budget |
| 2 | n/a | the probe table | the commit message |

## Out of scope

A new test without a named gap. The default is that a new test is not warranted.

## Close

done: 2f956ea — closed once at 5901e99 (679 → 576, the pass that cut what proved nothing), then reopened to apply rule 9's other half: prove it ONCE. 576 → 196 cases (pyunit slice 114 → 40), `make test` 48.5s → 27.5s, `make pyunit` 2.31s → 1.10s, test-to-source 1.10 → 0.65. 396 test functions merge into 111, and the commit names every cut by the mechanism that subsumes it — a shared case helper, a refusal matrix over the source's branch table, config refusals dropped to function altitude, and a pass case folded into its census case.

Sixteen probes redden the reduced suite: 5901e99's fifteen re-run against the 196-case tree, plus one the pass itself found. `WalkHasNoLength` went with test_boundaries' small classes and nothing took it — with `Walk.__len__`'s refusal deleted, all 195 cases stayed green, which is rule 4's first sin left unguarded. The case is restored at the cheapest tier that holds it (a constructor and a `len()`, no temp tree, no process) and is the one case this pass adds rather than merges. `src/` is byte-identical after every probe; none is committed.

`[tests] budget`/`cases` re-declared against this result — `{ pyunit = 2, test = 35 }` and `{ pyunit = 44, test = 215 }`, ten percent above 1.10s/27.55s and 40/196 — and graded by `check budget` off the ledger's census. The old 3/55 and 125/635 were the 576-case suite's; a ceiling of 635 over a census of 196 grades nothing. The `shell` mark stays derived: 156 marked / 40 unmarked, the same one-in-five as before the pass.
