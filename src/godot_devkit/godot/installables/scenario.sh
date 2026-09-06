#!/usr/bin/env bash
# scenario.sh — boot the project headless and hand control to ONE integration
# scenario. The single-scenario entry point; integration.sh fans this out.
#
# The bare `--` separator before the user arguments is load-bearing: it is what
# makes Godot treat the trailing arguments as USER args, visible through
# OS.get_cmdline_user_args(). Your scenario runner reads them.
#
# Usage:
#   tools/dev/runners/scenario.sh [--verbose|-v] <scenario_name>
#   tools/dev/runners/scenario.sh --help | --self-test
#
# OUTPUT: the full transcript is ALWAYS published to
# .scenario-reports/<name>.log — written to a private per-run file first, then
# moved onto that path at exit, so concurrent runs cannot splice each other's
# output. The console gets the runner's own one-line result; on a non-PASS it
# additionally prints the failed-assertion lines, any unexpected engine errors,
# and a pointer to the report. Drill into a failure by reading the report, never
# by re-running. `--verbose` streams the whole transcript.
#
# TWO LAYERS OF ERROR CAPTURE. Your in-process scenario runner sees your own
# logging; it cannot see engine-level output. So this wrapper additionally reads
# the stream for GDScript runtime errors, native push_error/push_warning, and
# engine-emitted ERROR/WARNING lines, filtered through the same noise allowlist.
# A scenario that reports PASS while the engine was shouting is upgraded to
# FAIL: a silent engine error is the bug class this layer exists for.
#
# Exit: 0 passed and the engine was quiet | 1 failed | 2 harness/usage error
#       | 3 hard timeout (a hang)
set -uo pipefail

# --- project config (yours to edit after install — the file is your repo's) --
GDK_RUNNERS_LIB="${GDK_RUNNERS_LIB:-../gdk_runners.sh}"
REPO_ROOT_FROM_HERE="../../.."
# Where scenario source lives, and where transcripts land. Gitignore the
# report dir.
GDK_SCENARIO_SOURCE_DIR="${GDK_SCENARIO_SOURCE_DIR:-tests/integration}"
GDK_SCENARIO_REPORT_DIR="${GDK_SCENARIO_REPORT_DIR:-.scenario-reports}"
# Engine-level lines your scenarios legitimately produce, one POSIX ERE per
# line, `#` comments allowed. A MISSING file means "allow nothing", which is
# the strict direction.
GDK_SCENARIO_NOISE_ALLOWLIST="${GDK_SCENARIO_NOISE_ALLOWLIST:-tests/integration/noise_allowlist.txt}"
# The user argument your scenario runner reads the name from.
GDK_SCENARIO_USER_ARG="${GDK_SCENARIO_USER_ARG:---scenario}"
# How your runner spells its own verdict line, as an ERE.
GDK_SCENARIO_RESULT_RE="${GDK_SCENARIO_RESULT_RE:-\[SCENARIO\]}"
# A transcript is evidence about the tree AS IT WAS WHEN IT RAN. Past this many
# days it is archaeology that reads as current, and any run reaps it.
GDK_REPORT_RETENTION_DAYS="${GDK_REPORT_RETENTION_DAYS:-7}"
# Env: GDK_SCENARIO_HARD_TIMEOUT  seconds bounding one scenario (default 60)
#      GDK_GODOT                  the engine binary (default `godot`)
#      GDK_SCENARIO_IN_SWEEP      set by integration.sh: this run has PEERS
#                                 booting in the same tree, so the cache
#                                 recovery below reports its last remedy
#                                 instead of performing it on them.
# -----------------------------------------------------------------------------

GATE_TAG="SCENARIO"
HARD_TIMEOUT_SECONDS="${GDK_SCENARIO_HARD_TIMEOUT:-60}"

