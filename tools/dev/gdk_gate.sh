#!/usr/bin/env bash
# gdk_gate.sh — the gate-framework library every gate sources: quiet capture,
# one verdict line naming a full log, a bounded-run contract, and a cost row.
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
#   GDK_LEDGER_CMD          command STRING the cost row is filed through
#                           (`pm ledger record …` appended); empty spawns nothing.
#                           The Makefile exports it: `export GDK_LEDGER_CMD ?= $(DEVKIT)`.
#   GDK_LEDGER_TIMEOUT      seconds the recorder is allowed.
#   GDK_GATE_CENSUS         how many things this run walked; unset is an absent
#                           column, never 0, and never parsed from the verdict.
#   GDK_GATE_VERDICT        PASS|FAIL|HANG|SKIP for a runner that never captured;
#                           unset, it is derived from the captures on this log slot.
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
GDK_LEDGER_CMD="${GDK_LEDGER_CMD:-}"
GDK_LEDGER_TIMEOUT="${GDK_LEDGER_TIMEOUT:-30}"
GDK_GATE_CENSUS="${GDK_GATE_CENSUS:-}"
GDK_GATE_VERDICT="${GDK_GATE_VERDICT:-}"

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

# --- gate output and the cost row --------------------------------------------
# The console gets one summary line; the stream goes to a per-gate slot that
# each run clears, so the report dir is bounded by construction.
# A slot's cost row is filed once, by the FIRST verdict naming it; the start
# time lives in a sidecar file because the log path is minted inside a `$( )`.
# Every path through the ledger code returns 0: a row that cannot be written
# is one note on stderr, never a gate failure.

# _gdk_ledger_note <what> — one line, on stderr, never on the verdict's stream.
_gdk_ledger_note() {
	printf '%s: %s — no cost row for this gate\n' "$GDK_LIB_TAG" "$1" >&2
}

# _gdk_ledger_sidecar <logfile> — this slot's start-time file; expansion, not spawns.
#
# **KEYED BY PID as well as by log path.** The log path alone is shared by every
# concurrent run of the same gate in one checkout, so two `make check` runs used
# one sidecar: the second `open` overwrote the first's start time and the first
# `close` unlinked it, and one of the two runs filed no cost row at all — a gate
# that ran, passed, and left no measurement. `$$` is the sourcing shell's, and
# `open` and `close` are both called from it (`gdk_gate_log`,
# `gdk_gate_verdict`), so the pair always agree.
#
# What this does NOT fix, and it is the same class one level up: the report
# directory is cleared per run, so a run that clears it while another holds a
# sidecar there still costs that one its row. Makefile.devkit's gate macros
# capture into `<slot>.<pid>` and rename it onto the slot; a runner capturing
# into the path `gdk_gate_log` returns still shares it with a concurrent run.
_gdk_ledger_sidecar() {
	case "$1" in
		*/*) printf '%s/.%s.%s.gdkms' "${1%/*}" "${1##*/}" "$$" ;;
		*)   printf '.%s.%s.gdkms' "$1" "$$" ;;
	esac
}

# The clock, resolved once: BSD date has no %N, python3 is the fallback, and
# no millisecond clock means no row rather than a wrong one.
_GDK_CLOCK=''

_gdk_now_ms() {
	local probe
	if [ -z "$_GDK_CLOCK" ]; then
		probe="$(date +%s%N 2>/dev/null)" || probe=''
		case "$probe" in
			''|*[!0-9]*) probe='' ;;
		esac
		if [ -n "$probe" ] && [ "${#probe}" -ge 16 ]; then
			_GDK_CLOCK='date'
		elif command -v python3 >/dev/null 2>&1; then
			_GDK_CLOCK='python3'
		else
			_GDK_CLOCK='none'
		fi
	fi
	case "$_GDK_CLOCK" in
		date)    echo $(( $(date +%s%N) / 1000000 )) ;;
		python3) python3 -c 'import time; print(int(time.time() * 1000))' ;;
		*)       : ;;
	esac
}

