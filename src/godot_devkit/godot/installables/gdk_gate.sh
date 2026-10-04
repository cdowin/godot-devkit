#!/usr/bin/env bash
# gdk_gate.sh — the gate-framework library every gate sources: quiet capture,
# one verdict line naming a full log, and a bounded-run contract.
#
#   source "$(dirname "${BASH_SOURCE[0]}")/gdk_gate.sh"
#   log="$(gdk_gate_log parse)"            # this gate's transcript slot
#   gdk_gate_capture "$log" -- make thing  # run it, quiet unless VERBOSE=1
#   gdk_gate_verdict PARSE "PASS (12 files)" "$log"
#
# `bash gdk_gate.sh --self-test` runs the contract corpus; `--help` lists the rest.
#
# --- project config (yours to edit after install — the file is your repo's) --
# Defaults; set them in the environment or edit them here.
#   GDK_GATE_REPORT_DIR     where transcripts land (gitignore it); one slot per gate.
#   GDK_LOG_CAP_BYTES       hard cap on a captured stream.
#   GDK_TIMEOUT_KILL_AFTER  grace between a bound's SIGTERM and its SIGKILL.
#   VERBOSE=1               stream every capture to the console too.
# -----------------------------------------------------------------------------

# Double-source guard: `return` when sourced, `exit` on the executed path.
if [ -n "${_GDK_GATE_SOURCED:-}" ]; then
	# shellcheck disable=SC2317  # the `exit` is the EXECUTED path (--self-test)
	return 0 2>/dev/null || exit 0
fi
_GDK_GATE_SOURCED=1

GDK_GATE_REPORT_DIR="${GDK_GATE_REPORT_DIR:-.gate-reports}"
GDK_LOG_CAP_BYTES="${GDK_LOG_CAP_BYTES:-52428800}"
GDK_TIMEOUT_KILL_AFTER="${GDK_TIMEOUT_KILL_AFTER:-5s}"

# The tag on every line this library prints on its own behalf.
GDK_LIB_TAG="gdk-gate"

# --- exit-hook dispatcher ----------------------------------------------------
# Bash has ONE `trap … EXIT` slot, so a wrapper never writes a bare trap: it
# registers with `gdk_on_exit`. Hooks run in order; none masks the exit status.
_GDK_EXIT_HOOKS=()

# shellcheck disable=SC2329  # invoked indirectly via `trap … EXIT`
_gdk_run_exit_hooks() {
	local status=$?
	local hook
	for hook in ${_GDK_EXIT_HOOKS[@]+"${_GDK_EXIT_HOOKS[@]}"}; do
		eval "$hook" || true
	done
	return "$status"
}

# gdk_on_exit <command> — run <command> when this shell exits.
gdk_on_exit() {
	_GDK_EXIT_HOOKS+=("${1:?usage: gdk_on_exit <command>}")
	trap _gdk_run_exit_hooks EXIT   # idempotent re-arm
}

# --- bounded-run / hang-detection contract ----------------------------------
# timeout(1) exits 124 on its SIGTERM deadline and 137 when --kill-after escalates.
GDK_EXIT_SIGTERM_TIMEOUT=124
GDK_EXIT_SIGKILL_TIMEOUT=137

# GNU `timeout`, or Homebrew's `gtimeout`; empty when neither is on PATH.
if command -v timeout >/dev/null 2>&1; then
	GDK_TIMEOUT="timeout"
elif command -v gtimeout >/dev/null 2>&1; then
	GDK_TIMEOUT="gtimeout"
else
	GDK_TIMEOUT=""
fi

# gdk_timeout_is_hang <exit_code> — true if the code is a timeout kill.
gdk_timeout_is_hang() {
	local code="${1:?usage: gdk_timeout_is_hang <exit_code>}"
	[ "$code" -eq "$GDK_EXIT_SIGTERM_TIMEOUT" ] || [ "$code" -eq "$GDK_EXIT_SIGKILL_TIMEOUT" ]
}

# gdk_run_bounded <seconds> -- <cmd...> — run under the timeout contract; 2 with no binary.
gdk_run_bounded() {
	local secs="${1:?usage: gdk_run_bounded <seconds> -- <cmd...>}"; shift
	[ "${1:-}" = "--" ] && shift
	if [ -z "$GDK_TIMEOUT" ]; then
		echo "$GDK_LIB_TAG: no timeout/gtimeout on PATH — install coreutils" >&2
		return 2
	fi
	"$GDK_TIMEOUT" --kill-after="$GDK_TIMEOUT_KILL_AFTER" "${secs}s" "$@"
}

