#!/usr/bin/env bash
# gdk_runners.sh — the shared library every Godot-booting gate in this repo
# runs through. Wire it as the thing your `tools/dev/*.sh` wrappers source.
#
# SOURCE this (do not execute it), except for `--self-test` / `--help`:
#
#   source "$(dirname "${BASH_SOURCE[0]}")/gdk_runners.sh"
#   gdk_sandbox_home                       # export a PER-RUN sandboxed HOME
#   log="$(gdk_gate_log parse)"            # this gate's transcript slot
#   gdk_gate_capture "$log" -- make thing  # run it, quiet unless VERBOSE=1
#   gdk_gate_verdict PARSE "PASS (12 files)" "$log"
#
# It exists because two consumer repos grew the same 400 lines of shell twice
# and then drifted: quiet gate capture with a one-line verdict naming a full
# log, a per-run self-destroying sandbox HOME, and a bounded-run contract that
# can tell a hang from a failure. One definition each, here, so a fix reaches
# both.
#
# EVERY public function is prefixed `gdk_`; every private one `_gdk_`. A
# consumer that renames them is forking the library and stranding the next fix.
#
# --- project config (yours to edit after install — the file is your repo's) --
# Each of these is an override-able default: set it in the environment, or edit
# it here.
#
#   GDK_GATE_REPORT_DIR       where a gate's full transcript lands. Gitignore
#                             it. Bounded by construction: the slot is named by
#                             GATE and each run clears its own.
#   GDK_LOG_CAP_BYTES         hard cap on a captured stream, so a runaway boot
#                             spewing to stdout cannot fill the disk. 50 MB is
#                             ~1000x a normal transcript.
#   GDK_TIMEOUT_KILL_AFTER    grace period between the SIGTERM a bound fires
#                             and the SIGKILL that guarantees no orphaned
#                             engine process survives.
#   GDK_SANDBOX_DIRNAME       repo-relative root of the per-run HOME sandbox.
#                             Gitignore it.
#   GDK_HEADLESS_HOME         set BY A CALLER that mints and owns its own HOME
#                             (a parallel scenario runner giving each job one).
#                             Honored verbatim: not reaped, not destroyed.
#   VERBOSE=1                 stream every captured gate to the console too.
# -----------------------------------------------------------------------------

# Guard against double-sourcing: a wrapper may source us once, and some chains
# source transitively. `return` works when sourced; the `exit` is the executed
# path, which only `--self-test` / `--help` ever take.
if [ -n "${_GDK_RUNNERS_SOURCED:-}" ]; then
	# shellcheck disable=SC2317  # the `exit` is the EXECUTED path (--self-test)
	return 0 2>/dev/null || exit 0
fi
_GDK_RUNNERS_SOURCED=1

GDK_GATE_REPORT_DIR="${GDK_GATE_REPORT_DIR:-.gate-reports}"
GDK_LOG_CAP_BYTES="${GDK_LOG_CAP_BYTES:-52428800}"
GDK_TIMEOUT_KILL_AFTER="${GDK_TIMEOUT_KILL_AFTER:-5s}"
GDK_SANDBOX_DIRNAME="${GDK_SANDBOX_DIRNAME:-.headless-userdata}"

# The tag every line this library prints on its OWN behalf carries, so a
# consumer can tell the library's voice from its gate's.
GDK_LIB_TAG="gdk-runners"

# --- exit-hook dispatcher ----------------------------------------------------
# Bash has ONE `trap … EXIT` slot per shell: a wrapper's own `trap cleanup EXIT`
# silently CLOBBERS anything the sandbox installed (and vice versa, depending on
# source order). So there is exactly one EXIT trap in a sandboxed wrapper — this
# dispatcher — and everything else registers a hook.
#
#   RULE: inside a wrapper that calls gdk_sandbox_home, never write a bare
#   `trap … EXIT`. Use `gdk_on_exit '<command>'`.
#
# Hooks run in registration order; a failing hook never masks the script's own
# exit status.
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

