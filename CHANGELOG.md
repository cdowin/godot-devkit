# Changelog

## Unreleased — templates, field mutation, execution lists, agent-definition drift

> **Not tagged.** Pin `v0.9.0` until this is released.

**New gate — `check agents`.** An agent definition is prose, so nothing stops it describing a
workflow the tooling refuses. That drift is invisible until an agent follows the instruction and the
CLI says no — by which point a story sits in the wrong state and someone hand-edits around it, which
is the exact failure the PM CLI exists to prevent. It catches a `pm <grain> <verb>` the CLI has no
verb for, a `<state> -> <state>` the grain's graph rejects, a skill written as a flat `<name>.md`
instead of `<name>/SKILL.md` (which never loads as a skill), and project-configured `[agents]
forbidden` patterns.

Run against the two live consumers on first build it found **10 and 8 real findings** — including
agent definitions that had already been hand-corrected once, in files nobody had flagged. Grain
context decides legality: `review -> done` is the feature close edge and a refusal for a story, so
the checker reads the grain from the same line and censuses a line naming two grains as UNVERIFIED
rather than guessing. Precision over reach, as everywhere: a false FAIL gets the gate switched off.

**New — `pm vocabulary [--json]`.** The states, transitions and verbs, machine-readably. `check
agents` reads the model directly, but an external scanner should never have to scrape help text; a
tool that states its own rules in a parseable form is the only way a checker stays honest when those
rules change.

> **Not tagged.** Pin `v0.9.0` until this is released.

**On upgrade:** `[pm.scaffold.<grain>]` is **replaced** by template files. Point `[pm] template_dir`
at a directory, run `pm templates` to populate it, and edit the markdown — a project can now change a
grain's whole shape, not just its frontmatter defaults. Nothing else changes; `check pm` gains V6,
which is inert until a file actually carries a generated block.

**Templates are files.** `pm new` renders `milestone|feature|story|bug` from markdown templates with
`{placeholder}` fills, and a new milestone also gets a `HANDOFF.md` (the cold-start doc) and a
`DECISIONS.md` (append-only, one block per decision that would otherwise be re-litigated). A project
template wins over the packaged one **per file**, so overriding one grain does not make you responsible
for the rest. Unknown placeholders are left visible rather than blanked — a template is prose as well
as schema, and silently emptying something that merely looked like a placeholder corrupts the file.

**`pm get` / `pm set` / `pm claim` / `pm release` — frontmatter mutation as code.** Every hand-rolled
`sed` over frontmatter is a chance to rewrite a line ending, drop a field, or move a value that had
preconditions on it. These go through the same byte-fidelity-proven writer the transitions use.
`status` is **refused**: it is the one field with a transition graph behind it, and a settable status
would reopen the hole the CLI exists to close. `claim`/`release` finally put `owner:` — hand-edited
everywhere `status:` was not — behind a command.

**`pm sync` — the execution list, generated.** A milestone states the order its features are built in;
a feature states the order its stories are. Standing doctrine forbids hand-maintaining exactly this
("a second scoreboard, and it will lie") — and it lies because a *human* maintains it. Rendered between
markers from the same tree `pm status` reads, it is not a second source of truth but a view of the only
one, and **V6** fails when the two disagree. Order is phase, then dependency (Kahn, name-tiebroken so
the output is stable), then name.

The list is **opt-in per file**: a file with no block is not stale, or the gate would go red on every
tree that never asked for the feature. `pm sync` adds blocks; `pm sync --check` and V6 only judge the
ones that exist.

## v0.9.0 — 2026-08-27 — the pm family

**The first pinnable release of everything below.** `v0.6.0`–`v0.8.0` were in-tree
version bumps during one continuous build and were never tagged; their notes are kept
for the record, but `v0.9.0` is the tag that contains all of them. Do not try to pin
them.

### the guidance ships with the tool

