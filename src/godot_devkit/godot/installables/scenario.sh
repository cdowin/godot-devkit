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
#   tools/dev/runners/scenario.sh [--verbose|-v] --suite <name> [<name>…]
#   tools/dev/runners/scenario.sh --help | --self-test
#
# THE WARM CONTRACT (`--suite`, #36). A cold boot costs 13-15 s of CPU before
# the first assertion, so `--suite` boots the engine ONCE and runs several
# scenarios in sequence. It passes `-- <GDK_SCENARIO_SUITE_ARG> a,b,c` (stock
# `--scenarios`, comma-separated), and YOUR scenario runner, which owns the
# reset, then:
#   1. prints `[SCENARIO] <name> START` before each scenario — a line matching
#      `<GDK_SCENARIO_START_RE> <name> START`;
#   2. runs it against a fresh World, with the reset its scenario_base owns
#      (autoload state, World, player);
#   3. FINISHES that scenario's teardown, then prints its usual verdict line
#      (GDK_SCENARIO_RESULT_RE, then PASS|FAIL as a word) — the verdict closes
#      the scenario, so nothing it causes may come after it;
#   4. exits 0 after the last one: a FAIL is carried by its verdict line,
#      never by the exit code.
# The stream is split at the START markers: a scenario's slice runs from its
# START to the next one, with the boot preamble before the first START
# prepended to every slice, so an engine error between a START and its
# verdict upgrades THAT scenario's PASS to FAIL exactly as a cold run would.
# Each slice is published to <report dir>/<name>.log, one console line per
# scenario as today. A worker that goes GDK_SCENARIO_HARD_TIMEOUT seconds
# without a new START or verdict (the bound is per scenario, not per suite) is
# stopped: the scenario in progress and every one that never started get NO
# verdict and are handed back unrun (exit 4) — run them cold. Two findings
# belong to NO scenario, and hand back EVERY member, verdict or not: an engine
# exit that is non-zero and not the bound's kill (a crash, even one after the
# last verdict), and an engine error after a verdict and before the next START
# or the exit (exit-time leak warnings land there). A slice that passed but
# carries the cold-import-cache class is handed back too, so the cold path's
# recovery ladder gets it. `--scenario <name>` (the single path) is unchanged.
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
#       | 4 --suite only: scenario(s) handed back unrun — after a stall or a
#         parse error the ones that DID finish still carry their verdicts;
#         after a crash or an unattributable engine error none does. The
#         caller runs every handed-back one cold
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
# --suite: the user argument carrying the comma-separated scenario list, and
# how your runner spells its START marker — an ERE built the same way as the
# verdict's; a marker line is `<this> <name> START`.
GDK_SCENARIO_SUITE_ARG="${GDK_SCENARIO_SUITE_ARG:---scenarios}"
GDK_SCENARIO_START_RE="${GDK_SCENARIO_START_RE:-\[SCENARIO\]}"
# A transcript is evidence about the tree AS IT WAS WHEN IT RAN. Past this many
# days it is archaeology that reads as current, and any run reaps it.
GDK_REPORT_RETENTION_DAYS="${GDK_REPORT_RETENTION_DAYS:-7}"
# Env: GDK_SCENARIO_HARD_TIMEOUT  seconds bounding one scenario (default 60);
#                                 under --suite, the longest a worker may go
#                                 without a new START or verdict
#      GDK_GODOT                  the engine binary (default `godot`)
#      GDK_SCENARIO_IN_SWEEP      set by integration.sh: this run has PEERS
#                                 booting in the same tree, so the cache
#                                 recovery below reports its last remedy
#                                 instead of performing it on them.
#      GDK_SCENARIO_SUITE_RESULTS set by integration.sh for --suite: a
#                                 directory where each FINISHED scenario gets
#                                 <name>.log (its console block) and a
#                                 `<name>\t<code>` line in `results`, and each
#                                 handed-back one a line in `unrun`.
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
# Godot's GDScript parse-error signature. A runner whose load() came back null
# over a broken script does not quit, so without a watch on the live stream the
# only exit is the hard timeout — and a verdict that says "hang".
# Anchored at the line's start, so a scenario's own log text quoting it is not one.
PARSE_ERROR_PATTERN='^[[:space:]]*(SCRIPT ERROR: Parse Error|ERROR: .* - Parse Error:)'
# The engine's import cache, which the recovery below may REMOVE. A literal,
# never a configurable: it is the argument to an `rm -rf` inside a directory
# holding somebody's project, and a name that can be set from outside is a name
# that can be aimed.
IMPORT_DIR=".godot"

