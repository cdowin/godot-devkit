---
id: 0.25.0/the-release-is-a-conveyor
milestone: "0.25.0"
name: The release protocol is a resumable step machine, not prose to follow correctly
status: planning
reviewed:
risk: high
size: xl
phase: 1
depends_on: []
consumed_by: []
labels: ["release", "sdlc", "installable", "config", "subtraction"]
---

# The release protocol is a resumable step machine, not prose to follow correctly

**Chris, 2026-09-04, after the release protocol got its own ordering wrong for the third time:**

> *"Can we do even better than skills and CLAUDE.md? Can we just encode the steps literally in code? We
> could even make it configurable about which ones to run vs skip etc for a given project. Basically, can
> we just create the conveyor belt? Move to next, move to next, move to next. Then the bot never has to
> infer anything."*

## Why — three incidents, one mistake

The release gate has been coupled to, or ordered against, the wrong thing three separate times:

1. `bugs/the-release-gate-cannot-run-before-the-close-it-gates` — D6 refused a `building` milestone whose
   features were all `done`, so the gate demanded the ship decision it exists to inform.
2. `make smoke` made two consumer checkouts a precondition for this package's tag — CLAUDE.md rule 8 and
   `bugs/consumer-names-and-provenance-in-code`, the latter filed 2026-09-02 and **shipped past in 0.23.0**.
3. **0.24.0's own release**: `make milestone` was run BEFORE the reviewer, twice (3:00 and 3:17), and both
   runs were void the moment the review asked for fixes. The gate answered for a tree nobody was shipping.

Each was fixed in prose. Prose is instructions someone must follow correctly, and following it correctly
is inference. **The rule the third incident produced — *when a gate and a judgement both bear on one
decision, the judgement runs first and the gate answers for its result* — is exactly the kind of thing a
step list expresses structurally and a paragraph does not.**

## What already exists, so this is mostly assembly

Three of the four pieces are shipped:

- **A configurable roster** — `devkit.toml [checks] all` and `[gates] extra`, already per-project.
- **A state machine** — `planning → ready → building → reviewing → accepted → packaging → done`.
- **Machine-readable judgement artifacts** — every review record ends in `| id | severity | disposition |`
  and `verdict.parse` already returns them structured, N passes per record since 0.24.0.

Missing: **a driver that walks the steps and refuses to advance.**

## The shape

`godot-devkit release <version>` — a resumable step machine over a config'd list:

```toml
[release]
steps = ["tree-clean", "on-milestone-branch", "main-merged",
         "changelog-unreleased-nonempty", "review-landed",
         "version-sync", "readme-pins", "features-done", "milestone-reviewing",
         "gate", "milestone-accepted", "changelog-retitle",
         "milestone-packaging", "milestone-done",
         "push-branch", "pr-open", "ci-green", "merge", "tag", "prove-artifact"]
```

Each step declares **`check()`** (is this already true?), **`do()`** (make it true, or state precisely what
a human must do), **`verify()`** (prove it took). Resumability falls out: re-run after fixing and it skips
what is already true. **The position lives on disk, not in an operator's head** — which is what makes it
survive a context clear, an interruption, or a handoff.

### Three kinds of step, and the honest limit

- **Automatic** — `version-sync`, `changelog-retitle`, `tag`. Code does it; nothing is inferred.
- **Gate** — run a command, require exit 0.
- **Judgement** — the review, the merge, the semver call. **Code cannot perform these.** It can refuse to
  advance until the ARTIFACT of judgement exists.

That third kind is where all three incidents lived, and it is already checkable: `review-landed` passes
only when a review record carries a verdict block with **zero findings at `disposition: open`**. On 0.24.0
the reviewer filed M1, M2 and m1–m4 as `open`, so the conveyor would have **refused to run `gate`** and the
ordering error becomes structurally impossible rather than a thing to remember.

## Chris's two rulings, both settled 2026-09-04

- **Steps are skippable, and a skip is RECORDED.** `--skip <step> --reason "…"` writes the deviation to the
  ledger. Deviation stays possible; *invisible* deviation does not. A protocol nobody can deviate from gets
  worked around, and a worked-around protocol teaches nothing.