**Hardening from the second pre-release review.** The headline was a false PASS in the *recommended*
configuration: `[pm] story_ordinal_prefix = true` was meant to teach V2 about a story file's `NN-`
prefix, and instead switched V2's story check off entirely — so a tree under the setting these notes
mandate reported VALID over a story id of pure garbage, with nothing saying the check was disabled.
It now strips the prefix and compares. Enabling the fix immediately surfaced two genuine id/path
inconsistencies in a consumer that the broken check had been hiding.

**An unreadable ref list is now a finding, not zero refs.** `depends_on` with a trailing comment, a
YAML block sequence, a bare scalar, or nested brackets parsed to `[]` — which reads as "no refs to
check", taking every ref out of V4's reach while reporting clean. Both consumers author only the flat
inline form the scaffolder mints, so nothing was live, but the failure shape was the wrong one.

**`pm new` refused nothing.** A slug was never slugified or validated, so
`pm new bug 0.1 ../../../../pwned` wrote outside the repo root and exited 0. Slugs are now one path
component or a refusal.

**Also fixed:** a bad `version_pattern` regex (or one with no capture group) tracebacked and exited
**1**, the findings code, for what is a config typo — it is exit 2 now, and the pattern is compiled at
load. `[pm.scaffold.*]` accepted an unknown grain key or a non-table value silently, the un-fixed half
of the earlier `checks` fix. D8 passed whenever *any* building milestone matched the version, masking
exactly the drift it exists to catch; two building milestones is now itself the finding. D10 skipped
silently on a detached HEAD — which is what CI checks out — and now says `UNVERIFIED` with the reason.
The ref census counted differently depending on which rules ran. A numeric phase depending on a `seam`
or unphased feature is no longer silently exempt. `pm validate` now honours `[pm] checks` like the gate
does. `prune`'s ROADMAP write no longer translates line endings, and fails cleanly instead of
tracebacking. `KNOWN_CHECKS` listed V1–V5 twice. The FAIL summary called integrity findings "status
drift". The CLI docstring and the README's `check pm` row had both fallen behind the verbs.


**On upgrade:** nothing changes until you run `godot-devkit pm install-skills`. Nothing is written to
a consuming repo without that explicit command.

**New — `pm install-skills`.** The tool shipped without its manual: a consumer got a
precondition-checked CLI and had to reinvent the doctrine that drives it. Measured across the two
consumers, that doctrine had forked badly — the execution rule differed by 57 lines out of ~60.
`install-skills` writes it once, from here:

- `.claude/rules/pm-execution.md` — the claim→close loop, why the CLI refuses what it refuses, and
  the close-evidence promotion test. Installed as a **rule**, not a skill file, because
  `.claude/rules/*.md` with a `paths:` header **auto-loads** for any agent touching the tree while a
  skill must be invoked. A per-edit loop that has to be asked for does not arrive.
- `.claude/skills/pm-operations/SKILL.md` — the operations manual: grain schemas, scaffolding,
  decomposition, phases, reading `status`/`validate`, and the prune model. A **skill**, because you
  reach for it deliberately when planning or restructuring, not on every edit.

Both are generated and carry a header saying so. Re-running is idempotent; a stale generated file
updates in place; a file the tool did **not** write is refused rather than clobbered (`--force`
overrides), because silently overwriting is how a project loses a decision it made on purpose.

**Where the line falls.** These two carry only what the CLI enforces and explains. A project's own
SDLC — branching, versioning, release ceremony, dispatch, review rosters, and what a milestone
*means* in that codebase — stays local. No agent ships from here for the same reason: an agent
carries a project's vocabulary.

**New — `pm init`.** For a repo with no tree at all: creates `pm/roadmap/` and a seeded `ROADMAP.md`
(with the § Prune log idiom already in it), installs the guidance, and prints the remaining wiring —
the gate target, the optional `[pm]` config, and the first scaffold commands — as a checklist rather
than a README to go find.

## v0.8.0 — validate  *(never tagged — shipped inside `v0.9.0`)*