# _gdk_ledger_open <gate> <logfile> — start the slot's clock; nothing without GDK_LEDGER_CMD.
_gdk_ledger_open() {
	[ -n "$GDK_LEDGER_CMD" ] || return 0
	local now side
	now="$(_gdk_now_ms)"
	if [ -z "$now" ]; then
		_gdk_ledger_note 'no millisecond clock here (GNU date or python3)'
		return 0
	fi
	side="$(_gdk_ledger_sidecar "$2")"
	# `2>/dev/null` first: an unwritable report dir must not become a gate failure.
	printf '%s\n%s\n' "$now" "$1" 2>/dev/null > "$side" || true
	return 0
}

# _gdk_ledger_fault <logfile> <exit code> — remember on the slot that a capture
# failed; the first non-zero wins, so a slot's verdict answers for every capture.
_gdk_ledger_fault() {
	[ -n "$GDK_LEDGER_CMD" ] || return 0
	case "${2-}" in ''|*[!0-9]*) return 0 ;; esac
	[ "$2" -ne 0 ] || return 0
	local side
	side="$(_gdk_ledger_sidecar "${1-}")"
	# No sidecar means no open slot, and a capture never mints one.
	[ -f "$side" ] || return 0
	printf '%s\n' "$2" 2>/dev/null >> "$side" || true
	return 0
}

# _gdk_ledger_verdict [slot exit code] — PASS|FAIL|HANG from an exit code, never
# from the message; GDK_GATE_VERDICT wins, then the slot's code, then GDK_GATE_EXIT.
_gdk_ledger_verdict() {
	case "$GDK_GATE_VERDICT" in
		PASS|FAIL|HANG|SKIP) printf '%s' "$GDK_GATE_VERDICT"; return 0 ;;
		'') ;;
		*) return 0 ;;
	esac
	local code="${1-}"
	[ -n "$code" ] || code="${GDK_GATE_EXIT:-}"
	case "$code" in
		''|*[!0-9]*) return 0 ;;
	esac
	if [ "$code" -eq 0 ]; then
		printf 'PASS'
	elif gdk_timeout_is_hang "$code"; then
		printf 'HANG'
	else
		printf 'FAIL'
	fi
}

# _gdk_ledger_run <argv...> — the recorder, bounded; no timeout binary, no row.
_gdk_ledger_run() {
	if [ -z "$GDK_TIMEOUT" ]; then
		return 1
	fi
	gdk_run_bounded "$GDK_LEDGER_TIMEOUT" -- "$@"
}

# The value is parsed INSIDE the bound: `eval` runs any `$( )` in GDK_LEDGER_CMD
# while the array is built, so the shim does it under `timeout` and `exec`s the
# recorder. 121 is the shim's own refusal, outside any code a recorder returns.
_GDK_LEDGER_PARSE_REFUSAL='GDK_LEDGER_CMD is not a command line this shell can parse'
# shellcheck disable=SC2016  # $1/$2/$@ are the SHIM's positionals, not ours
_GDK_LEDGER_SHIM='
eval "prefix=($1)" 2>/dev/null || { printf "%s\n" "$2" >&2; exit 121; }
shift 2
[ "${#prefix[@]}" -gt 0 ] || exit 0
exec "${prefix[@]}" "$@"
'

