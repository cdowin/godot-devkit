# 2026-08-30 — Closing technical review (0.16.0 hardening-and-reach)

Full-repo fresh eyes at `milestone/0.16.0-hardening-and-reach` HEAD (f8e1201), with the
milestone diff (origin/main..HEAD: 222 files, +15,096/−915) as the map. Charter: file
size, function shape, comment archaeology, magic literals, readability, build-upon-ability.

**Method.** Every claim below was verified at the named line: `wc`/AST function-size census
over all of `src/`, `tests/`, `tools/`; reader census for every symbol proposed dead
(grep + `apply.*(` call scan); the archaeology sweep run over comments/docstrings in
`src/`+`tools/`+`tests/` (42 src hits, 77 test hits, each classified); the stale
close-protocol `decide` call REPRODUCED against the live CLI in a temp repo (writes a
heading literally titled `--title the thing --chose A` at exit 0); both consumer
`devkit.toml`s grepped for retired keys (zero hits in nullbound and trail). Not verified:
a live `make test` run (review is read-only; static collection census only), and the
hooks fired at payloads (test_hooks_payloads.py's matrix was read, not re-run).

Classifications: SPLIT · SEAM · CUT-ARCHAEOLOGY · KEEP-WITH-REASON · NAME-THE-LITERAL ·
DELETE-DEAD · TEST-COLLAPSE · RECIPE-DRIFT. Effort: S (<1h) · M (half day) · L (day+).

---

## Findings, ranked by leverage

### 1. RECIPE-DRIFT — `pm-operator.md` installable contradicts this milestone's own verbs — **M**

`src/godot_devkit/repo/installables/pm-operator.md:42-54`. The tooling contract shipped to
every consumer by `install-agents` (a 0.16.0 feature):

- names **`prune`** as a sanctioned pm command — `pm prune` does not exist (D5 ratified
  `retire` as its replacement, this milestone);
- omits **`bug`, `retire`, `move`, `list`, `get`/`set`, `sync`, `vocabulary`** — five of
  which are 0.16.0's own new verbs;
- says **Create** = "`mkdir -p` the dir; Write the YAML+markdown file" — but `pm new` is
  the sanctioned scaffolder, and `_check_slug`'s path-escape refusals
  (`repo/pm/cli.py:96-115`) exist precisely because creation must go through the tool;
- says **Move** = "`git mv` the dir; update `id:`/`milestone:`/`feature:` … yourself" —
  hand-rolling exactly the whole-or-nothing dance `pm move` (`cli.py:571`) was built this
  milestone to own.

The agent-roster-upstream feature and the pm-verbs feature shipped in the same milestone
and did not meet. Fix the installable's Tooling contract section to the live verb roster
(`pm --help` is the source), re-install with `--force` where self-hosted.

### 2. CUT-ARCHAEOLOGY — `templates/bug.md` cites retired machinery, and mints it into every consumer bug — **S**

`src/godot_devkit/repo/pm/templates/bug.md:15-18`: "An open bug left under a closed
milestone is drift **(D14)** — and **a prune** deletes it where it sits." D14 is retired
(`model.py:242` names it as such) and `prune` is removed (D5). This is not a comment in
our code — it is a template minted into every consumer's every new bug. Rewrite the
comment to the live model (`fix_milestone:` names the decision; `pm retire` reports open
bugs when the milestone goes). Same file: `severity`, `fix_milestone`, `caught_in`,
`labels` have zero machine readers — see finding 14.

### 3. RECIPE-DRIFT — `install.py` points consumers at `docs/AGENT_WORKFLOW.md`, which does not exist — **S**

`src/godot_devkit/repo/install.py:140` (`_NEXT_STEP['install-agents']`, printed to every
consumer after an install): "The SDLC these agents run is docs/AGENT_WORKFLOW.md in the
godot-devkit repo." The file is root-level **`SDLC.md`** (there is no `docs/AGENT_WORKFLOW.md`
in this repo — only `docs/reviews/`). Same dangling pointer in the comment at
`install.py:73`. Two-line fix.

### 4. DELETE-DEAD — `apply.move` and `apply.remove_tree` module conveniences are readerless — **S**

