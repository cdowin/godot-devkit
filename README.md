# godot-devkit

Headless developer tooling for Godot 4.x projects — scene introspection, structural surgery, and fast
static repo gates. Nothing here boots Godot. Extracted from two shipping Godot 4.6 projects where
every tool runs in CI and in pre-commit hooks.

## Goal

**Give developers and LLMs simple, sharp tools to parse and work with Godot's text scene formats
(`.tscn` / `.tres`) without opening the editor.** A `.tscn` is text, so every structural question and
every structural change should be answerable by one command that runs in milliseconds, anywhere, in
parallel — not by loading a hundred thousand tokens of packed bytes into a human's head or a model's
context.

## Northstar

> **Any change you can make to a scene by hand, you should be able to make through one deterministic
> command that touches nothing else — and prove it, without ever reading the file.**

For a **human**, that means the editor stops being mandatory for mechanical work, and diffs stay
reviewable.

For an **LLM**, it means three specific things, and they are the reason this repo exists in its
current shape:

| | |
|---|---|
| **A framework** | A small, stable vocabulary of verbs to reach for, so a model composes known-good operations instead of inventing a bespoke `sed` or throwaway script every time. Fewer degrees of freedom is the feature. |
| **Determinism** | The same command on the same input produces the same bytes. Parse → serialise with no mutation is **byte-identical**. A tool that reformats what it was not asked to touch is worse than no tool, because its damage hides inside a legitimate diff. |
| **Token reduction** | Reading a tile-heavy scene can cost 100k+ tokens. `scene` answers structure in a few hundred; the write verbs put **zero** file content in context. Editing a property should never require loading the file that holds it. |

### What else that implies

These are not extra nice-to-haves — each one is a lesson from a real incident:

- **Refuse rather than mangle.** The worst outcome is never an error; it is *silent partial success*.
  A blanket rename once rewrote a `NodePath("Foo/Bar")` while it was rewriting prose, and reported
  success. If a verb cannot guarantee a correct result, it must decline and say why. Loud failure is a
  feature; a model can recover from it, and cannot recover from a lie.
- **Read output is write input.** The address you get back from `scene` is the address `scene set`
  accepts. One addressing vocabulary in both directions, so a model never has to translate between
  "how I saw it" and "how I change it".
- **Idempotence.** Running the same command twice is a no-op the second time. Models retry; retries
  must be safe.
- **Machine-readable on request.** Deterministic ordering, and `--json` where structure matters, so a
  consumer parses instead of regexing prose.
- **Prove the edit without re-reading it.** `scene-diff` closes the loop: make the change, confirm
  exactly what moved, still without loading the file.
- **Encode the footguns as gates.** Godot has silent-failure modes — a property assigned to a script
  that no longer declares it, an `ext_resource` that lost its `uid=`, an instance override missing
  `index=`. Nobody should have to *remember* those. The toolkit should refuse to let them through, so
  the knowledge lives in a gate instead of in a person or a prompt.
- **Bounded blast radius.** A verb changes what it was asked to change and nothing adjacent.

## Design commitments

1. **Pure parse — never boots Godot.** The tools read and write Godot's text-resource format directly
   (including binary `tile_map_data` decoding) — no editor, no import step, no `.godot/` cache
   dependency. Safe to run anywhere, anytime, in parallel.
   *(This was previously stated as "read-only, pure parse." Write verbs broadened the scope; they did
   not weaken the invariant, because the invariant was never read-only — it was never-boot-the-engine.
   A `.tscn` is text.)*
2. **Deterministic and non-destructive.** Byte-identical round trip on untouched content; refuse
   rather than silently reformat.
3. **Versioned, not vendored.** One Python package, one entry point, semver git tags. Consumers pin a
   tag in a single Makefile variable and put project variation in `devkit.toml` — nobody edits tool
   files in place, so there is no fork-drift to police.

## Scope boundary

Two things live here, and the second one is not about Godot at all.

