---
id: 0.21.0/ledger/pm-ledger-record
feature: 0.21.0/ledger
milestone: "0.21.0"
name: pm ledger record files a dispatch row by hand when no hook can
status: todo
owner:
depends_on: []
---

# pm ledger record files a dispatch row by hand when no hook can

## Goal
`pm ledger record --grain <id> --role <r> --agent <name> --tokens N --tool-uses N --duration-s N [--verdict V] [--notes …]` appends a `{kind: "dispatch", …}` row; `--grain ?` is legal and means unattributed. `pm ledger --help`.
## Verification
`make test` (round-trip, refusal matrix for bad numbers → exit 2), `make gates`.
## Commit prefix
`feat(0.21.0/ledger/S2):`
## Size
xs
