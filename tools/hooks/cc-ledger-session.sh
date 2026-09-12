#!/usr/bin/env bash
# cc-ledger-session.sh — Claude Code Stop hook: one ledger row per orchestrator
# stop. Reads the event JSON on stdin, copies the transcript path and session id
# into `pm ledger record`, and exits 0. It is a courier: the verb parses, sums
# and refuses; this file never reads a transcript or invents a row. It never
# blocks a stop (never exit 2): every failure says so on stderr and exits 0.
# Wire it `"async": true` from ANY scope; `install-hooks` emits that wiring.
# `bash cc-ledger-session.sh --self-test` replays the fail-open matrix.
set -eu

# --- project config (yours to edit after install — the file is your repo's) --
# The vehicle that runs `pm`, from the repo root; anything taking `ARGS=<pm argv>`.
# It must be .PHONY (a PM tree IS a `pm/` directory) and must pass its
# environment through (every payload value travels as `GDK_LEDGER_*`).
MAKE_PM=(make -s pm)
# -----------------------------------------------------------------------------

# A header carried from an older install may lack a key: it runs at its stock value.
declare -p MAKE_PM >/dev/null 2>&1 || MAKE_PM=(make -s pm)

# The event is a CONSTANT, not `hook_event_name` off the payload: a mis-wired
# entry must not file a session row for a dispatch stop.
HOOK_NAME="cc-ledger-session"
EVENT="Stop"
TRANSCRIPT_KEY="transcript_path"

note() { printf '[%s] %s\n' "$HOOK_NAME" "$1" >&2; }

# Fail open, never silently: a trap that only said `exit 0` would hide every future breakage.
trap 'note "internal error — no ledger row was written"; exit 0' ERR

# expand_tilde <path> — `~` and `~/…` against $HOME; `~user` is left to the verb's refusal.
expand_tilde() {
	# shellcheck disable=SC2088  # the tilde is the INPUT being matched
	case "$1" in
		'~') printf '%s' "$HOME" ;;
		'~/'*) printf '%s%s' "$HOME" "${1#\~}" ;;
		*) printf '%s' "$1" ;;
	esac
}

# env_arg <flag> <name> <value> — one flag on ARGS, its value in the ENVIRONMENT.
# ARGS crosses make and then a recipe shell that may not be bash, so no value
# is spelled into it: `$$NAME` reaches the verb byte-exact whatever it holds.
env_arg() {
	export "$2=$3"
	ARGS="$ARGS $1 \"\$\$$2\""
}

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
# The recording case runs the vehicle against a stub `pm` target that prints
# ARGS one word per line, so the wiring is proven without a PM tree.
self_test_payload() {
	python3 -c '
import json, sys
keys = ("hook_event_name", "cwd", "session_id", "transcript_path")
event = {k: v for k, v in zip(keys, sys.argv[1:]) if v}
event["stop_hook_active"] = False
event["last_assistant_message"] = "narration the hook must never read"
sys.stdout.write(json.dumps(event))
' "$@"
}

