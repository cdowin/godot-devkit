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
#   GDK_SANDBOX_DIRNAME       root of the per-run HOME sandbox, resolved
#                             against the CWD at the moment gdk_sandbox_home
#                             runs (every wrapper cd's to the repo root first).
#                             Gitignore it.
#   GDK_GODOT                 the engine binary every runner invokes. `godot`
#                             on a PATH that has it; an absolute
#                             /Applications/Godot.app/… path otherwise.
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
GDK_GODOT="${GDK_GODOT:-godot}"

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

# gdk_pid_is_live <pid> — true while that process exists, INCLUDING when it
# belongs to another user. `kill -0` is permission-gated: on a pid this user
# does not own it fails with EPERM, which reads as "dead" and is how a reaper
# came to `rm -rf` a live peer's HOME in a checkout shared by two accounts.
# `ps -p` answers existence without needing signal permission; the `kill -0`
# fast path stays because it is a syscall rather than a fork.
gdk_pid_is_live() {
	kill -0 "${1:?usage: gdk_pid_is_live <pid>}" 2>/dev/null && return 0
	ps -p "$1" >/dev/null 2>&1
}

# _gdk_reap_stale_run_homes <runs_dir> — the forget-proof backstop. A SIGKILLed
# run (or a future wrapper that clobbers the EXIT trap anyway) leaves its HOME
# behind; the next run reaps it. The owning pid is encoded in the directory
# name, so a CONCURRENT run's live HOME is never touched — and a directory
# whose name carries no pid is left alone rather than guessed at.
_gdk_reap_stale_run_homes() {
	local runs_dir="${1:?usage: _gdk_reap_stale_run_homes <runs_dir>}" dir pid
	for dir in "$runs_dir/$GDK_SANDBOX_RUN_PREFIX"*; do
		[ -d "$dir" ] || continue
		pid="${dir##*/"$GDK_SANDBOX_RUN_PREFIX"}"
		pid="${pid%%-*}"
		case "$pid" in ''|*[!0-9]*) continue ;; esac
		gdk_pid_is_live "$pid" && continue
		rm -rf "$dir"
	done
}

