#!/usr/bin/env bash
# integration.sh — the INTEGRATION tier: boot / cross-system scenarios, each in
# its OWN process (isolation by construction), N in PARALLEL (speed from cores).
#
# Every scenario runs through the cold path — one scenario.sh, one fresh engine
# — so no scenario can observe another's global state. That is the tier's whole
# contract; the parallelism is what makes paying for it affordable.
#
# WARM MODE (#36, opt-in: GDK_INTEGRATION_WARM=1). A cold boot costs 13-15 s of
# CPU before the first assertion, so warm mode splits the --all/--diff/--system
# roster into GDK_JOBS slices, balanced by count, and runs each through ONE
# `scenario.sh --suite` — one boot per worker, a fresh World per scenario,
# under the contract scenario.sh's header states and YOUR runner implements.
# A scenario whose header carries `## Isolated because: <reason>` never goes
# warm; every scenario a worker hands back (a crash, a stall) runs cold after
# it. With --diff, a warm failure is rerun COLD, alone: passing, it prints
# WARM-ONLY and counts green. Unset, every path is the cold one, byte for byte.
#
# A SCENARIO DECLARES WHAT IT COVERS. Its header — the leading run of comment
# lines — carries `## covers: <path>[, <path>…]`, repo-relative prefixes of the
# code it exercises, and `--diff <ref>` maps a change to the slice that
# declares it: touched paths → covering scenarios, plus the smoke scenario. A
# scenario declaring nothing cannot be sliced to and is REPORTED (it rides only
# --all); `check test-shape` is the gate that refuses one. `--all` stays the
# milestone gate and the gate for a change to the tier's own ground.
#
# THIS FILE OWNS THE ROSTER. What --all boots — the source dir minus support/,
# the capture tools (less the keep-list) and the infra basenames — is decided
# by the config block below and the GDK_* env, which a consumer edits and no
# TOML reader can see. So `--list` prints it, booting nothing, and
# `check test-shape` asks the header rule of exactly that set rather than of a
# second census of its own.
#
# Usage:
#   tools/dev/runners/integration.sh --all              # every scenario
#   tools/dev/runners/integration.sh --list             # the roster --all would boot, boots nothing
#   tools/dev/runners/integration.sh --smoke            # just the smoke scenario
#   tools/dev/runners/integration.sh --system protocol  # the tests/integration/protocol/ directory
#   tools/dev/runners/integration.sh --diff HEAD        # what the uncommitted change covers, + smoke
#   tools/dev/runners/integration.sh --diff HEAD --no-rerun   # a sweep failure is red at once
#   tools/dev/runners/integration.sh boot_a boot_b      # an explicit list
#   GDK_JOBS=4 tools/dev/runners/integration.sh --all   # cap the parallelism
#   GDK_INTEGRATION_WARM=1 tools/dev/runners/integration.sh --all   # one boot per worker
#   GDK_INTEGRATION_WARM=1 tools/dev/runners/integration.sh --all --cold   # not this run
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
# slice, because every scenario boots on them — the runners, the library, and
# the scenario base/runner scripts in the source dir. An ERE over REPO-RELATIVE
# paths. A basename matching GDK_INTEGRATION_INFRA_RE is ground too, wherever
# it lives. Shared FIXTURES are not ground: see GDK_SCENARIO_FIXTURE_DIR.
# shellcheck disable=SC2016  # the `$` inside sed's bracket is a character to escape
GDK_SCENARIO_SUBSTRATE_RE="${GDK_SCENARIO_SUBSTRATE_RE:-^tools/dev/runners/|^tools/dev/gdk_runners\.sh$|^$(printf '%s' "${GDK_SCENARIO_SOURCE_DIR%/}" | sed 's/[].[\*^$()+?{|]/\\&/g')/(scenario_base|scenario_runner)\.gd$}"
# The fixture root: scenes, resources and helper scripts scenarios LOAD. A
# touched file under it selects every scenario whose text names it — its
# res:// path in any quote or none, its uid://, a class_name it declares —
# followed transitively through the fixture root. A touched fixture NO
# scenario names boots the whole tier and says so: a reference the scan cannot
# see (a built path) must not become a silent zero. A root that is not a
# directory under the repo is a config error (exit 2); a touch under
# tests/support/ (1.3.0's ground) outside a root set elsewhere boots the tier.
GDK_SCENARIO_FIXTURE_DIR="${GDK_SCENARIO_FIXTURE_DIR:-tests/support/}"
# --diff reruns each FAILED scenario once, alone, after the sweep; one that
# passes alone counts green and prints a FLAKE line. 0 turns it off (as does
# --no-rerun). --all and named runs never rerun.
GDK_INTEGRATION_RERUN="${GDK_INTEGRATION_RERUN:-1}"
# 1 runs --all/--diff/--system WARM: one scenario.sh --suite per job, each
# booting once. Turn it on only once your scenario runner implements the
# contract in scenario.sh's header. 0 (the default) is the cold path; --cold
# forces it for one run.
GDK_INTEGRATION_WARM="${GDK_INTEGRATION_WARM:-0}"
GDK_RUNNERS_LIB="${GDK_RUNNERS_LIB:-$(dirname "${BASH_SOURCE[0]}")/../gdk_runners.sh}"
# Env: GDK_JOBS  parallelism (default: cores - 2, floor 1)
# -----------------------------------------------------------------------------

# This runner only READS git; an optional lock taken by a status/diff here
# must never collide with a hook or an agent writing the same repo. It sources
# no library, so it says so itself.
export GIT_OPTIONAL_LOCKS=0

GATE_TAG="INTEGRATION"
# What a failing scenario's transcript is grepped for, to say WHY in one line.
FAILURE_SUMMARY_RE='\[SCENARIO\]|reason=|SCRIPT ERROR|HARD_TIMEOUT'
FAILURE_SUMMARY_LINES=3
# The header line a scenario declares its coverage on. Matched at the start of
# a `##` comment line inside the header block only.
COVERS_KEY='covers:'
# The header line that keeps a scenario out of warm mode, with its reason.
ISOLATED_KEY='Isolated because:'
# A `--system` argument is ONE directory name under the source dir — never a
# path, never a pattern. Bounded so an over-long argument is refused, not
# interpolated.
SYSTEM_NAME_MAX=64
# A covers entry is a repo-relative path prefix. Bounded for the same reason.
COVERS_ENTRY_MAX=200

usage() {
	cat <<'USAGE_EOF'
usage: integration.sh --all | --smoke | --system <dir> | --diff <ref> [--no-rerun] [--cold] | <name>...
       integration.sh --help | --self-test

Runs integration scenarios, each in its own process, N in parallel. Each one
goes through scenario.sh, so the isolation is a process boundary rather than a
convention.

  --all            every discovered scenario
  --list           the roster: every scenario file --all would boot, one
                   repo-relative path per line, sorted, booting nothing —
                   what `check test-shape` asks the header rule of. An
                   EMPTY roster is exit 1
  --smoke          just GDK_SMOKE_SCENARIO
  --system <dir>   every discovered scenario under <source dir>/<dir>/ — the
                   DIRECTORY, so `--system threads` is tests/integration/threads/.
                   A directory that does not exist is a usage error; one that
                   holds no gate is a FAIL, never a green run over nothing
  --diff <ref>     the scenarios whose `## covers:` header names a path the
                   working tree changed against <ref> (plus every touched
                   scenario, plus GDK_SMOKE_SCENARIO). A touched file under
                   GDK_SCENARIO_FIXTURE_DIR selects every scenario whose text
                   names it, transitively — its res:// path, its uid://, a
                   class_name it declares; one NO scenario names boots the
                   whole tier and says so. A change to the tier's own ground
                   selects everything.
                   Scenarios declaring nothing are reported; they ride only
                   --all. Each scenario that FAILS in the sweep is rerun once,
                   alone: passing alone, it counts green and prints
                   `  FLAKE  <name> — failed in the sweep, passed alone`
  --no-rerun       with --diff: report a sweep failure red at once
  --cold           with GDK_INTEGRATION_WARM=1: run this one cold
  <name>...        an explicit list, discovery bypassed
  --self-test      prove the argument handling, the discovery filter, the
                   header reader, the slicing, the rerun and the cache
                   precheck against fixture trees and stub runners, booting
                   no engine
  --help           this message

A scenario header (the leading comment block) declares, one `##` line each:
  ## Boots because: tests/unit/<path> cannot <what only a boot can assert>
  ## covers: systems/<x>, resources/<y>.gd     repo-relative path prefixes
  ## Isolated because: <reason>                never run warm (the reason is
                                               required: an empty one exits 2)

Warm mode (GDK_INTEGRATION_WARM=1, --all/--diff/--system only): the roster is
split into GDK_JOBS slices, each run by ONE `scenario.sh --suite` (one boot
per worker); `## Isolated because:` scenarios and every scenario a worker
hands back (`  WARM-ABORT  after <name> — N scenario(s) handed back`) run
cold after. With --diff, a warm failure reruns cold, alone; passing, it prints
`  WARM-ONLY  <name> — failed warm, passed cold: …` and counts green. The
SUMMARY adds `(K flaky, W warm-only)` and `; warm A, cold B, handed back C`,
which must sum to the roster or the run FAILS naming what is missing; a
`[INTEGRATION] WALL:` line splits the wall clock between the two phases.

Env: GDK_SCENARIO_SOURCE_DIR    where scenario scripts live
     GDK_SCENARIO_RUNNER        scenario.sh, relative to this file
     GDK_INTEGRATION_INFRA_RE   basenames that are fixtures, not scenarios
     GDK_CAPTURE_SUFFIX_RE      basenames that are capture TOOLS, not gates
     GDK_CAPTURE_GATE_RE        captures that are gates after all
     GDK_SMOKE_SCENARIO         the scenario --smoke runs and every --diff carries
     GDK_SCENARIO_SUBSTRATE_RE  repo-relative paths that are the tier's ground
     GDK_SCENARIO_FIXTURE_DIR   the fixture root --diff slices by reference
                                (default tests/support/; one that is not a
                                directory under the repo exits 2)
     GDK_INTEGRATION_RERUN      0 turns off --diff's rerun-alone (default 1)
     GDK_INTEGRATION_WARM       1 runs --all/--diff/--system warm (default 0)
     GDK_JOBS                   parallelism (default: cores - 2, floor 1)
Sets: GDK_SCENARIO_IN_SWEEP=1 on every job, the rerun alone included — the
     runner's import-cache recovery must not remove a .godot its peers, or a
     playing session, are using. So before a --diff/--all sweep boots
     anything, a stale cache (.godot/uid_cache.bin missing, or older than a
     tracked *.uid, *.import or project.godot) is repaired ONCE by
     import_cache.sh beside this file; if that fails, the sweep does not
     start (exit 1).
Cost: every scenario FILE is one cold engine boot, whatever its length, so a
     run ends with `[INTEGRATION] BOOTS: <n> scenario(s) booted, <cpu>` above
     its SUMMARY — the census Makefile.tiers files on the gate's cost row.
     Merging two scenarios saves a boot; trimming lines saves nothing.
     Warm mode counts one boot per worker, however many scenarios it ran.
