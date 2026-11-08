#!/usr/bin/env bash
# fit_sweep.sh — every listed screen at every size class: clipped text, controls out of reach, a PNG each.
set -uo pipefail

GDK_RUNNERS_LIB="${GDK_RUNNERS_LIB:-../gdk_runners.sh}"
GDK_FIT_SWEEP_SCRIPT="${GDK_FIT_SWEEP_SCRIPT:-res://tools/dev/runners/fit_sweep.gd}"
GDK_FIT_SWEEP_TIMEOUT="${GDK_FIT_SWEEP_TIMEOUT:-300}"
GDK_FIT_SWEEP_PNG="${GDK_FIT_SWEEP_PNG:-1}"
GDK_FIT_SWEEP_POSITION="${GDK_FIT_SWEEP_POSITION:-100000,100000}"
GDK_FIT_SWEEP_XVFB="${GDK_FIT_SWEEP_XVFB:-Xvfb}"
GATE_TAG="FIT-SWEEP"

usage() {
	cat <<'USAGE_EOF'
usage: fit_sweep.sh -- <godot-devkit command...> | fit_sweep.sh <plan.txt>
       fit_sweep.sh --help | --self-test

`make fit-sweep` passes the godot-devkit command after `--`; the runner asks
it for `fit-sweep-plan` ([fit_sweep] in godot-devkit.toml: the size-class
table and the scenes). A plan file written by `godot-devkit fit-sweep-plan`
works too. Inside the user:// sandbox it instances each scene at each size of
the table (logical px, in a viewport of exactly that size). One line per
scene, size and node:

  clipped      <scene> <w>x<h> <class>-<role> : <node path> — a Label or
               RichTextLabel whose text does not fit or is clipped, with no
               autowrap and no overrun ellipsis
  unreachable  ... — a focusable Control that leaves the viewport, or whose
               centre a later sibling (of it or an ancestor) covers
  small        ... — a focusable Control under the table's touch target

A PNG per scene per size lands in .gate-reports/fit-sweep/ (the folder is
emptied first). Drawing needs a renderer (the Compatibility one, which runs
wherever OpenGL 3.3 or a software GL does): on $DISPLAY with the window parked
off screen, or on a private Xvfb server when there is no display. GDK_FIT_SWEEP_PNG=0
draws nothing and boots --headless. A plan with no scene, a scene that does not
load, a missing PNG or an engine ERROR line is a failure. A checkout with no
import cache (.godot/global_script_class_cache.cfg) exits 2: run `make import`.

Env: GDK_FIT_SWEEP_TIMEOUT seconds (default 300), GDK_FIT_SWEEP_PNG 0|1,
     GDK_FIT_SWEEP_POSITION x,y, GDK_FIT_SWEEP_XVFB (default Xvfb),
     GDK_FIT_SWEEP_SCRIPT helper path, GDK_GODOT engine
Exit: 0 pass | 1 findings | 2 harness/usage error
USAGE_EOF
}

# plan_count <plan> <kind> — how many `<kind> ` lines the plan holds. Pure:
# the self-test fires it at fixture plans with no project.
plan_count() {
	[ -f "$1" ] || { echo 0; return 0; }
	grep -c "^$2 " "$1" || true
}

# per_scene <ms> <scenes> — seconds per scene, one decimal.
per_scene() {
	[ "$2" -gt 0 ] || { echo 0.0; return 0; }
	awk -v ms="$1" -v n="$2" 'BEGIN { printf "%.1f\n", ms / n / 1000 }'
}

# start_xvfb — a private X server for this run; exports DISPLAY, and the
# server dies with the run.
start_xvfb() {
	local number i
	number="$(mktemp)" || return 1
	"$GDK_FIT_SWEEP_XVFB" -displayfd 1 -nolisten tcp -screen 0 1280x720x24 >"$number" 2>/dev/null &
	gdk_on_exit "kill $! 2>/dev/null; rm -f -- '$number'"
	for i in $(seq 50); do
		[ -s "$number" ] && break
		[ "$i" -lt 50 ] || { echo "[$GATE_TAG] $GDK_FIT_SWEEP_XVFB did not start" >&2; return 1; }
		sleep 0.1
	done
	DISPLAY=":$(tr -d '[:space:]' <"$number")"
	export DISPLAY
}