# _gdk_ledger_record <gate> <verdict> <duration_ms> [scratch] — scratch is a
# FILE, not a pipe, so a forking recorder cannot hold the gate open.
_gdk_ledger_record() {
	local said='' rc=0 scratch="${4-}"
	local -a argv
	argv=(pm ledger record --gate "$1" --verdict "$2" --duration-ms "$3")
	case "$GDK_GATE_CENSUS" in
		'') ;;
		*[!0-9]*)
			_gdk_ledger_note "GDK_GATE_CENSUS=\"$GDK_GATE_CENSUS\" is not a count, so the row omits it" ;;
		*) argv=("${argv[@]}" --census "$GDK_GATE_CENSUS") ;;
	esac
	# Both streams go to the file: stdout must never sit inside the `[TAG] …` line,
	# and the recorder's first line rides out on the note. The argv is built here
	# and parsed in the shim, so a gate name is ONE element whatever it contains.
	local -a cmd
	cmd=("${BASH:-bash}" -c "$_GDK_LEDGER_SHIM" _ \
		"$GDK_LEDGER_CMD" "$_GDK_LEDGER_PARSE_REFUSAL" "${argv[@]}")
	if [ -n "$scratch" ] && : 2>/dev/null > "$scratch"; then
		_gdk_ledger_run "${cmd[@]}" > "$scratch" 2>&1 || rc=$?
		# One line is all the note carries.
		IFS= read -r said < "$scratch" 2>/dev/null || said="${said-}"
		# Unlinked at once; a forked grandchild keeps writing to a nameless inode.
		rm -f "$scratch" 2>/dev/null || true
	else
		_gdk_ledger_run "${cmd[@]}" > /dev/null 2>&1 || rc=$?
	fi
	if [ "$rc" -eq 121 ] && [ "$said" = "$_GDK_LEDGER_PARSE_REFUSAL" ]; then
		# The shim refused the value; no recorder ran.
		_gdk_ledger_note "$said"
	elif [ "$rc" -ne 0 ]; then
		_gdk_ledger_note "the recorder exited $rc: ${said%%$'\n'*}"
	fi
	return 0
}

# _gdk_ledger_close <logfile> — file this slot's row, exactly once.
_gdk_ledger_close() {
	[ -n "$GDK_LEDGER_CMD" ] || return 0
	local side start='' gate='' fault='' now duration verdict
	side="$(_gdk_ledger_sidecar "${1-}")"
	# No sidecar: no slot was opened, or the row is already filed.
	[ -f "$side" ] || return 0
	# Line 3 is the first failing capture, if any.
	{ read -r start && read -r gate && read -r fault; } < "$side" 2>/dev/null || true
	rm -f "$side" 2>/dev/null || true
	case "$start" in ''|*[!0-9]*) return 0 ;; esac
	[ -n "$gate" ] || return 0
	now="$(_gdk_now_ms)"
	[ -n "$now" ] || return 0
	duration=$(( now - start ))
	[ "$duration" -ge 0 ] || duration=0
	verdict="$(_gdk_ledger_verdict "$fault")"
	if [ -z "$verdict" ]; then
		_gdk_ledger_note "gate \"$gate\" published no verdict this library can name (set GDK_GATE_VERDICT, or report through gdk_gate_capture)"
		return 0
	fi
	# Parked beside the sidecar, the one directory this slot has proved writable.
	_gdk_ledger_record "$gate" "$verdict" "$duration" "$side.out"
	return 0
}

# gdk_gate_log <gate> — echo this run's transcript path, cleared; the cost clock starts here.
gdk_gate_log() {
	local gate="${1:?usage: gdk_gate_log <gate>}"
	mkdir -p "$GDK_GATE_REPORT_DIR"
	local path="$GDK_GATE_REPORT_DIR/$gate.log"
	: > "$path"
	_gdk_ledger_open "$gate" "$path"
	printf '%s\n' "$path"
}

