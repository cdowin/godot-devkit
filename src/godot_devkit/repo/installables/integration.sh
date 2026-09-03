#!/usr/bin/env bash
# integration.sh — the INTEGRATION tier: boot / cross-system scenarios, each in
# its OWN process (isolation by construction), N in PARALLEL (speed from cores).
#
# Every scenario runs through the cold path — one scenario.sh, one fresh engine
# — so no scenario can observe another's global state. That is the tier's whole
# contract; the parallelism is what makes paying for it affordable.
#
# A SCENARIO DECLARES WHAT IT COVERS. Its header — the leading run of comment
# lines — carries `## covers: <path>[, <path>…]`, repo-relative prefixes of the
# code it exercises, and `--diff <ref>` maps a change to the slice that
# declares it: touched paths → covering scenarios, plus the smoke scenario. A
# scenario declaring nothing cannot be sliced to and is REPORTED (it rides only
# --all); `check test-shape` is the gate that refuses one. `--all` stays the
# milestone gate and the gate for a change to the tier's own ground.
#
# Usage:
#   tools/dev/runners/integration.sh --all              # every scenario
#   tools/dev/runners/integration.sh --smoke            # just the smoke scenario
#   tools/dev/runners/integration.sh --system protocol  # the tests/integration/protocol/ directory
#   tools/dev/runners/integration.sh --diff HEAD        # what the uncommitted change covers, + smoke
#   tools/dev/runners/integration.sh boot_a boot_b      # an explicit list
#   GDK_JOBS=4 tools/dev/runners/integration.sh --all   # cap the parallelism
#   tools/dev/runners/integration.sh --help | --self-test
#
# Exit: 0 = all passed | 1 = any failed, or a slice that selected nothing
#     | 2 = usage/harness error.
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
# This costs the tools nothing: ONLY --all, --system and --diff route through
# discovery. An explicit `integration.sh <name>` and capture.sh reach one
# directly.
GDK_CAPTURE_SUFFIX_RE="${GDK_CAPTURE_SUFFIX_RE:-_capture$}"
# …EXCEPT the captures that grew a real headless contract nothing else owns.
# An ERE over basenames; empty means no exceptions. Add to it only after
# proving no unit test and no other scenario asserts the same thing — and note
# that every name here is asserted to EXIST by --self-test, so a rename cannot
# drop a gate silently out of --all.
GDK_CAPTURE_GATE_RE="${GDK_CAPTURE_GATE_RE:-}"
# The one scenario `--smoke` runs, and the one every `--diff` slice carries:
# the shortest boot that proves the game comes up at all. Yours to name.
GDK_SMOKE_SCENARIO="${GDK_SMOKE_SCENARIO:-smoke}"
# The tier's own GROUND: paths whose change makes every scenario the honest
# slice, because every scenario boots on them. An ERE over REPO-RELATIVE paths.
# A basename matching GDK_INTEGRATION_INFRA_RE is ground too, without being
# named twice.
GDK_SCENARIO_SUBSTRATE_RE="${GDK_SCENARIO_SUBSTRATE_RE:-^tests/support/|^tools/dev/runners/|^tools/dev/gdk_runners\.sh$}"
# Env: GDK_JOBS  parallelism (default: cores - 2, floor 1)
# -----------------------------------------------------------------------------

GATE_TAG="INTEGRATION"
# What a failing scenario's transcript is grepped for, to say WHY in one line.
FAILURE_SUMMARY_RE='\[SCENARIO\]|reason=|SCRIPT ERROR|HARD_TIMEOUT'
FAILURE_SUMMARY_LINES=3
# The header line a scenario declares its coverage on. Matched at the start of
# a `##` comment line inside the header block only.
COVERS_KEY='covers:'
# A `--system` argument is ONE directory name under the source dir — never a
# path, never a pattern. Bounded so an over-long argument is refused, not
# interpolated.
SYSTEM_NAME_MAX=64
# A covers entry is a repo-relative path prefix. Bounded for the same reason.
COVERS_ENTRY_MAX=200

