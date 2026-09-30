#!/usr/bin/env bash
# capture.sh — the HEADED visual-capture wrapper, and the render-verify
# counterpart to scenario.sh.
#
# WHY IT IS NOT `scenario.sh --headed`. Headless is BLIND to render: the
# renderer does not rasterize, so a font-coverage bug, a shader that never
# compiled and a draw call that never ran all pass a headless gate. This boots
# WINDOWED — deliberately no `--headless` — so the pixels actually exist, then
# hands control to a capture scenario the same way scenario.sh does. user:// is
# sandboxed either way.
#
# LOCAL-ONLY: it needs a display. A visual-verification AID, never a CI gate —
# the headless scenario tier is the gate; this proves the pixels drew.
#
# THE CONVENTION: a capture scenario saves its PNG to
# res://.capture-reports/<scenario_name>.png. This wrapper OWNS that directory
# and verifies the PNG after the run, so detection never depends on grepping
# log text. Before the boot it ROTATES: <dir>/<name>.png, if present, moves to
# <dir>/previous/<name>.png (overwriting an older previous), so the last two
# captures of a name sit side by side for a before/after comparison. Nothing
# else is deleted, and previous/ is never itself rotated or cleared. Freshness
# stays STRUCTURAL, per name: <name>.png is moved away before the boot, so its
# presence afterwards proves this run wrote it — a consumer's directory once
# reached 131 files going back two months, and a stale PNG read as current cost
# an agent real time. A move that fails refuses the run rather than leave a
# stale PNG to pass for a fresh one.
#
# OFF SCREEN BY DEFAULT. The boot passes `--position <x>,<y>`
# (GDK_CAPTURE_POSITION, default 100000,100000), so the window exists and
# rasterizes out of view instead of landing on the developer's screen and
# taking focus; CAPTURE_VISIBLE=1 omits the flag, to watch. CAVEAT, from
# reading Godot 4's source rather than a display: the desktop display servers
# (macOS and Windows at least) CLAMP a new window's position into the screen's
# usable rect, so there an off-screen position may land at the screen's edge
# instead. The default is bottom-RIGHT for that reason: a clamp there leaves
# most of the window past the edge, where a top-left clamp would show it all. Godot 4 has no command-line flag that stops the window taking focus
# — the documented mechanism is the project setting
# display/window/size/no_focus, which lives in project.godot (or an
# override.cfg), and this wrapper does not write the consumer's project files.
# A project that wants it sets it there.
#
# LOOP WARNING. Every run appends "<epoch> <name>" to <dir>/.runs (the last 50
# are kept). When the same name has run more than 5 times in 10 minutes it
# prints ONE `WARN` line — every headed run opens a window — and runs anyway:
# a warning, never a refusal.
#
# PARAMETERS: the scenario runner takes exactly one user argument, so a
# parameterized capture reads ENVIRONMENT variables — which this wrapper passes
# through untouched.
#
# Usage: tools/dev/runners/capture.sh <scenario_name>
#        tools/dev/runners/capture.sh --help | --self-test
# Exit:  0 = a PNG was rendered | 1 = none was | 2 = harness/usage error
set -uo pipefail

# --- project config (yours to edit after install — the file is your repo's) --
GDK_RUNNERS_LIB="${GDK_RUNNERS_LIB:-../gdk_runners.sh}"
REPO_ROOT_FROM_HERE="../../.."
GDK_SCENARIO_SOURCE_DIR="${GDK_SCENARIO_SOURCE_DIR:-tests/integration}"
GDK_CAPTURE_REPORT_DIR="${GDK_CAPTURE_REPORT_DIR:-.capture-reports}"
GDK_SCENARIO_USER_ARG="${GDK_SCENARIO_USER_ARG:---scenario}"
GDK_CAPTURE_POSITION="${GDK_CAPTURE_POSITION:-100000,100000}"
# Env: GDK_CAPTURE_TIMEOUT  seconds bounding the headed boot (default 120)
#      GDK_GODOT            the engine binary (default `godot`)
#      CAPTURE_VISIBLE=1    boot the window on screen (omit --position)
# -----------------------------------------------------------------------------

GATE_TAG="CAPTURE"
TIMEOUT_SECONDS="${GDK_CAPTURE_TIMEOUT:-120}"
PNG_SUFFIX=".png"
TRANSCRIPT_TAIL_LINES=20
PREVIOUS_SUBDIR="previous"
RUNS_FILE=".runs"
RUNS_KEPT=50
LOOP_WINDOW_SECONDS=600
LOOP_WARN_OVER=5

