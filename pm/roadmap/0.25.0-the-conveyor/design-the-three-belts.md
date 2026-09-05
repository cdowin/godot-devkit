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
