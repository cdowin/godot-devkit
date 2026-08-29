Append with `godot-devkit pm changelog <milestone-id>` — never by hand; the command stamps the date and the next ordinal.

# 0.14.0 self hosting — changelog

Durable. What was built that a player cares about, in the words a player would
use. It survives close: a milestone's notes matter most once it has shipped.

> One entry per thing somebody would notice, and a reference proving it landed.
> The reasoning behind it is a decision, not a release note — that goes in
> `decisions.md`. `pm changelog --render` unions every milestone's log, newest
> first, and this file is the only place its entries come from.

## C1 — 2026-08-29 — a milestone has release notes
**What:** `pm changelog <milestone-id> --what … --evidence …` appends a release note to that milestone's own log.
**Evidence:** e432831

## C2 — 2026-08-29 — the whole log, newest release first
**What:** `pm changelog --render` prints the union of every milestone's notes to stdout, newest release first.
**Evidence:** e432831

## C3 — 2026-08-29 — read a grain's decisions back
**What:** `pm decisions <grain-id>` prints that grain's decision entries, parsed — a milestone printing its own log and its features'.
**Evidence:** e432831

## C4 — 2026-08-29 — D15 holds a changelog entry to its schema
**What:** D15 checks every `changelog.md` entry carries **What:** and **Evidence:**, with a `changelog_grandfather` ledger for legacy text.
**Evidence:** e432831

## C5 — 2026-08-29 — D16 stops a release shipping with no notes
**What:** D16 fails a `done` milestone whose changelog is missing, empty, or holds only entries D15 already reports.
**Evidence:** e432831

## C6 — 2026-08-29 — existing milestones need one re-scaffold
**What:** UPGRADE: `changelog.md` is a new canonical slot, so run `pm new milestone <id>` once per existing milestone to fill the gap.
**Evidence:** e432831

## C7 — 2026-08-29 — D17 caps grain prose as a ratchet
**What:** D17 caps the line count of a story, a `feature.md`, a bug, a feature's `decisions.md` and a `changelog.md`, with the caps as config.
**Evidence:** dcb2511

## C8 — 2026-08-29 — D18 collapses a closed milestone's trail
**What:** D18 fails a `done` milestone still carrying its raw decision trail — close evidence is pointers, not the log.
**Evidence:** dcb2511

## C9 — 2026-08-29 — pm prose-ledger, which will not raise a ceiling
**What:** `pm prose-ledger` regenerates D17's debt ledger to stdout and REFUSES to raise an existing ceiling.
**Evidence:** dcb2511

## C10 — 2026-08-29 — a short --evidence says how to lengthen it
**What:** A commit hash one character short of the minimum is now refused with the count, the minimum, and the `git rev-parse` that fixes it.
**Evidence:** dcb2511

## C11 — 2026-08-29 — a balanced backtick span no longer opens a fence
**What:** A paragraph opening with a balanced inline code span no longer masks the rest of the document, which had hidden real findings from `check doc` and D12.
**Evidence:** 2eaae12

## C12 — 2026-08-29 — a fence quoted inside a comment is not malformed
**What:** A lone fence marker inside a paired HTML comment is no longer reported MALFORMED — the two markers hide each other and document order settles it.
**Evidence:** 2eaae12

## C13 — 2026-08-29 — check agents reports what it cannot decode
**What:** `check agents` reports an agent definition it cannot decode and takes it OUT of the scanned count, instead of dropping it in silence.
**Evidence:** 2eaae12

## C14 — 2026-08-29 — stories/ is walked recursively
**What:** A story at `stories/<subdir>/<name>.md` or named `.MD` is visible to every `check pm` rule, the way bugs already were.
**Evidence:** 2eaae12

## C15 — 2026-08-29 — a grain is its frontmatter
**What:** A `.md` under `bugs/` or `stories/` with no frontmatter block is a note parked beside the grains, not a grain with an empty status.
**Evidence:** 2eaae12

## C16 — 2026-08-29 — pm new refuses instead of tracebacking
**What:** `pm new` on an over-long grain name or an unwritable `pm/roadmap/` refuses with the reason, and nothing is written.
**Evidence:** 2eaae12

## C17 — 2026-08-29 — check doc's FAIL line carries its census
**What:** `check doc` names how many docs it read and how many fenced lines it skipped on FAIL, not only on PASS.
**Evidence:** 2eaae12

## C18 — 2026-08-29 — check all runs the gates that apply to your repo
**What:** New `[checks] all` in devkit.toml names the gates `check all` runs here; an unknown name is exit 2, never a quietly narrowed run.
**Evidence:** src/godot_devkit/cli.py:87

## C19 — 2026-08-29 — a nested story is addressable by id
**What:** `pm story <state> <id>` resolves a story anywhere under `stories/`, so the gate can no longer report one the verb refuses.
**Evidence:** src/godot_devkit/repo/pm/model.py:572

## C20 — 2026-08-29 — [uid] exclude_prefixes scopes both uid checks
**What:** `[uid] exclude_prefixes` now scopes the sidecar-tracking check too, not just the ref-drift one.
**Evidence:** src/godot_devkit/godot/checks/uid.py:151

## C21 — 2026-08-29 — an empty census says what it was out of
**What:** A `uid`/`tres`/`props` run that scans nothing now reports "0 of N tracked", so an empty repo and an over-broad exclude stop reading identically.
**Evidence:** src/godot_devkit/godot/checks/tres.py:54

## C22 — 2026-08-29 — the toolkit runs its own gates on itself
**What:** godot-devkit carries its own PM tree at `pm/roadmap/`, with every rule it ships enabled, and its own CHANGELOG rendered from it.
**Evidence:** devkit.toml:1

## C23 — 2026-08-29 — a release heading names its tag and its date
**What:** A rendered release heading is now `## v<id> — <actual_date>`, matching the git tag it maps to; a milestone that has not shipped renders `## v<id>` with no invented date.
**Evidence:** src/godot_devkit/repo/pm/cli.py:1218
