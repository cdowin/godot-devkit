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

## D3 — 2026-08-29 — two idempotence contracts, recorded not flattened
**Chose:** recording per-verb replay exit codes — fill-gaps verbs exit 0, story and bug REFUSE
**Over:** dropping the refusing verbs from the replay sequence to make it uniform
**Because:** a story and a bug are one authored file each, so re-scaffolding could only mean overwrite; narrowing the sequence would convert a real distinction into a silent pass
**Evidence:** tests/test_replay_migration.py:70

## D4 — 2026-08-29 — a golden corpus, checksummed
**Chose:** committing the log-schema findings as a golden file whose header carries a checksum of the corpus that produced them
**Over:** diffing behaviour against an older git revision of the code
**Because:** an old revision stops being buildable, while a checksum makes a change to the GENERATOR report itself instead of silently redescribing different inputs
**Evidence:** tests/corpus/log_schema.golden.txt:1
