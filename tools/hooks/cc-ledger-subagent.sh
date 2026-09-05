#!/usr/bin/env bash
# cc-ledger-subagent.sh — Claude Code SubagentStop hook: one ledger row per
# dispatch, written by the tooling instead of tallied by hand.
#
# When a subagent finishes, Claude Code hands this hook the event JSON on
# stdin. The hook copies five fields out of it — the subagent's own transcript
# path, the session id, the agent id, the agent type, and the event name it was
# fired for — and hands them to `pm ledger record`, which is the ONE thing that
# writes a row. Nothing here reads a transcript, sums a number, names a grain
# or decides which milestone owns the row: this file is a courier.
#
# THE DIVISION OF LABOUR, said out loud because it is the whole design (Chris,
# 2026-09-03: the ledger *"just timestamps transitions and stamps whatever hook
# data. Judgement/inference is left to the caller."*):
#
#   the hook   copies fields, expands a leading `~`, finds the repo, runs the
#              verb, exits 0.
#   the verb   parses the transcript, sums `message.usage`, counts tool_use
#              blocks, snapshots the tree (D3), refuses what it cannot read.
#
# So a field this hook does not understand is a field it does not touch.
# `last_assistant_message` is on the payload and is never read — it is the
# agent's narration, the one source this SDLC refuses to trust (D4).
# `stop_hook_active` is on the payload and is never read either: it marks a
# re-entrant stop, and "one row per stop" is the verb's concern, not a
# de-duplication this hook could only get wrong. `background_tasks` and
# `session_crons` are likewise ignored.
#
# IT NEVER BLOCKS A STOP. Every path out of this file is exit 0 — including
# every failure, each of which says so on stderr first. Fail OPEN, out loud: a
# row that could not be written is a gap in the measurement, never a reason to
# wedge an agent that has finished its work. Claude Code shows a non-blocking
# hook's stderr in the hook log, which is where a refusal from the verb belongs
# and where it is passed through verbatim.
#
# WIRE IT `"async": true`. A dispatch transcript is megabytes and the parse is
# the verb's, not the turn's. `install-hooks` prints the settings.json snippet.
#
# Protocol: Claude Code feeds the SubagentStop event as JSON on stdin
# (session_id, transcript_path, cwd, permission_mode, hook_event_name,
# stop_hook_active, agent_id, agent_type, agent_transcript_path,
# last_assistant_message, background_tasks, session_crons). Exit 0 always.
set -eu

# --- project config (yours to edit after install — the file is your repo's) --
# The vehicle the ledger verb is invoked through, run with the repo root as the
# working directory. The stock spelling is the standard consumer Makefile's
# passthrough target (`make pm ARGS="…"`, Makefile.devkit), so a repo that
# pins its devkit version in one place keeps pinning it in one place. Repoint
# it at anything that takes `ARGS=<pm argv>`.
#
# THE TARGET MUST BE PHONY. A PM tree IS a `pm/` directory at the repo root, so
# an un-`.PHONY:`'d `pm` target is a target make considers up to date — the
# vehicle exits 0, prints nothing, and no row is ever written. Makefile.devkit
# declares it; a hand-rolled Makefile has to.
#
# AND IT MUST PASS ITS ENVIRONMENT THROUGH. Every value copied off the payload
# travels to the verb in the environment (`GDK_LEDGER_*`), never spelled into
# `ARGS=` — see "the argv" at the bottom of this file for why. make hands its
# environment to a recipe unchanged, so the stock spelling needs nothing said
# to it; a vehicle that scrubs the environment would drop the transcript path
# and every row with it.
MAKE_PM=(make -s pm)
# -----------------------------------------------------------------------------

# What this file IS: the event it is registered for, the payload key carrying
# the transcript that event describes, and the name its diagnostics carry. The
# event is a CONSTANT, not `hook_event_name` off the payload — which hook fired
# is a fact about the settings.json entry, and reading the kind out of the
# payload would let a mis-wired entry file a dispatch row for a session stop.
# `hook_event_name` is still read, and used only to say what arrived.
HOOK_NAME="cc-ledger-subagent"
EVENT="SubagentStop"
TRANSCRIPT_KEY="agent_transcript_path"

note() { printf '[%s] %s\n' "$HOOK_NAME" "$1" >&2; }

# An unexpected failure is still a fail-open — but never a SILENT one. A trap
# that only said `exit 0` would turn every future breakage into a ledger that
# is quietly missing rows, which is hard rule 4's read-side sin with a hook
# around it.
trap 'note "internal error — no ledger row was written"; exit 0' ERR

