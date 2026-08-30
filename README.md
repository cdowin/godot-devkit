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
  a status you move through code and a gate that reports a tree contradicting itself.
  → [Track work in a markdown PM tree](#track-work-in-a-markdown-pm-tree)

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
[check:tres] FAIL — scanned 0 of 13 tracked .tres/.tscn; check [tres] exclude_prefixes
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

**A stale rule id stops the GATE, not the read verbs.** `[pm] checks` naming a rule this
package no longer ships — which is what a pin bump retiring one produces — is exit 2 from
`check pm` and `pm validate`, and from nothing else. `pm status`, `pm get`, `pm new`
and `pm vocabulary --json` keep working, so you can read your own tree AND ask the tool
what the closed set became while deciding what to change. Learning the new roster must
not require the config to already be right about it.

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

### Installers (`godot-devkit install-<what>`)

An install verb writes a file. **Once.** If the destination is already there and is not byte-for-byte
what would be written, the command refuses, names the path, and names both remedies — move it aside,
or `--force`. `--diff` prints a unified diff of what a run would change and writes nothing. There is
no manifest, no content hash, no drift tracking and no merge: after the file is written it belongs to
the repo that asked for it. Every refusal is decided for **every** entry before the first byte, so a
collision on the third file leaves the first two unwritten.

| Verb | Writes |
|---|---|
| `install-ci [--force] [--diff]` | `.github/workflows/verify.yml` — one opinionated workflow: checkout, uv, `make milestone`. It carries no gate of its own and nothing to parameterize; the assumption that `make milestone` is your full gate is a **comment in the file**, not a discovery mechanism. A project that wants something else edits the workflow, which is now its file |
| `install-agents [--force] [--diff]` | `.claude/agents/verification-reviewer.md` + `verification-builder.md` — the review and build contract, as **agent definitions**. Deliberately not `.claude/rules/*`: a rules file never reaches a subagent's spawn context while its definition does, so a contract written as a rule arrives nowhere. Your project's own agents, rosters and dispatch model stay yours |
| `install-hooks [--force] [--diff]` | `tools/hooks/cc-commit-pathspec.sh` (a Claude Code PreToolUse guard: `git commit` commits the whole index, so in a shared tree a commit names its own paths), `tools/hooks/cc-godot-sandbox.sh` (never a raw `godot` boot — it runs the autoload stack against the real `user://`), and `tools/setup-hooks.sh`, which points `core.hooksPath` at them and sets the exec bit. Each hook is **standalone** — it sources no library, because a `source` of a file your repo does not have fails open and a guard that fails open is not there. Run `bash tools/setup-hooks.sh` after installing |

`pm install-skills` is the fourth install verb and shares these refusals; it lives under `pm` because
what it writes is the PM tree's own guidance.

### Static gates (`godot-devkit check <gate>`, pure git + parse, no Godot boot)

| Gate | Guards against |
|---|---|
| `check uid` | `.uid` sidecar drift: every tracked `.gd` has a tracked `.gd.uid`; every Script `ext_resource` uid matches the target's actual `.uid`. Prevents cold-cache `invalid UID … using text path` failures. **`check uid --fix`** applies the repair the gate already computes — each stale ref rewritten to the target's sidecar value, byte-surgically (only the `uid="…"` attribute on that line), then exits 0 so a re-run is clean. A drift with no should-be value (the target has no `.uid` at all) stays a finding: minting one would be invention, not repair. `--fix` on a clean tree is a no-op that says so; on any other gate, or on `check all`, it is a usage error. |
| `check tres` | Path-only `ext_resource` refs (missing `uid=`). Godot 4.4+ silently upgrades these on any editor/import pass — churn that leaks into unrelated commits. Migrate once, then this keeps the tree canonical. |
| `check props` | Assignments to properties that **do not exist** — the export was renamed or deleted and the scene still names the old one. Godot drops such an assignment silently, so the node comes up half-configured with every gate green. Checks scene nodes, sub_resources and `.tres` resources against the script's `@export` chain and the engine's ClassDB. Nothing is called dead unless the whole picture resolved; everything else is censused as UNVERIFIED, never failed. |
| `check defaults` | `.tres` assignments that repeat the script's declared `@export` default. Hand-authored data spells every property out; Godot's writer omits the defaults — so the file diffs forever, and the mop-up is `git checkout --` every session. Judges the elision dimension ONLY (see below); anything outside a small closed value language is censused, never reported. |
| `check doc` | Dead claims in always-loaded agent docs (`CLAUDE.md` + `.claude/rules/` + `.claude/agents/`): dead links, dead `make` targets, dead file paths. Plus one fact about placement: a skill written as a flat `.claude/skills/<name>.md` instead of `<name>/SKILL.md` never loads as a skill at all, so its description never fires. |
| `check repo-hygiene` | Close-time git-state cruft: dirty tree, stashes, dangling worktrees, merged-but-undeleted branches. Runs `git fetch --prune` — wire it into your close gate, not your per-change gate. |
| `check pm` | PM-tree status drift: a `done` feature with no substantive review record, a feature whose stories are all done but never advanced, a `done` milestone with live children, a status outside the schema (milestones, features, stories **and bugs**), a `done` story under a live feature, and a `building` milestone with everything closed. Shares its predicates with the `pm` CLI, so the gate and the tool cannot disagree. **Also runs the `pm validate` integrity rules (V1–V6) by default**, so the gate fails on a dangling `depends_on` as well as on status drift. Off by default in `check all` — a repo with no PM tree has no drift to find. Two further rules (D8/D9) gate the branch-per-milestone + bump-at-start flow, opt-in via `[pm] checks`. |
| `check shell` | Lints every shell script under `tools/` (incl. extension-less hook entry points), `shellcheck -x`. Soft-skips if shellcheck isn't installed. |
| `check all` | The offline fast set — `uid` + `tres` + `props` + `doc` + `shell` by default. **`[checks] all` names the roster for your repo**: five of the eight gates read `.tscn`/`.tres` or shell scripts, so a repo holding none of them gets five 0-file censuses and rule 4 correctly reddens each one. That is the roster being wrong for the repo, not a reason to soften a gate — name the gates that apply and run the rest on demand. An unknown gate name is exit 2, never a quietly narrowed run. |

### Project management (`godot-devkit pm <command>`)

Filesystem-backed milestone → feature → story tracking: markdown with YAML frontmatter under
`pm/roadmap/`. The CLI writes ONE line and touches nothing else — no line endings, no adjacent
fields, no file the caller did not name. **Closed states, open transitions:** the state you ask
for is validated against that grain's vocabulary (`butterfly` is exit 2, naming the set), and the
state the file currently holds is never validated at all — it is read for the message. So
`pm milestone done 0.1` on a hand-edited `status: wombat` prints `wombat -> done` and repairs it,
which is exactly the drift `check pm` reports. There is no transition graph: nothing checks an
EDGE (D3/D4/D5 read the tree's END STATE), so a graph would only tax whoever used the sanctioned
tool while a `sed` of the same line reached the state it refused.

| Command | What it does |
|---|---|
| `pm story <status> <story-id>` | Set a story's status. Any value in `[pm] story_states`; anything else is exit 2 naming the vocabulary. The value it currently holds is read **for the message only** — `wombat -> done` — so the verb is the repair path for exactly the drift D4 reports, and an absent key is `(none) -> done` |
| `pm feature <status> <feature-id>` | Same, against `[pm] feature_states` |
| `pm feature review <feature-id>` | Moves the feature to `review` and REPORTS the stories that are not there. It does not refuse on their account — which stories are where is a fact, and it belongs in the output rather than in a veto |
| `pm feature done <feature-id> [--cascade] [--review-record <path>]` | Closes the feature. **Touches no story file** unless `--cascade`, which additionally moves that feature's stories at `review` to `done` in the same run. Either way it REPORTS the stories it did not touch and refuses nothing on their account. A `--review-record` naming no file IS refused, whole — stamping a pointer to nothing is the drift D1 reports |
| `pm milestone <status> <id>` | Set a milestone's status; `done` REPORTS any feature that is not done and moves anyway (D3 asks the same question of the tree it leaves). It does **not** touch your git checkout — a PM tracker that runs `git checkout` in your trunk worktree is a tracker mutating your VCS, and every refusal behind that was about the shape of a worktree elsewhere on your disk rather than about the input |
| `pm status [<milestone>]` | Tree report, drift-aware, grouped by the optional `phase:` bucket |
| `pm validate` | Structural + referential integrity: frontmatter well-formed, ids match paths, parentage consistent, `depends_on`/`consumed_by` resolve, the feature graph acyclic. A ref into a milestone no longer in the tree is censused as UNVERIFIABLE, never failed — git history is the archive |
| `pm new <milestone\|feature\|story\|bug> …` | Scaffold a grain — its own frontmatter file (`milestone.md` / `feature.md`) and nothing else. **No directory is minted**: git stores no empty directory, so 158 scaffolded `design/` dirs across one consumer left 11 holding anything; `stories/` appears when the first story is written into it. **A shared doc is NOT minted either**: `decisions.md` appears when `pm decide` records the first one, `handoff.md` and `review.md` when somebody writes one. Scaffolding them empty put 204 files and ~1,900 lines into one consumer's tree — a quarter of its PM tree, minted by the verb that exists to stop sprawl. `new milestone` and `new feature` are **idempotent**: run against an existing grain they fill the gaps, rename a slot present under another case, restore a missing header line on a doc that HAS one, and leave every other byte alone — which is how a tree migrates. The `<name>` is optional once the grain exists. Every failure out is a **refusal**, never a stack trace — including the grain directory or file the filesystem itself will not take (a name past NAME_MAX, an unwritable parent), which answers the same way on every supported Python |
| `pm get <grain-id> <key>` · `pm set <grain-id> <key> <value>` | Read/write one frontmatter field **through code**, not a regex — the field's value replaced, every other byte and the file's line endings preserved |
| `pm vocabulary [--json]` | The CLOSED sets, machine-readably: the states each grain kind may hold, and the rule ids `[pm] checks` may name. It prints no transitions — there are none. Its audience is the **pin bump**: the toolkit ships a shape, you bump the pin, and this is how you see what the closed set became without scraping a changelog. It keeps working when `[pm] checks` names a rule this release retired |
| `pm sync [--check]` | Re-render the execution lists: a milestone's feature order, a feature's story order, both derived from `phase:` and `depends_on`. Opt-in per file; **V6** fails when a rendered block drifts from the tree |
| `pm templates [--force]` | Copy the packaged templates into `[pm] template_dir` to edit. A file present there wins; anything missing falls back, so overriding one grain does not mean owning them all |
| `pm decide <grain-id> <title…>` | Append one `## <id> — <ISO date> — <title>` heading to that milestone's or feature's `decisions.md`, **minting the log from its template if this is the first one**. It stamps the two things a hand-written entry gets wrong — the date, and the next ordinal in the log's own id prefix — and stops there; the reasoning under the heading is yours to write. No field schema: the four-field one this replaced produced zero conforming entries across a consumer's 158 decision logs, so what it gated was whether anyone used the verb |
| `pm install-skills [--force] [--diff]` | Write the shared guidance into the repo: `.claude/rules/pm-execution.md` (the claim→close loop, **auto-loads** on a `pm/roadmap/**` edit) and `.claude/skills/pm-operations/SKILL.md` (the operations manual, invoked deliberately). Refuses to clobber a file it did not generate |
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
review_slug_fallback = false    # also accept <review_dir>/<feature-slug>*.md
story_ordinal_prefix = false    # also resolve stories/NN-<slug>.md
checks = ["D1","D2","D3","D4","D5","D6",       # drift rules
          "V1","V2","V3","V4","V5","V6"]        # integrity rules (see `pm validate`)
                                                # ^ this IS the stock default: a repo
                                                #   with no devkit.toml runs exactly
                                                #   these, so a config "declaring the
                                                #   defaults" must name V6 too
# D8/D9 are the FLOW rules — opt in by naming them here:
#   D8  project version == the `building` milestone's id (bump at START; the id
#       IS the version, exact string equality)
#   D9  a `building` milestone declares `branch:` — a required field in a state
# A project that ships from the trunk and bumps at close is running a different
# valid flow, so these stay off unless asked for.
# `bugs/` and `stories/` are walked RECURSIVELY, with the extension compared
# case-insensitively, so a document one directory down or named `.MD` is not
# invisible. A grain IS its frontmatter: a `.md` in either slot with no leading
# `---` block is a note parked beside the grains (a README, a sketch), not a bug
# or a story with an empty status — and the census says how many it skipped.
bug_states      = ["open", "fixed", "closed"]   # D4: the bug vocabulary
version_file = "project.godot"                  # D8: where the version lives
version_pattern = '^config/version="(.*)"$'     # D8: the line that carries it
# The vocabularies are overridable: milestone_states, feature_states,
# story_states. They are what D4 holds a grain to, and what the status verbs
# accept — there is no transition graph, so nothing constrains the ORDER.


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

