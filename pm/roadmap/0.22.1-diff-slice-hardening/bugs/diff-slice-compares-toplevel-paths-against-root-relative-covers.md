---
id: 0.22.1/bugs/diff-slice-compares-toplevel-paths-against-root-relative-covers
milestone: "0.22.1"
name: integration.sh::touched_paths lists git-toplevel-relative, C-quoted paths while covers entries are REPO_ROOT-relative
status: open
caught_in: "0.22.1"
fix_milestone:
---

# diff-slice-compares-toplevel-paths-against-root-relative-covers

<!-- A bug lives in the milestone that will FIX it. `caught_in:` keeps the
     provenance; `fix_milestone:` names the decision, and moving the file into
     that milestone's bugs/ is that decision made real. When a milestone is
     retired, `pm retire` reports any bug still open under it. -->

## Symptom

MAJOR (latent) — integration.sh::touched_paths lists git-toplevel-relative, C-quoted paths while covers entries are REPO_ROOT-relative — a Godot project below the git toplevel (game/ in a monorepo) or a non-ASCII path under core.quotePath=true never matches, and --diff silently under-selects (smoke only, no hint). Fix: git diff --name-only --relative after the cd to REPO_ROOT, and -c core.quotePath=false (or -z). Repro in the v0.22.0 release review (scratch fixture: game/systems/alpha/x.gd → 0 SELECT; stripped → SELECT beta_flow). Neither trail nor nullbound is reachable today (root layout, zero non-ASCII paths) — which is why it did not block the cut.

## Root cause

## Fix