usage() {
	cat <<'USAGE_EOF'
usage: integration.sh --all | --smoke | --system <dir> | --diff <ref> | <name>...
       integration.sh --help | --self-test

Runs integration scenarios, each in its own process, N in parallel. Each one
goes through scenario.sh, so the isolation is a process boundary rather than a
convention.

  --all            every discovered scenario
  --smoke          just GDK_SMOKE_SCENARIO
  --system <dir>   every discovered scenario under <source dir>/<dir>/ — the
                   DIRECTORY, so `--system threads` is tests/integration/threads/.
                   A directory that does not exist is a usage error; one that
                   holds no gate is a FAIL, never a green run over nothing
  --diff <ref>     the scenarios whose `## covers:` header names a path the
                   working tree changed against <ref> (plus every touched
                   scenario, plus GDK_SMOKE_SCENARIO). A change to the tier's
                   own ground selects everything. Scenarios declaring nothing
                   are reported; they ride only --all
  <name>...        an explicit list, discovery bypassed
  --self-test      prove the argument handling, the discovery filter, the
                   header reader and the slicing against a fixture tree,
                   booting nothing
  --help           this message

A scenario header (the leading comment block) declares, one `##` line each:
  ## Boots because: tests/unit/<path> cannot <what only a boot can assert>
  ## covers: systems/<x>, resources/<y>.gd     repo-relative path prefixes

Env: GDK_SCENARIO_SOURCE_DIR    where scenario scripts live
     GDK_SCENARIO_RUNNER        scenario.sh, relative to this file
     GDK_INTEGRATION_INFRA_RE   basenames that are fixtures, not scenarios
     GDK_CAPTURE_SUFFIX_RE      basenames that are capture TOOLS, not gates
     GDK_CAPTURE_GATE_RE        captures that are gates after all
     GDK_SMOKE_SCENARIO         the scenario --smoke runs and every --diff carries
     GDK_SCENARIO_SUBSTRATE_RE  repo-relative paths that are the tier's ground
     GDK_JOBS                   parallelism (default: cores - 2, floor 1)
Exit: 0 all passed | 1 any failed, or a slice selecting nothing | 2 usage/harness error
USAGE_EOF
}

