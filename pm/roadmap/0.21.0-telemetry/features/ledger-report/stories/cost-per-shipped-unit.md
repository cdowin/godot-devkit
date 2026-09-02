---
id: 0.21.0/ledger-report/cost-per-shipped-unit
feature: 0.21.0/ledger-report
milestone: "0.21.0"
name: report prints tokens per closed story, feature and bug, normalized by size, by role
status: todo
owner:
depends_on: []
---

# report prints tokens per closed story, feature and bug, normalized by size, by role

## Goal
`pm ledger report <ms>` section 1: per closed story / feature / fixed bug — tokens, tool calls, dispatches, by role, normalized by `size:` (s=1, m=2, l=4, xl=8 unless `[ledger] size_weights` in devkit.toml says otherwise); unattributed rows listed at the bottom, never dropped. Quiet table; `--json`.
## Verification
`make test` on a fixture ledger + PM tree; `make gates`.
## Commit prefix
`feat(0.21.0/ledger-report/S1):`
## Size
m
