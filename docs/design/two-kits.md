# Two kits — the shape as shipped

One package became two, and this repository is the Godot half.

| | owns | the consumer's pin |
|---|---|---|
| **agentic-sdlc** | the gate framework (`Makefile.devkit`: `check`, `precommit`, `milestone`, `help`), the hooks and CI, the PM tree and its gates, the release belts | `DEVKIT_VERSION` |
| **godot-devkit** | the scene verbs (`scene`, `scene-diff`, `refs`, `orphans`, `autoloads`, `tiles`), the eight Godot gates, `install-runners` | `GODOT_DEVKIT_VERSION` |

## The seam

A consumer's Makefile is two pins and one include. `agentic-sdlc install-gates` writes
`Makefile.devkit`; `godot-devkit install-runners` writes `Makefile.tiers` — the Godot tier roster,
`GDK_PRECOMMIT_TIERS` / `GDK_MILESTONE_TIERS` and a `godot-check` target — on the seam the include
`-include`s, and `[gates] extra = ["godot-check"]` joins the eight gates to `make check`. Two kits
read one `devkit.toml`, each roster under its own key: `[checks] all` is agentic-sdlc's,
`[checks] godot` is this kit's, and each refuses the other's names rather than skipping them.

## Two relationships, one of them allowed

- **A library dependency** — `godot_devkit.godot` importing the agentic package — is the
  cross-wiring hard rule 8 bans: a scene parser must not drag in a PM tree, hooks and installables.
  There is none, in either direction.
- **A consumer pin** — this repository using agentic-sdlc for its own SDLC, hooks, PM tree, CI and
  releases — is dogfooding, and it is correct: the same relationship every game repo has, and what
  makes the kit answer for itself.

## What is duplicated

`core/` — read a TOML section, find the repo, walk the tracked files, the one writer — is small and
lives in both kits by ruling. The trigger for revisiting is named: if both kits stay config-forward
and the shared surface grows, the answer is a published shared config utility — not a private third
package, and not a dependency edge between the two.

## What the split did not change

Rule 8 binds both kits: neither names a consuming project, reads outside its own checkout, or gates
on another repo's state. Realistic data lives under `tests/fixtures/`, and a consumer proves its own
integration when it bumps a pin.