# Engine-level prefixes Godot uses when something goes wrong. Each alternative
# is anchored to start-of-line so an allowlisted word appearing mid-sentence in
# an ordinary log line cannot pose as an error.
ENGINE_ERROR_PATTERN='^(SCRIPT ERROR|SCRIPT WARNING|USER ERROR|USER WARNING|ERROR|WARNING): '
# A cold/stale import cache makes the engine warn about a uid and re-stamp it.
# On an otherwise PASSING run that is a cache problem, not a scenario problem.
COLD_CACHE_PATTERN='invalid UID.*using text path instead'
FAILED_ASSERTION_PATTERN='\[fail\]'
# The engine's import cache, which the recovery below may REMOVE. A literal,
# never a configurable: it is the argument to an `rm -rf` inside a directory
# holding somebody's project, and a name that can be set from outside is a name
# that can be aimed.
IMPORT_DIR=".godot"

usage() {
	cat <<'USAGE_EOF'
usage: scenario.sh [--verbose|-v] <scenario_name>
       scenario.sh --help | --self-test

Boots the project headless in a sandboxed HOME and runs ONE scenario, reading
the engine's own stream for errors your in-process runner cannot see.

  --verbose|-v  stream the whole transcript to the console
  --self-test   prove the argument handling, the report-freshness rules, the
                allowlist builder and what the cache recovery fires on,
                booting nothing
  --help        this message

Env: GDK_SCENARIO_SOURCE_DIR       where scenario scripts live
     GDK_SCENARIO_REPORT_DIR       where transcripts land (gitignore it)
     GDK_SCENARIO_NOISE_ALLOWLIST  EREs for engine lines you expect
     GDK_SCENARIO_USER_ARG         the user arg carrying the scenario name
     GDK_SCENARIO_RESULT_RE        how your runner spells its verdict line
     GDK_SCENARIO_HARD_TIMEOUT     seconds bounding the run (default 60)
     GDK_SCENARIO_IN_SWEEP         this run has peers in the same tree
     GDK_REPORT_RETENTION_DAYS     transcript retention (default 7)
     GDK_RUNNERS_LIB               path to gdk_runners.sh, relative to this file
     GDK_GODOT                     the engine binary (default `godot`)
Exit: 0 pass | 1 fail | 2 harness/usage error | 3 hard timeout
USAGE_EOF
}

# resolve_library — echo the gdk_runners.sh this runner sources, or return 1.
# GDK_RUNNERS_LIB first (the installed layout: this file in runners/, the
# library one level up), then a sibling — which is where the library sits in
# the package's own source tree and in any consumer that keeps its shell tools
# in one directory. Both the run and the --self-test resolve through here, so
# the corpus can never exercise a different library than the gate does.
resolve_library() {
	local here
	here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)" || return 1
	if [ -f "$here/$GDK_RUNNERS_LIB" ]; then
		printf '%s\n' "$here/$GDK_RUNNERS_LIB"
		return 0
	fi
	[ -f "$here/gdk_runners.sh" ] || return 1
	printf '%s\n' "$here/gdk_runners.sh"
}

# --- report freshness --------------------------------------------------------
# Two rules, and between them a log on disk is ALWAYS the latest run of that
# scenario:
#   1. a run owns its own slot: it clears the one file it is about to write,
#      and never the directory. A sweep runs ~140 of these in parallel, so
#      clearing the directory would delete the evidence a developer is halfway
#      through reading — and a typo'd name would destroy a real transcript.
#   2. anything NO run can refresh is residue and gets reaped: a log for a
#      scenario that no longer exists, a transcript past the retention window,
#      or an in-flight transcript abandoned by a killed run.
# Without rule 2 a consumer's directory reached 548 logs / 31 MB, 396 of them
# for scenarios long deleted — and a stale log read as current is a lie.

# report_temp_template <scenario> — the in-flight transcript name,
# `.<scenario>.<pid>.XXXXXX`. The pid is load-bearing: it is how the reaper
# tells a CONCURRENT peer's live transcript (never touch) from one a killed run
# abandoned. Same device as the library's run-home names.
report_temp_template() {
	printf '.%s.%s.XXXXXX\n' "${1:?usage: report_temp_template <scenario>}" "$$"
}

