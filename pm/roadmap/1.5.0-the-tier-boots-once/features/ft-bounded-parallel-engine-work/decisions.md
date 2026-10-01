Append with `make pm ARGS='decide <grain-id>'` — never by hand; the command stamps the date and the next ordinal.

# Independent review — 1.5.0 bounded parallel engine work

```
verdict: SHIP
| id | severity | disposition |
| W1 | MAJOR | landed in-place |
```

## W1 — Preserve integration modifiers across lease admission

The lease re-exec now passes the effective `RERUN` and `WARM` values as
`GDK_INTEGRATION_RERUN` and `GDK_INTEGRATION_WARM`. The regression invokes the
installed integration wrapper with `--no-rerun --cold` while warm mode is on,
then asserts the failing stub boots once and stays red. This covers both lost
modifiers through admission.

The lease still covers the wrapper and its descendants; contention returns
75, read-only verbs bypass admission, and inherited descriptors validate against
the host lock. The import self-test checks `.gdignore`, registered nested
worktrees, nested clone source, Git metadata exclusion, symlinks, census, and
copy fallback. The UID change reads only an existing target `.tscn` or `.tres`
header and returns no UID for a headerless target.

Focused review reported four passing stub cases. No real-engine boot was run.

Consumer check repair: scoped shellcheck passes. Integration, capture and import self-tests pass 150, 17 and 20 cases.
Temporary wrappers carry the shared library; stub leases use isolated fixture domains.
Feature close re-asks static checks after scoped builder proof; the full suite belongs to milestone close.
