# godot-devkit

Headless developer tooling for Godot 4.x, and an engine-agnostic project tracker that ships beside
it. Two families in one pinned-tag Python package: **scene tooling** that reads, edits and gates
`.tscn`/`.tres` as text without ever opening the editor, and **repo discipline** — a markdown PM tree
with a precondition-checked CLI, plus gates for docs, shell and git hygiene — that has no Godot in it
at all.

Nothing here boots Godot. Extracted from two shipping Godot 4.6 projects where every tool runs in CI
and in pre-commit hooks.

## What it's for

- **Read a scene without loading it.** `scene` answers structure in a few hundred tokens where the
  file costs 100k+. → [Quickstart](#quickstart-five-minutes)
- **Edit a scene without reformatting it.** Path-addressed write verbs that change the lines you
  named and refuse rather than mangle. → [Edit a scene you can't afford to read](#edit-a-scene-you-cant-afford-to-read)
- **Gate the silent-failure classes.** Renamed exports, uid drift, path-only refs — the things Godot
  drops without a word. → [Catch Godot's silent failures](#catch-godots-silent-failures-in-ci)
- **Run a project's work tree from the CLI.** Milestones, features and stories as markdown, with
  transitions no one can hand-edit around. → [Track work in a markdown PM tree](#track-work-in-a-markdown-pm-tree)

## Install

Consumed at a **pinned tag** so every machine and CI runs identical gate code:

```bash
uvx --from "git+https://github.com/cdowin/godot-devkit@v0.9.0" godot-devkit --version
```

```
godot-devkit 0.9.0
```

Pin that string once in your Makefile ([Wiring it in](#wiring-it-into-your-project)) and bump it
deliberately. `godot-devkit --help` lists every subcommand.

## Quickstart: five minutes

Run these from inside a Godot repo. The first three are read-only; the fourth writes nothing because
of `--dry-run`.

**See a scene's structure without loading it:**

```bash
godot-devkit scene scenes/ui/primitives/rest_moment_log_line.tscn
```

```
# scenes/ui/primitives/rest_moment_log_line.tscn
gd_scene  format=3  uid=uid://c8yqx3wnl2rft

## ext_resources (1)
  [1_logline] Script  rest_moment_log_line.gd

## node tree (1)
  RestMomentLogLine [Label]  script=→rest_moment_log_line.gd
```

**Get the addresses the write verbs accept** — read output *is* write input:

```bash
godot-devkit scene scenes/ui/primitives/rest_moment_log_line.tscn --paths
```

```
## node tree (1)
  .                          RestMomentLogLine [Label]  script=→rest_moment_log_line.gd
```

**Change one property, see the diff, write nothing:**

```bash
godot-devkit scene set scenes/ui/primitives/rest_moment_log_line.tscn RestMomentLogLine text '"the camp settles"' --dry-run
```

```
--- a/rest_moment_log_line.tscn
+++ b/rest_moment_log_line.tscn
@@ -16,3 +16,3 @@
 theme_type_variation = &"RestMomentLogLine"
-text = "the camp settles in"
+text = "the camp settles"
 autowrap_mode = 3
set  scenes/ui/primitives/rest_moment_log_line.tscn  set  (2 line(s), dry run)
```

Two lines changed, nothing else touched. Drop `--dry-run` to apply it; run it twice and the second
run is a no-op.

**Then run the gates:**

```bash
godot-devkit check all
```

On a repo that has never used this, **expect red** — most trees have path-only `ext_resource` refs
and missing `.uid` sidecars. That is the tool working. See
[Adopt the gates on an existing repo](#adopt-the-gates-on-an-existing-repo) for the order to fix them
in, and [Reading a gate failure](#reading-a-gate-failure) for what each one means.

## Use cases

### Stop `.tscn`/`.tres` churn in your diffs

The symptom: files you did not edit show up in every commit, and `git checkout --` is a reflex. Three
causes, fixed in this order:

1. **Path-only `ext_resource` refs.** Godot 4.4+ silently rewrites these to uid-in-refs on any editor
   or import pass. Migrate once — see [the appendix](#appendix-migrating-to-canonical-uid-in-refs) —
   then `check tres` keeps the tree canonical.
2. **What `PackedScene.pack()` drops.** Saving from the editor loses the header uid, `index=` on
   instance children, and `[editable path=]`. `scene canonicalize` restores them from evidence.
3. **Redundant `@export` defaults.** Hand-authored `.tres` spells every property out; Godot's writer
   omits anything equal to the default, so the file diffs forever.
   `scene canonicalize --elide-defaults` deletes exactly those lines — opt-in, because it removes
   lines. Then `check defaults` holds it.

### Edit a scene you can't afford to read

`scene --paths` prints an address; every write verb takes that same address. All of them accept
`--dry-run`, print a unified diff, and are idempotent.

```bash
godot-devkit scene rename   <file> <node-path> <new-name>
godot-devkit scene set      <file> <node-path> <prop> <value>
godot-devkit scene add      <file> <parent-path> <name> <type> [--script res://x.gd]
godot-devkit scene rm       <file> <node-path>
godot-devkit scene reparent <file> <node-path> <new-parent>
```

A TileMapLayer's grid is the extreme case of the same problem: the whole map is one base64 property,
so *"how far does this wall go"* is unreadable and *"fill these twelve cells"* has no hand form at
all. `tiles` answers the first and `tiles paint`/`erase` do the second, regenerating only that one
property:

```bash
godot-devkit tiles <file.tscn> --layer WallLayer --cols       # per-column counts: where it stops
godot-devkit tiles paint <file.tscn> --layer WallLayer --region 4,0,9,0 --tile 2/1,3
godot-devkit tiles erase <file.tscn> --layer WallLayer --region 4,0,9,0
```

`rename` rewrites every reference to the node — descendants' `parent=`, `[connection]`,
`[editable path=]`, and relative `NodePath("...")` literals resolved against the node that owns them.
A verb that cannot guarantee a correct result **refuses and says why**; it never edits partially.

### Catch Godot's silent failures in CI

The failure mode these exist for is a scene that loads fine and is half-configured, with every gate
green:

- **`check props`** — an assignment to a property that no longer exists. Rename an `@export` and
  Godot drops the old assignment without a word.
- **`check uid`** — `.uid` sidecar drift, which surfaces as cold-cache `invalid UID … using text path`.
- **`check tres`** — path-only refs (the churn cause above).
- **`check defaults`** — redundant defaults.

Wire `check all` (uid + tres + props + doc + shell) into your per-change gate;
`check repo-hygiene` is close-time and hits the network; `check defaults` and `check pm` are explicit.

### Adopt the gates on an existing repo

Order matters — some start red by design:

| Step | Command | Expect |
|---|---|---|
| 1 | `check uid` | Red if `.uid` sidecars are untracked. Commit them; the policy is the gate. Stale refs clear with `check uid --fix`. |
| 2 | [uid-in-refs migration](#appendix-migrating-to-canonical-uid-in-refs) → `check tres` | Red until migrated once. |
| 3 | `check props` | Findings are real renamed-export bugs. Fix before wiring. |
| 4 | `scene canonicalize --elide-defaults` → `check defaults` | Red on any tree never canonicalized. Clean once, then gate. |
| 5 | Wire `check all` | Green. |

### Track work in a markdown PM tree

Milestones → features → stories, as markdown with YAML frontmatter. The point of a CLI is that
`status:` is the one field a human should never hand-edit:

```bash
godot-devkit pm init                       # tree + guidance + a wiring checklist
godot-devkit pm new milestone 0.1 "First"
godot-devkit pm new feature 0.1 groundwork "Groundwork"
godot-devkit pm story wip 0.1/groundwork/it-boots
godot-devkit pm status                     # the single live read
godot-devkit pm validate                   # ids, parentage, refs, graph
```

`pm install-skills` writes the shared doctrine into the repo: an auto-loading rule carrying the
claim→close loop, and a `pm-operations` skill carrying the manual. Your own SDLC — branching,
release ceremony, who reviews what — stays in your own rules.

### Adapt it to your repo's conventions

Everything project-specific is `devkit.toml` ([reference](#configuration--devkittoml)). Grain
templates are files: set `[pm] template_dir`, run `pm templates` to copy them out, edit the markdown.
A file present there wins; anything missing falls back to the packaged default, so overriding one
grain does not make you responsible for the rest.

## Reading a gate failure

Every gate prints a **census** of what it scanned, then a verdict — on the FAIL line as much as on
the PASS line, because "1 malformed doc" out of one document and out of two hundred are different
reports. Read the census first — a gate that scanned fewer files than you expected is telling you
your config is wrong, not that your tree is clean. A gate that scans **zero** files fails rather than
passing, deliberately, and a file it could not DECODE is reported and dropped from the count rather
than counted as scanned.

```
[check:tres] FAIL — scanned 0 files; check [tres] exclude_prefixes
```

That is a config problem, not drift. A real finding names the file:

```
[check:pm] FAIL — 1 status-drift violation(s) across 18 milestone(s), 12 feature(s), 28 story/ies
  DRIFT  feature 0.28.0/chronicle-bus is done w/o review record  [pm/roadmap/…/feature.md]
```

**Precision over reach.** Nothing is reported as a finding unless the whole picture resolved;
anything unresolvable is censused as `UNVERIFIED`/`UNVERIFIABLE` and never failed. A false PASS is
survivable — a false FAIL gets the gate switched off, and then nothing is checked at all.

**Exit codes are contract:** `0` pass · `1` findings · `2` usage or config error. A `devkit.toml`
mistake is always `2`, never `1`, so CI can never read a typo as drift.

## Command reference

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
| `tiles <file.tscn> [--layer NAME] [--cols] [--rows] [--at X,Y] [--region X0,Y0,X1,Y1]` | A TileMapLayer's grid, decoded: cell count, bounds, tile-kind histogram; `--cols`/`--rows` give per-column/row counts (how you find where a wall stops), `--at` the tile at one cell, `--region` the census inside an inclusive rectangle |

A shared parser (`tscn.py`) all of them compose — sections, properties, resource-ref resolution — plus
one `tile_map_data` codec (`tilemap.py`) shared by the read and write sides.

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
| `tiles paint <file> --layer NAME --region X0,Y0,X1,Y1 --tile SRC/AX,AY[/ALT]` | Fill a rectangle of one TileMapLayer, replacing whatever was there. Only that one `tile_map_data` assignment is regenerated |
| `tiles erase <file> --layer NAME --region X0,Y0,X1,Y1` | Delete every cell in a rectangle |

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
| `check uid` | `.uid` sidecar drift: every tracked `.gd` has a tracked `.gd.uid`; every Script `ext_resource` uid matches the target's actual `.uid`. Prevents cold-cache `invalid UID … using text path` failures. **`check uid --fix`** applies the repair the gate already computes — each stale ref rewritten to the target's sidecar value, byte-surgically (only the `uid="…"` attribute on that line), then exits 0 so a re-run is clean. A drift with no should-be value (the target has no `.uid` at all) stays a finding: minting one would be invention, not repair. `--fix` on a clean tree is a no-op that says so; on any other gate, or on `check all`, it is a usage error. |
| `check tres` | Path-only `ext_resource` refs (missing `uid=`). Godot 4.4+ silently upgrades these on any editor/import pass — churn that leaks into unrelated commits. Migrate once, then this keeps the tree canonical. |
| `check props` | Assignments to properties that **do not exist** — the export was renamed or deleted and the scene still names the old one. Godot drops such an assignment silently, so the node comes up half-configured with every gate green. Checks scene nodes, sub_resources and `.tres` resources against the script's `@export` chain and the engine's ClassDB. Nothing is called dead unless the whole picture resolved; everything else is censused as UNVERIFIED, never failed. |
| `check defaults` | `.tres` assignments that repeat the script's declared `@export` default. Hand-authored data spells every property out; Godot's writer omits the defaults — so the file diffs forever, and the mop-up is `git checkout --` every session. Judges the elision dimension ONLY (see below); anything outside a small closed value language is censused, never reported. |
| `check doc` | Dead claims in always-loaded agent docs (`CLAUDE.md` + `.claude/rules/` + `.claude/agents/`): dead links, dead `make` targets, dead file paths. |
| `check repo-hygiene` | Close-time git-state cruft: dirty tree, stashes, dangling worktrees, merged-but-undeleted branches. Runs `git fetch --prune` — wire it into your close gate, not your per-change gate. |
| `check agents` | Agent/rule/skill definitions that instruct what the tooling refuses: a `pm <grain> <verb>` the CLI has no verb for, a `<state> -> <state>` its graph rejects, and a skill written as a flat `<name>.md` instead of `<name>/SKILL.md` (which never loads as a skill at all). The vocabulary comes from the pm model itself — see `pm vocabulary --json` — so the checker cannot drift from the tool it checks. Add your own house rules with `[agents] forbidden`. |
| `check pm` | PM-tree status drift: a `done` feature with no substantive review record, a feature whose stories are all done but never advanced, a `done` milestone with live children, a status outside the schema, a `done` story under a live feature, a `building` milestone with everything closed, and an overdue archive prune. Shares its predicates with the `pm` CLI, so the gate and the tool cannot disagree. **Also runs the `pm validate` integrity rules (V1–V5) by default**, so the gate fails on a dangling `depends_on` as well as on status drift. Off by default in `check all` — a repo with no PM tree has no drift to find. Three further rules (D8/D9/D10) gate the branch-per-milestone + bump-at-start flow, D11 retires a `done` grain's transient `review.md`, D12 holds every `decisions.md` entry to the four-field decision schema (`Chose`/`Over`/`Because`/`Evidence`), D13 holds every grain dir to the canonical slots (missing is drift **and** extra is drift, headers included), D14 reports an open bug parked under a `done` milestone, D15 holds every `changelog.md` entry to the two-field release-note schema (`What`/`Evidence`), D16 fails a `done` milestone whose changelog is empty, D17 caps the PROSE of every grain document as a ratchet (a story, a `feature.md`, a bug, a feature's `decisions.md`, a milestone's `changelog.md`), and D18 fails a `done` milestone still carrying its raw decision trail — all opt-in via `[pm] checks`, with D12's, D15's and D17's legacy text migrating through the `decision_grandfather` / `changelog_grandfather` / `prose_grandfather` ledgers the gate prints the size of. |
| `check shell` | Lints every shell script under `tools/` (incl. extension-less hook entry points), `shellcheck -x`. Soft-skips if shellcheck isn't installed. |
| `check all` | The offline fast set — `uid` + `tres` + `props` + `doc` + `shell` by default. **`[checks] all` names the roster for your repo**: five of the eight gates read `.tscn`/`.tres` or shell scripts, so a repo holding none of them gets five 0-file censuses and rule 4 correctly reddens each one. That is the roster being wrong for the repo, not a reason to soften a gate — name the gates that apply and run the rest on demand. An unknown gate name is exit 2, never a quietly narrowed run. |

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
| `pm milestone <ready\|building\|done> <id>` | Milestone flips; `done` refuses unless every feature is done. With `[pm] place_branch_on_building`, `building` also checks that milestone's `branch:` out in the **trunk** worktree — the same state D10 asserts. Every refusal (no `branch:`, missing branch, a branch another worktree holds, a dirty or unreadable trunk) lands **before** the flip; a checkout that fails after it exits 2 and the re-run is the repair |
| `pm status [<milestone>]` | Tree report, drift-aware, grouped by the optional `phase:` bucket |
| `pm validate` | Structural + referential integrity: frontmatter well-formed, ids match paths, parentage consistent, `depends_on`/`consumed_by` resolve, the feature graph acyclic and phase-monotone. A ref into a **pruned** milestone is censused as UNVERIFIABLE, never failed — git history is the archive |
| `pm new <milestone\|feature\|story\|bug> …` | Scaffold a grain from templates — every canonical slot, all lowercase (`milestone.md`/`handoff.md`/`decisions.md`/`changelog.md`/`review.md` + `features/ bugs/ design/`; a feature gets `feature.md`/`decisions.md`/`review.md` + `stories/ design/`). `new milestone` and `new feature` are **idempotent**: run against an existing grain they fill the gaps, rename a slot present under another case, restore a missing header line, and leave every other byte alone — which is how a tree migrates. The `<name>` is optional once the grain exists. `review.md` is never minted on a `done` grain; `changelog.md` always is, because a closed milestone is when its notes matter most. Every failure out is a **refusal**, never a stack trace — including the grain directory or file the filesystem itself will not take (a name past NAME_MAX, an unwritable parent), which answers the same way on every supported Python |
| `pm decide <grain-id> --chose … --over … --because … --evidence … [--title …]` | Append a D12-conforming entry to that milestone's or feature's `decisions.md`. The tool stamps the ISO date and the next ordinal in the log's own id prefix. `--over` is **required** — a decision with no rejected alternative is a description — and every value is validated by re-parsing the composed entry through D12's own predicates, so a non-conforming entry is refused with the log byte-identical rather than written and then reported |
| `pm decisions <grain-id>` | Print that grain's decision entries, parsed and deterministic — the READ half of the contract `decide` writes. A milestone prints its own log **and its features'**. The document goes to stdout and the count to stderr. Exists so answering "what did we decide in milestone xyz" is never a `find` piped to a `grep`: that is a second parser with none of the fence and comment handling, and it disagrees with the gate on exactly the logs where it matters |
| `pm changelog <milestone-id> --what … --evidence … [--title …]` | Append a D15-conforming release note to that milestone's `changelog.md`. Two fields and no more — **what was built that a player cares about**, and the reference proving it shipped; the reasoning is a *decision* and belongs in `decisions.md`. A **milestone** log: a feature contributes through the entry's `Evidence:` pointer, and naming one is refused. Same machinery as `decide` — the tool stamps the ISO date and the next ordinal in the log's own prefix, and re-parses the composed entry through D15's own predicates, so a refusal leaves the log byte-identical |
| `pm changelog --render [--milestone <id>]` | The union of every milestone's `changelog.md` to **stdout**, newest release first — a render the consumer redirects, so every count and skip goes to stderr instead. Milestones are ordered by **declared version, compared component-wise**, never by directory-name string sort (`0.9` sorts *before* `0.10` lexically and *after* it numerically); entries come out in the order their append-only log holds them. Same tree, same bytes, every run |
| `pm prose-ledger` | Regenerate D17's debt ledger — `prose_grandfather = [...]` to **stdout**, ready to paste into `devkit.toml`, with the count on stderr. It **REFUSES to raise** a ceiling: a document larger than the one recorded for it is reported and nothing is printed, so the only way to regenerate is after a genuine trim. Without that refusal the ratchet would be decorative — every growth would be absorbed by a regeneration. A document back inside its cap is dropped rather than re-recorded, so what comes out is gate-clean by construction |
| `pm get <grain-id> <key>` · `pm set <grain-id> <key> <value>` | Read/write one frontmatter field **through code**, not a regex. `status` is refused — it has a transition graph behind it |
| `pm claim <grain-id> <owner>` · `pm release <grain-id>` | Sugar over `owner:` — the field that was hand-edited everywhere `status:` was not |
| `pm vocabulary [--json]` | The states, transitions and verbs, machine-readably. Exists so an external checker never has to scrape help text — a tool that states its own rules in a parseable form is the only way a scanner stays honest when the rules change |
| `pm sync [--check]` | Re-render the execution lists: a milestone's feature order, a feature's story order, both derived from `phase:` and `depends_on`. Opt-in per file; **V6** fails when a rendered block drifts from the tree |
| `pm templates [--force]` | Copy the packaged templates into `[pm] template_dir` to edit. A file present there wins; anything missing falls back, so overriding one grain does not mean owning them all |
| `pm prune` | Delete cooled archives and stamp the resurrect anchor in the roadmap's prune log |
| `pm install-skills [--force]` | Write the shared guidance into the repo: `.claude/rules/pm-execution.md` (the claim→close loop, **auto-loads** on a `pm/roadmap/**` edit) and `.claude/skills/pm-operations/SKILL.md` (the operations manual, invoked deliberately). Refuses to clobber a file it did not generate |
| `pm init` | Stand up a tree in a repo that has none — `pm/roadmap/` + a seeded `ROADMAP.md`, the two guidance files, and the remaining wiring printed as a checklist |

**Why a rule AND a skill, not one of each.** A rule with a `paths:` header **auto-loads**
for any agent that touches the matched files; a skill must be invoked. The claim→close loop
is a protocol whose whole purpose is preventing status/reality drift, so it cannot depend on
something remembering to ask for it — it has to arrive unasked. The operations manual is the
opposite: consulted deliberately when planning or restructuring, and it would be pure cost
loaded on every edit. Same content split by *when it needs to be in front of you*.

**What ships as guidance, and what does not.** The two installed files carry only the loop the CLI
itself enforces and the manual for the tree it operates. A project's own SDLC — branching, versioning,
release ceremony, agent dispatch, who reviews what, and what a milestone *means* in that codebase —
stays in that project's own rules and agents, because it differs per repo and always will. The
installed files are generated: edit them and the next install refuses rather than overwriting.

Exit codes follow the house contract: `0` ok (including an idempotent no-op), `1` refused, `2` usage.
The vocabularies, the transition graphs, the review-record definition and the drift predicates live
in one module that both the CLI and `check pm` import — one definition, two readers.

## Configuration — `devkit.toml`

Optional, at the consuming repo root. Every tool works with stock defaults; a
section overrides only what it names:

```toml
[checks]
# Which gates `check all` runs HERE. Default: uid, tres, props, doc, shell.
# A repo with no Godot tree (a PM-tree-only consumer, this package itself) names
# the ones that apply rather than absorbing five 0-file censuses.
all = ["doc", "pm", "agents"]

[autoloads]
suffixes = { Manager = "emits", Tracker = "relays", Registry = "inert", Store = "inert", Service = "inert" }
expected_prefixes = ["autoloads/core/", "autoloads/sim/", "autoloads/presentation/"]

[doc]
scope = ["CLAUDE.md", ".claude/rules/*.md", ".claude/agents/*.md"]
ephemeral = ["docs/reviews/"]

[uid]
exclude_prefixes = ["addons/"]   # scopes BOTH uid checks, not just the ref one

[tres]
exclude_prefixes = ["addons/"]

[props]
exclude_prefixes = ["addons/"]

[agents]
# Definitions to scan (default: .claude/{agents,rules}/*.md + skills/**)
scope = [".claude/agents/*.md", ".claude/rules/*.md", ".claude/skills/**/*.md"]
# House rules, as regexes. An agent definition matching one is a finding.
forbidden = ["godot --headless"]

[pm]
roadmap_dir  = "pm/roadmap"     # the tree, relative to the repo root
template_dir = "pm/templates"   # REQUIRED to override a grain template
review_dir  = "docs/reviews"    # where review records live
review_min_content_bytes = 20   # anti-rubber-stamp floor (non-whitespace bytes)
review_slug_fallback = false    # also accept <review_dir>/<feature-slug>*.md
story_ordinal_prefix = false    # also resolve stories/NN-<slug>.md
place_branch_on_building = false  # `pm milestone building` also checks that
                                #   milestone's `branch:` out in the trunk
checks = ["D1","D2","D3","D4","D5","D6","D7",   # drift rules
          "V1","V2","V3","V4","V5"]             # integrity rules (see `pm validate`)
# D8/D9/D10 are the FLOW rules — opt in by naming them here:
#   D8  project version == the `building` milestone's id (bump at START; the id
#       IS the version, exact string equality)
#   D9  a `building` milestone declares `branch:`
#   D10 that branch is checked out in the TRUNK worktree
# A project that ships from the trunk and bumps at close is running a different
# valid flow, so these stay off unless asked for.
# D11-D16 opt in the same way:
#   D11 a `done` grain must not have a `review.md`. The slot is the TRANSIENT
#       half of the pair: reviewer and simplifier append to it while the grain
#       is open, and at close anything durable moves into decisions.md and the
#       file goes. Co-located, so there is no filename to resolve.
#   D13 every milestone/feature dir carries exactly its canonical slots, and
#       each shared doc still opens with its instruction header. MISSING is
#       drift AND EXTRA is drift — `plans/`, `findings/` and a hand-named
#       AUDIT-REPORT.md exist because nothing ever flagged the invention.
#       Directory slots are permitted, not required: git stores no empty dir.
#       `pm new milestone|feature <id>` is idempotent and fills the gaps.
#   D14 an OPEN bug under a `done` milestone. A bug lives in the milestone that
#       will FIX it (`caught_in:` keeps provenance, `fix_milestone:` names the
#       decision), and prune's lag-by-one deletes a closed milestone's dir — so
#       this rule is what makes prune safe by construction. Also reports a bug
#       status outside bug_states, which D4 does not cover.
#       `bugs/` and `stories/` are walked RECURSIVELY, with the extension
#       compared case-insensitively, so a document one directory down or named
#       `.MD` is not invisible. A grain IS its frontmatter: a `.md` in either
#       slot with no leading `---` block is a note parked beside the grains
#       (a README, a sketch), not a bug or a story with an empty status.
#   D12 every `## <ID> — <ISO date> — <title>` entry in a decisions.md carries
#       **Chose:** / **Over:** / **Because:** / **Evidence:**, in that order, one
#       per line, values <= 200 chars and the title <= 80. `Over:` is the
#       load-bearing one — an entry that cannot name what it ruled out is a
#       description, not a decision — and `Evidence:` must be a REFERENCE (a
#       commit hash, a path[:line] or a number), never a sentence. A `##`
#       heading is an ENTRY if it carries an id or a date, or if any
#       `**Word:**` field line appears beneath it — the field line is what a
#       title-reading detector cannot see. A heading with neither is prose and
#       is never checked, so a log may open with a preamble.
#   D15 the same machinery over `changelog.md`, whose entries carry **What:**
#       (one sentence a player would recognise) and **Evidence:** (the
#       reference proving it shipped). Deliberately the SMALLER schema: the
#       reasoning behind a change is a decision and lives in decisions.md, so a
#       changelog carrying it is a commit log with a nicer name.
#   D16 a `done` milestone must have a non-empty changelog.md holding at least
#       one entry D15 does not report. D15 asks whether what is written
#       conforms — and a conforming EMPTY log satisfies it forever; D16 is what
#       stops a release shipping with nothing a player can read.
#   D17 the PROSE RATCHET. Everything written into a PM tree is grep-reachable,
#       so every line of prose is context some future agent pays for — the
#       scaffolding should not be twice the size of the thing it scaffolds. A
#       story, a feature.md, a bug, a feature's decisions.md and a milestone's
#       changelog.md each get a line cap, with two finding classes: OVERCAP
#       (over cap, not on the ledger) and GREW (on the ledger, larger than its
#       recorded ceiling). The mandated instruction header D13 asserts is
#       EXCLUDED from every count — it is a constant an author cannot trim, so
#       counting it would make the budget uncompliable. A shape gate, not a
#       style gate: a story that genuinely needs 200 lines is usually two.
#       NOT capped: an OPEN milestone's own decisions.md, which is the
#       append-only autonomous-mode trail by design.
#   D18 a `done` milestone still carrying its RAW decision trail. Milestone
#       close evidence is pointers — "a line and a link" — so a done milestone
#       with a 1,600-line trail was not closed, it was abandoned. Its threshold
#       comes from that rule, not from any distribution.
bug_states      = ["open", "fixed", "closed"]   # D14: the bug vocabulary
bug_open_states = ["open"]                      # D14: which of those are OPEN
decision_grandfather = [                        # D12: logs that predate the schema
    "pm/roadmap/0.9-old/decisions.md",          #   the whole log is exempt
    "pm/roadmap/0.10-mid/decisions.md:12",      #   its first 12 entries are
]
changelog_grandfather = [                       # D15: the same ledger, same shape
    "pm/roadmap/0.9-old/changelog.md:4",        #   its first 4 entries are exempt
]                                               # The gate PRINTS each ledger's size
# every run, and a ledger may only SHRINK: an exemption that suppresses nothing,
# a cap reaching past the end of its log, and a line naming no log all FAIL. The
# capped form is the point — legacy entries stay, new ones still have to conform.
# D16 reads the changelog ledger too, so an entry D15 has been told to accept is
# never one D16 rejects.
# D17's caps. CONFIG, not constants. The defaults sit at roughly the p90 of ONE
# consumer's measured distribution (story median 74 / p90 119, feature.md 81 /
# 203, bug 73 / 124, feature decisions.md 98 / 273), so the median document is
# untouched and only the outliers must shrink. They are that consumer's
# distribution, NOT a law — another tree's is its own, and a cap that fits one
# repo misfires on the next. `decisions_lines_max` is deliberately tight
# relative to its p90 and `changelog_lines_max` takes the same number: both
# logs accumulate by design, and both are written by `pm decide`/`pm changelog`
# as declarations rather than narrative. `closed_log_lines_max` is not a
# distribution number at all — it is the close-evidence budget, about twenty
# pointer lines plus headers. A cap under 1 is a config error, not a finding.
story_lines_max      = 120                      # D17
feature_lines_max    = 200                      # D17
bug_lines_max        = 125                      # D17
decisions_lines_max  = 150                      # D17: a FEATURE's decisions.md
changelog_lines_max  = 150                      # D17
closed_log_lines_max = 60                       # D18: a `done` milestone's trail
prose_grandfather = [                           # D17/D18: documents already over
    "pm/roadmap/0.9-old/features/a/feature.md:274",   # cap, at their CURRENT size
]                                               # The ceiling is REQUIRED — an
# entry without one would be a permanent uncapped pass, which a ratchet cannot
# have. Same shrink-only rules as the log ledgers: an entry that suppresses
# nothing, a ceiling reaching past the end of its file, and a line naming no
# document each FAIL. `pm prose-ledger` regenerates it and REFUSES to raise a
# ceiling, so the only way to regenerate is after a genuine trim.
version_file = "project.godot"                  # D8: where the version lives
version_pattern = '^config/version="(.*)"$'     # D8: the line that carries it
trunk_branches = ["staging", "main"]            # D10: `branch: staging` = no integration branch
# Vocabularies + graphs are overridable too: milestone_states, feature_states,
# story_states, milestone_transitions, feature_transitions, story_transitions.
# The stock graph is the STRICT one: the story terminal is `review` (`done`
# comes only from the feature cascade) and milestones have no `review` state.


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

## Wiring it into your project

Pin the tag once; every target routes through it, so a bump is a one-line diff:

```make
DEVKIT_VERSION := v0.9.0
DEVKIT := uvx --from "git+https://github.com/cdowin/godot-devkit@$(DEVKIT_VERSION)" godot-devkit

# per-change gate — fast, offline, no Godot boot
check:        ; @$(DEVKIT) check all

# individually, if you want named targets
uid-scan:     ; @$(DEVKIT) check uid
tres-scan:    ; @$(DEVKIT) check tres
prop-scan:    ; @$(DEVKIT) check props
doc-scan:     ; @$(DEVKIT) check doc
shell-scan:   ; @$(DEVKIT) check shell
pm-scan:      ; @$(DEVKIT) check pm

# close-time only: repo-hygiene fetches from the network;
# defaults is red until the tree is canonicalized once
repo-hygiene:  ; @$(DEVKIT) check repo-hygiene
defaults-scan: ; @$(DEVKIT) check defaults

# read + write verbs
scene:        ; @$(DEVKIT) scene $(FILE) $(ARGS)
scene-diff:   ; @$(DEVKIT) scene-diff $(FILE) $(ARGS)
scene-set:    ; @$(DEVKIT) scene set $(FILE) $(ARGS)
scene-canon:  ; @$(DEVKIT) scene canonicalize $(FILE) $(ARGS)
refs:         ; @$(DEVKIT) refs $(NAME) $(ARGS)
orphans:      ; @$(DEVKIT) orphans $(ARGS)
autoloads:    ; @$(DEVKIT) autoloads
```

**Per-change vs close-time is the split that matters.** `check all` is the offline fast set and
belongs in your pre-commit or pre-push hook. `check repo-hygiene` hits the network and `check
defaults` is red on any tree that has never been canonicalized — wire both at milestone close, or
deliberately after a cleanup pass.

## Design commitments & northstar

### Goal

**Give developers and LLMs simple, sharp tools to parse and work with Godot's text scene formats
(`.tscn` / `.tres`) without opening the editor.** A `.tscn` is text, so every structural question and
every structural change should be answerable by one command that runs in milliseconds, anywhere, in
parallel — not by loading a hundred thousand tokens of packed bytes into a human's head or a model's
context.

### Northstar

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
  consumer parses instead of regexing prose.
- **Prove the edit without re-reading it.** `scene-diff` closes the loop: make the change, confirm
  exactly what moved, still without loading the file.
- **Encode the footguns as gates.** Godot has silent-failure modes — a property assigned to a script
  that no longer declares it, an `ext_resource` that lost its `uid=`, an instance override missing
  `index=`. Nobody should have to *remember* those. The toolkit should refuse to let them through, so
  the knowledge lives in a gate instead of in a person or a prompt.
- **Bounded blast radius.** A verb changes what it was asked to change and nothing adjacent.


### Design commitments & northstar

### Goal

**Give developers and LLMs simple, sharp tools to parse and work with Godot's text scene formats
(`.tscn` / `.tres`) without opening the editor.** A `.tscn` is text, so every structural question and
every structural change should be answerable by one command that runs in milliseconds, anywhere, in
parallel — not by loading a hundred thousand tokens of packed bytes into a human's head or a model's
context.

### Northstar

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
  consumer parses instead of regexing prose.
- **Prove the edit without re-reading it.** `scene-diff` closes the loop: make the change, confirm
  exactly what moved, still without loading the file.
- **Encode the footguns as gates.** Godot has silent-failure modes — a property assigned to a script
  that no longer declares it, an `ext_resource` that lost its `uid=`, an instance override missing
  `index=`. Nobody should have to *remember* those. The toolkit should refuse to let them through, so
  the knowledge lives in a gate instead of in a person or a prompt.
- **Bounded blast radius.** A verb changes what it was asked to change and nothing adjacent.

### Design commitments

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

## Appendix: migrating to canonical uid-in-refs

If your tree has path-only `ext_resource` refs: (1) for targets whose header has no uid at all, mint one with Godot's own `ResourceUID.create_id()` in a headless pass — **never hand-author uid strings**, invalid uids poison the cache; (2) inject each target's uid into the referencing `ext_resource` lines; (3) prove it cold: delete `.godot/`, run a headless `--import`, confirm zero `invalid UID` warnings. Then land `check tres` in your gates so the tree can never drift back.

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

## License

MIT — see [LICENSE](LICENSE).

