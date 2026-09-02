#!/usr/bin/env bash
# integration.sh — the INTEGRATION tier: boot / cross-system scenarios, each in
# its OWN process (isolation by construction), N in PARALLEL (speed from cores).
#
# Every scenario runs through the cold path — one scenario.sh, one fresh engine
# — so no scenario can observe another's global state. That is the tier's whole
# contract; the parallelism is what makes paying for it affordable.
#
# Usage:
#   tools/dev/runners/integration.sh --all             # every scenario
#   tools/dev/runners/integration.sh --smoke           # just the smoke scenario
#   tools/dev/runners/integration.sh --system protocol # slice: names matching protocol*
#   tools/dev/runners/integration.sh boot_a boot_b     # an explicit list
#   GDK_JOBS=4 tools/dev/runners/integration.sh --all  # cap the parallelism
#   tools/dev/runners/integration.sh --help | --self-test
#
# Exit: 0 = all passed | 1 = any failed | 2 = usage/harness error.
set -uo pipefail

# --- project config (yours to edit after install — the file is your repo's) --
REPO_ROOT_FROM_HERE="../../.."
# scenario.sh, relative to THIS file. The stock layout puts them side by side.
GDK_SCENARIO_RUNNER="${GDK_SCENARIO_RUNNER:-scenario.sh}"
GDK_SCENARIO_SOURCE_DIR="${GDK_SCENARIO_SOURCE_DIR:-tests/integration}"
# Shared fixtures and base classes that live among the scenarios but are not
# scenarios — an ERE over BASENAMES, without the .gd.
GDK_INTEGRATION_INFRA_RE="${GDK_INTEGRATION_INFRA_RE:-^(scenario_base|scenario_runner)$}"
# A CAPTURE is a TOOL — you run it to LOOK at something, and it renders a PNG
# that a headless boot deliberately no-ops. A SCENARIO is a GATE — it runs to
# stop a regression. The sweep boots gates; it has no business booting tools, so
# a basename matching this drops out of discovery.
#
# This costs the tools nothing: ONLY --all and --system route through discovery.
# An explicit `integration.sh <name>` and capture.sh reach one directly.
GDK_CAPTURE_SUFFIX_RE="${GDK_CAPTURE_SUFFIX_RE:-_capture$}"
# …EXCEPT the captures that grew a real headless contract nothing else owns.
# An ERE over basenames; empty means no exceptions. Add to it only after
# proving no unit test and no other scenario asserts the same thing — and note
# that every name here is asserted to EXIST by --self-test, so a rename cannot
# drop a gate silently out of --all.
GDK_CAPTURE_GATE_RE="${GDK_CAPTURE_GATE_RE:-}"
# The one scenario `--smoke` runs: the shortest boot that proves the game comes
# up at all. Yours to name.
GDK_SMOKE_SCENARIO="${GDK_SMOKE_SCENARIO:-smoke}"
# Env: GDK_JOBS  parallelism (default: cores - 2, floor 1)
# -----------------------------------------------------------------------------

GATE_TAG="INTEGRATION"
# What a failing scenario's transcript is grepped for, to say WHY in one line.
FAILURE_SUMMARY_RE='\[SCENARIO\]|reason=|SCRIPT ERROR|HARD_TIMEOUT'
FAILURE_SUMMARY_LINES=3

usage() {
	cat <<'USAGE_EOF'
usage: integration.sh --all | --smoke | --system <prefix> | <name>...
       integration.sh --help | --self-test

Runs integration scenarios, each in its own process, N in parallel. Each one
goes through scenario.sh, so the isolation is a process boundary rather than a
convention.

  --all            every discovered scenario
  --smoke          just GDK_SMOKE_SCENARIO
  --system <p>     every discovered scenario whose name starts with <p>
  <name>...        an explicit list, discovery bypassed
  --self-test      prove the argument handling and the discovery filter
                   against a fixture tree, booting nothing
  --help           this message

Env: GDK_SCENARIO_SOURCE_DIR    where scenario scripts live
     GDK_SCENARIO_RUNNER        scenario.sh, relative to this file
     GDK_INTEGRATION_INFRA_RE   basenames that are fixtures, not scenarios
     GDK_CAPTURE_SUFFIX_RE      basenames that are capture TOOLS, not gates
     GDK_CAPTURE_GATE_RE        captures that are gates after all
     GDK_SMOKE_SCENARIO         the scenario --smoke runs
     GDK_JOBS                   parallelism (default: cores - 2, floor 1)
Exit: 0 all passed | 1 any failed | 2 usage/harness error
USAGE_EOF
}