self_test() {
	local failures=0 cases=0 tmp got
	tmp="$(mktemp -d)" || return 1
	check() {
		cases=$((cases + 1))
		[ "$1" = "$2" ] || { echo "  MISS — $3: want '$2', got '$1'" >&2; failures=$((failures + 1)); }
	}
	printf 'size 800 360 phone-worst\nsize 667 360 phone-floor\ntouch 44\nscene res://ui/a.tscn\nscene res://ui/b c.tscn\n' > "$tmp/two"
	printf 'size 800 360 phone-worst\n' > "$tmp/none"
	got="$(plan_count "$tmp/two" scene)"; check "$got" 2 'a plan with two scenes'
	got="$(plan_count "$tmp/two" size)"; check "$got" 2 'a plan with two sizes'
	got="$(plan_count "$tmp/none" scene)"; check "$got" 0 'a plan with no scene'
	got="$(plan_count "$tmp/missing" scene)"; check "$got" 0 'no plan file'
	got="$(per_scene 2500 2)"; check "$got" 1.2 'seconds per scene'
	got="$(per_scene 0 0)"; check "$got" 0.0 'no scene booted'
	rm -rf "$tmp"
	cases=$((cases + 1))
	bash -n "$0" || { echo "  MISS — the script does not parse" >&2; failures=$((failures + 1)); }
	if [ "$failures" -eq 0 ]; then
		echo "[$GATE_TAG] SELF-TEST OK — $cases case(s)"
		return 0
	fi
	echo "[$GATE_TAG] SELF-TEST FAIL — $failures of $cases case(s), see above" >&2
	return 1
}

case "${1-}" in
	--help|-h)
		[ "$#" -eq 1 ] || exit 2
		usage; exit 0 ;;
	--self-test)
		[ "$#" -eq 1 ] || exit 2
		self_test; exit $? ;;
esac
PLAN=''
if [ "${1-}" = -- ]; then
	shift
	[ "$#" -gt 0 ] || { usage >&2; exit 2; }
else
	[ "$#" -eq 1 ] && [ -n "$1" ] || { usage >&2; exit 2; }
	[ -f "$1" ] || { echo "[$GATE_TAG] no plan at $1" >&2; exit 2; }
	PLAN="$(cd "$(dirname "$1")" && pwd)/$(basename "$1")" || exit 2
fi
case "$GDK_FIT_SWEEP_TIMEOUT" in
	''|*[!0-9]*|0) echo "[$GATE_TAG] GDK_FIT_SWEEP_TIMEOUT must be positive seconds" >&2; exit 2 ;;
esac
[[ "$GDK_FIT_SWEEP_POSITION" =~ ^-?[0-9]+,-?[0-9]+$ ]] || {
	echo "[$GATE_TAG] GDK_FIT_SWEEP_POSITION must be x,y" >&2; exit 2; }
case "$GDK_FIT_SWEEP_PNG" in
	0) ;;
	1)
		[ -n "${DISPLAY:-}" ] || command -v "$GDK_FIT_SWEEP_XVFB" >/dev/null 2>&1 || {
			echo "[$GATE_TAG] drawing needs a display: set DISPLAY, install Xvfb ($GDK_FIT_SWEEP_XVFB), or GDK_FIT_SWEEP_PNG=0 for findings only" >&2
			exit 2; } ;;
	*) echo "[$GATE_TAG] GDK_FIT_SWEEP_PNG must be 0 or 1" >&2; exit 2 ;;
esac

RUNNER_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)" || exit 2
REPO_ROOT="$(cd "$RUNNER_DIR/../../.." && pwd)" || exit 2
LIB="$RUNNER_DIR/$GDK_RUNNERS_LIB"
[ -f "$LIB" ] || { echo "[$GATE_TAG] gdk_runners.sh not found" >&2; exit 2; }
cd "$REPO_ROOT" || exit 2
# shellcheck source=/dev/null
source "$LIB"
[ -f "$GDK_PROJECT_FILE" ] || { echo "[$GATE_TAG] project.godot not found" >&2; exit 2; }
if [ -z "$PLAN" ]; then
	# The godot-devkit command reads [fit_sweep] and the table (pure parse; it
	# FAILS a scenes entry that matches nothing). It runs before the HOME
	# sandbox: its own tool cache lives in the real HOME.
	PLAN="$(mktemp)" || exit 2
	gdk_on_exit "rm -f -- '$PLAN'"
	"$@" fit-sweep-plan > "$PLAN"
	PLAN_STATUS=$?
	[ "$PLAN_STATUS" -eq 0 ] || exit "$PLAN_STATUS"
fi
TOTAL="$(plan_count "$PLAN" scene)"
SIZES="$(plan_count "$PLAN" size)"
if [ "$TOTAL" -eq 0 ] || [ "$SIZES" -eq 0 ]; then
	echo "[$GATE_TAG] FAIL — the plan names $TOTAL scene(s) and $SIZES size(s); check [fit_sweep] in godot-devkit.toml"
	exit 1
