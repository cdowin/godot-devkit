# godot-devkit

Headless developer tooling for Godot 4.x projects — pure-parse scene introspection and fast static repo gates. Nothing here boots Godot (one exception: nothing — even the uid tooling is pure text). Extracted from two shipping Godot 4.6 projects where every tool runs in CI and in pre-commit hooks.

Two design commitments:

1. **Read-only, pure parse.** The introspect tools parse Godot's text-resource format directly (including binary `tile_map_data` decoding) — no editor, no import step, no `.godot/` cache dependency. Safe to run anywhere, anytime, in parallel.
2. **Vendored, not depended-on.** Consuming repos copy these files in via `sync.sh` and commit them. Your hooks and CI never break because a submodule wasn't inited. A manifest records the devkit commit + per-file hashes so drift is visible, not silent.

## Tools

### `introspect/` — scene-file introspection CLI

`introspect` is a thin dispatcher over sibling Python tools (mirrors the layout it ships into: `tools/dev/introspect/introspect`):

| Command | What it does |
|---|---|
| `introspect scene <file.tscn\|.tres> [--props]` | Compact node tree + ext/sub resources + tile bounds for one scene |
| `introspect scene-diff <file> [--git <ref>]` | **Structural** diff vs a git ref — nodes added/removed/reparented, props changed, `tile_map_data` compared as decoded bounds — instead of an unreadable serialized byte diff |
| `introspect scene-diff <old> <new>` | Same, between two files |
| `introspect refs <symbol> [--tests]` | Reference-aware symbol search across `class_name` / methods / signals / `.gd`/`.tscn`/`.tres` paths / uids (word-boundary, comment-stripped) |
| `introspect orphans [--tests]` | Possible-orphan detector — files with zero inbound refs (a hint, never a hard claim) |
| `introspect autoloads` | Autoload census + naming-suffix vs. source-heuristic cross-check |

`godot_tscn.py` is the shared parser all of them compose — sections, properties, resource-ref resolution, TileMapLayer binary decoding.

### `checks/` — static gates (pure git + grep/python, no Godot boot)

| Gate | Guards against |
|---|---|
| `uid_scan.sh` | `.uid` sidecar drift: every tracked `.gd` has a tracked `.gd.uid`; every Script `ext_resource` uid matches the target's actual `.uid`. Prevents cold-cache `invalid UID … using text path` failures. |
| `tres_format_scan.sh` | Path-only `ext_resource` refs (missing `uid=`). Godot 4.4+ silently upgrades these on any editor/import pass — churn that leaks into unrelated commits. Migrate once, then this keeps the tree canonical. |
| `doc_scan.py` | Dead claims in always-loaded agent docs (`CLAUDE.md` + `.claude/rules/` + `.claude/agents/`): dead links, dead `make` targets, dead file paths. |
| `repo_hygiene.sh` | Close-time git-state cruft: dirty tree, stashes, dangling worktrees, merged-but-undeleted branches. Runs `git fetch --prune` — wire it into your close gate, not your per-change gate. |
| `shellcheck.sh` | Lints every shell script under `tools/` (incl. extension-less hook entry points), `shellcheck -x`. Soft-skips if shellcheck isn't installed. |

## Install / update

```sh
./sync.sh /path/to/your/godot/repo          # vendor (copy) the tools in + write tools/devkit.manifest
./sync.sh --check /path/to/your/godot/repo  # drift gate: verify vendored files still match the manifest
```

Files land at `tools/dev/introspect/` and `tools/dev/checks/` (the layout the tools' self-referencing paths assume). Commit them — they're yours now; the manifest records which devkit commit they came from. Local hotfixes are fine and expected: `--check` will name the drifted files, and the fix flows back here by PR.

Suggested Makefile wiring:

```make
DEV := tools/dev
scene:        ; @$(DEV)/introspect/introspect scene $(FILE) $(ARGS)
scene-diff:   ; @$(DEV)/introspect/introspect scene-diff $(FILE) $(ARGS)
refs:         ; @$(DEV)/introspect/introspect refs $(NAME) $(ARGS)
orphans:      ; @$(DEV)/introspect/introspect orphans $(ARGS)
autoloads:    ; @$(DEV)/introspect/introspect autoloads
uid-scan:     ; @bash $(DEV)/checks/uid_scan.sh
tres-scan:    ; @bash $(DEV)/checks/tres_format_scan.sh
doc-scan:     ; @python3 $(DEV)/checks/doc_scan.py
repo-hygiene: ; @bash $(DEV)/checks/repo_hygiene.sh
devkit-drift: ; @/path/to/godot-devkit/sync.sh --check .
```

## Per-project configuration

The deliberate local-edit surfaces (everything else should stay byte-identical to the devkit copy):

- **`introspect/autoloads.py`** — `SUFFIX_EXPECT` (your autoload naming vocabulary) and `EXPECTED_PREFIXES` (your autoload directory layout). Marked `PROJECT CONFIG SURFACE` in the file.
- **`checks/doc_scan.py`** — `SCOPE_GLOBS` (which always-loaded docs to gate) and `EPHEMERAL_DIRS` (paths whose citations are create-resolve-delete by design).
- **`checks/repo_hygiene.sh`** — env-overridable: `DEVKIT_MAINLINE` (default `origin/main`), `DEVKIT_PROTECTED_RE` (default `^(main|staging|archive/.*)$`).

## Requirements

- Python 3.10+ (stdlib only), bash, git. `shellcheck` optional.
- Godot 4.4+ text-resource format for the uid/tres gates (the introspect parser handles any Godot 4.x `.tscn`/`.tres`).

## Migrating a repo to canonical uid-in-refs (one-time, before adopting `tres-scan`)

If your tree has path-only `ext_resource` refs: (1) for targets whose header has no uid at all, mint one with Godot's own `ResourceUID.create_id()` in a headless pass — **never hand-author uid strings**, invalid uids poison the cache; (2) inject each target's uid into the referencing `ext_resource` lines; (3) prove it cold: delete `.godot/`, run a headless `--import`, confirm zero `invalid UID` warnings. Then land `tres_format_scan` so the tree can never drift back.

## License

MIT — see [LICENSE](LICENSE).