# report_temp_pid <basename> — the pid encoded in an in-flight transcript name,
# or nothing when the name carries none.
report_temp_pid() {
	local rest="${1#.}"
	rest="${rest#*.}"
	local pid="${rest%%.*}"
	case "$pid" in ''|*[!0-9]*) return 1 ;; esac
	printf '%s\n' "$pid"
}

# stale_scenario_reports <dir> <live names> — print every entry no run can
# refresh, one path per line. Pure read over a directory and a name list, so
# the self-test can fire it at fixtures.
stale_scenario_reports() {
	local dir="${1:?usage: stale_scenario_reports <dir> <live names>}"
	local live="${2-}"
	[ -d "$dir" ] || return 0
	local aged entry base stem pid
	aged="$(find "$dir" -maxdepth 1 -mtime "+$GDK_REPORT_RETENTION_DAYS" 2>/dev/null)"
	for entry in "$dir"/* "$dir"/.[!.]*; do
		[ -e "$entry" ] || continue
		base="${entry##*/}"
		if [ "${base#.}" != "$base" ]; then
			# An in-flight transcript: alive means a peer is writing it NOW.
			if pid="$(report_temp_pid "$base")" && gdk_pid_is_live "$pid"; then
				continue
			fi
			printf '%s\n' "$entry"
			continue
		fi
		case "$base" in
			*.log) stem="${base%.log}" ;;
			*) printf '%s\n' "$entry"; continue ;;
		esac
		if ! printf '%s\n' "$live" | grep -qxF -- "$stem"; then
			printf '%s\n' "$entry"
			continue
		fi
		case $'\n'"$aged"$'\n' in
			*$'\n'"$entry"$'\n'*) printf '%s\n' "$entry" ;;
		esac
	done
}

# live_scenario_names — every scenario the source tree can still produce.
live_scenario_names() {
	find "$GDK_SCENARIO_SOURCE_DIR" -type f -name '*.gd' 2>/dev/null \
		| sed 's|.*/||; s|\.gd$||'
}