# expand_tilde <path> — `~` and `~/…` against $HOME, everything else verbatim.
#
# Claude Code may deliver a transcript path with a leading `~`. The shell does
# not expand a tilde that arrives inside a variable, and the verb resolves the
# path it is handed, so the expansion has to happen here. `~user` is left alone
# deliberately: resolving another account's home is a guess about a machine,
# and the verb's "is not a file" refusal is the honest outcome.
expand_tilde() {
	# shellcheck disable=SC2088  # the tilde is the INPUT being matched, not a
	# path this file is trying to have the shell expand.
	case "$1" in
		'~') printf '%s' "$HOME" ;;
		'~/'*) printf '%s%s' "$HOME" "${1#\~}" ;;
		*) printf '%s' "$1" ;;
	esac
}

# env_arg <flag> <name> <value> — append one flag to ARGS and carry its value
# to the vehicle in the ENVIRONMENT, as one call so neither can be written
# without the other.
#
# `ARGS=` is a make variable interpolated into a recipe, so anything spelled
# into it crosses two expanders — make's, then the recipe shell's — AND THAT
# SHELL IS NOT THIS ONE. make runs a recipe under `/bin/sh` unless the Makefile
# says otherwise, and a hand-rolled consumer Makefile may say dash. Values were
# quoted here with `printf %q`, which is BASH's quoting and locale-sensitive
# besides: in the `C` locale a non-ASCII path came back as `$'…'`, dash kept the
# `$` as text, the verb refused "is not a file" at exit 2 — and this hook exits
# 0 whatever happens, so the row was lost with nothing red anywhere and the
# milestone read as cheaper than it was
# (0.24.0/bugs/courier-path-quoting-needs-a-bash-shell).
#
# So no value is spelled into ARGS at all. It travels in the environment, which
# make hands to the recipe shell untouched, and ARGS carries a FIXED reference
# — the same bytes for every value, so nothing about a path can change how the
# vehicle parses the word. `$$` is make's escape for a literal `$`; the double
# quotes are POSIX, and no shell re-scans the result of a parameter expansion,
# so the value reaches the verb byte-exact whatever is in it: space, quote,
# `$`, newline. The one word still spelled in full is `--event`, which is the
# constant at the top of THIS file rather than anything off the payload.
env_arg() {
	export "$2=$3"
	ARGS="$ARGS $1 \"\$\$$2\""
}

# read_event — the payload's fields, NUL-terminated, in a fixed order.
#
# ONE python3 call, `json.load` on stdin, no grep. `cc-stop-gate.sh` reads a
# path and a boolean with a grep extractor and says why that is adequate
# THERE; `cc-commit-pathspec.sh` says why a hook reading a command must not.
# This hook reads paths and ids, which is the adequate case — and it uses the
# real parser anyway, because one parser is one refusal path: a payload
# python3 cannot load yields nothing and the caller says so, instead of a
# regex handing back a field it half-matched.
#
# Every requested key comes back, in order, empty when absent or non-string,
# each terminated by a NUL — so a value containing a newline (nothing here
# should, and the row must not depend on that) still reads as one field.
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

# --- --self-test — the payload corpus, PROVEN rather than claimed ------------
# `bash tools/hooks/cc-ledger-subagent.sh --self-test` replays the fail-open
# matrix and one recording case through this same file and checks what came
# out; exit 0 means every case landed where it should. Wire it into your static
# gate beside cc-godot-sandbox.sh's — a hook nobody can see fire is a hook
# whose silence has to be provable.
#
# The recording case runs the vehicle against a STUB `pm` target that echoes
# ARGS, so it proves the whole wiring — tilde expansion, flag order, quoting —
# without needing a PM tree, a transcript or the devkit on PATH.
self_test_payload() {
	python3 -c '
import json, sys
keys = ("hook_event_name", "cwd", "session_id", "agent_transcript_path",
        "agent_id", "agent_type")
event = {k: v for k, v in zip(keys, sys.argv[1:]) if v}
event["stop_hook_active"] = False
event["last_assistant_message"] = "narration the hook must never read"
sys.stdout.write(json.dumps(event))
' "$@"
}

