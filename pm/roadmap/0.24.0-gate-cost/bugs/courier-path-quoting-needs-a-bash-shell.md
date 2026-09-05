---
id: 0.24.0/bugs/courier-path-quoting-needs-a-bash-shell
milestone: "0.24.0"
name: "the courier hooks' `printf %q` path spelling only decodes under a bash `SHELL`""
status: fixed
caught_in: "0.24.0"
fix_milestone: 0.24.0
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

## Resolution

The environment, not the assertion. Asserting `SHELL` is bash in the corpus removes nothing: the
corpus builds its OWN stub Makefile in a temp repo, so the assertion is about the corpus's vehicle
and says nothing about a consumer's hand-rolled one — the consumer keeps losing rows, now with a
sentence in a header saying it was their Makefile's fault. Silent loss is the worst failure a
telemetry courier has, and documenting a footgun does not remove it.

`env_arg <flag> <name> <value>` exports the value and appends the flag in ONE call, and `ARGS`
carries a fixed reference (`"$$GDK_LEDGER_TRANSCRIPT"`) — the same bytes for every value, so no
property of a path can change how the vehicle parses the word. The class is gone rather than
narrowed: the escape that broke is not written any more.

Measured while fixing: the defect is LOCALE-sensitive as well as shell-sensitive. `printf %q` leaves
`café` bare under a UTF-8 locale and escapes it to `$'…\303\251…'` under `C`/`POSIX`/unset, so the
same courier, path and dash vehicle record the row on a machine with a locale and lose it on one
without. `uv run` exports `LC_CTYPE=C.UTF-8`, which hid the case in a first draft of the test; the
corpus and the suite both pin `LC_ALL=C` rather than inherit one.