# --- discovery ---------------------------------------------------------------
# discover_gate_files [dir] — every scenario FILE the sweep should boot, as a
# path under dir, one per line, sorted. Takes the directory as an argument so
# the self-test can point it at a fixture tree instead of planting probe files
# in the real one.
discover_gate_files() {
	local dir="${1:-$GDK_SCENARIO_SOURCE_DIR}"
	[ -d "$dir" ] || return 0
	# support/ holds shared fixtures, not scenarios.
	find "$dir" -type f -name '*.gd' -not -path '*/support/*' 2>/dev/null \
		| awk -v infra="$GDK_INTEGRATION_INFRA_RE" -v tool="$GDK_CAPTURE_SUFFIX_RE" \
		      -v gate="$GDK_CAPTURE_GATE_RE" '
			{ name = $0; sub(/.*\//, "", name); sub(/\.gd$/, "", name) }
			name ~ infra { next }
			!(name ~ tool) { print; next }
			gate != "" && name ~ gate { print }
		' \
		| sort
}

# discover_all [dir] — the same set, as scenario NAMES, one per line.
discover_all() {
	discover_gate_files "$@" | sed 's|.*/||; s|\.gd$||' | sort -u
}

# names_of — file paths on stdin, scenario names out.
names_of() {
	sed 's|.*/||; s|\.gd$||' | sort -u
}

# capture_gate_names — the keep-list, one name per line.
capture_gate_names() {
	[ -n "$GDK_CAPTURE_GATE_RE" ] || return 0
	printf '%s\n' "$GDK_CAPTURE_GATE_RE" | tr '|' '\n' | tr -d '^()$'
}

# --- --system <dir> ----------------------------------------------------------
# system_name_defect <arg> — prints why <arg> is not a system directory name
# and returns 0; silent and 1 when it is one. The grammar is one path segment:
# letters, digits, `_`, `-`; bounded. Everything else — a separator, a dot
# segment, a glob, a space, a leading dash — is refused before any lookup, so
# a `--system` can never name a path outside the source dir or read as a flag.
system_name_defect() {
	local arg="${1-}"
	if [ -z "$arg" ]; then echo "is empty"; return 0; fi
	if [ "${#arg}" -gt "$SYSTEM_NAME_MAX" ]; then echo "is longer than $SYSTEM_NAME_MAX characters"; return 0; fi
	case "$arg" in
		-*) echo "starts with a dash — a flag, not a directory"; return 0 ;;
		*/*|*\\*) echo "carries a path separator — one directory name, not a path"; return 0 ;;
		.|..) echo "is a dot segment"; return 0 ;;
	esac
	if ! printf '%s' "$arg" | grep -qE '^[A-Za-z0-9_-]+$'; then
		echo "carries a character outside [A-Za-z0-9_-]"; return 0
	fi
	return 1
}

# select_system <name> [dir] — the gate files under <dir>/<name>/, one per
# line. Exit 2, saying which directories DO exist, when there is no such
# directory: a typo must not resolve to nothing quietly, and must never
# resolve to everything.
select_system() {
	local name="$1" root="${2:-$GDK_SCENARIO_SOURCE_DIR}"
	if [ ! -d "$root/$name" ]; then
		echo "[$GATE_TAG] no directory '$name' under $root/. The systems there:" >&2
		find "$root" -mindepth 1 -maxdepth 1 -type d -not -name 'support' -not -name '.*' 2>/dev/null \
			| sed 's|.*/||' | sort | tr '\n' ' ' | sed 's/^/    /; s/ $/\n/' >&2
		return 2
	fi
	discover_gate_files "$root/$name"
}

# --- the header: `## covers:` ------------------------------------------------
# covers_entry_defect <entry> — prints why <entry> is not a repo-relative path
# prefix and returns 0; silent and 1 when it is one. The runner only ever
# COMPARES an entry as a string, so a hostile one can select nothing — but a
# malformed declaration is a declaration that lies, and this is the grammar
# `check test-shape` refuses it under.
covers_entry_defect() {
	local entry="${1-}"
	if [ -z "$entry" ]; then echo "is empty"; return 0; fi
	if [ "${#entry}" -gt "$COVERS_ENTRY_MAX" ]; then echo "is longer than $COVERS_ENTRY_MAX characters"; return 0; fi
	case "$entry" in
		/*) echo "is absolute — a covers entry is repo-relative"; return 0 ;;
		*://*) echo "carries a scheme — write the repo-relative path, not res://"; return 0 ;;
		*\\*) echo "carries a backslash"; return 0 ;;
		*[\*\?\[]*) echo "carries a glob — a covers entry is a literal prefix"; return 0 ;;
		*[[:space:]]*) echo "carries whitespace"; return 0 ;;
		.|..|./*|../*|*/.|*/..|*/./*|*/../*) echo "carries a dot segment"; return 0 ;;
	esac
	return 1
}

# scenario_covers <file> — the prefixes the scenario's header declares, one per
# line, a trailing `/` dropped. The header is the leading run of blank, comment,
# `extends`, `class_name` and annotation lines; a `## covers:` below the first
# statement is prose, not a declaration. Several `## covers:` lines union. An
# entry the grammar refuses is dropped here — the gate reports it.
scenario_covers() {
	local entry
	awk -v key="$COVERS_KEY" '
		/^[[:space:]]*$/ || /^#/ || /^extends[[:space:]]/ || /^class_name[[:space:]]/ || /^@/ {
			if ($0 ~ ("^##[[:space:]]*" key)) {
				sub("^##[[:space:]]*" key "[[:space:]]*", "")
				n = split($0, parts, ",")
				for (i = 1; i <= n; i++) {
					e = parts[i]
					gsub(/^[[:space:]]+|[[:space:]]+$/, "", e)
					if (e != "") print e
				}
			}
			next
		}
		{ exit }
	' "$1" | while IFS= read -r entry; do
		entry="${entry%/}"
		covers_entry_defect "$entry" >/dev/null && continue
		printf '%s\n' "$entry"
	done
}

# covers_table [dir] — one tab-separated line per declared entry:
#   <name>\t<file>\t<entry>
# and one line with an EMPTY entry for a scenario declaring nothing, so a single
# pass reads both the slice and the finding.
covers_table() {
	local file name entry n
	while IFS= read -r file; do
		name="${file##*/}"; name="${name%.gd}"; n=0
		while IFS= read -r entry; do
			[ -n "$entry" ] || continue
			printf '%s\t%s\t%s\n' "$name" "$file" "$entry"; n=$((n + 1))
		done < <(scenario_covers "$file")
		[ "$n" -gt 0 ] || printf '%s\t%s\t\n' "$name" "$file"
	done < <(discover_gate_files "${1:-$GDK_SCENARIO_SOURCE_DIR}")
}