# gdk_gate_capture <logfile> -- <cmd...> — run <cmd>, APPEND its output to
# <logfile> under the byte cap, stream it under VERBOSE. Publishes the command's
# own code in GDK_GATE_EXIT (last-write-wins) and tells the slot about a failure.
# errexit is suspended around the pipeline: under `set -eo pipefail` the shell
# would die on this line, and `|| true` would reset PIPESTATUS.
gdk_gate_capture() {
	local log="${1:?usage: gdk_gate_capture <log> -- <cmd...>}"; shift
	[ "${1:-}" = "--" ] && shift
	local errexit_was_set=0
	case "$-" in *e*) errexit_was_set=1; set +e ;; esac
	if [ "${VERBOSE:-0}" != "0" ]; then
		"$@" 2>&1 | head -c "$GDK_LOG_CAP_BYTES" | tee -a "$log"
	else
		"$@" 2>&1 | head -c "$GDK_LOG_CAP_BYTES" >> "$log"
	fi
	# shellcheck disable=SC2034  # read by the sourcing wrapper, not here
	GDK_GATE_EXIT="${PIPESTATUS[0]}"
	# Before the errexit restore, so a non-zero here cannot kill the wrapper.
	_gdk_ledger_fault "$log" "$GDK_GATE_EXIT"
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
# It closes the cost row AFTER the line, and returns 0 so a wrapper under
# `set -e` never dies of a ledger problem.
gdk_gate_verdict() {
	printf '[%s] %s — full log: %s\n' \
		"${1:?usage: gdk_gate_verdict <TAG> <message> <log>}" "${2-}" "${3-}"
	_gdk_ledger_close "${3-}"
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

# _gdk_st_gate <lib> <ledger cmd> <gate exit> — one whole gate in a CHILD shell
# under `set -euo pipefail`; echoes what it said, then `exit=<its own code>`.
_gdk_st_gate() {
	local out rc=0
	# shellcheck disable=SC2016  # $1/$2/$3 are the CHILD shell's positionals
	out="$(bash -c '
		set -euo pipefail
		# shellcheck source=/dev/null
		source "$1"
		GDK_LEDGER_CMD="$2"
		log="$(gdk_gate_log strict)"
		gdk_gate_capture "$log" -- sh -c "exit $3"
		status="$GDK_GATE_EXIT"
		gdk_gate_verdict STRICT "done" "$log"
		exit "$status"
	' _ "$1" "$2" "$3" 2>/dev/null)" || rc=$?
	printf '%s\nexit=%s\n' "$out" "$rc"
}

_gdk_self_test() {
	local scratch verdict log body status hung lib recorded ledger_case t0 elapsed
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
		status=0; gdk_run_bounded 1 -- sleep 5 || status=$?
		hung=0
		[ "$status" = "$GDK_EXIT_SIGTERM_TIMEOUT" ] \
			|| [ "$status" = "$GDK_EXIT_SIGKILL_TIMEOUT" ] || hung=1
		_gdk_st_true 'run_bounded reports a hang as 124/137' "$hung"
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

	# --- the cost row -------------------------------------------------------
	# A recorder stub: every case asserts on the argv it was handed, one line per call.
	GDK_ST_REC_LOG="$scratch/recorder.log"
	export GDK_ST_REC_LOG
	cat > "$scratch/rec.sh" <<'REC_EOF'
#!/usr/bin/env bash
{ printf 'CALL'; for a in "$@"; do printf ' ARG[%s]' "$a"; done; printf '\n'
} >> "$GDK_ST_REC_LOG" 2>/dev/null || exit 4   # 4: the ledger is unwritable
[ -z "${GDK_ST_REC_SAY:-}" ] || printf '%s\n' "$GDK_ST_REC_SAY"
exit "${GDK_ST_REC_EXIT:-0}"
REC_EOF
	cat > "$scratch/hang.sh" <<'HANG_EOF'
#!/usr/bin/env bash
sleep 30
HANG_EOF
	# A recorder that exits cleanly and leaves a child behind. sleep 3 against a
	# 1 s bound and a 2000 ms ceiling keeps the margin wide and the suite fast.
	cat > "$scratch/fork.sh" <<'FORK_EOF'
#!/usr/bin/env bash
sleep 3 &
exit 0
FORK_EOF
	: > "$GDK_ST_REC_LOG"

	# Unset spawns nothing: the recorder's sentinel is the assertion.
	GDK_LEDGER_CMD=''
	log="$(gdk_gate_log quiet)"
	status=0; [ ! -f "$(_gdk_ledger_sidecar "$log")" ] || status=1
	_gdk_st_true 'an unset GDK_LEDGER_CMD opens no slot' "$status"
	GDK_GATE_EXIT=0
	gdk_gate_verdict QUIET 'PASS' "$log" >/dev/null
	_gdk_st_eq 'an unset GDK_LEDGER_CMD spawns no recorder' \
		'' "$(cat "$GDK_ST_REC_LOG")"

	# THE ROW ITSELF, and the verdict line it must not touch.
	GDK_LEDGER_CMD="bash $scratch/rec.sh"
	: > "$GDK_ST_REC_LOG"
	GDK_GATE_CENSUS=''
	log="$(gdk_gate_log check)"
	GDK_GATE_EXIT=0
	body="$(gdk_gate_verdict CHECK 'PASS (12 files)' "$log" 2>/dev/null)"
	_gdk_st_eq 'the recorder never reaches the verdict stream' \
		"[CHECK] PASS (12 files) — full log: $GDK_GATE_REPORT_DIR/check.log" \
		"$body"
	recorded="$(cat "$GDK_ST_REC_LOG")"
	_gdk_st_eq 'one gdk_gate_log slot files exactly one row' '1' \
		"$(grep -c '^CALL' "$GDK_ST_REC_LOG" | tr -d ' ')"
	_gdk_st_has 'the row names the verb' "$recorded" 'ARG[ledger] ARG[record]'
	_gdk_st_has 'the row names the gate' "$recorded" 'ARG[--gate] ARG[check]'
	_gdk_st_has 'a gate that exited 0 is a PASS' "$recorded" 'ARG[--verdict] ARG[PASS]'
	status=0
	[ -n "$(sed -n 's/.*ARG\[--duration-ms\] ARG\[\([0-9][0-9]*\)\].*/\1/p' \
		"$GDK_ST_REC_LOG")" ] || status=1
	_gdk_st_true 'the row carries an integer millisecond duration' "$status"

	# The census is absent, never zero, and never read out of the prose.
	_gdk_st_lacks 'an unset census is an omitted flag' "$recorded" 'ARG[--census]'
	: > "$GDK_ST_REC_LOG"
	log="$(gdk_gate_log prose)"
	gdk_gate_verdict PROSE 'PASS (683 files, 0 findings)' "$log" >/dev/null 2>&1
	_gdk_st_lacks 'no census is inferred from the message' \
		"$(cat "$GDK_ST_REC_LOG")" 'ARG[--census]'
	: > "$GDK_ST_REC_LOG"
	GDK_GATE_CENSUS=683
	log="$(gdk_gate_log counted)"
	gdk_gate_verdict COUNTED 'PASS' "$log" >/dev/null 2>&1
	_gdk_st_has 'a census the CALLER set rides on the row' \
		"$(cat "$GDK_ST_REC_LOG")" 'ARG[--census] ARG[683]'
	GDK_GATE_CENSUS=''

	# One row per run, not one per verdict line.
	: > "$GDK_ST_REC_LOG"
	log="$(gdk_gate_log multi)"
	gdk_gate_verdict MULTI 'first'  "$log" >/dev/null 2>&1
	gdk_gate_verdict MULTI 'second' "$log" >/dev/null 2>&1
	gdk_gate_verdict MULTI 'third'  "$log" >/dev/null 2>&1
	_gdk_st_eq 'three verdicts on one slot file ONE row' '1' \
		"$(grep -c '^CALL' "$GDK_ST_REC_LOG" | tr -d ' ')"

	# One verdict per slot, answering for every capture, not the last; asserted
	# on the argv, since the console line was right while the row was inverted.
	: > "$GDK_ST_REC_LOG"
	GDK_GATE_EXIT=''
	log="$(gdk_gate_log mixed)"
	gdk_gate_capture "$log" -- sh -c 'exit 1' >/dev/null 2>&1
	gdk_gate_capture "$log" -- sh -c 'exit 0' >/dev/null 2>&1
	_gdk_st_eq 'the LAST capture still publishes GDK_GATE_EXIT' '0' "$GDK_GATE_EXIT"
	gdk_gate_verdict MIXED 'FAIL on first' "$log" >/dev/null 2>&1
	_gdk_st_has 'a slot whose captures were 1 then 0 files FAIL, not PASS' \
		"$(cat "$GDK_ST_REC_LOG")" 'ARG[--verdict] ARG[FAIL]'
	_gdk_st_eq 'and a multi-capture slot is still exactly one row' '1' \
		"$(grep -c '^CALL' "$GDK_ST_REC_LOG" | tr -d ' ')"

	# ...and a slot every capture passed is still a PASS.
	: > "$GDK_ST_REC_LOG"
	log="$(gdk_gate_log allgood)"
	gdk_gate_capture "$log" -- sh -c 'exit 0' >/dev/null 2>&1
	gdk_gate_capture "$log" -- sh -c 'exit 0' >/dev/null 2>&1
	gdk_gate_verdict ALLGOOD 'PASS' "$log" >/dev/null 2>&1
	_gdk_st_has 'two passing captures on one slot file PASS' \
		"$(cat "$GDK_ST_REC_LOG")" 'ARG[--verdict] ARG[PASS]'

	# A capture against a log no slot was opened for mints nothing.
	: > "$GDK_ST_REC_LOG"
	: > "$GDK_GATE_REPORT_DIR/orphan.log"
	gdk_gate_capture "$GDK_GATE_REPORT_DIR/orphan.log" -- sh -c 'exit 1' >/dev/null 2>&1
	status=0
	[ ! -f "$(_gdk_ledger_sidecar "$GDK_GATE_REPORT_DIR/orphan.log")" ] || status=1
	_gdk_st_true 'a capture never mints a slot its log never opened' "$status"
	GDK_GATE_EXIT=0

	# The value's quoting survives the bounded parse.
	: > "$GDK_ST_REC_LOG"
	GDK_LEDGER_CMD="bash $scratch/rec.sh --from \"git+https://example.invalid/x@v0.0.0\" agentic-sdlc"
	log="$(gdk_gate_log quoted)"
	gdk_gate_verdict QUOTED 'PASS' "$log" >/dev/null 2>&1
	_gdk_st_has 'a quoted value arrives as ONE argv element' \
		"$(cat "$GDK_ST_REC_LOG")" \
		'ARG[--from] ARG[git+https://example.invalid/x@v0.0.0] ARG[agentic-sdlc]'
	GDK_LEDGER_CMD="bash $scratch/rec.sh"

	# The publish-only shape: nothing sets GDK_GATE_EXIT, so the runner publishes its own verdict.
	: > "$GDK_ST_REC_LOG"
	GDK_GATE_EXIT=''
	GDK_GATE_VERDICT=FAIL
	log="$(gdk_gate_log published)"
	gdk_gate_publish "$log" 'held in a variable' >/dev/null
	gdk_gate_verdict PUBLISHED 'FAIL (2 of 40)' "$log" >/dev/null 2>&1
	recorded="$(cat "$GDK_ST_REC_LOG")"
	_gdk_st_has 'a gate that never captured still files its cost' \
		"$recorded" 'ARG[--gate] ARG[published]'
	_gdk_st_has 'and the verdict its runner published' \
		"$recorded" 'ARG[--verdict] ARG[FAIL]'
	GDK_GATE_VERDICT=''

	# THE VERDICT IS DERIVED FROM THE EXIT CODE, INCLUDING THE TIMEOUT PAIR.
	: > "$GDK_ST_REC_LOG"
	GDK_GATE_EXIT=3
	log="$(gdk_gate_log failed)"
	gdk_gate_verdict FAILED 'FAIL (exit 3)' "$log" >/dev/null 2>&1
	_gdk_st_has 'a non-zero exit is a FAIL' \
		"$(cat "$GDK_ST_REC_LOG")" 'ARG[--verdict] ARG[FAIL]'
	: > "$GDK_ST_REC_LOG"
	GDK_GATE_EXIT="$GDK_EXIT_SIGTERM_TIMEOUT"
	log="$(gdk_gate_log hung)"
	gdk_gate_verdict HUNG 'HUNG' "$log" >/dev/null 2>&1
	_gdk_st_has 'the timeout pair is a HANG, not a FAIL' \
		"$(cat "$GDK_ST_REC_LOG")" 'ARG[--verdict] ARG[HANG]'
	GDK_GATE_EXIT=0

	# A gate name with a space and a metacharacter is one argv element, always.
	: > "$GDK_ST_REC_LOG"
	log="$(gdk_gate_log 'bad name;touch pwned')"
	gdk_gate_verdict BAD 'PASS' "$log" >/dev/null 2>&1
	_gdk_st_has 'a gate name is ONE argv element, metacharacters and all' \
		"$(cat "$GDK_ST_REC_LOG")" 'ARG[bad name;touch pwned]'
	status=0; [ ! -f "$scratch/pwned" ] || status=1
	_gdk_st_true 'and nothing in it was executed' "$status"

	# --- FAIL OPEN: the refusal matrix; the verdict prints and the gate's code survives
	: > "$GDK_ST_REC_LOG"
	for ledger_case in \
		'' \
		"$scratch/no-such-recorder" \
		"env GDK_ST_REC_EXIT=1 bash $scratch/rec.sh" \
		"env GDK_ST_REC_SAY=noise bash $scratch/rec.sh" \
		"env GDK_ST_REC_LOG=$scratch/read-only/x bash $scratch/rec.sh"
	do
		body="$(_gdk_st_gate "$lib" "$ledger_case" 7)"
		_gdk_st_eq "a broken recorder never changes a failing gate's code (${ledger_case:-unset})" \
			"[STRICT] done — full log: $GDK_GATE_REPORT_DIR/strict.log
exit=7" "$body"
		body="$(_gdk_st_gate "$lib" "$ledger_case" 0)"
		_gdk_st_eq "a broken recorder never changes a passing gate's code (${ledger_case:-unset})" \
			"[STRICT] done — full log: $GDK_GATE_REPORT_DIR/strict.log
exit=0" "$body"
	done

	# --- the wall-clock cases, the only slow ones ----------------------------
	# Only the clock can tell a fixed library from a broken one here.
	# GDK_ST_SKIP_TIMING=1 is a caller's optimisation for mutation tests that
	# have nothing to do with timing; the default runs everything.
	if [ -n "$GDK_TIMEOUT" ] && [ "${GDK_ST_SKIP_TIMING:-0}" != "1" ]; then
		# Exported: the bound is read by the library in the CHILD shell.
		export GDK_LEDGER_TIMEOUT=1
		body="$(_gdk_st_gate "$lib" "bash $scratch/hang.sh" 7)"
		unset GDK_LEDGER_TIMEOUT
		_gdk_st_eq 'a recorder that hangs is bounded, and the gate still reports' \
			"[STRICT] done — full log: $GDK_GATE_REPORT_DIR/strict.log
exit=7" "$body"

		# And a recorder that forks: it exits 0 and the deadline never fires, so only
		# wall clock can see a gate held open by the pipe the grandchild inherited.
		export GDK_LEDGER_TIMEOUT=1
		t0="$(_gdk_now_ms)"
		body="$(_gdk_st_gate "$lib" "bash $scratch/fork.sh" 7)"
		elapsed="$(_gdk_now_ms)"
		unset GDK_LEDGER_TIMEOUT
		_gdk_st_eq 'a recorder that forks still lets the gate report' \
			"[STRICT] done — full log: $GDK_GATE_REPORT_DIR/strict.log
exit=7" "$body"
		if [ -n "$t0" ] && [ -n "$elapsed" ]; then
			elapsed=$(( elapsed - t0 ))
			status=0; [ "$elapsed" -lt 2000 ] || status=1
			_gdk_st_true \
				"a recorder that forks does not hold the gate open (${elapsed} ms, bound 1000)" \
				"$status"
		else
			echo '  SKIP — no millisecond clock; the forking-recorder bound was not timed' >&2
		fi

		# And a value that executes while parsed; wall clock again, since line and code stay right.
		export GDK_LEDGER_TIMEOUT=1
		t0="$(_gdk_now_ms)"
		body="$(_gdk_st_gate "$lib" "bash $scratch/rec.sh \$(sleep 3)" 7)"
		elapsed="$(_gdk_now_ms)"
		unset GDK_LEDGER_TIMEOUT
		_gdk_st_eq 'a substituting recorder value still lets the gate report' \
			"[STRICT] done — full log: $GDK_GATE_REPORT_DIR/strict.log
exit=7" "$body"
		if [ -n "$t0" ] && [ -n "$elapsed" ]; then
			elapsed=$(( elapsed - t0 ))
			status=0; [ "$elapsed" -lt 2000 ] || status=1
			_gdk_st_true \
				"a substitution in GDK_LEDGER_CMD is parsed UNDER the bound (${elapsed} ms, bound 1000)" \
				"$status"
		else
			echo '  SKIP — no millisecond clock; the parse-under-bound case was not timed' >&2
		fi
	else
		echo '  SKIP — no timeout binary; the bounded-recorder case did not run' >&2
	fi
	GDK_LEDGER_CMD=''
	unset GDK_ST_REC_LOG

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