`src/godot_devkit/core/apply.py:340-341` (`move`) has **zero** readers in `src/` and zero
in `tests/` — every mover uses the `Plan.move` method (`cli.py:618`). `apply.py:344-345`
(`remove_tree`) has zero `src/` readers; its only readers are its own tests
(`tests/test_apply.py:39,44`), which per house doctrine test nothing real once the last
consumer is gone (`cmd_retire` uses `Plan.delete_tree`, not the convenience). Queue item
(a) confirmed for `move`; `remove_tree` goes with it, plus its two tests. The siblings
survive: `write` (6 readers), `write_translated` (1), `make_dir` (1), `remove_file` (1),
`raise_on_error` (10). Note `test_boundaries.py`'s mutator census may pin counts — adjust
in the same change.

### 5. TEST-COLLAPSE — `test_pm_close_protocol.py` merges into `FeatureClose`, and its first test pins garbage — **S**

`tests/test_pm_close_protocol.py` (147 lines) duplicates test_pm.py's harness (`tree`/`pm`
runner vs `tree`/`run_cli`) and overlaps `FeatureClose` (test_pm.py:334-479).
**Reproduced**: its `test_the_durable_decision_log_closes_the_feature` (line 80) still
calls the retired four-field interface — `pm decide 0.1/f --title the thing --chose A
--over B …` — which today writes a decisions heading literally titled
`## D1 — … — --title the thing --chose A --over B --because C --evidence abc1234` at
exit 0, and the test passes because it asserts only the exit code. Merge the three
genuinely distinct cases into `FeatureClose` (dangling-symlink record, 15-byte record,
custom-`review_dir` record), rewrite the decide call to the live interface, delete the
file and its duplicate harness. Net ~−100 lines and one fewer close-protocol description
of the same contract. (Optional hardening while there: `cmd_decide` could refuse a title
whose first word starts with `--` — the only caller who types that is one using the dead
interface.)

### 6. TEST-COLLAPSE — the audit's "~600-900 collapsible lines" in test_pm.py is wrong; the honest number is ~150-250, and the real problem is the filename — **M**

Queue item (b), verified against the actual classes. `Scaffolding` (270L),
`BugStatusVocabulary` (116L), `DamagedFrontmatter` (192L) etc. are **not** per-grain-kind
repetition — each method pins a distinct behavior (symlinked slot, case variant, nested
bug, census wording), and the states are already `subTest`-parameterized where they can
be. What IS parameterizable: `BugStatus` (3600-3674) explicitly "mirrors `StatusMoves`'
story coverage" — the four shared shapes (every-state-reachable / out-of-vocabulary /
idempotent no-op / unresolvable id) exist per grain kind across `StatusMoves`, `BugStatus`
and the milestone/feature cases inside `StatusMoves`. A grain-parameterized quartet
collapses ~150-250 lines, not 600-900; each grain's unique guards (bug's cross-grain-write
refusal, nested-bug resolution) stay.

The higher-leverage move for the 3,857-line file is a mechanical SPLIT by concern —
the harness (`tree`/`run_cli`/`run_gate`/`write`, lines 32-139) moves to `tests/support/`,
then: `test_pm_verbs.py` (status moves, close, retire, move, decide),
`test_pm_gate.py` (DriftGate, FlowChecks, MainlineGuard, Validate, censuses),
`test_pm_scaffold.py` (Scaffolding, Templates, NoDeleter, slugs),
`test_pm_guidance.py` (Guidance, SkillShape, install-skills). Four findable files, zero
behavior change, and `test_pm_close_protocol.py`'s remnant (finding 5) lands where it
belongs.

### 7. TEST-COLLAPSE / decision — retired-key exit-2 tests: collapse to mechanism level, do not delete outright — **M**

Queue item (d). Verified: neither consumer's `devkit.toml` carries any retired key
(grep for `place_branch|lines_max|grandfather|transitions|review_min|bug_open_states|
trunk_branches|scaffold`: zero hits in both). But the audit's "deletable" is only half
right: the tests (`ThePMTrackerNeverMovesYourCheckout` 1193-1296 + 
`EveryKeyThisReleaseStoppedHonouring` 1299-1395, ~201 lines) pin `RETIRED_KEYS` /
`RETIRED_SECTIONS` (`model.py:235-283`) — machinery the same audit lists as confirmed
healthy ("tombstoned retired config") and which still guards any consumer arriving from
an older pin. Deleting the tests while the machinery ships un-pins a live refusal.
Proposal: keep the mechanism tests (one key refused by name, one section, retired ids not
in `KNOWN_CHECKS`, the read-verbs-keep-working case at 1017-1058), drop the
per-key enumeration loop and the per-behavior tombstones of the checkout-mover
(~201 → ~60 lines). Full deletion of tests **and** table is a Chris-level call about
whether unknown consumers below 0.15.0 exist.