**Scene structure** is the origin and the bulk of the toolkit. This does **not** replace Godot for
bulk content authoring. Painting a `TileMapLayer` cell-by-cell,
baking navigation, importing art — those need the engine. This toolkit owns **structure**: nodes,
properties, resource references, connections, and the gates that keep them honest. That is the
majority of what changes in a scene file after it first exists.

**Repo discipline** is the second half, and it was always here — `check doc`, `check shell` and
`check repo-hygiene` never parsed a scene. `pm` (v0.6.0) is the largest member of that family: a
markdown-and-frontmatter project tracker with a precondition-checked transition CLI and a drift
gate. It is engine-agnostic and would work in a repo with no Godot in it. It ships here because
this is the pinned-tag channel its consumers already share, and because splitting it out would
mean a second version to pin for no benefit. If that ever stops being true, it leaves — the
package name is the only thing arguing against it.

## Tools

### Scene-file introspection

All subcommands of the one `godot-devkit` entry point:

| Command | What it does |
|---|---|
| `scene <file.tscn\|.tres> [--props] [--paths]` | Compact node tree + ext/sub resources + tile bounds for one scene. `--paths` prints each node's full path — the same address the write verbs take |
| `scene-diff <file> [--git <ref>]` | **Structural** diff vs a git ref — nodes added/removed/reparented, props changed, `tile_map_data` compared as decoded bounds — instead of an unreadable serialized byte diff |
| `scene-diff <old> <new>` | Same, between two files |
| `refs <symbol> [--tests]` | Reference-aware symbol search across `class_name` / methods / signals / `.gd`/`.tscn`/`.tres` paths / uids (word-boundary, comment-stripped) |
| `orphans [--tests]` | Possible-orphan detector — files with zero inbound refs (a hint, never a hard claim) |
| `autoloads` | Autoload census + naming-suffix vs. source-heuristic cross-check |

A shared parser (`tscn.py`) all of them compose — sections, properties, resource-ref resolution, TileMapLayer binary decoding.

### Scene surgery (write verbs)

Nodes are addressed **by path** — `.` is the root, `Name` its child, `Parent/Name` deeper. That is how
`.tscn` addresses them in `parent=`, and it is what `scene --paths` prints. (Format-4 `unique_id=` is a
serialisation detail, not an address; nothing keys off it.)

| Command | What it does |
|---|---|
| `scene set <file> <node-path> <prop> <value>` | Assign a property, replacing the value in place (inline `; comments` survive) or appending it to the node |
| `scene rename <file> <node-path> <new-name>` | Rename a node **and every reference to it** — descendants' `parent=`, `[connection from=/to=]`, `[editable path=]`, and every relative `NodePath("...")` literal, resolved against the node that owns it |
| `scene add <file> <parent-path> <name> <type> [--script res://x.gd]` | Add a node after the parent's subtree; `--script` mints the `ext_resource` from the script's `.uid` sidecar, so the ref is born canonical |
| `scene rm <file> <node-path>` | Remove a node, its descendants, its connections and editable markers, and any `ext_resource` left unreferenced |
| `scene reparent <file> <node-path> <new-parent>` | Move a subtree and re-express the NodePaths that pointed into or out of it |
| `scene canonicalize <file>...` | Restore what `PackedScene.pack()` + `ResourceSaver.save()` drop: uid-in-refs, the file's own header uid, `index=` on instance-child overrides, `[editable path=]` |
| `scene canonicalize --elide-defaults <file>...` | Also **delete** `.tres` assignments proven equal to the script's `@export` default — the ones Godot's writer omits, so a hand-authored file stops diffing on every editor save. Opt-in, because it removes lines |

Every verb takes `--dry-run` (prints a unified diff, writes nothing), is **idempotent** (a second run
reports `unchanged`), and **refuses** — exit 1, with a reason — rather than write a result it cannot
guarantee. Untouched lines are never rewritten: parse → serialise with no mutation is byte-identical,
proven over every `.tscn`/`.tres` in the consuming repos plus a fixture carrying the awkward
constructs (`&"StringName"` literals, inline `;` comments, multi-line dictionaries, instance
overrides).

