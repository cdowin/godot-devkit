---
id: 0.25.0/the-agentic-half-leaves/01-the-repo-family-leaves
feature: 0.25.0/the-agentic-half-leaves
milestone: "0.25.0"
name: src/godot_devkit/repo/ is gone, and the CLI routes only Godot verbs
status: done
owner: claude
depends_on: []
---

# src/godot_devkit/repo/ is gone, and the CLI routes only Godot verbs

## Acceptance criteria

- `src/godot_devkit/repo/` is deleted: `pm/`, `checks/` (doc, shell, hooks, pm, repo_hygiene), `install.py`, `init.py`, `gates_extra.py`, and every non-Godot installable (agents, shared `cc-*` hooks, `pre-push`, `prepare-commit-msg`, `setup-hooks.sh`, `agent-worktree.sh`, `doctor.sh`, `ci-verify/semver-gate/auto-tag.yml`, `Makefile.devkit`, `project-*`, pm guidance, templates, skills).
- `cli.py` routes `scene`, `tiles`, `scene-diff`, `refs`, `orphans`, `autoloads`, `install-runners` and `check <uid|tres|props|defaults|rng|tres-comment|unit-disk|test-shape|all>`; `--help` lists exactly those; `pm`, `init`, `check doc|shell|pm|hooks|repo-hygiene` and the other installers exit 2 naming `agentic-sdlc`.
- `core/` keeps only what `godot/` imports; `tests/test_boundaries.py` holds the one-way edge.
- `selfcheck` and `[gates] extra` leave this repo's Makefile.tiers and devkit.toml; `make check` is `agentic-sdlc check all` alone.

## How this is proven

| criterion | tier | the case that proves it | existing? |
|---|---|---|---|
| 1 | unit | `--help` and the route table equal the Godot verb set; a retired verb exits 2 naming the kit | amend the cli surface test |
| 2 | unit | no module under src/ imports a deleted name | tests/test_boundaries.py, amended |

## Out of scope

Rewriting a Godot verb. Nothing under `godot/` changes in this story.

## Close

done: 621970e — src/godot_devkit/repo/ deleted, the fourteen Godot installables moved to godot/installables/ with a narrowed install-runners beside them, cli.py routes the Godot verbs and exits 2 on a retired one naming agentic-sdlc, selfcheck and [gates] extra dropped, nineteen family tests deleted and six amended.