# --- user:// HOME sandbox (the single most load-bearing safety line) --------
# A headless boot runs the project's full autoload stack — save flushes, log
# appends — against whatever `user://` resolves to, and it MUST NEVER be the
# real player data. Overriding HOME is the only redirect Godot honors on macOS
# (XDG_DATA_HOME is ignored there); Linux honors HOME too.
#
# The sandbox is PER-RUN and self-destroying: nothing survives a run, no cache
# and no shared directory of any kind. A shared one accumulated ~10,000 save
# dirs over two months and then failed a test that counted them — a run's
# outcome must not depend on the history of every run before it. Everything a
# run needs is re-derived from version-controlled source inside that HOME and
# dies with it.
#
# Layout under the repo-root sandbox dir:
#   $GDK_SANDBOX_DIRNAME/runs/    one self-destroying HOME per run
GDK_SANDBOX_RUNS_SUBDIR="runs"
GDK_SANDBOX_RUN_PREFIX="run-"

# _gdk_destroy_run_home — remove THIS run's HOME. Guarded: it will only ever
# delete a path that looks like one we minted, so a mis-set variable can never
# point `rm -rf` at the real ~/Library/Application Support.
# shellcheck disable=SC2329  # invoked indirectly via gdk_on_exit
_gdk_destroy_run_home() {
	local home="${_GDK_RUN_HOME:-}"
	[ -n "$home" ] || return 0
	case "$home" in
		*"/$GDK_SANDBOX_DIRNAME/$GDK_SANDBOX_RUNS_SUBDIR/$GDK_SANDBOX_RUN_PREFIX"*)
			rm -rf "$home" ;;
		*)
			echo "$GDK_LIB_TAG: refusing to remove non-sandbox HOME '$home'" >&2 ;;
	esac
	_GDK_RUN_HOME=""
}

# gdk_sandbox_home — export a HOME no headless boot can escape. Call it before
# the first engine invocation in any wrapper.
gdk_sandbox_home() {
	if [ -n "${GDK_HEADLESS_HOME:-}" ]; then
		# The CALLER minted this home and owns its lifetime (a parallel
		# scenario runner gives every job its own). Honor it verbatim — do not
		# reap it, do not destroy it.
		HOME="$GDK_HEADLESS_HOME"
		export HOME
		mkdir -p "$HOME"
		return 0
	fi

	local runs="$PWD/$GDK_SANDBOX_DIRNAME/$GDK_SANDBOX_RUNS_SUBDIR"
	mkdir -p "$runs"

	# The pid is in the name on purpose: it is how a reaper tells a CONCURRENT
	# run's live HOME (never touch) from one a killed run abandoned.
	_GDK_RUN_HOME="$(mktemp -d "$runs/$GDK_SANDBOX_RUN_PREFIX$$-XXXXXX")"
	HOME="$_GDK_RUN_HOME"
	export HOME
	gdk_on_exit _gdk_destroy_run_home
}

# gdk_sandbox_tmpfile <template> — a scratch file INSIDE the per-run HOME, so
# it dies with the run. Wrapper logs used to land in shared /tmp, where
# concurrent runs and separate users on one machine overwrite each other's
# transcript. Falls back to $TMPDIR when no sandbox home is live, so it never
# lies about where it put the file.
gdk_sandbox_tmpfile() {
	local template="${1:?usage: gdk_sandbox_tmpfile <name.XXXXXX>}"
	local dir="${_GDK_RUN_HOME:-${TMPDIR:-/tmp}}"
	mkdir -p "$dir"
	mktemp "$dir/$template"
}

# --- bounded-run / hang-detection contract ----------------------------------
# timeout(1) exits 124 when its own SIGTERM deadline fires and 137 (128+SIGKILL)
# when --kill-after escalates. Either means the run hung.
GDK_EXIT_SIGTERM_TIMEOUT=124
GDK_EXIT_SIGKILL_TIMEOUT=137

# timeout binary: GNU coreutils ships `timeout`; on a stock macOS with Homebrew
# coreutils it is `gtimeout`. Resolve once so every wrapper agrees. Empty if
# neither is present — callers that require it check and fail loud.
if command -v timeout >/dev/null 2>&1; then
	GDK_TIMEOUT="timeout"
elif command -v gtimeout >/dev/null 2>&1; then
	GDK_TIMEOUT="gtimeout"
else
	GDK_TIMEOUT=""
fi

