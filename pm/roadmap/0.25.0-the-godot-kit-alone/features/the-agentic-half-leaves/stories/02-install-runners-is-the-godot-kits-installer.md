---
id: 0.25.0/the-agentic-half-leaves/02-install-runners-is-the-godot-kits-installer
feature: 0.25.0/the-agentic-half-leaves
milestone: "0.25.0"
name: install-runners writes the Godot tiers, runners, sandbox hook and Makefile.tiers into a consumer
status: done
owner: claude
depends_on: []
---

# install-runners writes the Godot tiers, runners, sandbox hook and Makefile.tiers into a consumer

## Acceptance criteria

- `godot-devkit install-runners` writes `tools/dev/runners/*.sh` (parse, lint, warnings, unit, integration, scenario, capture, import_cache, hermetic_run_scan) with `gdk_runners.sh` and `compile_sweep.gd`, `tools/hooks/cc-godot-sandbox.sh`, `.github/workflows/uid-guard.yml`, and `Makefile.tiers` declaring the Godot targets and `GDK_PRECOMMIT_TIERS` / `GDK_MILESTONE_TIERS`; it prints the `.claude/settings.json` entry for the sandbox hook.
- Idempotent; `--diff` writes nothing; a differing destination is refused naming `--force`; the `project config` header rule the hooks use holds for the sandbox hook.
- The written `Makefile.tiers` composes under agentic-sdlc's `Makefile.devkit`: `make -n precommit` and `make -n milestone` resolve every tier on a fixture project holding both.
- This repo's own `Makefile.tiers` is what the installer writes, byte-current (self-hosting), plus this repo's Python test tiers.

## How this is proven

| criterion | tier | the case that proves it | existing? |
|---|---|---|---|
| 1 | unit | the plan writes its files, a second run is a no-op, --diff, collision refusal | amend tests/test_runners_installable.py |
| 2 | integration | the written tiers resolve under the pinned include on a fixture | amend tests/test_runners_installable.py |
| 3 | unit | this repo's Makefile.tiers is byte-current with the installable | new case in the same module; docstring says why |

## Out of scope

`Makefile.devkit`. It is agentic-sdlc's; a consumer gets it from that pin.

## Close

done: ad47964 — install-runners writes the runners, compile sweep, sandbox hook, uid-guard workflow and a new Makefile.tiers (the Godot roster, GDK_PRECOMMIT/MILESTONE_TIERS, godot-check) reading GODOT_DEVKIT_VERSION; idempotent, --diff, collision and header-only refusals proven, `make -n precommit|milestone` resolve on a fixture holding both pins; this repo self-hosts the file (Python tier renamed pyunit).
