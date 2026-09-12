#!/usr/bin/env bash
# cc-session-preflight.sh — Claude Code SessionStart hook: prints what this
# session can do BEFORE the first dispatch. Reads the event JSON on stdin, runs
# `preflight` from the session's tree, and prints its rows on STDOUT, which is
# what a SessionStart hook hands the session. It is a courier: the verb reads
# and decides the words; this file never inspects a setting or a process. It
# never blocks a start (never exit 2): every failure says so and exits 0.
# Wire it on SessionStart, unmatched and not async; `install-hooks` emits that.
# `bash cc-session-preflight.sh --self-test` replays its corpus.
set -eu

# --- project config (yours to edit after install — the file is your repo's) --
# The vehicle that runs a devkit verb, from the repo root; anything taking
# `ARGS=<argv>` — the stock `sdlc` target reaches every verb at your pin.
MAKE_SDLC=(make -s sdlc)
# -----------------------------------------------------------------------------

# A header carried from an older install may lack a key: it runs at its stock value.
declare -p MAKE_SDLC >/dev/null 2>&1 || MAKE_SDLC=(make -s sdlc)

HOOK_NAME="cc-session-preflight"
EVENT="SessionStart"
VERB="preflight"

note() { printf '[%s] %s\n' "$HOOK_NAME" "$1" >&2; }
# To the SESSION, not the operator: stdout is what a SessionStart hook injects.
say() { printf '[%s] %s\n' "$HOOK_NAME" "$1"; }

# Fail open, never silently: a trap that only said `exit 0` would hide every future breakage.
trap 'note "internal error — no capability report this session"; exit 0' ERR

# read_event — the payload's fields, NUL-terminated, in a fixed order; empty
# when absent or non-string, nothing at all when the payload is not JSON.
# shellcheck disable=SC2016  # literal python source: nothing here is the shell's
read_event() {
	python3 -c '
import json, sys
try:
	event = json.load(sys.stdin)
except Exception:
	sys.exit(1)
if not isinstance(event, dict):
	sys.exit(1)
for key in sys.argv[1:]:
	value = event.get(key)
	sys.stdout.write((value if isinstance(value, str) else "") + "\0")
' "$@" 2>/dev/null
}

# --- --self-test — the payload corpus ----------------------------------------
# The wired case runs the vehicle against a stub `sdlc` target that prints ARGS
# one word per line, so the wiring is proven without the package installed.
self_test_payload() {
	python3 -c '
import json, sys
event = {"hook_event_name": sys.argv[1], "source": "startup"}
if sys.argv[2]:
	event["cwd"] = sys.argv[2]
sys.stdout.write(json.dumps(event))
' "$@"
}

# fire <payload> <streams> — `out` is stdout alone (what the session reads),
# `both` is both streams; then `exit=<n>`.
self_test_fire() {
	local rc=0 out
	if [ "$2" = out ]; then
		out="$(printf '%s' "$1" | bash "$0" 2>/dev/null)" || rc=$?
	else
		out="$(printf '%s' "$1" | bash "$0" 2>&1)" || rc=$?
	fi
	printf '%s\nexit=%s\n' "$out" "$rc"
}

self_test_says() {
	local label="$1" got="$2" want="$3"
	case "$got" in
		*"$want"*) return 0 ;;
	esac
	printf '  MISS — %s\n    wanted: %s\n    got: %s\n' \
		"$label" "$want" "${got//$'\n'/ | }" >&2
	return 1
}

# case <label> <payload> <streams> <want>... — every want, and exit 0.
self_test_case() {
	local label="$1" got want
	got="$(self_test_fire "$2" "$3")"
	shift 3
	for want in "$@" 'exit=0'; do
		self_test_says "$label" "$got" "$want" || return 1
	done
}

