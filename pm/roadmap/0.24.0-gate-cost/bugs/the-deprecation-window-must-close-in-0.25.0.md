---
id: 0.24.0/bugs/the-deprecation-window-must-close-in-0.25.0
milestone: "0.24.0"
name: "`todo`/`wip`/`blocked`/`review` ride in the stock vocabulary for 0.24.0 only — 0.25.0 trims them, and each consumer must rewrite its tree before that bump"
status: open
caught_in: "0.24.0"
fix_milestone: "0.25.0"
caused_by: 0.24.0/the-lifecycle-says-what-it-means
---

# the-deprecation-window-must-close-in-0.25.0

Filed as part of C1's fix, so the window cannot outlive the release that opened it. Nothing here is
broken today: this is a **dated obligation** with two halves, one in this package and one in each
consumer, and the failure mode is that both are simply forgotten and a "one release" carve-out
becomes the vocabulary.

## What 0.24.0 ships

`model.DEPRECATED_STATES` maps the four retired words to the canonical words that replaced them, and
`STOCK_STATES` splices each into `LIFECYCLE` immediately after its replacement:

```
planning ready todo building wip blocked reviewing review accepted packaging done
```

- **Read.** D4 accepts a grain at any of the four, so no tree turns red on the pin bump.
- **Never written.** `model.deprecated_write` arms whenever the effective set IS `STOCK_STATES`, and
  `pm story|feature|milestone <retired-word>` exits 2 naming the replacement. The set of files a
  consumer has to rewrite therefore only ever shrinks.
- **Counted out loud.** `check pm` prints one `NOTE` line per run: how many grains hold each retired
  word and what each becomes. Exit code untouched.
- **Named by the tool.** `pm vocabulary` (both shapes) marks the four and says 0.25.0 removes them.

## What 0.25.0 must do

1. Delete `DEPRECATED_STATES` and the `STOCK_STATES` splice from `src/godot_devkit/repo/pm/model.py`;
   `DEFAULT_*_STATES` go back to `LIFECYCLE` and `STALLED_IF_ALL_STORIES_DONE` derives from it again.
2. Delete `model.deprecated_write` and its three call sites in `cli.py` (`_refuse_deprecated`), the
   census in `checks/pm.py`'s `_drift_walk`, and the disclosure blocks in `cmd_vocabulary`.
3. Retire the tests that assert the window: `TheDeprecationWindow` in `tests/test_pm_gate.py`, the
   `test_a_retired_state_is_refused_…` case in `tests/test_pm_verbs.py`, and the window clauses in
   `OneLifecycleAcrossGrains` — restoring `test_the_retired_words_are_gone_from_every_grain`, which
   is the assertion this window suspended.
4. The dwell columns in `pm ledger report` narrow from ten states back to six; the golden tables in
   `tests/test_pm_ledger_report.py` and `tests/test_pm_ledger_report_sections.py` narrow with them.
5. Drop the window paragraphs from `README.md` and `installables/project-devkit.toml`, and say in
   `CHANGELOG.md` that the window closed — that bullet is the one a consumer greps for.

## What each consumer must do FIRST

Both live consumers wire `check pm` into `make check` and therefore into a pre-push hook, so the
rewrite has to land **before** the 0.25.0 pin bump, not after it. Re-derive the census rather than
trusting a number written here — both trees move daily:

```
cd <consumer> && godot-devkit check pm | grep 'NOTE — .* deprecation window'
```

Then rewrite every `status:` line the NOTE counts, in **every grain kind** — milestone, feature,
story alike, not stories only:

| retired | write |
| --- | --- |
| `todo` | `ready` |
| `wip` | `building` |
| `blocked` | `building` |
| `review` | `reviewing` |

`todo → ready`, never `→ planning`: a PO-written, dispatch-ready story is not still being shaped.
Measured on 2026-09-04, after the change: **trail** 25 grains (`todo` ×24, `review` ×1), **nullbound**
37 (`todo` ×36, `wip` ×1). A grain the rewrite reaches through `pm` rather than an editor is written
for you — the verbs refuse the retired word and name the replacement.

Two things the rewrite does NOT cover, because they are not grains:

- **Ledger history.** Rows already written spell the pair `review`/`wip`, and nothing rewrites a
  ledger. `pm ledger report`'s `reopens` column is armed per story and prints `-` for a story whose
  rows predate the migration — by design, and unaffected by the trim.
- **trail's 8 `status: active` documents** under `features/*/plans/`, which the tree walk never
  visits. Not grains, not findings, and not part of this.

## The tell that it was forgotten

`check pm` is silent about the window on a migrated tree, so a consumer that finished the rewrite
hears nothing. The thing to watch is the opposite: a 0.25.0 pin bump on a tree whose NOTE still
prints a census turns every counted grain into a D4 finding, and the pre-push gate that had been
green goes red on the first push after the bump.