# reap_stale_scenario_reports <dir> — rule 2, applied. Called by EVERY run, so
# any entry point heals the directory and no future runner can opt out by
# forgetting.
reap_stale_scenario_reports() {
	local dir="${1:?usage: reap_stale_scenario_reports <dir>}" entry live
	live="$(live_scenario_names)"
	while IFS= read -r entry; do
		[ -n "$entry" ] || continue
		# Only ever inside the report dir. That is half the claim; the other
		# half is that the DIR itself is one this runner may own, which is
		# `gdk_report_dir_defect`'s answer at the call site below — this case
		# held perfectly while `dir` was `.`, and the tree went with it.
		case "$entry" in
			"$dir"/*) rm -rf "$entry" ;;
			*) echo "$GATE_TAG: refusing to reap non-report path '$entry'" >&2 ;;
		esac
	done < <(stale_scenario_reports "$dir" "$live")
}

# --- the import-cache recovery's one question --------------------------------
# cold_cache_only <report> <engine exit> — true when this transcript says the
# tree is what is broken and the scenario is not: it carries the uid class, the
# scenario reported its own PASS, and the run did not hang. Pure over its two
# arguments so the corpus can fire it at fake transcripts — the conjunct that
# refuses to retry a REAL failure is the one worth proving.
cold_cache_only() {
	local report="${1:?usage: cold_cache_only <report> <engine exit>}"
	local code="${2:?usage: cold_cache_only <report> <engine exit>}"
	grep -qE "$COLD_CACHE_PATTERN" "$report" \
		&& grep -qE "$GDK_SCENARIO_RESULT_RE.*PASS" "$report" \
		&& ! gdk_timeout_is_hang "$code"
}

# allowlist_regex <file> — OR-join every non-blank, non-comment entry. EMPTY
# output means "reject every engine-level hit", which is what a missing file
# must also mean: a filter that cannot be read has to be strict, never absent.
allowlist_regex() {
	[ -f "$1" ] || return 0
	grep -vE '^[[:space:]]*($|#)' "$1" | tr '\n' '|' | sed 's/|$//'
}

# --- --self-test -------------------------------------------------------------
self_test() {
	local scratch rc out lib failures=0 cases=0

	# The freshness rules turn on a pid liveness probe the library owns, so
	# the corpus sources it rather than re-deciding what "alive" means.
	if ! lib="$(resolve_library)"; then
		echo "  MISS — gdk_runners.sh not found; set GDK_RUNNERS_LIB" >&2
		return 1
	fi
	# shellcheck source=/dev/null
	source "$lib"

	cases=$((cases + 1))
	rc=0; bash "$0" --help >/dev/null 2>&1 || rc=$?
	[ "$rc" -eq 0 ] || { echo "  MISS — --help should exit 0, got $rc" >&2; failures=$((failures + 1)); }

	cases=$((cases + 1))
	rc=0; bash "$0" >/dev/null 2>&1 || rc=$?
	[ "$rc" -eq 2 ] || { echo "  MISS — no scenario name should exit 2, got $rc" >&2; failures=$((failures + 1)); }

	cases=$((cases + 1))
	rc=0; bash "$0" --nope >/dev/null 2>&1 || rc=$?
	[ "$rc" -eq 2 ] || { echo "  MISS — an unknown flag should exit 2, got $rc" >&2; failures=$((failures + 1)); }

	cases=$((cases + 1))
	rc=0; bash "$0" '' >/dev/null 2>&1 || rc=$?
	[ "$rc" -eq 2 ] || { echo "  MISS — an EMPTY name should exit 2, got $rc" >&2; failures=$((failures + 1)); }

	cases=$((cases + 1))
	rc=0; bash "$0" a b >/dev/null 2>&1 || rc=$?
	[ "$rc" -eq 2 ] || { echo "  MISS — two scenario names should exit 2, got $rc" >&2; failures=$((failures + 1)); }

	# A scenario NAME is a name, never a path — it becomes a report file and a
	# user argument, and `../../etc/passwd` must reach neither.
	cases=$((cases + 1))
	rc=0; bash "$0" ../escape >/dev/null 2>&1 || rc=$?
	[ "$rc" -eq 2 ] || { echo "  MISS — a name carrying a separator should exit 2, got $rc" >&2; failures=$((failures + 1)); }

	# --- the in-flight name and its pid -------------------------------------
	cases=$((cases + 1))
	out="$(report_temp_template boot_smoke)"
	[ "$out" = ".boot_smoke.$$.XXXXXX" ] \
		|| { echo "  MISS — the in-flight template, got '$out'" >&2; failures=$((failures + 1)); }

	cases=$((cases + 1))
	out="$(report_temp_pid ".boot_smoke.4242.ab12cd")"
	[ "$out" = "4242" ] \
		|| { echo "  MISS — the pid must come back out of the name, got '$out'" >&2; failures=$((failures + 1)); }

	cases=$((cases + 1))
	rc=0; report_temp_pid ".no_pid_here" >/dev/null || rc=$?
	[ "$rc" -ne 0 ] \
		|| { echo "  MISS — a name carrying no pid must not yield one" >&2; failures=$((failures + 1)); }

	# --- the freshness rules ------------------------------------------------
	scratch="$(mktemp -d "${TMPDIR:-/tmp}/gdk-scenario-selftest.XXXXXX")" || return 1
	: > "$scratch/alive.log"          # a scenario that still exists
	: > "$scratch/deleted.log"        # one whose source is gone
	: > "$scratch/notalog.txt"        # not a transcript at all
	: > "$scratch/.alive.4194304.aa"  # in-flight, owner long dead
	: > "$scratch/.alive.$$.bb"       # in-flight, THIS process: a live peer

	out="$(stale_scenario_reports "$scratch" "alive" | sed "s|$scratch/||" | sort | tr '\n' ' ')"
	cases=$((cases + 1))
	[ "$out" = ".alive.4194304.aa deleted.log notalog.txt " ] \
		|| { echo "  MISS — the stale set, got '$out'" >&2; failures=$((failures + 1)); }

	cases=$((cases + 1))
	printf '%s\n' "$out" | grep -q "alive.log" \
		&& { echo "  MISS — a LIVE scenario's transcript was called stale" >&2; failures=$((failures + 1)); }

	# The pid is what protects a peer mid-write. Without it a parallel sweep
	# deletes its own siblings' transcripts as it goes.
	cases=$((cases + 1))
	printf '%s\n' "$out" | grep -q "\.alive\.$$\." \
		&& { echo "  MISS — a CONCURRENT run's in-flight transcript was called stale" >&2; failures=$((failures + 1)); }

	# The reaper only ever deletes INSIDE the directory it was given. Fed a
	# path from outside it, it must refuse aloud and delete nothing — a
	# mis-set report dir must not be able to aim `rm -rf` at the tree.
	cases=$((cases + 1))
	: > "$scratch/outsider"
	out="$(GDK_SCENARIO_SOURCE_DIR="$scratch/no-such-source" \
		reap_stale_scenario_reports "$scratch/elsewhere" 2>&1)"
	[ -e "$scratch/outsider" ] \
		|| { echo "  MISS — the reaper deleted a path outside its directory" >&2; failures=$((failures + 1)); }
	[ -z "$out" ] \
		|| { echo "  MISS — reaping an absent directory said '$out'" >&2; failures=$((failures + 1)); }

	# --- the allowlist ------------------------------------------------------
	printf '# a comment\n\nWARNING: expected thing\nERROR: known\n' > "$scratch/allow.txt"
	cases=$((cases + 1))
	out="$(allowlist_regex "$scratch/allow.txt")"
	[ "$out" = "WARNING: expected thing|ERROR: known" ] \
		|| { echo "  MISS — the allowlist regex, got '$out'" >&2; failures=$((failures + 1)); }

	# A MISSING allowlist means allow NOTHING. An empty regex passed to `grep
	# -v` would match every line and silently allow every engine error there is
	# — the exact false PASS this layer exists to prevent, which is why the
	# caller branches on emptiness instead of interpolating.
	cases=$((cases + 1))
	out="$(allowlist_regex "$scratch/nope.txt")"
	[ -z "$out" ] \
		|| { echo "  MISS — a missing allowlist produced a filter: '$out'" >&2; failures=$((failures + 1)); }

	cases=$((cases + 1))
	printf '# only comments\n\n' > "$scratch/empty.txt"
	out="$(allowlist_regex "$scratch/empty.txt")"
	[ -z "$out" ] \
		|| { echo "  MISS — a comments-only allowlist produced '$out'" >&2; failures=$((failures + 1)); }

	# --- what the cache recovery is allowed to fire on ----------------------
	# Three conjuncts, one case each. Two of them are the ONLY thing standing
	# between a real failure and an engine reboot it cannot fix — and rung 2
	# of that ladder removes a directory.
	printf 'WARNING: invalid UID "uid://c" - using text path instead\n[SCENARIO] a PASS steps=1 errors=0\n' \
		> "$scratch/cold_pass.log"
	printf 'WARNING: invalid UID "uid://c" - using text path instead\n[SCENARIO] a FAIL steps=1 errors=2\n' \
		> "$scratch/cold_fail.log"
	printf '[SCENARIO] a PASS steps=1 errors=0\n' > "$scratch/clean_pass.log"

	cases=$((cases + 1))
	rc=0; cold_cache_only "$scratch/cold_pass.log" 0 || rc=$?
	[ "$rc" -eq 0 ] \
		|| { echo "  MISS — the uid class on a PASSING run is the recovery's case" >&2; failures=$((failures + 1)); }

	cases=$((cases + 1))
	rc=0; cold_cache_only "$scratch/cold_fail.log" 1 || rc=$?
	[ "$rc" -ne 0 ] \
		|| { echo "  MISS — a genuinely FAILING scenario must never be retried" >&2; failures=$((failures + 1)); }

	cases=$((cases + 1))
	rc=0; cold_cache_only "$scratch/clean_pass.log" 0 || rc=$?
	[ "$rc" -ne 0 ] \
		|| { echo "  MISS — a transcript with no uid class is not a cache problem" >&2; failures=$((failures + 1)); }

	cases=$((cases + 1))
	rc=0; cold_cache_only "$scratch/cold_pass.log" "$GDK_EXIT_SIGKILL_TIMEOUT" || rc=$?
	[ "$rc" -ne 0 ] \
		|| { echo "  MISS — a HUNG run's truncated transcript must not trigger a rebuild" >&2; failures=$((failures + 1)); }

	rm -rf "$scratch"

	if [ "$failures" -eq 0 ]; then
		echo "[$GATE_TAG] SELF-TEST OK — $cases case(s)"
		return 0
	fi
	echo "[$GATE_TAG] SELF-TEST FAIL — $failures of $cases case(s), see above" >&2
	return 1
}

# --- argument surface --------------------------------------------------------
VERBOSE_STREAM=0
case "${1:-}" in
	--help|-h)
		[ "$#" -eq 1 ] || { echo "[$GATE_TAG] --help takes no argument" >&2; exit 2; }
		usage; exit 0 ;;
	--self-test)
		[ "$#" -eq 1 ] || { echo "[$GATE_TAG] --self-test takes no argument. See --help." >&2; exit 2; }
		self_test_rc=0; self_test || self_test_rc=$?; exit "$self_test_rc" ;;
	-v|--verbose) VERBOSE_STREAM=1; shift ;;
esac
if [ "$#" -ne 1 ]; then
	echo "[$GATE_TAG] exactly one scenario name — got $#. See --help." >&2
	usage >&2
	exit 2
fi
SCENARIO_NAME="$1"
# The name becomes a FILE NAME and a user argument. An empty one is an unset
# variable at the call site; anything carrying a separator or a leading dash
# would aim the report write outside the report directory.
case "$SCENARIO_NAME" in
	''|*/*|.|..|-*)
		echo "[$GATE_TAG] '$SCENARIO_NAME' is not a scenario name. See --help." >&2
		exit 2 ;;
