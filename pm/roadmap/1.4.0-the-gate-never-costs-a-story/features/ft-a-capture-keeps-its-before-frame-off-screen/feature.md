---
id: ft-a-capture-keeps-its-before-frame-off-screen
kind: feature
milestone: "1.4.0"
name: a capture keeps its before frame off screen
status: done
reviewed: docs/reviews/2026-09-29-1.4.0-a-capture-keeps-its-before-frame-off-screen.md
depends_on: []
consumed_by: []
changelog: capture.sh keeps the previous PNG under previous/, places its window off screen unless CAPTURE_VISIBLE=1, and warns on a capture loop (#17 #37).
---

# a capture keeps its before frame off screen

Issues: #17, #37.

`capture.sh` has two costs:

- **#17** It clears the whole report directory before every run, so a before/after comparison
  means copying the first PNG out by hand.
- **#37** Its headed window lands on the developer's screen and steals focus. An agent looping a
  capture did that about a dozen times in an hour.

## Decided (do not re-plan)

- **Rotate, do not clear (#17).** Before the boot, move `<dir>/<name>.png` (if present) to
  `<dir>/previous/<name>.png`, overwriting an older previous. Delete nothing else. `previous/` is
  never itself rotated or cleared. Freshness stays structural per NAME: `<name>.png` is moved away
  before the boot, so its presence afterwards proves this run wrote it. Rewrite the header's
  "clears the WHOLE of it" paragraph to say this, and keep the refusal of a report dir the wrapper
  may not own. The self-test corpus from the issue: rotation on a first run (no previous), rotation
  on a second run, previous/ is never rotated, a report dir the wrapper does not own is still
  refused.
- **Off-screen by default (#37).** The boot passes `--position <x>,<y>` with an off-screen default
  (`GDK_CAPTURE_POSITION`, default `-10000,-10000`), so the window exists and rasterises but is not
  in view. `CAPTURE_VISIBLE=1` omits the flag. Check how Godot 4 handles a fully off-screen
  position on macOS (it may clamp the window back on-screen). If it clamps, use the smallest
  documented mechanism that keeps the window from taking focus, say which one in the header, and
  list it under NOT verified if you cannot prove it without a display.
- **Loop warning (#37).** Each run appends a timestamp to `<dir>/.runs`, keeping the last 50. When
  the same capture name has run more than 5 times in 10 minutes, print one `WARN` line naming the
  count and `CAPTURE_VISIBLE`. It is a warning, never a refusal.
- #17's "boots its own instance, independent of OS focus": the wrapper already boots its own
  process, and the off-screen default is the kit side. Synthesised input is the consumer harness's.
- Minor bump: the report-dir layout and a new env var.

## Ship criterion

- `capture.sh --self-test` proves the four rotation cases and the loop warning's arithmetic,
  booting nothing.
- The boot argv carries the position flag by default and not under `CAPTURE_VISIBLE=1` (asserted
  on a stub godot's recorded argv).

## Proof budget

  cases: 5-6, capture.sh --self-test
  tier: the runner's self-test corpus
  lands in: src/godot_devkit/godot/installables/capture.sh
  what already covers this: the output-path precheck cases; the clear-everything case is replaced