# gdk_run_bounded <seconds> -- <cmd...>
# Run a NON-piped command under the shared timeout contract; returns its exit
# code (124/137 on hang, 2 when no timeout binary exists). A piped capture
# keeps its own PIPESTATUS idiom and references "$GDK_TIMEOUT" directly.
gdk_run_bounded() {
	local secs="${1:?usage: gdk_run_bounded <seconds> -- <cmd...>}"; shift
	[ "${1:-}" = "--" ] && shift
	if [ -z "$GDK_TIMEOUT" ]; then
		echo "$GDK_LIB_TAG: no timeout/gtimeout on PATH — install coreutils" >&2
		return 2
	fi
	"$GDK_TIMEOUT" --kill-after="$GDK_TIMEOUT_KILL_AFTER" "${secs}s" "$@"
}

# --- gate output: a summary on the console, the full transcript on disk ------
# A headless gate used to STREAM its whole boot to the console: `make parse`
# printed 273 lines of which two mattered (the verdict, and any error line);
# `make warnings` printed 1,581. Every agent pays that on every run, so the
# default is the summary and the stream goes to a file.
#
# The report dir cannot rot the way a per-scenario one does: the slot is named
# by GATE, each run clears the slot it is about to write, and there is a
# handful of gate names — so the directory is bounded BY CONSTRUCTION and there
# is no reaper anyone can forget to call.

# gdk_gate_log <gate> — echo this run's transcript path, cleared and ready.
gdk_gate_log() {
	local gate="${1:?usage: gdk_gate_log <gate>}"
	mkdir -p "$GDK_GATE_REPORT_DIR"
	local path="$GDK_GATE_REPORT_DIR/$gate.log"
	: > "$path"
	printf '%s\n' "$path"
}

# gdk_gate_capture <logfile> -- <cmd...>
# Run <cmd>, APPENDING its combined output to <logfile> under the shared byte
# cap, and stream it to the console only under VERBOSE. Appends so a two-stage
# gate (boot, then sweep) publishes one transcript.
#
# Sets GDK_GATE_EXIT to the COMMAND's own exit code — `head -c` is the last
# pipe element and exits 0, so a caller must read that and never `$?`.
gdk_gate_capture() {
	local log="${1:?usage: gdk_gate_capture <log> -- <cmd...>}"; shift
	[ "${1:-}" = "--" ] && shift
	if [ "${VERBOSE:-0}" != "0" ]; then
		"$@" 2>&1 | head -c "$GDK_LOG_CAP_BYTES" | tee -a "$log"
	else
		"$@" 2>&1 | head -c "$GDK_LOG_CAP_BYTES" >> "$log"
	fi
	# shellcheck disable=SC2034  # read by the sourcing wrapper, not here
	GDK_GATE_EXIT="${PIPESTATUS[0]}"
}

# gdk_gate_publish <logfile> <transcript>
# The capture-then-PARSE shape: a gate that must hold the whole transcript in a
# variable to reconcile a test runner's counts before it can report cannot
# stream through the pipeline above. Same contract — persist capped, echo under
# VERBOSE.
gdk_gate_publish() {
	local log="${1:?usage: gdk_gate_publish <log> <transcript>}"
	printf '%s\n' "${2-}" | head -c "$GDK_LOG_CAP_BYTES" > "$log"
	[ "${VERBOSE:-0}" = "0" ] || printf '%s\n' "${2-}"
}

# gdk_gate_verdict <TAG> <message> <logfile>
# The ONE shape a gate's result line takes, so the transcript is always named
# in the same place and a failing run is one `sed -n` away:
#   [TAG] <message> — full log: <path>
gdk_gate_verdict() {
	printf '[%s] %s — full log: %s\n' \
		"${1:?usage: gdk_gate_verdict <TAG> <message> <log>}" "${2-}" "${3-}"
}

# --- the import-cache rebuild ------------------------------------------------
# Regenerate `.godot` (the uid map + the `class_name` global registry) via a
# headless EDITOR import pass, bounded by the shared timeout. Output is
# discarded and the engine's exit code is SWALLOWED: this is a best-effort
# recovery step for its other caller (a cold-cache retry), so the caller that
# cares proves the outcome by checking the artifacts instead. Requires a prior
# gdk_sandbox_home — the pass boots the project.
GDK_REBUILD_IMPORT_CACHE_TIMEOUT="${GDK_REBUILD_IMPORT_CACHE_TIMEOUT:-60}"

