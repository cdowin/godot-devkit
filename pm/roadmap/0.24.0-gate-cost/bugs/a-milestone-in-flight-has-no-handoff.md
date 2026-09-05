---
id: 0.24.0/bugs/a-milestone-in-flight-has-no-handoff
milestone: "0.24.0"
name: "`handoff.md` is defined, ruled milestone-only, documented as the cold-start file — and no gate notices a milestone that has none, including this package's own"
status: open
caught_in: "0.24.0"
fix_milestone:
caused_by:
---

# a-milestone-in-flight-has-no-handoff

## Symptom

Found 2026-09-04, resetting context on a long session. This package **defines** the convention:

- `src/godot_devkit/repo/pm/model.py:122` — `HANDOFF_FILE_NAME = 'handoff.md'`
- `model.py:107` — ruled **milestone-only**, explicitly: *"a feature is not a thing that hands off"*
- `repo/pm/guidance/pm-operations.md:24` — *"handoff.md — cold-start only, never what `pm status`
  computes"*

And does not follow it. **Neither `0.24.0-gate-cost` nor `0.23.0-telemetry` had one** until this bug
was filed. The consumer that does follow it is nullbound, which has carried
`pm/roadmap/<milestone>/handoff.md` for milestones.

`model.py:135` explains why nobody noticed: `handoff.md` and `review.md` *"are hand-written and appear
when somebody writes"* them. Nothing scaffolds one, so nothing complains when one is absent.

## Why it matters

A handoff is the only artifact whose entire purpose is to survive the loss of the session that
produced it. `milestone.md` is the SHAPE of the work and `review.md` is a verdict on it; neither is a
pickup. A milestone that runs for days across several agents and ends without one hands the next
reader a tree and a git log.

This is the SECOND time in this milestone that this package has defined a rule, shipped it to
consumers, and not run it on itself — the first being `CLAUDE.md` claiming the hook corpus was
self-hosted while `core.hooksPath` was unset in every checkout of this repo, for two releases
(`0.24.0/self-hosting-has-no-arm-or-verify-target`). The shape is worth naming: **a rule this package
only enforces on consumers is a rule it will drift on.**

## Fix

A `check pm` finding: a milestone at `building` or later with no `handoff.md` is reported. Not at
`planning`/`ready` — there is nothing to hand off before work starts, and a gate that fires on an
empty milestone teaches people to create empty files.

Weigh two things before implementing:

- **Report, not refuse.** This is a tree-shaped observation like D3/D5, not a fact about the input.
  It belongs in the same family and should be a named rule id so a project can disable it — a repo
  whose milestones are one sitting long does not need it.
- **Do not scaffold an empty one.** `pm new milestone` creating a stub would satisfy the gate with a
  file nobody wrote, which is the rubber-stamp failure the review-record rule already refuses
  (`--review-record` naming an EMPTY file fails the gate, deliberately).

Test: a fixture milestone at `building` with no `handoff.md` reports; the same at `planning` does
not; one WITH the file is silent at every state.

## Note

The two consumer trees should be checked when this lands — nullbound has one per active milestone,
trail is unmeasured.