# --- gate output ---------------------------------------------------------------
# The console gets one summary line; the stream goes to a per-gate slot that
# each run clears, so the report dir is bounded by construction.

# gdk_gate_log <gate> — echo this run's transcript path, cleared.
gdk_gate_log() {
	local gate="${1:?usage: gdk_gate_log <gate>}"
	mkdir -p "$GDK_GATE_REPORT_DIR"
	local path="$GDK_GATE_REPORT_DIR/$gate.log"
	: > "$path"
	printf '%s\n' "$path"
}

# <logfile> under the byte cap, stream it under VERBOSE. Publishes the command's
# own code in GDK_GATE_EXIT (last-write-wins).
# errexit is suspended around the pipeline: under `set -eo pipefail` the shell
# would die on this line, and `|| true` would reset PIPESTATUS.
gdk_gate_capture() {
	local log="${1:?usage: gdk_gate_capture <log> -- <cmd...>}"; shift
	[ "${1:-}" = "--" ] && shift
	local errexit_was_set=0
	case "$-" in *e*) errexit_was_set=1; set +e ;; esac
	if [ "${VERBOSE:-0}" != "0" ]; then
		# `tee` FIRST: it writes each chunk as it arrives, where `head -c` holds
		# 4 KB in stdio. A CI log stamps each line when it ARRIVES, so behind
		# `head` the check gate read as taking the next tier's 82 seconds.
		{ "$@" 2>&1 | tee /dev/fd/3 | head -c "$GDK_LOG_CAP_BYTES" >> "$log"; } 3>&1
	else
		"$@" 2>&1 | head -c "$GDK_LOG_CAP_BYTES" >> "$log"
	fi
	# shellcheck disable=SC2034  # read by the sourcing wrapper, not here
	GDK_GATE_EXIT="${PIPESTATUS[0]}"
	[ "$errexit_was_set" -eq 0 ] || set -e
	return 0
}

# gdk_gate_publish <logfile> <transcript> — the capture-then-parse shape; same cap, same VERBOSE.
gdk_gate_publish() {
	local log="${1:?usage: gdk_gate_publish <log> <transcript>}"
	printf '%s\n' "${2-}" | head -c "$GDK_LOG_CAP_BYTES" > "$log"
	[ "${VERBOSE:-0}" = "0" ] || printf '%s\n' "${2-}"
}

# gdk_gate_verdict <TAG> <message> <logfile> — the ONE result-line shape:
#   [TAG] <message> — full log: <path>
# It returns 0, so a wrapper under `set -e` never dies of the print.
gdk_gate_verdict() {
	printf '[%s] %s — full log: %s\n' \
		"${1:?usage: gdk_gate_verdict <TAG> <message> <log>}" "${2-}" "${3-}"
	return 0
}


# --- --self-test — the contract corpus ---------------------------------------
# Runs entirely inside a scratch dir it makes and removes.

_GDK_ST_FAILURES=0
_GDK_ST_CASES=0

# _gdk_st_eq <what> <expected> <actual>
_gdk_st_eq() {
	_GDK_ST_CASES=$((_GDK_ST_CASES + 1))
	if [ "$2" != "$3" ]; then
		printf '  MISS — %s\n    expected: %s\n    actual:   %s\n' "$1" "$2" "$3" >&2
		_GDK_ST_FAILURES=$((_GDK_ST_FAILURES + 1))
	fi
}

# _gdk_st_true <what> <status>
_gdk_st_true() {
	_GDK_ST_CASES=$((_GDK_ST_CASES + 1))
	if [ "$2" != "0" ]; then
		printf '  MISS — %s (status %s)\n' "$1" "$2" >&2
		_GDK_ST_FAILURES=$((_GDK_ST_FAILURES + 1))
	fi
}

# _gdk_st_has <what> <haystack> <needle>
_gdk_st_has() {
	_GDK_ST_CASES=$((_GDK_ST_CASES + 1))
	case "$2" in
		*"$3"*) return 0 ;;
	esac
	printf '  MISS — %s\n    wanted: %s\n    in:     %s\n' "$1" "$3" "$2" >&2
	_GDK_ST_FAILURES=$((_GDK_ST_FAILURES + 1))
}

# _gdk_st_lacks <what> <haystack> <needle>
_gdk_st_lacks() {
	_GDK_ST_CASES=$((_GDK_ST_CASES + 1))
	case "$2" in
		*"$3"*)
			printf '  MISS — %s\n    forbidden: %s\n    in:        %s\n' \
				"$1" "$3" "$2" >&2
			_GDK_ST_FAILURES=$((_GDK_ST_FAILURES + 1)) ;;
	esac
}