# fire <payload> — everything the hook said (both streams), plus its exit code
# as a final `exit=<n>` line, so a case can assert on either.
self_test_fire() {
	local rc=0 out
	out="$(printf '%s' "$1" | bash "$0" 2>&1)" || rc=$?
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
	local rc=0 tmp repo argv want tilde
	# shellcheck disable=SC2088  # a LITERAL leading ~ is the payload under
	# test: the point is that the HOOK expands it, not the shell.
	tilde='~/t.jsonl'
	tmp="$(mktemp -d "${TMPDIR:-/tmp}/cc-ledger-selftest.XXXXXX")"
	repo="$tmp/repo"
	mkdir -p "$repo"
	git -C "$repo" init -q

	self_test_case 'a payload that is not JSON' \
		'not json {{{' 'not JSON this hook can read' || rc=1
	self_test_case 'a payload with no transcript path' \
		"$(self_test_payload "$EVENT" "$repo" 'sess-1' '' 'ag-1' 'developer')" \
		"carries no $TRANSCRIPT_KEY" || rc=1
	self_test_case 'a repo with no Makefile' \
		"$(self_test_payload "$EVENT" "$repo" 'sess-1' "$tilde" 'ag-1' 'developer')" \
		'has no Makefile' || rc=1

	# The vehicle, end to end, against a stub `pm` target. Unquoted `$(ARGS)`
	# in the recipe so the SHELL splits it — which is what makes this a test of
	# the quoting and not merely of the concatenation.
	if command -v make >/dev/null 2>&1; then
		# shellcheck disable=SC2016  # `$(ARGS)` is MAKE's expansion, written
		# into the stub Makefile literally.
		printf 'pm:\n\t@printf "ARG[%%s]\\n" $(ARGS)\n' >"$repo/Makefile"
		argv="$(self_test_fire "$(self_test_payload \
			"$EVENT" "$repo" 'sess-1' "$tilde" 'ag-1' 'developer')")"
		for want in 'ARG[ledger]' 'ARG[record]' 'ARG[--from-transcript]' \
				"ARG[${HOME}/t.jsonl]" 'ARG[--event]' "ARG[${EVENT}]" \
				'ARG[--session-id]' 'ARG[sess-1]' 'ARG[--agent-id]' \
				'ARG[ag-1]' 'ARG[--agent-type]' 'ARG[developer]' 'exit=0'; do
			self_test_says 'the recorded argv' "$argv" "$want" || rc=1
		done
		# An id the payload did not carry is an OMITTED FLAG, not an empty one.
		argv="$(self_test_fire "$(self_test_payload \
			"$EVENT" "$repo" '' "$tilde" '' '')")"
		case "$argv" in
			*'ARG[--session-id]'*|*'ARG[--agent-id]'*|*'ARG[--agent-type]'*)
				printf '  MISS — an absent id was passed as an empty flag\n    got: %s\n' \
					"${argv//$'\n'/ | }" >&2
				rc=1 ;;
		esac
		self_test_says 'a payload with no ids still records' "$argv" 'exit=0' || rc=1

		# THE VEHICLE'S SHELL IS NOT THIS ONE. make runs a recipe under `/bin/sh`
		# unless the Makefile says otherwise, and a hand-rolled consumer Makefile
		# may say dash — so a value spelled into ARGS as a BASH literal is a value
		# the vehicle cannot decode, and the lost row is silent because this hook
		# exits 0 either way. The path carries a non-ASCII byte and a space, and
		# the locale is pinned to `C`: `printf %q` leaves a non-ASCII path bare
		# under a UTF-8 locale, so an inherited locale is a case that passes for
		# the wrong reason on the machine that happens to have one. Nothing opens
		# this transcript — the stub prints ARGS — so what is proven is the WORD
		# the vehicle handed on.
		if command -v dash >/dev/null 2>&1; then
			# shellcheck disable=SC2016  # `$(ARGS)` is MAKE's expansion, written
			# into the stub Makefile literally.
			printf 'SHELL := %s\npm:\n\t@printf "ARG[%%s]\\n" $(ARGS)\n' \
				"$(command -v dash)" >"$repo/Makefile"
			awkward="$tmp/café dir/t.jsonl"
			argv="$(LC_ALL=C self_test_fire "$(self_test_payload \
				"$EVENT" "$repo" 'sess-1' "$awkward" 'ag-1' 'developer')")"
			self_test_says 'a non-bash vehicle, a path bash would escape' \
				"$argv" "ARG[$awkward]" || rc=1
		else
			echo "  SKIP — dash is not on PATH; the non-bash vehicle case did not run" >&2
		fi

		# THE SILENT VEHICLE. A Makefile with no `pm` target, in a repo that
		# has a `pm/` DIRECTORY — which every PM tree does — is make's
		# up-to-date case: exit 0, not a word, no row. An un-`.PHONY:`'d `pm`
		# target is the same case with a recipe attached. This is the failure
		# mode the header warns about, and the case is here because a warning
		# in a comment has never caught anything.
		mkdir -p "$repo/pm"
		printf 'all:\n\t@true\n' >"$repo/Makefile"
		self_test_case 'a vehicle that exits 0 without reaching the verb' \
			"$(self_test_payload "$EVENT" "$repo" 'sess-1' "$tilde" 'ag-1' 'developer')" \
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
	# Captured through `||` so the ERR trap above — which exists to fail OPEN —
	# cannot turn a self-test FAILURE into exit 0. That false green is the exact
	# thing a corpus exists to prevent.
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
	hook_event_name cwd session_id "$TRANSCRIPT_KEY" agent_id agent_type)

