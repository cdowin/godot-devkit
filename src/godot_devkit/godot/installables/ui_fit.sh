#!/usr/bin/env bash
# ui_fit.sh — boot each planned scene under stress; report spilled controls and cut text.
set -uo pipefail

GDK_RUNNERS_LIB="${GDK_RUNNERS_LIB:-../gdk_runners.sh}"
GDK_UI_FIT_SCRIPT="${GDK_UI_FIT_SCRIPT:-res://tools/dev/runners/ui_fit.gd}"
GDK_UI_FIT_TIMEOUT="${GDK_UI_FIT_TIMEOUT:-300}"
GDK_UI_FIT_REPORT_DIR="${GDK_UI_FIT_REPORT_DIR:-.ui-fit-reports}"
GDK_UI_FIT_CAPTURE="${GDK_UI_FIT_CAPTURE:-1}"
GATE_TAG="UI-FIT"

usage() {
	cat <<'USAGE_EOF'
usage: ui_fit.sh -- <godot-devkit command...> | ui_fit.sh <plan.txt>
       ui_fit.sh --help | --self-test

`make ui-fit` passes the godot-devkit command after `--`; the runner asks it
for `ui-fit-plan` (the [ui_fit] section of godot-devkit.toml). A plan file
written by `godot-devkit ui-fit-plan` works too. Boots the engine headless
inside the user:// sandbox, turns on Godot's pseudolocalization, and loads
each scene at the smallest and the largest window (and again after the large
text hook, when the plan names one). One line per finding:

  spills  <scene> : <node path> — a visible Control leaves its parent's rect
  cut     <scene> : <node path> — a Label/Button's text does not fit and it
          set neither autowrap_mode nor text_overrun_behavior

A plan with no scene, a scene that does not boot, or an engine ERROR line is a
failure. For each scene with findings, render.sh draws a PNG to
.ui-fit-reports/ (needs a display; GDK_UI_FIT_CAPTURE=0 skips it).

Env: GDK_UI_FIT_TIMEOUT seconds (default 300), GDK_UI_FIT_REPORT_DIR,
     GDK_UI_FIT_CAPTURE 0|1, GDK_UI_FIT_SCRIPT helper path, GDK_GODOT engine
Exit: 0 pass | 1 findings | 2 harness/usage error
USAGE_EOF
}

# plan_scenes <plan> — how many scenes the plan names. Pure: the self-test
# fires it at fixture plans with no project.
plan_scenes() {
	[ -f "$1" ] || { echo 0; return 0; }
	grep -c '^scene res://' "$1" || true
}

# png_name <res://a/b.tscn> — the capture file name for one scene.
png_name() {
	local rel="${1#res://}"
	rel="${rel%.tscn}"
	printf '%s.png\n' "${rel//\//__}"
}

self_test() {
	local failures=0 cases=0 tmp got
	tmp="$(mktemp -d)" || return 1
	check() {
		cases=$((cases + 1))
		[ "$1" = "$2" ] || { echo "  MISS — $3: want '$2', got '$1'" >&2; failures=$((failures + 1)); }
	}
	printf 'window 1280 720\nwindow 3840 2160\nscene res://ui/gallery/a.tscn\nscene res://ui/b c.tscn\n' > "$tmp/two"
	printf 'window 1280 720\nwindow 3840 2160\n' > "$tmp/none"
	got="$(plan_scenes "$tmp/two")"; check "$got" 2 'a plan with two scenes'
	got="$(plan_scenes "$tmp/none")"; check "$got" 0 'a plan with no scene'
	got="$(plan_scenes "$tmp/missing")"; check "$got" 0 'no plan file'
	got="$(png_name res://ui/gallery/a.tscn)"; check "$got" ui__gallery__a.png 'the capture name'
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
case "$GDK_UI_FIT_TIMEOUT" in
	''|*[!0-9]*|0) echo "[$GATE_TAG] GDK_UI_FIT_TIMEOUT must be positive seconds" >&2; exit 2 ;;
esac
case "$GDK_UI_FIT_CAPTURE" in
	0|1) ;;
	*) echo "[$GATE_TAG] GDK_UI_FIT_CAPTURE must be 0 or 1" >&2; exit 2 ;;
esac