# --- discovery ---------------------------------------------------------------
# discover_all [dir] — every scenario the sweep should boot, one name per line.
# Takes the directory as an argument so the self-test can point it at a fixture
# tree instead of planting probe files in the real one.
discover_all() {
	local dir="${1:-$GDK_SCENARIO_SOURCE_DIR}"
	[ -d "$dir" ] || return 0
	# support/ holds shared fixtures, not scenarios.
	find "$dir" -type f -name '*.gd' -not -path '*/support/*' 2>/dev/null \
		| sed 's|.*/||; s|\.gd$||' \
		| grep -vE "$GDK_INTEGRATION_INFRA_RE" \
		| awk -v tool="$GDK_CAPTURE_SUFFIX_RE" -v gate="$GDK_CAPTURE_GATE_RE" '
			!($0 ~ tool) { print; next }
			gate != "" && $0 ~ gate { print }
		' \
		| sort -u
}

# capture_gate_names — the keep-list, one name per line.
capture_gate_names() {
	[ -n "$GDK_CAPTURE_GATE_RE" ] || return 0
	printf '%s\n' "$GDK_CAPTURE_GATE_RE" | tr '|' '\n' | tr -d '^()$'
}

# detect_jobs — cores minus two, floor one. Two are left for the shell, the
# aggregator and whatever else the machine is doing; a sweep that saturates
# every core makes each engine slower than the parallelism buys back.
detect_jobs() {
	local n j
	n="$( (sysctl -n hw.ncpu 2>/dev/null || nproc 2>/dev/null || echo 4) )"
	j=$((n - 2)); [ "$j" -lt 1 ] && j=1
	printf '%s\n' "$j"
}

