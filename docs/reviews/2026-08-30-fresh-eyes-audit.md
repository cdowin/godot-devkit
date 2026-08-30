# Fresh-eyes audit — 2026-08-30, against v0.15.0 (`1ad9d17`)

Four independent review passes (godot/ family, repo/ family, tests + apparatus, consumer usage),
~12,000 lines read in full; correctness claims below marked REPRODUCED were exercised live against
scratch trees or real hook payloads. This document is the dispatch reference for milestone
`0.16.0-hardening-and-reach` — each finding names the story that owns it.

Line numbers are against `1ad9d17` and will drift as fixes land; the claim, not the number, is the
finding.

## gate-integrity / config-through-core

- `godot/read/autoloads.py:67-72` — `EXPECTED_PREFIXES = tuple(_CFG['expected_prefixes'])` is the
  banned bare-string pattern: a string value becomes a tuple of characters, `startswith` then
  matches almost anything, layout flags silently suppressed. `str_tuple` is imported (line 35) and
  never called. `suffixes` values unvalidated (`{Manager = 5}` → TypeError). `_CFG` loads at module
  import, so a bad `[autoloads]` table stack-traces during `cli.py` import — outside `_run_check`'s
  ConfigError handler → traceback instead of exit 2.
- `godot/checks/props.py:244-245` — `for names in extra.values(): allowed.update(names)` discards
  the class key of `extra_properties`; a per-class carve-out applies to every class (false PASS on a
  typo'd assignment of that name anywhere). A bare-string value iterates characterwise: 12
  single-char legal property names.
- Config-over-forks never landed for the read verbs: `refs.py:29` hardcodes `ALWAYS_EXCLUDED`
  (`.claude/worktrees/`, `pm/roadmap/zz_archive/`, `addons/`); `orphans.py:39-44` hardcodes
  `tools/`, `tests/`, `data/`, `default_bus_layout.tres`; `autoloads.py:40-43` defaults to
  nullbound's exact directory roster. Six files import `load_config` and never call it (dead
  imports: refs.py:23, orphans.py:29, tres.py:18, defaults.py:34, props.py:41, autoloads.py:34).
  Wire them to devkit.toml sections with stock defaults equal to today's behavior.

## gate-integrity / refusal-not-traceback

- `orphans.py:83` and `autoloads.py:77` — missing `project.godot` → FileNotFoundError traceback.
- `orphans.py:59-61` — outside a git repo → CalledProcessError traceback.
- `checks/uid.py:119` — `_apply` re-reads strict what `_scan` (line 84) read with
  `errors='replace'`: a censused file can crash mid `--fix`.
- `index/uid_index.py:75` — `from_repo_references` reads every ls-files entry without `is_file()`;
  tracked-but-locally-deleted file → FileNotFoundError during canonicalize / `scene add`.
- `read/scene_diff.py:200` — bad git ref exits 1 (`SystemExit(str)`), contract says environment
  errors are 2. Also `print_diff`'s bool return (line 174) is dropped at main:232 — dead either way.

## write-fidelity / newline-preservation

- `format/tscn_document.py:97` (`read_text()`, universal newlines) + `save()` via
  `apply.write_translated` (`newline=None` → `os.linesep`): every write verb silently normalizes the
  whole file's line endings; the `--dry-run` diff and the "(N line(s))" count are computed on the
  translated text (`scene_edit.py:151,167`) so the real byte change is invisible. Breaches rules 3
  and 4 at once. `tests/test_tscn_roundtrip.py:52-56` proves the in-memory constructor only — the
  `load()`/`save()` path defeats it. Fix: preserve the file's detected ending (read bytes or save
  `newline=''`), and extend the round-trip test to the load/save path with a CRLF fixture.

## write-fidelity / apply-honesty

- `core/apply.py:286` — DELETE_TREE uses `shutil.rmtree(..., ignore_errors=True)`: a failed delete
  reports `landed`. The only step violating the module's no-partial-result-that-does-not-say-so
  contract (line 21). MKDIR/OVERWRITE/RENAME all surface OSError into `Applied.failed`.
- `core/apply.py:213-218` — case-only-rename carve-out: too narrow (mixed-case rename where dest ≠
  `lower()` ≠ `upper()` falsely Blocked EXISTS on case-insensitive FS) and too wide (on
  case-sensitive FS, dest matching `src.name.upper()/.lower()` of a DIFFERENT file skips the EXISTS
  block and silently overwrites). Correct predicate: `dest.name.lower() == src.name.lower()` plus a
  samefile/inode check.