self_test() {
	local rc=0 tmp repo
	tmp="$(mktemp -d "${TMPDIR:-/tmp}/cc-preflight-selftest.XXXXXX")"
	repo="$tmp/repo"
	mkdir -p "$repo"
	git -C "$repo" init -q

	self_test_case 'a payload that is not JSON' 'not json {{{' both \
		'not JSON this hook can read' || rc=1
	self_test_case 'a cwd outside any git repository' \
		"$(self_test_payload "$EVENT" "$tmp/no-such-tree")" both \
		'not inside a git repository' || rc=1
	self_test_case 'a repo with no Makefile' \
		"$(self_test_payload "$EVENT" "$repo")" both 'has no Makefile' || rc=1

	if command -v make >/dev/null 2>&1; then
		# The wired case, asked of STDOUT alone: a report on stderr is a
		# report the session never reads. `$(ARGS)` is MAKE's expansion.
		# shellcheck disable=SC2016
		printf 'sdlc:\n\t@printf "ARG[%%s]\\n" $(ARGS)\n' >"$repo/Makefile"
		self_test_case 'the verb reaches the session on stdout' \
			"$(self_test_payload "$EVENT" "$repo")" out \
			"ARG[$VERB]" 'what this session can do' || rc=1
		# A vehicle that fails is still exit 0 — and the session is TOLD it
		# starts without a report, rather than left to assume one ran.
		printf 'sdlc:\n\t@echo "unknown command" >&2; false\n' >"$repo/Makefile"
		self_test_case 'a failing vehicle is named to the session' \
			"$(self_test_payload "$EVENT" "$repo")" out \
			'WITHOUT a capability report' 'unknown command' || rc=1
		# The silent vehicle: exit 0 and not a word never reached the verb.
		printf 'sdlc:\n\t@true\n' >"$repo/Makefile"
		self_test_case 'a vehicle that exits 0 without reaching the verb' \
			"$(self_test_payload "$EVENT" "$repo")" out 'without a word' || rc=1
	else
		echo "  SKIP — make is not on PATH; the vehicle cases did not run" >&2
	fi
	rm -rf "$tmp"

	if [ "$rc" -eq 0 ]; then
		echo "[$HOOK_NAME] SELF-TEST OK — every case exits 0, and the report reaches stdout"
	else
		echo "[$HOOK_NAME] SELF-TEST FAIL — see the case(s) above" >&2
	fi
	return "$rc"
}

if [ "${1:-}" = "--self-test" ]; then
	# Through `||`, so the fail-open ERR trap cannot turn a self-test failure into exit 0.
	self_test_rc=0
	self_test || self_test_rc=$?
	exit "$self_test_rc"
fi

# --- the hook -----------------------------------------------------------------
command -v python3 >/dev/null 2>&1 || {
	note "python3 is not on PATH, so the event cannot be parsed — no capability report"
	exit 0
}

INPUT="$(cat)"

FIELDS=()
while IFS= read -r -d '' value; do
	FIELDS+=("$value")
done < <(printf '%s' "$INPUT" | read_event cwd)

if [ "${#FIELDS[@]}" -ne 1 ]; then
	note "the event payload is not JSON this hook can read — no capability report"
	exit 0
fi
SESSION_CWD="${FIELDS[0]}"
[ -n "$SESSION_CWD" ] || SESSION_CWD="$PWD"

REPO_ROOT="$(git -C "$SESSION_CWD" rev-parse --show-toplevel 2>/dev/null || true)"
if [ -z "$REPO_ROOT" ]; then
	note "$SESSION_CWD (the $EVENT payload's cwd) is not inside a git repository — no capability report"
	exit 0
fi

cd "$REPO_ROOT"

if [ ! -f Makefile ]; then
	note "$REPO_ROOT has no Makefile, so ${MAKE_SDLC[*]} cannot run — no capability report"
	exit 0
fi

# Stdout is the report; stderr is kept apart so a download line from the
# vehicle never lands among the rows, and is passed through to the operator.
err_file="$(mktemp "${TMPDIR:-/tmp}/cc-preflight.XXXXXX")"
verb_rc=0
verb_out=""
verb_out="$("${MAKE_SDLC[@]}" ARGS="$VERB" 2>"$err_file")" || verb_rc=$?
verb_err="$(cat "$err_file")"
rm -f "$err_file"

if [ "$verb_rc" -ne 0 ]; then
	say "${MAKE_SDLC[*]} ARGS=$VERB exited $verb_rc — this session starts WITHOUT a capability report:"
	[ -z "$verb_out" ] || printf '%s\n' "$verb_out"
	[ -z "$verb_err" ] || printf '%s\n' "$verb_err"
elif [ -z "$verb_out" ]; then
	say "${MAKE_SDLC[*]} ARGS=$VERB exited 0 without a word — the vehicle never reached the verb (is the \`sdlc\` target present, and .PHONY?) — no capability report"
else
	[ -z "$verb_err" ] || printf '%s\n' "$verb_err" >&2
	say "what this session can do, before the first dispatch — \`$VERB\`, one row per capability: capability, value, meaning (tab-separated)"
	printf '%s\n' "$verb_out"
fi
exit 0
