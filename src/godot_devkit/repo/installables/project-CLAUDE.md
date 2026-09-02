# CLAUDE.md

Orientation for agents working in this repo. `godot-devkit init` wrote this
skeleton once and never overwrites it — **it is yours**: replace every section
below with what is true here. What it starts as is the scaffolding `init`
installed, so that the first agent to open the repo finds the loop rather than
inventing one.

The tooling is [godot-devkit](https://github.com/cdowin/godot-devkit), pinned
at `DEVKIT_VERSION` in the Makefile and configured in `devkit.toml`. Bumping
the pin is a one-line diff; `godot-devkit install-* --diff` shows what a bump
would change in the installed files before you let it.

## What this project is

*(One paragraph: what the game is, what the player does, what it is built in.
An agent that has to infer this from the code infers it differently every
time.)*

## Project structure

*(Where things live and WHY — the rule, not the inventory. `ls` is the
inventory and it cannot go stale.)*

## Verification loop

**`make help` is the authoritative target list.** Every gate prints ONE verdict
line naming its full transcript under `.gate-reports/`; `VERBOSE=1` streams the
whole thing. Never hand-roll an incantation — if the check you need is not a
target, add the target.

| When | Run |
|---|---|
| first thing on a cold machine | `make doctor` — the toolchain census, with a fix for anything missing |
| per change | `make precommit` — `check` + `parse` + `lint` + `unit` + `smoke` |
| slicing while you work | `make unit SYS="<system>"`, `make scenario NAME=<name>`, `make parse` |
| before a release | `make milestone` — the full gate, and what CI runs |

The static gates are `make check` (the devkit roster plus this project's own,
named in `devkit.toml` under `[gates] extra`), `make pm-scan`, `make uid-scan`,
`make hermetic-scan`, `make hooks-self-test` and `make runners-self-test`. The
Godot-booting ones are `make parse`, `make lint`, `make warnings`, `make unit`,
`make integration`, `make scenario`, `make smoke` and `make capture` — each
runs sandboxed through `tools/dev/gdk_runners.sh`, which gives every headless
run its own self-destroying HOME so a boot can never reach the real `user://`.

Reading a scene, a symbol or the autoload census without loading anything —
all pure text parsing, none of it boots Godot:
`make scene FILE=<path>` and `make scene-diff FILE=<path>` for one file,
`make refs NAME=<symbol>` for every real use of a symbol,
`make orphans` for files nothing references, and `make autoloads`.

## How we work

- **The PM tree is `pm/roadmap/`** — milestones, features, stories and bugs as
  markdown with frontmatter. Status moves through the CLI and never through a
  hand edit (`make pm ARGS="story wip <id>"`); `make pm-scan` is the drift
  gate. The execution loop auto-loads from `.claude/rules/pm-execution.md`,
  and the operations manual is `.claude/skills/pm-operations/SKILL.md`.
- **The agent roster is `.claude/agents/`.** Each file opens with a `Project
  config` section carrying stock values — edit them to this project's
  spellings, because the files are yours now.
- **The guards are armed by `tools/setup-hooks.sh`**, which `init` already ran:
  a `git commit` in a shared tree must name its own paths, a raw `godot` boot
  against the real `user://` is blocked, and a push to a protected branch is
  refused. `tools/hooks/cc-godot-sandbox.sh` replays its own block/allow corpus
  under `make hooks-self-test`.
- *(Your branching, review and release flow goes here — the installed files
  carry only what the tooling itself enforces.)*

## Architecture invariants

*(The cross-cutting rules every change must respect: the ones that are true
everywhere, with a pointer to the spec for each. Keep this list short enough
that it is read.)*

## Don'ts

- **Never invoke `godot --headless` directly.** The `make` targets sandbox
  `user://` by overriding HOME; a raw boot does not, and the hook blocks it.
- **Never skip verification before claiming done.** `make precommit` on any
  runtime-affecting change.
- *(Add the footguns this project has actually hit. A rule nobody tripped over
  is a rule nobody reads.)*
