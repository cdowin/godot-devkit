# Changelog

## Unreleased

## v0.17.0 — 2026-08-31

- **`pm` id resolution refuses what creation always refused** — dot/empty/separator segments and absolute ids: `0.1/..` no longer writes a milestone's decisions.md, an absolute milestone id exits 2 instead of a `Path.glob` traceback. The fuzz harness's three carve-out pins died with their reasons. (repo/pm/model.py)
- **the scene plane refuses a path the filesystem itself rejects** — ENAMETOOLONG (and kin) across scene set/rm/rename/add/reparent/connect, canonicalize, tiles paint/erase and refs --retarget is a refusal, not a raw OSError. (godot/write/)
- **`check uid --fix` is byte-surgical on CRLF files** — only the uid attribute changes, every line terminator survives (whole-file byte-compare proven). CHECK 1 now censuses Script ref uids permissively: an undecodable spelling is reported INVALID, never repaired — closing the gap where CHECK 5's Script exemption and `check tres` both waved it through. (godot/checks/uid.py)
- **a tracked-but-deleted file is a disclosed `UNVERIFIED` skip** in check uid/tres/props, never a FileNotFoundError traceback. (godot/checks/)

- **`make fuzz` grows a seeded adversarial-input property harness** — every pm grain id and every scene/retarget path either refuses byte-identically or writes only inside its named slot, over 12 hostile input classes with anti-degenerate censuses. Proven to catch the v0.16.0 traversal blocker against the pre-fix code; found and pinned three live findings on arrival (`pm decide` dot-segment traversal, absolute-milestone-id crash, over-long scene-path crash — filed as 0.17.0 bugs). SDLC §5 now requires every new input surface to ship a refusal matrix plus adversarial cases against its own docstring claims, mirrored into the verification-builder contract. (tests/test_fuzz_inputs.py, SDLC.md, repo/installables/verification-builder.md)

## v0.16.0 — 2026-08-30

- **`pm decide` refuses a `--`-leading title word** — the retired four-field interface's flags were landing verbatim in the durable log at exit 0. (repo/pm/cli.py)
- **pm templates stop minting machine-unread frontmatter** — `severity`, `labels`, `estimate`, `risk`, `size`, `theme`, `target_date`, `track` are gone from the stock grain templates (`pm set` inserts any of them back on demand); `bug.md` keeps `caught_in`/`fix_milestone` and its comment now describes `pm retire`, not the retired D14/prune. pm-operator.md's tooling contract matches the shipped verb roster — re-install with `--force`. (repo/pm/templates/, repo/installables/pm-operator.md)
- **`cc-godot-sandbox.sh` blocks godot-named-variable boots** (`$GODOT --headless`, `"${GODOT}" -e`), carries a `project config` header, and states its accepted arbitrary-name fail-open gap. (repo/installables/cc-godot-sandbox.sh)
- **post-review structure pass** — the two biggest check runners restructured along their phase/section seams with byte-identical output (differential-proven); the installer family extracted from pm/cli.py (1,374 → 1,090 lines); module-level `apply.move`/`remove_tree` deleted with their last readers; test_pm.py split by concern at identical collected-test count; UTF-8 refusals, doc-name and vendored-prefix literals each got one home. (src/, tests/)

- **`scene set --resource` / `--sub-resource <id>`** — the set verb reaches the whole `data/**.tres` plane, previously hand-edit-only; the id is verbatim what `scene --props` prints (read output is write input). An unknown id refuses naming the known ones. (godot/write/scene_edit.py, godot/format/tscn_document.py)
- **`scene add --instance res://x.tscn`** — instance nodes (`instance=ExtResource(...)`, no `type=`); the PackedScene ref is minted from the target's own uid and REFUSED when the target is missing or has no resolvable uid — never invented. (godot/write/scene_edit.py)
- **`scene connect` / `scene disconnect`** — `[connection]` sections were parsed and rewritten on rename/reparent/rm but never authorable. Connect appends in Godot's serialization position; disconnect removes exactly the match, refusing ambiguity (`--flags` disambiguates); connect→disconnect round-trips byte-identically. (godot/write/scene_edit.py)
- **`refs --retarget <old> <new>`** — the post-`git mv` repair: every `ext_resource` `path=` attr and exact `preload`/`load` literal naming old rewritten byte-surgically (uid attr untouched); a comment, substring, or quoted path outside a call is SKIPPED with the reason and exits 1 — a loud skip, never a silent rewrite. `--dry-run` lists every site. (godot/write/refs_retarget.py, cli.py)

- **new opt-in `check pm` rule D10** — a `building` milestone whose `branch:` is empty or equals `[repo_hygiene] mainline` (`origin/`-stripped) is drift. Pairs with D9: run D9 alone for "a building milestone declares its branch," add D10 for the stricter guarantee that it is never the trunk itself. Devkit enables it on its own tree; the flow it encodes is `SDLC.md` §1. (repo/checks/pm.py, repo/pm/model.py)

- **`pm bug <status> <id>`** — moves a bug's status through the vocabulary and resolver that already existed for it: the one grain a typo'd status could previously reach only by hand edit or untyped `pm set`. (repo/pm/cli.py)
- **`pm retire <milestone-id>`** — fills the ROADMAP.md table `pm init` already seeds: one whole-or-nothing write removing the milestone directory and appending its row, reporting (never refusing on) an undone status or live children; `--dry-run` decides and prints without writing. The `NoDeleter` guard survives narrowed to `cmd_retire`'s body — a named single target is not `prune`'s automatic sweep. (repo/pm/cli.py)
- **`pm move <story-id> <feature-id>`** — re-parents a story whole: renames the file and rewrites `id`/`feature`/`milestone` together through the new `model.set_fields`, or touches nothing. (repo/pm/cli.py, repo/pm/model.py)

- **`install-agents` ships the full base agent roster** — architect, po, developer, reviewer, milestone-reviewer, simplifier, test-writer, tech-writer, changelog-writer, doc-hygiene, pm-operator join the verification pair: generalized from the two consumers (the better half taken where the forks diverged; designer/world-designer/tools-reviewer excluded as genuinely project-bound), each with `model:`/`effort:` frontmatter carrying the tiering mix and an editable Project config section. The SDLC they run — milestone branching, the scout-once dispatch loop, the model mix, the token-economy rules — is codified at the repo root as `SDLC.md`. (repo/installables/, repo/install.py, SDLC.md)