# fire <payload> [<grain>] [<root>] — both streams, then `exit=<n>`.
#
# The child's environment is BUILT, not inherited: the grain and the tree root
# arrive that way, and an operator with either exported would turn every case
# asserting its ABSENCE into a false pass. Every `-u` precedes every
# assignment, because BSD `env` stops reading options at the first NAME=value.
self_test_fire() {
	local rc=0 out
	local child=(env)
	[ -n "${2:-}" ] || child+=(-u GDK_LEDGER_GRAIN)
	[ -n "${3:-}" ] || child+=(-u GDK_LEDGER_ROOT)
	[ -z "${2:-}" ] || child+=("GDK_LEDGER_GRAIN=$2")
	[ -z "${3:-}" ] || child+=("GDK_LEDGER_ROOT=$3")
	out="$(printf '%s' "$1" | "${child[@]}" bash "$0" 2>&1)" || rc=$?
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

self_test_case() {
	local label="$1" payload="$2" want="$3" got
	got="$(self_test_fire "$payload")"
	self_test_says "$label" "$got" "$want" || return 1
	self_test_says "$label (exit code)" "$got" 'exit=0' || return 1
}

self_test() {
	local rc=0 tmp repo other argv want tilde
	# shellcheck disable=SC2088  # a LITERAL leading ~ is the payload under test
	tilde='~/t.jsonl'
	tmp="$(mktemp -d "${TMPDIR:-/tmp}/cc-ledger-selftest.XXXXXX")"
	repo="$tmp/repo"
	mkdir -p "$repo"
	git -C "$repo" init -q

	self_test_case 'a payload that is not JSON' \
		'not json {{{' 'not JSON this hook can read' || rc=1
	self_test_case 'a payload with no transcript path' \
		"$(self_test_payload "$EVENT" "$repo" 'sess-1' '')" \
		"carries no $TRANSCRIPT_KEY" || rc=1
	self_test_case 'a repo with no Makefile' \
		"$(self_test_payload "$EVENT" "$repo" 'sess-1' "$tilde")" \
		'has no Makefile' || rc=1

	# The vehicle end to end; `$(ARGS)` is unquoted so the SHELL splits it.
	if command -v make >/dev/null 2>&1; then
		# shellcheck disable=SC2016  # `$(ARGS)` is MAKE's expansion
		printf 'pm:\n\t@printf "ARG[%%s]\\n" $(ARGS)\n' >"$repo/Makefile"
		argv="$(self_test_fire "$(self_test_payload \
			"$EVENT" "$repo" 'sess-1' "$tilde")")"
		for want in 'ARG[ledger]' 'ARG[record]' 'ARG[--from-transcript]' \
				"ARG[${HOME}/t.jsonl]" 'ARG[--event]' "ARG[${EVENT}]" \
				'ARG[--session-id]' 'ARG[sess-1]' 'exit=0'; do
			self_test_says 'the recorded argv' "$argv" "$want" || rc=1
		done
		# A Stop event has no agent, so neither agent flag may ever appear.
		case "$argv" in
			*'ARG[--agent-id]'*|*'ARG[--agent-type]'*)
				printf '  MISS — a session row was given an agent flag\n    got: %s\n' \
					"${argv//$'\n'/ | }" >&2
				rc=1 ;;
		esac
		# An id the payload did not carry is an OMITTED FLAG, not an empty one.
		argv="$(self_test_fire "$(self_test_payload \
			"$EVENT" "$repo" '' "$tilde")")"
		case "$argv" in
			*'ARG[--session-id]'*)
				printf '  MISS — an absent session id was passed as an empty flag\n    got: %s\n' \
					"${argv//$'\n'/ | }" >&2
				rc=1 ;;
		esac
		self_test_says 'a payload with no ids still records' "$argv" 'exit=0' || rc=1
		# The grain is the same discipline, one source further out: it comes
		# from the ENVIRONMENT rather than the payload, because no hook event
		# carries a grain. The argv above was fired with GDK_LEDGER_GRAIN
		# unset, so it is the negative.
		case "$argv" in
			*'ARG[--grain]'*)
				printf '  MISS — an unset grain was passed as a flag\n    got: %s\n' \
					"${argv//$'\n'/ | }" >&2
				rc=1 ;;
		esac
		# And the positive. Every real grain id holds a `/`, so this is also the
		# value most likely to be lost by a vehicle that re-splits or re-quotes.
		argv="$(self_test_fire "$(self_test_payload "$EVENT" "$repo" 'sess-1' "$tilde")" \
			'0.1/alpha/s0')"
		for want in 'ARG[--grain]' 'ARG[0.1/alpha/s0]' 'exit=0'; do
			self_test_says 'the grain travels' "$argv" "$want" || rc=1
		done

		# The TREE, from the environment. `other` is a git tree with no Makefile
		# and `repo` has one, so which tree was derived is visible in the note.
		other="$tmp/other"
		mkdir -p "$other"
		git -C "$other" init -q
		argv="$(self_test_fire "$(self_test_payload \
			"$EVENT" "$other" 'sess-1' "$tilde")")"
		self_test_says 'a session rooted in another tree derives THAT tree' \
			"$argv" 'has no Makefile' || rc=1
		argv="$(self_test_fire "$(self_test_payload \
			"$EVENT" "$other" 'sess-1' "$tilde")" '' "$repo")"
		for want in 'ARG[ledger]' 'ARG[record]' "ARG[${HOME}/t.jsonl]" 'exit=0'; do
			self_test_says 'GDK_LEDGER_ROOT files the row from another scope' \
				"$argv" "$want" || rc=1
		done
		# A root naming no tree is a NOTE and exit 0, never a fall back to a cwd.
		argv="$(self_test_fire "$(self_test_payload \
			"$EVENT" "$repo" 'sess-1' "$tilde")" '' "$tmp/no-such-tree")"
		for want in 'GDK_LEDGER_ROOT' 'not inside a git repository' 'exit=0'; do
			self_test_says 'a root naming no tree is a note' "$argv" "$want" || rc=1
		done
		case "$argv" in
			*'ARG[ledger]'*)
				printf '  MISS — an unresolvable GDK_LEDGER_ROOT fell back to the cwd\n    got: %s\n' \
					"${argv//$'\n'/ | }" >&2
				rc=1 ;;
		esac

		# A non-bash vehicle under LC_ALL=C: a bash-quoted value would be a lost row
		# with nothing red anywhere.
		if command -v dash >/dev/null 2>&1; then
			# shellcheck disable=SC2016  # `$(ARGS)` is MAKE's expansion
			printf 'SHELL := %s\npm:\n\t@printf "ARG[%%s]\\n" $(ARGS)\n' \
				"$(command -v dash)" >"$repo/Makefile"
			awkward="$tmp/café dir/t.jsonl"
			# The grain travels HERE too. A REACHABILITY proof, not a
			# quoting one, and the difference is worth stating: the id
			# grammar forbids spaces, so the grain cannot exercise the
			# word-splitting this case's PATH assertion exists to catch.
			# What it does prove is that the value arrives intact under
			# the honest vehicle — dash, LC_ALL=C — rather than only
			# under the bash the other cases run.
			argv="$(LC_ALL=C self_test_fire "$(self_test_payload \
				"$EVENT" "$repo" 'sess-1' "$awkward")" '0.1/alpha/s0')"
			for want in "ARG[$awkward]" 'ARG[--grain]' \
					'ARG[0.1/alpha/s0]'; do
				self_test_says 'a non-bash vehicle, a path bash would escape' \
					"$argv" "$want" || rc=1
			done
		else
			echo "  SKIP — dash is not on PATH; the non-bash vehicle case did not run" >&2
		fi

		# The silent vehicle: a `pm/` directory and no phony `pm` target is make's
		# up-to-date case — exit 0, not a word, no row.
		mkdir -p "$repo/pm"
		printf 'all:\n\t@true\n' >"$repo/Makefile"
		self_test_case 'a vehicle that exits 0 without reaching the verb' \
			"$(self_test_payload "$EVENT" "$repo" 'sess-1' "$tilde")" \
			'without a word' || rc=1
		rmdir "$repo/pm"
	else
		echo "  SKIP — make is not on PATH; the vehicle cases did not run" >&2
	fi
	rm -rf "$tmp"

	if [ "$rc" -eq 0 ]; then
		echo "[$HOOK_NAME] SELF-TEST OK — every case exits 0, and only the wired case records"
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
	note "python3 is not on PATH, so the event cannot be parsed — no ledger row"
	exit 0
}

