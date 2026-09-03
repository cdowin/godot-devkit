# godot-devkit

**godot-devkit** is a set of command-line tools for Godot projects. It tells you what's in your
files, scaffolds the structure you work in, and edits those files precisely — so you're not
rebuilding a pile of shell every time you need an answer or a change. Three verbs: it **informs**,
it **scaffolds**, it **edits**.

It ships as a pinned tag. A project bumps the pin, runs `install-* --diff` to see what changed, and
takes what it wants — which is how a lesson learned in one game reaches the other. Nothing here boots
Godot: it is pure text parsing over `.tscn`/`.tres`, git and markdown.

- **Stand a fresh project up in one command.** `init` writes the config, the PM tree, your
  two-line Makefile, the standard target set, the runners, the hooks (armed), the agent roster and
  the CI set — in order, idempotently. → [Wiring it in](#wiring-it-into-your-project)
- **Read a scene without loading it.** `scene` answers structure in a few hundred tokens where the
  file costs 100k+; `--props` adds every `[resource]`/`[sub_resource]` property value, packed data
  elided, each id verbatim — the address the write verbs take. → [Quickstart](#quickstart-five-minutes)
- **Edit a scene without reformatting it.** Path-addressed write verbs that change the lines you
  named and refuse rather than mangle. → [Scene surgery](#scene-surgery-write-verbs)
- **Gate the silent-failure classes.** Renamed exports, uid drift, path-only refs — the things Godot
  drops without a word. → [Static gates](#static-gates-godot-devkit-check-gate)
- **Run a project's work tree from the CLI.** Milestones, features and stories as markdown, with
  status moved through code and a gate that reports a tree contradicting itself.
  → [Project management](#project-management-godot-devkit-pm-command)

## Install

Consumed at a **pinned tag** so every machine and CI runs identical gate code:

```bash
uvx --from "git+https://github.com/cdowin/godot-devkit@v0.21.0" godot-devkit --version   # godot-devkit 0.21.0
```

Pin that string once in your Makefile ([Wiring it in](#wiring-it-into-your-project)) and bump it to
adopt a release. **Adopting a bump is three reads:** the CHANGELOG, `pm vocabulary` for what the
closed state/rule sets became, and `install-* --diff` for what the shipped files would change before
you let them.

## Quickstart: five minutes

Run these from inside a Godot repo. **See a scene's structure without loading it:**

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

Read output *is* write input: `--paths` adds a first column holding each node's full path (`.` is the
root, `Name` its child, `Parent/Name` deeper), and that is the address every write verb takes.

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

Nothing else is touched. Drop `--dry-run` to apply it; run it twice and the second run is a no-op.

**Then run the gates** — `godot-devkit check all`. On a repo that has never used this, **expect red**:
most trees have path-only `ext_resource` refs and missing `.uid` sidecars. That is the tool working.
See [Adopt the gates on an existing repo](#adopt-the-gates-on-an-existing-repo).

## Adopt the gates on an existing repo

A NEW project skips this section: `godot-devkit init` writes everything and step 5 below is already
done. This is the order for a tree that already has content in it.

Order matters — some start red by design. Steps 2 and 4 are also the cure for `.tscn`/`.tres` churn.
That churn — files you did not edit turning up in every commit — has three causes: path-only
`ext_resource` refs, which Godot 4.4+ rewrites silently on any editor or import pass; what
`PackedScene.pack()` drops (the header uid, `index=` on instance children, `[editable path=]`), which
`scene canonicalize` restores; and hand-authored `@export` defaults Godot's writer omits, which
`scene canonicalize --elide-defaults` deletes.

| Step | Command | Expect |
|---|---|---|
| 1 | `check uid` | Red if `.uid` sidecars are untracked, missing on a new `.gd`, or orphaned — or a uid spelling is non-canonical. Commit sidecars with their scripts; stale refs, spellings and orphans clear with `check uid --fix`. |
| 2 | [uid-in-refs migration](#appendix-migrating-to-canonical-uid-in-refs) → `check tres` | Red until migrated once. |
| 3 | `check props` | Findings are real renamed-export bugs. Fix before wiring. |
| 4 | `scene canonicalize --elide-defaults` → `check defaults` | Red on any tree never canonicalized. Clean once, then gate. |
| 5 | Wire `check all` | Green. |

## Reading a gate failure

Every gate prints a **census** of what it scanned, then a verdict — on the FAIL line as much as the
PASS line. Read the census first; a gate that scanned fewer files than you expected is telling you
your config is wrong, not that your tree is clean. A zero-file census FAILS rather than passing, and a
file that could not be DECODED is reported and dropped from the count rather than counted as scanned.

```
[check:tres] FAIL — scanned 0 of 13 tracked .tres/.tscn; check [tres] exclude_prefixes  <- config, not drift
[check:pm]   FAIL — 1 status-drift violation(s) across 18 milestone(s), 12 feature(s), 28 story/ies
  DRIFT  feature 0.28.0/chronicle-bus is done w/o review record  [pm/roadmap/…/feature.md]
```

**Precision over reach.** Nothing is a finding unless the whole picture resolved; anything
unresolvable is censused `UNVERIFIED`/`UNVERIFIABLE` and never failed. A false PASS is survivable — a
false FAIL gets the gate switched off, and then nothing is checked at all.

**Exit codes are contract:** `0` pass · `1` findings · `2` usage or config error. A `devkit.toml`
mistake is always `2`, so CI can never read a typo as drift. A retired `[pm]` rule id or config key —
what a pin bump produces — is exit 2 from `check pm` and `pm validate` and nothing else, so the read
verbs keep working while you decide what to change.

## Command reference

`godot-devkit --help` and `godot-devkit pm --help` are the live rosters; this is the same set with
what each one is for.

### Scene-file introspection

| Command | What it does |
|---|---|
| `scene <file.tscn\|.tres> [--props] [--paths]` | Node tree + ext/sub resources + tile bounds. `--paths` prints the address the write verbs take |
| `scene-diff <file> [--git <ref>]` · `scene-diff <old> <new>` | **Structural** diff — nodes added/removed/reparented, props changed, `tile_map_data` as decoded bounds — not a serialized byte diff |
| `refs <symbol> [--tests]` | Reference-aware search across `class_name`/methods/signals/`.gd`/`.tscn`/`.tres` paths/uids (word-boundary, comment-stripped) |
| `orphans [--tests]` | Files with zero inbound refs — a hint, never a hard claim |
| `autoloads` | Autoload census + naming-suffix vs. source-heuristic cross-check |
| `tiles <file> [--layer N] [--cols] [--rows] [--at X,Y] [--region X0,Y0,X1,Y1]` | A TileMapLayer's grid, decoded: cell count, bounds, tile-kind histogram, per-column/row counts, one cell, or an inclusive rectangle |

### Scene surgery (write verbs)

Nodes are addressed **by path**, the way `.tscn` addresses them in `parent=` and the way
`scene --paths` prints them. (Format-4 `unique_id=` is a serialisation detail, not an address.)

| Command | What it does |
|---|---|
| `scene set <file> <path> <prop> <value>` | Assign a property in place (inline `; comments` survive) or append it to the node |
| `scene rename <file> <path> <new-name>` | Rename a node **and every reference to it** — `parent=`, `[connection from=/to=]`, `[editable path=]`, and relative `NodePath("...")` literals |
| `scene add <file> <parent> <name> <type> [--script res://x.gd]` | Add a node after the parent's subtree; `--script` mints the `ext_resource` from the script's `.uid`, so the ref is born canonical |
| `scene rm <file> <path>` | Remove a node, its descendants, its connections and markers, and any `ext_resource` left unreferenced |
| `scene reparent <file> <path> <new-parent>` | Move a subtree and re-express the NodePaths that pointed into or out of it |
| `scene set <file> --resource <prop> <value>` · `scene set <file> --sub-resource <id> <prop> <value>` | The same set semantics on the `[resource]` body of a `.tres` or a `[sub_resource]` — the id is verbatim what `scene --props` prints |
| `scene add <file> <parent> <name> --instance res://x.tscn` | Add an instance node (no `type=`); the `PackedScene` ref is minted from the target scene's own uid, or refused — never invented |
| `scene connect <file> <signal> <from> <to> <method> [--flags N]` · `scene disconnect …` | Author / remove one `[connection]` in Godot's serialization position; ambiguous disconnects are refused, `--flags` names one |
| `refs --retarget <old> <new> [--dry-run]` | After a `git mv`: rewrite every `ext_resource` path attr and exact `preload`/`load` literal naming old (uid untouched); unprovable occurrences are SKIPPED with a reason and exit 1 |
| `scene canonicalize <file>... [--elide-defaults]` | Restore what `PackedScene.pack()` drops: uid-in-refs, the header uid, `index=` on instance-child overrides, `[editable path=]`. `--elide-defaults` also **deletes** `.tres` assignments proven equal to the script's `@export` default |
| `tiles paint <file> --layer N --region X0,Y0,X1,Y1 --tile SRC/AX,AY[/ALT]` | Fill a rectangle of one TileMapLayer; only that one `tile_map_data` assignment is regenerated |
| `tiles erase <file> --layer N --region X0,Y0,X1,Y1` | Delete every cell in a rectangle |

Every verb takes `--dry-run` (unified diff, writes nothing), is **idempotent**, and **refuses** — exit
1, with a reason — rather than write a result it cannot guarantee. Untouched lines are never
rewritten: parse → serialise with no mutation is byte-identical, proven over every `.tscn`/`.tres` in
the consuming repos plus a fixture of the awkward constructs. `--elide-defaults` deletes lines rather
than re-serialising because Godot's own writer is destructive (strips comments, reorders properties,
drops every `uid=`, and can save an EMPTY file returning `OK`). `canonicalize` restores from
**evidence, never invention**; anything unresolvable is reported and left alone.

### Installers (`godot-devkit install-<what>`)

An install verb writes a file. **Once.** A destination that exists and is not byte-for-byte what would
be written is refused by path, naming both remedies — move it aside, or `--force`. `--diff` prints what
a run would change and writes nothing. No manifest, no merge: after the write the file is the repo's.
Every refusal is decided before the first byte, so a collision on the third file leaves the first two
unwritten.

| Verb | Writes |
|---|---|
| `init` | **All of the below, in the order a fresh project needs them**, plus the three files nothing else writes: `devkit.toml` (every gate section, commented at its stock default, so the file is inert on arrival), your two-line `Makefile` with this tag substituted into the pin, and a `CLAUDE.md` skeleton naming the standard targets and the installed rules. It also appends the four run-artifact directories to `.gitignore` and RUNS `tools/setup-hooks.sh`, because installing a hook is not arming it. Idempotent: re-run any time to fill what is missing. **Two ownerships:** the installed files are devkit-owned and `--force` overwrites them; `devkit.toml`, `Makefile`, `CLAUDE.md` and the PM tree are yours from the first write and `--force` never touches them, so a differing seed is reported rather than refused. Refuses, before writing a byte, in a directory with no `project.godot` or no git repo |
| `install-ci` | The four workflows a Godot project runs on a push: `verify.yml` (checkout, uv, `make milestone` — that this is your full gate is a **comment in the file**, not a discovery mechanism), `uid-guard.yml` (`make uid-scan` on a PR to main and a push to staging; an `on:` filter takes no variable, so rename the branches if yours differ), `semver-gate.yml` (a merge to main must bump `config/version` in `project.godot`, and the new version must be the id of a `done` milestone under `PM_ROADMAP` or main's version plus one hotfix component — a building milestone's id refuses) and `auto-tag.yml` (tag the mainline from that same version, then dispatch `RELEASE_WORKFLOW` — the one project-specific string, and its absence is a green "tagged only" rather than a red X). Release, website and social workflows are the project's and are not written |
| `install-agents` | The review/build contract (`verification-reviewer.md` + `verification-builder.md`) plus the base agent roster — architect, po, developer, reviewer, milestone-reviewer, simplifier, test-writer, tech-writer, changelog-writer, doc-hygiene, pm-operator — under `.claude/agents/`, each with `model:`/`effort:` frontmatter and a Project config section that is yours to edit after install. The SDLC they run is [`SDLC.md`](SDLC.md). Deliberately not `.claude/rules/*`: a rules file never reaches a subagent's spawn context; a definition does |
| `install-hooks` | The agent-workflow guard corpus: `tools/hooks/` gets `cc-commit-pathspec.sh` (a `git commit` in a shared tree must name its own paths), `cc-godot-sandbox.sh` (never a raw `godot` boot against the real `user://`), `cc-stop-gate.sh` (an agent's stop is blocked while its fast gate is red), `cc-write-confine.sh` (a write outside the session's repo is blocked at the edit, not the commit), `pre-push` (no direct push to a protected branch + a scoped trunk gate) and `prepare-commit-msg` (agent commits get the trailer, the human's never do); `tools/dev/` gets `agent-worktree.sh` (the one sanctioned per-agent worktree create/teardown) and `checks/doctor.sh` (toolchain census that self-heals the hook wiring); plus `tools/setup-hooks.sh`. Each is **standalone** — a `source` of a file your repo lacks fails open, and a guard that fails open is not there — and each carries a `project config` header that is yours to edit after install. `cc-godot-sandbox.sh` also ships its own block/allow payload corpus: wire `bash tools/hooks/cc-godot-sandbox.sh --self-test` into your static gate (nullbound: a `hooks-self-test` target in `make check`) so an edit to the guard cannot quietly change a verdict |
| `install-runners` | The sandboxed headless-run shell library — `tools/dev/gdk_runners.sh` (one verdict line per gate naming `.gate-reports/<gate>.log`, `VERBOSE=1` streams; a per-run self-destroying HOME sandbox so a boot can never reach the real `user://`; a bounded-run contract that tells a hang from a failure; a `project.godot` restore that undoes engine re-serialization and leaves a real edit alone) plus the runners that source it, under `tools/dev/runners/`: `import_cache.sh`, `parse.sh` (headless boot + a full-project `compile_sweep.gd` pass, reported N/N), `lint.sh` (gdlint over a scan set derived from git's index, never a maintained list), `warnings.sh` (the editor-only GDScript analyzer warnings, promoted to errors in a throwaway project mirror — an editor import pass, then the same `compile_sweep.gd` pass under the promotion, so a `class_name` script nothing instantiates is analyzed too, reported N/N), `unit.sh` (GUT, sliced per system, with the coverage gate that fails the run when GUT silently refused to load a test script), `scenario.sh` / `integration.sh` (one boot scenario, and the whole tier one process each, N-way parallel — `--system <dir>` is the DIRECTORY under the tier, a slice that selects nothing is a FAIL; `--diff <ref>` runs every scenario whose `## covers:` header names a path the change touched, plus the touched scenarios and smoke, and reports the scenarios that declare nothing; a touched piece of the tier's own ground runs the whole tier), `capture.sh` (HEADED, because headless is blind to render), and `hermetic_run_scan.sh` — the gate ON that pair rather than a gate that uses it: no bare `trap … EXIT` clobbering the sandbox self-destruct, a real child run whose HOME and state are gone afterwards with the real `user://` untouched, and nothing persisted beside the `runs/` spool. It boots no engine, so it belongs in your STATIC gate set. Every function is `gdk_*` and your `make` targets call those — a consumer keeping its own prefix is forking the library and stranding the next fix. Each file carries `--help` and `--self-test`; the `runners-self-test` target replays every one of them. **Plus `Makefile.devkit` at the repo root** — the standard target set that CALLS them, which your own Makefile `include`s ([Wiring it in](#wiring-it-into-your-project)). The two ship under one verb because neither half is usable alone: the runners have no callers without the targets, and every runner-backed target is dead without the runners. `.gate-reports/`, `.scenario-reports/`, `.capture-reports/` + `.headless-userdata/` want gitignoring, which `init` does for you |
| `pm install-skills` | `.claude/rules/pm-execution.md` (auto-loads on a `pm/roadmap/**` edit) + `.claude/skills/pm-operations/SKILL.md` (invoked deliberately). Under `pm` because what it writes is the PM tree's own guidance |

All six take `--force` and `--diff`.

### Static gates (`godot-devkit check <gate>`)

`check <gate> --help` prints that gate's contract, its `devkit.toml` section and its
honest scope — the module docstring itself, so the help cannot drift from the code.

Pure git + parse; no Godot boot. Run from anywhere inside the repo.

| Gate | Guards against |
|---|---|
| `check uid` | `.uid` drift, five checks: every Script `ext_resource` uid matches the target's `.gd.uid`; every tracked `.gd` has a tracked `.gd.uid`; every NEW (untracked/staged) `.gd` has a sidecar on disk — the finding names the mint remedy, since only an editor import can create one; every tracked `.gd.uid` still has its `.gd`; every header + non-Script `ext_resource` uid is the canonical `ResourceUID` spelling, judged by a ported engine codec with no engine boot. **`--fix`** rewrites stale refs and non-canonical spellings byte-surgically (same id, no ref break) and deletes orphan sidecars; a drift with no should-be value stays a finding, because minting one is invention. `--fix` on another gate, or on `check all`, is a usage error |
| `check tres` | Path-only `ext_resource` refs, which Godot 4.4+ silently upgrades on any editor/import pass |
| `check props` | Assignments to properties that **do not exist** — a renamed `@export` whose old assignment Godot drops in silence. Scene nodes, sub_resources and `.tres`, against the `@export` chain and the engine's ClassDB |
| `check defaults` | `.tres` assignments repeating the script's declared `@export` default. Judges the elision dimension only |
| `check doc` | Dead claims in always-loaded agent docs (`CLAUDE.md`, `.claude/rules/`, `.claude/agents/`): dead links, dead `make` targets, dead file paths. Plus one placement fact — a flat `.claude/skills/<name>.md` instead of `<name>/SKILL.md` never loads at all |
| `check repo-hygiene` | Close-time git cruft: dirty tree, stashes, dangling worktrees, merged-but-undeleted branches. Runs `git fetch --prune` |
| `check shell` | `shellcheck -x` over every script under `tools/`, incl. extension-less hook entry points. Soft-skips if shellcheck isn't installed |
| `check pm` | PM-tree drift: a `done` feature whose `reviewed:` names no file, a feature whose stories are all done but never advanced, a `done` milestone with live children, a status outside the schema (milestones, features, stories **and bugs**), a `done` story under a live feature, a `building` milestone with everything closed. Also runs the `pm validate` integrity rules (V1–V5). Shares its predicates with the `pm` CLI, so the gate and the tool cannot disagree |
| `check rng` | Randomness a seeded run cannot reproduce: an UNQUALIFIED `randi()`/`randf()`/`randi_range()`/`randf_range()` — the global generator — and `randomize()` in any spelling, including on an instance RNG (which makes an entropy-seeded result LOOK derived). Scope is `[rng] roots` and is meant to be narrow. `[rng] allowlist` is `"<path>:<enclosing func>" = "the reason"`: function granularity, so a new bare call elsewhere in a listed file still trips, the reason is DATA rather than a comment, and an entry that no longer matches a call is itself a finding |
| `check tres-comment` | An authored `;` comment in a `.tres`/`.tscn`. Godot's parser accepts one and its writer DROPS it, so any rationale in a resource file survives only until the next editor save, import or headless run — silently, permanently, with no diff to notice |
| `check unit-disk` | A no-boot test that reaches real persistent state: a `user://` path (stock), a call that touches a live owner (`[unit_disk] forbidden_calls`), or a call whose root/scope parameter DEFAULTS to the real one (`[unit_disk] min_args` — `Save.load(uuid)` is a finding where `Save.load(uuid, throwaway)` is not). A call NAMED in an assert message or a doc comment is not a call |
| `check test-shape` | The expensive test tier growing into the bulk. A RATCHET: `[test_shape] cap` bounds a new scenario, and every file already over it is recorded in `[test_shape] ledger` at its current size — the gate fails when one GROWS past its ceiling or a new one crosses the cap. Prints the tier balance it exists to move, and the ledger line to paste; read-only, so it never edits the config that governs it. **Opt-in `[test_shape] header = true`:** every scenario says, in its leading comment block, why it boots and what it covers — `## Boots because: tests/unit/<path> cannot <what only a boot can assert>` (or the scenario of the same shape it extends) and `## covers: <repo-relative prefix>[, …]`, each entry existing in the tree and refused when absolute, dotted, schemed, globbed or spaced. The same ratchet: the existing tier enters `[test_shape] header_ledger` and leaves it as it is touched — a ledgered scenario that grew a header is a finding naming the line to drop. `covers:` is what `integration.sh --diff <ref>` slices by |
| `gates-extra` | **Not a gate** — prints `[gates] extra` from `devkit.toml`, one make target per line: the project's OWN gate targets, which `Makefile.devkit`'s `check` runs after the devkit ones. The include shells out to this once per run rather than parsing TOML in make, because a `sed` over section headers is a second TOML reader and a second answer. The value is interpolated into a make command line, so the grammar is narrow: whitespace, a path, a shell or make metacharacter, an over-long name or a non-list is exit 2 with a reason — never a silently dropped entry |
| `check all` | The offline fast set — `uid` + `tres` + `props` + `doc` + `shell` by default. **`[checks] all` names the roster for your repo**: most of the roster reads `.tscn`/`.tres`/`.gd` or shell, so a repo holding none gets a 0-file census per gate and correctly reddens each. That is the roster being wrong for the repo, not a reason to soften a gate. The four ported project scans (`rng`, `tres-comment`, `unit-disk`, `test-shape`) are out of the default for the same reason in reverse — none can state a stock scope true of every repo, so each is one `[checks] all` entry away once yours has declared one. An unknown name is exit 2, never a quietly narrowed run |

### Project management (`godot-devkit pm <command>`)

Milestones → features → stories, as markdown with YAML frontmatter under `pm/roadmap/`. The CLI writes
ONE line and touches nothing else — no line endings, no adjacent fields, no file the caller did not name.

**Closed states, open transitions.** The state you ask for is validated against that grain's
vocabulary: `pm milestone butterfly 0.1` is exit 2 naming the set. The state the file currently holds
is never validated — it is read for the message — so `pm milestone done 0.1` works from any state,
including a hand-edited `status: wombat`, which it prints as `wombat -> done` and repairs. There is no
transition graph and nothing checks an EDGE; a graph would only tax whoever used the sanctioned tool
while a `sed` of the same line reached the state it refused. **The verbs report what they noticed and
refuse nothing on process** — stories not at review, features not done, named in the output.
`check pm` catches an invalid state from any route, hand-edit included.

| Command | What it does |
|---|---|
| `pm init` · `pm new <milestone\|feature\|story\|bug> …` | Stand up a tree; scaffold a grain — its own frontmatter file and nothing else. **No directory and no shared doc is minted**: git stores no empty directory, and a shared doc appears on first WRITE. `new milestone`/`new feature` are idempotent — re-run to fill gaps. Every failure out is a refusal, never a stack trace |
| `pm story\|bug\|feature\|milestone <status> <id>` | Set a grain's status to any value in its vocabulary; anything else is exit 2 naming the set. A bug id is `<milestone>/bugs/<slug>` |
| `pm feature review <id>` | Move to `review` and REPORT the stories that are not there |
| `pm feature done <id> [--cascade] [--review-record <path>]` | Close the feature. **Touches no story file** unless `--cascade`, which also closes that feature's stories at `review`. A `--review-record` naming no file IS refused, whole — stamping a pointer to nothing is the drift D1 reports |
| `pm status [<milestone>]` | Tree report, drift-aware, grouped by the optional `phase:` bucket |
| `pm list [--status <s>[,<s>…]] [--owner <n>] [--milestone <id>]` | One tab-separated `<story-id> <status> <owner> <feature-id>` per story, filtered. Deliberately **no `pm next`**: a verb that picks THE next thing is the tool having an opinion about your priorities. Rows to stdout, census to stderr |
| `pm validate` | Frontmatter well-formed, ids match paths, parentage consistent, `depends_on`/`consumed_by` resolve, the feature graph acyclic. A ref into a milestone no longer in the tree is UNVERIFIABLE, never failed — git history is the archive |
| `pm get <id> <key>` · `pm set <id> <key> <value>` | Read/write one frontmatter field through code, not a regex — every other byte and the line endings preserved |
| `pm vocabulary [--json]` | The CLOSED sets: the states each grain may hold, and the rule ids `[pm] checks` may name. Its audience is the **pin bump**. It keeps working when `[pm] checks` names a rule this release retired |
| `pm sync [--check]` | Re-render the execution lists (feature order, story order) from `phase:` + `depends_on`. Opt-in per file; **V6** gates the same thing and is itself opt-in |
| `pm templates [--force]` | Copy the packaged templates into `[pm] template_dir` to edit. A file present there wins; anything missing falls back |
| `pm decide <id> <title…>` | Append one dated, ordinal-stamped heading to that grain's `decisions.md`, minting the log if it is the first. The reasoning under it is yours |
| `pm retire <milestone-id> [<summary…>] [--dry-run]` | Remove a shipped milestone's directory and append its row to the ROADMAP.md table `pm init` already seeds. Reports an undone status or live features/bugs rather than refusing on their account; refuses only when the id or ROADMAP.md itself is missing. `--dry-run` decides and prints, writing nothing |
| `pm move <story-id> <feature-id>` | Re-parent a story to a different feature: renames its file under the target's `stories/` and rewrites `id`/`feature`/`milestone` together. Whole, or not at all — a decided obstruction refuses with nothing touched |
| `pm install-skills [--force] [--diff]` | The auto-loading rule + the operations skill (see [Installers](#installers-godot-devkit-install-what)) |

## Configuration — `devkit.toml`

Optional, at the consuming repo root. Every tool works with stock defaults; a section overrides only
what it names, and a repo with NO `devkit.toml` behaves byte-identically to one declaring the
defaults. A key this package no longer honours is NAMED at exit 2, never silently ignored.

```toml
[checks]
all = ["doc", "pm"]   # which gates `check all` runs HERE.
                      # Default: uid, tres, props, doc, shell

[autoloads]
suffixes = { Manager = "emits", Registry = "inert" }   # suffix -> the source bucket(s)
                                # consistent with its contract: "emits" / "relays" /
                                # "inert" (a string or a list; replaces the default
                                # vocabulary wholesale)
expected_prefixes = ["autoloads/core/", "autoloads/presentation/"]

[refs]
exclude_prefixes = [".git/", ".godot/", ".claude/worktrees/",
                    "pm/roadmap/zz_archive/", "addons/"]   # the stock default;
                                                           # replaced wholesale

[orphans]
vendored_prefixes        = ["addons/"]          # out of the scan entirely — not ours
entry_point_prefixes     = ["tools/"]           # scanned as reference corpus,
                                                # never orphan candidates
auto_discovered_prefixes = ["tests/", "data/"]  # not candidates unless --tests
convention_files         = ["default_bus_layout.tres"]  # engine implicit-load
                                                        # filenames (each key
                                                        # replaces its default
                                                        # wholesale)

[doc]
scope = ["CLAUDE.md", ".claude/rules/*.md", ".claude/agents/*.md"]
ephemeral = ["docs/reviews/"]

[uid]
exclude_prefixes = ["addons/"]   # scopes BOTH uid checks, not just the ref one
[tres]
exclude_prefixes = ["addons/"]
[props]
exclude_prefixes = ["addons/"]
extra_properties = { MyWidget = ["virtual_prop"] }   # for a `_get_property_list`
                                # shape the scanner cannot see. The key names the
                                # script's `class_name` (or an ancestor's) or the
                                # node's engine type — the carve-out applies ONLY
                                # to sections of that class, never tree-wide

[defaults]
exclude_prefixes = ["addons/"]

[repo_hygiene]
mainline = "origin/main"
protected = "^(main|staging|archive/.*)$"

[shell]
roots = ["tools"]

[pm]
roadmap_dir  = "pm/roadmap"     # the tree, relative to the repo root
template_dir = "pm/templates"   # REQUIRED to override a grain template
review_dir   = "docs/reviews"   # where review records live
review_slug_fallback = false    # also accept <review_dir>/<feature-slug>*.md
story_ordinal_prefix = false    # also resolve stories/NN-<slug>.md
checks = ["D1","D2","D3","D4","D5","D6",   # drift rules       — the stock default.
          "V1","V2","V3","V4","V5"]        # integrity rules    V6 and the FLOW rules
                                           # D8 (version == the building milestone's
                                           # id), D9 (a building milestone declares
                                           # `branch:`) and D10 (that branch: is not
                                           # empty or the [repo_hygiene] mainline)
                                           # are opt-in — name them here.
bug_states      = ["open", "fixed", "closed"]   # D4: the bug vocabulary
version_file    = "project.godot"               # D8: where the version lives
version_pattern = '^config/version="(.*)"$'     # D8: the line that carries it
# milestone_states / feature_states / story_states are overridable too — what D4
# holds a grain to, and what the status verbs accept.
```

`godot-devkit pm vocabulary` prints the rule ids in full. `bugs/` and `stories/` are walked
recursively, extension compared case-insensitively; a `.md` in either slot with no leading `---` block
is a note parked beside the grains, not a grain with an empty status, and the census says how many it
skipped.

## Wiring it into your project

**A new project — one command.** From inside the repo:

```bash
uvx --from "git+https://github.com/cdowin/godot-devkit@v0.21.0" godot-devkit init
make doctor && make help
```

**Your Makefile is two lines plus what is yours.** The pin is the one line that must differ per
project, so it lives in YOUR file and a bump is a one-line diff:

```make
DEVKIT_VERSION := v0.21.0
include Makefile.devkit

my-scan: ## a gate this project owns
	@bash tools/dev/checks/my_scan.sh
```

`Makefile.devkit` is devkit-owned and carries the standard set — `help` `doctor` · `parse` `lint`
`warnings` · `unit` `integration` `integration-all` `integration-diff` `scenario` `smoke` `capture` `import-cache` ·
`refs` `scene` `scene-diff` `orphans` `autoloads` `pm` · `pm-scan` `uid-scan` `hermetic-scan`
`hooks-self-test` `runners-self-test` · `check` `precommit` `milestone`. **Every gate prints ONE
verdict line** naming its full transcript under `.gate-reports/`; `VERBOSE=1` streams the whole
thing. `make help` is the authoritative list and shows your targets beside the standard ones.

**Your own gates join `check` by config, never by a fork of the include:**

```toml
[gates]
extra = ["my-scan"]
```

**Per-change vs close-time is the split that matters.** `make precommit` (`check` + `parse` + `lint`
+ `unit` + `integration-diff` — the scenarios whose `## covers:` header names a path the change
against `REF` touched, plus smoke; on a clean tree exactly smoke) belongs in your pre-commit or
pre-push hook; `make milestone` is the full gate and what the installed CI runs; `check repo-hygiene`
and `check defaults` belong at milestone close.

## Northstar

> **Any change you can make to a scene by hand, you should be able to make through one deterministic
> command that touches nothing else — and prove it, without ever reading the file.**

For a **human**, the editor stops being mandatory for mechanical work and diffs stay reviewable. For
an **LLM**: a small stable vocabulary of verbs to compose instead of inventing a bespoke `sed`;
determinism, because a tool that reformats what it was not asked to touch hides its damage inside a
legitimate diff; and token reduction, because a tile-heavy scene costs 100k+ tokens to read where
`scene` costs a few hundred and the write verbs cost zero. Each commitment below is a lesson from a
real incident, not a nice-to-have:

- **Refuse rather than mangle.** The worst outcome is never an error; it is silent partial success. A
  blanket rename once rewrote a `NodePath("Foo/Bar")` while rewriting prose, and reported success.
- **Read output is write input**, one addressing vocabulary in both directions. **Idempotence**,
  because models retry. **Bounded blast radius** — a verb changes nothing adjacent. **`scene-diff`**,
  so the edit is provable without re-reading the file.
- **Encode the footguns as gates,** so the knowledge lives in a gate instead of in a person or prompt.
- **Pure parse — never boots Godot.** No editor, no import step, no `.godot/` cache dependency.
- **Versioned, not vendored.** Consumers pin a tag in one Makefile variable and put project variation
  in `devkit.toml`, so there is no fork-drift to police.

**Scope boundary.** This does not replace Godot for bulk content authoring — painting a
`TileMapLayer` cell-by-cell, baking navigation and importing art need the engine. It owns
**structure**: nodes, properties, resource references, connections, and the gates that keep them
honest. The second half — `check doc`, `check shell`, `check repo-hygiene`, `pm` — never parsed a
scene and would work in a repo with no Godot in it. It ships here because this is the pinned-tag
channel its consumers already share. If that stops being true, it leaves.

## Appendix: migrating to canonical uid-in-refs

If your tree has path-only `ext_resource` refs: (1) for targets whose header has no uid at all, mint
one with Godot's own `ResourceUID.create_id()` in a headless pass — **never hand-author uid strings**,
invalid uids poison the cache; (2) inject each target's uid into the referencing `ext_resource` lines;
(3) prove it cold: delete `.godot/`, run a headless `--import`, confirm zero `invalid UID` warnings.
Then land `check tres` in your gates so the tree can never drift back.

## Development

`make help` lists every target. Never hand-roll an incantation; if the check you need is not a target,
add the target.

```sh
make test        # the suite on the 3.11 floor (pytest, via uv)
make gates       # godot-devkit check all, on this repo
make precommit   # gates + test — the per-change gate
make milestone   # gates + matrix + smoke — the full gate, and what CI runs
```

`make matrix` runs the suite on every claimed interpreter and reports which one failed; `make fuzz`
runs the seeded differential + replay harnesses alone; `make smoke` runs `check all`, `autoloads`,
`scene`, `refs`, `pm status`, `pm validate` and `check pm` against the live consumer checkouts,
compares each printed census against an independent count, and fails if it leaves either dirty. It
also carries the **fresh-project probe**: an empty Godot 4 project in a temp dir, `init`, then the
REAL `make doctor` — the one write in the file, never inside a consumer checkout, and a loud NOT RUN
where `godot` is off PATH.
`orphans`, `scene-diff`, `tiles`, `pm list` and `pm get` are NOT in it. Write verbs NEVER run against
a consumer checkout. Tests needing a Godot repo skip cleanly when none is present; the hermetic
fixtures under `tests/fixtures/` always run.

`check props` compares against a snapshot of Godot's ClassDB in
`src/godot_devkit/data/classdb.json`. Reading it boots nothing. Regenerate when the engine minor moves:

```sh
godot --headless --dump-extension-api      # writes ./extension_api.json
python3 tools/gen_classdb.py extension_api.json
```

## Requirements

- Python 3.11+ (stdlib only) and git. `shellcheck` optional (enables `check shell`).
- Godot 4.4+ text-resource format for the uid/tres gates (the parser handles any Godot 4.x `.tscn`/`.tres`).

## License

MIT — see [LICENSE](LICENSE).