esac

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/$REPO_ROOT_FROM_HERE" && pwd)" || exit 2
if ! LIB="$(resolve_library)"; then
	echo "[$GATE_TAG] gdk_runners.sh not found beside this file or at" >&2
	echo "[$GATE_TAG] '$GDK_RUNNERS_LIB' relative to it — set GDK_RUNNERS_LIB" >&2
	exit 2
fi
cd "$REPO_ROOT" || exit 2

# shellcheck source=/dev/null
source "$LIB"

if [ ! -f "$GDK_PROJECT_FILE" ]; then
	echo "[$GATE_TAG] $REPO_ROOT is not a Godot project — no $GDK_PROJECT_FILE there." >&2
	exit 2
fi

# The report dir is a directory this runner CREATES, fills and reaps entries
# out of, so it is checked before it is used rather than trusted because it
# came from the config header. `GDK_SCENARIO_REPORT_DIR=.` deleted a probe repo
# whole, `.git` included, before the boot.
if REPORT_DIR_DEFECT="$(gdk_report_dir_defect "$GDK_SCENARIO_REPORT_DIR")"; then
	:
else
	echo "[$GATE_TAG] GDK_SCENARIO_REPORT_DIR $REPORT_DIR_DEFECT" >&2
	echo "[$GATE_TAG] nothing was read, written or removed. Set it to a" >&2
	echo "[$GATE_TAG] project-relative directory this runner may own." >&2
	exit 2