fi
# A cold checkout registers no class_name: every scene half-loads and the run
# prints thousands of engine errors that read like a broken project.
if [ ! -f .godot/global_script_class_cache.cfg ]; then
	echo "[$GATE_TAG] no import cache (.godot/global_script_class_cache.cfg); run \`make import\` first" >&2
	exit 2
fi
PNG_DIR="$GDK_GATE_REPORT_DIR/fit-sweep"
SWEEP_ARGS=(--plan "$PLAN")
if [ "$GDK_FIT_SWEEP_PNG" = 1 ]; then
	rm -rf -- "$PNG_DIR"
	mkdir -p "$PNG_DIR" || exit 2
	SWEEP_ARGS+=(--png-dir "$(cd "$PNG_DIR" && pwd)")
	ENGINE_ARGS=(--position "$GDK_FIT_SWEEP_POSITION" --audio-driver Dummy --rendering-method gl_compatibility)
	[ -n "${DISPLAY:-}" ] || start_xvfb || exit 2
else
	ENGINE_ARGS=(--headless)
fi

gdk_sandbox_home
LOG="$(gdk_gate_log fit-sweep)"
RAW="$(gdk_run_bounded "$GDK_FIT_SWEEP_TIMEOUT" -- \
	"$GDK_GODOT" "${ENGINE_ARGS[@]}" --path . -s "$GDK_FIT_SWEEP_SCRIPT" -- "${SWEEP_ARGS[@]}" 2>&1)"
STATUS=$?
gdk_gate_publish "$LOG" "$RAW"
if gdk_timeout_is_hang "$STATUS"; then
	gdk_gate_verdict "$GATE_TAG" "HANG (${GDK_FIT_SWEEP_TIMEOUT}s)" "$LOG"
	exit 2
fi
RESULT="$(printf '%s\n' "$RAW" | grep -a '^FIT_SWEEP_RESULT ' | tail -1)"
FINDINGS="$(printf '%s\n' "$RAW" | grep -aE '^  (clipped|unreachable|small)  ')"
FAILS="$(printf '%s\n' "$RAW" | grep -ac '^FIT_SWEEP_FAIL ')"
ERRORS="$(printf '%s\n' "$RAW" | grep -acE '^(SCRIPT )?ERROR:')"
PNGS="$(printf '%s\n' "$RAW" | grep -ac '^FIT_SWEEP_PNG ')"
COUNT=0
[ -z "$FINDINGS" ] || COUNT="$(printf '%s\n' "$FINDINGS" | wc -l | tr -d ' ')"
BOOTED=0 MS=0
[ -z "$RESULT" ] || read -r _ BOOTED _ _ _ MS <<<"$RESULT"
[ -z "$FINDINGS" ] || printf '%s\n' "$FINDINGS"
PER="$(per_scene "$MS" "$BOOTED") s/scene"
WANT_PNGS=0
[ "$GDK_FIT_SWEEP_PNG" = 0 ] || WANT_PNGS=$((BOOTED * SIZES))
DRAWN="PNGs: off (GDK_FIT_SWEEP_PNG=0)"
[ "$GDK_FIT_SWEEP_PNG" = 0 ] || DRAWN="$PNGS PNG(s) in $PNG_DIR/"

if [ -z "$RESULT" ] || [ "$FAILS" -ne 0 ] || [ "$ERRORS" -ne 0 ] || [ "$BOOTED" -ne "$TOTAL" ] \
		|| [ "$PNGS" -ne "$WANT_PNGS" ]; then
	printf '%s\n' "$RAW" | grep -aE '^(FIT_SWEEP_FAIL|(SCRIPT )?ERROR:)' | head -5
	gdk_gate_verdict "$GATE_TAG" "FAIL ($BOOTED of $TOTAL scene(s) loaded: engine=$STATUS, $FAILS harness failure(s), $ERRORS engine error(s), $PNGS of $WANT_PNGS PNG(s), $COUNT finding(s))" "$LOG"
	exit 1
fi
if [ "$COUNT" -gt 0 ]; then
	gdk_gate_verdict "$GATE_TAG" "FAIL ($COUNT finding(s) over $BOOTED scene(s) x $SIZES size(s), $PER; $DRAWN)" "$LOG"
	exit 1
fi
gdk_gate_verdict "$GATE_TAG" "PASS ($BOOTED of $TOTAL scene(s) x $SIZES size(s), 0 findings, $PER; $DRAWN)" "$LOG"