Exit: 0 all passed | 1 any failed, or a slice selecting nothing | 2 usage/harness error
USAGE_EOF
}

# --- discovery ---------------------------------------------------------------
# discover_gate_files [dir] — THE ROSTER: every scenario FILE the sweep should
# boot, as a path under dir, one per line, sorted. Takes the directory as an
# argument so the self-test can point it at a fixture tree instead of planting
# probe files in the real one. `--list` prints exactly this.
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
		# After the ONE trailing slash scenario_covers drops, a slash with
		# nothing after it is an empty segment: `a//b`, `a//`, `a/`. Compared as
		# a prefix it can never match a path git names; the gate refuses it by
		# the same name, so the two cannot disagree.
		*//*|*/) echo "carries an empty segment (a doubled slash)"; return 0 ;;
	esac
	return 1
}

# scenario_covers <file> — the prefixes the scenario's header declares, one per
# line, ONE trailing `/` dropped (exactly one, as the gate drops it — a second
# is an empty segment the grammar refuses). The header is the leading run of blank, comment,
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

# scenario_isolation <file> — the reason the header gives on its first
# `## Isolated because:` line, printed (EMPTY when the line gives none) and 0;
# silent and 1 when the header declares no isolation. The header is the same
# leading block scenario_covers reads.
scenario_isolation() {
	local found
	found="$(awk -v key="$ISOLATED_KEY" '
		/^[[:space:]]*$/ || /^#/ || /^extends[[:space:]]/ || /^class_name[[:space:]]/ || /^@/ {
			if ($0 ~ ("^##[[:space:]]*" key)) {
				sub("^##[[:space:]]*" key "[[:space:]]*", "")
				sub(/[[:space:]]+$/, "")
				print "D" $0
				exit
			}
			next
		}
		{ exit }
	' "$1")"
	[ -n "$found" ] || return 1
	printf '%s\n' "${found#D}"
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

# touched_paths <ref> — every REPO_ROOT-relative path the working tree differs
# from <ref> on (staged or not), plus every untracked file git does not ignore:
# a new scenario is a touched scenario before it is ever added. Exit 2 when
# <ref> does not name a commit.
#
# Relative to REPO_ROOT (the cwd), NOT the git toplevel — a covers entry is
# repo-relative, and a project below the toplevel (game/ in a monorepo) would
# otherwise compare `game/systems/alpha/x.gd` against `systems/alpha` and
# match nothing. A change outside the project is dropped: nothing repo-relative
# can name it. And the bytes, not git's C-quoting: under core.quotePath (the
# default) a non-ASCII path prints as `"caf\303\251.gd"`, a prefix of nothing.
touched_paths() {
	local ref="$1"
	git rev-parse --verify --quiet "${ref}^{commit}" >/dev/null 2>&1 || return 2
	{ git -c core.quotePath=false diff --name-only --relative "$ref" -- 2>/dev/null
	  git -c core.quotePath=false ls-files --others --exclude-standard 2>/dev/null; } | sort -u
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
	# The touched list reaches awk as a FILE, never a `-v` value: BWK awk (macOS)
	# refuses a newline inside one, so a list of two paths broke the slice.
	local touched
	touched="$(mktemp "${TMPDIR:-/tmp}/gdk-touched.XXXXXX")" || return 2
	cat > "$touched"
	covers_table "${1:-}" | awk -F'\t' '
		FNR == NR { if ($0 != "") t[++n] = $0; next }
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
	' "$touched" - | sort
	rm -f "$touched"
}