fi

REPORT_FILE="$GDK_SCENARIO_REPORT_DIR/$SCENARIO_NAME.log"
mkdir -p "$GDK_SCENARIO_REPORT_DIR"
reap_stale_scenario_reports "$GDK_SCENARIO_REPORT_DIR"
rm -f "$REPORT_FILE"

# The stable path is SHARED: two runs of the same scenario (a sweep alongside a
# hand run, two agents in one tree) interleave their writes into it, and the
# greps below then read a spliced transcript — which reported a false
# engine-error FAIL on a scenario that had printed PASS. So the run writes to a
# private file, every read is of THAT, and the stable path is published from it
# at exit, atomically. A publish can be stale; it can never be spliced.
RUN_REPORT="$(mktemp "$GDK_SCENARIO_REPORT_DIR/$(report_temp_template "$SCENARIO_NAME")")" || exit 2

# NEVER a bare `trap … EXIT` — it would clobber the sandbox home's self-destruct
# hook. The INT/TERM handlers just exit; bash runs the EXIT dispatcher on the
# way out, so the report still publishes.
gdk_on_exit "mv -f '$RUN_REPORT' '$REPORT_FILE' 2>/dev/null || rm -f '$RUN_REPORT'"
trap 'exit 130' INT
trap 'exit 143' TERM