**Why `--elide-defaults` is a line-deletion pass and not a load-and-re-save.** Godot's own writer
produces the canonical form, but running it over a tree is destructive: measured over one consumer's
559 `.tres`, a headless load-and-re-save rewrote 558 of them — deleting every `;` comment (1157 lines
across 107 files), reordering properties into declaration order, respelling typed arrays
(`[a, b]` -> `Array[Resource]([a, b])`) and floats (`0.30` -> `0.3`), minting new `ext_resource`
entries with random ids, and dropping every `uid=`. Worse, a resource whose script fails to compile in
that context loads scriptless and saves as an EMPTY file, with `ResourceSaver.save()` returning `OK`.
So this pass never re-serialises: it deletes only the assignment lines it can PROVE are redundant, and
every other byte is carried through. Over that same corpus it removed 2479 assignments from 384 files
with zero lines added, zero structural lines touched, and zero change to any loaded property value.

`canonicalize` restores from **evidence, never invention**. A uid comes from the target's own `.uid`
sidecar, its `[gd_scene]`/`[gd_resource]` header, or its `.import` file — falling back to what the rest
of the repo already says about that path. An `index=` is counted off the base scene's actual children.
Anything unresolvable is reported and left alone.

### Static gates (`godot-devkit check <gate>`, pure git + parse, no Godot boot)

| Gate | Guards against |
|---|---|
| `check uid` | `.uid` sidecar drift: every tracked `.gd` has a tracked `.gd.uid`; every Script `ext_resource` uid matches the target's actual `.uid`. Prevents cold-cache `invalid UID … using text path` failures. |
| `check tres` | Path-only `ext_resource` refs (missing `uid=`). Godot 4.4+ silently upgrades these on any editor/import pass — churn that leaks into unrelated commits. Migrate once, then this keeps the tree canonical. |
| `check props` | Assignments to properties that **do not exist** — the export was renamed or deleted and the scene still names the old one. Godot drops such an assignment silently, so the node comes up half-configured with every gate green. Checks scene nodes, sub_resources and `.tres` resources against the script's `@export` chain and the engine's ClassDB. Nothing is called dead unless the whole picture resolved; everything else is censused as UNVERIFIED, never failed. |
| `check defaults` | `.tres` assignments that repeat the script's declared `@export` default. Hand-authored data spells every property out; Godot's writer omits the defaults — so the file diffs forever, and the mop-up is `git checkout --` every session. Judges the elision dimension ONLY (see below); anything outside a small closed value language is censused, never reported. |
| `check doc` | Dead claims in always-loaded agent docs (`CLAUDE.md` + `.claude/rules/` + `.claude/agents/`): dead links, dead `make` targets, dead file paths. |
| `check repo-hygiene` | Close-time git-state cruft: dirty tree, stashes, dangling worktrees, merged-but-undeleted branches. Runs `git fetch --prune` — wire it into your close gate, not your per-change gate. |
| `check pm` | PM-tree status drift: a `done` feature with no substantive review record, a feature whose stories are all done but never advanced, a `done` milestone with live children, a status outside the schema, a `done` story under a live feature, a `building` milestone with everything closed, and an overdue archive prune. Shares its predicates with the `pm` CLI, so the gate and the tool cannot disagree. **Also runs the `pm validate` integrity rules (V1–V5) by default**, so the gate fails on a dangling `depends_on` as well as on status drift. Off by default in `check all` — a repo with no PM tree has no drift to find. Three further rules (D8/D9/D10) gate the branch-per-milestone + bump-at-start flow and are opt-in via `[pm] checks`. |
| `check shell` | Lints every shell script under `tools/` (incl. extension-less hook entry points), `shellcheck -x`. Soft-skips if shellcheck isn't installed. |