usage() {
	cat <<'USAGE_EOF'
usage: scenario.sh [--verbose|-v] <scenario_name>
       scenario.sh [--verbose|-v] --suite <name> [<name>...]
       scenario.sh --help | --self-test

Boots the project headless in a sandboxed HOME and runs ONE scenario, reading
the engine's own stream for errors your in-process runner cannot see.

  --verbose|-v  stream the whole transcript to the console
  --suite       boot ONCE and run the named scenarios in sequence (the warm
                worker): the runner gets `-- GDK_SCENARIO_SUITE_ARG a,b,c`,
                prints `[SCENARIO] <name> START` before each and its verdict
                after its teardown, and exits 0. A stall hands the unfinished
                ones back: `  WARM-ABORT  after <last finished> — N
                scenario(s) handed back`, exit 4; a crash, or an engine error
                outside every START..verdict window, hands back every member
                and names why after a colon
  --self-test   prove the argument handling, the report-freshness rules, the
                allowlist builder, what the cache recovery fires on, and the
                warm split against a stub engine
  --help        this message

Env: GDK_SCENARIO_SOURCE_DIR       where scenario scripts live
     GDK_SCENARIO_REPORT_DIR       where transcripts land (gitignore it)
     GDK_SCENARIO_NOISE_ALLOWLIST  EREs for engine lines you expect
     GDK_SCENARIO_USER_ARG         the user arg carrying the scenario name
     GDK_SCENARIO_RESULT_RE        how your runner spells its verdict line
     GDK_SCENARIO_HARD_TIMEOUT     seconds bounding the run (default 60); with
                                   --suite, per scenario: no START or verdict
                                   for this long kills the worker
     GDK_SCENARIO_SUITE_ARG        the user arg carrying the --suite list
                                   (default --scenarios)
     GDK_SCENARIO_START_RE         how your runner spells its START marker
     GDK_SCENARIO_SUITE_RESULTS    --suite: a directory for per-scenario results
     GDK_SCENARIO_IN_SWEEP         this run has peers in the same tree
     GDK_REPORT_RETENTION_DAYS     transcript retention (default 7)
     GDK_RUNNERS_LIB               path to gdk_runners.sh, relative to this file
     GDK_GODOT                     the engine binary (default `godot`)
Exit: 0 pass | 1 fail | 2 harness/usage error | 3 hard timeout
      | 4 --suite: scenario(s) handed back unrun
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

# --- the live stream: parse errors, and (--suite) progress --------------------
# Pure definitions; ALLOW_REGEX is read when they are CALLED, after the
# argument surface has set it.

# parse_error_line <report> — the first parse-error line the noise allowlist
# does not admit, or return 1. The allowlist applies because a scenario that
# loads a deliberately broken script has already said so there.
parse_error_line() {
	local line
	if [ -n "$ALLOW_REGEX" ]; then
		line="$(grep -E "$PARSE_ERROR_PATTERN" "$1" | grep -vE "$ALLOW_REGEX" | head -1)"
	else
		line="$(grep -E "$PARSE_ERROR_PATTERN" "$1" | head -1)"
	fi
	[ -n "$line" ] || return 1
	printf '%s\n' "$line"
}

# tap_parse_errors <hits> — pass the live stream through untouched, appending
# every parse-error line to <hits> AS IT ARRIVES. The watch cannot read the
# report instead: `head -c` block-buffers into it, so a short transcript
# reaches the disk only when the engine exits — which is the thing that never
# happens. Every line is flushed downstream as it passes: awk block-buffers
# into a pipe, and the --suite progress tap below it would otherwise see the
# stream in 4 KB lumps, turning the per-scenario bound into a per-suite one.
tap_parse_errors() {
	PARSE_RE="$PARSE_ERROR_PATTERN" awk -v hits="$1" \
		'{ print; fflush() } $0 ~ ENVIRON["PARSE_RE"] { print >> hits; close(hits) }'
}

# watch_for_parse_error <pidfile> <hits> <marker> — poll the tapped lines; on
# the first parse error the allowlist does not admit, write it to <marker> and
# stop the engine through the bound's own kill path. Ends with this run's
# shell, whichever way it ends.
watch_for_parse_error() {
	local pidfile="$1" hits="$2" marker="$3" line pid
	while kill -0 "$$" 2>/dev/null; do
		if line="$(parse_error_line "$hits")"; then
			printf '%s\n' "$line" > "$marker"
			pid="$(cat "$pidfile" 2>/dev/null)"
			# The bound's own process: `timeout` forwards the TERM to the
			# engine's whole group and escalates to KILL after its grace, so an
			# engine a wrapper script started (not exec'd) is stopped too.
			[ -z "$pid" ] || kill -TERM "$pid" 2>/dev/null
			return 0
		fi
		sleep 0.2
	done
}

# --- --suite: one boot, several scenarios ------------------------------------
# The awk half of both functions below: `start_name(line)` is the scenario a
# START marker names (empty when the line is not one, or names a scenario this
# suite did not ask for — a marker cannot aim a slice outside the list), and
# `verdict_of(line)` the first PASS|FAIL WORD after the verdict ERE's match
# (empty when the line is not a verdict). Reads START_RE, RESULT_RE and
# SUITE_NAMES (comma-separated) from the environment.
# shellcheck disable=SC2016  # an awk program, not a shell expansion
SUITE_AWK_LIB='
	function suite_init(   n, i, f) {
		n = split(ENVIRON["SUITE_NAMES"], f, ",")
		for (i = 1; i <= n; i++) asked[f[i]] = 1
		start_re = ENVIRON["START_RE"] "[[:space:]]+[^[:space:]]+[[:space:]]+START[[:space:]]*$"
	}
	function start_name(line,   s, n, f) {
		if (line !~ start_re) return ""
		s = line; sub(/[[:space:]]+START[[:space:]]*$/, "", s)
		n = split(s, f, /[[:space:]]+/)
		return (f[n] in asked) ? f[n] : ""
	}
	function verdict_of(line,   rest, n, f, i) {
		if (!match(line, ENVIRON["RESULT_RE"])) return ""
		rest = substr(line, RSTART + RLENGTH)
		n = split(rest, f, /[[:space:]]+/)
		for (i = 1; i <= n; i++) if (f[i] == "PASS" || f[i] == "FAIL") return f[i]
		return ""
	}
'

# suite_env — run "$@" with the three variables SUITE_AWK_LIB reads.
suite_env() {
	local IFS=,
	START_RE="$GDK_SCENARIO_START_RE" RESULT_RE="$GDK_SCENARIO_RESULT_RE" \
		SUITE_NAMES="${SUITE_NAMES[*]}" "$@"
}

# tap_suite_progress <progress> — pass the live stream through untouched,
# appending one line to <progress> per START marker or verdict AS IT ARRIVES:
# the per-scenario bound's clock is "the last time this file grew".
# shellcheck disable=SC2016  # an awk program, not a shell expansion
tap_suite_progress() {
	suite_env awk -v progress="$1" "$SUITE_AWK_LIB"'
		BEGIN { suite_init() }
		{ print; fflush() }
		start_name($0) != "" || verdict_of($0) != "" {
			print "." >> progress; close(progress)
		}'
}

# watch_for_stall <pidfile> <progress> <marker> — the per-scenario bound. When
# <progress> has not grown for more than GDK_SCENARIO_HARD_TIMEOUT seconds, say
# so in <marker> and stop the engine through the bound's own kill path, as the
# parse-error watch does. Ends with this run's shell.
watch_for_stall() {
	local pidfile="$1" progress="$2" marker="$3" seen=0 now last="$SECONDS" pid
	while kill -0 "$$" 2>/dev/null; do
		now="$(wc -l < "$progress" 2>/dev/null | tr -d ' ')"
		if [ "${now:-0}" != "$seen" ]; then
			seen="${now:-0}"; last="$SECONDS"
		elif [ $((SECONDS - last)) -gt "$HARD_TIMEOUT_SECONDS" ]; then
			printf '%s\n' "$((SECONDS - last))" > "$marker"
			pid="$(cat "$pidfile" 2>/dev/null)"
			[ -z "$pid" ] || kill -TERM "$pid" 2>/dev/null
			return 0
		fi
		sleep 0.2
	done
}

# split_suite_transcript <transcript> <dir> — write <dir>/<name>.slice for
# every scenario that STARTed, and print one row per such scenario, in START
# order: `<name>\t<PASS|FAIL|->\t<verdict line>`. A slice runs from its START
# to the next START; the boot preamble before the first START opens every
# slice, as it opens every cold transcript. A verdict re-emitted later wins,
# as the cold path's `tail -1` does. Output after a scenario's verdict belongs
# to NO scenario (the contract has the runner finish its teardown first): it
# stays in the slice's report, and is also written to <dir>/between when a
# START follows it and to <dir>/after when none does, where the caller can
# refuse to attribute it. Pure over a file, for the corpus.
# shellcheck disable=SC2016  # an awk program, not a shell expansion
split_suite_transcript() {
	suite_env awk -v out="$2" "$SUITE_AWK_LIB"'
		BEGIN { suite_init() }
		{
			name = start_name($0)
			if (name != "") {
				if (orph != "") { printf "%s", orph >> (out "/between"); close(out "/between"); orph = "" }
				if (file != "") close(file)
				cur = name; file = out "/" cur ".slice"
				if (!(cur in started)) { order[++k] = cur; started[cur] = 1; printf "%s", pre >> file }
				print >> file
				next
			}
			if (cur == "") { pre = pre $0 "\n"; next }
			print >> file
			if (cur in verdict) orph = orph $0 "\n"
			v = verdict_of($0)
			if (v != "") { verdict[cur] = v; vline[cur] = $0 }
		}
		END {
			if (orph != "") printf "%s", orph >> (out "/after")
			for (i = 1; i <= k; i++) {
				n = order[i]
				printf "%s\t%s\t%s\n", n, ((n in verdict) ? verdict[n] : "-"), vline[n]
			}
		}' "$1"
}

# suite_name_defect <name> — why <name> cannot be a --suite member (it becomes
# a file name, a user argument, and one field of a comma-separated list), or
# return 1.
suite_name_defect() {
	case "${1-}" in
		''|*/*|.|..|-*) echo "is not a scenario name"; return 0 ;;
		*,*|*[[:space:]]*) echo "carries a comma or whitespace — the suite list is comma-separated"; return 0 ;;
	esac
	return 1
}

# engine_error_lines <file> — the engine-level lines the allowlist does not
# admit, the same filter the cold path applies to its whole transcript.
engine_error_lines() {
	if [ -n "$ALLOW_REGEX" ]; then
		grep -E "$ENGINE_ERROR_PATTERN" "$1" | grep -vE "$ALLOW_REGEX" || true
	else
		grep -E "$ENGINE_ERROR_PATTERN" "$1" || true
	fi
}

# publish_report <name> <source> — the private-file-then-move rule, for one
# slice: a publish can be stale, never spliced.
publish_report() {
	local tmp
	tmp="$(mktemp "$GDK_SCENARIO_REPORT_DIR/$(report_temp_template "$1")")" || return 2
	if ! { cat "$2" > "$tmp" && mv -f "$tmp" "$GDK_SCENARIO_REPORT_DIR/$1.log"; }; then
		rm -f "$tmp"
	fi
}

# run_suite — the warm worker, after the shared setup. Boots once under a
# backstop bound of HARD_TIMEOUT x (N + 2); the per-scenario bound is the stall
# watch. Returns the documented exit code.
run_suite() {
	local n="${#SUITE_NAMES[@]}" list transcript pidfile hits marker progress stalled
	local watch_pid stall_pid code rcode slices table name row verdict vline block
	local killed=0 in_progress='' last_started='' last_finished='(none)' failed=0
	local results="${GDK_SCENARIO_SUITE_RESULTS:-}" unexpected parse_error stall
	local whole='' orphans='' where last_verdict
	local -a aborted=() cached=()
	list="$(IFS=,; printf '%s' "${SUITE_NAMES[*]}")"
	transcript="$(gdk_sandbox_tmpfile suite.XXXXXX)" || return 2
	pidfile="$(gdk_sandbox_tmpfile engine-pid.XXXXXX)" || return 2
	hits="$(gdk_sandbox_tmpfile parse-hits.XXXXXX)" || return 2
	marker="$(gdk_sandbox_tmpfile parse-error.XXXXXX)" || return 2
	progress="$(gdk_sandbox_tmpfile progress.XXXXXX)" || return 2
	stalled="$(gdk_sandbox_tmpfile stalled.XXXXXX)" || return 2
	slices="$(mktemp -d "${TMPDIR:-/tmp}/gdk-suite.XXXXXX")" || return 2
	gdk_on_exit "rm -rf '$slices'"
	[ -z "$results" ] || mkdir -p "$results" || return 2
	# Rule 1 of the freshness rules, per member: each clears its own slot.
	for name in "${SUITE_NAMES[@]}"; do rm -f "$GDK_SCENARIO_REPORT_DIR/$name.log"; done

	watch_for_parse_error "$pidfile" "$hits" "$marker" &
	watch_pid=$!
	watch_for_stall "$pidfile" "$progress" "$stalled" &
	stall_pid=$!
	# shellcheck disable=SC2016  # $$ and $0 are the shim's own, not ours
	if [ "$VERBOSE_STREAM" -eq 1 ]; then
		gdk_run_bounded $((HARD_TIMEOUT_SECONDS * (n + 2))) -- \
			sh -c 'echo "$PPID" > "$0"; exec "$@"' "$pidfile" \
			"$GDK_GODOT" --path . --headless -- \
			"$GDK_SCENARIO_SUITE_ARG" "$list" 2>&1 \
			| tap_parse_errors "$hits" | tap_suite_progress "$progress" \
			| head -c "$GDK_LOG_CAP_BYTES" | tee "$transcript"
	else
		gdk_run_bounded $((HARD_TIMEOUT_SECONDS * (n + 2))) -- \
			sh -c 'echo "$PPID" > "$0"; exec "$@"' "$pidfile" \
			"$GDK_GODOT" --path . --headless -- \
			"$GDK_SCENARIO_SUITE_ARG" "$list" 2>&1 \
			| tap_parse_errors "$hits" | tap_suite_progress "$progress" \
			| head -c "$GDK_LOG_CAP_BYTES" > "$transcript"
	fi
	code="${PIPESTATUS[0]}"
	kill "$watch_pid" "$stall_pid" 2>/dev/null
	wait "$watch_pid" "$stall_pid" 2>/dev/null
	parse_error="$(cat "$marker")"; stall="$(cat "$stalled")"
	if [ -n "$parse_error" ] || [ -n "$stall" ] || gdk_timeout_is_hang "$code"; then
		killed=1
	fi

	table="$(split_suite_transcript "$transcript" "$slices")"
	last_started="$(printf '%s\n' "$table" | awk -F'\t' 'NF { n = $1 } END { print n }')"
	last_verdict="$(printf '%s\n' "$table" | awk -F'\t' 'NF && $2 != "-" { n = $1 } END { print n }')"
	# Two findings belong to no one scenario, so NO member keeps a warm
	# verdict and the cold path judges each: an engine exit that is non-zero
	# and not the bound's own kill (a crash, even after every verdict), and an
	# unallowed engine error outside every START..verdict window.
	for where in between after; do
		[ -z "$orphans" ] && [ -f "$slices/$where" ] || continue
		orphans="$(engine_error_lines "$slices/$where")"
		[ -n "$orphans" ] || continue
		case "$where" in
			between) whole="engine errors between a verdict and the next START" ;;
			*) whole="engine errors after the last verdict" ;;
		esac
	done
	if [ "$killed" -eq 0 ] && [ "$code" -ne 0 ]; then
		whole="the engine exited $code"
	fi
	[ -z "$whole" ] || last_finished="${last_verdict:-(none)}"

	for name in "${SUITE_NAMES[@]}"; do
		row="$(printf '%s\n' "$table" | awk -F'\t' -v n="$name" '$1 == n { print; exit }')"
		[ -z "$row" ] || publish_report "$name" "$slices/$name.slice"
		verdict="$(printf '%s' "$row" | cut -f2)"
		vline="$(printf '%s' "$row" | cut -f3-)"
		if [ -n "$whole" ]; then
			# Still name the one in progress, for a kill's reason line below.
			if [ -n "$row" ] && { [ "$verdict" = "-" ] || { [ "$killed" -eq 1 ] && [ "$name" = "$last_started" ]; }; }; then
				[ -n "$in_progress" ] || in_progress="$name"
			fi
			aborted+=("$name")
			continue
		fi
		# No verdict, or the one in progress when the worker was stopped: a
		# stop after its verdict is a runner that never exited (contract step
		# 4), and a cold run is what says so.
		if [ -z "$row" ] || [ "$verdict" = "-" ] \
			|| { [ "$killed" -eq 1 ] && [ "$name" = "$last_started" ]; }; then
			[ -n "$in_progress" ] || [ -z "$row" ] || in_progress="$name"
			aborted+=("$name")
			continue
		fi
		# A passing slice carrying the cold-cache class is the cold path's
		# case: its recovery ladder is the one that can repair the tree.
		if [ "$verdict" = PASS ] && grep -qE "$COLD_CACHE_PATTERN" "$slices/$name.slice"; then
			echo "[$GATE_TAG] $name — cold import cache on a passing run; handed back to the cold path"
			cached+=("$name")
			continue
		fi
		last_finished="$name"
		unexpected="$(engine_error_lines "$slices/$name.slice")"
		if [ -n "$unexpected" ]; then
			block="$(printf '%s\n' "[$GATE_TAG] $name FAIL — engine-level errors your runner could not see" \
				"  engine errors:"
				printf '%s\n' "$unexpected" | sed 's/^/    /'
				echo "  full report: $GDK_SCENARIO_REPORT_DIR/$name.log")"
			verdict=FAIL
		elif [ "$VERBOSE_STREAM" -eq 1 ]; then
			block=''
		elif [ "$verdict" = FAIL ]; then
			block="$(printf '%s\n' "$vline"
				grep -E "$FAILED_ASSERTION_PATTERN" "$slices/$name.slice" | sed 's/^/  /' || true
				echo "  full report: $GDK_SCENARIO_REPORT_DIR/$name.log")"
		else
			block="$vline"
		fi
		[ -z "$block" ] || printf '%s\n' "$block"
		if [ "$verdict" = FAIL ]; then failed=$((failed + 1)); fi
		if [ -n "$results" ]; then
			printf '%s\n' "$block" > "$results/$name.log"
			if [ "$verdict" = FAIL ]; then rcode=1; else rcode=0; fi
			printf '%s\t%s\n' "$name" "$rcode" >> "$results/results"
		fi
	done

	if [ "${#aborted[@]}" -gt 0 ]; then
		if [ -n "$parse_error" ]; then
			echo "[$GATE_TAG] ${in_progress:-(boot)} — GDScript parse error: $parse_error; the worker was stopped"
		elif [ -n "$stall" ]; then
			echo "[$GATE_TAG] ${in_progress:-(boot)} HARD_TIMEOUT — no START or verdict for ${HARD_TIMEOUT_SECONDS}s, worker killed (likely hang)"
		elif gdk_timeout_is_hang "$code"; then
			echo "[$GATE_TAG] suite HARD_TIMEOUT — exceeded $((HARD_TIMEOUT_SECONDS * (n + 2)))s, worker killed"
		elif [ -n "$whole" ]; then
			echo "[$GATE_TAG] suite — $whole: no one scenario owns that, so every member runs cold"
			if [ -n "$orphans" ]; then
				printf '%s\n' "$orphans" | sed 's/^/    /'
			else
				tail -3 "$transcript" | sed 's/^/    /'
			fi
		else
			echo "[$GATE_TAG] ${in_progress:-(boot)} — the engine exited before its verdict"
			[ -n "$in_progress" ] || tail -3 "$transcript" | sed 's/^/    /'
		fi
		echo "  WARM-ABORT  after $last_finished — ${#aborted[@]} scenario(s) handed back${whole:+: $whole}"
		echo "    handed back: ${aborted[*]}"
	fi
	if [ -n "$results" ]; then
		for name in ${aborted[@]+"${aborted[@]}"} ${cached[@]+"${cached[@]}"}; do
			printf '%s\n' "$name" >> "$results/unrun"
		done
	fi
	[ $(( ${#aborted[@]} + ${#cached[@]} )) -eq 0 ] || return 4
	[ "$failed" -eq 0 ] || return 1
	return 0
}

# suite_cases <scratch> <library> — self_test's warm-worker cases: THIS file
# installed at the stock depth of a scratch project, a stub `godot` on PATH that
# runs the --scenarios list the way the contract says (GDK_STUB_MODE makes B
# shout an engine ERROR, crash, or stall), and the results directory
# integration.sh reads. Uses self_test's `cases` and `failures`. Each case is
# one chain of claims ending in `|| miss`.
# shellcheck disable=SC2015
suite_cases() {
	local scratch="$1" lib="$2" proj bin res out rc t0 n
	proj="$scratch/suite"; bin="$scratch/bin"; res="$scratch/results"
	mkdir -p "$proj/tools/dev/runners" "$proj/tests/integration" "$bin"
	cp "$0" "$proj/tools/dev/runners/scenario.sh"
	cp "$lib" "$proj/tools/dev/gdk_runners.sh"
	: > "$proj/project.godot"
	for n in a b c; do : > "$proj/tests/integration/$n.gd"; done
	cat > "$bin/godot" <<'STUB_EOF'
#!/usr/bin/env bash
list=''; single=''
while [ "$#" -gt 0 ]; do
	case "$1" in --scenarios) list="${2-}" ;; --scenario) single="${2-}" ;; esac
	shift
done
echo "Godot Engine v4.stub"
if [ -n "$list" ]; then IFS=, read -r -a names <<<"$list"; warm=1; else names=("$single"); warm=0; fi
leak=0
for n in "${names[@]}"; do
	[ "$warm" -eq 0 ] || echo "[SCENARIO] $n START"
	case "${GDK_STUB_MODE:-}:$n" in
		error:b) echo "ERROR: b broke the engine" ;;
		crash:b) exit 139 ;;
		stall:b) sleep 30 ;;
		slow:*) sleep 1.5 ;;
		exitleak:a) leak=1 ;;
	esac
	echo "[SCENARIO] $n PASS steps=1 errors=0"
	[ "${GDK_STUB_MODE:-}:$n" != gap:a ] || echo "ERROR: a tore down after its verdict"
done
[ "$leak" -eq 0 ] || echo "WARNING: ObjectDB instances leaked at exit (run with --verbose for details)."
[ "${GDK_STUB_MODE:-}" != crashexit ] || exit 139
STUB_EOF
	chmod +x "$bin/godot"
	# suite <mode> [hard timeout] — one warm run of a,b,c, fresh results, the
	# caller's GDK_* out of the way.
	suite() {
		rm -rf "$res" "$proj/.scenario-reports"
		( unset GDK_SCENARIO_REPORT_DIR GDK_SCENARIO_SOURCE_DIR GDK_SCENARIO_NOISE_ALLOWLIST \
			GDK_SCENARIO_START_RE GDK_SCENARIO_RESULT_RE GDK_SCENARIO_SUITE_ARG GDK_RUNNERS_LIB \
			GDK_HEADLESS_HOME GDK_SCENARIO_IN_SWEEP VERBOSE
		  PATH="$bin:$PATH" GDK_GODOT=godot GDK_SCENARIO_SUITE_RESULTS="$res" \
			GDK_SCENARIO_HARD_TIMEOUT="${2:-20}" GDK_STUB_MODE="$1" \
			bash "$proj/tools/dev/runners/scenario.sh" --suite a b c 2>&1 )
	}
	# cold <mode> <name> — the cold path the caller runs a handed-back member
	# through, against the same stub; prints nothing, returns its exit code.
	cold() {
		( unset GDK_SCENARIO_REPORT_DIR GDK_SCENARIO_SOURCE_DIR GDK_SCENARIO_NOISE_ALLOWLIST \
			GDK_SCENARIO_RESULT_RE GDK_SCENARIO_USER_ARG GDK_RUNNERS_LIB GDK_HEADLESS_HOME \
			GDK_SCENARIO_IN_SWEEP VERBOSE
		  PATH="$bin:$PATH" GDK_GODOT=godot GDK_SCENARIO_HARD_TIMEOUT=20 GDK_STUB_MODE="$1" \
			bash "$proj/tools/dev/runners/scenario.sh" "$2" >/dev/null 2>&1 )
	}
	miss() { echo "  MISS — $1" >&2; failures=$((failures + 1)); }

	cases=$((cases + 1))
	out="$(suite ok)"; rc=$?
	[ "$rc" -eq 0 ] && [ "$(grep -cE '^\[SCENARIO\] [abc] PASS steps=1' <<<"$out")" = 3 ] \
		&& [ "$(sort "$res/results" | tr '\t\n' ': ')" = "a:0 b:0 c:0 " ] \
		|| miss "three scenarios in one boot are three verdicts (rc $rc): $out"
	cases=$((cases + 1))
	[ "$(ls "$proj/.scenario-reports")" = "$(printf 'a.log\nb.log\nc.log')" ] \
		&& grep -qx '\[SCENARIO\] b START' "$proj/.scenario-reports/b.log" \
		&& ! grep -q 'a START' "$proj/.scenario-reports/b.log" \
		&& grep -qx 'Godot Engine v4.stub' "$proj/.scenario-reports/c.log" \
		|| miss "each scenario is published to its own report: its slice, opened by the boot preamble"

	cases=$((cases + 1))
	out="$(suite error)"; rc=$?
	[ "$rc" -eq 1 ] && [ "$(sort "$res/results" | tr '\t\n' ': ')" = "a:0 b:1 c:0 " ] \
		&& grep -qF '[SCENARIO] b FAIL — engine-level errors your runner could not see' <<<"$out" \
		&& grep -qx '\[SCENARIO\] c PASS steps=1 errors=0' <<<"$out" \
		|| miss "an engine ERROR between B's START and its verdict fails B only (rc $rc): $out"

	# A non-zero engine exit that is not the bound's kill belongs to no one
	# scenario, so no member keeps a warm verdict — A's PASS included.
	cases=$((cases + 1))
	out="$(suite crash)"; rc=$?
	[ "$rc" -eq 4 ] \
		&& grep -qxF '  WARM-ABORT  after a — 3 scenario(s) handed back: the engine exited 139' <<<"$out" \
		&& [ "$(tr '\n' ' ' < "$res/unrun")" = "a b c " ] && [ ! -s "$res/results" ] \
		|| miss "a worker that crashes during B hands back every member, exit 4 (rc $rc): $out"
	cases=$((cases + 1))
	out="$(suite crashexit)"; rc=$?
	[ "$rc" -eq 4 ] \
		&& grep -qxF '  WARM-ABORT  after c — 3 scenario(s) handed back: the engine exited 139' <<<"$out" \
		&& [ "$(tr '\n' ' ' < "$res/unrun")" = "a b c " ] && [ ! -s "$res/results" ] \
		|| miss "three PASS verdicts then exit 139 hand back every member, exit 4 (rc $rc): $out"

	# Engine errors outside every START..verdict window are nobody's: the
	# slice goes cold, where the leaker is red and nobody else is blamed.
	cases=$((cases + 1))
	out="$(suite exitleak)"; rc=$?
	[ "$rc" -eq 4 ] \
		&& grep -qxF '  WARM-ABORT  after c — 3 scenario(s) handed back: engine errors after the last verdict' <<<"$out" \
		&& [ "$(tr '\n' ' ' < "$res/unrun")" = "a b c " ] && [ ! -s "$res/results" ] \
		&& ! cold exitleak a && cold exitleak c \
		|| miss "a leak-at-exit line after the last verdict hands the slice back; cold, A is red and C green (rc $rc): $out"
	cases=$((cases + 1))
	out="$(suite gap)"; rc=$?
	[ "$rc" -eq 4 ] \
		&& grep -qxF '  WARM-ABORT  after c — 3 scenario(s) handed back: engine errors between a verdict and the next START' <<<"$out" \
		&& [ "$(tr '\n' ' ' < "$res/unrun")" = "a b c " ] \
		|| miss "an engine error between A's verdict and B's START hands the slice back (rc $rc): $out"

	# The bound is per scenario: three scenarios of 1.5 s each under a 2 s
	# bound finish warm, although the suite takes longer than the bound.
	cases=$((cases + 1))
	out="$(suite slow 2)"; rc=$?
	[ "$rc" -eq 0 ] && [ "$(sort "$res/results" | tr '\t\n' ': ')" = "a:0 b:0 c:0 " ] \
		|| miss "a slow-but-progressing suite completes warm under a per-scenario bound (rc $rc): $out"

	cases=$((cases + 1))
	t0="$SECONDS"
	out="$(suite stall 1)"; rc=$?
	[ "$rc" -eq 4 ] && [ $((SECONDS - t0)) -lt 15 ] \
		&& grep -qF '[SCENARIO] b HARD_TIMEOUT — no START or verdict for 1s' <<<"$out" \
		&& [ "$(tr '\n' ' ' < "$res/unrun")" = "b c " ] \
		|| miss "a worker that stalls in B is killed at the per-scenario bound, B and C handed back (rc $rc, $((SECONDS - t0))s): $out"
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

	# --- --suite: the argument surface --------------------------------------
	local -a bad_suite
	for bad in '' 'a a' 'a,b'; do
		cases=$((cases + 1))
		# Split on purpose: 'a a' is the same name twice.
		read -r -a bad_suite <<<"$bad"
		rc=0; bash "$0" --suite ${bad_suite[@]+"${bad_suite[@]}"} >/dev/null 2>&1 || rc=$?
		[ "$rc" -eq 2 ] || { echo "  MISS — --suite '$bad' should exit 2, got $rc" >&2; failures=$((failures + 1)); }
	done

	# --- --suite end to end, over a stub engine that honours the contract ----
	suite_cases "$scratch" "$lib"

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
SUITE=0
SUITE_NAMES=()
if [ "${1:-}" = "--suite" ]; then
	SUITE=1; shift
	[ "$#" -ge 1 ] || { echo "[$GATE_TAG] --suite takes one or more scenario names. See --help." >&2; exit 2; }
	for name in "$@"; do
		if defect="$(suite_name_defect "$name")"; then
			echo "[$GATE_TAG] '$name' $defect. See --help." >&2; exit 2
		fi
		case $'\n'"$(printf '%s\n' ${SUITE_NAMES[@]+"${SUITE_NAMES[@]}"})"$'\n' in
			*$'\n'"$name"$'\n'*) echo "[$GATE_TAG] '$name' is named twice in the suite. See --help." >&2; exit 2 ;;
		esac
		SUITE_NAMES+=("$name")
	done
	case "$HARD_TIMEOUT_SECONDS" in
		''|*[!0-9]*|0) echo "[$GATE_TAG] GDK_SCENARIO_HARD_TIMEOUT='$HARD_TIMEOUT_SECONDS' — expected whole seconds above 0" >&2; exit 2 ;;
	esac
else
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
fi

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

# The warm worker shares everything above and nothing below: no single report
# slot, and no cache-recovery ladder — a slice that needs the ladder is handed
# back to the cold path, which has it.
if [ "$SUITE" -eq 1 ]; then
	mkdir -p "$GDK_SCENARIO_REPORT_DIR"
	reap_stale_scenario_reports "$GDK_SCENARIO_REPORT_DIR"
	trap 'exit 130' INT
	trap 'exit 143' TERM
	gdk_sandbox_home
	ALLOW_REGEX="$(allowlist_regex "$GDK_SCENARIO_NOISE_ALLOWLIST")"
	suite_rc=0; run_suite || suite_rc=$?
	exit "$suite_rc"
fi

# A receipt over these exact inputs is the proof already bought (gdk_runners.sh,
# proof receipts) — on a DIRECT run only. A sweep's job is integration.sh's
# receipt to give, and `-v` is someone asking to watch the engine. The key is
# the name, how the runner is told it, the scenario file and every path its
# header covers.
RECEIPT_KEY=""
if [ "$VERBOSE_STREAM" -eq 0 ] && [ -z "${GDK_SCENARIO_IN_SWEEP:-}" ]; then
	scenario_files=()
	while IFS= read -r f; do [ -n "$f" ] && scenario_files+=("$f"); done \
		< <(find "$GDK_SCENARIO_SOURCE_DIR" -type f -name "$SCENARIO_NAME.gd" 2>/dev/null | sort)
	# shellcheck disable=SC2034  # read by gdk_receipt_key, in the sourced library
	GDK_RECEIPT_PATHS="$(gdk_receipt_covers ${scenario_files[@]+"${scenario_files[@]}"} | tr '\n' ' ')"
	RECEIPT_KEY="$(gdk_receipt_key scenario "$SCENARIO_NAME" "$GDK_SCENARIO_USER_ARG" \
		"$GDK_SCENARIO_RESULT_RE" "$GDK_SCENARIO_NOISE_ALLOWLIST")" || RECEIPT_KEY=""
	if gdk_receipt_hit scenario "$RECEIPT_KEY"; then
		exit 0
	fi
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

ALLOW_REGEX="$(allowlist_regex "$GDK_SCENARIO_NOISE_ALLOWLIST")"

# Boot the scenario once, capturing the transcript. A function so the
# cold-cache recovery below can re-run it without duplicating the plumbing.
# The engine is exec'd through a shim that records its PARENT's pid — the
# `timeout` bounding it — which is what the parse-error watch signals.
run_scenario() {
	local pidfile hits marker watch_pid
	pidfile="$(gdk_sandbox_tmpfile engine-pid.XXXXXX)" || exit 2
	hits="$(gdk_sandbox_tmpfile parse-hits.XXXXXX)" || exit 2
	marker="$(gdk_sandbox_tmpfile parse-error.XXXXXX)" || exit 2
	watch_for_parse_error "$pidfile" "$hits" "$marker" &
	watch_pid=$!
	# shellcheck disable=SC2016  # $$ and $0 are the shim's own, not ours
	if [ "$VERBOSE_STREAM" -eq 1 ]; then
		gdk_run_bounded "$HARD_TIMEOUT_SECONDS" -- \
			sh -c 'echo "$PPID" > "$0"; exec "$@"' "$pidfile" \
			"$GDK_GODOT" --path . --headless -- \
			"$GDK_SCENARIO_USER_ARG" "$SCENARIO_NAME" 2>&1 \
			| tap_parse_errors "$hits" \
			| head -c "$GDK_LOG_CAP_BYTES" | tee "$RUN_REPORT"
	else
		gdk_run_bounded "$HARD_TIMEOUT_SECONDS" -- \
			sh -c 'echo "$PPID" > "$0"; exec "$@"' "$pidfile" \
			"$GDK_GODOT" --path . --headless -- \
			"$GDK_SCENARIO_USER_ARG" "$SCENARIO_NAME" 2>&1 \
			| tap_parse_errors "$hits" \
			| head -c "$GDK_LOG_CAP_BYTES" > "$RUN_REPORT"
	fi
	# head -c exits 0 — the engine's own code is PIPESTATUS[0], exactly as
	# gdk_gate_capture documents.
	godot_exit="${PIPESTATUS[0]}"
	kill "$watch_pid" 2>/dev/null
	wait "$watch_pid" 2>/dev/null
	parse_error="$(cat "$marker")"
	rm -f "$pidfile" "$hits" "$marker"
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
#
# A parse error the watch caught is checked FIRST: stopping the engine can end
# in the SIGKILL escalation, whose code reads as a hang.
if [ -n "$parse_error" ]; then
	echo "[$GATE_TAG] $SCENARIO_NAME FAIL — GDScript parse error: $parse_error"
	echo "  full report: $REPORT_FILE"
	exit 1
fi
if gdk_timeout_is_hang "$godot_exit"; then
	# The backstop: a hang whose transcript names a parse error the watch
	# missed says so, instead of sending the reader after a hang.
	if parse_error="$(parse_error_line "$RUN_REPORT")"; then
		echo "[$GATE_TAG] $SCENARIO_NAME HARD_TIMEOUT — exceeded ${HARD_TIMEOUT_SECONDS}s, killed (GDScript parse error: $parse_error)"
	else
		echo "[$GATE_TAG] $SCENARIO_NAME HARD_TIMEOUT — exceeded ${HARD_TIMEOUT_SECONDS}s, killed (likely hang)"
	fi
	echo "  full report: $REPORT_FILE"
	exit 3
fi

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

if [ "$godot_exit" -eq 0 ] && [ -n "$RECEIPT_KEY" ] && [ -n "$result_line" ]; then
	gdk_receipt_write scenario "$RECEIPT_KEY" "$result_line" "$SCENARIO_NAME" "$GDK_SCENARIO_USER_ARG" \
		"$GDK_SCENARIO_RESULT_RE" "$GDK_SCENARIO_NOISE_ALLOWLIST"
fi
exit "$godot_exit"