# --- --diff: a touched FIXTURE selects the scenarios that load it -------------
# A file REFERENCES a fixture when its text holds any of the fixture's names:
#   - its res:// path, as a substring — any quote, none, a const, a threaded
#     load, an ext_resource, a string property;
#   - its basename after a `/` or a quote — a relative path ("../support/x.gd");
#   - its own uid://, read from its .uid or .import sidecar, or from the
#     [gd_scene|gd_resource … uid="…"] header of a .tscn/.tres — a whole token;
#   - a class_name it declares — a whole word.
# The scan does NOT enumerate call forms: the form that was missing from a list
# is the scenario that dropped out of the slice without a word. A comment or
# a string naming a fixture over-selects, which is the safe direction. Pure
# text — nothing boots. The files that may reference are the .gd/.tscn/.tres
# under the fixture root and every scenario, read once.
# shellcheck disable=SC2016  # an awk program, not a shell expansion
FIXTURE_SLICE_AWK='
	function slurp(f,   s, line) {
		s = ""
		while ((getline line < f) > 0) s = s line "\n"
		close(f)
		return s
	}
	function word_char(c) { return c ~ /[A-Za-z0-9_]/ }
	# has_word — w occurs in t with no word character on either side.
	function has_word(t, w,   p, off, before) {
		off = 0
		while ((p = index(substr(t, off + 1), w)) > 0) {
			p += off
			before = (p == 1) ? "" : substr(t, p - 1, 1)
			if (!word_char(before) && !word_char(substr(t, p + length(w), 1))) return 1
			off = p
		}
		return 0
	}
	function first_uid(t) {
		return match(t, /uid:\/\/[A-Za-z0-9_]+/) ? substr(t, RSTART, RLENGTH) : ""
	}
	# uid_of — the fixture own uid://, or "".
	function uid_of(f,   line, u) {
		if (f ~ /\.(tscn|tres)$/) {
			line = ""; getline line < f; close(f)
			return (line ~ /^\[gd_(scene|resource)[ \t]/) ? first_uid(line) : ""
		}
		u = first_uid(slurp(f ".uid"))
		return u != "" ? u : first_uid(slurp(f ".import"))
	}
	# names_of — fills need[1..n] / whole[1..n] with the names f goes by.
	function names_of(f,   n, u, t, k, lines, m, i, b) {
		n = 0
		need[++n] = "res://" f; whole[n] = 0
		# A relative path ("../support/x.gd") ends in the basename after a
		# slash or a quote; another file of the same basename over-selects.
		b = f; sub(/.*\//, "", b)
		need[++n] = "/" b; whole[n] = 0
		need[++n] = "\"" b; whole[n] = 0
		need[++n] = "\047" b; whole[n] = 0
		u = uid_of(f)
		if (u != "") { need[++n] = u; whole[n] = 1 }
		if (f ~ /\.gd$/) {
			t = (f in text) ? text[f] : slurp(f)
			k = split(t, lines, "\n")
			for (i = 1; i <= k; i++)
				if (match(lines[i], /(^|[^A-Za-z0-9_])class_name[ \t]+[A-Za-z_][A-Za-z0-9_]*/)) {
					m = substr(lines[i], RSTART, RLENGTH)
					sub(/.*class_name[ \t]+/, "", m)
					need[++n] = m; whole[n] = 1
				}
		}
		return n
	}
	function refers(t, n,   k) {
		for (k = 1; k <= n; k++)
			if (whole[k] ? has_word(t, need[k]) : index(t, need[k]) > 0) return 1
		return 0
	}
	FILENAME == ARGV[1] { if ($0 != "") fx[++nf] = $0; next }
	FILENAME == ARGV[2] { if ($0 != "") { gate[$0] = 1; if (!($0 in text)) { file[++nu] = $0; text[$0] = "" } }; next }
	FILENAME == ARGV[3] { if ($0 != "" && !($0 in text)) { file[++nu] = $0; text[$0] = "" }; next }
	END {
		for (j = 1; j <= nu; j++) text[file[j]] = slurp(file[j])
		for (i = 1; i <= nf; i++) {
			split("", seen); split("", queue)
			key = fx[i]; sub(/\.(uid|import)$/, "", key)
			seen[key] = 1; queue[1] = key; head = 1; tail = 1
			# The reverse closure: whoever names anything already reached,
			# until nothing new is reached.
			while (head <= tail) {
				n = names_of(queue[head++])
				for (j = 1; j <= nu; j++) {
					f = file[j]
					if (!(f in seen) && refers(text[f], n)) { seen[f] = 1; queue[++tail] = f }
				}
			}
			found = 0
			for (s in seen) if (s in gate) {
				name = s; sub(/.*\//, "", name); sub(/\.gd$/, "", name)
				print "FIXTURE\t" fx[i] "\t" name; found++
			}
			if (found == 0) print "ORPHAN\t" fx[i]
		}
	}
'

# fixture_slice [scenario dir] [fixture dir] — touched REPO-relative paths on
# stdin; the ones under the fixture dir are looked up, and out, sorted:
#   FIXTURE\t<fixture>\t<name>   a scenario that references <fixture>,
#                                directly or through other fixtures
#   ORPHAN\t<fixture>            a touched fixture NO scenario references
# A `.uid` / `.import` sidecar is looked up as the file it belongs to. Paths are
# relative to the cwd, which is REPO_ROOT, as res:// is. Sorted bytewise.
fixture_slice() {
	local sdir="${1:-$GDK_SCENARIO_SOURCE_DIR}" fdir="${2:-$GDK_SCENARIO_FIXTURE_DIR}" touched gates files
	sdir="${sdir%/}"; fdir="${fdir%/}"
	touched="$(mktemp "${TMPDIR:-/tmp}/gdk-fixtures.XXXXXX")" || return 2
	gates="$(mktemp "${TMPDIR:-/tmp}/gdk-gates.XXXXXX")" || { rm -f "$touched"; return 2; }
	files="$(mktemp "${TMPDIR:-/tmp}/gdk-refs.XXXXXX")" || { rm -f "$touched" "$gates"; return 2; }
	awk -v root="$fdir/" 'index($0, root) == 1' > "$touched"
	if [ ! -s "$touched" ]; then rm -f "$touched" "$gates" "$files"; return 0; fi
	discover_gate_files "$sdir" > "$gates"
	# BSD find prints `dir//x` for a trailing slash, hence the strip above.
	# What may reference a fixture: the fixture root AND everything under the
	# scenario dir — a scenario_base, a runner or a scenario-local support
	# script that loads a fixture on a scenario's behalf is a path to it.
	find "$fdir" "$sdir" -type f \( -name '*.gd' -o -name '*.tscn' -o -name '*.tres' \) 2>/dev/null \
		| LC_ALL=C sort -u > "$files"
	awk "$FIXTURE_SLICE_AWK" "$touched" "$gates" "$files" | LC_ALL=C sort -u
	rm -f "$touched" "$gates" "$files"
}

# fixture_root <value> — GDK_SCENARIO_FIXTURE_DIR as one spelling, `a/b/`: a
# leading `./` and extra trailing `/` stripped. Returns 1, the reason on
# stdout, when it is not a directory under the cwd (REPO_ROOT). The stock
# default is exempt from existing: a project with no fixtures has none, and a
# touch under a missing root still boots the tier as ORPHAN.
FIXTURE_DIR_STOCK="tests/support/"
fixture_root() {
	local d="$1"
	while [ "${d#./}" != "$d" ]; do d="${d#./}"; done
	while [ "${d%/}" != "$d" ]; do d="${d%/}"; done
	case "$d" in
		''|.) echo "names no directory"; return 1 ;;
		/*|..|../*|*/..|*/../*) echo "is not a path under the repo root"; return 1 ;;
	esac
	d="$d/"
	if [ ! -d "$d" ] && [ "$d" != "$FIXTURE_DIR_STOCK" ]; then
		echo "is not a directory under the repo root"; return 1
	fi
	printf '%s\n' "$d"
}

# --- the import cache, checked BEFORE the sweep -------------------------------
# A merge of worktree lanes brings in `.uid` sidecars the cache has never seen,
# and every scenario then fails `uid index is STALE`. scenario.sh can detect
# that, but inside a sweep it must not remove the `.godot` its peers boot in —
# so the repair has to happen once, serially, before anything boots.
IMPORT_CACHE_STAMP=".godot/uid_cache.bin"
IMPORT_CACHE_RUNNER="import_cache.sh"

# import_inputs — the tracked files an import pass reads the cache from,
# NUL-separated: project.godot, every *.uid and *.import. Outside a git work
# tree, the same set by find (minus .godot/).
import_inputs() {
	if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
		git ls-files -z -- 'project.godot' '*.uid' '*.import' 2>/dev/null
	else
		find . -path ./.godot -prune -o -type f \
			\( -name project.godot -o -name '*.uid' -o -name '*.import' \) -print0 2>/dev/null
	fi
}

# import_cache_stale — prints why the import cache is stale and returns 0;
# silent and 1 when it is current. The cwd is the project root.
import_cache_stale() {
	local f
	if [ ! -f "$IMPORT_CACHE_STAMP" ]; then echo "$IMPORT_CACHE_STAMP is missing"; return 0; fi
	while IFS= read -r -d '' f; do
		if [ "$f" -nt "$IMPORT_CACHE_STAMP" ]; then
			echo "${f#./} is newer than $IMPORT_CACHE_STAMP"; return 0
		fi
	done < <(import_inputs)
	return 1
}

# --- git on a SCRATCH repo ----------------------------------------------------
# A hook exports GIT_DIR / GIT_WORK_TREE / GIT_INDEX_FILE, and a bare `git init`
# under them re-initialises the HOST repo rather than the scratch one. Every git
# call the self-test makes on a fixture goes through one of these.
unset_git_env() {
	# Repeated until gone: each `unset` pops one scope, and a prefix
	# assignment over an exported variable is two.
	local v
	for v in GIT_DIR GIT_WORK_TREE GIT_INDEX_FILE GIT_OBJECT_DIRECTORY GIT_COMMON_DIR \
		GIT_ALTERNATE_OBJECT_DIRECTORIES; do
		while [ -n "${!v+x}" ]; do unset "$v" 2>/dev/null || break; done
	done
}
# scratch_git <dir> <git args…>
# `env -u`, not `unset`: under a caller's prefix assignment (`GIT_DIR=x f`)
# bash's `unset` pops only that temporary binding, and a hook's exported
# GIT_DIR underneath comes back — the host repo gets the commit.
scratch_git() {
	env -u GIT_DIR -u GIT_WORK_TREE -u GIT_INDEX_FILE -u GIT_OBJECT_DIRECTORY \
		-u GIT_COMMON_DIR -u GIT_ALTERNATE_OBJECT_DIRECTORIES git -C "$@"
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

# --- what the tier costs: BOOTS ----------------------------------------------
# A scenario FILE is one cold engine, and the boot is the cost: measured on a
# consumer's tier, scenarios of 114, 358 and 325 lines each cost ~3.3s
# standalone — the line count does not move the number. So the census this
# runner reports is the boots, with the CPU they burned beside it: merging two
# scenarios saves a boot, trimming lines saves nothing. Makefile.tiers reads
# the count off the BOOTS line into the gate's cost row, where agentic-sdlc's
# `[tests] cases` is the ceiling on it.

# cpu_ms <XmY.YYYs> — one field of `times`, in milliseconds; empty when it is
# not that shape. Bash writes the fraction with the locale's radix.
cpu_ms() {
	local t="$1" m s whole frac
	case "$t" in *m*s) ;; *) return 0 ;; esac
	m="${t%%m*}"; s="${t#*m}"; s="${s%s}"
	whole="${s%%[.,]*}"; frac="${s#"$whole"}"; frac="${frac#[.,]}"
	printf -v frac '%-3.3s' "$frac"; frac="${frac// /0}"
	case "$m" in ''|*[!0-9]*) return 0 ;; esac
	case "$whole" in ''|*[!0-9]*) return 0 ;; esac
	case "$frac" in *[!0-9]*) return 0 ;; esac
	printf '%s\n' $(( (10#$m * 60 + 10#$whole) * 1000 + 10#$frac ))
}

# children_cpu <scratch file> — set CHILD_CPU_MS to the CPU (user + sys) every
# child this shell has reaped has spent; empty when `times` cannot be read. It
# SETS rather than prints: inside a `$( )` it would read a subshell's `times`,
# and a subshell has reaped nothing.
children_cpu() {
	local user='' sys='' u s
	CHILD_CPU_MS=''
	times > "$1" 2>/dev/null || return 0
	{ read -r _ _ && read -r user sys; } < "$1" 2>/dev/null || return 0
	u="$(cpu_ms "$user")"; s="$(cpu_ms "$sys")"
	[ -n "$u" ] && [ -n "$s" ] || return 0
	CHILD_CPU_MS=$((u + s))
}

# boots_line <boots> [cpu ms] — the census line. Makefile.tiers reads the count
# back off `BOOTS: <n> `, so that prefix is contract.
boots_line() {
	local n="$1" ms="${2-}" cost='CPU unmeasured' per
	if [ -n "$ms" ]; then
		cost="$((ms / 1000)).$((ms % 1000 / 100))s CPU"
		if [ "$n" -gt 0 ]; then
			per=$((ms / n))
			printf -v per '%d.%02d' $((per / 1000)) $((per % 1000 / 10))
			cost="$cost, ${per}s per boot"
		fi
	fi
	printf '[%s] BOOTS: %s scenario(s) booted, %s\n' "$GATE_TAG" "$n" "$cost"
}

# keep_list_cases — self_test's keep-list cases, one per keep-listed name:
# the gate has a file, and it survives the filter into the sweep. Uses
# self_test's `cases` and `miss`.
keep_list_cases() {
	local swept name
	# The sweep is read ONCE and matched with no pipe: under pipefail,
	# `discover_all | grep -q` exits on the match, the producer takes SIGPIPE
	# (Linux, a sweep longer than the pipe buffer) and the pipeline fails.
	swept="$(discover_all)"
	while IFS= read -r name; do
		[ -n "$name" ] || continue
		cases=$((cases + 1))
		if [ -z "$(find "$GDK_SCENARIO_SOURCE_DIR" -type f -name "$name.gd" 2>/dev/null)" ]; then
			miss "GDK_CAPTURE_GATE_RE names '$name', which has no file"
			continue
		fi
		grep -qxF -- "$name" <<<"$swept" \
			|| miss "keep-listed gate '$name' is missing from the sweep"
	done < <(capture_gate_names)
}

# mono_fixture <dir> — commit <dir> as its own scratch repo, with core.quotePath
# on (git's default made explicit). Every call is scratch_git: the caller may
# be a hook with the host repo's git env exported.
mono_fixture() {
	scratch_git "$1" init -q && scratch_git "$1" config core.quotePath true \
		&& scratch_git "$1" add -A \
		&& scratch_git "$1" -c user.name=t -c user.email=t@t -c commit.gpgsign=false commit -q -m fixture
} >/dev/null 2>&1

# cache_cases <dir> — self_test's import-cache precheck cases, by stub
# timestamps in a scratch repo; nothing imports, nothing boots. Uses self_test's
# `cases` and `miss`.
cache_cases() {
	local dir="$1" out rc
	mkdir -p "$dir/.godot" "$dir/a"
	: > "$dir/project.godot"; : > "$dir/a/x.gd.uid"; : > "$dir/a/y.png.import"
	{ scratch_git "$dir" init -q && scratch_git "$dir" add -A; } >/dev/null 2>&1 \
		|| miss "the cache git fixture could not be built"
	touch -t 202001010000 "$dir/project.godot" "$dir/a/x.gd.uid" "$dir/a/y.png.import"
	cases=$((cases + 1))
	out="$(unset_git_env; cd "$dir" && import_cache_stale)"
	[ "$out" = "$IMPORT_CACHE_STAMP is missing" ] || miss "a missing cache is stale, got '$out'"
	touch -t 202101010000 "$dir/$IMPORT_CACHE_STAMP"
	cases=$((cases + 1))
	rc=0; (unset_git_env; cd "$dir" && import_cache_stale >/dev/null) || rc=$?
	[ "$rc" -eq 1 ] || miss "a cache newer than every tracked input is current, got $rc"
	touch -t 202201010000 "$dir/a/x.gd.uid"
	cases=$((cases + 1))
	out="$(unset_git_env; cd "$dir" && import_cache_stale)"
	[ "$out" = "a/x.gd.uid is newer than $IMPORT_CACHE_STAMP" ] \
		|| miss "a tracked .uid newer than the cache (a merged lane) is stale, got '$out'"
	touch -t 202001010000 "$dir/a/x.gd.uid"; touch -t 202201010000 "$dir/project.godot"
	cases=$((cases + 1))
	out="$(unset_git_env; cd "$dir" && import_cache_stale)"
	[ "$out" = "project.godot is newer than $IMPORT_CACHE_STAMP" ] \
		|| miss "a project.godot newer than the cache is stale, got '$out'"
	touch -t 202001010000 "$dir/project.godot"; touch -t 202201010000 "$dir/a/untracked.gd.uid"
	cases=$((cases + 1))
	rc=0; (unset_git_env; cd "$dir" && import_cache_stale >/dev/null) || rc=$?
	[ "$rc" -eq 1 ] || miss "an UNTRACKED newer .uid is not a stale cache, got $rc"
}

# sweep_cases <proj> — self_test's end-to-end cases: THIS file installed at the
# stock depth of a scratch repo, beside a stub scenario.sh (flaky fails its
# first boot, red every boot) and a stub import_cache.sh. The stubs record
# every boot and repair in order, so what is asserted is what the sweep DID.
# Uses self_test's `cases` and `miss`. Each case is one chain of claims ending
# in `|| miss`, the rest of self_test's shape.
# shellcheck disable=SC2015
sweep_cases() {
	local proj="$1" state="$1.state" runners out rc n
	runners="$proj/tools/dev/runners"
	mkdir -p "$runners" "$proj/tests/integration" "$proj/tests/support" "$proj/.godot"
	cp "$0" "$runners/integration.sh"
	cat > "$runners/scenario.sh" <<'STUB_EOF'
#!/usr/bin/env bash
state="$GDK_STUB_STATE"; name="$1"
echo "$name" >> "$state/order"
echo "$name ${GDK_SCENARIO_IN_SWEEP:-unset}" >> "$state/env"
n=$(( $(cat "$state/$name.n" 2>/dev/null || echo 0) + 1 )); echo "$n" > "$state/$name.n"
case "$name" in
	flaky) [ "$n" -ge 2 ] || { echo "[SCENARIO] $name FAIL — load flake"; exit 1; } ;;
	red*) echo "[SCENARIO] $name FAIL — real"; exit 1 ;;
esac
echo "[SCENARIO] $name PASS"
STUB_EOF
	cat > "$runners/import_cache.sh" <<'STUB_EOF'
#!/usr/bin/env bash
echo import >> "$GDK_STUB_STATE/order"
[ "${GDK_STUB_IMPORT_RC:-0}" -eq 0 ] || exit "$GDK_STUB_IMPORT_RC"
mkdir -p .godot && touch .godot/uid_cache.bin
STUB_EOF
	: > "$proj/project.godot"
	for n in flaky red smoke green; do printf 'extends Node\n' > "$proj/tests/integration/$n.gd"; done
	printf 'extends Node\n' > "$proj/tests/support/orphan.gd"
	printf '.godot/\n' > "$proj/.gitignore"
	{ scratch_git "$proj" init -q && scratch_git "$proj" add -A \
		&& scratch_git "$proj" -c user.name=t -c user.email=t@t -c commit.gpgsign=false commit -q -m proj; } >/dev/null 2>&1 \
		|| miss "the sweep git fixture could not be built"
	touch -t 202001010000 "$proj/project.godot"; touch "$proj/$IMPORT_CACHE_STAMP"

	# sweep <args…> — one run of the installed copy, fresh stub state, the
	# caller's GDK_* and git env out of the way.
	sweep() {
		rm -rf "$state"; mkdir -p "$state"
		( unset_git_env
		  unset GDK_SCENARIO_SUBSTRATE_RE GDK_INTEGRATION_INFRA_RE GDK_CAPTURE_SUFFIX_RE GDK_CAPTURE_GATE_RE
		  GDK_STUB_STATE="$state" GDK_JOBS=2 GDK_SCENARIO_RUNNER=scenario.sh GDK_SMOKE_SCENARIO=smoke \
			GDK_SCENARIO_SOURCE_DIR=tests/integration GDK_SCENARIO_FIXTURE_DIR="${GDK_STUB_FIXTURE_DIR:-tests/support/}" \
			GDK_INTEGRATION_RERUN="${GDK_INTEGRATION_RERUN-1}" bash "$runners/integration.sh" "$@" 2>&1 )
	}
	flake_line() { printf '  FLAKE  %s — failed in the sweep, passed alone' "$1"; }

	# Six runs, each a real sweep of stubs — every one a claim the pure
	# functions above cannot make: what was booted, in what order, how often.

	# A flake alone, over a STALE cache: the repair ran once, before any boot;
	# the scenario failed in the sweep, passed alone, and the run is GREEN.
	rm -f "$proj/$IMPORT_CACHE_STAMP"
	echo '# touched' >> "$proj/tests/integration/flaky.gd"
	cases=$((cases + 1))
	out="$(sweep --diff HEAD)"; rc=$?
	[ "$rc" -eq 0 ] && grep -qxF -- "$(flake_line flaky)" <<<"$out" \
		&& grep -qF 'SUMMARY: 2 passed (1 flaky), 0 failed (of 2)' <<<"$out" \
		|| miss "a scenario that fails in the sweep and passes alone is a FLAKE and counts green (rc $rc): $out"
	cases=$((cases + 1))
	[ "$(head -1 "$state/order")" = import ] && [ "$(grep -c '^import$' "$state/order")" = 1 ] \
		&& grep -qF 'import cache is stale' <<<"$out" \
		|| miss "a stale cache is repaired once, before the sweep boots anything: $(tr '\n' ' ' < "$state/order")"
	# The rerun is alone, but the cache was repaired ONCE above: scenario.sh
	# must not repair it again in the tree (rm -rf .godot, an editor pass).
	cases=$((cases + 1))
	[ "$(grep -c '^flaky ' "$state/env")" = 2 ] && ! grep -qv ' 1$' "$state/env" \
		|| miss "every boot, the rerun alone included, carries GDK_SCENARIO_IN_SWEEP=1: $(tr '\n' '|' < "$state/env")"

	echo '# touched' >> "$proj/tests/integration/red.gd"
	cases=$((cases + 1))
	out="$(sweep --diff HEAD)"; rc=$?
	[ "$rc" -eq 1 ] && grep -qxF -- "$(flake_line flaky)" <<<"$out" \
		&& ! grep -qF -- "$(flake_line red)" <<<"$out" \
		&& grep -qF 'SUMMARY: 2 passed (1 flaky), 1 failed (of 3)' <<<"$out" \
		&& [ "$(cat "$state/red.n")" = 2 ] \
		|| miss "a scenario that fails in the sweep AND alone stays red, after exactly one rerun (rc $rc): $out"
	cases=$((cases + 1))
	out="$(sweep --diff HEAD --no-rerun)"; rc=$?
	[ "$rc" -eq 1 ] && ! grep -qF 'FLAKE' <<<"$out" && [ "$(cat "$state/flaky.n")" = 1 ] \
		&& grep -qF 'SUMMARY: 1 passed, 2 failed (of 3)' <<<"$out" \
		|| miss "--no-rerun reports a sweep failure red at once (rc $rc): $out"
	cases=$((cases + 1))
	out="$(GDK_INTEGRATION_RERUN=maybe sweep --diff HEAD)"; rc=$?
	[ "$rc" -eq 2 ] || miss "a GDK_INTEGRATION_RERUN that is not 0 or 1 is a config error (exit 2), got $rc"
	# Past the cap (max of 3 and 10% of the slice) nothing reruns: the answer
	# is already red, and serial cold boots would only make it slower.
	for n in red2 red3 red4; do echo 'extends Node' > "$proj/tests/integration/$n.gd"; done
	cases=$((cases + 1))
	out="$(sweep --diff HEAD)"; rc=$?
	[ "$rc" -eq 1 ] && grep -qF 'over the rerun cap of 3' <<<"$out" \
		&& [ "$(cat "$state/flaky.n")" = 1 ] && ! grep -qF 'FLAKE' <<<"$out" \
		|| miss "past the rerun cap nothing reruns and the failures stay red (rc $rc): $out"
	rm -f "$proj/tests/integration/red2.gd" "$proj/tests/integration/red3.gd" "$proj/tests/integration/red4.gd"

	# A touched fixture no scenario references boots the tier and says why —
	# and the env spelling of --no-rerun holds on the way.
	echo '# touched' >> "$proj/tests/support/orphan.gd"
	cases=$((cases + 1))
	out="$(GDK_INTEGRATION_RERUN=0 sweep --diff HEAD)"; rc=$?
	grep -qxF '[INTEGRATION] fixture tests/support/orphan.gd is referenced by no scenario — booting the tier' <<<"$out" \
		&& [ "$(sort "$state/order" | tr '\n' ' ')" = "flaky green red smoke " ] \
		|| miss "an unreferenced fixture falls back to the whole tier with its line: $out"
	cases=$((cases + 1))
	[ "$rc" -eq 1 ] && [ "$(cat "$state/flaky.n")" = 1 ] \
		|| miss "GDK_INTEGRATION_RERUN=0 turns the rerun off (rc $rc): $out"

	# The fixture root, as configured (M2): a leading ./ is the same root; a
	# root that does not exist is a config error, never a slice of smoke.
	cases=$((cases + 1))
	out="$(GDK_INTEGRATION_RERUN=0 GDK_STUB_FIXTURE_DIR=./tests/support sweep --diff HEAD)"; rc=$?
	grep -qxF '[INTEGRATION] fixture tests/support/orphan.gd is referenced by no scenario — booting the tier' <<<"$out" \
		&& [ "$(sort "$state/order" | tr '\n' ' ')" = "flaky green red smoke " ] \
		|| miss "GDK_SCENARIO_FIXTURE_DIR=./tests/support is tests/support/ (rc $rc): $out"
	cases=$((cases + 1))
	out="$(GDK_STUB_FIXTURE_DIR=tests/suport/ sweep --diff HEAD)"; rc=$?
	[ "$rc" -eq 2 ] && grep -qF "GDK_SCENARIO_FIXTURE_DIR='tests/suport/'" <<<"$out" && [ ! -s "$state/order" ] \
		|| miss "a fixture root that does not exist exits 2 naming it, before any boot (rc $rc): $out"
	# A root elsewhere: tests/support/ was 1.3.0's ground, so a touch there
	# that the fixture rule no longer looks at still boots the tier.
	mkdir -p "$proj/tests/fixtures"
	cases=$((cases + 1))
	out="$(GDK_INTEGRATION_RERUN=0 GDK_STUB_FIXTURE_DIR=tests/fixtures sweep --diff HEAD)"; rc=$?
	grep -qxF '[INTEGRATION] tests/support/orphan.gd is outside the fixture root tests/fixtures/ — booting the tier' <<<"$out" \
		&& [ "$(sort "$state/order" | tr '\n' ' ')" = "flaky green red smoke " ] \
		|| miss "a touch under tests/support/ outside a configured fixture root boots the tier with its line (rc $rc): $out"

	# A repair that fails starts nothing, and names itself.
	rm -f "$proj/$IMPORT_CACHE_STAMP"
	cases=$((cases + 1))
	out="$(GDK_STUB_IMPORT_RC=1 sweep --diff HEAD)"; rc=$?
	[ "$rc" -eq 1 ] && [ "$(tr '\n' ' ' < "$state/order")" = "import " ] \
		&& grep -qF "$IMPORT_CACHE_RUNNER" <<<"$out" \
		|| miss "a failed repair must stop the sweep (exit 1, naming it) before any boot (rc $rc): $out"
	rm -rf "$state"
}

# warm_cases <proj> — self_test's warm-mode cases: THIS file installed at the
# stock depth of a scratch repo, beside a stub scenario.sh that speaks the
# --suite results protocol (a `--suite` call writes results/unrun into
# GDK_SCENARIO_SUITE_RESULTS; `leaky` fails warm and passes cold; the suite
# crashes at GDK_STUB_CRASH, handing back the rest). Every call's argv is
# recorded, so what is asserted is what the run BOOTED. Uses self_test's
# `cases` and `miss`.
# shellcheck disable=SC2015
warm_cases() {
	local proj="$1" state="$1.state" runners out rc n
	runners="$proj/tools/dev/runners"
	mkdir -p "$runners" "$proj/tests/integration" "$proj/.godot"
	cp "$0" "$runners/integration.sh"
	cat > "$runners/scenario.sh" <<'STUB_EOF'
#!/usr/bin/env bash
echo "$*" >> "$GDK_STUB_STATE/argv"
echo "$* ${GDK_SCENARIO_IN_SWEEP:-unset}" >> "$GDK_STUB_STATE/env"
if [ "$1" = --suite ]; then
	shift; out="$GDK_SCENARIO_SUITE_RESULTS"; gone=0
	for name in "$@"; do
		if [ "$gone" -eq 1 ] || [ "$name" = "${GDK_STUB_CRASH:-}" ]; then
			gone=1; echo "$name" >> "$out/unrun"; continue
		fi
		case "$name" in
			leaky) printf '%s\t1\n' "$name" >> "$out/results"; echo "[SCENARIO] $name FAIL — warm" > "$out/$name.log" ;;
			*) printf '%s\t0\n' "$name" >> "$out/results"; echo "[SCENARIO] $name PASS" > "$out/$name.log" ;;
		esac
	done
	[ "$gone" -eq 0 ] || { echo "  WARM-ABORT  after a — n scenario(s) handed back"; exit 4; }
	exit 0
fi
echo "[SCENARIO] $1 PASS"
STUB_EOF
	: > "$proj/project.godot"
	for n in alpha beta leaky smoke; do printf 'extends Node\n' > "$proj/tests/integration/$n.gd"; done
	printf 'extends Node\n## Isolated because: it reads the process clock\n' > "$proj/tests/integration/iso.gd"
	printf '.godot/\n' > "$proj/.gitignore"
	{ scratch_git "$proj" init -q && scratch_git "$proj" add -A \
		&& scratch_git "$proj" -c user.name=t -c user.email=t@t -c commit.gpgsign=false commit -q -m proj; } >/dev/null 2>&1 \
		|| miss "the warm git fixture could not be built"
	touch -t 202001010000 "$proj/project.godot"; touch "$proj/$IMPORT_CACHE_STAMP"
	# The runners are the tier's ground: --diff HEAD is the whole roster.
	echo '# touched' >> "$runners/scenario.sh"

	warm() {
		rm -rf "$state"; mkdir -p "$state"
		( unset_git_env
		  unset GDK_SCENARIO_SUBSTRATE_RE GDK_INTEGRATION_INFRA_RE GDK_CAPTURE_SUFFIX_RE GDK_CAPTURE_GATE_RE \
			GDK_INTEGRATION_RERUN
		  GDK_STUB_STATE="$state" GDK_JOBS=2 GDK_SCENARIO_RUNNER=scenario.sh GDK_SMOKE_SCENARIO=smoke \
			GDK_SCENARIO_SOURCE_DIR=tests/integration bash "$runners/integration.sh" "$@" 2>&1 )
	}
	argv() { sort "$state/argv" | tr '\n' '|'; }

	# Two workers over alpha beta leaky smoke (iso is isolated): alpha+leaky
	# and beta+smoke. The second crashes at beta, handing back beta and smoke.
	cases=$((cases + 1))
	out="$(GDK_INTEGRATION_WARM=1 GDK_STUB_CRASH=beta warm --diff HEAD)"; rc=$?
	[ "$rc" -eq 0 ] \
		&& grep -qF '[INTEGRATION] SUMMARY: 5 passed (0 flaky, 1 warm-only), 0 failed (of 5); warm 2, cold 1, handed back 2' <<<"$out" \
		&& grep -qE '^\[INTEGRATION\] WALL: warm workers [0-9]+s, cold remainder [0-9]+s$' <<<"$out" \
		&& grep -qF '[INTEGRATION] BOOTS: 6 scenario(s) booted' <<<"$out" \
		|| miss "warm mode sums its census to the roster and boots once per worker (rc $rc): $out"
	cases=$((cases + 1))
	[ "$(argv)" = "--suite alpha leaky|--suite beta smoke|beta|iso|leaky|smoke|" ] \
		|| miss "an Isolated scenario runs cold, never warm; the handed-back ones run cold — argv '$(argv)'"
	cases=$((cases + 1))
	[ "$(wc -l < "$state/env" | tr -d ' ')" = 6 ] && ! grep -qv ' 1$' "$state/env" \
		|| miss "warm, handed-back cold and the WARM-ONLY rerun all carry GDK_SCENARIO_IN_SWEEP=1: $(tr '\n' '|' < "$state/env")"
	cases=$((cases + 1))
	grep -qxF '  WARM-ONLY  leaky — failed warm, passed cold: it leans on process state; mark it "## Isolated because:" or fix its reset' <<<"$out" \
		&& grep -qxF '  WARM-ABORT  after a — n scenario(s) handed back' <<<"$out" \
		&& ! grep -qF 'FLAKE' <<<"$out" \
		|| miss "a warm failure that passes cold prints WARM-ONLY, not FLAKE, and counts green: $out"
	cases=$((cases + 1))
	out="$(GDK_INTEGRATION_WARM=1 warm --diff HEAD --no-rerun)"; rc=$?
	[ "$rc" -eq 1 ] && ! grep -qF 'WARM-ONLY' <<<"$out" \
		&& grep -qF 'SUMMARY: 4 passed, 1 failed (of 5); warm 4, cold 1, handed back 0' <<<"$out" \
		&& grep -qF 'FAIL — warm' <<<"$out" \
		|| miss "--no-rerun leaves a warm failure red, its warm report in FAILURES (rc $rc): $out"

	# Unset, and --cold: today's argv exactly — one bare name per boot.
	cases=$((cases + 1))
	out="$(warm --diff HEAD)"; rc=$?
	[ "$rc" -eq 0 ] && [ "$(argv)" = "alpha|beta|iso|leaky|smoke|" ] \
		&& ! grep -qE 'WALL|warm' <<<"$out" \
		|| miss "with GDK_INTEGRATION_WARM unset the run is today's cold one (rc $rc, argv '$(argv)'): $out"
	cases=$((cases + 1))
	out="$(GDK_INTEGRATION_WARM=1 warm --diff HEAD --cold)"; rc=$?
	[ "$rc" -eq 0 ] && [ "$(argv)" = "alpha|beta|iso|leaky|smoke|" ] \
		|| miss "--cold forces the cold path for one run (rc $rc, argv '$(argv)')"
	cases=$((cases + 1))
	out="$(GDK_INTEGRATION_WARM=yes warm --diff HEAD)"; rc=$?
	[ "$rc" -eq 2 ] || miss "a GDK_INTEGRATION_WARM that is not 0 or 1 is a config error (exit 2), got $rc"

	printf 'extends Node\n## Isolated because:   \n' > "$proj/tests/integration/iso.gd"
	cases=$((cases + 1))
	out="$(GDK_INTEGRATION_WARM=1 warm --diff HEAD)"; rc=$?
	[ "$rc" -eq 2 ] && grep -qF 'tests/integration/iso.gd' <<<"$out" && [ ! -s "$state/argv" ] \
		|| miss "an '## Isolated because:' with no reason exits 2 naming the file, before any boot (rc $rc): $out"
	rm -rf "$state"
}

# --- --self-test -------------------------------------------------------------
# Boots nothing:discovery, the header reader and the slicing are pure
# filesystem and text, which is exactly why they are written as functions over
# a directory and a list.
self_test() {
	local scratch rc out failures=0 cases=0 name bad fx mono host host_before host_after

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
		'a b' 'a\b' 'systems/*' 'a?b' 'a[b]' 'systems//alpha' 'systems/alpha//' 'a/' \
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

	# --- --list: the roster, for the gate that asks it ------------------------
	cases=$((cases + 1))
	rc=0; bash "$0" --list extra >/dev/null 2>&1 || rc=$?
	[ "$rc" -eq 2 ] || miss "--list takes no argument, got $rc"
	cases=$((cases + 1))
	out="$(GDK_SCENARIO_SOURCE_DIR="$scratch" bash "$0" --list 2>/dev/null | names_of | tr '\n' ' ')"
	[ "$out" = "plain_gate protocol_boot " ] \
		|| miss "--list should print exactly the sweep's roster, got '$out'"
	cases=$((cases + 1))
	rc=0; GDK_SCENARIO_SOURCE_DIR="$scratch/tools_only" bash "$0" --list >/dev/null 2>&1 || rc=$?
	[ "$rc" -eq 1 ] || miss "--list over an EMPTY roster must FAIL (exit 1), got $rc"

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
	# A doubled slash: one trailing slash is spelling, two is an empty segment.
	# `systems/alpha//` lost ONE slash and compared `systems/alpha/` as a
	# prefix of `systems/alpha/x.gd` — never true — while the gate's
	# rstrip('/') passed it. Refused by name in both now.
	mkdir -p "$scratch/dbl"
	printf '## covers: systems/alpha//, systems//beta, systems/gamma/\n' > "$scratch/dbl/dbl_flow.gd"
	cases=$((cases + 1))
	out="$(scenario_covers "$scratch/dbl/dbl_flow.gd" | tr '\n' ' ')"
	[ "$out" = "systems/gamma " ] \
		|| miss "a doubled slash is an empty segment and dropped; one trailing slash is spelling — got '$out'"

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
	# TWO OR MORE touched paths — the shape a real diff has. BWK awk refused a
	# newline inside a -v string, so every multi-path slice came back empty
	# and reported nothing undeclared: a green run over the wrong set.
	cases=$((cases + 1))
	out="$(printf '%s\n' CLAUDE.md systems/alpha/thing.gd docs/x.md | slice_for_touched "$scratch" | tr '\t\n' ': ')"
	[ "$out" = "SELECT:alpha_flow UNDECLARED:plain_gate UNDECLARED:protocol_boot " ] \
		|| miss "a multi-path touched list should slice like a single one, got '$out'"

	# --- the tier's ground --------------------------------------------------
	# A fixture under tests/support/ is NOT ground (#33): one fixture edit
	# booted the whole tier when two scenarios load it. It is sliced below.
	cases=$((cases + 1))
	out="$(printf '%s\n' tests/support/maps/x.tscn tests/integration/scenario_base.gd systems/alpha/x.gd \
		tools/dev/runners/scenario.sh tools/dev/gdk_runners.sh tests/integration/scenario_runner.gd \
		| touched_substrate | tr '\n' ' ')"
	[ "$out" = "tests/integration/scenario_base.gd tools/dev/runners/scenario.sh tools/dev/gdk_runners.sh tests/integration/scenario_runner.gd " ] \
		|| miss "substrate: the base/runner scripts and the runners are ground; a fixture and a system are not — got '$out'"
	cases=$((cases + 1))
	out="$(printf '%s\n' tests/support/maps/x.tscn \
		| GDK_SCENARIO_SUBSTRATE_RE='^tests/support/' touched_substrate | tr '\n' ' ')"
	[ "$out" = "tests/support/maps/x.tscn " ] \
		|| miss "a consumer's own GDK_SCENARIO_SUBSTRATE_RE must keep its value — got '$out'"

	# --- the fixture slice: who LOADS the touched fixture ---------------------
	# Three scenarios: a preloads direct.gd; b loads mid.tscn, whose
	# ext_resource is leaf.gd (fixture → fixture → scenario); c loads nothing.
	# lone.gd is loaded by no scenario, which must fall back, not select zero.
	fx="$scratch/fx"
	mkdir -p "$fx/tests/integration" "$fx/tests/support"
	printf '%s\n' 'extends "res://tests/integration/scenario_base.gd"' \
		'const D = preload("res://tests/support/direct.gd")' > "$fx/tests/integration/a.gd"
	printf '%s\n' 'extends Node' 'func run() -> void:' \
		'	var m = load( "res://tests/support/mid.tscn" )' > "$fx/tests/integration/b.gd"
	printf '%s\n' 'extends Node' > "$fx/tests/integration/c.gd"
	printf '%s\n' '[gd_scene load_steps=2 format=3]' \
		'[ext_resource type="Script" path="res://tests/support/leaf.gd" id="1_a"]' \
		'[node name="Mid" type="Node"]' > "$fx/tests/support/mid.tscn"
	: > "$fx/tests/support/direct.gd"; : > "$fx/tests/support/leaf.gd"; : > "$fx/tests/support/lone.gd"
	cases=$((cases + 1))
	out="$(cd "$fx" && printf '%s\n' tests/support/direct.gd systems/x.gd | fixture_slice | tr '\t\n' ': ')"
	[ "$out" = "FIXTURE:tests/support/direct.gd:a " ] \
		|| miss "a fixture one of three scenarios preloads selects exactly that one — got '$out'"
	cases=$((cases + 1))
	out="$(cd "$fx" && printf '%s\n' tests/support/leaf.gd tests/support/leaf.gd.uid | fixture_slice | tr '\t\n' ': ')"
	[ "$out" = "FIXTURE:tests/support/leaf.gd:b FIXTURE:tests/support/leaf.gd.uid:b " ] \
		|| miss "a fixture reached through another fixture (and its .uid sidecar) selects the scenario — got '$out'"
	cases=$((cases + 1))
	out="$(cd "$fx" && printf '%s\n' tests/support/lone.gd | fixture_slice | tr '\t\n' ': ')"
	[ "$out" = "ORPHAN:tests/support/lone.gd " ] \
		|| miss "a fixture no scenario references must read as ORPHAN, never as zero scenarios — got '$out'"
	# Every way a scenario can name a fixture (M1): the scan does not
	# enumerate call forms. It matches the fixture's res:// path in any quote
	# or none, its uid://, and a class_name it declares as a whole word.
	printf '%s\n' 'class_name SharedThing' 'extends Node' > "$fx/tests/support/shared.gd"
	printf '%s\n' 'uid://cshared1' > "$fx/tests/support/shared.gd.uid"
	printf '%s\n' '[gd_scene format=3 uid="uid://clevel9"]' '[node name="Level" type="Node"]' > "$fx/tests/support/level.tscn"
	printf '%s\n' 'extends Node' "const S = preload('res://tests/support/shared.gd')" > "$fx/tests/integration/sq.gd"
	printf '%s\n' 'extends Node' 'const P := "res://tests/support/shared.gd"' 'func f(): return load(P)' > "$fx/tests/integration/cst.gd"
	printf '%s\n' 'extends Node' 'const U = preload("uid://cshared1")' > "$fx/tests/integration/uid.gd"
	printf '%s\n' 'extends Node' 'var x := SharedThing.new()' > "$fx/tests/integration/cls.gd"
	printf '%s\n' "extends 'res://tests/support/shared.gd'" > "$fx/tests/integration/ext.gd"
	printf '%s\n' 'extends Node' 'const R = preload("../support/shared.gd")' > "$fx/tests/integration/rel.gd"
	# Reached through a scenario base that lives in the scenario dir (C2).
	printf '%s\n' 'extends Node' > "$fx/tests/support/via.gd"
	printf '%s\n' 'extends Node' 'const V = preload("res://tests/support/via.gd")' > "$fx/tests/integration/scenario_base.gd"
	printf '%s\n' 'extends "res://tests/integration/scenario_base.gd"' > "$fx/tests/integration/beta.gd"
	printf '%s\n' 'extends Node' 'var y := SharedThingy.new()' 'const V = preload("uid://cshared12")' > "$fx/tests/integration/decoy.gd"
	printf '%s\n' 'extends Node' 'const L = preload("uid://clevel9")' > "$fx/tests/integration/lvl.gd"
	out="$(cd "$fx" && printf '%s\n' tests/support/shared.gd | fixture_slice | tr '\t\n' ': ')"
	for name in 'sq:single quotes' 'cst:a const path' 'uid:its uid://' 'cls:its class_name' "ext:extends '…'" 'rel:a relative path'; do
		cases=$((cases + 1))
		case "$out" in
			*"FIXTURE:tests/support/shared.gd:${name%%:*} "*) ;;
			*) miss "a scenario that names a fixture by ${name#*:} must be selected — got '$out'" ;;
		esac
	done
	cases=$((cases + 1))
	case "$out" in
		*:decoy\ *) miss "a longer class_name or uid is not the fixture's (whole words only) — got '$out'" ;;
	esac
	cases=$((cases + 1))
	out="$(cd "$fx" && printf '%s\n' tests/support/via.gd | fixture_slice | tr '\t\n' ': ')"
	case "$out" in
		*"FIXTURE:tests/support/via.gd:beta "*) ;;
		*) miss "a fixture a scenario reaches through a scenario base in the scenario dir selects it — got '$out'" ;;
	esac
	cases=$((cases + 1))
	out="$(cd "$fx" && printf '%s\n' tests/support/level.tscn | fixture_slice | tr '\t\n' ': ')"
	[ "$out" = "FIXTURE:tests/support/level.tscn:lvl " ] \
		|| miss "a scene fixture named by the uid in its own header selects its scenario — got '$out'"
	# The fixture root as configured: a leading ./ and the trailing / are
	# spelling; a root that is not a directory under the repo is a defect,
	# except the stock default, which a project with no fixtures lacks.
	cases=$((cases + 1))
	out="$(cd "$fx" && fixture_root ./tests/support) $(cd "$fx" && fixture_root tests/support//) $(cd "$scratch" && fixture_root tests/support/)"
	[ "$out" = "tests/support/ tests/support/ tests/support/" ] \
		|| miss "a fixture root normalises to one trailing / with no leading ./ — got '$out'"
	for bad in '' '.' './' '/abs/support' '../support' 'tests/../support' 'tests/suport' 'tests/support/direct.gd'; do
		cases=$((cases + 1))
		(cd "$fx" && fixture_root "$bad" >/dev/null) && miss "a fixture root '$bad' is admitted"
	done

	# --- touched_paths: REPO_ROOT-relative and literal ------------------------
	# `git diff --name-only` names a path relative to the git TOPLEVEL and
	# C-quotes a non-ASCII one under core.quotePath (git's default), while a
	# covers entry is REPO_ROOT-relative and literal. A project below the
	# toplevel (game/ in a monorepo) or a café.gd matched nothing, and --diff
	# under-selected to smoke without a word. A change OUTSIDE the project is
	# not a touched path of the project: nothing repo-relative can name it.
	mono="$scratch/mono"
	mkdir -p "$mono/game/systems/alpha" "$mono/game/tests/support"
	: > "$mono/README.md"; : > "$mono/game/project.godot"; : > "$mono/game/tests/support/base.gd"
	# #24: built while a HOST repo's GIT_DIR / GIT_WORK_TREE are exported, the
	# way a hook runs this self-test. A bare `git init -q .` re-initialised the
	# host (core.bare=true in a shared config) and committed into it.
	host="$scratch/host"
	mkdir -p "$host"; : > "$host/tracked"
	{ scratch_git "$host" init -q && scratch_git "$host" add -A \
		&& scratch_git "$host" -c user.name=t -c user.email=t@t -c commit.gpgsign=false commit -q -m host; } >/dev/null 2>&1 \
		|| miss "the host git fixture could not be built"
	host_before="$(scratch_git "$host" rev-parse HEAD 2>&1) $(cksum < "$host/.git/config")"
	# Exported in a subshell, as a hook exports it — a prefix assignment is a
	# different scope, and it hid this runner's own escape (C1, 1.4.0 checkup).
	( export GIT_DIR="$host/.git" GIT_WORK_TREE="$host" GIT_INDEX_FILE="$host/.git/index"
	  mono_fixture "$mono" ) || miss "the git fixture could not be built"
	cases=$((cases + 1))
	host_after="$(scratch_git "$host" rev-parse HEAD 2>&1) $(cksum < "$host/.git/config")"
	[ "$host_after" = "$host_before" ] && [ -z "$(scratch_git "$host" config --get core.quotePath)" ] \
		|| miss "the mono fixture wrote into a GIT_DIR-exported host repo (before '$host_before', after '$host_after')"
	: > "$mono/game/systems/alpha/x.gd"
	: > "$mono/game/systems/alpha/café.gd"
	echo change >> "$mono/README.md"
	echo change >> "$mono/game/tests/support/base.gd"
	cases=$((cases + 1))
	out="$( (unset_git_env; cd "$mono/game" && touched_paths HEAD) | tr '\n' ' ')"
	[ "$out" = "systems/alpha/café.gd systems/alpha/x.gd tests/support/base.gd " ] \
		|| miss "touched paths must be REPO_ROOT-relative and literal (a project under game/, a café.gd; the toplevel README is outside the project) — got '$out'"
	cases=$((cases + 1))
	rc=0; (unset_git_env; cd "$mono/game" && touched_paths no-such-ref >/dev/null 2>&1) || rc=$?
	[ "$rc" -eq 2 ] || miss "touched_paths with no such ref should return 2, got $rc"

	# --- the import-cache precheck, by timestamps ----------------------------
	cache_cases "$scratch/cache"

	# --- the sweep end to end: rerun-alone and the repair before it -----------
	sweep_cases "$scratch/proj"

	# --- warm mode end to end: the census, isolation, the hand-back -----------
	warm_cases "$scratch/warm"

	# --- every keep-listed gate must EXIST and survive the filter ------------
	# A renamed or deleted keep-listed capture must fail loudly here, never
	# drop silently out of --all.
	keep_list_cases

	# The same cases when grep -q exits before the producer finishes: a stub
	# sweep that prints the gate FIRST, then more lines than a pipe buffer
	# holds. Piped, the producer takes SIGPIPE and the gate reads as missing.
	# The subshell prints its failure and case counts: a stubbed case that
	# missed moves the first, and a keep-list that named no gate leaves the
	# second where it was — a row that checked nothing.
	cases=$((cases + 1))
	out="$(
		discover_all() {
			local i
			echo thing_capture
			for ((i = 0; i < 20000; i++)); do echo "filler_gate_$i"; done
		}
		GDK_CAPTURE_GATE_RE='^(thing_capture)$' GDK_SCENARIO_SOURCE_DIR="$scratch" \
			keep_list_cases 2>/dev/null
		echo "$failures $cases"
	)"
	[ "${out% *}" = "$failures" ] \
		|| miss "a keep-listed gate printed first in a sweep longer than a pipe buffer read as missing"
	[ "${out#* }" -gt "$cases" ] 2>/dev/null \
		|| miss "the stubbed keep-list named no gate, so the pipe-buffer row checked nothing"

	cases=$((cases + 1))
	[ "$(detect_jobs)" -ge 1 ] \
		|| miss "the job count must be at least 1"

	# --- the census: boots, and what they cost -------------------------------
	cases=$((cases + 1))
	out="$(cpu_ms 0m2.750s) $(cpu_ms 12m3,25s) $(cpu_ms 1m5s)"
	[ "$out" = "2750 723250 65000" ] \
		|| miss "a times field must read as ms whatever the radix, got '$out'"
	cases=$((cases + 1))
	out="$(cpu_ms nonsense)$(cpu_ms m.5s)$(cpu_ms 0mxs)"
	[ -z "$out" ] || miss "a field that is not XmY.YYYs must read as EMPTY, got '$out'"
	cases=$((cases + 1))
	out="$(boots_line 272 748123)"
	[ "$out" = "[$GATE_TAG] BOOTS: 272 scenario(s) booted, 748.1s CPU, 2.75s per boot" ] \
		|| miss "the BOOTS line shape, got '$out'"
	cases=$((cases + 1))
	out="$(boots_line 0 '')"
	[ "$out" = "[$GATE_TAG] BOOTS: 0 scenario(s) booted, CPU unmeasured" ] \
		|| miss "an unmeasured sweep says so rather than printing 0s, got '$out'"
	cases=$((cases + 1))
	sleep 0 & wait "$!"
	children_cpu "$scratch/times"
	case "$CHILD_CPU_MS" in
		''|*[!0-9]*) miss "this shell's own times must read as a count, got '$CHILD_CPU_MS'" ;;
	esac

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

# --no-rerun is a modifier, taken from anywhere on the line; what remains is
# the mode. The env spelling is validated here: a value that is neither 0 nor
# 1 is a config error, never a silent default.
case "$GDK_INTEGRATION_RERUN" in
	0|1) RERUN="$GDK_INTEGRATION_RERUN" ;;
	*) echo "[$GATE_TAG] GDK_INTEGRATION_RERUN='$GDK_INTEGRATION_RERUN' — expected 0 or 1" >&2; exit 2 ;;
esac
case "$GDK_INTEGRATION_WARM" in
	0|1) WARM="$GDK_INTEGRATION_WARM" ;;
	*) echo "[$GATE_TAG] GDK_INTEGRATION_WARM='$GDK_INTEGRATION_WARM' — expected 0 or 1" >&2; exit 2 ;;
esac
REST=()
for arg in "$@"; do
	case "$arg" in
		--no-rerun) RERUN=0 ;;
		--cold) WARM=0 ;;
		*) REST+=("$arg") ;;
	esac
done
set -- ${REST[@]+"${REST[@]}"}

# Resolved before the cd: a relative $0 stops resolving once the cwd moves.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)" || exit 2
REPO_ROOT="$(cd "$SCRIPT_DIR/$REPO_ROOT_FROM_HERE" && pwd)" || exit 2
cd "$REPO_ROOT" || exit 2

# --list boots nothing and needs no scenario.sh, so it is answered before that
# file is looked for: the gate that asks it runs where no scenario ever does.
if [ "${1:-}" = "--list" ]; then
	[ "$#" -eq 1 ] || { echo "[$GATE_TAG] --list takes no argument. See --help." >&2; exit 2; }
	roster="$(discover_gate_files)"
	if [ -z "$roster" ]; then
		echo "[$GATE_TAG] FAIL — the roster is EMPTY: no gate under $GDK_SCENARIO_SOURCE_DIR/ (support/, capture tools and infra are not swept)" >&2
		exit 1
	fi
	printf '%s\n' "$roster"
	exit 0
fi

# Read-only exits above never take the lease. One owner covers repair and the
# full fan-out; child workers validate and inherit its descriptor.
ORIGINAL_ARGS=("$@")
[ -f "$GDK_RUNNERS_LIB" ] || { echo "[$GATE_TAG] engine-gate library not found: $GDK_RUNNERS_LIB" >&2; exit 2; }
# shellcheck source=/dev/null
. "$GDK_RUNNERS_LIB"
held_rc=0; gdk_engine_gate_held || held_rc=$?
if [ "$held_rc" -eq 2 ]; then exit 2; fi
if [ "$held_rc" -eq 1 ]; then
	gdk_engine_gate_run "$GATE_TAG" -- bash "$SCRIPT_DIR/$(basename "$0")" ${ORIGINAL_ARGS[@]+"${ORIGINAL_ARGS[@]}"}
	exit $?
fi

SCENARIO_SH="$SCRIPT_DIR/$GDK_SCENARIO_RUNNER"
if [ ! -f "$SCENARIO_SH" ]; then
	echo "[$GATE_TAG] scenario.sh not found at '$SCENARIO_SH' — set GDK_SCENARIO_RUNNER" >&2
	exit 2
fi

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
		# A root that names nothing would make every fixture touch neither a
		# fixture nor ground: a slice of smoke, exit 0, no line (rule 4).
		if ! FIXTURE_ROOT="$(fixture_root "$GDK_SCENARIO_FIXTURE_DIR")"; then
			echo "[$GATE_TAG] GDK_SCENARIO_FIXTURE_DIR='$GDK_SCENARIO_FIXTURE_DIR' $FIXTURE_ROOT — name the directory your scenarios load fixtures from" >&2
			exit 2
		fi
		GDK_SCENARIO_FIXTURE_DIR="$FIXTURE_ROOT"
		touched_count="$(printf '%s' "$touched" | grep -c . || true)"
		substrate="$(printf '%s\n' "$touched" | touched_substrate)"
		# Only asked when the ground is not touched: the ground boots it all.
		fixtures=''
		[ -n "$substrate" ] || fixtures="$(printf '%s\n' "$touched" | fixture_slice)"
		orphans="$(printf '%s\n' "$fixtures" | awk -F'\t' '$1 == "ORPHAN" { print $2 }')"
		# 1.3.0 booted the tier for any touch under tests/support/. With the
		# fixture root moved elsewhere, a touch there is looked up by nothing,
		# and must not shrink to smoke without a word.
		unclaimed=''
		[ "$FIXTURE_ROOT" = "$FIXTURE_DIR_STOCK" ] || unclaimed="$(printf '%s\n' "$touched" \
			| awk -v old="$FIXTURE_DIR_STOCK" -v root="$FIXTURE_ROOT" 'index($0, old) == 1 && index($0, root) != 1')"
		if [ -n "$fixtures" ]; then
			scanned="$(find "${FIXTURE_ROOT%/}" -type f \( -name '*.gd' -o -name '*.tscn' -o -name '*.tres' \) 2>/dev/null | wc -l | tr -d ' ')"
			echo "[$GATE_TAG] fixture root $FIXTURE_ROOT: $scanned file(s) scanned for references"
		fi
		if [ -n "$substrate" ]; then
			while IFS= read -r n; do NAMES+=("$n"); done < <(discover_all)
			echo "[$GATE_TAG] --diff $2: the change touches the tier's own ground — every scenario is the honest slice:"
			printf '%s\n' "$substrate" | sed 's/^/    /'
			SLICE_NOTE="; substrate touched, whole tier"
		elif [ -n "$unclaimed" ]; then
			while IFS= read -r n; do NAMES+=("$n"); done < <(discover_all)
			printf '%s\n' "$unclaimed" | while IFS= read -r f; do
				echo "[$GATE_TAG] $f is outside the fixture root $FIXTURE_ROOT — booting the tier"
			done
			SLICE_NOTE="; $FIXTURE_DIR_STOCK touched outside the fixture root, whole tier"
		elif [ -n "$orphans" ]; then
			# Rule 4: a reference the text scan cannot see (a path built at
			# runtime) must not read as "no scenario needs this".
			while IFS= read -r n; do NAMES+=("$n"); done < <(discover_all)
			printf '%s\n' "$orphans" | while IFS= read -r f; do
				echo "[$GATE_TAG] fixture $f is referenced by no scenario — booting the tier"
			done
			SLICE_NOTE="; unreferenced fixture touched, whole tier"
		else
			# The fixture census: what each touched fixture selected.
			printf '%s\n' "$fixtures" | awk -F'\t' -v tag="$GATE_TAG" '
				$1 == "FIXTURE" { if (!($2 in n)) order[++k] = $2; n[$2]++ }
				END { for (i = 1; i <= k; i++) printf "[%s] fixture %s selected %d scenario(s)\n", tag, order[i], n[order[i]] }
			'
			slice="$(printf '%s\n' "$touched" | slice_for_touched
				printf '%s\n' "$fixtures" | awk -F'\t' '$1 == "FIXTURE" { print "SELECT\t" $3 }')"
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

MODE="${1:-}"
# Only the slice that gates a merge batch reruns; --all is the milestone gate
# and a named run is someone looking at one scenario on purpose.
[ "$MODE" = "--diff" ] || RERUN=0

# Warm mode is for the sweeps; --smoke and a named run are one boot anyway.
case "$MODE" in --all|--diff|--system) ;; *) WARM=0 ;; esac
# Which scenarios may share a process, decided BEFORE anything boots: an
# `## Isolated because:` with no reason is a declaration that says nothing,
# and it stops the run naming its file.
WARM_NAMES=(); ISO_NAMES=()
if [ "$WARM" -eq 1 ]; then
	ROSTER_NL="$(printf '%s\n' "${NAMES[@]}")"
	while IFS= read -r f; do
		n="${f##*/}"; n="${n%.gd}"
		case $'\n'"$ROSTER_NL"$'\n' in *$'\n'"$n"$'\n'*) ;; *) continue ;; esac
		if reason="$(scenario_isolation "$f")"; then
			if [ -z "$reason" ]; then
				echo "[$GATE_TAG] $f: '## $ISOLATED_KEY' gives no reason — say what process state it needs, or remove the line" >&2
				exit 2
			fi
			ISO_NAMES+=("$n")
		fi
	done < <(discover_gate_files)
	ISO_NL="$(printf '%s\n' ${ISO_NAMES[@]+"${ISO_NAMES[@]}"})"
	for n in "${NAMES[@]}"; do
		case $'\n'"$ISO_NL"$'\n' in *$'\n'"$n"$'\n'*) ;; *) WARM_NAMES+=("$n") ;; esac
	done
