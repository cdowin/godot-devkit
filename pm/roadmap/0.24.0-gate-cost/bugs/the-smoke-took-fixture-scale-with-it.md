---
id: 0.24.0/bugs/the-smoke-took-fixture-scale-with-it
milestone: "0.24.0"
name: "Deleting `consumer_smoke.py` removed the only sweep at real-tree SCALE; six assertions now hold over a smaller committed corpus and one holds over nothing at all"
status: open
caught_in: "0.24.0"
fix_milestone:
caused_by:
---

# the-smoke-took-fixture-scale-with-it

## Symptom

`tools/consumer_smoke.py` (971 lines) and the `make smoke` target are deleted under
CLAUDE.md hard rule 8 (the prose half of the same sweep is what
`0.23.0/bugs/consumer-names-and-provenance-in-code` asked for) — a release gate that depends on which repos happen to be cloned on
the machine running it is not a gate, and it SKIPPED in CI, so it never guarded a tag that
was cut anywhere but one laptop.

That decision is not in dispute here. What this bug records is the **coverage that went
with it**, so nobody has to re-derive it from a deleted file. The smoke's rows fell into
three classes:

| class | rows | what happens to them |
|---|---|---|
| **testing the smoke itself** (worktree lifecycle, install-ahead census, fallback refusal) | 5 | correctly gone — they proved a mechanism that no longer exists |
| **already proven by the committed suite, only smaller** | 6 | still proven, at reduced scale — quantified below |
| **proven by nothing now** | 1 | `fresh project`: the only engine-on-PATH probe |

**The committed fixture base it fell back to:** 11 purpose-built repos under
`tests/fixtures/` (`canon_repo`, `uid_repo`, `props_repo`, `defaults_repo`,
`test_shape_repo`, `tres_comment_repo`, `rng_repo`, `unit_disk_repo`, `retarget_repo`,
`read_repo`, `corpus`), 91 committed `.tscn`/`.tres`, of which `corpus/` is 65 real-world
scrubbed files (36 `.tscn` + 29 `.tres`), 266 distinct uids, 26 authored `index=`
attributes across 9 files, 4 inherited-scene roots.

## The six assertions that lost scale, each with its number

Numbers on the left are what the smoke swept across the two checkouts it read; on the
right is what the committed corpus gives the same assertion today.

### 1. Round-trip fidelity — `scene round trip`

`TscnDocument(text).text == text` over every `.tscn`/`.tres` in the tree.

- **was:** ~310 files (194 + 116), floor 100 per tree, with a loud "too small to prove
  anything" below the floor.
- **now:** `tests/test_tscn_roundtrip.py::CommittedCorpusRoundTrip`, 65 files, `CORPUS_FLOOR
  = 65`, guarded by 24 named `CORPUS_CONSTRUCTS` needles so the corpus cannot rot into
  vacuity.
- **to restore:** vendor more scrubbed scenes. The scrubber (prose-carrying property values
  and comment bodies word-substituted from a deterministic dictionary; node names, types,
  keys, uids, paths and punctuation untouched) is not committed — that is the first thing
  to rebuild, as `tools/` script + a test, or the corpus cannot grow reproducibly.

### 2. uid codec differential — `uid codec differential`

Every uid in the tree, round-trip verdict cross-checked against an independently spelled
positional canonicality predicate.

- **was:** every uid in two trees, against a SECOND restatement of the predicate living in
  `consumer_smoke._independently_canonical`, with `test_uid_codec.py::
  test_the_smoke_grades_against_the_SAME_independent_formulation` pinning the two
  restatements to one answer (that test is deleted; see the census below).
- **now:** `tests/test_uid_codec.py::RealWorldDifferential::test_the_committed_corpus`, 266
  uids, `CORPUS_UID_FLOOR = 200`, `CORPUS_NONCANONICAL_FLOOR = 2`, plus 8
  `PREDICATE_VECTORS` hand-written one per clause (the corpus reaches the alias clauses
  never — the engine emits no `z`, no `9`, no leading `a`).
