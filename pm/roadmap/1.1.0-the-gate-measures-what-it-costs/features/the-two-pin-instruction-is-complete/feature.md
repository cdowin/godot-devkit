---
id: 1.1.0/the-two-pin-instruction-is-complete
milestone: "1.1.0"
name: The two-pin install produces a working consumer, not a green one
status: done
reviewed: docs/reviews/2026-09-12-1.1.0-the-two-pin-instruction-is-complete.md
phase:
depends_on: []
consumed_by: []
changelog: README two-pin install names the pm init step and separates fresh-repo from bumping-consumer paths.
---

# The two-pin install produces a working consumer, not a green one

**The finding.** README § "Install — two pins" is the entry point every Godot consumer reads,
because this is the Godot kit and that is the section named "Install". It says: set two pins,
then

```sh
uvx … agentic-sdlc install-gates    # Makefile.devkit
uvx … godot-devkit install-runners  # Makefile.tiers + runners
```

```toml
[gates]
extra = ["godot-check"]
```

Follow it exactly on a repo that has a PM tree and you get a green `make check` over a PM CLI
that refuses every work-moving verb, because `[pm.states.*]` has no default behind it and nothing
on this path mentions it. That is what happened on NullBound, 2026-09-06 — the adopting agent
followed this section as the authoritative install path (reasonably: it is a Godot consumer and
this is the Godot kit's install section), reported the adoption complete, and the tree's `pm` was
dead until a human asked about the conveyor.

agentic-sdlc's own README *does* say "re-run `pm init` once" under *Adopting a bump*. The agent
read that text and treated it as background, because **this** section presented itself as the
complete two-pin instruction. It is complete for a repo with no tree. It is silent for one with.

**The adjacent half.** That same README section is what a consumer reads to learn what the two
packages are FOR. It describes agentic-sdlc as "the gate framework and the SDLC (`check`,
`precommit`, `milestone`, hooks, CI, the PM tree, the release belts)" — a parts list. Nothing says
the SDLC has a ladder, that the ladder is declared in `[verify]`, or that a consumer has to
declare its own flow before any of it runs. A reader optimising for "what do I type" gets two
commands and one key.

## Ship criterion

The two-pin install section names the third step for a consumer with a PM tree — `agentic-sdlc pm
init` (or `adopt`), and `pm vocabulary` to read back what it wrote — and says in one sentence that
the flow has no default, so a repo that skips it has a working gate set and a dead PM CLI. The
section distinguishes the fresh-repo path from the bumping-consumer path, because they are
different and today only one is written down.

## Proof budget

  cases: 1
  tier: the existing README/doc consistency case — every command a README shows is a command the
    packages route
  lands in: `tests/test_boundaries.py` or the doc-consistency module, wherever the README's
    command claims are already asserted
  what already covers this: the install commands are correct and presumably asserted; nothing can
    assert that a documented sequence is SUFFICIENT, so the ship criterion is prose and the case
    only holds the added command to being real.

## Out of scope

Moving the SDLC documentation into this kit. The argument for the flow belongs in agentic-sdlc
(`0.3.0/pm-init-teaches-the-conveyor` carries it); this feature only stops the Godot kit's install
path from being a silent detour around it.
