# godot-devkit

Headless developer tooling for Godot 4.x projects — pure-parse scene introspection and fast static repo gates. Nothing here boots Godot (one exception: nothing — even the uid tooling is pure text). Extracted from two shipping Godot 4.6 projects where every tool runs in CI and in pre-commit hooks.

Two design commitments:

1. **Read-only, pure parse.** The introspect tools parse Godot's text-resource format directly (including binary `tile_map_data` decoding) — no editor, no import step, no `.godot/` cache dependency. Safe to run anywhere, anytime, in parallel.
2. **Versioned, not vendored.** One Python package, one entry point, semver git tags. Consumers pin a tag in a single Makefile variable and put project variation in `devkit.toml` — nobody edits tool files in place, so there is no fork-drift to police.

## Tools

### Scene-file introspection

All subcommands of the one `godot-devkit` entry point:

| Command | What it does |
|---|---|
| `scene <file.tscn\|.tres> [--props]` | Compact node tree + ext/sub resources + tile bounds for one scene |
| `scene-diff <file> [--git <ref>]` | **Structural** diff vs a git ref — nodes added/removed/reparented, props changed, `tile_map_data` compared as decoded bounds — instead of an unreadable serialized byte diff |
| `scene-diff <old> <new>` | Same, between two files |
| `refs <symbol> [--tests]` | Reference-aware symbol search across `class_name` / methods / signals / `.gd`/`.tscn`/`.tres` paths / uids (word-boundary, comment-stripped) |
| `orphans [--tests]` | Possible-orphan detector — files with zero inbound refs (a hint, never a hard claim) |
| `autoloads` | Autoload census + naming-suffix vs. source-heuristic cross-check |

A shared parser (`tscn.py`) all of them compose — sections, properties, resource-ref resolution, TileMapLayer binary decoding.

### Static gates (`godot-devkit check <gate>`, pure git + parse, no Godot boot)

| Gate | Guards against |
|---|---|
| `check uid` | `.uid` sidecar drift: every tracked `.gd` has a tracked `.gd.uid`; every Script `ext_resource` uid matches the target's actual `.uid`. Prevents cold-cache `invalid UID … using text path` failures. |
| `check tres` | Path-only `ext_resource` refs (missing `uid=`). Godot 4.4+ silently upgrades these on any editor/import pass — churn that leaks into unrelated commits. Migrate once, then this keeps the tree canonical. |
| `check doc` | Dead claims in always-loaded agent docs (`CLAUDE.md` + `.claude/rules/` + `.claude/agents/`): dead links, dead `make` targets, dead file paths. |
| `check repo-hygiene` | Close-time git-state cruft: dirty tree, stashes, dangling worktrees, merged-but-undeleted branches. Runs `git fetch --prune` — wire it into your close gate, not your per-change gate. |
| `check shell` | Lints every shell script under `tools/` (incl. extension-less hook entry points), `shellcheck -x`. Soft-skips if shellcheck isn't installed. |

## Install

No PyPI needed — install straight from a git tag (pin it):

```sh
uv tool install "git+https://github.com/cdowin/godot-devkit@v0.2.0"   # on PATH as godot-devkit
# or invoke pinned without installing:
uvx --from "git+https://github.com/cdowin/godot-devkit@v0.2.0" godot-devkit scene scenes/main.tscn
```

Suggested Makefile wiring (one pinned variable, targets delegate):

```make
DEVKIT_VERSION := v0.2.0
DEVKIT := uvx --from "git+https://github.com/cdowin/godot-devkit@$(DEVKIT_VERSION)" godot-devkit

scene:        ; @$(DEVKIT) scene $(FILE) $(ARGS)
scene-diff:   ; @$(DEVKIT) scene-diff $(FILE) $(ARGS)
refs:         ; @$(DEVKIT) refs $(NAME) $(ARGS)
orphans:      ; @$(DEVKIT) orphans $(ARGS)
autoloads:    ; @$(DEVKIT) autoloads
uid-scan:     ; @$(DEVKIT) check uid
tres-scan:    ; @$(DEVKIT) check tres
doc-scan:     ; @$(DEVKIT) check doc
shell-scan:   ; @$(DEVKIT) check shell
repo-hygiene: ; @$(DEVKIT) check repo-hygiene
```

Updating = bump `DEVKIT_VERSION`, run your gates, commit the one-line diff.

## Per-project configuration — `devkit.toml`

Optional, at the consuming repo root. Every tool works with stock defaults; a
section overrides only what it names:

```toml
[autoloads]
suffixes = { Manager = "emits", Tracker = "relays", Registry = "inert", Store = "inert", Service = "inert" }
expected_prefixes = ["autoloads/core/", "autoloads/sim/", "autoloads/presentation/"]

[doc]
scope = ["CLAUDE.md", ".claude/rules/*.md", ".claude/agents/*.md"]
ephemeral = ["docs/reviews/"]

[uid]
scan_dirs = ["data", "scenes", "resources", "systems", "autoloads", "shared"]

[tres]
exclude_prefixes = ["addons/"]

[repo_hygiene]
mainline = "origin/main"
protected = "^(main|staging|archive/.*)$"

[shell]
roots = ["tools"]
```

## Requirements

- Python 3.11+ (stdlib only) and git. `shellcheck` optional (enables `check shell`).
- Godot 4.4+ text-resource format for the uid/tres gates (the introspect parser handles any Godot 4.x `.tscn`/`.tres`).

## Migrating a repo to canonical uid-in-refs (one-time, before adopting `tres-scan`)

If your tree has path-only `ext_resource` refs: (1) for targets whose header has no uid at all, mint one with Godot's own `ResourceUID.create_id()` in a headless pass — **never hand-author uid strings**, invalid uids poison the cache; (2) inject each target's uid into the referencing `ext_resource` lines; (3) prove it cold: delete `.godot/`, run a headless `--import`, confirm zero `invalid UID` warnings. Then land `check tres` in your gates so the tree can never drift back.

## License

MIT — see [LICENSE](LICENSE).
