Append with `godot-devkit pm decide <grain-id>` — never by hand; the command stamps the date and the next ordinal.

# 0.15.0 scripted verification — decisions

Durable. This log outlives the grain: when the milestone closes it collapses to
pointers, and everything that still explains a live constraint stays.

> Never write what is derivable. `pm status` gives tallies, `git log` gives
> history. This file holds the WHY that neither of them records.

## D1 — 2026-08-29 — roles, not a shipped Makefile
**Chose:** devkit.toml [tasks] naming which of the project's OWN targets fill the quick and verify roles
**Over:** shipping one Makefile template into every consumer
**Because:** a template copied into three repos is a fork-by-copy that drifts, and both consumers already had precommit and milestone targets to declare — the role set is discovered, not invented
**Evidence:** src/godot_devkit/repo/tasks.py:38

## D2 — 2026-08-29 — check tasks ships opt-in
**Chose:** putting check tasks in EXPLICIT_CHECKS, named by this repo's own [checks] all
**Over:** adding it to the default check all roster
**Because:** a consumer that has not declared [tasks] has no stale role to find, and failing it for the absence reddens every existing consumer on the version bump that introduced the table
**Evidence:** src/godot_devkit/cli.py:98
