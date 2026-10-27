#!/usr/bin/env bash
# render.sh — draw one scene, or a folder of scenes as a contact sheet, to a PNG.
set -uo pipefail

GDK_RUNNERS_LIB="${GDK_RUNNERS_LIB:-../gdk_runners.sh}"
GDK_RENDER_SCRIPT="${GDK_RENDER_SCRIPT:-res://tools/dev/runners/render_scene.gd}"
GDK_RENDER_POSITION="${GDK_RENDER_POSITION:-100000,100000}"
GDK_RENDER_TIMEOUT="${GDK_RENDER_TIMEOUT:-120}"
GATE_TAG="RENDER"

usage() {
	cat <<'USAGE_EOF'
usage: render.sh <scene.tscn> --out <x.png> [--rect X,Y,W,H]
       render.sh --sheet <dir> --out <sheet.png>
       render.sh --help | --self-test

Boots the engine with a real renderer (its window parked off screen;
RENDER_VISIBLE=1 shows it) inside the user:// sandbox and draws a 2D scene
to a PNG. With no --rect the frame is the scene's tile layers, sprites and
controls. --sheet draws every .tscn in one folder (not its subfolders) as a
labeled contact sheet. Paths are res:// or relative to the project root.
The scene's own scripts run while it is drawn. A missing PNG, a scene that
does not load, or an engine ERROR line is a failure.

Env: GDK_RENDER_TIMEOUT seconds (default 120), GDK_RENDER_POSITION x,y,
     GDK_RENDER_SCRIPT helper path, GDK_GODOT engine binary (default godot)
Exit: 0 drawn | 1 findings | 2 harness/usage error
USAGE_EOF
}

# render_args <argv...> — validate the argument surface; set MODE, TARGET,
# OUT and RECT. Prints the reason and returns 2 on a usage error. Pure: it
# reads no file, so the self-test exercises it with no project.
render_args() {
	MODE=scene TARGET='' OUT='' RECT=''
	while [ "$#" -gt 0 ]; do
		case "$1" in
			--out|--rect|--sheet)
				[ "$#" -ge 2 ] && [ -n "$2" ] || { echo "[$GATE_TAG] $1 needs a value" >&2; return 2; }
				case "$1" in
					--out) OUT="$2" ;;
					--rect) RECT="$2" ;;
					--sheet) [ -z "$TARGET" ] || { echo "[$GATE_TAG] one scene or one --sheet" >&2; return 2; }
						MODE=sheet; TARGET="$2" ;;
				esac
				shift 2 ;;
			-*|'') echo "[$GATE_TAG] unknown argument '$1'" >&2; return 2 ;;
			*)
				[ -z "$TARGET" ] || { echo "[$GATE_TAG] one scene or one --sheet" >&2; return 2; }
				TARGET="$1"; shift ;;
		esac
	done
	[ -n "$TARGET" ] || { echo "[$GATE_TAG] name a scene or --sheet <dir>" >&2; return 2; }
	case "$OUT" in
		*.png) ;;
		*) echo "[$GATE_TAG] --out must name a .png" >&2; return 2 ;;
	esac
	if [ -n "$RECT" ]; then
		[ "$MODE" = scene ] || { echo "[$GATE_TAG] --rect is for one scene, not --sheet" >&2; return 2; }
		[[ "$RECT" =~ ^-?[0-9]+,-?[0-9]+,[1-9][0-9]*,[1-9][0-9]*$ ]] || {
			echo "[$GATE_TAG] --rect must be X,Y,W,H with W and H above 0" >&2; return 2; }
	fi
	return 0
}

self_test() {
	local rc failures=0 cases=0
	expect() {
		local want="$1"; shift
		cases=$((cases + 1))
		rc=0; ( render_args "$@" ) >/dev/null 2>&1 || rc=$?
		[ "$rc" -eq "$want" ] || { echo "  MISS — '$*' should exit $want, got $rc" >&2; failures=$((failures + 1)); }
	}
	expect 0 rooms/a.tscn --out a.png
	expect 0 res://rooms/a.tscn --out a.png --rect -8,-8,64,32
	expect 0 --sheet rooms --out sheet.png
	expect 2 rooms/a.tscn
	expect 2 rooms/a.tscn --out a.jpg
	expect 2 --sheet rooms --out s.png --rect 0,0,8,8
	expect 2 rooms/a.tscn --out a.png --rect 0,0,0,8
	expect 2 rooms/a.tscn rooms/b.tscn --out a.png
	expect 2 rooms/a.tscn --out a.png --what
	expect 2 rooms/a.tscn --out
	expect 2 ''
	cases=$((cases + 1))
	rc=0; bash -n "$0" || rc=$?
	[ "$rc" -eq 0 ] || { echo "  MISS — the script does not parse" >&2; failures=$((failures + 1)); }
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
render_args "$@" || { usage >&2; exit 2; }
case "$GDK_RENDER_TIMEOUT" in
	''|*[!0-9]*|0) echo "[$GATE_TAG] GDK_RENDER_TIMEOUT must be positive seconds" >&2; exit 2 ;;