### Project management (`godot-devkit pm <command>`)

Filesystem-backed milestone → feature → story tracking: markdown with YAML frontmatter under
`pm/roadmap/`. The point of a CLI rather than a convention is that a `status:` is the one field a
human should never hand-edit — free-text flips are how a lifecycle drifts, with features reaching
`done` without the review the flow requires.

| Command | What it does |
|---|---|
| `pm story <wip\|review\|blocked> <story-id>` | Legal story transitions. `review` is the story terminal — there is deliberately no `story done` |
| `pm feature <ready\|building> <feature-id>` | The claim-side flips |
| `pm feature review <feature-id>` | Refuses unless every story is at `review` |
| `pm feature done <feature-id> [--review-record <path>]` | Cascade-closes every `review` story **and** the feature, atomically. Refuses without a *substantive* review record — and a refused close leaves `feature.md` byte-identical |
| `pm milestone <ready\|building\|done> <id>` | Milestone flips; `done` refuses unless every feature is done |
| `pm status [<milestone>]` | Tree report, drift-aware, grouped by the optional `phase:` bucket |
| `pm validate` | Structural + referential integrity: frontmatter well-formed, ids match paths, parentage consistent, `depends_on`/`consumed_by` resolve, the feature graph acyclic and phase-monotone. A ref into a **pruned** milestone is censused as UNVERIFIABLE, never failed — git history is the archive |
| `pm new <milestone\|feature\|story\|bug> …` | Scaffold a grain to the schema. Creation only — never overwrites |
| `pm prune` | Delete cooled archives and stamp the resurrect anchor in the roadmap's prune log |
| `pm install-skills [--force]` | Write the shared guidance into the repo: `.claude/rules/pm-execution.md` (the claim→close loop, **auto-loads** on a `pm/roadmap/**` edit) and `.claude/skills/pm-operations/SKILL.md` (the operations manual, invoked deliberately). Refuses to clobber a file it did not generate |
| `pm init` | Stand up a tree in a repo that has none — `pm/roadmap/` + a seeded `ROADMAP.md`, the two guidance files, and the remaining wiring printed as a checklist |

**What ships as guidance, and what does not.** The two installed files carry only the loop the CLI
itself enforces and the manual for the tree it operates. A project's own SDLC — branching, versioning,
release ceremony, agent dispatch, who reviews what, and what a milestone *means* in that codebase —
stays in that project's own rules and agents, because it differs per repo and always will. The
installed files are generated: edit them and the next install refuses rather than overwriting.

Exit codes follow the house contract: `0` ok (including an idempotent no-op), `1` refused, `2` usage.
The vocabularies, the transition graphs, the review-record definition and the drift predicates live
in one module that both the CLI and `check pm` import — one definition, two readers.

## Install

No PyPI needed — install straight from a git tag (pin it):

```sh
uv tool install "git+https://github.com/cdowin/godot-devkit@v0.3.0"   # on PATH as godot-devkit
# or invoke pinned without installing:
uvx --from "git+https://github.com/cdowin/godot-devkit@v0.3.0" godot-devkit scene scenes/main.tscn
```

Suggested Makefile wiring (one pinned variable, targets delegate):