**On upgrade:** `check pm` gains five integrity rules (V1–V5), on by default, so a tree with a
dangling `depends_on` that previously passed will now fail. That is the point — but check with
`pm validate` before you bump. Projects whose story FILES carry an ordering prefix (`01-slug.md`)
while their story IDS do not **must** declare `[pm] story_ordinal_prefix = true`; without it every
such story reads as an id/path mismatch. (Measured: one consumer went from 96 findings to 0 on that
one line.)

**New verb — `pm validate`, and the same predicates inside `check pm`.** A different question from
drift. Drift asks whether statuses are consistent with each other; validation asks whether the tree
is well-formed and its references are real. A milestone can be perfectly undrifted and still depend
on a feature that does not exist — nothing checked that until now, in either consumer.

- **V1** frontmatter is well-formed (a leading fence carrying `id:` and `status:`)
- **V2** the id matches the path — the id==path convention every resolver relies on
- **V3** parentage is consistent: a story's `feature:`/`milestone:` and a feature's `milestone:`
  name the grains that actually own them
- **V4** `depends_on` / `consumed_by` resolve
- **V5** the feature dependency graph is **acyclic** and **phase-monotone** (no feature depends on
  one in a LATER phase). Both were documented in a consumer's README as properties to uphold and
  neither was implemented anywhere.

**Pruned milestones are not errors.** Git history is the archive, so a ref naming a milestone no
longer in the working tree is expected. V4 resolves only refs whose milestone is present and censuses
the rest as UNVERIFIABLE — the discipline `check props` already uses. Failing them would punish the
prune model; hiding them would conceal a typo, so they are counted and named in the summary.

**`pm validate` refuses an empty tree** (exit 2) rather than printing VALID over zero grains — the
same rule-4 guard `check pm` carries.

## v0.7.0 — the flow rules  *(never tagged — shipped inside `v0.9.0`)*

**On upgrade:** nothing changes unless you ask for it. The three new rules are **opt-in** — name them
in `[pm] checks` to enable them. A project that ships from the trunk and bumps its version at
milestone close is running a different, valid flow; failing it would make the gate a liar.

**New rules — D8, D9, D10**, gating branch-per-milestone and bump-at-start:

- **D8** — the project's shipped version equals the `building` milestone's id, by **exact string
  equality**: the milestone id IS the version. Bumping at milestone START means the manifest always
  answers "what am I working on?", a fact every crash report, save file and dev build then carries
  for free. Configurable via `version_file` + `version_pattern`, so this is not Godot-specific.
- **D9** — a `building` milestone declares the `branch:` its work lives on. A fresh checkout of the
  trunk sees a milestone's PM records but not its code; without the stamp the only recourse is
  guessing at `git branch -a`, and a wrong guess means reporting on the wrong milestone.
- **D10** — that branch is checked out **in the trunk worktree**. D9 proves a milestone says where
  its code lives; D10 proves it is where a human can actually follow it. Read from git's MAIN
  worktree, not the tree the scan happens to run from. A milestone declaring a trunk branch
  (`trunk_branches`, default `staging`/`main`) is skipped — it is not using an integration branch.

**Config:** `version_file`, `version_pattern`, `trunk_branches`, and the three rule names in `checks`.

## v0.6.0 — project management  *(never tagged — shipped inside `v0.9.0`)*

**On upgrade:** nothing a consumer must edit. Every existing subcommand, flag and output shape is
unchanged, and the new `check pm` is **opt-in** — it is deliberately excluded from `check all`,
because a repo with no PM tree has no drift to find and must not be failed for its absence.

**New tool family — `godot-devkit pm`.** Filesystem-backed milestone → feature → story tracking
(markdown + YAML frontmatter under `pm/roadmap/`), with the transitions as a precondition-checked
CLI rather than a convention: `pm story|feature|milestone <transition>`, `pm status`, `pm new`,
`pm prune`. A `status:` is the one field a human should never hand-edit — free-text flips are how a
lifecycle drifts, features reaching `done` without the review the flow requires. `pm feature done`
cascade-closes every `review` story and the feature atomically, refuses without a *substantive*
review record (the anti-rubber-stamp: it rejects emptiness, not brevity), and on refusal leaves
`feature.md` byte-identical — a half-applied cascade is worse than no cascade.