# gdk_rebuild_import_cache [seconds]
gdk_rebuild_import_cache() {
	local secs="${1:-$GDK_REBUILD_IMPORT_CACHE_TIMEOUT}"
	if [ -n "$GDK_TIMEOUT" ]; then
		"$GDK_TIMEOUT" --kill-after="$GDK_TIMEOUT_KILL_AFTER" "${secs}s" \
			godot --path . --headless --editor --quit >/dev/null 2>&1 || true
	else
		godot --path . --headless --editor --quit >/dev/null 2>&1 || true
	fi
}

# --- --self-test — the contract, PROVEN rather than claimed ------------------
# `bash gdk_runners.sh --self-test` runs a fake gate through capture → verdict
# and checks every claim the comments above make. Same shape as the hook
# corpus: a corpus that is re-run is the only reason to trust it six months
# later. It runs entirely inside a scratch dir it makes and removes, so it can
# never write into the repo it lives in.

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

_gdk_self_test() {
	local scratch verdict log body status hung
	scratch="$(mktemp -d "${TMPDIR:-/tmp}/gdk-runners-selftest.XXXXXX")" || return 1
	cd "$scratch" || return 1
	# Re-read it from the shell: a TMPDIR with a trailing slash yields `//` in
	# the mktemp path, and every prefix comparison below would silently miss.
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
	body="$(VERBOSE=0 gdk_gate_capture "$log" -- printf 'engine line\n')"
	_gdk_st_eq 'capture prints nothing when VERBOSE=0' '' "$body"
	_gdk_st_eq 'capture persists the stream' 'engine line' "$(cat "$log")"
	body="$(VERBOSE=1 gdk_gate_capture "$log" -- printf 'second line\n')"
	_gdk_st_eq 'capture streams when VERBOSE=1' 'second line' "$body"
	_gdk_st_eq 'capture APPENDS (a two-stage gate is one transcript)' \
		'engine line
second line' "$(cat "$log")"

	# --- gdk_gate_capture: GDK_GATE_EXIT is the COMMAND's code, not head's ---
	GDK_GATE_EXIT=''
	gdk_gate_capture "$log" -- sh -c 'exit 7' >/dev/null 2>&1
	_gdk_st_eq 'capture reports the command exit code, not the pipeline tail' \
		'7' "$GDK_GATE_EXIT"

	# --- the byte cap is real ------------------------------------------------
	log="$(gdk_gate_log capped)"
	( GDK_LOG_CAP_BYTES=8; gdk_gate_capture "$log" -- printf '0123456789abcdef' )
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

	# --- gdk_sandbox_home: HOME lands inside the sandbox, tmpfiles with it ---
	( gdk_sandbox_home
	  case "$HOME" in
	    "$scratch/$GDK_SANDBOX_DIRNAME/$GDK_SANDBOX_RUNS_SUBDIR/$GDK_SANDBOX_RUN_PREFIX"*) ;;
	    *) printf '  MISS — sandbox HOME outside the sandbox dir: %s\n' "$HOME" >&2; exit 1 ;;
	  esac
	  case "$(gdk_sandbox_tmpfile stamp.XXXXXX)" in
	    "$HOME"/stamp.*) ;;
	    *) printf '  MISS — sandbox tmpfile landed outside the run HOME\n' >&2; exit 1 ;;
	  esac )
	_gdk_st_true 'sandbox_home exports a HOME under the sandbox dir' "$?"

	# --- the destroy guard refuses a HOME it did not mint --------------------
	_GDK_RUN_HOME="$scratch/not-a-sandbox"
	mkdir -p "$_GDK_RUN_HOME"
	_gdk_destroy_run_home 2>/dev/null
	status=0; [ -d "$scratch/not-a-sandbox" ] || status=1
	_gdk_st_true 'destroy refuses a path outside the sandbox layout' "$status"

	cd / || return 1
	rm -rf "$scratch"
	return 0
}

_gdk_usage() {
	cat <<'USAGE_EOF'
usage: source gdk_runners.sh            the normal use — a shell library
       bash gdk_runners.sh --self-test  run the contract corpus
       bash gdk_runners.sh --help       this message

Public functions: gdk_on_exit, gdk_sandbox_home, gdk_sandbox_tmpfile,
gdk_run_bounded, gdk_gate_log, gdk_gate_capture, gdk_gate_publish,
gdk_gate_verdict, gdk_rebuild_import_cache.
USAGE_EOF
}

# Executed rather than sourced? Only --self-test and --help are supported, and
# only one of them: an extra argument is a caller who thinks this takes options
# it does not, and guessing at their intent is how a gate runs the wrong thing.
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