INPUT="$(cat)"

FIELDS=()
while IFS= read -r -d '' value; do
	FIELDS+=("$value")
done < <(printf '%s' "$INPUT" | read_event \
	hook_event_name cwd session_id "$TRANSCRIPT_KEY")

if [ "${#FIELDS[@]}" -ne 4 ]; then
	note "the event payload is not JSON this hook can read — no ledger row"
	exit 0
fi
EVENT_NAME="${FIELDS[0]}"
SESSION_CWD="${FIELDS[1]}"
SESSION_ID="${FIELDS[2]}"
TRANSCRIPT="$(expand_tilde "${FIELDS[3]}")"

# No transcript path: no row, and never an invented one.
if [ -z "$TRANSCRIPT" ]; then
	note "the ${EVENT_NAME:-$EVENT} payload carries no $TRANSCRIPT_KEY — no ledger row"
	exit 0
fi

[ -n "$SESSION_CWD" ] || SESSION_CWD="$PWD"
# The tree: named in the environment, else derived from the cwd — which a
# session rooted above the repo cannot supply, and no gate here sees that.
LEDGER_ROOT="$SESSION_CWD"
ROOT_FROM="the $EVENT payload's cwd"
if [ -n "${GDK_LEDGER_ROOT:-}" ]; then
	LEDGER_ROOT="$(expand_tilde "$GDK_LEDGER_ROOT")"
	ROOT_FROM="GDK_LEDGER_ROOT"
fi
REPO_ROOT="$(git -C "$LEDGER_ROOT" rev-parse --show-toplevel 2>/dev/null || true)"
if [ -z "$REPO_ROOT" ]; then
	note "$LEDGER_ROOT ($ROOT_FROM) is not inside a git repository — no ledger row"
	exit 0
fi

cd "$REPO_ROOT"

# No Makefile, no vehicle; fail open, out loud.
if [ ! -f Makefile ]; then
	note "$REPO_ROOT has no Makefile, so ${MAKE_PM[*]} cannot run — no ledger row"
	exit 0
fi

# The argv, in the verb's order. An id the payload did not carry is an
# omitted flag, never an empty one.
ARGS='ledger record'
env_arg --from-transcript GDK_LEDGER_TRANSCRIPT "$TRANSCRIPT"
ARGS="$ARGS --event $EVENT"
# The grain, when the dispatch carried one. Through `env_arg` like every other
# value: a grain id holds `/`, and the vehicle's shell may be dash under
# LC_ALL=C. Absent is an OMITTED FLAG — never `--grain ""`, which the verb would
# have to refuse, turning "nobody said" into a lost row.
if [ -n "${GDK_LEDGER_GRAIN:-}" ]; then
	env_arg --grain GDK_LEDGER_GRAIN "$GDK_LEDGER_GRAIN"
fi
if [ -n "$SESSION_ID" ]; then
	env_arg --session-id GDK_LEDGER_SESSION_ID "$SESSION_ID"
fi

# The hook exits 0 whatever the verb returns, and passes its output through
# verbatim. A vehicle that exits 0 without a word never reached the verb (the
# verb always speaks), so silence is named rather than counted as success.
verb_rc=0
verb_out=""
verb_out="$("${MAKE_PM[@]}" ARGS="$ARGS" 2>&1)" || verb_rc=$?
[ -z "$verb_out" ] || printf '%s\n' "$verb_out" >&2
if [ "$verb_rc" -ne 0 ]; then
	note "${MAKE_PM[*]} exited $verb_rc — see its output above"
elif [ -z "$verb_out" ]; then
	note "${MAKE_PM[*]} exited 0 without a word — the vehicle never reached the verb (is the \`pm\` target present, and .PHONY?) — no ledger row"
fi
exit 0