**New gate — `check pm`.** Seven drift rules: a `done` feature with no review record (D1), a feature
whose stories are all done but which never advanced (D2), a `done` milestone with live children
(D3), a status outside the schema (D4), a `done` story under a live feature (D5), a `building`
milestone with everything closed (D6), an overdue archive prune (D7). Per rule 4 it prints its
census and **fails rather than passing** when it finds no milestones at all — a misconfigured
`roadmap_dir` used to be indistinguishable from a clean tree. Each rule is proven to fire by a
deliberately-broken probe, and the gate's verdict was diffed against the shell implementation it
replaces over a live consumer tree: identical, as is `pm status` byte-for-byte.

**One definition, two readers.** The vocabularies, transition graphs, id↔path resolution,
frontmatter IO, the review-record definition and the drift predicates live in
`pm/model.py`, imported by both the CLI and the gate. That invariant is the reason this ships as one
package instead of a tool and a separate linter — the two halves cannot describe "reviewed" or
"drift" differently.

**Engine-agnostic, and the README says so.** Nothing in `pm` parses a scene; it would work in a repo
with no Godot in it. The § Scope boundary now names the two families this package actually holds —
scene structure, and repo discipline (`check doc`, `check shell`, `check repo-hygiene` never parsed
a scene either) — rather than implying everything here is `.tscn` tooling.

**Config:** `[pm]` — `roadmap_dir`, `review_dir`, `review_min_content_bytes`, `review_slug_fallback`,
`story_ordinal_prefix`, `checks`, the six vocabulary/graph lists, and `[pm.scaffold.<grain>]` for
projects whose frontmatter schema differs. Stock defaults are the strict graph.

**Hardening from the pre-release review.** The gate could be turned into a rubber stamp by a
`devkit.toml` typo: `[pm] checks` accepted any iterable, so `checks = "D1"` iterated into *characters*,
no rule name matched, and the gate walked the whole tree finding nothing while printing PASS and a
census that made it look thorough. Every `[pm]` value is now type-checked and `checks` is validated
against the known rule names; a malformed section exits **2** (config error), never 0 and never 1 —
`project.py` already stated that contract and only `TOMLDecodeError` had honoured it.

**Fix — frontmatter writes preserved every byte except the ones asked for.** `Path.read_text` /
`write_text` apply universal-newline translation, and `str.splitlines()` additionally breaks on
U+2028/U+2029/form-feed/lone-CR — so a one-field status write silently converted a CRLF file to LF
and rewrote exotic body separators. Reads and writes now pass `newline=''` and split on `\n` only,
proven byte-for-byte on CRLF and on a body carrying U+2028, form feed and a lone CR.

**Fix — `pm prune` could destroy an archive without recording the resurrect anchor, and say it had.**
The prune-log stamp was skipped when `ROADMAP.md` did not exist, while the success line still claimed
the anchor was written. The index is now created and stamped before anything is deleted.

**Fix — a mid-cascade write failure** (an unwritable story file) raised a traceback and left a
half-applied close. It now aborts with exit 2 and says the command is idempotent — re-run to finish.

**Fix — the gate and the CLI disagreed about a quoted `status: "done"`.** The CLI unquoted it, the
gate did not, so `check pm` called a tree clean while `pm prune` deleted a directory from it.
`field_of` now unquotes centrally — one definition, both readers.

**Fix — a directory with no grain file is reported, not skipped.** A milestone dir missing
`milestone.md` (or a feature dir missing `feature.md`) silently took every descendant out of the scan.
Those are now findings that name what was skipped.

**Also fixed:** ids are rejected as glob patterns (`pm milestone ready '*'` resolved to a real
milestone); `prune`'s lag-by-one now orders versions numerically, so `0.9` no longer counts as newer
than `0.11`; `prune` in a repo with no commits exits 2 instead of raising; `_slugify` is ASCII-only,
so `pm new` cannot mint a non-ASCII directory name as a permanent id.