## write-fidelity / write-verb-test-matrix

- Missing idempotence tests: `add`, `rm`, `reparent` (matrix in tests/test_scene_edit.py — rename
  :82, set :113, canonicalize :70, tiles paint :331 have them). Missing refusal test: `rm`.
- Semantics decision, then pin it: `_do_rm` (scene_edit.py:93-97) returns `unchanged` exit 0 for a
  never-existed path — a typo is indistinguishable from success. `rename` demands the target exist
  (:70-73); `rm` should refuse on a path that resolves nothing (still idempotent under `--force`?
  decide and record in decisions.md).
- Strict `read_text(encoding='utf-8')` in `scene_edit.py:151`, `tiles_paint.py:157`,
  `scene_canonicalize.py:200,239` — mis-encoded file → UnicodeDecodeError traceback; should be a
  REFUSED line, exit 1.
- `tscn_document.node()` (:118-127) root-by-name convenience: a child of root sharing the root's
  name wins before the root fallback — silent wrong-node addressing; refuse ambiguity.
- `resource_defaults.literal` (:147) compares via `float()` — two distinct ints > 2^53 normalize
  equal; cheap exact-int compare closes it.
- `scene-diff` keys the root by name where write verbs use `.` (`scene_diff.py:52-53,69`): root
  rename renders as remove+add and the root row is not valid write input.

## write-fidelity / layering-format-index

- `format/tscn_document.py:497` — `_uid_of` imports `godot.index.uid_index`: the only upward edge
  in ~90 internal import edges. Callers (`scene add --script`, canonicalize) live in `write/`, which
  may import `index/` — inject the resolver. Add the direction to the boundary test so it cannot
  recur.

## pm-contract / execlist-refusals  (both REPRODUCED)

- `repo/pm/execlist.py:148` — non-UTF-8 grain → UnicodeDecodeError traceback at exit 1, aborting
  the scan mid-tree (later findings unreported) from both `pm sync` and `check pm` with V6.
  Converge on `model.read_raw` + a refusal; kills the inline second-spelling of the raw read.
- `execlist._replace` (:117-122) — reversed OPEN/CLOSE markers hit the append branch every run:
  file grew 25→33→41→49 lines over three `pm sync` runs, each exit 0. Refuse naming the broken
  markers.

## pm-contract / status-verb-vocabulary  (REPRODUCED)

- `repo/pm/cli.py:341-344` — `feature done`/`feature review` dispatch before the vocabulary
  membership check at :345; with custom `feature_states` the sanctioned tool writes D4 drift.
  `--cascade` (:318) writes story `done` without checking `story_states`.
- `cli.py:275-276,300` — `--review-record=` (equals-spelling, empty value) stores `''` and silently
  skips the stamp; the space-spelling's missing-arg case is a Usage refusal (:271-272). Make them
  agree.

## pm-contract / census-and-second-names

