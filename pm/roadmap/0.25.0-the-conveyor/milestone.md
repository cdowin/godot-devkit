---
id: "0.25.0"
name: the conveyor
status: planning
depends_on: []
branch:
---

# 0.25.0 — the conveyor

The SDLC stops being prose an operator follows correctly and becomes a step machine that
refuses to advance. Three features compose: **the kit owns the gates that scan its own
artifacts**, so a fix reaches every consumer; **every gate reports its cost**, so the set
can be argued from data; and **the release is a conveyor**, with `release` and `adopt` as
ordered step lists whose judgement steps gate on the artifact of judgement.

## ▶ The SDLC, and who provides each piece

Written 2026-09-04 when the package split in two. **The line: a thing belongs to the KIT
whose artifact it scans, drives or installs.** Three providers, and the third is not a
mistake — a project's own rules are its own.

| phase | the piece | provider |
|---|---|---|
| **Plan** | grain schema, the state vocabulary, `pm` verbs, `check pm`, templates | **agentic-sdlc** |
| | the milestones, features, stories and bugs themselves | **the project** |
| **Claim** | agent definitions (stock roster) | **agentic-sdlc** |
| | forked/configured agents, project-specific roles | **the project** |
| **Build** | commit-pathspec, write-confine, stop-gate guards; worktree tooling | **agentic-sdlc** |
| | language runners — parse, lint, unit, integration, scenario, capture | **godot-devkit** |
| **Verify** | the gate FRAMEWORK — `gdk_gate`, `Makefile.devkit`, `[checks]`, `[gates] extra` | **agentic-sdlc** |
| | checks over SDLC artifacts — grain prose, hooks, runners, sandbox | **agentic-sdlc** |
| | checks over Godot artifacts — uid, tres, props, defaults, rng, test-shape, unit-disk | **godot-devkit** |
| | the project's own architecture scans | **the project** |
| **Review** | the review record, N-pass verdict parsing, reviewer agents | **agentic-sdlc** |
| **Release** | the protocol, version sync, changelog discipline, tag | **agentic-sdlc** |
| **Telemetry** | the ledger, the two couriers, `pm ledger report` | **agentic-sdlc** |
| **Adopt** | `install-*` verbs and their installables | **each kit, for its own** |

### The consumer's shape, in one line

> A project pins **agentic-sdlc** for how it works, pins **godot-devkit** for what it builds
> with, and owns its own rules about its own code.

`godot-devkit` is itself a consumer of `agentic-sdlc` — that is dogfooding, and it is a
CONSUMER PIN, never a library import. A scene parser must not drag in a PM tree.

### What the split has NOT yet resolved — measured 2026-09-04

`src/` split at **zero cross-imports** (repo/ 9,334 lines, godot/ 6,844, core/ 981 shared and
deliberately duplicated). **The installables did not.** Of 44:

- **6 are pure SDLC** — `cc-commit-pathspec.sh`, `cc-stop-gate.sh`, `cc-write-confine.sh`,
  `pre-push`, `prepare-commit-msg`, `setup-hooks.sh`.
- **~13 are pure Godot** — `parse.sh`, `lint.sh`, `unit.sh`, `integration.sh`, `scenario.sh`,
  `warnings.sh`, `capture.sh`, `import_cache.sh`, `compile_sweep.gd`, `hermetic_run_scan.sh`,
  `cc-godot-sandbox.sh`, `gdk_runners.sh`, `ci-uid-guard.yml`.
- **The rest are SDLC FRAMEWORK carrying a Godot ROSTER** — `Makefile.devkit` (23 Godot
  references), `ci-verify.yml` (23), `doctor.sh` (38), `project-devkit.toml`,
  `project-CLAUDE.md`, and the agent files. The structure is generic; the content names
  Godot targets.

**That middle tier is the real work of the split, and it is not a file move.** `Makefile.devkit`
must offer the gate framework while the Godot targets come from somewhere else — probably the
same `[gates] extra` mechanism a project already uses for its own. Until that is designed,
`godot-devkit` cannot cleanly shed the agentic half.

## Ship criterion

1. `release` and `adopt` both run as step lists that refuse to advance, and a skip is recorded
   rather than silent.
2. The SDLC document a consumer reads is GENERATED from its own step list — `install-sdlc`
   beside `install-agents` — so it cannot drift from what runs.
3. Every gate records name, duration, verdict and corpus size to the ledger, through the one
   funnel, failing open.
4. The four gates that scan this kit's own artifacts ship in `[checks] all`, and the tree that
   never had a prose-cap gate gains one.
5. The installables' middle tier is resolved, or the milestone says in writing why it is not
   and what blocks it.

## Risks

1. **Over-encoding.** A step earns its place by having a checkable postcondition; anything else
   is guidance and belongs in the generated doc.
2. **A gate landing in the default roster reds every consumer at once.** Ships reporting-only or
   config-ceilinged, the posture the 0.24.0 deprecation window took.
3. **A conveyor that is always skipped is worse than none**, because it looks like control. If
   the skip ledger shows one step skipped every release, that step is wrong.
4. **The middle tier may not decompose cleanly**, and forcing it would put a Godot roster in the
   agentic kit or a gate framework in the Godot one. Better to state the blocker than to ship a
   split that re-creates the coupling under new names.