- **to restore:** nothing needs vendoring — the independent predicate still exists in
  `test_uid_codec._independently_canonical` and still shares no code with the codec. Two
  concrete moves, both fixture-free:
  1. **Assert the predicate against the CODEC over the whole encoder id space**, not just
     over the corpus: `_independently_canonical(id_to_text(uid))` must be `True` for every
     `uid` in `EncoderProperties.IDS` (3037 ids — the dense 0..2999 range, every base-power
     boundary, the 63-bit ceiling). The deleted test subTested over those 3037 but compared
     COPY to COPY; predicate-to-codec is the stronger claim and was never made.
  2. Non-canonical spellings are the scarce input the corpus cannot manufacture
     (`CORPUS_NONCANONICAL_FLOOR` is 2). Vendor scenes carrying more, or leave the floor at
     2 and rely on the 8 `PREDICATE_VECTORS`, one per clause of the rule.

### 3. `check props` calibration — `check props findings`

Every `DEAD` finding on a real tree must be real drift, count pinned.

- **was:** `PROPS_DEAD_CEILING = 30` over two real Godot projects, plus `all accounted for`
  present and no `BUG` line.
- **now:** `tests/test_check_props.py` false-positive cases over `props_repo` — a
  hand-built repo, so it proves the classifier on constructs somebody thought of.
- **to restore:** this is the assertion that lost the most and is hardest to vendor,
  because its value came from *unanticipated* real constructs. What would have to be
  vendored: a `props_repo` grown to carry a real project's `@export`/`class_name`/autoload
  spread — realistically a scrubbed copy of one project's `systems/` tree — with the
  ceiling re-derived and pinned here.

### 4. canonicalize round trip — `canonicalize round trip`

Degrade one real scene the way `pack()` + `save()` does, restore it, byte-compare, and
assert no header uid was invented for a file outside its own repo.

- **was:** the scene the degradation costs the MOST lines, per tree, chosen by rule so the
  pick could not be a pick that passes.
- **now:** `tests/test_canonicalize.py` over hand-built fixtures plus
  `test_no_corpus_scene_gains_or_loses_a_marker` over both corpus slices.
- **to restore:** the "worst-degraded scene" SELECTION RULE has no committed home. Vendor
  it as a test over `corpus/`: compute the degradation cost for all 36 corpus `.tscn`, pick
  the max, restore, byte-compare. That is a direct port and would close this row entirely.

### 5. canonicalize invents no index — `canonicalize invents no index`

Over EVERY tracked scene: degrade, canonicalize, and count `index=` attributes that came
back on a node that never had one; identity `restored + lost == authored` so a value that
comes back DIFFERENT is red rather than counted in a green row's detail.

- **was:** ~310 scenes, 56 authored `index=` (17 + 39), 505 attributes measurably invented
  by the rejected "next free slot" rule.
- **now:** the BEHAVIOUR is pinned by `AnInheritedRootIsAnInstanceHost`,
  `AChainedBaseIsRefusedNotCounted` and `ACreatedNodeGainsNoIndexWhateverItsParentIs` over
  hand-built fixtures shaped from the real evidence. The **whole-tree identity** is pinned
  by nothing: the three tests in `TheSmokeRowGatesAWrongValueNotOnlyAnInventedOne` that
  proved the accounting are deleted with the row they graded.
- **to restore:** port the accounting to `corpus/` — 26 authored `index=` across 9 files,
  4 inherited roots. `restored + lost == authored` over 26 is a real assertion and the
  cheapest of the six to rebuild. **Do this one first.**

### 6. defaults elision — `defaults elision`

`--elide-defaults` over a real tree must be a pure, stable, idempotent deletion (every
surviving line an original line, in order; second run a no-op).

- **was:** every tracked `.tres` in two trees, copied to a throwaway repo, with an explicit
  loud skip when the corpus was already canonical and the row therefore exercised nothing.
- **now:** `tests/test_defaults.py` over `defaults_repo`.
- **to restore:** run the same three-property check (pure deletion / idempotent / something
  actually changed) over the 29 corpus `.tres` copied to scratch. Also a direct port; the
  "changed NOTHING is reported, not counted as proof" clause is the part worth keeping.

## The one thing now proven by nothing: `fresh project`