fi

# The repair a sweep cannot do, done once before it (#16): a sweep is where a
# stale cache fails every scenario, and where scenario.sh must NOT repair it.
if { [ "$MODE" = "--diff" ] || [ "$MODE" = "--all" ]; } && [ -f project.godot ] \
	&& stale="$(import_cache_stale)"; then
	repair="$SCRIPT_DIR/$IMPORT_CACHE_RUNNER"
	if [ ! -f "$repair" ]; then
		echo "[$GATE_TAG] the import cache is stale ($stale) and $IMPORT_CACHE_RUNNER is not installed at $repair — the sweep did not start" >&2
		exit 2
	fi
	echo "[$GATE_TAG] import cache is stale ($stale) — running $IMPORT_CACHE_RUNNER once, before the sweep"
	repair_rc=0; bash "$repair" || repair_rc=$?
	if [ "$repair_rc" -ne 0 ]; then
		echo "[$GATE_TAG] FAIL — the import-cache repair ($IMPORT_CACHE_RUNNER) exited $repair_rc; the sweep did not start. Run it alone (make import-cache) and read its report."
		exit 1
	fi
fi

JOBS="${GDK_JOBS:-$(detect_jobs)}"
WORKERS=0
if [ "$WARM" -eq 1 ]; then
	WORKERS="${#WARM_NAMES[@]}"
	[ "$WORKERS" -le "$JOBS" ] || WORKERS="$JOBS"
	echo "[$GATE_TAG] ${#NAMES[@]} scenario(s), warm: ${#WARM_NAMES[@]} in $WORKERS worker(s), ${#ISO_NAMES[@]} isolated (cold)"