_gdk_self_test() {
	local scratch verdict log body status hung lib
	# Resolved before the cd: the sub-shell cases re-source from elsewhere.
	lib="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/$(basename "${BASH_SOURCE[0]}")"
	scratch="$(mktemp -d "${TMPDIR:-/tmp}/gdk-gate-selftest.XXXXXX")" || return 1
	cd "$scratch" || return 1
	# Both settings are pinned by their own cases; an inherited VERBOSE=1 leaked into the verdict line.
	VERBOSE=0
	# Re-read: a TMPDIR with a trailing slash yields `//` and every prefix compare misses.
	scratch="$PWD"

	# --- gdk_gate_log: names the slot, creates it, clears it -----------------
	log="$(gdk_gate_log parse)"
	_gdk_st_eq 'gate_log names <dir>/<gate>.log' "$GDK_GATE_REPORT_DIR/parse.log" "$log"
	status=0; [ -f "$log" ] || status=1
	_gdk_st_true 'gate_log creates the file' "$status"
	printf 'residue from a previous run\n' > "$log"
	log="$(gdk_gate_log parse)"
	_gdk_st_eq 'gate_log clears the slot it hands back' '' "$(cat "$log")"

	# --- gdk_gate_capture: quiet by default, persists, appends ---------------
	body="$(VERBOSE=0 gdk_gate_capture "$log" -- printf 'first line\n')"
	_gdk_st_eq 'capture prints nothing when VERBOSE=0' '' "$body"
	_gdk_st_eq 'capture persists the stream' 'first line' "$(cat "$log")"
	body="$(VERBOSE=1 gdk_gate_capture "$log" -- printf 'second line\n')"
	_gdk_st_eq 'capture streams when VERBOSE=1' 'second line' "$body"
	_gdk_st_eq 'capture APPENDS (a two-stage gate is one transcript)' \
		'first line
second line' "$(cat "$log")"

	# --- gdk_gate_capture: GDK_GATE_EXIT is the COMMAND's code, not head's ---
	GDK_GATE_EXIT=''
	gdk_gate_capture "$log" -- sh -c 'exit 7' >/dev/null 2>&1
	_gdk_st_eq 'capture reports the command exit code, not the pipeline tail' \
		'7' "$GDK_GATE_EXIT"

	# --- capture survives a wrapper under `set -euo pipefail` ----------------
	body="$(cd "$scratch" && bash -c '
		set -euo pipefail
		# shellcheck source=/dev/null
		source "$1"
		log="$(gdk_gate_log strict)"
		gdk_gate_capture "$log" -- sh -c "exit 7"
		printf "exit=%s reached-the-verdict\n" "$GDK_GATE_EXIT"
	' _ "$lib" 2>&1)"
	_gdk_st_eq 'capture under set -euo pipefail reports and returns' \
		'exit=7 reached-the-verdict' "$body"

	# --- the byte cap is real ------------------------------------------------
	# `env … bash -c`, not a subshell assignment: that trips SC2031 at consumer sites.
	log="$(gdk_gate_log capped)"
	# shellcheck disable=SC2016  # $1/$2 are the CHILD shell's positionals
	env GDK_LOG_CAP_BYTES=8 bash -c '
		# shellcheck source=/dev/null
		source "$1"
		gdk_gate_capture "$2" -- printf "0123456789abcdef"
	' _ "$lib" "$log"
	_gdk_st_eq 'the log cap truncates a runaway stream' '8' \
		"$(wc -c < "$log" | tr -d ' ')"

	# --- gdk_gate_publish: capture-then-parse takes the same slot ------------
	log="$(gdk_gate_log unit)"
	body="$(VERBOSE=0 gdk_gate_publish "$log" 'held in a variable')"
	_gdk_st_eq 'publish prints nothing when VERBOSE=0' '' "$body"
	_gdk_st_eq 'publish persists the transcript' 'held in a variable' "$(cat "$log")"
	body="$(VERBOSE=1 gdk_gate_publish "$log" 'held in a variable')"
	_gdk_st_eq 'publish streams when VERBOSE=1' 'held in a variable' "$body"

	# --- gdk_gate_verdict: ONE line, and it names the full log ---------------
	verdict="$(gdk_gate_verdict PARSE 'PASS (12 files)' '.gate-reports/parse.log')"
	_gdk_st_eq 'the verdict line shape' \
		'[PARSE] PASS (12 files) — full log: .gate-reports/parse.log' "$verdict"
	_gdk_st_eq 'the verdict is exactly one line' '1' \
		"$(gdk_gate_verdict PARSE 'PASS' 'x.log' | wc -l | tr -d ' ')"

	# --- gdk_run_bounded: passes through, and 124 means HUNG -----------------
	if [ -n "$GDK_TIMEOUT" ]; then
		status=0; gdk_run_bounded 5 -- sh -c 'exit 3' || status=$?
		_gdk_st_eq 'run_bounded returns the command exit code' '3' "$status"
		if [ "${GDK_ST_SKIP_TIMING:-0}" != "1" ]; then
			status=0; gdk_run_bounded 1 -- sleep 5 || status=$?
			hung=0
			[ "$status" = "$GDK_EXIT_SIGTERM_TIMEOUT" ] \
				|| [ "$status" = "$GDK_EXIT_SIGKILL_TIMEOUT" ] || hung=1
			_gdk_st_true 'run_bounded reports a hang as 124/137' "$hung"
		fi
	else
		status=0; gdk_run_bounded 5 -- true 2>/dev/null || status=$?
		_gdk_st_eq 'run_bounded fails loud with no timeout binary' '2' "$status"
	fi

	# --- gdk_timeout_is_hang: only the two timeout codes are a hang ----------
	status=0; gdk_timeout_is_hang "$GDK_EXIT_SIGTERM_TIMEOUT" || status=1
	_gdk_st_true 'timeout_is_hang recognises 124' "$status"
	status=0; gdk_timeout_is_hang "$GDK_EXIT_SIGKILL_TIMEOUT" || status=1
	_gdk_st_true 'timeout_is_hang recognises 137' "$status"
	status=0; gdk_timeout_is_hang 1 && status=1
	_gdk_st_true 'a failing gate (exit 1) is NOT a hang' "$status"
	status=0; gdk_timeout_is_hang 0 && status=1
	_gdk_st_true 'a passing gate (exit 0) is NOT a hang' "$status"

	# --- gdk_on_exit: registration order, and no hook masks the status -------
	# Order is contract: a later hook may read what an earlier one wrote.
	# shellcheck disable=SC2016  # $1 is the CHILD shell's positional
	body="$(bash -c '
		# shellcheck source=/dev/null
		source "$1"
		gdk_on_exit "printf one"
		gdk_on_exit "printf two"
		exit 0
	' _ "$lib" 2>&1)"
	_gdk_st_eq 'exit hooks run in registration order' 'onetwo' "$body"

	# shellcheck disable=SC2016  # $1 is the CHILD shell's positional
	status=0
	bash -c '
		# shellcheck source=/dev/null
		source "$1"
		gdk_on_exit "false"
		gdk_on_exit "printf ran-anyway"
		exit 5
	' _ "$lib" >/dev/null 2>&1 || status=$?
	_gdk_st_eq 'a failing hook never masks the script exit status' '5' "$status"


	cd / || return 1
	rm -rf "$scratch"
	return 0
}