usage() {
	cat <<'USAGE_EOF'
usage: capture.sh <scenario_name>
       capture.sh --help | --self-test

Boots the project WINDOWED (no --headless, so the renderer rasterizes) in a
sandboxed HOME and runs one capture scenario, which must save its PNG to
res://.capture-reports/<scenario_name>.png. Before the boot the last PNG of
that name moves to <dir>/previous/<scenario_name>.png, so <name>.png afterwards
came from this run and the one before it sits beside it. Nothing is deleted.

The window opens OFF SCREEN (--position GDK_CAPTURE_POSITION) unless
CAPTURE_VISIBLE=1. A name run more than 5 times in 10 minutes prints one WARN.

  --self-test   prove the argument handling, the output-path precheck, the
                rotation, the loop warning and the boot argv, booting nothing
                (a stub engine)
  --help        this message

Env: GDK_CAPTURE_REPORT_DIR   where the PNGs land (gitignore it)
     GDK_CAPTURE_TIMEOUT      seconds bounding the boot (default 120)
     GDK_CAPTURE_POSITION     where the window opens (default 100000,100000)
     CAPTURE_VISIBLE          1 = open the window on screen (no --position)
     GDK_SCENARIO_SOURCE_DIR  where capture scenarios live
     GDK_SCENARIO_USER_ARG    the user arg carrying the scenario name
     GDK_RUNNERS_LIB          path to gdk_runners.sh, relative to this file
     GDK_GODOT                the engine binary (default `godot`)
Exit: 0 rendered | 1 no PNG | 2 harness/usage error
USAGE_EOF
}

# --- the output-path precheck ------------------------------------------------
# Fail FAST, before a ~30s headed boot, if the scenario does not declare the
# conventional path. The wrapper owns res://<dir>/<name>.png; a bespoke path
# (into a directory that later prunes, say) rots in silence and the run reports
# a render failure that never happened.

# scenario_file <name> <source dir> — the scenario script that answers to
# <name>, or nothing. Matched on the two spellings a runner uses: the user
# argument as written in a comment or doc, and the name returned as a
# StringName.
scenario_file() {
	local name="$1" dir="$2"
	[ -d "$dir" ] || return 0
	grep -rl -- "$GDK_SCENARIO_USER_ARG ${name}\|return &\"${name}\"" "$dir" 2>/dev/null | head -1
}

# declares_output_path <file> <name> — true when the scenario names the
# conventional PNG path. A file we cannot find is NOT a failure: an unfound
# scenario is the runner's problem to report after the boot, not a precheck's
# to guess at.
declares_output_path() {
	local file="$1" name="$2"
	[ -n "$file" ] || return 0
	grep -q "$GDK_CAPTURE_REPORT_DIR/${name}${PNG_SUFFIX}" "$file"
}

# --- rotation: the last capture of a name becomes its previous --------------

# rotate_previous <dir> <name> — move <dir>/<name>.png to
# <dir>/previous/<name>.png, overwriting an older previous. Deletes nothing
# else and never touches the rest of previous/. Fails when <name>.png is still
# there afterwards: the verdict reads its presence as "this run wrote it".
rotate_previous() {
	local dir="$1" name="$2"
	local png="$dir/${name}${PNG_SUFFIX}" prev="$dir/$PREVIOUS_SUBDIR"
	mkdir -p "$prev" || return 1
	if [ -e "$png" ]; then
		mv -f "$png" "$prev/${name}${PNG_SUFFIX}" || return 1
	fi
	[ ! -e "$png" ]
}

# --- the loop warning ----------------------------------------------------------

# record_run <runs file> <name> <epoch> — append this run, keep the last
# RUNS_KEPT lines.
record_run() {
	local file="$1" name="$2" now="$3"
	printf '%s %s\n' "$now" "$name" >> "$file" || return 1
	tail -n "$RUNS_KEPT" "$file" > "$file.tmp.$$" && mv -f "$file.tmp.$$" "$file"
}

