# The three belts — one per grain, each with its own loop

**Chris, 2026-09-04:**

> *"This is like code -> lint -> unit -> LOCAL integration (on just your system) -> review. Think about
> what a development SDLC looks like. There are probably three layers, one each for milestone, feature,
> and story ... with loops."*

That is the design. It also diagnoses today's 31-minute failure in one sentence, which is how you know
it is the right cut: **an agent doing STORY-layer work verified it at MILESTONE-layer scope.**

## The shape

**The grain vocabulary already has three layers, and 0.24.0 made them share one set of words.** The
belts are those same three, and each one's job is to widen verification by exactly one step.

```
MILESTONE  ┌────────────────────────────────────────────────────────┐
           │  all features done → cross-cutting review → LAND        │
           │  → FULL GATE (last) → accepted → packaging → done → tag │
           │         ▲                                               │
FEATURE    │  ┌──────┴─────────────────────────────────────┐         │
           │  │  all stories reviewing → simplifier →      │         │
           │  │  reviewer → LAND → review record → done    │         │
           │  │         ▲                                  │         │
STORY      │  │  ┌──────┴───────────────────────────────┐  │         │
           │  │  │  claim → code → lint → unit(slice) → │  │         │
           │  │  │  local integration(covers) → close   │  │         │
           │  │  │         └──── loop, seconds ─────┘   │  │         │
           │  │  └──────────────────────────────────────┘  │         │
           │  └────────────────────────────────────────────┘         │
           └────────────────────────────────────────────────────────┘
```

## What each belt verifies, and why the width is the whole point

| belt | runs | verifies | cost target |
|---|---|---|---|
| **story** | dozens of times per story | only what this edit touched — the file's lint, the system's unit slice, the scenarios declaring they cover it | **seconds** |
| **feature** | once per feature | the feature's whole commit range, cross-story: duplication, functions grown across edits, drift | tens of seconds |
| **milestone** | once | everything, every interpreter | minutes, and **paid once** |

**Measured, and it is why this is not cosmetic:** one suite is 154 s whole and 0.9 s for a single module
— **170x**. Eleven story-layer fixes verified at milestone scope cost 31 minutes; the same five modules
re-checked at story scope cost **13 seconds**.

## The loops, which are the part prose keeps losing

Each belt loops **back into the belt below it**, and that is what makes findings cheap:

- **Story loop** — a failing narrow check sends you back to the edit. No other belt runs.
- **Feature loop** — the reviewer finds something. **≤10 lines lands inline; anything larger opens a
  STORY**, which re-enters the story belt with its own tight loop. The feature belt does not re-run
  until that story reaches `reviewing`.
- **Milestone loop** — the cross-cutting review finds something; same rule, one level up. **And the full
  gate re-runs only after every finding is landed** — which is exactly the ordering this package got
  wrong three times, now structural rather than remembered.

**A belt never runs a belt above it.** That is the single rule that would have prevented today's cost.

## Entry conditions are the gates between belts

A belt refuses to start until the one below it is finished, and each condition is already machine-checkable:

- story → feature: **every story at `reviewing`** (`pm status` says so).
- feature → milestone: **every feature `done`** with a non-empty review record (`check pm` D1 already
  asserts the pointer resolves).
- milestone → tag: **every finding at a disposition other than `open`** — `verdict.parse` already
  returns those, which is why `review-landed` was the cheapest first slice.

## What this replaces

The `change` pair filed earlier is the **story belt**, and it was the right instinct at the wrong
altitude — a pair is what one belt needs, not what the SDLC needs. `release` is the tail of the
**milestone belt**. `adopt` is a fourth thing and stays separate: it is not a grain, it is an operation
on the toolchain, and it borrows the story belt's narrow-verification idea without having a grain to
close.

## What is NOT yet designed