```make
DEVKIT_VERSION := v0.3.0
DEVKIT := uvx --from "git+https://github.com/cdowin/godot-devkit@$(DEVKIT_VERSION)" godot-devkit

scene:        ; @$(DEVKIT) scene $(FILE) $(ARGS)
scene-diff:   ; @$(DEVKIT) scene-diff $(FILE) $(ARGS)
refs:         ; @$(DEVKIT) refs $(NAME) $(ARGS)
orphans:      ; @$(DEVKIT) orphans $(ARGS)
autoloads:    ; @$(DEVKIT) autoloads
scene-set:    ; @$(DEVKIT) scene set $(FILE) $(ARGS)
scene-canon:  ; @$(DEVKIT) scene canonicalize $(FILE) $(ARGS)
uid-scan:     ; @$(DEVKIT) check uid
tres-scan:    ; @$(DEVKIT) check tres
prop-scan:    ; @$(DEVKIT) check props
defaults-scan:; @$(DEVKIT) check defaults
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
exclude_prefixes = ["addons/"]

[tres]
exclude_prefixes = ["addons/"]

[props]
exclude_prefixes = ["addons/"]

[pm]
roadmap_dir = "pm/roadmap"      # the tree, relative to the repo root
review_dir  = "docs/reviews"    # where review records live
review_min_content_bytes = 20   # anti-rubber-stamp floor (non-whitespace bytes)
review_slug_fallback = false    # also accept <review_dir>/<feature-slug>*.md
story_ordinal_prefix = false    # also resolve stories/NN-<slug>.md
checks = ["D1","D2","D3","D4","D5","D6","D7",   # drift rules
          "V1","V2","V3","V4","V5"]             # integrity rules (see `pm validate`)
# D8/D9/D10 are the FLOW rules — opt in by naming them here:
#   D8  project version == the `building` milestone's id (bump at START; the id
#       IS the version, exact string equality)
#   D9  a `building` milestone declares `branch:`
#   D10 that branch is checked out in the TRUNK worktree
# A project that ships from the trunk and bumps at close is running a different
# valid flow, so these stay off unless asked for.
version_file = "project.godot"                  # D8: where the version lives
version_pattern = '^config/version="(.*)"$'     # D8: the line that carries it
trunk_branches = ["staging", "main"]            # D10: `branch: staging` = no integration branch
# Vocabularies + graphs are overridable too: milestone_states, feature_states,
# story_states, milestone_transitions, feature_transitions, story_transitions.
# The stock graph is the STRICT one: the story terminal is `review` (`done`
# comes only from the feature cascade) and milestones have no `review` state.

[pm.scaffold.feature]           # per-grain scaffold schema, if yours differs
reviewed = ""
risk = "medium"
size = "m"

[defaults]
exclude_prefixes = ["addons/"]
# Escape hatch for properties a script answers to without declaring them
# statically (a `_get_property_list` shape the scanner cannot see):
extra_properties = { MyWidget = ["virtual_prop"] }

[repo_hygiene]
mainline = "origin/main"
protected = "^(main|staging|archive/.*)$"

[shell]
roots = ["tools"]
```

## Development

```sh
python3 -m unittest discover -s tests -t tests          # the suite (stdlib only)
python3 -c "import ast,pathlib; [ast.parse(p.read_text()) for p in pathlib.Path('src').rglob('*.py')]"
```

Tests that need a Godot repo (round-trip corpus, gate calibration) skip cleanly when no consumer
checkout is present; the hermetic fixtures under `tests/fixtures/` always run.

`check props` compares against a snapshot of Godot's ClassDB in
`src/godot_devkit/data/classdb.json`. Reading it boots nothing. Regenerate when the target engine
minor moves:

```sh
godot --headless --dump-extension-api      # writes ./extension_api.json
python3 tools/gen_classdb.py extension_api.json
```

## Requirements

- Python 3.11+ (stdlib only) and git. `shellcheck` optional (enables `check shell`).
- Godot 4.4+ text-resource format for the uid/tres gates (the introspect parser handles any Godot 4.x `.tscn`/`.tres`).

## Migrating a repo to canonical uid-in-refs (one-time, before adopting `tres-scan`)

If your tree has path-only `ext_resource` refs: (1) for targets whose header has no uid at all, mint one with Godot's own `ResourceUID.create_id()` in a headless pass — **never hand-author uid strings**, invalid uids poison the cache; (2) inject each target's uid into the referencing `ext_resource` lines; (3) prove it cold: delete `.godot/`, run a headless `--import`, confirm zero `invalid UID` warnings. Then land `check tres` in your gates so the tree can never drift back.

## License

MIT — see [LICENSE](LICENSE).
