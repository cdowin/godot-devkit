---
id: bg-a-parse-error-waits-for-the-hard-timeout
kind: bug
milestone: "1.2.0"
name: A scenario with a GDScript parse error hangs to HARD_TIMEOUT instead of failing fast
status: open
caused_by:
changelog: A scenario whose script does not parse fails within seconds and names the parse error, instead of timing out as a hang (#12).
---

# a-parse-error-waits-for-the-hard-timeout

GitHub issue #12.

## Symptom

`make scenario NAME=<x>` on a scenario whose script has a GDScript parse error (an undeclared
identifier) prints `SCRIPT ERROR: Parse Error`, then `Invalid call. Nonexistent function 'new' in
base 'GDScript'` from the consumer's scenario runner, then waits for the full
`GDK_SCENARIO_HARD_TIMEOUT` (60s) and reports `HARD_TIMEOUT — exceeded 60s, killed (likely hang)`.
Three such scenarios in a loop cost three minutes, and the verdict points the reader at a hang
rather than at the parse error that is already on stderr.

## Root cause

`scenario.sh` bounds the engine with `gdk_run_bounded` and reads the transcript only after the
process exits. A runner whose `load()` returns null does not quit, so the only exit is the timeout,
and the timeout verdict never looks at what the transcript says.

## Fix

In `src/godot_devkit/godot/installables/scenario.sh` (the path `integration.sh` also runs):
- While the engine runs, watch its capture for Godot's parse-error signature (`SCRIPT ERROR: Parse
  Error` or `Parse Error:`). On the first match, stop the run through the same kill path the bound
  uses, and print `[<TAG>] <name> FAIL — GDScript parse error: <the matched line>`. That is a FAIL,
  not a HARD_TIMEOUT, and it exits 1.
- As a backstop, when a run does reach HARD_TIMEOUT and its transcript holds that signature, the
  verdict names the parse error instead of "likely hang".
- Prove it once, in the existing runner corpus/self-test: a stub engine that prints the signature
  and then sleeps must FAIL fast and name the error. No new test module. CHANGELOG bullet, patch.