- `pm sync --check` over zero grains prints `all 0 execution list(s) current` exit 0
  (cli.py:779-780 write-mode refuses; check mode doesn't). `pm status` over an empty/misconfigured
  roadmap prints nothing exit 0 (:383-427); `cmd_list` got the empty-tree arm (:481-486) — mirror it.
- `repo/pm/validate.py:39` `VALIDATE_RULES` re-declares `model.VALIDATE_CHECKS` (model.py:67) —
  second name; a V7 added to one silently splits `pm validate` from `check pm`. Delete one.
- `model.py:615-629` — `include_archive` parameter and archive-merging branch: zero callers pass
  True; unreachable. Delete.

## hook-soundness  (both REPRODUCED)

- `repo/installables/cc-commit-pathspec.sh:216` — `--pathspec-from-file` consumed but never sets
  `verdict="pathspec"`; the `=` spelling falls into the generic `--*=*` skip at :215. Both spellings
  false-BLOCK — the one false-positive class the header (:19) promises must not exist.
- `repo/installables/cc-godot-sandbox.sh:136` — flag roster misses `-e` (short `--editor`) and the
  bare `godot <scene>` / bare `godot` project boot (a real boot against real `user://`). `:82`
  `${CMD%%<<*}` also truncates at `<<<`, so a herestring hides a following boot (reproduced).

## self-discipline / boundary-gates

- Extend `tests/test_boundaries.py` (which already bans raw mutators/enumerators) to: (a) ban
  config-section reads outside `core/config.py`'s `str_tuple`/`table` guards — would have caught
  the autoloads and props findings; (b) assert zero unused imports package-wide (stdlib `ast` walk)
  — 8 dead `load_config` imports today (six godot/ files above + `repo/checks/shell.py:15`,
  `repo/checks/repo_hygiene.py:26`); (c) assert the format→index→read/write→checks direction.

## self-discipline / doc-hygiene

- `README.md:27` and `:288` still pin v0.14.0 — teach the `/release` skill both pin sites.
- `repo/checks/doc.py:1-25` — docstring describes its pre-extraction life (`doc_scan.py`,
  `make doc-scan`, `uid_scan.sh` siblings — none exist here). Rewrite to what it is.
- `uv.lock` untracked AND unignored — pick one (recommend ignore; stdlib-only package).
- CLAUDE.md says round-trip corpus is "COPIES of real consumer scenes, kept as a corpus" — false
  until ci-corpus lands; that feature makes the sentence true (do not fix the sentence, fix reality).
- `.claude/agents/code-reviewer.md` has no installables counterpart and sits outside the
  byte-currency test — deliberate (repo-local agent); leave, but note in the file header.
- `make test` recreates `.venv` every run and the Makefile "no venv, no network" comment is
  contradicted by `PYTEST := uv run --with pytest` two variables down — scope the comment.
- `tests/test_pm_close_protocol.py` (147 lines) overlaps test_pm.py's `FeatureClose` class — merge.

## self-discipline / helper-dedup

- `_diff` + `DIFF_CONTEXT = 1` identical in `scene_edit.py:45-48` and `tiles_paint.py:121-124`,
  inlined a third time in `scene_canonicalize.py:246-248`.
- `scene_summary.format_prop` (:42-53) ≈ `scene_diff.format_value` (:74-85); `describe_node` and
  `PROP_ELIDE_LEN = 70` duplicated across the pair.
- `tscn_document.py:52-57` re-declares `EXT_RESOURCE_KIND`, `COMMENT_CHAR`, `PARENT_SEG` that
  `tscn.py:39-49` exports; `checks/uid.py:42-44` re-declares `UID_ATTR`/`EXT_RESOURCE_PREFIX` from
  `uid_index.py:25-30`.
- Underscore-private names imported across module boundaries (`_basename` ×4, `_strip_quotes`,
  `_parse_lines`) — de facto public; rename to public or stop importing.

## ci-corpus

- `tests/test_tscn_roundtrip.py` consumer sweep is `@skipUnless(available_consumers())` —
  `~/workspace/{nullbound,trail}` absent on ubuntu-latest, so CI proves the hermetic fixture only;
  the >100-file corpus and `make smoke` run on exactly one laptop. Commit a scrubbed corpus
  (structure kept, art/strings anonymized where needed) with its own census floor; CI round-trips it.

## case-rename-retirement

- `repo/pm/templates/__init__.py:27-31, 98-157, 254-312, 346-372` (`TEMP_RENAME_SUFFIX`,
  `_rename_case`, squatter/variant pre-pass) + `model.py:143-178` (`git_rename`, `case_variants`) ≈
  130 executable lines protecting a migration both consumers completed (nullbound `02357b6c0`,
  `78353be2f`). Delete whole, with their tests.

## uid-deepening

- `checks/uid.py:135` `_untracked_sidecars` covers `.gd`-without-`.uid` for TRACKED files only; an
  untracked/staged new `.gd` — the moment of risk — is invisible (trail's written ask:
  `docs/plans/forward-look/04-devex-tooling.md:58-68`). Both consumers papered over it with a
  duplicated `cc-uid-sidecar.sh` hook. Also unchecked: the inverse — a tracked `.uid` whose `.gd`
  is gone.
- Port Godot's uid base36 codec (`text_to_id`/`id_to_text`) to Python so a non-canonical TEXT
  spelling of a valid id becomes a `check uid` finding (nullbound's 155-line
  `tools/dev/checks/resource_uid_scan.sh` boots sandboxed Godot for exactly this; ~70 uids across
  108 files once churned). Folding both lets consumers delete the hook and the scan.

## subresource-model

- Trail's written ask (`tools/dev/checks/content_schema_lint.py:22-27`): `scene` exposes
  sub_resource field NAMES but not VALUES; 272 consumer lines wait on a structural model. The
  parser already spans `[resource]`/`[sub_resource]` props (`tscn_document.py` Prop spans) — expose
  them in `scene` output (and JSON-ish addressing consistent with write-verb input).

## scene-verbs

- `set-resource`: `set_prop` addresses nodes only (`tscn_document.py:171-179`) though Prop spans
  exist for `[resource]`/`[sub_resource]` — accept `--resource` / `--sub-resource <id>`. This is
  the whole `data/**.tres` plane, currently hand-edit-only.
- `add-instance`: `add_node` (:248) mints type-nodes only; `_ensure_ext_resource` already handles
  arbitrary types and the uid resolver exists. `scene add <file> <parent> <name> --instance
  res://x.tscn`.
- `refs-retarget`: after a `git mv`, every `path="res://old"` ref strands; `uid --fix`
  (checks/uid.py:104-132) demonstrates the byte-surgical multi-file rewrite and
  `UidIndex.from_repo_references` already builds the path→uid cross-index.
- `connect-disconnect`: `[connection]` sections are parsed, rewritten on rename/reparent, deleted
  on rm — but cannot be authored.

## pm-verbs

- `pm bug <status> <id>` — vocabulary (`bug_states`) and resolver (`_grain_file` `/bugs/` arm,
  cli.py:695-701) exist; today only a hand edit or unchecked `pm set` can move the one grain whose
  docstring says a typo'd status "matters most" (checks/pm.py:18-21).
- `pm retire <milestone>` — the documented prune flow is a hand-rolled `git rm -r` + hand-appended
  ROADMAP.md row that `pm init` itself seeds (cli.py:512-520): the tool mints the table, then never
  writes it.
- `pm move <story-id> <feature-id>` — re-parenting is a rename + three frontmatter edits V2/V3 only
  police afterwards; one whole-or-nothing verb through the machinery templates already owns.

## hook-corpus-upstream

- Near-identical siblings in both consumers that devkit does not ship (~1,000–1,200 lines
  duplicated per repo): `cc-uid-sidecar.sh` (97/98 — superseded by uid-deepening, do NOT upstream),
  `cc-stop-gate.sh` (100/103), `cc-write-confine.sh` (152/108), `_scope.sh` (116/120),
  `agent-worktree.sh` (272/295), `doctor.sh` (121/148), plus `pre-push`, `prepare-commit-msg`.
  Survey the pairwise diffs, generalize each to one configurable source, ship via `install-hooks`
  (or a second installer if the set warrants), proven the existing way: installed into a temp repo
  and run against real payloads. Out of scope by charter: the Godot-booting runners.

## consumer-adoption

- Both repos: unadopted v0.15.0 `install-* --diff` output in `.claude/rules/pm-execution.md`,
  `.claude/skills/pm-operations/SKILL.md` (both stamped v0.14.0), `tools/hooks/cc-commit-pathspec.sh`.
- Both repos: no make target for any surgery verb (`scene-set`/`scene-canon` in the README recipe;
  zero exist) — agents cannot reach what the wiring does not name; wire them.
- Trail: no `make pm` target and no shim despite CLAUDE.md:183 mandating pm-through-CLI — copy
  nullbound's 19-line `tools/dev/devkit` shim + `make pm`. No `defaults-scan` target (nullbound
  Makefile:114 has one). `Makefile:111` claims "D1–D7 + V1–V6": D7 does not exist, V6 not enabled.