# gdk_report_dir_defect <dir> — '' when <dir> is a directory a runner may
# create, CLEAR and reap; otherwise the one-line reason it may not, printed on
# stdout, with a non-zero return.
#
# scenario.sh and capture.sh each own their report directory and each aims an
# `rm -rf` at what the project config names. Both took that name on trust:
# `GDK_SCENARIO_REPORT_DIR=.` deleted a probe repo whole — `.git` included —
# BEFORE the boot, and `GDK_CAPTURE_REPORT_DIR=tests` emptied `tests/`. Neither
# is a default and neither is reachable without an explicit misconfiguration,
# which is exactly the class a guard is cheap for and an incident is not.
#
# Three refusals, and they are structural rather than a denylist of paths:
#
#   * a report dir is RELATIVE to the project root — every caller `cd`s there
#     first — so an absolute path or a `~` is a caller who thinks otherwise;
#   * no segment may be `.` or `..`, which is what makes "under the project
#     root, and not the root itself" true BY CONSTRUCTION rather than by
#     resolving a path that may not exist yet;
#   * it may hold nothing git TRACKS. A directory the repo keeps content in is
#     the repo's, whatever the config says — that is the clause that separates
#     `.scenario-reports` from `tests`, and no amount of path arithmetic can.
#     Softly skipped outside a git checkout (a tarball, a fresh extract): the
#     two structural clauses still hold, and refusing every run for want of a
#     `.git` would trade one incident for a broken tool.
gdk_report_dir_defect() {
	local dir="${1-}"
	if [ -z "$dir" ]; then
		printf 'the report directory is unset or empty\n'
		return 1
	fi
	case "$dir" in
		/*|'~'*)
			printf "'%s' is not relative to the project root\n" "$dir"
			return 1 ;;
	esac
	case "/$dir/" in
		*/./*|*/../*)
			printf "'%s' walks the tree with a . or .. segment\n" "$dir"
			return 1 ;;
	esac
	if command -v git >/dev/null 2>&1 \
		&& git rev-parse --is-inside-work-tree >/dev/null 2>&1 \
		&& [ -n "$(git ls-files -- "$dir" 2>/dev/null | head -1)" ]; then
		printf "'%s' holds files git tracks — it is the repo's, not a report directory\n" "$dir"
		return 1
	fi
	return 0
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
		_gdk_snapshot_project_file
		return 0
	fi

	local runs="$PWD/$GDK_SANDBOX_DIRNAME/$GDK_SANDBOX_RUNS_SUBDIR"
	mkdir -p "$runs"
	_gdk_reap_stale_run_homes "$runs"

	# The pid is in the name on purpose: it is how the reaper tells a CONCURRENT
	# run's live HOME (never touch) from one a killed run abandoned.
	_GDK_RUN_HOME="$(mktemp -d "$runs/$GDK_SANDBOX_RUN_PREFIX$$-XXXXXX")"
	HOME="$_GDK_RUN_HOME"
	export HOME
	# Order matters: the project-file restore reads a snapshot that lives in
	# this HOME, so its hook must be registered — and therefore run — BEFORE
	# the home's self-destruct hook. Hooks run in registration order.
	_gdk_snapshot_project_file
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

# --- project.godot auto-restore ---------------------------------------------
# A headless EDITOR pass (an import-cache rebuild, a screenshot capture, an
# editor session) re-serializes project.godot with no semantic change — same
# keys, reflowed. Every agent then reverts it by hand before committing, and
# the ones who forget ship the churn. So a run that produced ONLY
# re-serialization undoes it itself.
#
# The test is deliberately conservative and one-directional: restore only when
# the file's NORMALIZED content is unchanged — i.e. nothing but whitespace,
# comments and SECTION order moved. Anything that changed a key, a value, or
# the order of keys WITHIN a section is a deliberate edit, or an engine change
# worth seeing, and is LEFT ALONE and reported. The helper can therefore lose
# formatting churn and never work.
#
# The normalization is section-aware and order-preserving inside each section,
# because a flat `sort` of the whole file cannot tell a reorder from a reflow:
# `[autoload] A, B` rewritten as `B, A` normalized identically, so the restore
# reverted it — and autoload order IS load order. A key moved from one section
# to another normalized identically too, and that changes what the key means.
# Each line is therefore keyed by (its section, its index in that section) and
# only those keys are sorted, so section ORDER is still free to move.
#
# Armed by gdk_sandbox_home so no wrapper can opt out by forgetting; callable
# directly (import_cache.sh) so a churn report is already accurate when printed.
GDK_PROJECT_FILE="${GDK_PROJECT_FILE:-project.godot}"

_gdk_normalize_project_file() {
	awk '
		/^[[:space:]]*(;|$)/ { next }
		/^\[.*\][[:space:]]*$/ { section = $0; index_in = 0; print section "\t000000"; next }
		{ index_in += 1; printf "%s\t%06d\t%s\n", section, index_in, $0 }
	' "$1" 2>/dev/null | sort
}

# gdk_restore_project_file — idempotent; silent when the run left the file
# alone (the overwhelmingly common case), one line otherwise.
# shellcheck disable=SC2329  # invoked indirectly via gdk_on_exit
gdk_restore_project_file() {
	local snapshot="${_GDK_PROJECT_SNAPSHOT:-}"
	[ -n "$snapshot" ] || return 0
	# The ABSOLUTE path resolved when the snapshot was taken, never the
	# cwd-relative GDK_PROJECT_FILE: a wrapper that cd's between the sandbox
	# call and its exit would otherwise find nothing there and drop the restore
	# in silence.
	local target="${_GDK_PROJECT_TARGET:-$GDK_PROJECT_FILE}"
	_GDK_PROJECT_SNAPSHOT=""
	_GDK_PROJECT_TARGET=""
	if [ ! -e "$snapshot" ] || [ ! -e "$target" ]; then
		rm -f "$snapshot"
		return 0
	fi
	if cmp -s "$snapshot" "$target"; then
		rm -f "$snapshot"
		return 0
	fi
	if diff -q \
			<(_gdk_normalize_project_file "$snapshot") \
			<(_gdk_normalize_project_file "$target") >/dev/null 2>&1; then
		cp "$snapshot" "$target"
		echo "$GDK_LIB_TAG: restored $target (engine re-serialization, no semantic change)"
	else
		echo "$GDK_LIB_TAG: $target changed BEYOND re-serialization — left alone, review it"
	fi
	rm -f "$snapshot"
}

# _gdk_snapshot_project_file — take the pre-run copy the restore compares
# against. It lives INSIDE the sandbox HOME, so it leaves nothing behind and a
# SIGKILLed run's copy dies with the home it could no longer restore from.
_gdk_snapshot_project_file() {
	[ -e "$GDK_PROJECT_FILE" ] || return 0
	[ -z "${_GDK_PROJECT_SNAPSHOT:-}" ] || return 0
	# Pin the target now, absolute. GDK_PROJECT_FILE is cwd-relative by
	# default, and the restore runs at EXIT — by which time a wrapper may have
	# cd'd somewhere else entirely.
	_GDK_PROJECT_TARGET="$(cd "$(dirname "$GDK_PROJECT_FILE")" >/dev/null 2>&1 \
		&& pwd)/$(basename "$GDK_PROJECT_FILE")" || return 0
	_GDK_PROJECT_SNAPSHOT="$(mktemp "$HOME/project-godot.XXXXXX")" || return 0
	cp "$GDK_PROJECT_FILE" "$_GDK_PROJECT_SNAPSHOT"
	gdk_on_exit gdk_restore_project_file
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

# gdk_timeout_is_hang <exit_code> — true if the code is a timeout kill. A
# piped engine capture reads PIPESTATUS itself and cannot use gdk_run_bounded;
# this is how it tells a HANG from a failing gate without respelling the codes.
gdk_timeout_is_hang() {
	local code="${1:?usage: gdk_timeout_is_hang <exit_code>}"
	[ "$code" -eq "$GDK_EXIT_SIGTERM_TIMEOUT" ] || [ "$code" -eq "$GDK_EXIT_SIGKILL_TIMEOUT" ]
}

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
#
# errexit is suspended around the pipeline and restored after. A wrapper under
# `set -euo pipefail` used to die ON this line: pipefail makes the pipeline's
# status the failing command's, `-e` then kills the shell, and GDK_GATE_EXIT is
# never read — the gate exited 3 having printed no verdict at all. Suspending
# is the only shape that keeps PIPESTATUS readable; `|| true` and `if …; then
# :; fi` both run a further simple command, which RESETS PIPESTATUS to (0) and
# would report every gate as passing.
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
	[ "$errexit_was_set" -eq 0 ] || set -e
	return 0
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
			"$GDK_GODOT" --path . --headless --editor --quit >/dev/null 2>&1 || true
		return 0
	fi
	# No timeout binary. This is best-effort recovery, so it still runs — but
	# it runs UNBOUNDED, and a caller that printed "up to ${secs}s" would be
	# stating a bound nothing enforces. gdk_run_bounded REFUSES in the same
	# situation; the difference is deliberate and is why this says it out loud.
	echo "$GDK_LIB_TAG: no timeout/gtimeout on PATH — the import pass runs UNBOUNDED" >&2
	"$GDK_GODOT" --path . --headless --editor --quit >/dev/null 2>&1 || true
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
	local scratch verdict log body status hung runs dead live lib
	# Resolved BEFORE the cd below: the sub-shell cases re-source the library
	# from a different working directory.
	lib="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/$(basename "${BASH_SOURCE[0]}")"
	scratch="$(mktemp -d "${TMPDIR:-/tmp}/gdk-runners-selftest.XXXXXX")" || return 1
	cd "$scratch" || return 1
	# The corpus proves BOTH settings, each pinned on its own case; the value
	# the caller happens to export is not part of it. Left to inherit, a
	# `make runners-self-test VERBOSE=1` — what the installed CI exports for
	# the whole run — streamed the cap case's eight bytes straight into this
	# corpus's own verdict line (`01234567[gdk-runners] SELF-TEST OK …`).
	VERBOSE=0
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

	# --- capture survives a wrapper under `set -euo pipefail` ----------------
	# pipefail + errexit used to kill the wrapper ON the capture line: no
	# verdict, exit 3, and VERBOSE=1 showing only the stream.
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
	# `env … bash -c`, never `( GDK_LOG_CAP_BYTES=8; … )`. A subshell
	# ASSIGNMENT to a name the library also publishes makes `shellcheck -x`
	# raise SC2031 at every CONSUMER site that reads that name — the consumer's
	# own lint reddens on a line the library wrote, and the only local repair
	# is a disable comment in a file whose author did nothing wrong. Scoping
	# the value to a child process says the same thing with no such shadow.
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

	# --- the reaper: a dead run's HOME goes, a live one's never does ---------
	runs="$scratch/$GDK_SANDBOX_DIRNAME/$GDK_SANDBOX_RUNS_SUBDIR"
	# 4194304 is above every platform's pid ceiling, so it is reliably dead —
	# a recycled pid would make this case flap instead of prove anything.
	dead="$runs/${GDK_SANDBOX_RUN_PREFIX}4194304-dead"
	live="$runs/$GDK_SANDBOX_RUN_PREFIX$$-live"
	mkdir -p "$dead" "$live" "$runs/${GDK_SANDBOX_RUN_PREFIX}notapid-x"
	_gdk_reap_stale_run_homes "$runs"
	status=0; [ ! -d "$dead" ] || status=1
	_gdk_st_true 'reap removes the HOME of a process that is gone' "$status"
	status=0; [ -d "$live" ] || status=1
	_gdk_st_true 'reap never touches a CONCURRENT run home' "$status"
	status=0; [ -d "$runs/${GDK_SANDBOX_RUN_PREFIX}notapid-x" ] || status=1
	_gdk_st_true 'reap leaves a directory carrying no pid alone' "$status"

	# pid 1 is alive and belongs to root: `kill -0` on it returns EPERM for an
	# ordinary user, which a liveness probe must not read as death. Same shape
	# as a peer's run home in a checkout two accounts share.
	status=0; gdk_pid_is_live 1 || status=1
	_gdk_st_true 'a live pid this user cannot signal is still live' "$status"
	mkdir -p "$runs/${GDK_SANDBOX_RUN_PREFIX}1-foreign"
	_gdk_reap_stale_run_homes "$runs"
	status=0; [ -d "$runs/${GDK_SANDBOX_RUN_PREFIX}1-foreign" ] || status=1
	_gdk_st_true 'reap never touches a live home owned by another user' "$status"

	# --- the rebuild says so when it cannot be bounded -----------------------
	mkdir -p "$scratch/stub-bin"
	printf '#!/bin/sh\nexit 0\n' > "$scratch/stub-bin/godot"
	chmod +x "$scratch/stub-bin/godot"
	body="$( PATH="$scratch/stub-bin:$PATH" GDK_TIMEOUT='' GDK_GODOT='godot' \
		gdk_rebuild_import_cache 5 2>&1 )"
	case "$body" in
		*UNBOUNDED*) status=0 ;;
		*) status=1; printf '  MISS — an unbounded rebuild said nothing: %s\n' "$body" >&2 ;;
	esac
	_gdk_st_true 'rebuild_import_cache warns when nothing can bound it' "$status"

	# --- gdk_timeout_is_hang: only the two timeout codes are a hang ----------
	status=0; gdk_timeout_is_hang "$GDK_EXIT_SIGTERM_TIMEOUT" || status=1
	_gdk_st_true 'timeout_is_hang recognises 124' "$status"
	status=0; gdk_timeout_is_hang "$GDK_EXIT_SIGKILL_TIMEOUT" || status=1
	_gdk_st_true 'timeout_is_hang recognises 137' "$status"
	status=0; gdk_timeout_is_hang 1 && status=1
	_gdk_st_true 'a failing gate (exit 1) is NOT a hang' "$status"
	status=0; gdk_timeout_is_hang 0 && status=1
	_gdk_st_true 'a passing gate (exit 0) is NOT a hang' "$status"

	# --- project.godot: re-serialization comes back, a real edit does not ----
	# The three outcomes, each proven separately, because the whole value of
	# this helper is that it can lose formatting churn and never work.
	printf '; a comment\n\n[application]\nconfig/name="x"\nrun/main_scene="y"\n\n[debug]\nsettings/stdout/verbose=true\n' \
		> "$scratch/project.godot"
	# shellcheck disable=SC2016  # $1/$2 are the CHILD shell's positionals
	env GDK_PROJECT_FILE="$scratch/project.godot" HOME="$scratch" bash -c '
		# shellcheck source=/dev/null
		source "$1"
		body="$(_gdk_snapshot_project_file; gdk_restore_project_file)"
		[ -z "$body" ] || { printf "  MISS — restore spoke about an untouched file: %s\n" "$body" >&2; exit 1; }
	' _ "$lib"
	_gdk_st_true 'restore is silent when the run left the file alone' "$?"

	# Same keys, same values, same order WITHIN each section: the comment is
	# gone, the blank lines are gone and the sections swapped. Pure churn.
	# shellcheck disable=SC2016  # $1/$2 are the CHILD shell's positionals
	env GDK_PROJECT_FILE="$scratch/project.godot" HOME="$scratch" bash -c '
		# shellcheck source=/dev/null
		source "$1"
		_gdk_snapshot_project_file
		printf "[debug]\nsettings/stdout/verbose=true\n[application]\nconfig/name=\"x\"\nrun/main_scene=\"y\"\n" \
			> "$GDK_PROJECT_FILE"
		body="$(gdk_restore_project_file)"
		case "$body" in *restored*) ;; *) printf "  MISS — churn was not reported as restored: %s\n" "$body" >&2; exit 1 ;; esac
		grep -q "^; a comment$" "$GDK_PROJECT_FILE" || { echo "  MISS — the file did not come back" >&2; exit 1; }
	' _ "$lib"
	_gdk_st_true 'restore undoes a pure re-serialization and says so' "$?"

	# shellcheck disable=SC2016  # $1/$2 are the CHILD shell's positionals
	env GDK_PROJECT_FILE="$scratch/project.godot" HOME="$scratch" bash -c '
		# shellcheck source=/dev/null
		source "$1"
		_gdk_snapshot_project_file
		printf "; a comment\n\n[application]\nconfig/name=\"CHANGED\"\nrun/main_scene=\"y\"\n\n[debug]\nsettings/stdout/verbose=true\n" \
			> "$GDK_PROJECT_FILE"
		body="$(gdk_restore_project_file)"
		case "$body" in *"BEYOND re-serialization"*) ;; *) printf "  MISS — a real edit was not reported: %s\n" "$body" >&2; exit 1 ;; esac
		grep -q CHANGED "$GDK_PROJECT_FILE" || { echo "  MISS — a real edit was CLOBBERED by the restore" >&2; exit 1; }
	' _ "$lib"
	_gdk_st_true 'restore leaves a deliberate edit alone and says so' "$?"

	# A REORDER inside one section is not re-serialization: [autoload] order is
	# load order. A flat sort of the whole file could not tell the two apart.
	printf '[autoload]\nA="*res://a.gd"\nB="*res://b.gd"\n' > "$scratch/project.godot"
	# shellcheck disable=SC2016  # $1/$2 are the CHILD shell's positionals
	env GDK_PROJECT_FILE="$scratch/project.godot" HOME="$scratch" bash -c '
		# shellcheck source=/dev/null
		source "$1"
		_gdk_snapshot_project_file
		printf "[autoload]\nB=\"*res://b.gd\"\nA=\"*res://a.gd\"\n" > "$GDK_PROJECT_FILE"
		body="$(gdk_restore_project_file)"
		case "$body" in *"BEYOND re-serialization"*) ;; *) printf "  MISS — a within-section REORDER was treated as churn: %s\n" "$body" >&2; exit 1 ;; esac
		head -2 "$GDK_PROJECT_FILE" | tail -1 | grep -q "^B=" || { echo "  MISS — a within-section reorder was CLOBBERED" >&2; exit 1; }
	' _ "$lib"
	_gdk_st_true 'restore leaves a reorder inside a section alone' "$?"

	# The same line under a DIFFERENT section is a different fact.
	printf '[autoload]\nA="*res://a.gd"\n[debug]\n' > "$scratch/project.godot"
	# shellcheck disable=SC2016  # $1/$2 are the CHILD shell's positionals
	env GDK_PROJECT_FILE="$scratch/project.godot" HOME="$scratch" bash -c '
		# shellcheck source=/dev/null
		source "$1"
		_gdk_snapshot_project_file
		printf "[autoload]\n[debug]\nA=\"*res://a.gd\"\n" > "$GDK_PROJECT_FILE"
		body="$(gdk_restore_project_file)"
		case "$body" in *"BEYOND re-serialization"*) ;; *) printf "  MISS — a key moved between sections was treated as churn: %s\n" "$body" >&2; exit 1 ;; esac
	' _ "$lib"
	_gdk_st_true 'restore leaves a key moved between sections alone' "$?"

	# The restore target is pinned ABSOLUTE at snapshot time, so a wrapper that
	# cd's mid-run still restores rather than silently finding nothing there.
	printf '; c\nconfig/name="x"\n' > "$scratch/project.godot"
	# shellcheck disable=SC2016  # $1/$2 are the CHILD shell's positionals
	env GDK_PROJECT_FILE="project.godot" HOME="$scratch" bash -c '
		cd "$2" || exit 1
		# shellcheck source=/dev/null
		source "$1"
		_gdk_snapshot_project_file
		printf "config/name=\"x\"\n; c\n" > "$2/project.godot"
		cd / || exit 1
		body="$(gdk_restore_project_file)"
		case "$body" in *restored*) ;; *) printf "  MISS — a cd mid-run dropped the restore: %s\n" "$body" >&2; exit 1 ;; esac
		head -1 "$2/project.godot" | grep -q "^; c$" || { echo "  MISS — the file did not come back after a cd" >&2; exit 1; }
	' _ "$lib" "$scratch"
	_gdk_st_true 'restore survives a wrapper that cd s between snapshot and exit' "$?"

	# --- and the two are wired: sandbox_home arms the restore ----------------
	# The hook ORDER is the load-bearing part — the snapshot lives inside the
	# run HOME, so a restore registered after the self-destruct reads a file
	# that is already gone.
	( cd "$scratch" || exit 1
	  printf '; c\n[application]\nconfig/name="x"\nrun/main_scene="y"\n' > project.godot
	  ( gdk_sandbox_home
	    printf '\n[application]\n\nconfig/name="x"\nrun/main_scene="y"\n' > project.godot ) >/dev/null
	  head -1 project.godot | grep -q '^; c$' || { echo '  MISS — sandbox_home did not arm the project-file restore' >&2; exit 1; } )
	_gdk_st_true 'sandbox_home arms the restore, and it runs before the home dies' "$?"

	# --- the destroy guard refuses a HOME it did not mint --------------------
	_GDK_RUN_HOME="$scratch/not-a-sandbox"
	mkdir -p "$_GDK_RUN_HOME"
	_gdk_destroy_run_home 2>/dev/null
	status=0; [ -d "$scratch/not-a-sandbox" ] || status=1
	_gdk_st_true 'destroy refuses a path outside the sandbox layout' "$status"

	# --- the report-dir guard: what a runner may aim rm -rf at --------------
	# The two shapes that actually happened get their own cases; the rest are
	# the grammar the same misconfiguration can be spelled in.
	local bad
	# The literal `~` is the case, not a mistake: a config VALUE is not
	# tilde-expanded by the shell that reads it, so what reaches the guard
	# is the character.
	# shellcheck disable=SC2088
	for bad in '' '.' '..' './x' '../x' 'a/../b' '/tmp/x' '~/x'; do
		status=1; gdk_report_dir_defect "$bad" >/dev/null || status=0
		_gdk_st_true "report_dir_defect refuses '$bad'" "$status"
	done
	status=0; gdk_report_dir_defect '.scenario-reports' >/dev/null || status=1
	_gdk_st_true 'report_dir_defect admits an ordinary report dir' "$status"

	# A directory the repo keeps TRACKED content in is the repo's, whatever
	# the config says. `GDK_CAPTURE_REPORT_DIR=tests` emptied tests/.
	( cd "$scratch" || exit 1
	  git init -q . >/dev/null 2>&1 || exit 0    # no git: the clause is skipped
	  mkdir -p tracked
	  : > tracked/keep.txt
	  git add tracked/keep.txt >/dev/null 2>&1 || exit 0
	  gdk_report_dir_defect tracked >/dev/null && exit 1
	  gdk_report_dir_defect .scenario-reports >/dev/null || exit 1
	  exit 0 )
	_gdk_st_true 'report_dir_defect refuses a directory git tracks files in' "$?"

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
gdk_pid_is_live, gdk_report_dir_defect, gdk_run_bounded, gdk_timeout_is_hang,
gdk_restore_project_file, gdk_gate_log, gdk_gate_capture, gdk_gate_publish,
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