**Which command is "narrow" is per-project, and nothing declares it.** Two consumers invented the
mechanism independently — one slices unit tests by system, one picks integration scenarios from a
`## covers:` header — and neither is discoverable by a dispatch. The story belt needs that to come from
config, the way the release steps do. **This is the first thing to solve**, because it is what every
other layer's economics rest on.

---

# Designing the two missing pieces

Both were named as gaps above. Chris, 2026-09-04: *"Can we design this? … I want to do this ONCE."*

## 1 — Declaring which command is NARROW

**The question a belt has to answer:** *given this set of changed paths, what verifies them?*

Two consumers already answer it, differently, and neither is discoverable:

- **Forward** — config maps a changed source path to a command. One tree slices unit tests by system
  directory (`unit SYS=<x>`).
- **Reverse** — the TEST declares what it covers and changed paths select tests. The same tree reads a
  `## covers:` header out of integration scenarios.

**Both are right, for different tiers**, and the design must carry both rather than pick. Forward suits
unit tests, where the mapping is structural (this directory's tests cover this directory). Reverse suits
integration, where only the test knows what it exercises and no path rule could infer it.

```toml
[verify]
wide = "make check test"           # the close. One command. Always defined.

[[verify.narrow]]                  # FORWARD: glob with a named capture
paths = "systems/<sys>/**"
run   = "make unit SYS=<sys>"

[[verify.narrow]]
paths = "tests/test_<name>.py"
run   = "pytest tests/test_<name>.py"

[[verify.narrow]]                  # REVERSE: the test declares its own coverage
declares = "## covers:"
scan     = "tests/integration/**"
run      = "make scenario NAME=<stem>"
```

**Three properties that are not optional, each because leaving it out produces a silent lie:**

- **Captures deduplicate.** Five files under `systems/combat/` produce ONE `unit SYS=combat`, not five.
  Without this the narrow path re-runs the same slice per file and stops being narrow.
- **A miss is LOUD and falls back to wide.** If no rule matches a changed path, the verifier says which
  path matched nothing and runs the wide command. **A narrow verifier that matches nothing and exits 0
  is worse than no verifier** — it reports success for work it never checked. This is the single most
  dangerous failure in the whole design.
- **The declaration is checkable.** A rule whose glob matches no tracked file, or whose `run` names a
  target that does not exist, is a finding — the same posture as a stale allowlist entry. A rule set
  nobody validates rots into a set that quietly matches nothing.

**And it reports the ratio.** With `every-gate-reports-its-cost` recording durations, `verify --changed`
prints narrow-vs-wide with real numbers. A 1.2x ratio does not justify a two-command dispatch; the
measured 170x does. **The ratio is what makes the rule obvious to a dispatch author instead of advice
they have to trust.**

## 2 — The entry conditions, as verbs rather than prose

Each belt refuses to start until the belt below is finished. Every one of these is already derivable —
what is missing is a verb that answers it with an exit code, so a step machine can gate on it and a
human cannot mis-read it.

| gate | question | already available from |
|---|---|---|
| story → feature | is every story at `reviewing`? | `pm status` |
| feature → milestone | is every feature `done`, each with a **non-empty** review record? | `check pm` D1 asserts the pointer resolves |
| milestone → tag | is every finding at a disposition other than `open`? | `verdict.parse` returns dispositions |

```
pm ready-for feature <id>     # exit 0 ready · 1 not, and says which children block · 2 usage
pm ready-for milestone <id>
pm ready-for tag <id>
```

**Exit 1 must NAME the blockers, not count them.** "3 stories not at reviewing" sends someone to `pm
status` to find out which; "`s/foo` is `building`, `s/bar` is `ready`" is actionable. The whole point of
a machine-checkable gate is that the machine already knows the answer — printing a tally throws it away.

**`ready-for tag` is the one that would have caught this package's own worst habit**: the release gate
running before the review that changes the tree. It is the cheapest of the three to build, because
`verdict.parse` already returns what it needs, and it is the first slice for exactly that reason.