_gdk_usage() {
	cat <<'USAGE_EOF'
usage: source gdk_gate.sh            the normal use — a shell library
       bash gdk_gate.sh --self-test  run the contract corpus
       bash gdk_gate.sh --help       this message

Public functions: gdk_on_exit, gdk_run_bounded, gdk_timeout_is_hang,
gdk_gate_log, gdk_gate_capture, gdk_gate_publish, gdk_gate_verdict.
USAGE_EOF
}

# Executed rather than sourced: only --self-test and --help, and exactly one of them.
if [ "${BASH_SOURCE[0]}" = "$0" ]; then
	if [ "$#" -ne 1 ]; then
		echo "$GDK_LIB_TAG: exactly one argument — got $#. See --help." >&2
		exit 2
	fi
	case "$1" in
		--self-test)
			_gdk_self_test || _GDK_ST_FAILURES=$((_GDK_ST_FAILURES + 1))
			if [ "$_GDK_ST_FAILURES" -eq 0 ]; then
				echo "[$GDK_LIB_TAG] SELF-TEST OK — $_GDK_ST_CASES case(s)"
				exit 0
			fi
			echo "[$GDK_LIB_TAG] SELF-TEST FAIL — $_GDK_ST_FAILURES of $_GDK_ST_CASES case(s), see above" >&2
			exit 1
			;;
		--help|-h) _gdk_usage; exit 0 ;;
		*)
			echo "$GDK_LIB_TAG: this is a library — source it. See --help." >&2
			exit 2
			;;
	esac
fi