# --- --self-test -------------------------------------------------------------
# Boots nothing: discovery is pure filesystem and text, which is exactly why it
# is written as a function over a directory.
self_test() {
	local scratch rc out failures=0 cases=0 name

	cases=$((cases + 1))
	rc=0; bash "$0" --help >/dev/null 2>&1 || rc=$?
	[ "$rc" -eq 0 ] || { echo "  MISS — --help should exit 0, got $rc" >&2; failures=$((failures + 1)); }

	cases=$((cases + 1))
	rc=0; bash "$0" >/dev/null 2>&1 || rc=$?
	[ "$rc" -eq 2 ] || { echo "  MISS — no argument should exit 2, got $rc" >&2; failures=$((failures + 1)); }

	cases=$((cases + 1))
	rc=0; bash "$0" --system >/dev/null 2>&1 || rc=$?
	[ "$rc" -eq 2 ] || { echo "  MISS — --system with no prefix should exit 2, got $rc" >&2; failures=$((failures + 1)); }

	cases=$((cases + 1))
	rc=0; bash "$0" '' >/dev/null 2>&1 || rc=$?
	[ "$rc" -eq 2 ] || { echo "  MISS — an EMPTY name should exit 2, got $rc" >&2; failures=$((failures + 1)); }

	cases=$((cases + 1))
	rc=0; bash "$0" ../escape >/dev/null 2>&1 || rc=$?
	[ "$rc" -eq 2 ] || { echo "  MISS — a name carrying a separator should exit 2, got $rc" >&2; failures=$((failures + 1)); }

	cases=$((cases + 1))
	rc=0; bash "$0" --self-test extra >/dev/null 2>&1 || rc=$?
	[ "$rc" -eq 2 ] || { echo "  MISS — --self-test takes no argument, got $rc" >&2; failures=$((failures + 1)); }

	# --- the discovery filter, against a fixture tree ------------------------
	scratch="$(mktemp -d "${TMPDIR:-/tmp}/gdk-integration-selftest.XXXXXX")" || return 1
	mkdir -p "$scratch/protocol" "$scratch/support"
	: > "$scratch/protocol/protocol_boot.gd"
	: > "$scratch/plain_gate.gd"
	: > "$scratch/thing_capture.gd"
	: > "$scratch/scenario_base.gd"
	: > "$scratch/support/helper.gd"
	out="$(discover_all "$scratch" | tr '\n' ' ')"

	cases=$((cases + 1))
	[ "$out" = "plain_gate protocol_boot " ] \
		|| { echo "  MISS — discovery, got '$out'" >&2; failures=$((failures + 1)); }

	# Each exclusion said separately, because each is a different claim: a
	# capture is a tool, a base class is not a scenario, support/ is fixtures.
	cases=$((cases + 1))
	printf '%s\n' "$out" | grep -q 'thing_capture' \
		&& { echo "  MISS — a capture TOOL still boots in the sweep" >&2; failures=$((failures + 1)); }
	cases=$((cases + 1))
	printf '%s\n' "$out" | grep -q 'scenario_base' \
		&& { echo "  MISS — a fixture base class was discovered as a scenario" >&2; failures=$((failures + 1)); }
	cases=$((cases + 1))
	printf '%s\n' "$out" | grep -q 'helper' \
		&& { echo "  MISS — a support/ fixture was discovered as a scenario" >&2; failures=$((failures + 1)); }

	# A keep-listed capture comes BACK into the sweep — the exception has to
	# work, or the list is decoration.
	cases=$((cases + 1))
	out="$(GDK_CAPTURE_GATE_RE='^(thing_capture)$' discover_all "$scratch" | tr '\n' ' ')"
	[ "$out" = "plain_gate protocol_boot thing_capture " ] \
		|| { echo "  MISS — the keep-list did not restore the gate, got '$out'" >&2; failures=$((failures + 1)); }

	# --- every keep-listed gate must EXIST and survive the filter ------------
	# A renamed or deleted keep-listed capture must fail loudly here, never
	# drop silently out of --all.
	while IFS= read -r name; do
		[ -n "$name" ] || continue
		cases=$((cases + 1))
		if [ -z "$(find "$GDK_SCENARIO_SOURCE_DIR" -type f -name "$name.gd" 2>/dev/null)" ]; then
			echo "  MISS — GDK_CAPTURE_GATE_RE names '$name', which has no file" >&2
			failures=$((failures + 1))
			continue
		fi
		discover_all | grep -qx "$name" \
			|| { echo "  MISS — keep-listed gate '$name' is missing from the sweep" >&2; failures=$((failures + 1)); }
	done < <(capture_gate_names)

	cases=$((cases + 1))
	[ "$(detect_jobs)" -ge 1 ] \
		|| { echo "  MISS — the job count must be at least 1" >&2; failures=$((failures + 1)); }

	rm -rf "$scratch"

	if [ "$failures" -eq 0 ]; then
		echo "[$GATE_TAG] SELF-TEST OK — $cases case(s)"
		return 0
	fi
	echo "[$GATE_TAG] SELF-TEST FAIL — $failures of $cases case(s), see above" >&2
	return 1
}

case "${1:-}" in
	--help|-h)
		[ "$#" -eq 1 ] || { echo "[$GATE_TAG] --help takes no argument" >&2; exit 2; }
		usage; exit 0 ;;
	--self-test)
		[ "$#" -eq 1 ] || { echo "[$GATE_TAG] --self-test takes no argument. See --help." >&2; exit 2; }
		self_test_rc=0; self_test || self_test_rc=$?; exit "$self_test_rc" ;;
esac

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/$REPO_ROOT_FROM_HERE" && pwd)" || exit 2
SCENARIO_SH="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/$GDK_SCENARIO_RUNNER"
if [ ! -f "$SCENARIO_SH" ]; then
	echo "[$GATE_TAG] scenario.sh not found at '$SCENARIO_SH' — set GDK_SCENARIO_RUNNER" >&2
	exit 2