# user:// sandbox — a scenario boots the project's whole autoload stack.
gdk_sandbox_home

# Boot the scenario once, capturing the transcript. A function so the
# cold-cache recovery below can re-run it without duplicating the plumbing.
run_scenario() {
	if [ "$VERBOSE_STREAM" -eq 1 ]; then
		gdk_run_bounded "$HARD_TIMEOUT_SECONDS" -- \
			"$GDK_GODOT" --path . --headless -- \
			"$GDK_SCENARIO_USER_ARG" "$SCENARIO_NAME" 2>&1 \
			| head -c "$GDK_LOG_CAP_BYTES" | tee "$RUN_REPORT"
	else
		gdk_run_bounded "$HARD_TIMEOUT_SECONDS" -- \
			"$GDK_GODOT" --path . --headless -- \
			"$GDK_SCENARIO_USER_ARG" "$SCENARIO_NAME" 2>&1 \
			| head -c "$GDK_LOG_CAP_BYTES" > "$RUN_REPORT"
	fi
	# head -c is the last pipe element and exits 0 — the engine's own code is
	# PIPESTATUS[0], exactly as gdk_gate_capture documents.
	godot_exit="${PIPESTATUS[0]}"
}

run_scenario

# --- import-cache auto-recovery: two rungs, then it is a real failure --------
# A cold/stale .godot makes the engine warn `invalid UID … using text path
# instead` and re-stamp the uid — noise that upgraded an otherwise-PASSING
# scenario to FAIL. When the report carries that class AND the scenario itself
# passed and did not hang, the run is healthy and the TREE is what is wrong.
#
# COLD and STALE are different defects with different remedies, which is why
# this escalates instead of retrying the same one:
#   cold  — .godot is absent, or has no entry for a file that is NEW. An import
#           pass against the existing directory mints it. Rung 1.
#   stale — the uid INDEX is missing entries for tracked files it already knew
#           about. The import pass does not rebuild those: measured three times
#           in a consumer, including once after deleting uid_cache.bin alone,
#           each run left 1780 entries and the same 56 missing. Removing the
#           directory and rebuilding gave 1822. Rung 2.
# Before the second rung existed, a stale tree cost every scenario a rebuild
# that could not work and a retry that re-failed: 147 of 147 green inside and
# red outside, 147 times.
#
# The ladder is two rungs of straight-line code, deliberately NOT a loop. A
# third failure is a real failure and stays fast — a retry re-evaluating its
# own condition would reboot the engine forever on a tree that is genuinely
# broken, and each reboot is an engine start plus an editor import.
#
# Rung 2 removes a directory a local editor owns, so it says so BEFORE it acts,
# and it declines inside a sweep: integration.sh runs N scenarios in ONE tree,
# and removing .godot under peers that are mid-boot converts one cache defect
# into a scatter of failures that look like real ones. There the run names the
# repair instead of performing it — the operator runs it once, serially.
if cold_cache_only "$RUN_REPORT" "$godot_exit"; then
	echo "[$GATE_TAG] $SCENARIO_NAME — cold import cache on a passing run; rebuilding and retrying once" >&2
	gdk_rebuild_import_cache "$HARD_TIMEOUT_SECONDS"
	run_scenario
