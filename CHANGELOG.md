# Changelog

## v0.6.0 — 2026-08-27 — project management

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
