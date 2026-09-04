---
id: 0.23.0/bugs/diff-slice-compares-toplevel-paths-against-root-relative-covers
milestone: "0.23.0"
name: integration.sh::touched_paths lists git-toplevel-relative, C-quoted paths while covers entries are REPO_ROOT-relative
status: fixed
caught_in: "0.22.1"
fix_milestone: "0.23.0"
---

# diff-slice-compares-toplevel-paths-against-root-relative-covers

<!-- A bug lives in the milestone that will FIX it. `caught_in:` keeps the
     provenance; `fix_milestone:` names the decision, and moving the file into
     that milestone's bugs/ is that decision made real. When a milestone is
     retired, `pm retire` reports any bug still open under it. -->

## Symptom

MAJOR (latent) — integration.sh::touched_paths lists git-toplevel-relative, C-quoted paths while covers entries are REPO_ROOT-relative — a Godot project below the git toplevel (game/ in a monorepo) or a non-ASCII path under core.quotePath=true never matches, and --diff silently under-selects (smoke only, no hint). Fix: git diff --name-only --relative after the cd to REPO_ROOT, and -c core.quotePath=false (or -z). Repro in the v0.22.0 release review (scratch fixture: game/systems/alpha/x.gd → 0 SELECT; stripped → SELECT beta_flow). Neither trail nor nullbound is reachable today (root layout, zero non-ASCII paths) — which is why it did not block the cut.

## Root cause

`touched_paths` ran `git diff --name-only <ref>` and `git ls-files --others` bare: the diff names paths relative to the git TOPLEVEL, and both C-quote a non-ASCII path under `core.quotePath` (git's default) — while every `## covers:` entry, `GDK_SCENARIO_SUBSTRATE_RE` and the discovered scenario file paths are REPO_ROOT-relative and literal. The comparison was between two coordinate systems and two encodings; it only agreed when the project sat at the toplevel and every path was ASCII, which both consumers happen to satisfy.

## Fix

fixed: 3d6cc87 — `git -c core.quotePath=false diff --name-only --relative` from the project root, and the same for the untracked list; a change outside the project is dropped (nothing repo-relative can name it), and the tier's ground is recognised below the toplevel too. Watched red first: corpus case on a monorepo git fixture with `game/` + `café.gd` (85 → 87), three e2e cases (monorepo select, monorepo substrate, non-ASCII) each `{smoke}` at HEAD.