The smoke's fresh-project probe was the only place in this repo that ran `godot-devkit
init` and then the REAL `make doctor` **with an engine on PATH**. `tests/test_fresh_project.py`
still runs `init`, `make check` and `doctor.sh` for real, and still asserts the hook census
— but every engine-facing target is proven by `make -n` (expand the recipe, run nothing),
which cannot catch a runner that expands fine and fails on contact with Godot.

**This gap cannot be closed by vendoring.** It needs an engine, and this package's rule 2
is that it never boots one. The honest resolutions, in order of preference:

1. **Say so and leave it** (what the code now does — `test_fresh_project.py`'s header
   states the gap in the same paragraph that describes the `make -n` half). Contact with
   the engine is proven where an engine exists, which is a consuming project's own gate in
   its own repo, when it bumps its pin.
2. A CI job that installs Godot headless and runs `init` + `make parse` in a scratch
   project. Self-contained (no consumer), but it boots the engine, so it is a rule-2
   decision and belongs in `decisions.md`, not in a bug.

## Test census — every test removed, by name

Fifteen test functions deleted — 19 pytest node ids, since one is 5-way parametrized —
all of them testing `consumer_smoke.py` itself. Collected count 1772 -> 1761 (net -11:
19 out, 8 in from the new rule-8 guard, 1 renamed). Subtests 3992 -> 681: the whole
3311 delta is the single `test_the_smoke_grades_against_the_SAME_independent_formulation`
sweep (266 corpus uids + 8 predicate vectors + 3037 encoder ids), which compared two
COPIES of a predicate rather than a predicate against the codec. No codec coverage moved:
`test_encode_decode_is_identity_on_every_id` still walks the same 3037 ids.

| test | file | what it proved |
|---|---|---|
| `test_the_smoke_probes_hook_census_is_derived_from_the_install_roster` | test_fresh_project | `consumer_smoke.TRACKED_HOOKS` was derived, not a literal |
| `test_check_all_runs_against_the_release_runners_not_the_consumers` | test_fresh_project | the smoke's worktree carried the release's runners |
| `test_the_row_says_how_many_files_the_release_is_ahead_by` | test_fresh_project | the `runners ahead` row's detail |
| `test_the_consumers_checkout_is_byte_identical_before_and_after` | test_fresh_project | the smoke did not write to the checkout |
| `test_no_worktree_is_left_behind_in_the_consumer` | test_fresh_project | worktree teardown |
| `test_a_consumer_already_current_is_zero_ahead_and_still_green` | test_fresh_project | 0-ahead is not "nothing proven" |
| `test_a_header_edited_runner_is_not_a_refusal` | test_fresh_project | `--force` past an edited config header |
| `test_a_failing_install_is_a_red_row_naming_the_file_and_never_a_fallback` | test_fresh_project | no silent fallback to the in-place run |
| `test_an_uncommitted_runner_edit_is_not_a_census_disagreement` | test_fresh_project | the census is asked of the worktree |
| `test_the_worktree_row_tells_a_leak_from_somebody_elses_commit` (5 params) | test_fresh_project | `git worktree list` shape discrimination |
| `test_a_worktree_that_cannot_be_added_is_a_red_row_and_not_a_fallback` | test_fresh_project | pre-gate failure is red, not skipped |
| `test_an_authored_index_that_comes_back_DIFFERENT_reds_the_row` | test_canonicalize | the smoke row's `restored + lost == authored` identity |
| `test_a_chained_scene_is_NOT_DERIVABLE_and_the_row_stays_green` | test_canonicalize | a refusal is accounted for, not counted as loss |
| `test_the_identity_holds_on_a_corpus_with_nothing_wrong_in_it` | test_canonicalize | the control against the identity over-reporting |
| `test_the_smoke_grades_against_the_SAME_independent_formulation` | test_uid_codec | the smoke's predicate restatement had not drifted |

Every one of them names `consumer_smoke` in its body or grades a row the file owns.
**None of them tested a behaviour of the package that survives the deletion**, except the
three canonicalize identity cases and the uid predicate-agreement case, which are items 5
and 2 above.

One node id changed NAME and is not a loss: `CommittedCorpusRoundTrip::
test_census_meets_the_floor_from_both_source_repos` is now
`…::test_census_meets_the_floor_from_both_slices`, because the corpus slices `corpus/nb`
and `corpus/tr` were renamed to `corpus/editor_written` and `corpus/hand_authored` — the
distinction they actually carry, and the one the canonicalize evidence already leans on.

## Not a fix for this

Rebuilding the lost scale inside the same change that deletes the coupling would be two
changes wearing one diff, and the second one is a corpus-growing exercise with a scrubber
to write first. Filed instead so each item above can be taken on its own evidence.
