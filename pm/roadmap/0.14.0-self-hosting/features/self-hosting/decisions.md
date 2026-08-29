Append with `godot-devkit pm decide <grain-id>` — never by hand; the command stamps the date and the next ordinal.

# 0.14.0/self-hosting devkit runs its own gates on its own tree — decisions

Durable. This log outlives the grain: when the milestone closes it collapses to
pointers, and everything that still explains a live constraint stays.

> Never write what is derivable. `pm status` gives tallies, `git log` gives
> history. This file holds the WHY that neither of them records.

## D1 — 2026-08-29 — the roster is per-repo config
**Chose:** name the gate roster for this repo in [checks] all
**Over:** a per-gate opt-out saying an empty census is acceptable here
**Because:** which gates apply is a property of the repo; an empty-census opt-out would let a real over-exclusion pass in silence
**Evidence:** src/godot_devkit/cli.py:87

## D2 — 2026-08-29 — the fixture corpus is excluded, not reported
**Chose:** exclude tests/fixtures/ from [uid], [tres] and [props]
**Over:** leaving the deliberately-drifted corpus reported at the repo root
**Because:** the fixtures are test INPUT, and the tests copy them into temp repos, so every gate is still proven to fire on them
**Evidence:** devkit.toml:24

## D3 — 2026-08-29 — D8 is right and does not apply here
**Chose:** leave D8 off for this package
**Over:** bumping pyproject.toml to 0.14.0 at milestone start so D8 passes
**Because:** D8 encodes bump-at-START and this package bumps at close; publishing a version that does not exist is worse than an unused rule
**Evidence:** devkit.toml:37

## D4 — 2026-08-29 — one definition of what a story is
**Chose:** resolve a story id through the same grain_docs walk the gates use
**Over:** a second recursive glob inside the resolver
**Because:** the two disagreeing is what let check pm report a story that pm story wip then refused to move
**Evidence:** src/godot_devkit/repo/pm/model.py:572

## D5 — 2026-08-29 — one key scopes the whole gate
**Chose:** read [uid] exclude_prefixes in CHECK 2 as well as CHECK 1
**Over:** documenting that the key only scopes the ref-drift half
**Because:** one documented key that scopes half a gate is a key that does not scope the gate
**Evidence:** src/godot_devkit/godot/checks/uid.py:151

## D6 — 2026-08-29 — an empty census names both numbers
**Chose:** report scanned 0 of N tracked when a census comes back empty
**Over:** keeping the single scanned 0 files line
**Because:** a repo with no Godot content and an exclude that ate the whole census need different fixes and read identically today
**Evidence:** src/godot_devkit/godot/checks/tres.py:54

## D7 — 2026-08-29 — the shard is forward-only
**Chose:** render 0.14.0 from the tree and leave the historical section frozen verbatim
**Over:** back-filling changelog entries for the sections that predate the tooling
**Because:** deriving entries from prose written before the schema existed is invention, not migration
**Evidence:** CHANGELOG.md:1

## D8 — 2026-08-29 — v0.13.0 outlives its siblings
**Chose:** keep the v0.13.0 section and delete v0.12.0 and older
**Over:** deleting every historical section uniformly
**Because:** v0.13.0 is the only written notice of the DECISIONS.md rename, and trail is pinned at v0.10.0 and has not migrated
**Evidence:** CHANGELOG.md:1

## D9 — 2026-08-29 — the toolkit runs its own gates
**Chose:** Point every gate devkit ships at devkit's own tree
**Over:** Ship gates that only ever run in consumer repos
**Because:** Enabling uid on its own tree is the only thing that surfaced exclude_prefixes scoping just half the gate — a config key that silently half-applied through three releases
**Evidence:** 0c40c20