# --- --diff <ref> ------------------------------------------------------------
# ref_defect <arg> — prints why <arg> cannot be handed to git as a ref and
# returns 0; silent and 1 otherwise. Resolution is git's; this only keeps a
# flag or whitespace from being read as one.
ref_defect() {
	local arg="${1-}"
	if [ -z "$arg" ]; then echo "is empty"; return 0; fi
	case "$arg" in
		-*) echo "starts with a dash — a flag, not a ref"; return 0 ;;
		*[[:space:]]*) echo "carries whitespace"; return 0 ;;
	esac
	return 1
}

# touched_paths <ref> — every repo-relative path the working tree differs from
# <ref> on (staged or not), plus every untracked file git does not ignore: a
# new scenario is a touched scenario before it is ever added. Exit 2 when
# <ref> does not name a commit.
touched_paths() {
	local ref="$1"
	git rev-parse --verify --quiet "${ref}^{commit}" >/dev/null 2>&1 || return 2
	{ git diff --name-only "$ref" -- 2>/dev/null
	  git ls-files --others --exclude-standard 2>/dev/null; } | sort -u
}

# touched_substrate — touched paths on stdin; the ones that are the tier's own
# ground out.
touched_substrate() {
	local p base
	while IFS= read -r p; do
		[ -n "$p" ] || continue
		base="${p##*/}"; base="${base%.gd}"
		if printf '%s\n' "$p" | grep -qE "$GDK_SCENARIO_SUBSTRATE_RE" \
			|| printf '%s\n' "$base" | grep -qE "$GDK_INTEGRATION_INFRA_RE"; then
			printf '%s\n' "$p"
		fi
	done
}