- **`check uid` runs five checks** — CHECK 3: a NEW (untracked or staged) `.gd` with no `.uid` sidecar on disk is a finding naming the mint remedy — the tracked-only census missed the exact moment of risk (trail's written ask; supersedes both consumers' `cc-uid-sidecar.sh` hook). CHECK 4: a tracked `.gd.uid` whose `.gd` is gone is a finding; `--fix` deletes it. CHECK 5: every header and non-Script `ext_resource` uid must be the canonical `ResourceUID` spelling; `--fix` canonicalizes byte-surgically (same id, no ref break); an undecodable uid is reported, never repaired. Output adds a census disclosure line and per-class `FIX —` lines; every existing line shape unchanged. (godot/checks/uid.py)
- **pure-Python port of Godot's `ResourceUID` text codec** — base-34 with the engine's compatibility off-by-one, uint64 wrap, 63-bit mask; validated against 3,018 real consumer uids (37 real non-canonical spellings found) and an engine-adjudicated round-trip pair. Folds nullbound's Godot-booting `resource_uid_scan.sh` into the no-boot gate. (godot/index/uid_codec.py)
- **`apply` grows `DELETE_FILE`** — single-file deletion joins the one place the package mutates a filesystem, with the same decided-before-any-byte obstructions. (core/apply.py)

