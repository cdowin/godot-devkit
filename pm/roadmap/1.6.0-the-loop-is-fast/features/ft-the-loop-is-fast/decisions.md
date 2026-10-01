Append with `make pm ARGS='decide <grain-id>'` — never by hand; the command stamps the date and the next ordinal.

# ft-the-loop-is-fast the loop is fast — decisions

Durable. This log outlives the grain: it is where a choice and its rejected
alternative are recorded, and it survives close.

> Never write what is derivable. `pm status` gives tallies, `git log` gives
> history. This file holds the WHY that neither of them records.

## D1 — 2026-10-01 — Review record for 1.6.0 the loop is fast

```
verdict: SHIP
| id | severity | disposition |
```

No independent reviewer pass ran. The feature is small: two runner changes behind opt-out switches.
Proof is the two new regressions in `tests/test_runners_installable.py` plus the full pytest suite and `make check`.
`test_engine_gate_queues_until_the_owner_releases` covers #41. `test_receipt_keys_on_inputs_not_prose_and_is_shared_by_worktrees` covers #42.
