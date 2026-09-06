---
id: 0.25.0/the-agentic-half-leaves/05-every-surface-says-the-godot-kit-alone
feature: 0.25.0/the-agentic-half-leaves
milestone: "0.25.0"
name: README, CLAUDE.md, SDLC.md, the seeds and the version say what this package is now
status: planning
owner:
depends_on: []
---

# README, CLAUDE.md, SDLC.md, the seeds and the version say what this package is now

## Acceptance criteria

- `README.md`: the Godot kit alone — scene verbs, the eight gates, `install-runners`, the two pins a consumer sets; no `pm`, no `check doc`, no conveyor prose. `CLAUDE.md` under 150 lines, its hard rules for a scene kit, the ladder as this repo runs it (`make check`, `make unit`, `make test`, `make milestone`, the pinned belts). `SDLC.md` points at `docs/sdlc-protocol.md` and says nothing the protocol already says. `docs/design/two-kits.md` describes the shape as shipped.
- `pyproject.toml` and `__init__.py` say 0.25.0; `CHANGELOG.md` `## Unreleased` names every verb a consumer loses, the second pin, and `install-runners`' new outputs.
- `installables/project-devkit.toml` and `project-Makefile` (if kept) show a consumer's two pins and `[gates] extra = ["godot-check"]`.
- `check doc` covers README, CLAUDE.md, SDLC.md and docs; everything it holds resolves.

## How this is proven

| criterion | tier | the case that proves it | existing? |
|---|---|---|---|
| 1 | unit | `check doc` over the widened scope; `make check` green | existing gate |
| 2 | n/a | the two version sites agree | release's version-sync check |

## Out of scope

History. The 0.14–0.24 records are not rewritten.