- **`install-hooks` ships the whole agent-workflow guard corpus** — stop gate, write confinement, pre-push, prepare-commit-msg, agent-worktree, doctor: previously ~1,800 lines forked across the two consumers, now 925 generic lines, each standalone with an editable `project config` header. Generalizing fixed a shared pre-push defect (a substring match blocked any branch *containing* a protected name) and unified the forks' one-sided fixes: same-repo sibling-worktree writes allowed (nullbound's fix), non-repo scratch writes allowed (trail's fix), PM-tree integration-branch base for agent worktrees. (repo/installables/, repo/install.py)

- **`scene --props` renders `[resource]` and `[sub_resource]` property VALUES** — previously key names only. Packed/bulky data elides as node props already do, resource-ref arrays stay whole as `[→id, …]` (inside a resource body the ids ARE the structure), and every sub_resource id prints verbatim — the address `scene set --resource/--sub-resource` takes. Default output unchanged except a new `## resource` block on `.tres` files; existing lines byte-stable, proven differentially across the 65-file corpus. Trail's `content_schema_lint.py` SEAM parser can retire against this. (godot/read/scene_summary.py)

- **a committed 65-file scrubbed corpus proves round-trip fidelity in CI** — 36 nullbound + 29 trail `.tscn`/`.tres`, prose deterministically anonymized with structure byte-preserved, covering 24 distinct awkward constructs (tile_map_data, editable paths, packed arrays, inline comments, escaped quotes, …). The corpus round-trip runs unconditionally — CI no longer proves only the hand-built fixture — with a census floor and construct-coverage guard so it cannot rot. (tests/fixtures/corpus/, tests/test_tscn_roundtrip.py)

- **the hard rules are gates on this repo now** — three new boundary tests: config imports live on a closed allowlist and no collection may be built directly from a config lookup (the v0.9.0 bare-string bug class, now unwritable); zero dead imports across src/ (found and removed the last two); the layer directions (format→index→read/write→checks, repo↛godot, core↛both) are asserted with per-layer census floors. Each proven to fire on injected probes. (tests/test_boundaries.py)
- **one home per helper** — the thrice-declared diff renderer, the twice-declared value formatters and section constants, and nine cross-module underscore imports are collapsed to single public homes, proven byte-identical against the old bytes on real CLI runs. (godot/)
- **doc hygiene** — README pins bumped to v0.15.0 and both pin sites named in the release skill; `check doc`'s docstring stops describing its pre-extraction life; `uv.lock` ignored; the Makefile's no-venv comment scoped to the gates. (README.md, .claude/skills/release/, repo/checks/doc.py)

- **the uppercase-migration machinery is retired** — both consumers completed the lowercase grain migration, so the temp-suffix rename pre-pass, `_rename_case` and `git_rename` are deleted (−210 source lines, −208 test lines). A legacy uppercase slot is now a whole-grain refusal naming the variant and the exact `git mv` to run — never a silent rename, twin, or truncation. (repo/pm/templates/, repo/pm/model.py)

- **write verbs preserve the file's own line endings, byte-for-byte** — load/save normalized every line to the platform ending (universal-newline read + `os.linesep` write), a whole-file rewrite the `--dry-run` diff and the "(N line(s))" count never showed. Lines now carry their endings through the store: an untouched line keeps its exact bytes, an in-place rewrite keeps the replaced lines' endings, an inserted line takes the file's dominant ending. Proven on 1,406 real consumer `.tscn`/`.tres`: `load().text` byte-identical to disk on every one. (godot/format/tscn_document.py, godot/write/)
- **`scene rm` refuses a path that resolves nothing** — a typo'd path was indistinguishable from success at exit 0; it now refuses with the file untouched, and `--force` restores the no-op for scripted re-runs. Non-UTF-8 input is a printed refusal in all three write verbs, never a traceback; a root name shared with a child is an ambiguity refusal instead of a silently wrong node. (godot/write/scene_edit.py)
- **`apply` stops lying twice** — DELETE_TREE swallowed every error (`ignore_errors=True`) and reported the step landed; a real failure now surfaces, an already-gone tree stays a landed no-op. The case-only-rename carve-out (`upper()`/`lower()` name match) both false-blocked mixed-case renames and could silently overwrite a *different* file on a case-sensitive FS; it is now a same-file respelling check. (core/apply.py)
- **`scene-diff` addresses the root as `.` and exits 2 on a git error** — the root row was keyed by name (a root rename rendered as remove+add, and the row wasn't valid write-verb input); an unservable ref exited 1, the code reserved for findings. (godot/read/scene_diff.py)
- **`format/` no longer imports upward** — the uid resolver is injected from `write/`; an AST test pins the layer direction. `--elide-defaults` compares big ints exactly instead of through `float()`. (godot/format/tscn_document.py, godot/index/resource_defaults.py)

- **`extra_properties` is scoped to its class key** — the documented per-class carve-out was applied to EVERY class (the key discarded), so a typo'd assignment of a carved-out name anywhere false-PASSed `check props`; a bare-string value iterated characterwise into 12 one-letter legal names. The key now must name the section's engine type or script `class_name` (ancestors included), values go through the new `str_tuple_table` guard, and the key is documented under `[props]` (it was shown under `[defaults]`, which never read it). (godot/checks/props.py, core/config.py, README.md)
- **`refs`, `orphans` and `autoloads` read `devkit.toml` instead of one consumer's layout** — `[refs] exclude_prefixes`, `[orphans] vendored_prefixes/entry_point_prefixes/auto_discovered_prefixes/convention_files`, and the `[autoloads]` keys all resolve at call time through the core guards, with stock defaults byte-identical to the old hardcoded rosters (differential-proven on both consumers). A bare-string or wrong-typed value is exit 2 by name — `expected_prefixes = "autoloads/"` used to become a character tuple that silently suppressed layout flags. Six dead `load_config` imports removed. (godot/read/, godot/checks/)
- **read paths refuse instead of stack-tracing** — missing `project.godot` (autoloads, orphans), running outside a git repo (orphans), a non-UTF-8 file mid `check uid --fix` (drift stays reported, file never lossily rewritten), and a tracked-but-locally-deleted file during uid indexing. (godot/read/, godot/checks/uid.py, godot/index/uid_index.py)

- **`pm` refuses instead of crashing or lying, four ways** — a non-UTF-8 grain file stack-traced `pm sync` and V6 mid-tree (later findings unreported); reversed/lone `OPEN`/`CLOSE` markers hit the append branch every run, growing the file forever at exit 0; `pm status` over an empty or misconfigured roadmap printed nothing at exit 0; `pm sync --check` over zero grains printed `all 0 … current` at exit 0. All four now refuse naming the file, the markers, or the scope problem. (repo/pm/execlist.py, repo/pm/cli.py, repo/pm/validate.py)
- **the status verbs honour a custom vocabulary everywhere** — `feature done`/`feature review` dispatched before the vocabulary check, so a repo with custom `feature_states` got D4 drift written by the sanctioned tool; `--cascade` wrote story `done` without checking `story_states`; `--review-record=` (and an empty space-spelling value) silently skipped the stamp. Target states now validate at exit 2 naming the set; an empty review record is a refusal. (repo/pm/cli.py)
- **one home per fact in the pm internals** — `VALIDATE_RULES` (a byte-identical twin of `model.VALIDATE_CHECKS`) and the dead `include_archive` parameter + unreachable archive-merge branch are deleted. (repo/pm/validate.py, repo/pm/model.py)

- **`cc-commit-pathspec.sh` recognizes `--pathspec-from-file`** — both spellings were false-BLOCKED: the space form consumed the file argument without setting the verdict, the `=` form fell into the generic flag skip. A pathspec by file IS naming your paths; it now waves through, and the header's exemption roster says so. (repo/installables/cc-commit-pathspec.sh)
- **`cc-godot-sandbox.sh` detects every boot shape, not a flag roster** — `godot -e`, `godot <scene>`, `godot .`, bare `godot` and `timeout 60 godot -e` all reached a real engine boot against the real `user://`; a `--help` substring anywhere waved a boot through; a `<<<` herestring truncated the scan ahead of a following boot. Detection is inverted to a query-only allowlist (a godot in command position is allowed iff every argument is `--version|--help|-h`), herestrings are neutralized before the heredoc strip, and `command -v godot` stays exempt. Proven by 36 installed-hook payload tests, 14 of which fail against the old bytes. (repo/installables/cc-godot-sandbox.sh, tests/test_hooks_payloads.py)

## v0.15.0 — 2026-08-30

- **BLOCKER: `pm feature done --cascade` was unreachable from the state the plain run leaves you in** — The verb short-circuited on an already-`done` feature BEFORE the cascade, so the two-step its own output prints as the remedy ("`--cascade` closes the ones at `review`") answered "already done (no-op)" at exit 0, moved no story and stopped even reporting the untouched ones. The feature flip is now the only idempotent part: the cascade, the `--review-record` stamp and the untouched-story report run whatever the feature's status is, and a late record on a closed feature has to RESOLVE like any other. (repo/pm/cli.py)
- **eleven config surfaces stop being silently ignored** — `review_min_content_bytes`, the three grandfather ledgers, the six line caps and the whole `[agents]` section were all read from `devkit.toml` at v0.14.0 and by nothing at HEAD, yet `check pm` and `pm validate` both printed PASS at exit 0 over a file declaring every one of them. They are now named at exit 2 beside the six already in the ledger — on the GATES only, so the read verbs keep working through the pin bump. `core.config.section_declared` catches an empty `[agents]` too, which `config_section` cannot tell from an absent one. (repo/pm/model.py, core/config.py)
- **`pm list --milestone` names the set** — A typo printed `0 of 0` at exit 0, indistinguishable from an emptied milestone and from a wrong `roadmap_dir`. Milestone ids are enumerable, so an unknown one is exit 2 listing them, the way `--status wombat` already did; an empty roadmap says it is a scope problem rather than a typo. (repo/pm/cli.py)
- **the boundary allowlists cannot pass on an empty census** — Both assert an EMPTY offender list, so a moved `SRC` would have satisfied them over zero files. `_sources()` now refuses a census under 20 modules, and a test proves the refusal by pointing `SRC` at an empty directory. (tests/test_boundaries.py)
- **five shipped claims the cuts made false** — The cascade is described as OPT-IN everywhere it is described (`cli.py` module docstring, `pm vocabulary` text and `--json` `notes.feature_done`); exit 1 is named as a refusal, not "findings"; `pm new milestone --help` stops promising directory slots; `check pm` says its real default roster (D1-D6 + V1-V5) and stops calling the feature close atomic; `make smoke` is described by the verbs it actually runs in README, CLAUDE.md and `make help`; and `devkit.toml`'s `[pm]` comment stops describing deleted ratchets. (repo/pm/cli.py, repo/checks/pm.py, README.md, CLAUDE.md, Makefile, devkit.toml)

- **the two handoff docs match the package** — README rewritten 655 -> 375 lines, opening with what the tool IS (informs / scaffolds / edits) and the pinned-tag sharing loop instead of a taxonomy. Dropped the false "precondition-checked CLI" and "a status you move through code" claims for closed states, open transitions; removed the `[agents]` config section and `check agents` from the roster, the duplicated northstar block, and the `python3 -m unittest` development stanza (the suite is `make test`). CLAUDE.md rule 2 loses its archaeology parenthetical. (README.md, CLAUDE.md)
- **consumer smoke is a target** — `make smoke` runs every read verb against the live game checkouts, compares each printed census against an independent count, and fails if it leaves either checkout dirty. (tools/consumer_smoke.py)
- **one walk** — Filesystem enumeration moves into core/walk.py, which returns what it KEPT and what it SKIPPED under a closed-enum reason; Walk has no length, so a census cannot reach a count without its disclosures. (6ac90c3)
- **the two allowlists** — An AST test asserts glob/rglob/iterdir/os.walk live only in core/walk.py and write_text/open-for-write/rename/unlink/rmtree/mkdir only in core/apply.py, naming file:line otherwise. (tests/test_boundaries.py)
- **one apply** — Filesystem mutation moves into core/apply.py: a Plan is an explicit list of Steps, decide() names every obstruction from a closed enum before anything runs, and Applied says which landed. (7134e72)
- **the toolkit stops managing your prose** — The prose ratchet (D17/D18, `pm collapse`, `pm prose-ledger`, six line caps) is gone. Its entire output over two releases was 41 lines of markdown. (b8dc7c4)
- **`pm decide` writes a heading, not a form** — The four-field decision schema produced ZERO conforming entries across a consumer's 158 decision logs. `pm decide <grain-id> <title>` now stamps the date and the next ordinal and stops; the reasoning under it is yours. (6de5b0e)
- **`pm new` stops minting empty files** — Scaffolding a `decisions.md` and `handoff.md` into every grain put 204 empty files and ~1,900 lines into one consumer's tree. A shared doc now appears on first WRITE. (b1c9629)
- **BREAKING: `pm changelog`, `pm decisions`, `pm collapse`, `pm prose-ledger`, `pm claim`, `pm release`, `task` and `check tasks` are removed** — No consumer invoked any of them. `pm set <id> owner <x>` replaces claim/release; `CHANGELOG.md` is hand-maintained. (4e034a4, 56ffaf4)
- **`install-ci` and `install-agents` are back** — They were cut on a census reading 0 consumer references; the verbs had shipped hours earlier and had been held read-only against both consumers, so the census measured a restriction rather than disuse. Restored from history. (56ffaf4, src/godot_devkit/repo/install.py)
- **`install-ci` emits ONE opinionated workflow** — checkout, uv, `make milestone`. The `[ci]` config block, its hand-rolled TOML→YAML emitter and the PyYAML dev dependency do NOT come back: a project that wants a different workflow edits the file, which after the write is its own. The assumption that `make milestone` exists is a comment in the emitted file, not a discovery mechanism. (src/godot_devkit/repo/installables/ci-verify.yml)
- **`install-hooks`** — The shared-tree commit guard, the raw-engine-boot guard and `setup-hooks.sh`, which were forked between two consumers and drifting. Canonical here, each script STANDALONE: the project-name-prefixed JSON helper (`<project>_hook_json_field`, defined in a `_scope.sh` this package does not ship) collapses to one neutral `hook_json_field` defined where it is used, because a `source` of a library a fresh repo lacks fails open and a guard that fails open is not there. (src/godot_devkit/repo/installables/)
- **`--diff` on every install verb** — Prints a unified diff of what a run would change and writes nothing; an absent destination is named as an addition, an undecodable one as a whole-file replace. (src/godot_devkit/repo/install.py)
- **an install refuses on ANY difference** — The install-* verbs used to overwrite, without asking, any destination still carrying their generated header — so a project that edited an installed file lost the edit on the next run. A destination that exists and is not byte-for-byte what would be written is now refused by path, with `--force` named. (src/godot_devkit/repo/install.py)
- **BREAKING: D11, D12, D15, D16, D17 and D18 no longer exist** — `[pm] checks` naming any of them is exit 2. Neither consumer enabled one. Of the rules that survive this release — D1-D6, D8, D9 and V1-V6 — every one is byte-identical; D7 and D10 are removed by their own entries below, and V6 is demoted out of the default roster (D1-D6 + V1-V5) rather than deleted. `review.md` is a permitted file rather than a mandatory slot. (355b671)
- **`actual_date:` is not minted and not stamped** — `pm milestone done` stopped writing it and the milestone template stopped minting the field when the changelog render that read it was removed. Git records when a milestone closed; existing values in a tree are left alone. (src/godot_devkit/repo/pm/templates/milestone.md)
- **one gate roster** — `[checks] all` and the dispatch table were two lists holding one fact; a gate now carries its own default-in-`all` flag, and a test walks the roster to prove every name dispatches. (1c744f8)
- **BREAKING: `pm prune` is removed, with D7 and D14** — On the default roster an open bug under a `done` milestone was PASS, and prune then deleted it. Nothing here deletes a grain. (repo/pm/cli.py)
- **D4 covers a bug's status** — D14's one fact about a FILE (a status outside `bug_states`) moves to the rule that already owns it, on by default. `bug_open_states` goes with its only reader.
- **the census always counts bugs** — `N bug(s)` used to ride the opt-in D14, so a default run said nothing about a directory it had walked. (repo/checks/pm.py)
- **a stale rule id stops the gate, not the CLI** — One retired name in `[pm] checks` used to kill `pm status`, `pm get` and `pm vocabulary --json` too. Only `check pm` and `pm validate` refuse.
- **BREAKING: `check agents` is removed** — A1/A2/A4 failed a build because a markdown file DESCRIBED a workflow, and they inferred: a line's subject was guessed from "one grain word appears".
- **the flat-skill rule survives, in `check doc`** — `.claude/skills/<name>.md` instead of `<name>/SKILL.md` genuinely does not load. A fact about a file, on the gate that checks those.
- **BREAKING: the transition graph is removed** — README claimed "transitions no one can hand-edit around". A `sed` reaches the refused state and `check pm` prints PASS: nothing checked an EDGE.
- **closed states, open transitions** — `pm story|feature|milestone <status> <id>` takes any value in that grain's vocabulary; `butterfly` is exit 2 naming the set. `pm set <id> status` works too.
- **a status verb never validates the state it FOUND** — `pm milestone done` on a hand-edited `status: wombat` used to refuse. It prints `wombat -> done` and repairs the drift `check pm` reports.
- **BREAKING: the `pm feature done` story cascade is opt-in** — Without `--cascade` no story file is touched. Writing files the caller did not name is the tool acting on its own initiative.
- **BREAKING: `place_branch_on_building` and D10 are removed** — `pm milestone building` ran `git checkout` in your trunk worktree. A PM tracker does not mutate your VCS checkout. D9 stays.
- **a retired `[pm]` key is NAMED, never silently ignored** — `check pm` and `pm validate` exit 2 listing it, beside a stale rule id. The read verbs keep running, so a pin bump stays readable.
- **BREAKING: `review_min_content_bytes` is removed** — It refused an honest 15-byte "LGTM. Ship it." — the tool judging whether a person's prose was long enough. A record is a pointer that RESOLVES.
- **D1 is the dangling-pointer half only** — `reviewed:` naming a file that is not there, the shape V4 checks. "This feature has no `reviewed:` at all" is the absence of a document, not drift.
- **`pm feature review` and `pm milestone done` report instead of refusing** — Stories not at review, features not done: named in the output, and the verb does what it was asked. D3/D5 read the tree.
- **BREAKING: D13 is removed** — Its "extra slot" half failed your gate for keeping a file in your own milestone directory. The missing-grain-file half is already reported by `orphan_dirs` and V1.
- **V5 is the dependency cycle, and nothing else** — Phase-monotone fired on `seam`, a bucket this tool invented and called neither blocking nor blocked. `phase:` buckets; the graph orders.
- **`pm new` mints no directory** — `features/ bugs/ design/ stories/` were scaffolded empty, and git stores no empty directory: 158 `design/` dirs in one consumer, 11 with content in them.
- **`pm list` — the nail-finder** — One tab-separated row per story, filtered by `--status`/`--owner`/`--milestone`. `pm status` prints 165 lines on one consumer; the open work was 2 stories.
- **no `pm next`, on purpose** — A verb that picks THE next thing is the tool having an opinion about your priorities. `pm list` filters; you decide. `pm status` is unchanged.
- **V6 leaves the default roster** — A generated VIEW going stale while ordinary work moves the tree is not a defect in the tree. `pm sync --check` still answers; name V6 in `[pm] checks` to gate it.
- **empty repo to a closed milestone: 14 commands to 6** — Six of the fourteen existed only because an edge demanded them, and every one was reachable by hand anyway.
- **`pm vocabulary` prints the closed SETS, not edges** — The states each grain may hold and the rule ids `[pm] checks` may name, machine-readably. It is how a project sees what a pin bump changed.
- **a project's own template may open a grain at any state** — The guard forbidding it was the tool overruling a project about its own scaffold; D4 reads the state off the tree either way.

## v0.14.0 — 2026-08-29

- **a milestone has release notes** — `pm changelog <milestone-id> --what … --evidence …` appends a release note to that milestone's own log. (e432831)
- **the whole log, newest release first** — `pm changelog --render` prints the union of every milestone's notes to stdout, newest release first. (e432831)
- **read a grain's decisions back** — `pm decisions <grain-id>` prints that grain's decision entries, parsed — a milestone printing its own log and its features'. (e432831)
- **D15 holds a changelog entry to its schema** — D15 checks every `changelog.md` entry carries **What:** and **Evidence:**, with a `changelog_grandfather` ledger for legacy text. (e432831)
- **D16 stops a release shipping with no notes** — D16 fails a `done` milestone whose changelog is missing, empty, or holds only entries D15 already reports. (e432831)
- **existing milestones need one re-scaffold** — UPGRADE: `changelog.md` is a new canonical slot, so run `pm new milestone <id>` once per existing milestone to fill the gap. (e432831)
- **D17 caps grain prose as a ratchet** — D17 caps the line count of a story, a `feature.md`, a bug, a feature's `decisions.md` and a `changelog.md`, with the caps as config. (dcb2511)
- **D18 collapses a closed milestone's trail** — D18 fails a `done` milestone still carrying its raw decision trail — close evidence is pointers, not the log. (dcb2511)
- **pm prose-ledger, which will not raise a ceiling** — `pm prose-ledger` regenerates D17's debt ledger to stdout and REFUSES to raise an existing ceiling. (dcb2511)
- **a short --evidence says how to lengthen it** — A commit hash one character short of the minimum is now refused with the count, the minimum, and the `git rev-parse` that fixes it. (dcb2511)
- **a balanced backtick span no longer opens a fence** — A paragraph opening with a balanced inline code span no longer masks the rest of the document, which had hidden real findings from `check doc` and D12. (2eaae12)
- **a fence quoted inside a comment is not malformed** — A lone fence marker inside a paired HTML comment is no longer reported MALFORMED — the two markers hide each other and document order settles it. (2eaae12)
- **check agents reports what it cannot decode** — `check agents` reports an agent definition it cannot decode and takes it OUT of the scanned count, instead of dropping it in silence. (2eaae12)
- **stories/ is walked recursively** — A story at `stories/<subdir>/<name>.md` or named `.MD` is visible to every `check pm` rule, the way bugs already were. (2eaae12)
- **a grain is its frontmatter** — A `.md` under `bugs/` or `stories/` with no frontmatter block is a note parked beside the grains, not a grain with an empty status. (2eaae12)
- **pm new refuses instead of tracebacking** — `pm new` on an over-long grain name or an unwritable `pm/roadmap/` refuses with the reason, and nothing is written. (2eaae12)
- **check doc's FAIL line carries its census** — `check doc` names how many docs it read and how many fenced lines it skipped on FAIL, not only on PASS. (2eaae12)
- **check all runs the gates that apply to your repo** — New `[checks] all` in devkit.toml names the gates `check all` runs here; an unknown name is exit 2, never a quietly narrowed run. (src/godot_devkit/cli.py:87)
- **a nested story is addressable by id** — `pm story <state> <id>` resolves a story anywhere under `stories/`, so the gate can no longer report one the verb refuses. (src/godot_devkit/repo/pm/model.py:572)
- **[uid] exclude_prefixes scopes both uid checks** — `[uid] exclude_prefixes` now scopes the sidecar-tracking check too, not just the ref-drift one. (src/godot_devkit/godot/checks/uid.py:151)
- **an empty census says what it was out of** — A `uid`/`tres`/`props` run that scans nothing now reports "0 of N tracked", so an empty repo and an over-broad exclude stop reading identically. (src/godot_devkit/godot/checks/tres.py:54)
- **the toolkit runs its own gates on itself** — godot-devkit carries its own PM tree at `pm/roadmap/`, with every rule it ships enabled, and its own CHANGELOG rendered from it. (devkit.toml:1)
- **a release heading names its tag and its date** — A rendered release heading is now `## v<id> — <actual_date>`, matching the git tag it maps to; a milestone that has not shipped renders `## v<id>` with no invented date. (src/godot_devkit/repo/pm/cli.py:1218)
- **a broken grain is reported, not dropped** — A story or bug whose frontmatter is damaged — a BOM, a blank line above the fence, no closing fence — stays in the census and is reported, instead of leaving the scan in silence. (src/godot_devkit/repo/pm/model.py:706)
- **the census says how far it looked** — check pm now names how many .md files the grain walk skipped as notes, so a zero bug count is never mistaken for an empty directory. (src/godot_devkit/repo/checks/pm.py:540)
- **a milestone stamps its release date at close** — pm milestone done writes actual_date, which is what puts the date in the changelog render's '## v<id> — <date>' heading; the render still never reads a clock. (src/godot_devkit/repo/pm/cli.py:425)
- **pm prose-ledger names what it absorbs** — Regenerating the prose debt ledger prints every newly absorbed document on stderr with a count, so new debt can no longer enter the ratchet unannounced. (src/godot_devkit/repo/pm/cli.py:1394)
- **a version-shaped changelog heading is not an entry id** — A preamble heading like '## v0.9 release notes' no longer reads as entry 'v0', so the next appended note is allocated C1 rather than v1. (src/godot_devkit/repo/pm/model.py:1138)
- **one fact, one finding, in the right vocabulary** — An over-cap finding names the grain kind it is about, and a ledgered document back inside its cap is reported once — drop the entry — rather than twice. (src/godot_devkit/repo/pm/model.py:1900)
- **a hidden document is still disclosed** — A dot-prefixed file under bugs/ or stories/ is counted in the census instead of vanishing from it. (src/godot_devkit/repo/pm/model.py:769)

---

`v0.13.0` is the only historical section retained, for one reason: it carries
the breaking `DECISIONS.md` -> `decisions.md` rename and how to absorb it, and
the `trail` consumer is still pinned below it. When trail migrates it goes.

## v0.13.0 — 2026-08-29

**One uniform grain structure, all lowercase.** Every milestone and feature dir carries the same
slots, and the split that makes it worth having is durable vs transient:

```
<milestone>/                       <feature>/
  milestone.md                       feature.md
  handoff.md                         —          (milestone-only)
  decisions.md                       decisions.md
  review.md                          review.md
  bugs/                              —          (milestone-only)
  design/                            design/
  features/                          stories/
```

`decisions.md` is **durable** — appended during the grain's life, it survives close and collapses to
pointers when a milestone closes. `review.md` is **transient** — simplifier and reviewer both append,
and it is **deleted at close** with anything durable promoted into `decisions.md` first.

**`pm new milestone` and `pm new feature` are now idempotent**, which is how a consumer migrates. Run
against an existing grain they fill the missing slots, rename a slot present under another case, and
leave every existing byte alone; `<name>` is optional there, since the name only ever mints the
directory. The case rename goes through **`git mv --force`** when git tracks the path, and through a
temp name when it does not. Both halves are load-bearing and neither is optional: macOS is
case-INSENSITIVE, so `open('decisions.md', 'w')` next to an existing `DECISIONS.md` truncates the
very content the migration exists to carry forward — and git's default there is
`core.ignorecase = true`, under which a worktree-only rename leaves the INDEX on the old spelling.
The worktree says `decisions.md`, `git ls-files` says `DECISIONS.md`, and an explicit `git add` of
the new name stages nothing: the migration goes green on the laptop, gets committed, and CI on Linux
checks out the old name with D13 reporting every renamed grain missing and D12 scanning nothing. If
git tracks the path and refuses the move, the scaffolder **refuses too**, printing the exact command
— a half-done rename is the one outcome worse than none. A file slot that exists as a DIRECTORY is
likewise refused rather than crashed, because exit 1 is reserved for findings; that refusal reads the
KIND of every spelling, not just the canonical one, so a `DECISIONS.md/` directory is refused where a
name-only variant scan would have queued it as a rename, renamed it, and then opened it as a file.
A slot that is a SYMLINK is refused for the same reason from the other side: a verb asked to fill
THIS grain does not follow a link and rewrite a file outside it.

Every refusal the grain can raise is decided **before the first rename runs**, so `nothing was
written` is a claim about the whole grain rather than about the slot the refusal happened to land on:
the slot order is `milestone.md, handoff.md, decisions.md, review.md`, and a refusal keyed on
`decisions.md` used to leave `HANDOFF.md -> handoff.md` on disk and staged, where it rides out on the
next commit under somebody else's message. That now covers a leftover `.pm-case-rename` temp file
too — it is in the directory listing, so it is decidable in the pre-pass, and deciding it inside the
moving loop was the last way an earlier slot's rename reached disk under a "nothing was written".
**And the write phase is pre-decided the same way**: every template the grain will need is loaded and
DECODED, and every existing doc due a header prepend is proved writable, before the first byte lands
— a latin-1 byte in a project's `template_dir` and a read-only legacy `handoff.md` both used to
escape as tracebacks with two slots already created. What genuinely cannot be inspected in advance —
git declining a `git mv --force`, a mode changed underneath the run — becomes a refusal that names
what already landed instead of claiming nothing did, and says whether a landed rename was **staged by
`git mv`** or only moved on disk: advice to unstage a worktree-only rename sends an operator to a
`git status` that shows them nothing. The two halves of that composed sentence no longer contradict
each other either: the inner refusal states what became of ITS OWN file (*its content is untouched,
still at …*) and the NOTE states what became of the ones before it, where one message used to say
both `nothing was written` and `1 earlier rename(s) already landed`.

**Exit 1 is a finding, not a stack trace, on every path a rename takes** — the last two paths out
from under that are closed. A rename writes the DIRECTORY, not the file, and the pre-pass checked
only the file: a `0555` grain dir holding a `0644` `DECISIONS.md` passed every inspection and came
out of `os.rename` as a raw `PermissionError` traceback. Directory writability is trivially inspectable, so it is inspected,
and anything still escaping the two-step temp rename becomes a refusal that **names where the bytes
actually are** — the second step failing parks the log at `decisions.md.pm-case-rename`, which no
later run looks for, so a message saying only that the rename failed left an operator hunting for
content sitting right there. A SYMLINK in a file slot is also identified as a link before its kind is
read: `is_dir()` follows the link, so one pointing at a directory got the DIRECTORY refusal — the
right answer with advice aimed at the wrong problem. Measured on
scratch copies of both consumers, with a second full pass changing nothing:

| | grain dirs | slots created | renamed | headers restored |
|---|---|---|---|---|
| nullbound | 158 | 469 | 60 | 60 |
| trail | 32 | 132 | 4 | 4 |

**Each shared doc opens with a one-line instruction**, and D13 asserts it is still there. `.claude/
rules/*` never reach a dispatched subagent — measured — so a file's own first line is the one
delivery channel with a 100% hit rate for the action its reader is about to take. Each line is an
instruction for that action, not an explanation of what the file is:

- `decisions.md` — *Append with `godot-devkit pm decide <grain-id>` — never by hand; the command
  stamps the date and the next ordinal.* It points at the command rather than restating D12's four
  fields: the gate already owns that schema, and a second copy in 178 files is a drift generator.
- `review.md` — *Transient. Deleted at close — promote anything durable into decisions.md first.*
- `handoff.md` — *Cold-start only. Never restate what `pm status` computes.*
- `milestone.md` / `feature.md` get none. V1–V6 already validate their frontmatter.

**New — `pm decide <grain-id> --chose … --over … --because … --evidence … [--title …]`.** Appends a
D12-conforming entry to that milestone's or feature's `decisions.md`, stamping the two things authors
get wrong: the ISO date, and the next ordinal (in the log's OWN id prefix, so a tree numbering `M27`
keeps numbering `M`). `--over` is **required** — a decision with no rejected alternative is a
description, and a required flag enforces that at write time, where the author still remembers the
alternative, instead of at gate time weeks later. Every value is validated by re-parsing the composed
entry through D12's own predicates, so the writer refuses exactly what the gate would report and the
two cannot drift; prose evidence, an over-long value and a `--chose` too long to serve as the header
title are all refused with the log left byte-identical.

**`check pm` D11 is rewritten around the co-located `review.md`: a `done` grain must not have one.**
No `review_dir`, no filename matching, no exemption, no ambiguity. What it replaces resolved a
findings-doc FILENAME back to the grain it "named", and a real corpus got that exactly backwards — on
trail it resolved 6 of 123 docs, and those 6 were precisely the durable ones `reviewed:` already
points at, so after the previous release's fixes trail reported **0 findings over 123 stale docs**.
Anchoring the match could only ever remove matches. `grain_named_by()` and the `KNOWN_DEFECT` test
that pinned its substring bug are gone. The rule-4 loudness stays: a tree with no `done` grain is
NAMED in the output rather than passing in silence, and the census carries the done-grain count.

**`check pm` D13 — the canonical structure.** Every grain dir carries exactly its slots: **missing is
drift AND extra is drift**, and each templated file must still open with its instruction header so
the breadcrumb cannot rot. The extra half is the one that earns the rule — `plans/`, `findings/`,
`AUDIT-REPORT.md`, `audit-prompt.md` and `DELETED-SCENARIO-LEDGER.md` all exist in a real tree
because no slot was scaffolded *and* nothing flagged the invention, and a missing-only check leaves
every one of them there forever. Existence is decided from a directory LISTING, never `Path.is_file`:
macOS resolves `decisions.md` to an existing `DECISIONS.md` and Linux does not, so the same tree
would be clean on a laptop and drifting in CI. Directory slots are permitted, never required — git
does not store an empty directory, so requiring `design/` would mean 178 placeholder files.
`review.md` is required exactly while the grain is open and forbidden once it is done, D11 owning
that half, so a closed grain is never told both to have it and to delete it.

**`check pm` D14 — bug lifetime.** A bug lives in the milestone that will FIX it: `caught_in:` keeps
the provenance, `fix_milestone:` names the decision, and the directory is that decision made real. An
**open bug under a `done` milestone** is therefore drift, and not cosmetically: `prune`'s lag-by-one
deletes a done milestone's directory the moment the next one closes, so those bugs are already
scheduled for deletion. This rule is what makes prune safe by construction. It also reports a bug
status outside `[pm] bug_states` — D4 does not cover bugs, so a typo would otherwise read as "closed"
and pass in silence. Two new config keys, `bug_states` (default `open`/`fixed`/`closed`) and
`bug_open_states` (default `open`); naming an open state the vocabulary lacks is a config error.
The bug census is **recursive and case-insensitive in the extension**: a `glob('*.md')` saw neither
`bugs/<topic>/<bug>.md` nor `<BUG>.MD`, and since `bugs/` is a permitted slot that D13 never descends
into, both were invisible to every rule at once while the census printed the smaller number without
saying it had looked less far. D14 is the rule that stops `prune` deleting an open bug along with its
done milestone, so one that undercounts is not a weaker safety net — it is a false one.

D11, D13 and D14 are OFF by default like D8–D12 — a tree predating the canonical slots is missing
most of them, and a rule that turns a consumer red on upgrade day is unshippable. Scaffold first,
then hold the line. Measured on scratch copies:

| after scaffolding | D13 missing | D13 extra | D13 header | D11 stale | D14 open-bug-under-done |
|---|---|---|---|---|---|
| nullbound | 0 | 12 | 0 | 0 | 28 of 91 bugs |
| trail | 0 | 10 | 0 | 0 | 8 of 13 bugs |

The residual extras are the genuine inventions a human has to place: `plans/` (8 + 10),
`AUDIT-REPORT.md`, `audit-prompt.md`, `findings/` and `DELETED-SCENARIO-LEDGER.md`.

**`check pm` D12 — the decision-record schema.** Every `## <ID> — <ISO date> — <title>` entry in a
`decisions.md` carries `**Chose:**` / `**Over:**` / `**Because:**` / `**Evidence:**`, in that order,
one per line, values <= 200 chars and the title <= 80. `Over:` is the load-bearing field — an entry
that cannot name what it ruled out is a description, not a decision — and `Evidence:` must be a
REFERENCE (a commit hash, a `path[:line]`, a number), never a sentence.

Entry DETECTION reads the entry's BODY, never only its title: a `##` heading is an entry if it
carries an id or a date **or** if any `**Word:**` field line appears beneath it. The field line is
the positive signal, and it is what a title-reading detector cannot see — this package's own retired
template told authors to write `## <short title>` with `**Decision:/Because:/Rejected:/Costs:**`
underneath, and against trail's live corpus a heading-only test called 8 of 9 real decision blocks
prose and passed the whole file, its single finding landing on the one heading that happened to
contain a bug id. A heading with neither an id/date nor a field line is prose and is never
schema-checked, so a log may open with a preamble. A CLOSED `<!-- -->` block is not in the log at
all, and neither is a TERMINATED fenced code block — both are text the entry parser steps over. Its
two edges are symmetric and both keep their live half: the opening line keeps what precedes `<!--`,
and the closing line keeps what follows `-->`, so a conforming `**Over:**` written after a spanning
aside is still read rather than failed for naming no rejected alternative.

**Neither marker may mask in silence.** An unclosed `<!--` suppresses nothing and is itself reported,
and **so is an unterminated code fence** — one stray ` ``` `, a `~~~` "closed" by ` ``` `, an
unbalanced three-backtick span leading a line. Either would otherwise mark every line after it
dead and D12 would print PASS over the entries it ate, which is the exact sin the comment scan
already refuses to commit; the fence masking added to stop a quoted `<!--` eating a log had reopened
it by the other route, silently, and `pm decide` then refused every append to that log forever with
`the composed entry does not parse as a decision entry`. A marker inside backticks or a terminated
fence is a marker being named, not a comment being opened.

**And `check doc` / `check agents` now answer an unterminated fence the same way**, because it was
the same defect wearing the other gate's clothes: their fence scan was a parity toggle, so an ODD
number of fence-looking lines dropped every remaining line of the document and the gate printed PASS
over them. Two dead claims that FAIL normally — `[check:doc] FAIL — 2 unresolved claim(s)` — became
`PASS — 1 doc(s), 0 unresolved claims` the moment one stray ` ``` ` was prepended above them, and
`check agents` did it too. `check doc` runs in `check all`; both run from each consumer's
`make check`. An unterminated fence now masks
nothing and is REPORTED (`malformed doc(s)` / `MALFORMED`) while a terminated one still masks, since
a rule file quoting the CLI's own refusal is documenting it. **One scanner** answers where the fences
are — `core.markdown.fenced_flags`, which D12's own mask now calls rather than keeping a second copy
— so the two families cannot drift into disagreeing about which lines a document even has. That also
brings the CommonMark rules the toggle never had: a closing fence must be the same character, at
least as long and carry no info string (so `~~~` no longer "closes" a ` ``` `), and a fence indented
four spaces is INDENTED CODE — a doc showing how a fence is written no longer opens one. Both
censuses now print **how much they skipped** (`22 doc(s), 223 fenced line(s) skipped`): the count was
of FILES, and files are not what a fence hides.

Legacy logs migrate through `[pm] decision_grandfather` — `"<path>"` exempts a whole log,
`"<path>:<N>"` only its first N entries — whose size the gate PRINTS every run and which may only
shrink: an exemption that suppresses nothing, a cap reaching past the end of its log, and a line
naming no log all FAIL.

**D12 prints its census — `N decision log(s), M entry/ies` — and carries both into the summary
line,** the way D11 prints its done-grain count and D13/D14 print theirs. Without it "scanned 58 logs
/ 294 entries", "scanned 1 log" and "scanned 2 logs / 0 entries" printed identically, which is what
kept the two defects above invisible. The log census itself comes from a directory LISTING with an
EXACT-name comparison, never `rglob('decisions.md')`: a glob whose final segment holds no wildcard
resolves through `Path.exists()`, so macOS answers an on-disk `DECISIONS.md` with the path
`x/decisions.md` — a path that does not exist, a `decision_grandfather` key authorable on exactly one
platform, and, once ONE log of a tree has been migrated, a non-empty list that silences the
scanned-nothing guard while every other log goes unopened (57 of nullbound's 58, carrying 1,467
violations, printed `PASS` and exit 0). A case-variant log is now REPORTED, never folded in; a log
that cannot be decoded is REPORTED rather than counted as scanned-with-zero-entries.

**`pm templates` no longer writes past a case variant.** It reads the target directory by exact name,
exactly as the template loader does, so a project holding a customised `DECISIONS.md` is told the
spelling to port it to instead of silently rendering from the packaged template — and the packaged
one is not written over it, since on a case-insensitive filesystem that write would truncate the
customisation.

**`decision_grandfather = []` is now legal**, and means what it looks like. Every `[pm]` key is
written so that a repo declaring the documented defaults behaves identically to one with no
`devkit.toml`; this was the single key that broke that contract, exiting 2 with *remove the key to
take the default* because an empty list usually means the reverse of what it looks like (`git
ls-files` with no pathspec is the entire repo). It does not here: this key is a LEDGER of exemptions,
so `[]` and the absent key both say "none exempt".

**Known issues, all reported and none fixed here:** `pm decide --title` is not validated for a bare
`\r`; a `decision_grandfather` cap names the wrong entry when one is inserted above it;
`ScaffoldRefused` prints an absolute path rather than a repo-relative one.

Six more were reported here and all six are fixed in `## Unreleased` above: the balanced
three-backtick span read as a fence opener, `check agents` skipping a non-UTF-8 definition in
silence, `stories/` never getting D14's recursion, `pm new`'s unguarded `gdir.mkdir`, D14 reporting a
non-bug `.md` under `bugs/`, and an unterminated fence inside a *closed* HTML comment reported as
malformed.

**`tiles --region` and `tiles --at` can address the negative quadrants again.** `--region -2,-2,1,1`
died with `argument --region: expected one argument` on **every Python a consumer actually runs**:
argparse before 3.14 excuses a leading `-` only for a bare number, so a coordinate list read as an
option. Godot cell coordinates are routinely negative — `tile_map_data` signs x and y precisely
because the upper-left quadrant is ordinary — so `tiles paint` / `tiles erase` / `tiles --at` could
not reach a quarter of the plane on the declared 3.11 floor, while passing on 3.14. Fixed in the
argv, not the parser (the private matcher argparse keys on was rewritten in 3.14, and a tool whose
behaviour depends on which interpreter `uvx` picked is not a tool): a token opening `-<digit>` after
one of those flags is glued into `--flag=value`, on `sys.argv` as well as on an injected argv —
applying it only to the injected one left `python -m godot_devkit.godot.read.tiles … --at -3,-3`
exiting 2 on 3.11 while working on 3.14, which is the version-dependent tool the glue exists to not
be. Narrow on purpose — `--region --tile 9/0,0` is still a usage error with exit 2, and nothing after
`--` is touched. Predates v0.12.0. The suite now runs green on 3.11, 3.12, 3.13 and 3.14; it was
296 passed / 1 failed below 3.14.

**Breaking for a tree that has one:** the decision log is `decisions.md`, not `DECISIONS.md`, and the
handoff is `handoff.md`. `pm new milestone <id>` / `pm new feature <mid> <slug>` performs the rename.
`pm new feature` scaffolds `design/`, not `plans/`. The bug template carries `fix_milestone:` in
place of `fixed_in:`.