### 8. SEAM — `repo/checks/pm.py run()` is the biggest function in src (185 lines, four phases) — **M**

`src/godot_devkit/repo/checks/pm.py:61-245`. Linear and readable, but four distinct
phases share one scope: config/roster guard (62-76), the D1-D6 grain walk with a triple
nested loop (113-168), the D8/D10 flow checks (170-204), V-rules + census/verdict
rendering (206-245). Natural cut: `_drift_walk(cfg, enabled, report) -> (n_features,
n_stories)`, `_flow_findings(cfg, enabled, report)`, `_verdict(findings, census…) -> int`.
Sixth-D-rule authors then have one obvious insertion point per phase instead of a
185-line scan for where their rule goes.

### 9. SEAM — `checks/uid.py run()`: the verdict arithmetic is the one place a sixth check can silently lie — **M**

`src/godot_devkit/godot/checks/uid.py:272-375` (104 lines) is a clean orchestrator, but
the FAIL count is hand-summed at line 335-336: `hard = (len(drifts) + len(misspellings)
- len(repaired) + len(untracked) + len(missing) + len(orphans) - len(deleted))`. A CHECK 6
author must remember to add their findings term here AND to the census line at 331 —
a forgotten term is a finding printed above a PASS verdict, the exact rule-4 sin this gate
exists to catch elsewhere. Restructure the five checks as a list of
`(header, findings, fixed)` sections the loop prints, censuses and sums from one
structure. Sub-seam: the five `print('[check:uid] CHECK n — …')` blocks (292-327) become
that loop. `_scan`'s single-pass two-output shape (129-169) is fine — leave it.

### 10. SPLIT — `pm/cli.py` (1,374 lines): extract the installer family; the verb table itself is healthy — **M**

The file is a flat table of self-contained `cmd_*` functions and reads fine per-verb; a
full shatter would be a false split. The one coherent extraction: the
**devkit-writes-its-own-files family** — `GUIDANCE_HEADER`, `ROADMAP_SEED`, `cmd_init`
(799-843), `cmd_install_skills` (846-966), `cmd_templates` (1017-1036) — ~250 lines whose
concern (installing devkit-owned files into the consumer) is `repo/install.py`'s concern,
not status-verb concern. Move to `repo/pm/skills.py` (or fold into install.py per
finding 11) and the remaining ~1,100 lines are one thing: verbs over the tree.

Micro-seams inside, worth taking in the same pass:
- `cmd_feature_done` (290-393, 104L): the hand-rolled `--flag value` / `--flag=value`
  loop (311-336) duplicates `cmd_list`'s (723-744). One `_take_flags(args, spec)` helper
  serves both (S).
- The `known = [(mdir, unquote(field_of(mdir / 'milestone.md', 'id')))…]` enumeration is
  spelled three times: `cmd_status:652`, `cmd_list:755`, `_known_milestone_ids:447`. One
  `model.known_milestones(cfg)` is the single home (S).
- `cmd_new` (1193-1270, 78L) is four grain kinds in one `if` ladder — fine at this size;
  split only if a fifth grain kind ever lands.

### 11. SEAM — `cmd_install_skills` re-implements `install.main`'s decide/apply/report loop — **M**