# recent_runs <runs file> <name> <epoch> — how many runs of <name> the file
# holds inside the LOOP_WINDOW_SECONDS ending at <epoch>. The name goes
# through the environment, not `awk -v`, which would unescape a backslash.
recent_runs() {
	local file="$1" name="$2" now="$3"
	[ -f "$file" ] || { echo 0; return 0; }
	GDK_CAPTURE_RUN_NAME="$name" awk -v since="$((now - LOOP_WINDOW_SECONDS))" '
		{ t = $1; sub(/^[^ ]* /, ""); if (t + 0 >= since && $0 == ENVIRON["GDK_CAPTURE_RUN_NAME"]) c++ }
		END { print c + 0 }' "$file"
}

# loop_warning <runs file> <name> <epoch> — the one WARN line when <name> has
# run more than LOOP_WARN_OVER times in the window, else nothing.
loop_warning() {
	local count
	count="$(recent_runs "$@")"
	[ "$count" -gt "$LOOP_WARN_OVER" ] || return 0
	echo "[$GATE_TAG] $2 WARN — $count runs in the last $((LOOP_WINDOW_SECONDS / 60)) minutes; each headed run opens a window (placed off screen unless CAPTURE_VISIBLE=1)"
}

# --- --self-test -------------------------------------------------------------
self_test() {
	local scratch rc failures=0 cases=0 found out lib repo stub i

	cases=$((cases + 1))
	rc=0; bash "$0" --help >/dev/null 2>&1 || rc=$?
	[ "$rc" -eq 0 ] || { echo "  MISS — --help should exit 0, got $rc" >&2; failures=$((failures + 1)); }

	cases=$((cases + 1))
	rc=0; bash "$0" >/dev/null 2>&1 || rc=$?
	[ "$rc" -eq 2 ] || { echo "  MISS — no scenario name should exit 2, got $rc" >&2; failures=$((failures + 1)); }

	cases=$((cases + 1))
	rc=0; bash "$0" a b >/dev/null 2>&1 || rc=$?
	[ "$rc" -eq 2 ] || { echo "  MISS — two names should exit 2, got $rc" >&2; failures=$((failures + 1)); }

	cases=$((cases + 1))
	rc=0; bash "$0" '' >/dev/null 2>&1 || rc=$?
	[ "$rc" -eq 2 ] || { echo "  MISS — an EMPTY name should exit 2, got $rc" >&2; failures=$((failures + 1)); }

	# The name becomes a FILE NAME under a directory this wrapper moves files
	# within. `../..` must never reach that path join.
	cases=$((cases + 1))
	rc=0; bash "$0" ../escape >/dev/null 2>&1 || rc=$?
	[ "$rc" -eq 2 ] || { echo "  MISS — a name carrying a separator should exit 2, got $rc" >&2; failures=$((failures + 1)); }

	cases=$((cases + 1))
	rc=0; bash "$0" --self-test extra >/dev/null 2>&1 || rc=$?
	[ "$rc" -eq 2 ] || { echo "  MISS — --self-test takes no argument, got $rc" >&2; failures=$((failures + 1)); }

	scratch="$(mktemp -d "${TMPDIR:-/tmp}/gdk-capture-selftest.XXXXXX")" || return 1
	mkdir -p "$scratch/src"
	printf 'const OUTPUT_PNG := "res://%s/good_capture%s"\nfunc name(): return &"good_capture"\n' \
		"$GDK_CAPTURE_REPORT_DIR" "$PNG_SUFFIX" > "$scratch/src/good_capture.gd"
	printf 'const OUTPUT_PNG := "res://pm/somewhere/else.png"\nfunc name(): return &"bad_capture"\n' \
		> "$scratch/src/bad_capture.gd"

	cases=$((cases + 1))
	found="$(scenario_file good_capture "$scratch/src")"
	[ "$found" = "$scratch/src/good_capture.gd" ] \
		|| { echo "  MISS — the scenario file was not found, got '$found'" >&2; failures=$((failures + 1)); }

	cases=$((cases + 1))
	declares_output_path "$(scenario_file good_capture "$scratch/src")" good_capture \
		|| { echo "  MISS — a conforming scenario was rejected by the precheck" >&2; failures=$((failures + 1)); }

	cases=$((cases + 1))
	declares_output_path "$(scenario_file bad_capture "$scratch/src")" bad_capture \
		&& { echo "  MISS — a scenario saving elsewhere passed the precheck" >&2; failures=$((failures + 1)); }

	# An unfound scenario is NOT a precheck failure: refusing here would block
	# every capture whose name this grep cannot spell, and the boot reports the
	# real problem a moment later.
	cases=$((cases + 1))
	declares_output_path "$(scenario_file nobody "$scratch/src")" nobody \
		|| { echo "  MISS — an unfound scenario was refused by the precheck" >&2; failures=$((failures + 1)); }

	# --- rotation (#17): a first run, a second run, previous/ left alone ---
	mkdir -p "$scratch/r"
	printf 'other\n' > "$scratch/r/other.png"

	cases=$((cases + 1))
	rotate_previous "$scratch/r" shot \
		&& [ ! -e "$scratch/r/previous/shot.png" ] && [ -d "$scratch/r/previous" ] \
		&& [ -f "$scratch/r/other.png" ] \
		|| { echo "  MISS — a first run (no PNG yet) should rotate nothing and delete nothing" >&2; failures=$((failures + 1)); }

	cases=$((cases + 1))
	printf 'old\n' > "$scratch/r/previous/shot.png"
	printf 'new\n' > "$scratch/r/shot.png"
	rotate_previous "$scratch/r" shot \
		&& [ ! -e "$scratch/r/shot.png" ] && [ "$(cat "$scratch/r/previous/shot.png")" = new ] \
		&& [ -f "$scratch/r/other.png" ] \
		|| { echo "  MISS — a second run should move <name>.png over previous/<name>.png and nothing else" >&2; failures=$((failures + 1)); }

	cases=$((cases + 1))
	printf 'kept\n' > "$scratch/r/previous/other.png"
	printf 'again\n' > "$scratch/r/shot.png"
	rotate_previous "$scratch/r" shot \
		&& [ "$(cat "$scratch/r/previous/other.png")" = kept ] \
		&& [ ! -e "$scratch/r/previous/previous" ] && [ "$(cat "$scratch/r/other.png")" = other ] \
		|| { echo "  MISS — previous/ must never itself be rotated or cleared" >&2; failures=$((failures + 1)); }

	# --- the loop warning's arithmetic (#37) ---
	cases=$((cases + 1))
	out=''
	: > "$scratch/runs"
	record_run "$scratch/runs" loopy 1000                  # outside the window
	for i in 1 2 3 4 5; do record_run "$scratch/runs" loopy $((2000 + i)); done
	record_run "$scratch/runs" 'other one' 2006            # another name
	[ -z "$(loop_warning "$scratch/runs" loopy 2010)" ] || out="5 runs in the window warned"
	record_run "$scratch/runs" loopy 2010
	case "$(loop_warning "$scratch/runs" loopy 2010)" in
		*"loopy WARN — 6 runs"*CAPTURE_VISIBLE*) ;;
		*) out="${out:+$out; }6 runs in the window did not warn" ;;
	esac
	for i in $(seq 1 60); do record_run "$scratch/runs" filler "$i"; done
	[ "$(wc -l < "$scratch/runs" | tr -d ' ')" -eq "$RUNS_KEPT" ] || out="${out:+$out; }the run log was not trimmed to $RUNS_KEPT"
	[ -z "$out" ] || { echo "  MISS — loop warning: $out" >&2; failures=$((failures + 1)); }

	# --- the wrapper end to end, over a stub engine that records its argv ---
	lib="$(dirname "$0")/$GDK_RUNNERS_LIB"
	[ -f "$lib" ] || lib="$(dirname "$0")/gdk_runners.sh"   # the uninstalled layout
	repo="$scratch/repo"; stub="$scratch/bin"
	mkdir -p "$repo/tools/dev/runners" "$repo/$GDK_SCENARIO_SOURCE_DIR" "$stub"
	cp "$0" "$repo/tools/dev/runners/capture.sh"
	cp "$lib" "$repo/tools/dev/gdk_runners.sh" 2>/dev/null
	printf 'config_version=5\n' > "$repo/project.godot"
	printf 'const OUTPUT_PNG := "res://%s/eyes%s"\nfunc name(): return &"eyes"\n' \
		"$GDK_CAPTURE_REPORT_DIR" "$PNG_SUFFIX" > "$repo/$GDK_SCENARIO_SOURCE_DIR/eyes.gd"
	printf '#!/usr/bin/env bash\nshift 2\nexec "$@"\n' > "$stub/timeout"
	# shellcheck disable=SC2016  # the stub's own $@ and $n, expanded when it runs
	printf '#!/usr/bin/env bash\nprintf "%%s\\n" "$@" > "%s/argv"\nfor a; do n="$a"; done\nmkdir -p "%s"\necho png > "%s/$n%s"\n' \
		"$scratch" "$GDK_CAPTURE_REPORT_DIR" "$GDK_CAPTURE_REPORT_DIR" "$PNG_SUFFIX" > "$stub/godot"
	chmod +x "$stub/timeout" "$stub/godot"

	cases=$((cases + 1))
	rc=0; (cd "$repo" && env -u CAPTURE_VISIBLE -u GDK_CAPTURE_POSITION -u GDK_RUNNERS_LIB \
		PATH="$stub:$PATH" GDK_GODOT=godot bash tools/dev/runners/capture.sh eyes) >/dev/null 2>&1 || rc=$?
	out="$(tr '\n' ' ' < "$scratch/argv" 2>/dev/null)"
	[ "$rc" -eq 0 ] && [ "${out#*--position 100000,100000 --}" != "$out" ] \
		|| { echo "  MISS — the default boot should carry --position 100000,100000 (rc $rc, argv: $out)" >&2; failures=$((failures + 1)); }

	cases=$((cases + 1))
	rm -f "$scratch/argv"
	rc=0; (cd "$repo" && env -u GDK_CAPTURE_POSITION -u GDK_RUNNERS_LIB CAPTURE_VISIBLE=1 \
		PATH="$stub:$PATH" GDK_GODOT=godot bash tools/dev/runners/capture.sh eyes) >/dev/null 2>&1 || rc=$?
	out="$(tr '\n' ' ' < "$scratch/argv" 2>/dev/null)"
	[ "$rc" -eq 0 ] && [ -n "$out" ] && [ "${out#*--position}" = "$out" ] \
		&& [ -f "$repo/$GDK_CAPTURE_REPORT_DIR/$PREVIOUS_SUBDIR/eyes$PNG_SUFFIX" ] \
		|| { echo "  MISS — CAPTURE_VISIBLE=1 should boot without --position and rotate the first PNG (rc $rc, argv: $out)" >&2; failures=$((failures + 1)); }

	# A report dir the wrapper may not own is still refused, before anything moves.
	cases=$((cases + 1))
	rc=0; (cd "$repo" && env -u CAPTURE_VISIBLE -u GDK_RUNNERS_LIB GDK_CAPTURE_REPORT_DIR=. \
		PATH="$stub:$PATH" GDK_GODOT=godot bash tools/dev/runners/capture.sh eyes) >/dev/null 2>&1 || rc=$?
	[ "$rc" -eq 2 ] && [ -f "$repo/$GDK_CAPTURE_REPORT_DIR/eyes$PNG_SUFFIX" ] && [ ! -e "$repo/$PREVIOUS_SUBDIR" ] \
		|| { echo "  MISS — a report dir the wrapper does not own should exit 2 and move nothing, got $rc" >&2; failures=$((failures + 1)); }

	rm -rf "$scratch"

	if [ "$failures" -eq 0 ]; then
		echo "[$GATE_TAG] SELF-TEST OK — $cases case(s)"
		return 0
	fi
	echo "[$GATE_TAG] SELF-TEST FAIL — $failures of $cases case(s), see above" >&2
	return 1
}