RUNNER_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)" || exit 2
REPO_ROOT="$(cd "$RUNNER_DIR/../../.." && pwd)" || exit 2
LIB="$RUNNER_DIR/$GDK_RUNNERS_LIB"
[ -f "$LIB" ] || { echo "[$GATE_TAG] gdk_runners.sh not found" >&2; exit 2; }
cd "$REPO_ROOT" || exit 2
# shellcheck source=/dev/null
source "$LIB"
[ -f "$GDK_PROJECT_FILE" ] || { echo "[$GATE_TAG] project.godot not found" >&2; exit 2; }
if ! DEFECT="$(gdk_report_dir_defect "$GDK_UI_FIT_REPORT_DIR")"; then
	echo "[$GATE_TAG] GDK_UI_FIT_REPORT_DIR $DEFECT" >&2
	exit 2
fi
if [ -z "$PLAN" ]; then
	# The godot-devkit command resolves [ui_fit] (pure parse; it FAILS a census
	# of 0 itself). It runs before the HOME sandbox: its own tool cache lives in
	# the real HOME.
	PLAN="$(mktemp)" || exit 2
	gdk_on_exit "rm -f -- '$PLAN'"
	"$@" ui-fit-plan > "$PLAN"
	PLAN_STATUS=$?
	[ "$PLAN_STATUS" -eq 0 ] || exit "$PLAN_STATUS"
fi
TOTAL="$(plan_scenes "$PLAN")"
if [ "$TOTAL" -eq 0 ]; then
	echo "[$GATE_TAG] FAIL — the plan names 0 scenes; check [ui_fit] scenes in godot-devkit.toml"
	exit 1
fi

gdk_sandbox_home
LOG="$(gdk_gate_log ui-fit)"
RAW="$(gdk_run_bounded "$GDK_UI_FIT_TIMEOUT" -- \
	"$GDK_GODOT" --headless --path . -s "$GDK_UI_FIT_SCRIPT" -- --plan "$PLAN" 2>&1)"
STATUS=$?
gdk_gate_publish "$LOG" "$RAW"
if gdk_timeout_is_hang "$STATUS"; then
	gdk_gate_verdict "$GATE_TAG" "HANG (${GDK_UI_FIT_TIMEOUT}s)" "$LOG"
	exit 2
fi
RESULT="$(printf '%s\n' "$RAW" | grep -a '^UI_FIT_RESULT ' | tail -1)"
FINDINGS="$(printf '%s\n' "$RAW" | grep -aE '^  (spills|cut)  ')"
FAILS="$(printf '%s\n' "$RAW" | grep -ac '^UI_FIT_FAIL ')"
ERRORS="$(printf '%s\n' "$RAW" | grep -acE '^(SCRIPT )?ERROR:')"
COUNT=0
[ -z "$FINDINGS" ] || COUNT="$(printf '%s\n' "$FINDINGS" | wc -l | tr -d ' ')"
BOOTED=0
[ -z "$RESULT" ] || read -r _ BOOTED _ <<<"$RESULT"
[ -z "$FINDINGS" ] || printf '%s\n' "$FINDINGS"

CAPTURES=''
if [ "$COUNT" -gt 0 ] && [ "$GDK_UI_FIT_CAPTURE" = 1 ]; then
	mkdir -p "$GDK_UI_FIT_REPORT_DIR" || exit 2
	while read -r _ SCENE; do
		OUT="$GDK_UI_FIT_REPORT_DIR/$(png_name "$SCENE")"
		if bash "$RUNNER_DIR/render.sh" "$SCENE" --out "$OUT" >/dev/null 2>&1; then
			CAPTURES="$CAPTURES $OUT"
		else
			CAPTURES="$CAPTURES (no capture for $SCENE)"
		fi
	done < <(printf '%s\n' "$RAW" | grep -a '^UI_FIT_DIRTY ')
fi

if [ -z "$RESULT" ] || [ "$FAILS" -ne 0 ] || [ "$ERRORS" -ne 0 ] || [ "$BOOTED" -eq 0 ]; then
	printf '%s\n' "$RAW" | grep -aE '^(UI_FIT_FAIL|(SCRIPT )?ERROR:)' | head -5
	gdk_gate_verdict "$GATE_TAG" "FAIL ($BOOTED of $TOTAL scene(s) booted: engine=$STATUS, $FAILS harness failure(s), $ERRORS engine error(s), $COUNT finding(s))" "$LOG"
	exit 1
fi
if [ "$COUNT" -gt 0 ]; then
	gdk_gate_verdict "$GATE_TAG" "FAIL ($COUNT finding(s) in $BOOTED scene(s)${CAPTURES:+; captures:$CAPTURES})" "$LOG"
	exit 1
fi
gdk_gate_verdict "$GATE_TAG" "PASS ($BOOTED of $TOTAL scene(s), 0 findings)" "$LOG"