if [ "${#FIELDS[@]}" -ne 6 ]; then
	note "the event payload is not JSON this hook can read — no ledger row"
	exit 0
fi
EVENT_NAME="${FIELDS[0]}"
SESSION_CWD="${FIELDS[1]}"
SESSION_ID="${FIELDS[2]}"
TRANSCRIPT="$(expand_tilde "${FIELDS[3]}")"
AGENT_ID="${FIELDS[4]}"
AGENT_TYPE="${FIELDS[5]}"

# No transcript path — an older Claude Code, or an event shape that does not
# carry one. No row, and NEVER an invented one: the verb's whole input is that
# path (D4).
if [ -z "$TRANSCRIPT" ]; then
	note "the ${EVENT_NAME:-$EVENT} payload carries no $TRANSCRIPT_KEY — no ledger row"
	exit 0
fi

[ -n "$SESSION_CWD" ] || SESSION_CWD="$PWD"
REPO_ROOT="$(git -C "$SESSION_CWD" rev-parse --show-toplevel 2>/dev/null || true)"
if [ -z "$REPO_ROOT" ]; then
	note "$SESSION_CWD is not inside a git repository — no ledger row"
	exit 0
fi

cd "$REPO_ROOT"

# No Makefile → no vehicle to reach the verb through. Fail OPEN, out loud, for
# the same reason cc-stop-gate.sh does: a hook installed ahead of the dev loop
# must not make noise a consumer cannot act on, and must not pretend it wrote
# a row.
if [ ! -f Makefile ]; then
	note "$REPO_ROOT has no Makefile, so ${MAKE_PM[*]} cannot run — no ledger row"
	exit 0
fi

# The argv, in the order the verb documents it. An id the payload did not carry
# is an OMITTED FLAG, never an empty string: the verb reads the ids out of the
# transcript when the caller is silent, and a `--session-id ''` would tell it
# the caller was not.
#
# EVERY VALUE TRAVELS IN THE ENVIRONMENT, not inside ARGS — `env_arg` above
# says why, and is the only place the reference is spelled. The one word still
# written out in full is `--event`, a constant at the top of THIS file rather
# than anything off the payload.
ARGS='ledger record'
env_arg --from-transcript GDK_LEDGER_TRANSCRIPT "$TRANSCRIPT"
ARGS="$ARGS --event $EVENT"
if [ -n "$SESSION_ID" ]; then
	env_arg --session-id GDK_LEDGER_SESSION_ID "$SESSION_ID"
fi
if [ -n "$AGENT_ID" ]; then
	env_arg --agent-id GDK_LEDGER_AGENT_ID "$AGENT_ID"
fi
if [ -n "$AGENT_TYPE" ]; then
	env_arg --agent-type GDK_LEDGER_AGENT_TYPE "$AGENT_TYPE"
fi

# Whatever the verb returns, this hook exits 0. Its stdout joins its stderr so
# the hook log carries ONE stream: a refusal ("2 milestones are building …") is
# the message a consumer has to see, and it is passed through verbatim rather
# than summarised by a courier that did not decide it.
#
# AND A VEHICLE THAT EXITS 0 SAYING NOTHING NEVER REACHED THE VERB. The `pm`
# target is un-`.PHONY:`'d — a PM tree IS a `pm/` directory, so make finds a
# file by that name and calls the target up to date — or it is absent from a
# Makefile that exists. Both exit 0, print nothing, and write no row. The
# header comment above warns about the first; a comment is not a gate, and a
# courier that cannot tell "wrote a row" from "did nothing" is hard rule 4's
# read-side sin wearing a hook: the milestone reads as cheap forever after and
# nothing downstream can tell it from one that was. The verb ALWAYS speaks —
# `[pm] ledger … row appended` on success, `[pm] ERROR — …` on a refusal — so
# silence is the one answer that is neither, and it is named rather than
# counted as a success. The output is captured to ask that question and then
# passed through verbatim; nothing here parses it.
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