- After uid-deepening ships in a release both repos pin: delete `cc-uid-sidecar.sh` (both) and
  nullbound's `tools/dev/checks/resource_uid_scan.sh` (155 lines).
- Nullbound devkit targets/claims were audited accurate; keep as the reference wiring.

## technical-review

Closing gate, after all fixes land: full-repo pass for oversized files, function decomposition,
comment archaeology (prose pointing at deleted machinery or past milestones), magic
numbers/strings, and general readability/maintainability. Candidates already known: pm/cli.py
(1090) and pm/model.py (968) file size; test_pm.py ~600–900 lines of per-grain-kind repetition a
parameterization pass would collapse (contracts are good — shape, not substance); the retired-key
exit-2 tests (~190 lines) now deletable since both consumers are past the 0.15.0 bump.

## Confirmed healthy — do not churn

`tilemap.py` codec; `props.py` self-balancing census; `core/walk.py`/`core/apply.py` architecture
(fix the two deviations, keep the shape); `tscn.py`/`tscn_document.py` span surgery;
`resource_defaults.py` proof-not-inference; `test_tscn_roundtrip.py` self-guarding corpus test;
refuse-before-first-byte in all three installers; `model.py` byte-fidelity IO; tombstoned retired
config; the hooks' JSON/tokenizer hard parts; `make smoke` matching its README description exactly;
zero stale tests surviving the 0.15.0 deletion.