- **The docs are GENERATED from the step list**, and shipped the way everything else is:
  > *"The docs is kind of like the install verbs for agents and skills. You get devkit, write your config,
  > and install the sdlc, install the agents, install the skills."*

  So **`install-sdlc` joins `install-agents` / `install-skills` / `install-hooks` / `install-runners` /
  `install-ci`**, and a consumer's SDLC document is rendered from *their* `[release] steps`. It cannot drift
  from what actually runs — which is the exact failure this milestone fixed by hand in `SDLC.md` and
  `.claude/skills/release/SKILL.md`, in two places, after they disagreed with each other and with the code.

## Scope

| Thing | Action | Purpose |
|---|---|---|
| a `release` verb + step registry | NEW | the driver; one module per step kind |
| `devkit.toml [release]` | NEW | the step list, per project, with a shipped default |
| run state | NEW | on-disk position, so the run is resumable and inspectable |
| `install-sdlc` | NEW | renders the SDLC doc from the step list |
| `.claude/skills/release/SKILL.md` | SHRINK | becomes "run this verb", not a protocol to follow |
| `SDLC.md` § Close protocol | GENERATED | stops being hand-maintained prose that drifts |

## A second conveyor: `adopt`

Chris, 2026-09-04, on what a pin bump actually costs a consumer:

> *"Pinning 24 should be simple. Upgrade the pin, inspect what new install verbs came in, decide what to
> take, update/check configs, lint (to make sure the pm tree is still good against the new version) and
> go. What am I missing?"*

**Almost nothing — the list is right. What is missing is that nothing scopes verification to the
operation.** Measured on the live consumers: this package's entire `check all` is **2.6 s** and
`check pm` is **0.3 s**, while a consumer's `make check` also runs its OWN gates — twenty of them in one
tree — and that is where the minutes go. Those gates verify the CONSUMER'S code against the CONSUMER'S
rules; **a version bump here cannot change their verdict.** Running them during adoption re-verifies the
game, not the adoption.

`make check` is one gate answering one question — *is everything fine?* — for every operation, so
adoption, a one-line edit and a release all pay the price of the most expensive thing anyone might need.
That is the same shape as the ordering incidents above: one blunt instrument standing in for several
scoped ones.

**So `adopt` is a step list too**, and its postconditions are the operation's, not the project's:

```toml
[adopt]
steps = ["pin-bumped", "installables-diffed", "installable-decisions-recorded",
         "config-updated", "hooks-self-test", "runner-targets-resolve",
         "checks-pass", "pm-validates"]
```

Two steps in there are ones a human list keeps forgetting, and both have bitten:

- **`hooks-self-test`** — `install-hooks` rewrites guard scripts, and a guard that fails OPEN is not
  there. This package has already shipped a hook that was installed, executable, and stopping nothing;
  a config diff cannot show that.
- **`runner-targets-resolve`** — `install-runners --force` rewrites `Makefile.devkit`, which defines the
  targets every later gate runs through. Broken there, every subsequent gate fails for the wrong reason
  and the operator debugs the wrong thing.

**`checks-pass` means THIS package's checks, not the consumer's whole gate set** — that is the
subtraction. On the numbers above the scoped set is seconds rather than minutes, and the consumer's own
gates run when the consumer changes its own code, which is what they are for.

## The first slice, and why it is that one

**`review-landed` then `gate`, in that order, with the disposition check.** It needs no new parsing —
`verdict.parse` already returns dispositions — and that single ordered pair encodes the lesson of all three
incidents. Everything else is additive once the driver exists.

## Risks

1. **Over-encoding.** Not every instruction is a step. The test: a step must have a checkable
   postcondition. If it does not, it is guidance and belongs in the generated doc, not in the list.
2. **A second home for the protocol** — the failure this feature exists to end. Mitigated only if the docs
   are genuinely generated; a hand-written doc *describing* the steps recreates the drift immediately.
3. **A conveyor that is always skipped is worse than none**, because it looks like control. If the skip
   ledger shows the same step skipped every release, that step is wrong and the feature has to say so.
