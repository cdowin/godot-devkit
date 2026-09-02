---
id: 0.19.0/install-runners
milestone: "0.19.0"
name: The sandboxed headless-run shell library becomes an installable
status: done
reviewed: pm/roadmap/0.19.0-runners/review.md
phase:
depends_on: []
consumed_by: []
---

# The sandboxed headless-run shell library becomes an installable

What it makes true: a consumer runs every Godot-booting gate through a devkit-owned shell library
(`installables/gdk_runners.sh` + `installables/import_cache.sh`) instead of a hand-grown
`tools/dev/_common.sh`. The reference implementation is nullbound's `tools/dev/_common.sh` at
its `271baf4ec` (2026-09-02) — port, do not redesign.

## Existing-construct audit

- `installables/` already holds consumer-side shell (`cc-godot-sandbox.sh`, `doctor.sh`,
  `agent-worktree.sh`, `setup-hooks.sh`) — this is one more installable, not a new mechanism.
- `install-hooks` is the installer verb family; a new `install-runners` verb mirrors it. Folding
  the library into `install-hooks` would make a hooks-only consumer carry runners it does not call.
- The devkit's Python never boots Godot and stays that way; the library is shell the CONSUMER's
  `make` runs, which is what the sandbox hook (`cc-godot-sandbox.sh`) already enforces.

## Ship criterion

Four stories: the gate log/verdict helpers, the sandbox HOME + `project.godot` restore, the
import-cache runner, and both consumers adopting (forks deleted, verdict lines unchanged).

## Out of scope

- The consumer's gate TARGETS (`parse`, `unit`, `scenario`, …) stay in the consumer's Makefile —
  they are the project's; only the library they call moves.
- Any Python wrapper around the shell.