**Fix — `__version__` had drifted from `pyproject.toml`** (`0.4.0` vs `0.5.0`), which rule 7 forbids.
Both now read `0.6.0`.

## v0.5.0

**New gate — `check defaults`.** A `.tres` assignment may not repeat the value its script already
declares as the `@export` default. Two writers, two formats: hand-authored data spells every property
out, Godot's writer omits anything equal to the default — so `trigger = 0` for
`@export var trigger: Trigger = Trigger.ALL_PLAYERS_DOWN` vanishes on the first editor save and the
file diffs forever. Precision is the design constraint, as in `check props`: both sides of every
comparison must normalise into one small closed value language (bool / number / string / empty array /
empty dict / null / numeric constructor), with enum members, `const`s and `const Alias = preload(...)`
chains resolved from the scripts themselves. Anything outside it — an accessor on the export, an
engine built-in with no default table, a `preload()` default — is censused as NOT-A-FINDING and never
reported. Calibrated against Godot's own writer over 559 real `.tres`: **0 false positives, 97.1% of
the engine's own elisions found.** Config: `[defaults] exclude_prefixes`.

**Scope, stated plainly:** the gate judges the property-ELISION dimension only. Godot's writer also
reorders properties into declaration order, respells typed arrays and floats, mints `ext_resource`
entries for typed-array element types, and drops `;` comments. A PASS means "no redundant defaults",
not "the editor would leave this file alone" — the other dimensions are not decidable by parse without
reimplementing `ResourceFormatSaverText`.

**New flag — `scene canonicalize --elide-defaults`.** The fixer for the above. Opt-in, because it
deletes lines. It is a line-deletion pass, never a re-serialisation: over 559 consumer `.tres` it
removed 2479 assignments from 384 files with **zero lines added, zero structural lines touched, every
`;` comment and every `uid=` intact, and zero change to any loaded property value** (proven by loading
every resource in Godot before and after and comparing every STORAGE property, recursively). The
contrast is the point — a headless load-and-re-save over the same corpus rewrote 558 of 559 files,
deleted 1157 comment lines, and silently emptied resources whose script failed to compile.

**Fix — `scene canonicalize` no longer reports a uid-less `.tres` as UNRESOLVED.** A `.tscn` always
leaves the editor with a header uid, so a missing one is a real `pack()` loss. A hand-authored `.tres`
legitimately has none, and when nothing references it by uid there is nothing to restore and nothing
broken. This was 372 false findings out of 559 files in one consumer.

**Internal.** `ext_index` / `ref_path` / `script_path` moved from `checks/props.py` into `tscn.py`
(one home, two consumers); `scan_line` grew `comment_in_brackets`, the one place the two grammars
differ (a `;` inside a multi-line `.tres` value is data, a `#` inside a GDScript `enum {}` is a
comment); `TscnDocument.delete_props` does batch bottom-up span deletion.

## v0.4.0 — 2026-08-23 — the .tscn toolkit

**On upgrade:** nothing a consumer must edit — every existing subcommand, flag, and output shape is
unchanged, so bumping `DEVKIT_VERSION` is a one-line diff. The new `check props` gate is **opt-in**:
it runs only when a consumer wires it into its own gate set. It currently reports 25 findings in
nullbound and 5 in trail, all of them real renamed-export assignments that Godot drops silently — so
wire it deliberately, after a cleanup pass, not as part of the version bump.

A `.tscn` is text, and now it is text we edit *through* tools instead of around them.

**New gate — `check props`.** For every section carrying a script (scene nodes, `sub_resource`s and
`.tres` resources), each assigned property must be an `@export` on the script's inheritance chain or a
built-in of the node/resource type. Catches the silent-failure class where an export is renamed and a
scene keeps assigning the old name: Godot drops the assignment without a word. Precision was the
design constraint — nothing is reported DEAD unless the script parsed, its `extends` chain landed on a
known engine class, and it declares no dynamic properties; instance roots and instance-child overrides
are followed into their base scenes, and anything still unresolved is censused as UNVERIFIED rather
than failed. Every property lands in exactly one bucket and the buckets are printed and checked to
balance. Config: `[props] exclude_prefixes`, `[props] extra_properties`.