esac
case "${RENDER_VISIBLE:-0}" in
	0)
		[[ "$GDK_RENDER_POSITION" =~ ^-?[0-9]+,-?[0-9]+$ ]] || {
			echo "[$GATE_TAG] GDK_RENDER_POSITION must be x,y" >&2; exit 2;
		}
		POSITION_ARGS=(--position "$GDK_RENDER_POSITION") ;;
	1) POSITION_ARGS=() ;;
	*) echo "[$GATE_TAG] RENDER_VISIBLE must be 0 or 1" >&2; exit 2 ;;
esac

RUNNER_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)" || exit 2
REPO_ROOT="$(cd "$RUNNER_DIR/../../.." && pwd)" || exit 2
LIB="$RUNNER_DIR/$GDK_RUNNERS_LIB"
[ -f "$LIB" ] || { echo "[$GATE_TAG] gdk_runners.sh not found" >&2; exit 2; }
# The PNG lands where the caller asked, so --out resolves against the
# caller's directory before the run moves to the project root.
mkdir -p "$(dirname "$OUT")" || exit 2
OUT="$(cd "$(dirname "$OUT")" && pwd)/$(basename "$OUT")" || exit 2
cd "$REPO_ROOT" || exit 2
# shellcheck source=/dev/null
source "$LIB"
[ -f "$GDK_PROJECT_FILE" ] || { echo "[$GATE_TAG] project.godot not found" >&2; exit 2; }
RES="res://${TARGET#res://}"
LOCAL="${RES#res://}"
if [ "$MODE" = sheet ]; then
	[ -d "${LOCAL:-.}" ] || { echo "[$GATE_TAG] no folder at $RES" >&2; exit 1; }
	ARGS=(--sheet "${RES%/}" --out "$OUT")
else
	[ -f "$LOCAL" ] || { echo "[$GATE_TAG] no scene at $RES" >&2; exit 1; }
	ARGS=(--scene "$RES" --out "$OUT")
	[ -z "$RECT" ] || ARGS+=(--rect "$RECT")
fi
rm -f -- "$OUT"

gdk_sandbox_home
LOG="$(gdk_gate_log render)"
RAW="$(gdk_run_bounded "$GDK_RENDER_TIMEOUT" -- \
	"$GDK_GODOT" --path . ${POSITION_ARGS[@]+"${POSITION_ARGS[@]}"} -s "$GDK_RENDER_SCRIPT" \
	-- "${ARGS[@]}" 2>&1)"
STATUS=$?
gdk_gate_publish "$LOG" "$RAW"
if gdk_timeout_is_hang "$STATUS"; then
	gdk_gate_verdict "$GATE_TAG" "HANG (${GDK_RENDER_TIMEOUT}s)" "$LOG"
	exit 2
fi
RESULT="$(printf '%s\n' "$RAW" | grep -a '^RENDER_RESULT ' | tail -1)"
FAILS="$(printf '%s\n' "$RAW" | grep -ac '^RENDER_FAIL ')"
ERRORS="$(printf '%s\n' "$RAW" | grep -acE '^(SCRIPT )?ERROR:')"
WARNINGS="$(printf '%s\n' "$RAW" | grep -acE '^WARNING:')"
if [ "$STATUS" -ne 0 ] || [ -z "$RESULT" ] || [ ! -f "$OUT" ] || [ "$FAILS" -ne 0 ] || [ "$ERRORS" -ne 0 ]; then
	printf '%s\n' "$RAW" | grep -aE '^(RENDER_FAIL|(SCRIPT )?ERROR:)' | head -5
	gdk_gate_verdict "$GATE_TAG" "FAIL ($RES: engine=$STATUS, $FAILS render failure(s), $ERRORS engine error(s), PNG=$OUT)" "$LOG"
	exit 1
fi
read -r _ DRAWN TOTAL _ <<<"$RESULT"
gdk_gate_verdict "$GATE_TAG" "PASS ($RES: $DRAWN of $TOTAL scene(s), $WARNINGS warning(s), PNG=$OUT)" "$LOG"