# slice_for_touched [dir] — touched paths on stdin; out, sorted:
#   SELECT\t<name>       a scenario whose file was touched, or whose covers
#                        entry is a component-boundary prefix of a touched path
#   UNDECLARED\t<name>   a scenario with no covers entry — never selected here
# `systems/alpha` covers `systems/alpha/x.gd` and not `systems/alphabet/x.gd`.
slice_for_touched() {
	local touched
	touched="$(cat)"
	covers_table "${1:-}" | awk -F'\t' -v touched="$touched" '
		BEGIN { n = split(touched, t, "\n") }
		function covered(prefix,   i) {
			for (i = 1; i <= n; i++) {
				if (t[i] == "") continue
				if (t[i] == prefix || index(t[i], prefix "/") == 1) return 1
			}
			return 0
		}
		{
			if ($3 == "") undeclared[$1] = 1
			else if (covered($3)) selected[$1] = 1
			if (covered($2)) selected[$1] = 1
		}
		END {
			for (s in selected) print "SELECT\t" s
			for (u in undeclared) print "UNDECLARED\t" u
		}
	' | sort
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
# Boots nothing: discovery, the header reader and the slicing are pure
# filesystem and text, which is exactly why they are written as functions over
# a directory and a list.
self_test() {
	local scratch rc out failures=0 cases=0 name bad

	miss() { echo "  MISS — $1" >&2; failures=$((failures + 1)); }

	cases=$((cases + 1))
	rc=0; bash "$0" --help >/dev/null 2>&1 || rc=$?
	[ "$rc" -eq 0 ] || miss "--help should exit 0, got $rc"

	cases=$((cases + 1))
	rc=0; bash "$0" >/dev/null 2>&1 || rc=$?
	[ "$rc" -eq 2 ] || miss "no argument should exit 2, got $rc"

	cases=$((cases + 1))
	rc=0; bash "$0" --system >/dev/null 2>&1 || rc=$?
	[ "$rc" -eq 2 ] || miss "--system with no directory should exit 2, got $rc"

	cases=$((cases + 1))
	rc=0; bash "$0" --diff >/dev/null 2>&1 || rc=$?
	[ "$rc" -eq 2 ] || miss "--diff with no ref should exit 2, got $rc"

	cases=$((cases + 1))
	rc=0; bash "$0" --diff HEAD extra >/dev/null 2>&1 || rc=$?
	[ "$rc" -eq 2 ] || miss "--diff takes exactly one ref, got $rc"

	cases=$((cases + 1))
	rc=0; bash "$0" '' >/dev/null 2>&1 || rc=$?
	[ "$rc" -eq 2 ] || miss "an EMPTY name should exit 2, got $rc"

	cases=$((cases + 1))
	rc=0; bash "$0" ../escape >/dev/null 2>&1 || rc=$?
	[ "$rc" -eq 2 ] || miss "a name carrying a separator should exit 2, got $rc"

	cases=$((cases + 1))
	rc=0; bash "$0" --self-test extra >/dev/null 2>&1 || rc=$?
	[ "$rc" -eq 2 ] || miss "--self-test takes no argument, got $rc"

	# --- the --system grammar: one directory name, nothing else ------------
	# shellcheck disable=SC2016  # the `$` is the hostile input, not an expansion
	for bad in '' '.' '..' 'a/b' 'a\b' '/abs' '*' 'a b' '-x' 'a;b' 'a$b' \
		'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'; do
		cases=$((cases + 1))
		system_name_defect "$bad" >/dev/null || miss "--system admits '$bad'"
		cases=$((cases + 1))
		rc=0; bash "$0" --system "$bad" >/dev/null 2>&1 || rc=$?
		[ "$rc" -eq 2 ] || miss "--system '$bad' should exit 2 before any lookup, got $rc"
	done
	cases=$((cases + 1))
	system_name_defect 'spatial_zones-2' >/dev/null && miss "--system refuses an ordinary directory name"

	# --- the --diff ref grammar --------------------------------------------
	for bad in '' '-x' '--all' 'HEAD extra' ' '; do
		cases=$((cases + 1))
		ref_defect "$bad" >/dev/null || miss "--diff admits ref '$bad'"
		cases=$((cases + 1))
		rc=0; bash "$0" --diff "$bad" >/dev/null 2>&1 || rc=$?
		[ "$rc" -eq 2 ] || miss "--diff '$bad' should exit 2, got $rc"
	done
	cases=$((cases + 1))
	ref_defect 'origin/main' >/dev/null && miss "--diff refuses an ordinary ref"

	# --- the covers-entry grammar ------------------------------------------
	for bad in '' '/abs/x' '../x' 'a/../b' './x' 'a/./b' '.' '..' 'res://x' \
		'a b' 'a\b' 'systems/*' 'a?b' 'a[b]' \
		"$(printf 'a%.0s' $(seq 1 201))"; do
		cases=$((cases + 1))
		covers_entry_defect "$bad" >/dev/null || miss "covers admits '$bad'"
	done
	for name in 'systems/alpha' 'resources/beta.gd' 'a-b_c/d.e'; do
		cases=$((cases + 1))
		covers_entry_defect "$name" >/dev/null && miss "covers refuses an ordinary prefix '$name'"
	done

	# --- the discovery filter, against a fixture tree ------------------------
	scratch="$(mktemp -d "${TMPDIR:-/tmp}/gdk-integration-selftest.XXXXXX")" || return 1
	mkdir -p "$scratch/protocol" "$scratch/support" "$scratch/tools_only" "$scratch/alpha"
	: > "$scratch/protocol/protocol_boot.gd"
	: > "$scratch/plain_gate.gd"
	: > "$scratch/thing_capture.gd"
	: > "$scratch/scenario_base.gd"
	: > "$scratch/support/helper.gd"
	: > "$scratch/tools_only/eyes_capture.gd"
	out="$(discover_all "$scratch" | tr '\n' ' ')"

	cases=$((cases + 1))
	[ "$out" = "plain_gate protocol_boot " ] \
		|| miss "discovery, got '$out'"

	# Each exclusion said separately, because each is a different claim: a
	# capture is a tool, a base class is not a scenario, support/ is fixtures.
	cases=$((cases + 1))
	printf '%s\n' "$out" | grep -q 'thing_capture' \
		&& miss "a capture TOOL still boots in the sweep"
	cases=$((cases + 1))
	printf '%s\n' "$out" | grep -q 'scenario_base' \
		&& miss "a fixture base class was discovered as a scenario"
	cases=$((cases + 1))
	printf '%s\n' "$out" | grep -q 'helper' \
		&& miss "a support/ fixture was discovered as a scenario"

	# A keep-listed capture comes BACK into the sweep — the exception has to
	# work, or the list is decoration.
	cases=$((cases + 1))
	out="$(GDK_CAPTURE_GATE_RE='^(thing_capture)$' discover_all "$scratch" | tr '\n' ' ')"
	[ "$out" = "plain_gate protocol_boot thing_capture " ] \
		|| miss "the keep-list did not restore the gate, got '$out'"

	# --- --system selects the DIRECTORY ------------------------------------
	cases=$((cases + 1))
	out="$(select_system protocol "$scratch" | names_of | tr '\n' ' ')"
	[ "$out" = "protocol_boot " ] || miss "--system protocol should select the directory, got '$out'"
	# The old matcher took a NAME PREFIX: `--system pro` found protocol_boot,
	# `--system threads` found nothing in threads/. Neither may hold now.
	cases=$((cases + 1))
	rc=0; select_system pro "$scratch" >/dev/null 2>&1 || rc=$?
	[ "$rc" -eq 2 ] || miss "--system with a name PREFIX, not a directory, should exit 2, got $rc"
	cases=$((cases + 1))
	rc=0; select_system nope "$scratch" >/dev/null 2>&1 || rc=$?
	[ "$rc" -eq 2 ] || miss "--system with no such directory should exit 2, got $rc"
	cases=$((cases + 1))
	out="$(select_system nope "$scratch" 2>&1 >/dev/null || true)"
	printf '%s\n' "$out" | grep -q 'protocol' \
		|| miss "the no-such-directory refusal does not name the directories that exist"
	cases=$((cases + 1))
	out="$(select_system tools_only "$scratch" | tr '\n' ' ')"
	[ -z "$out" ] || miss "a directory of capture tools should select nothing, got '$out'"
	cases=$((cases + 1))
	rc=0; GDK_SCENARIO_SOURCE_DIR="$scratch" GDK_SCENARIO_RUNNER="$(basename "$0")" \
		bash "$0" --system tools_only >/dev/null 2>&1 || rc=$?
	[ "$rc" -eq 1 ] || miss "an EMPTY slice must FAIL (exit 1), got $rc"
	cases=$((cases + 1))
	rc=0; GDK_SCENARIO_SOURCE_DIR="$scratch" GDK_SCENARIO_RUNNER="$(basename "$0")" \
		bash "$0" --system nope >/dev/null 2>&1 || rc=$?
	[ "$rc" -eq 2 ] || miss "--system naming no directory must exit 2 through the CLI, got $rc"

	# --- the header reader --------------------------------------------------
	cat > "$scratch/alpha/alpha_flow.gd" <<'FIXTURE_EOF'
extends "res://tests/integration/scenario_base.gd"

## Boots because: tests/unit/alpha/test_alpha.gd cannot drive the live flow.
## covers: systems/alpha, resources/beta.gd/ , /abs/nope, ../escape

## More prose, then the body.
func run() -> void:
	## covers: systems/not_a_declaration
	pass
FIXTURE_EOF
	cases=$((cases + 1))
	out="$(scenario_covers "$scratch/alpha/alpha_flow.gd" | tr '\n' ' ')"
	[ "$out" = "systems/alpha resources/beta.gd " ] \
		|| miss "the header reader: trimmed entries, trailing slash dropped, hostile ones dropped, body ignored — got '$out'"
	cases=$((cases + 1))
	out="$(scenario_covers "$scratch/plain_gate.gd" | tr '\n' ' ')"
	[ -z "$out" ] || miss "an undeclared scenario should read as no entries, got '$out'"

	# --- the slice ----------------------------------------------------------
	cases=$((cases + 1))
	out="$(printf '%s\n' systems/alpha/thing.gd | slice_for_touched "$scratch" | tr '\t\n' ': ')"
	[ "$out" = "SELECT:alpha_flow UNDECLARED:plain_gate UNDECLARED:protocol_boot " ] \
		|| miss "a touched covered path should select the declaring scenario and report the rest, got '$out'"
	cases=$((cases + 1))
	out="$(printf '%s\n' systems/alphabet/thing.gd | slice_for_touched "$scratch" | grep -c SELECT)"
	[ "$out" = "0" ] || miss "a prefix must match at a path-component boundary (alphabet is not alpha)"
	cases=$((cases + 1))
	out="$(printf '%s\n' resources/beta.gd | slice_for_touched "$scratch" | grep -c 'SELECT.alpha_flow')"
	[ "$out" = "1" ] || miss "a covered FILE entry should match the touched file exactly"
	cases=$((cases + 1))
	out="$(printf '%s\n' "$scratch/plain_gate.gd" | slice_for_touched "$scratch" | grep -c 'SELECT.plain_gate')"
	[ "$out" = "1" ] || miss "a touched scenario file selects itself, declared or not"
	cases=$((cases + 1))
	out="$(printf '%s\n' systems/zeta/x.gd | slice_for_touched "$scratch" | grep -c SELECT)"
	[ "$out" = "0" ] || miss "an unrelated touched path should select nothing"
	cases=$((cases + 1))
	out="$(printf '' | slice_for_touched "$scratch" | grep -c SELECT)"
	[ "$out" = "0" ] || miss "no touched paths should select nothing"

	# --- the tier's ground --------------------------------------------------
	cases=$((cases + 1))
	out="$(printf '%s\n' tests/support/maps/x.tscn tests/integration/scenario_base.gd systems/alpha/x.gd tools/dev/runners/scenario.sh \
		| touched_substrate | tr '\n' ' ')"
	[ "$out" = "tests/support/maps/x.tscn tests/integration/scenario_base.gd tools/dev/runners/scenario.sh " ] \
		|| miss "substrate: fixtures, the base class and the runners are ground; a system is not — got '$out'"

	# --- every keep-listed gate must EXIST and survive the filter ------------
	# A renamed or deleted keep-listed capture must fail loudly here, never
	# drop silently out of --all.
	while IFS= read -r name; do
		[ -n "$name" ] || continue
		cases=$((cases + 1))
		if [ -z "$(find "$GDK_SCENARIO_SOURCE_DIR" -type f -name "$name.gd" 2>/dev/null)" ]; then
			miss "GDK_CAPTURE_GATE_RE names '$name', which has no file"
			continue
		fi
		discover_all | grep -qx "$name" \
			|| miss "keep-listed gate '$name' is missing from the sweep"
	done < <(capture_gate_names)

	cases=$((cases + 1))
	[ "$(detect_jobs)" -ge 1 ] \
		|| miss "the job count must be at least 1"

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
SLICE_NOTE=""
case "${1:-}" in
	"") echo "[$GATE_TAG] nothing to run. See --help." >&2; usage >&2; exit 2 ;;
	# `while read`, not `mapfile`: macOS ships bash 3.2.
	--all) while IFS= read -r n; do NAMES+=("$n"); done < <(discover_all) ;;
	--smoke) NAMES=("$GDK_SMOKE_SCENARIO") ;;
	--system)
		[ "$#" -eq 2 ] || { echo "[$GATE_TAG] --system takes exactly one directory name. See --help." >&2; exit 2; }
		if defect="$(system_name_defect "${2-}")"; then
			echo "[$GATE_TAG] --system '${2-}' $defect. See --help." >&2; exit 2
		fi
		files="$(select_system "$2")" || exit 2
		while IFS= read -r n; do [ -n "$n" ] && NAMES+=("$n"); done < <(printf '%s\n' "$files" | names_of)
		# A directory that exists and yields no gate: say what it holds
		# instead, so "no scenarios matched" can never be read as "no coverage".
		if [ "${#NAMES[@]}" -eq 0 ]; then
			held="$(find "$GDK_SCENARIO_SOURCE_DIR/$2" -type f -name '*.gd' 2>/dev/null | wc -l | tr -d ' ')"
			echo "[$GATE_TAG] FAIL — the slice '$2' is EMPTY: $held .gd file(s) under $GDK_SCENARIO_SOURCE_DIR/$2/, none a gate (capture tools and infra are not swept; reach one by name)" >&2
			exit 1
		fi
		dropped=$(( $(find "$GDK_SCENARIO_SOURCE_DIR/$2" -type f -name '*.gd' -not -path '*/support/*' 2>/dev/null | wc -l) - ${#NAMES[@]} ))
		[ "$dropped" -le 0 ] || SLICE_NOTE="; $dropped file(s) in $2/ are tools or infra and not swept"
		;;
	--diff)
		[ "$#" -eq 2 ] || { echo "[$GATE_TAG] --diff takes exactly one ref. See --help." >&2; exit 2; }
		if defect="$(ref_defect "${2-}")"; then
			echo "[$GATE_TAG] --diff ref '${2-}' $defect. See --help." >&2; exit 2
		fi
		git rev-parse --is-inside-work-tree >/dev/null 2>&1 \
			|| { echo "[$GATE_TAG] --diff needs a git repository at $REPO_ROOT" >&2; exit 2; }
		touched="$(touched_paths "$2")" \
			|| { echo "[$GATE_TAG] --diff: '$2' does not name a commit" >&2; exit 2; }
		touched_count="$(printf '%s' "$touched" | grep -c . || true)"
		substrate="$(printf '%s\n' "$touched" | touched_substrate)"
		if [ -n "$substrate" ]; then
			while IFS= read -r n; do NAMES+=("$n"); done < <(discover_all)
			echo "[$GATE_TAG] --diff $2: the change touches the tier's own ground — every scenario is the honest slice:"
			printf '%s\n' "$substrate" | sed 's/^/    /'
			SLICE_NOTE="; substrate touched, whole tier"
		else
			slice="$(printf '%s\n' "$touched" | slice_for_touched)"
			undeclared="$(printf '%s\n' "$slice" | awk -F'\t' '$1 == "UNDECLARED" { print $2 }')"
			undeclared_count="$(printf '%s' "$undeclared" | grep -c . || true)"
			while IFS= read -r n; do [ -n "$n" ] && NAMES+=("$n"); done \
				< <({ printf '%s\n' "$slice" | awk -F'\t' '$1 == "SELECT" { print $2 }'; printf '%s\n' "$GDK_SMOKE_SCENARIO"; } | sort -u)
			echo "[$GATE_TAG] --diff $2: $touched_count touched path(s) → ${#NAMES[@]} scenario(s) incl. smoke"
			if [ "$undeclared_count" -gt 0 ]; then
				echo "[$GATE_TAG] UNDECLARED: $undeclared_count scenario(s) carry no '## $COVERS_KEY' header and cannot be sliced to — they ride only --all:"
				printf '%s\n' "$undeclared" | sed 's/^/    /'
			fi
			SLICE_NOTE="; slice of $touched_count touched path(s), $undeclared_count undeclared scenario(s) ride only --all"
		fi
		;;
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
#
# `bash "$SCENARIO_SH"`, never a bare exec of it. This is the spelling
# Makefile.devkit and install-runners' own next step tell a consumer to use,
# and the reason is that a checkout can carry the file without its mode bits —
# a zip, a `git config core.fileMode false` tree, an older install. Exec'ing it
# directly returned 126 from every scenario, and `Permission denied` matches
# nothing in FAILURE_SUMMARY_RE, so the FAILURES block named each scenario and
# printed nothing under it.
# shellcheck disable=SC2016
printf '%s\n' "${NAMES[@]}" | xargs -P "$JOBS" -I{} bash -c '
	name="$1"; tmp="$2"
	export GDK_HEADLESS_HOME="$tmp/home-$name"
	out="$(bash "'"$SCENARIO_SH"'" "$name" 2>&1)"; code=$?
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
		# A transcript matching NO summary line still has to say something:
		# the summary patterns describe how a scenario reports its own
		# failure, and the failures that matter most are the ones that never
		# got that far. The tail is the fallback, never nothing.
		if grep -qE "$FAILURE_SUMMARY_RE" "$TMP/$n.log" 2>/dev/null; then
			grep -hE "$FAILURE_SUMMARY_RE" "$TMP/$n.log" 2>/dev/null \
				| head -"$FAILURE_SUMMARY_LINES" | sed 's/^/      /'
		else
			tail -"$FAILURE_SUMMARY_LINES" "$TMP/$n.log" 2>/dev/null \
				| sed 's/^/      /'
		fi
	done
fi

echo ""
echo "[$GATE_TAG] SUMMARY: $PASS passed, $FAIL failed (of ${#NAMES[@]})$SLICE_NOTE"
[ "$FAIL" -eq 0 ] || exit 1
exit 0