else
	echo "[$GATE_TAG] ${#NAMES[@]} scenario(s), ${JOBS}-way parallel, isolated per process"
fi

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
#
# GDK_SCENARIO_IN_SWEEP tells each job it has PEERS. The runner's import-cache
# recovery ends in removing .godot, which in a sweep would be done TO the peers
# still booting in it — a scatter of failures that look like real ones. Told it
# is in a sweep, the runner reports that repair instead of performing it.
#
# The body is SINGLE-quoted, so nothing inside it may carry an apostrophe: the
# quote ends the string and the sweep stops parsing.
#
# The CPU the fan-out burns is the difference of this shell's `times` across
# it: every job is reaped through xargs before the pipeline returns.
children_cpu "$TMP/times"; CPU_BEFORE="$CHILD_CPU_MS"
# cold_fanout <name>... — the cold path: one scenario.sh per name, JOBS at once.
cold_fanout() {
# shellcheck disable=SC2016
printf '%s\n' "$@" | xargs -P "$JOBS" -I{} bash -c '
	name="$1"; tmp="$2"
	export GDK_HEADLESS_HOME="$tmp/home-$name"
	export GDK_SCENARIO_IN_SWEEP=1
	out="$(bash "'"$SCENARIO_SH"'" "$name" 2>&1)"; code=$?
	printf "%s\n" "$out" > "$tmp/$name.log"
	printf "%s\t%s\n" "$name" "$code" >> "$tmp/results"
' _ {} "$TMP"
}