fi
cd "$REPO_ROOT" || exit 2

NAMES=()
case "${1:-}" in
	"") echo "[$GATE_TAG] nothing to run. See --help." >&2; usage >&2; exit 2 ;;
	# `while read`, not `mapfile`: macOS ships bash 3.2.
	--all) while IFS= read -r n; do NAMES+=("$n"); done < <(discover_all) ;;
	--smoke) NAMES=("$GDK_SMOKE_SCENARIO") ;;
	--system)
		[ -n "${2:-}" ] || { echo "[$GATE_TAG] --system needs a prefix. See --help." >&2; exit 2; }
		while IFS= read -r n; do NAMES+=("$n"); done < <(discover_all | grep -E "^${2}") ;;
	-*) echo "[$GATE_TAG] unknown flag '$1'. See --help." >&2; exit 2 ;;
	*) NAMES=("$@") ;;
esac
for n in ${NAMES[@]+"${NAMES[@]}"}; do
	case "$n" in
		''|*/*|.|..|-*)
			echo "[$GATE_TAG] '$n' is not a scenario name. See --help." >&2
			exit 2 ;;
	esac
done
[ "${#NAMES[@]}" -gt 0 ] || { echo "[$GATE_TAG] no scenarios matched" >&2; exit 2; }

JOBS="${GDK_JOBS:-$(detect_jobs)}"
echo "[$GATE_TAG] ${#NAMES[@]} scenario(s), ${JOBS}-way parallel, isolated per process"

TMP="$(mktemp -d)" || exit 2
trap 'rm -rf "$TMP"' EXIT
: > "$TMP/results"

# Fan out: each scenario in its own scenario.sh, so each gets a fresh engine.
# Each job also gets its OWN user:// sandbox (GDK_HEADLESS_HOME) — without it
# every parallel boot shares one sandbox and they collide on save and log
# writes, reddening heavy scenarios nondeterministically. Per-process isolation
# is the tier's whole contract, and the per-job HOME is what delivers it.
# The $1/$2 below are the INNER bash's positionals, expanded by that shell.
# shellcheck disable=SC2016
printf '%s\n' "${NAMES[@]}" | xargs -P "$JOBS" -I{} bash -c '
	name="$1"; tmp="$2"
	export GDK_HEADLESS_HOME="$tmp/home-$name"
	out="$("'"$SCENARIO_SH"'" "$name" 2>&1)"; code=$?
	printf "%s\n" "$out" > "$tmp/$name.log"
	printf "%s\t%s\n" "$name" "$code" >> "$tmp/results"
' _ {} "$TMP"

PASS=0; FAIL=0; FAILED_NAMES=()
while IFS=$'\t' read -r name code; do
	if [ "$code" -eq 0 ]; then
		PASS=$((PASS + 1))
	else
		FAIL=$((FAIL + 1)); FAILED_NAMES+=("$name")
	fi
done < "$TMP/results"

# A job that never wrote a result line is a job that died before scenario.sh
# could report — counted as a failure, because the alternative is a sweep that
# reports 0 failures over scenarios that never ran.
UNREPORTED=$(( ${#NAMES[@]} - PASS - FAIL ))
if [ "$UNREPORTED" -gt 0 ]; then
	echo "[$GATE_TAG] $UNREPORTED scenario(s) produced no result at all — counting them failed"
	FAIL=$((FAIL + UNREPORTED))
fi

if [ "$FAIL" -gt 0 ]; then
	echo ""
	echo "[$GATE_TAG] FAILURES:"
	for n in ${FAILED_NAMES[@]+"${FAILED_NAMES[@]}"}; do
		echo "  --- $n ---"
		grep -hE "$FAILURE_SUMMARY_RE" "$TMP/$n.log" 2>/dev/null \
			| head -"$FAILURE_SUMMARY_LINES" | sed 's/^/      /'
	done
fi

echo ""
echo "[$GATE_TAG] SUMMARY: $PASS passed, $FAIL failed (of ${#NAMES[@]})"
[ "$FAIL" -eq 0 ] || exit 1
exit 0