fi

if cold_cache_only "$RUN_REPORT" "$godot_exit"; then
	echo "[$GATE_TAG] $SCENARIO_NAME — the uid index is STALE, not cold: the rebuild did not repair it." >&2
	if [ -n "${GDK_SCENARIO_IN_SWEEP:-}" ]; then
		echo "[$GATE_TAG] A sweep shares one $IMPORT_DIR/ with every peer still booting, so this run will" >&2
		echo "[$GATE_TAG] not remove it. Repair the tree ONCE, serially, then re-run the sweep:" >&2
		echo "[$GATE_TAG]   rm -rf $IMPORT_DIR && make import-cache" >&2
	else
		echo "[$GATE_TAG] REMOVING $IMPORT_DIR/ — a local editor's cache state, rebuilt from the tree —" >&2
		echo "[$GATE_TAG] then rebuilding and retrying a final time." >&2
		# The cwd is the project root: nothing above refused a tree without a
		# $GDK_PROJECT_FILE in it, and the operand is a literal.
		rm -rf "./$IMPORT_DIR"
		gdk_rebuild_import_cache "$HARD_TIMEOUT_SECONDS"
		run_scenario
	fi
fi

# A timeout kill means the run hung — the documented exit-3 verdict. The report
# is truncated, so reading it for a result line is pointless.
if gdk_timeout_is_hang "$godot_exit"; then
	echo "[$GATE_TAG] $SCENARIO_NAME HARD_TIMEOUT — exceeded ${HARD_TIMEOUT_SECONDS}s, killed (likely hang)"
	echo "  full report: $REPORT_FILE"
	exit 3
fi

ALLOW_REGEX="$(allowlist_regex "$GDK_SCENARIO_NOISE_ALLOWLIST")"
if [ -n "$ALLOW_REGEX" ]; then
	unexpected="$(grep -E "$ENGINE_ERROR_PATTERN" "$RUN_REPORT" | grep -vE "$ALLOW_REGEX" || true)"
else
	unexpected="$(grep -E "$ENGINE_ERROR_PATTERN" "$RUN_REPORT" || true)"
fi

# The runner's own verdict line (the last one wins if a scenario re-emits).
result_line="$(grep -E "$GDK_SCENARIO_RESULT_RE" "$RUN_REPORT" | tail -1 || true)"

if [ -n "$unexpected" ]; then
	echo "[$GATE_TAG] $SCENARIO_NAME FAIL — engine-level errors your runner could not see"
	echo "  engine errors:"
	printf '%s\n' "$unexpected" | sed 's/^/    /'
	echo "  full report: $REPORT_FILE"
	# A scenario PASS with engine-level output is a silent bug — upgrade it. A
	# non-zero engine exit keeps its own discriminating code so the caller can
	# still tell the shape of the failure.
	[ "$godot_exit" -eq 0 ] && exit 1
	exit "$godot_exit"
fi

if [ "$VERBOSE_STREAM" -eq 0 ]; then
	if [ -n "$result_line" ]; then
		echo "$result_line"
	else
		echo "[$GATE_TAG] $SCENARIO_NAME — no result line emitted (see report)"
	fi
	if [ "$godot_exit" -ne 0 ]; then
		grep -E "$FAILED_ASSERTION_PATTERN" "$RUN_REPORT" | sed 's/^/  /' || true
		echo "  full report: $REPORT_FILE"
	fi
fi

exit "$godot_exit"
