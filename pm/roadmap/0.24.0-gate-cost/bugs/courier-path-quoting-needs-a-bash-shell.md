---
id: 0.24.0/bugs/courier-path-quoting-needs-a-bash-shell
milestone: "0.24.0"
name: "the courier hooks' `printf %q` path spelling only decodes under a bash `SHELL`""
status: open
caught_in: "0.24.0"
fix_milestone:
caused_by: 0.23.0/usage-capture
---

# courier-path-quoting-needs-a-bash-shell

## Symptom

v0.23.0 release review n3. `cc-ledger-*.sh` (~:110) spell a non-ASCII transcript path with
`printf %q` (`$'…'`); the installed `Makefile.devkit` sets `SHELL := bash` so the stock route decodes
it, but under a hand-rolled Makefile with dash the `$` survives, `pm ledger record` refuses "is not a
file" at exit 2, and the hook exits 0 — the row is silently lost.

## Root cause

The courier assumes the vehicle's shell is bash; the assumption is true for every stock consumer and
stated nowhere.

## Fix

Pass the path through the environment (`GDK_TRANSCRIPT=… make pm …`) instead of a quoted argv word,
or assert `SHELL` is bash in the courier's self-test corpus and say so in its header. Test: a dash
vehicle case in the courier corpus.