`repo/pm/cli.py:895-966` and `repo/install.py:297-363` are the same ~60-line skeleton:
per-entry defect/collision/current triage → refuse whole → one `apply.Plan` → report in
plan order, stopping at the failure → refusal naming what landed. The three refusal
HELPERS were single-homed last milestone (install.py's docstring says why); the DRIVER
was not. Extract `install.run_plan(entries, *, force, printer) -> int` in install.py and
have both call it. Honest caveat: they genuinely diverge on ownership — install-skills
clobbers its own generated file (`GUIDANCE_HEADER` check, cli.py:921-924) without
`--force`, install.main does not — so the driver takes an `owned(existing) -> bool`
predicate rather than pretending the two are identical. If that parameter makes the
driver read worse than two copies, keep the copies and pin them against each other with
a test instead; do not force the merge.

### 12. NAME-THE-LITERAL — the UTF-8 refusal paragraph is pasted across three write-verb mains — **S**

`scene_edit.py:359-363`, `tiles_paint.py:150-155`, `scene_canonicalize.py:240-244` carry
the identical `try: read_scene_text … except UnicodeDecodeError: print('REFUSED  {path}:
not valid UTF-8 ({reason} at byte {start}) — refusing to rewrite bytes this tool cannot
read')` block (refs_retarget.py:149-151 has the SKIPPED variant). This is an output-shape
contract duplicated between implementation sites — exactly what
`godot/write/__init__.py`'s own docstring ("the one rendering they share") exists to
prevent, and where `render_diff` already lives. Add `load_scene_or_refuse(path)` there;
a tenth write verb then gets the contract for free.

### 13. NAME-THE-LITERAL — `'milestone.md'` / `'feature.md'` spelled inline 16 / 8 times across five modules — **S**

`model.py` owns the id↔path convention, yet `mdir / 'milestone.md'` is composed inline in
`cli.py` (×7), `model.py` (×5), `execlist.py`, `validate.py`, `checks/pm.py`. One
`MILESTONE_DOC = 'milestone.md'` / `FEATURE_DOC = 'feature.md'` beside
`DECISION_FILE_NAME` (model.py:91) — or better, `model.milestone_doc(mdir)` accessors —
makes the convention greppable from one line. Same class, smaller: `'ROADMAP.md'` ×2 in
cli.py (493, 804).

### 14. NAME-THE-LITERAL / decision — template frontmatter fields with zero machine readers — **M** (queue item e)

Reader census across `src/` for every field the four grain templates mint:
**read by machinery** — `id`, `status`, `milestone`, `feature`, `name`, `owner`
(list/execlist), `phase` (status buckets), `depends_on`/`consumed_by` (V4/V5), `reviewed`
(D1), `branch` (D9/D10). **Read by nothing** — `estimate`, `labels` (minted in all four
templates), `risk` (milestone + feature), `size`, `track`, `theme`, `target_date`
(milestone), `severity`, `fix_milestone`, `caught_in` (bug). Per the house rule a field
earns existence by being read; every unread key is per-grain boilerplate multiplied by
grain count (nullbound: 158+ grains). Proposal: cut the unread keys from the packaged
templates — a consumer who wants `severity:` edits their copied templates, which is what
`pm templates` is for. Chris's call which (if any) are human-load-bearing enough to keep;
`caught_in` at least is prose-justified in bug.md itself.

### 15. CUT-ARCHAEOLOGY — milestone stamps in test docstrings — **S**

Pure provenance stamps, adding no constraint or incident evidence (house rule: version
history lives in decisions.md/CHANGELOG):
- `tests/test_scene_edit.py:202, 240, 325, 410, 516` — "(0.16.0 scene-verbs.)",
  "(0.16.0 write-fidelity decision.)", "(0.16.0 newline-preservation.)"
- `tests/test_install.py:525` — "decided with the roster (0.16.0)"
- `tests/test_pm.py:1109, 1262` — "(decision D3, 0.16.0)" — keep the D3 pointer if wanted,
  cut the milestone stamp; `test_pm.py:1474` "What changed at 0.16.0 is `pm retire`" —
  rewrite as present-tense contract.
- `tests/test_hooks_payloads.py:11` — the commit hash `d76eeea` is evidence (KEEP), but
  "(the 2026-08-30 fresh-eyes audit reproductions)" names a doc the close protocol
  deletes at step 4 — drop the doc name, keep the hash.

Each docstring's surrounding constraint prose stays; only the stamps go.

### 16. SEAM — `cc-godot-sandbox.sh`: the `$GODOT`-in-variable gap is half-closable, cheaply — **S** (queue item f)

`src/godot_devkit/repo/installables/cc-godot-sandbox.sh:136-140`. Today
`GODOT=/Apps/Godot; $GODOT --headless` passes: the assignment survives the fast path
(value contains "Godot") but the command word `$GODOT` fails
`case … in godot|godot4|godot_v*)` because of the leading `$`. The **named-variable**
spelling — the one an agent naturally types — closes in ~4 lines: strip quotes, `$`, and
`{}` from the command word before the basename/lowercase match, so `$GODOT`, `"${GODOT}"`,
`"$godot_bin"` all resolve to a token matching `godot*`. The **arbitrary-name** case
(`ENGINE=…; $ENGINE`) is genuinely out of reach for a static PreToolUse hook without
expansion, as is a two-Bash-call assignment — that residue is the fail-open design
working as declared; record it in the file header as the accepted gap instead of an
unstated one.

### 17. RECIPE-DRIFT — the generalized sandbox installable still speaks in one consumer's voice — **S**

`cc-godot-sandbox.sh:6,176-179`: the header and the BLOCK message a consumer's agent sees
say "**Chris's LIVE game data**" / "Chris's live saves" and hardcode
`tools/dev/_common.sh` + the nullbound make-target roster. The hook-corpus-upstream story
was survey-and-**generalize**; the incident citation (~40 synthetic save dirs) is
KEEP-worthy evidence, but the possessive and the target roster belong in the marked
`project config` header the other hooks use, not in the canonical corpus. (The Makefile
lines are already presented as examples; the "Chris" spelling is the part that reads as
un-generalized.)

### 18. RECIPE-DRIFT — CLAUDE.md's growth recipes drifted one rename and one shape behind — **S** (dimension 6)

- CLAUDE.md:43: "New check = … + branch in **`_run_check`**" — the branches live in
  `_dispatch_check` (`src/godot_devkit/cli.py:190`) since the `--fix` split; `_run_check`
  is now only the flag guard. Rename in the doc.
- The "New WRITE verb = module + cli.py route + …" recipe no longer matches the dominant
  case: a ninth scene verb is a **subverb** — `scene_edit.py` `VERBS` (line 50) +
  `HANDLERS` (270) + `_build_parser` + `_check_usage`, no new module, no cli.py edit.
  Add the one sentence distinguishing "new top-level verb" from "new scene subverb".
- Also friction for "a sixth uid check with `--fix`": `cli.py:181` hardcodes
  `name == 'uid' and f == FIX_FLAG` — a second fixable gate must edit an inline
  condition. One `FIXABLE_CHECKS = {'uid'}` set makes it a table edit. Otherwise the
  recipes verified accurate: check/verb/README/CHANGELOG rows all exist where the doc
  says, and `install_commands()` deriving from `PLANS` means a new installable is one
  table row — that recipe is exemplary.

### 19. SEAM — `validate.py run()`: the depends_on ref-check block is pasted three times — **S**

`repo/pm/validate.py:179-186` (story), `188-200` (feature, + graph collection), `202-209`
(milestone) are the same census/unverifiable/V4 block. Extract
`_check_refs(cfg, path, key, on, bad, census) -> resolved_refs` and the feature site
keeps its two extra lines for graph edges. `run()` drops from 123 to ~90 lines and a V7
author touches one block, not three.

### 20. NAME-THE-LITERAL — smaller single-home items — **S**

- `DEFAULT_EXCLUDE = ('addons/',)` declared identically in four checks
  (`tres.py:21`, `defaults.py:39`, `props.py:62`, `uid.py:63`) + `DEFAULT_VENDORED`
  (`orphans.py:44`). Each gate keeping its own config key is right (rule 5); the default
  VALUE is one fact — `VENDORED_DEFAULT` in `godot/checks/__init__.py`. If the
  per-module copy is deliberate standalone-ness, say so once and this drops.
- Two constants named `KNOWN_CHECKS` with different meanings: gate names
  (`cli.py:135`) vs pm rule ids (`model.py:68`). Both are correct rosters; the shared
  name makes `refs`/grep answers ambiguous. Rename one (`KNOWN_GATES` in cli.py).
- `scene_edit._build_parser` (275-329): `set` and `add` are hand-built and re-add
  `--dry-run` themselves while `add_verb` adds it for the rest — hoist the `--dry-run`
  attach so a new subverb can't forget it.

---

## Comment archaeology — the sweep verdict

42 history-marked comment lines in `src/`+`tools/`, 77 in `tests/`, each read in context.
The overwhelming majority are **KEEP-WITH-REASON**: this codebase's house voice is
"current constraint, with the incident as proof" — e.g. `cli.py:341` (cascade validates
against story vocabulary; the incident is why), `cli.py:650`, `model.py:232-273` (the
retired-key tombstones ARE the feature), `validate.py:111-114`, `apply.py` throughout,
`uid.py:300-303`, `cc-godot-sandbox.sh`'s save-littering incident, `tscn` split-rule note
(`model.py:324-329`), and the v0.9.0 bare-string citations (`CLAUDE.md`,
`test_boundaries.py:268,418`) — that one is the package's founding cautionary tale and is
load-bearing in all three places. The CUT list is exactly findings 2, 3, 15, 17 plus
`pm-operator.md`'s dead verb (finding 1). No comment in `src/` points at deleted
*machinery* except through the RETIRED_KEYS table, which is executable and blessed.

## File-size verdicts not already covered

- `model.py` (975): one coherent substrate (vocabulary, frontmatter IO, resolution, walk,
  predicates), well-sectioned, audit-blessed IO. Leave whole; revisit only past ~1,200.
- `tscn_document.py` (757): 44 methods, largest 32 lines; audit-blessed span surgery. Leave.
- `scene_edit.py` (385): the model of what a verb module should look like — small
  handlers, dispatch table, one parser. The four new verbs landed without bending it.
- `templates/__init__.py` `scaffold` (131-266, 136L): long but strictly
  refuse-before-first-byte phased; a 3-way phase split is available but optional — the
  linearity IS the safety argument here.
- `tools/consumer_smoke.py` (236): fine. *(DELETED in 0.24.0 under CLAUDE.md rule 8 — a dated observation, not current state: the file made two consumer checkouts a precondition for this package's tag.)*

## Counts by classification

| Classification | Findings |
|---|---|
| RECIPE-DRIFT | 4 (1, 3, 17, 18) |
| CUT-ARCHAEOLOGY | 2 (2, 15) |
| SEAM | 5 (8, 9, 11, 16, 19) |
| SPLIT | 1 (10) |
| TEST-COLLAPSE | 3 (5, 6, 7) |
| NAME-THE-LITERAL | 4 (12, 13, 14, 20) |
| DELETE-DEAD | 1 (4) |
| KEEP-WITH-REASON | the archaeology sweep's majority verdict (see above) |

Effort: S ×11 · M ×8 · L ×0. Nothing found rises to L — the tree is in good shape; the
top of this list is doc/installable truth, not structure.

## Do not touch (looks like a finding, is deliberate)

Cross-checked against decisions D1-D5 and the fresh-eyes audit's confirmed-healthy list:

- **`rm` refusing a no-node path while every other verb no-ops** — D2; `--force` restores
  idempotence on request. Not an inconsistency.
- **`retire` reporting (not refusing) an undone milestone / open bugs** — D5's ratified
  shape; the notices-below-the-verb pattern is the same one `milestone done` uses.
- **CHECK 5 exempting Script refs and sidecar contents from canonicality** — D4;
  flagging them would set CHECK 1 and CHECK 5 at war over the same byte.
- **No transition graph anywhere in pm** — measured decision
  (`StatusMoves.test_a_hand_edit_reaches_what_the_cli_refused…` is the kept proof);
  do not propose one, and do not propose gating `_was()` on the current state.
- **`RETIRED_KEYS`/`RETIRED_SECTIONS` executable tombstones** (`model.py:235-283`) —
  audit-blessed ("tombstoned retired config"); finding 7 is about their TESTS' grain,
  not the machinery.
- **The incident-citing comment style** — it is dense, but it is the house contract
  ("docs state what is; the incident is the proof of the constraint"). Do not strip
  "used to" comments wholesale; the CUT list above is exhaustive.
- **Audit's confirmed-healthy roster**: `tilemap.py` codec; `props.py` self-balancing
  census; `core/walk.py`/`core/apply.py` architecture; `tscn.py`/`tscn_document.py` span
  surgery; `resource_defaults.py` proof-not-inference; `test_tscn_roundtrip.py`
  self-guarding corpus; refuse-before-first-byte in all installers; `model.py`
  byte-fidelity IO; the hooks' JSON/tokenizer hard parts; `make smoke`.
- **`Plan` builder methods named `make_dir`/`move` not `mkdir`/`rename`** —
  test_boundaries' AST census requires the distinct vocabulary (`apply.py:157-159`).
- **`feature done` not short-circuiting on already-done** (`cli.py:346-352`) — the
  two-step cascade its own output recommends depends on it.
- **`check all` excluding `defaults`/`repo-hygiene`/`pm`** — each exclusion is reasoned
  at `cli.py:118-124`; not an oversight.
- **`_grain_file`'s `/bugs/` pre-guard in `cmd_bug`** (`cli.py:226-229`) — looks
  redundant, prevents a cross-grain write; pinned by
  `BugStatus.test_an_id_lacking_the_bugs_segment_never_writes_a_different_grain`.