**New write verbs — `scene set|rename|add|rm|reparent`.** Path-addressed, `--dry-run`-able,
idempotent, and refusing rather than mangling. `rename` rewrites every `parent=`, every
`[connection]`/`[editable]` reference, and every relative `NodePath("...")` literal — resolved against
the node that owns it, not text-matched. Export names (`node_paths=PackedStringArray(...)`) are left
alone, because they are not paths.

**New verb — `scene canonicalize`.** Restores what `PackedScene.pack()` + `ResourceSaver.save()` drop:
uid-in-refs on every `ext_resource`, the file's own header uid, `index=` on instance-child overrides
(without it the override reloads as a NEW SIBLING and leaks the base scene's child as an orphan on
every load), and `[editable path=]`. Restores from evidence — `.uid` sidecar, resource header,
`.import` file, or existing repo references — and reports what it could not resolve.

**Parser.** `tscn.py` sections and properties now carry line spans, and value continuation is
string-aware (brackets and `;` inside a quoted value no longer count), which fixes multi-line
dictionary values and stops inline comments being swallowed into the value. New `tscn_document.py`
edits only the spans it was asked about, so an unmutated round trip is byte-identical by construction.
`scene` gains `--paths`.

**Also:** `uid_index.py` is the one answer to "where does this resource's uid live" (`.uid` sidecar,
resource header, `.import` file, or existing repo references), shared by `canonicalize` and
`add --script`; `check all` now includes `props`; `src/godot_devkit/data/classdb.json` (a snapshot of
`--dump-extension-api`) ships with the package and is regenerated by `tools/gen_classdb.py`; a stdlib
`unittest` suite lives in `tests/`.

## v0.3.0 — 2026-07-04

Post-review release — all findings from the full code-reviewer pass fixed:

- **CRITICAL fix**: `check repo-hygiene` CHECK 3 could never detect a dangling
  worktree (`git worktree prune -n -v` reports on stderr; the gate read
  stdout). Now parses `git worktree list --porcelain` `prunable` entries.
- **Fix**: an unresolvable `[repo_hygiene] mainline` no longer silently
  disables CHECK 4 — it is a CONFIG ERROR, exit 2.
- **Fix**: a malformed `devkit.toml` exits 2 with a clean message instead of
  a traceback at exit 1 (1 is reserved for findings).
- **Change (upgrade note)**: `check uid` CHECK 1 now censuses ALL tracked
  .tres/.tscn (addons/ exempt) instead of a `[uid] scan_dirs` allowlist — the
  config key is now `exclude_prefixes`; the PASS line reports the ref/file
  census. Attribute matching is order-independent (a reordered ext_resource
  ref is censused, not skipped).
- **Fix**: top-level `--help`/`help` exits 0.

## v0.2.0 — 2026-07-04

- Converted from a vendored file-set to a real Python package: one
  `godot-devkit` entry point with subcommands (`scene`, `scene-diff`, `refs`,
  `orphans`, `autoloads`, `check <gate>`).
- Ported the four bash gates (uid, tres-format, repo-hygiene, shellcheck
  wrapper) to Python — cross-platform, config-driven.
- Per-project variation moved out of file edits into `devkit.toml` at the
  consuming repo root (`[autoloads]`, `[doc]`, `[uid]`, `[tres]`,
  `[repo_hygiene]`, `[shell]`).
- Retired `sync.sh` + the vendored-manifest model; consumers now pin a git
  tag: `uvx --from git+https://github.com/cdowin/godot-devkit@v0.2.0 godot-devkit …`.

## v0.1.0 — 2026-07-04

- Initial extraction from two shipping Godot 4.6 projects: introspect suite
  (shared .tscn/.tres parser, scene summary, structural scene-diff, refs,
  orphans, autoload census) + five static gates, consumed by vendored sync
  with a drift manifest.