HANDED=(); WARM_FAILED_NL=''; WARM_RAN=0; WARM_SECS=0; COLD_T0="$SECONDS"
if [ "$WARM" -eq 0 ]; then
	cold_fanout "${NAMES[@]}"
else
	# The warm phase. Slices balanced by count: name j goes to worker j mod W.
	# Every worker's finished scenarios land in $TMP/warm/results in the shape
	# the cold jobs write; what is not there afterwards was never finished,
	# whatever the worker said, and runs cold (rule 4: a worker that died
	# without a word must not shrink the census).
	mkdir -p "$TMP/warm"; : > "$TMP/warm/results"
	WARM_T0="$SECONDS"; WORKER_PIDS=()
	for ((w = 0; w < WORKERS; w++)); do
		slice=()
		for ((j = w; j < ${#WARM_NAMES[@]}; j += WORKERS)); do slice+=("${WARM_NAMES[$j]}"); done
		GDK_HEADLESS_HOME="$TMP/home-warm-$w" GDK_SCENARIO_IN_SWEEP=1 GDK_SCENARIO_SUITE_RESULTS="$TMP/warm" \
			bash "$SCENARIO_SH" --suite "${slice[@]}" > "$TMP/warm-$w.out" 2>&1 &
		WORKER_PIDS+=("$!")
	done
	for ((w = 0; w < WORKERS; w++)); do
		wrc=0; wait "${WORKER_PIDS[$w]}" || wrc=$?
		case "$wrc" in
			0|1|4) ;;
			*) echo "[$GATE_TAG] warm worker $w exited $wrc — what it did not finish runs cold:"
			   tail -"$FAILURE_SUMMARY_LINES" "$TMP/warm-$w.out" | sed 's/^/    /' ;;
		esac
	done
	WARM_SECS=$((SECONDS - WARM_T0))
	grep -hE '^  WARM-ABORT  |^    handed back: ' "$TMP"/warm-*.out 2>/dev/null || true
	for n in ${WARM_NAMES[@]+"${WARM_NAMES[@]}"}; do
		code="$(awk -F'\t' -v n="$n" '$1 == n { c = $2 } END { print c }' "$TMP/warm/results")"
		if [ -z "$code" ]; then HANDED+=("$n"); continue; fi
		WARM_RAN=$((WARM_RAN + 1))
		printf '%s\t%s\n' "$n" "$code" >> "$TMP/results"
		[ ! -f "$TMP/warm/$n.log" ] || mv -f "$TMP/warm/$n.log" "$TMP/$n.log"
		[ "$code" -eq 0 ] || WARM_FAILED_NL="$WARM_FAILED_NL$n"$'\n'
	done
	COLD_T0="$SECONDS"
	COLD_RUN=(${ISO_NAMES[@]+"${ISO_NAMES[@]}"} ${HANDED[@]+"${HANDED[@]}"})
	if [ "${#COLD_RUN[@]}" -gt 0 ]; then
		echo "[$GATE_TAG] cold: ${#ISO_NAMES[@]} isolated + ${#HANDED[@]} handed back, ${JOBS}-way parallel"
		cold_fanout "${COLD_RUN[@]}"
	fi
fi

PASS=0; FAIL=0; FAILED_NAMES=()
while IFS=$'\t' read -r name code; do
	if [ "$code" -eq 0 ]; then
		PASS=$((PASS + 1))
	else
		FAIL=$((FAIL + 1)); FAILED_NAMES+=("$name")
	fi
done < "$TMP/results"
# What the run booted: every job that came back with a result ran scenario.sh.
# Counted before the unreported are folded into FAIL below — a job that never
# reported is a failure, and not a boot anyone can show happened.
BOOTS=$((PASS + FAIL))
# Warm: each worker is ONE boot, however many scenarios it ran.
[ "$WARM" -eq 0 ] || BOOTS=$((BOOTS - WARM_RAN + WORKERS))

# Rerun alone, once (#34). A scenario that fails among N peers and passes on
# its own failed on LOAD, not on what it asserts — and a merge batch stopped
# for one costs a story. Serial, one engine, no peers — and still with
# GDK_SCENARIO_IN_SWEEP=1: the cache was repaired once, before the sweep, and
# the runner's own recovery is `rm -rf .godot` plus an editor pass IN THE
# TREE, which removes the .godot a playing session reads and re-serialises
# tracked resources into a diff. The runner reports that repair; it does not
# perform it. Still red alone is red, exactly as before. The FLAKE line is the
# record; nothing is filed.
FLAKY=0; WARM_ONLY=0
# A rerun is for the few a loaded machine reddens. Past a cap the answer is
# already red, and 166 serial cold boots would only make it slower.
RERUN_CAP=$(( ${#NAMES[@]} / 10 )); [ "$RERUN_CAP" -ge 3 ] || RERUN_CAP=3
if [ "$RERUN" -eq 1 ] && [ "${#FAILED_NAMES[@]}" -gt "$RERUN_CAP" ]; then
	echo "[$GATE_TAG] ${#FAILED_NAMES[@]} scenario(s) failed, over the rerun cap of $RERUN_CAP (max of 3 and 10% of ${#NAMES[@]}) — not rerunning; they are red"
	RERUN=0
fi
if [ "$RERUN" -eq 1 ] && [ "${#FAILED_NAMES[@]}" -gt 0 ]; then
	echo "[$GATE_TAG] rerunning ${#FAILED_NAMES[@]} failed scenario(s) alone, once each"
	STILL_RED=()
	for n in "${FAILED_NAMES[@]}"; do
		code=0
		GDK_HEADLESS_HOME="$TMP/home-$n-alone" GDK_SCENARIO_IN_SWEEP=1 \
			bash "$SCENARIO_SH" "$n" > "$TMP/$n.alone.log" 2>&1 || code=$?
		BOOTS=$((BOOTS + 1))
		if [ "$code" -eq 0 ]; then
			PASS=$((PASS + 1)); FAIL=$((FAIL - 1))
			# A warm failure that passes cold leans on process state — which is
			# a different finding from a load flake, and counted apart.
			case $'\n'"$WARM_FAILED_NL" in
				*$'\n'"$n"$'\n'*)
					WARM_ONLY=$((WARM_ONLY + 1))
					echo "  WARM-ONLY  $n — failed warm, passed cold: it leans on process state; mark it \"## $ISOLATED_KEY\" or fix its reset" ;;
				*)
					FLAKY=$((FLAKY + 1))
					echo "  FLAKE  $n — failed in the sweep, passed alone" ;;
			esac
		else
			STILL_RED+=("$n")
		fi
	done
	FAILED_NAMES=(${STILL_RED[@]+"${STILL_RED[@]}"})
fi
COLD_SECS=$((SECONDS - COLD_T0))
children_cpu "$TMP/times"
BOOT_CPU_MS=''
[ -z "$CPU_BEFORE" ] || [ -z "$CHILD_CPU_MS" ] || BOOT_CPU_MS=$((CHILD_CPU_MS - CPU_BEFORE))

# A job that never wrote a result line is a job that died before scenario.sh
# could report — counted as a failure, because the alternative is a sweep that
# reports 0 failures over scenarios that never ran.
UNREPORTED=$(( ${#NAMES[@]} - PASS - FAIL ))
if [ "$UNREPORTED" -gt 0 ]; then
	echo "[$GATE_TAG] $UNREPORTED scenario(s) produced no result at all — counting them failed"
	FAIL=$((FAIL + UNREPORTED))
fi

# Warm mode's census (rule 4): warm + cold + handed back is the roster, and
# every name on it has a result. Anything else is a FAIL naming the missing.
CENSUS_NOTE=''
if [ "$WARM" -eq 1 ]; then
	CENSUS_NOTE="; warm $WARM_RAN, cold ${#ISO_NAMES[@]}, handed back ${#HANDED[@]}"
	missing="$(printf '%s\n' "${NAMES[@]}" | awk -F'\t' 'FILENAME == ARGV[1] { seen[$1] = 1; next } !($0 in seen)' "$TMP/results" -)"
	if [ $((WARM_RAN + ${#ISO_NAMES[@]} + ${#HANDED[@]})) -ne "${#NAMES[@]}" ] || [ -n "$missing" ]; then
		echo "[$GATE_TAG] FAIL — census: warm $WARM_RAN + cold ${#ISO_NAMES[@]} + handed back ${#HANDED[@]} is not the roster of ${#NAMES[@]}; no result for: $(printf '%s' "$missing" | tr '\n' ' ')"
		[ "$UNREPORTED" -gt 0 ] || FAIL=$((FAIL + 1))
	fi
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
[ "$WARM" -eq 0 ] || echo "[$GATE_TAG] WALL: warm workers ${WARM_SECS}s, cold remainder ${COLD_SECS}s"
boots_line "$BOOTS" "$BOOT_CPU_MS"
FLAKY_NOTE=''
[ "$FLAKY" -eq 0 ] || FLAKY_NOTE=" ($FLAKY flaky)"
[ "$WARM_ONLY" -eq 0 ] || FLAKY_NOTE=" ($FLAKY flaky, $WARM_ONLY warm-only)"
echo "[$GATE_TAG] SUMMARY: $PASS passed$FLAKY_NOTE, $FAIL failed (of ${#NAMES[@]})$CENSUS_NOTE$SLICE_NOTE"
[ "$FAIL" -eq 0 ] || exit 1
exit 0