case "${1:-}" in
	--help|-h)
		[ "$#" -eq 1 ] || { echo "[$GATE_TAG] --help takes no argument" >&2; exit 2; }
		usage; exit 0 ;;
	--self-test)
		[ "$#" -eq 1 ] || { echo "[$GATE_TAG] --self-test takes no argument. See --help." >&2; exit 2; }
		self_test_rc=0; self_test || self_test_rc=$?; exit "$self_test_rc" ;;
esac
if [ "$#" -ne 1 ]; then
	echo "[$GATE_TAG] exactly one scenario name — got $#. See --help." >&2
	usage >&2
	exit 2
fi
NAME="$1"
case "$NAME" in
	''|*/*|.|..|-*)
		echo "[$GATE_TAG] '$NAME' is not a scenario name. See --help." >&2
		exit 2 ;;
esac

# Off screen unless asked: validated before anything is touched, because a
# typo in either would otherwise boot a window where nobody asked for one.
POSITION_ARGS=()
case "${CAPTURE_VISIBLE:-}" in
	1) ;;
	''|0)
		if [[ ! "$GDK_CAPTURE_POSITION" =~ ^-?[0-9]+,-?[0-9]+$ ]]; then
			echo "[$GATE_TAG] GDK_CAPTURE_POSITION '$GDK_CAPTURE_POSITION' is not <x>,<y>. See --help." >&2
			exit 2
		fi
		POSITION_ARGS=(--position "$GDK_CAPTURE_POSITION") ;;
	*)
		echo "[$GATE_TAG] CAPTURE_VISIBLE '$CAPTURE_VISIBLE' is not 1 or 0. See --help." >&2
		exit 2 ;;
esac

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/$REPO_ROOT_FROM_HERE" && pwd)" || exit 2
LIB="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/$GDK_RUNNERS_LIB"
if [ ! -f "$LIB" ]; then
	echo "[$GATE_TAG] gdk_runners.sh not found at '$LIB' — set GDK_RUNNERS_LIB" >&2
	exit 2
fi
cd "$REPO_ROOT" || exit 2

# shellcheck source=/dev/null
source "$LIB"

if [ ! -f "$GDK_PROJECT_FILE" ]; then
	echo "[$GATE_TAG] $REPO_ROOT is not a Godot project — no $GDK_PROJECT_FILE there." >&2
	exit 2
fi

# This wrapper OWNS the report dir — it rotates PNGs inside it and keeps its
# run log there. That ownership is only safe over a directory it may actually
# own: `GDK_CAPTURE_REPORT_DIR=tests` once emptied tests/.
if CAPTURE_DIR_DEFECT="$(gdk_report_dir_defect "$GDK_CAPTURE_REPORT_DIR")"; then
	:
else
	echo "[$GATE_TAG] GDK_CAPTURE_REPORT_DIR $CAPTURE_DIR_DEFECT" >&2
	echo "[$GATE_TAG] nothing was written or removed. This wrapper MOVES files inside" >&2
	echo "[$GATE_TAG] that directory on every run — point it at one it may own." >&2
	exit 2
fi

OUT="$GDK_CAPTURE_REPORT_DIR/${NAME}${PNG_SUFFIX}"

SCENARIO_FILE="$(scenario_file "$NAME" "$GDK_SCENARIO_SOURCE_DIR")"
if ! declares_output_path "$SCENARIO_FILE" "$NAME"; then
	echo "[$GATE_TAG] ${NAME} FAIL — $SCENARIO_FILE does not save to res://$OUT" >&2
	echo "          (this wrapper owns that path; fix the scenario before running)" >&2
	exit 1
fi

# user:// sandbox — a headed boot runs the same autoload stack a headless one
# does, and writes the same saves.
gdk_sandbox_home

if ! mkdir -p "$GDK_CAPTURE_REPORT_DIR" || ! rotate_previous "$GDK_CAPTURE_REPORT_DIR" "$NAME"; then
	echo "[$GATE_TAG] ${NAME} could not move ${OUT} to $GDK_CAPTURE_REPORT_DIR/$PREVIOUS_SUBDIR/ —" >&2
	echo "          refusing to boot: a PNG left there would read as this run's." >&2
	exit 2
fi

# Advisory only: a run log that cannot be written costs the warning, not the run.
RUNS="$GDK_CAPTURE_REPORT_DIR/$RUNS_FILE"
NOW="$(date +%s)"
record_run "$RUNS" "$NAME" "$NOW" 2>/dev/null || true
loop_warning "$RUNS" "$NAME" "$NOW" >&2

LOG="$(gdk_sandbox_tmpfile capture.XXXXXX)"

# HEADED — deliberately NO --headless, so the renderer rasterizes. Bounded so a
# window that never closes cannot run forever. The engine's exit code is not
# the verdict: the PNG is.
gdk_run_bounded "$TIMEOUT_SECONDS" -- \
	"$GDK_GODOT" --path . ${POSITION_ARGS[@]+"${POSITION_ARGS[@]}"} \
	-- "$GDK_SCENARIO_USER_ARG" "$NAME" > "$LOG" 2>&1 || true

if [ -f "$OUT" ]; then
	echo "[$GATE_TAG] ${NAME} PASS — PNG: ${OUT}  (open it to verify the render)"
	exit 0
fi

{
	echo "[$GATE_TAG] ${NAME} FAIL — no PNG at ${OUT}."
	echo "          A capture scenario must run HEADED (this wrapper drops --headless)"
	echo "          and save_png to res://$OUT. Transcript tail:"
	echo "---- $LOG (tail) ----"
	tail -n "$TRANSCRIPT_TAIL_LINES" "$LOG"
} >&2
exit 1
