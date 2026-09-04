#!/usr/bin/env bash
# cc-godot-sandbox.sh — Claude Code PreToolUse Bash hook: never a raw engine boot.
#
# A headless Godot boot runs the project's full autoload stack (save flush,
# run-log appends) against whatever `user://` resolves to — the developer's
# LIVE game data. A week of scenario runs once littered ~40 synthetic save
# dirs into the real user://saves/ before anyone noticed; the fix, and the
# only thing that prevents a recurrence, is the HOME override in the project's
# sandbox wrapper (SANDBOX_OWNER, project config below). Every scripted target
# routes through that. A hand-typed `godot --headless` does not. So: hard
# BLOCK, with the wrapper that owns the job named in the message.
#
# HOW THIS DOES NOT BRICK THE DEV LOOP. The wrappers themselves exec godot
# constantly and MUST keep working. They do: a PreToolUse hook observes the
# command the agent TYPED into the Bash tool, never the subprocesses that
# command goes on to spawn. `make unit` reaches this hook as the four
# characters `make unit`. The guard therefore matches only an invocation of
# godot in COMMAND POSITION within the typed line — which is precisely "an
# agent typed it" and never "a wrapper did its job".
#
# KNOWN, ACCEPTED GAP. The guard sees the typed line, never the shell's
# expansion of it. A godot-NAMED variable in command position (`$GODOT`,
# `"${GODOT}"`, `"$godot_bin"`) is resolved below by stripping quotes, `$`
# and `{}` from the command word. An engine behind an ARBITRARY name
# (`ENGINE=…; $ENGINE`), or an assignment made in an earlier Bash call, is
# out of reach for a static hook without expansion — that residue is the
# fail-open design working as declared, not an unstated hole.
#
# Protocol: Claude Code feeds the PreToolUse event as JSON on stdin (tool_name,
# tool_input.command). Exit 0 = allow, exit 2 = BLOCK with stderr returned to
# the agent. Any internal failure exits 0 (fail open) — a broken hook must never
# wedge the session. `--self-test` replays the corpus below through this same
# file and is meant to be a member of your static gate.
set -eu
trap 'exit 0' ERR

# --- project config (yours to edit after install — the file is your repo's) --
# The file that owns the user:// HOME sandbox — named in the BLOCK message so
# the agent is pointed at the door, not just turned away at the wall.
SANDBOX_OWNER='tools/dev/gdk_runners.sh (its gdk_sandbox_home function)'
# The wrapper roster the BLOCK message offers — your project's spellings.
WRAPPER_ROSTER='    make parse | make lint | make check      # static gates
    make unit SYS=<system>                   # unit tier (sliced)
    make scenario NAME=<name>                # one integration scenario, cold
    make integration ARGS="--system <x>"     # a scenario slice
    make smoke                               # the boot smoke test
    make import-cache                        # rebuild .godot, sandboxed
    make help                                # every target, authoritative'
# A shell FUNCTION that boots the engine itself is the other way past this
# guard: typing it (after sourcing the library) is a raw boot with no `godot`
# token on the line for the command-position check below to see — and such a
# function sandboxes NOTHING by itself, it relies on the typist having set the
# sandbox HOME first. One consumer's did, one typist did not, and an editor
# pass ran against the live player data.
#
# STOCK ROSTER — the functions `godot-devkit install-runners` puts in every
# consumer, blocked with no configuration at all. `gdk_sandbox_home` is
# deliberately NOT here: it is the door, not a boot, and blocking the one
# function that MAKES a run safe would teach people to switch this guard off.
GDK_BOOT_FUNCTIONS='gdk_rebuild_import_cache'
GDK_BOOT_FUNCTION_TARGET='make import-cache'
# OPTIONAL, empty by default: one more function name, for a repo that still
# carries a project-prefixed spelling of the same thing. Set SANDBOX_FUNCTION
# to the name and SANDBOX_FUNCTION_TARGET to the wrapper that owns the job.
SANDBOX_FUNCTION=''
SANDBOX_FUNCTION_TARGET=''
# -----------------------------------------------------------------------------

# The effective roster: the stock names, plus the consumer's if it set one.
# Parallel arrays rather than a map, because bash 3.2 has no associative ones
# and every entry needs the wrapper that owns its job alongside it.
BOOT_FUNCTIONS=()
BOOT_FUNCTION_TARGETS=()
for _fn in $GDK_BOOT_FUNCTIONS; do
	BOOT_FUNCTIONS+=("$_fn")
	BOOT_FUNCTION_TARGETS+=("$GDK_BOOT_FUNCTION_TARGET")
done
if [ -n "$SANDBOX_FUNCTION" ]; then
	BOOT_FUNCTIONS+=("$SANDBOX_FUNCTION")
	BOOT_FUNCTION_TARGETS+=("$SANDBOX_FUNCTION_TARGET")
fi

# --- --self-test — the payload corpus, PROVEN rather than claimed ------------
# `bash tools/hooks/cc-godot-sandbox.sh --self-test` replays every payload
# through the real hook and checks the verdict; exit 0 means every case landed
# where it should. Wire it into your static gate (in the stock consumer
# Makefile: a `hooks-self-test` target listed in `check`) — a corpus that is
# re-run is the only reason to trust "every case verified" six months later.
# The stock roster's cases are always in the corpus; the two extra
# SANDBOX_FUNCTION cases in each list appear only when you have set that
# variable, so the corpus always tests the guard you actually run.
# shellcheck disable=SC2016  # these are literal PAYLOADS — expansion is the
# thing under test, and it must not happen here.
SELF_TEST_BLOCK=(
	'godot --headless --quit'
	'godot --path . --headless -s tools/dev/checks/compile_sweep.gd'
	'godot'                                       # bare: the project manager IS a boot
	'godot --headless --help'                     # a query flag buried in a boot
	'make lint && godot --headless --editor --quit'
	'$GODOT --headless --quit'
	'"${GODOT}" --headless'
	'/Applications/Godot.app/Contents/MacOS/Godot --headless --quit'
	'env HOME=/tmp godot --headless --quit'
	'timeout 60 godot --headless --quit'
	# An UNBALANCED quote is unparseable, and unparseable input stays STRICT:
	# the quote-aware split refuses and the naive fallback still sees the boot.
	'echo "foo; godot --headless'
	# The library's boot-in-a-function, typed. It sandboxes nothing by itself.
	'gdk_rebuild_import_cache'
	# the realistic spelling: sourced, then typed, in a later segment.
	'source tools/dev/gdk_runners.sh && gdk_rebuild_import_cache'
)
# The two `git commit` cases and the `echo` case are the quoting false positives
# this guard used to fire on: a word inside quotes is data, never a command word.
SELF_TEST_ALLOW=(
	'make parse'
	'godot --version'
	'command -v godot'
	'godot-devkit refs GameRunner'
	'grep -n "godot --" file'
	'git commit -m "tools(dev): godot --headless is wrapper-only"'
	'git commit -m "hooks: block (godot --headless) in command position"'
	'echo "foo; godot --headless"'
	# A MULTI-LINE quoted body: a commit message whose second paragraph talks
	# about the engine. The walk kept the newline and the segment reader split
	# on it, so the quoted line posed as a command word.
	$'git commit -m "feat: x\n\ngodot --headless is wrapper-only now" -- a.py'
	$'echo "a\ngodot --headless\nb"'
	# Single quotes take the same path through the walk.
	$'git commit -m \'chore: y\n\ngodot --headless\' -- a.py'
	$'cat <<EOF\ngodot --headless --quit\nEOF'
	'make import-cache'
	'grep -rn gdk_rebuild_import_cache docs/'
	'echo "run it: (gdk_rebuild_import_cache) by hand"'
	# gdk_sandbox_home is the DOOR — it exports a sandboxed HOME and boots
	# nothing. Blocking it would turn the safe spelling into a blocked one.
	'source tools/dev/gdk_runners.sh && gdk_sandbox_home'
)
if [ -n "$SANDBOX_FUNCTION" ]; then
	SELF_TEST_BLOCK+=(
		"$SANDBOX_FUNCTION"
		# the realistic spelling: sourced, then typed, in a later segment. The
		# library path is a stand-in — a payload is tokenized, never executed.
		"source ./sandbox-lib.sh && $SANDBOX_FUNCTION"
	)
	SELF_TEST_ALLOW+=(
		"grep -rn $SANDBOX_FUNCTION docs/"
		"echo \"run it: ($SANDBOX_FUNCTION) by hand\""
	)
fi

# json_payload <command> — the PreToolUse event this hook reads on stdin.
json_payload() {
	local cmd="$1"
	cmd="${cmd//\\/\\\\}"
	cmd="${cmd//\"/\\\"}"
	cmd="${cmd//$'\n'/\\n}"
	printf '{"tool_name":"Bash","tool_input":{"command":"%s"}}' "$cmd"
}

self_test() {
	local rc=0 payload verdict
	for payload in "${SELF_TEST_BLOCK[@]}"; do
		verdict=0
		json_payload "$payload" | bash "$0" >/dev/null 2>&1 || verdict=$?
		if [ "$verdict" -ne 2 ]; then
			echo "  MISS — expected BLOCK, got exit $verdict: $payload" >&2
			rc=1
		fi
	done
	for payload in "${SELF_TEST_ALLOW[@]}"; do
		verdict=0
		json_payload "$payload" | bash "$0" >/dev/null 2>&1 || verdict=$?
		if [ "$verdict" -ne 0 ]; then
			echo "  FALSE POSITIVE — expected ALLOW, got exit $verdict: $payload" >&2
			rc=1
		fi
	done
	if [ "$rc" -eq 0 ]; then
		echo "[cc-godot-sandbox] SELF-TEST OK — ${#SELF_TEST_BLOCK[@]} block / ${#SELF_TEST_ALLOW[@]} allow case(s)"
	else
		echo "[cc-godot-sandbox] SELF-TEST FAIL — see the case(s) above" >&2
	fi
	return "$rc"
}

if [ "${1:-}" = "--self-test" ]; then
	# `set -e` plus the fail-open ERR trap above would turn a self-test FAILURE
	# into exit 0 — the exact false green this corpus exists to prevent. So the
	# result is captured through `||`, which never trips the trap.
	self_test_rc=0
	self_test || self_test_rc=$?
	exit "$self_test_rc"
fi

# hook_json_field <payload> <dotted.key>
# Echo a STRING field out of a Claude Code hook event, or nothing.
#
# INLINE, not sourced. An installed hook is a standalone file; `source` of a
# library the project does not have fails open, and a guard that fails open is
# a guard that is not there.
#
# A `grep -oE '"key"…"[^"]*"' extractor is fine for absolute paths and
# booleans. It is NOT fine for `tool_input.command`: a Bash command routinely
# embeds escaped quotes (`git commit -m \"fix\"`), and `"[^"]*"` truncates at
# the first one, handing the guard HALF a command line — which is exactly how a
# guard starts firing on commands that were fine. So the payload is decoded
# with a real JSON parser, and this yields nothing (the caller then exits 0)
# when no parser is available.
hook_json_field() {
	local payload="$1" key="$2"
	if command -v python3 >/dev/null 2>&1; then
		printf '%s' "$payload" | python3 -c '
import json, sys
try:
	node = json.load(sys.stdin)
except Exception:
	sys.exit(0)
for part in sys.argv[1].split("."):
	if not isinstance(node, dict) or part not in node:
		sys.exit(0)
	node = node[part]
if isinstance(node, str):
	sys.stdout.write(node)
' "$key" 2>/dev/null || true
	elif command -v jq >/dev/null 2>&1; then
		printf '%s' "$payload" \
			| jq -r --arg k "$key" 'getpath($k | split(".")) | select(type == "string")' 2>/dev/null || true
	fi
}

INPUT="$(cat)"

# Fast path: the overwhelming majority of Bash calls never mention the engine.
# Pure shell, no fork, no JSON decode. `*GODOT*` is for the named-variable
# spelling (`$GODOT --headless`) with no lowercase mention beside it.
# A SANDBOX_FUNCTION mention is the other way in — and the test is written as
# two steps rather than an extra `case` arm because an EMPTY SANDBOX_FUNCTION
# would make `*"$SANDBOX_FUNCTION"*` match every command on earth, quietly
# retiring the fast path for every consumer that left the stock value alone.
mentions_engine=0
case "$INPUT" in
	*godot*|*Godot*|*GODOT*) mentions_engine=1 ;;
esac
if [ "$mentions_engine" -eq 0 ]; then
	for _fn in ${BOOT_FUNCTIONS[@]+"${BOOT_FUNCTIONS[@]}"}; do
		# An EMPTY name would make `*"$_fn"*` match every command on earth,
		# quietly retiring the fast path — so an empty entry never gets in.
		[ -n "$_fn" ] || continue
		case "$INPUT" in
			*"$_fn"*) mentions_engine=1; break ;;
		esac
	done
fi
[ "$mentions_engine" -eq 1 ] || exit 0

[ "$(hook_json_field "$INPUT" tool_name)" = "Bash" ] || exit 0

CMD="$(hook_json_field "$INPUT" tool_input.command)"
[ -n "$CMD" ] || exit 0   # unparseable payload → fail open

# A heredoc BODY is data, not commands — an agent writing a doc or a script that
# quotes `godot --headless` is not booting anything. Everything from the first
# `<<` on is body (and a heredoc is not how anyone runs the engine). A `<<<`
# HERESTRING is not a heredoc: its payload is one inline word and the command
# line CONTINUES after it, so truncating at it would hide a boot typed after
# the herestring. Neutralize herestrings first; the placeholder glues onto the
# data word so that word can never be misread as a fresh command word.
ANALYZE="${CMD//<<</ __NBHSTR__}"
ANALYZE="${ANALYZE%%<<*}"

# split_command_segments <line>
# Emit one line per shell segment, cutting at the operator characters that start
# a fresh command word — but ONLY where they lie outside quotes.
#
# WHY THE QUOTE STATE MATTERS. The naive `tr ';|&()\`{}' '\n…'` split cut inside
# quoted text too, so a quoted word that HAPPENS to follow an operator character
# became the next segment's command word. Real, everyday commands were blocked:
#
#   echo "foo; godot --headless"
#   git commit -m "hooks: block (godot --headless) in command position"
#
# Quoted text is preserved verbatim INSIDE its segment instead, so a word in
# quotes can never be a command word — while a quoted COMMAND word
# (`"$GODOT" --headless`, the named-variable spelling the header documents)
# still is one, because it is genuinely first in its segment.
#
# Returns 1 on an unbalanced quote. The caller then falls back to the naive
# split: unparseable input stays STRICT rather than sliding open.
split_command_segments() {
	local rest="$1" out="" head quote="" ch nxt
	while [ -n "$rest" ]; do
		if [ "$quote" = "'" ]; then
			head="${rest%%\'*}"                      # single quotes: no escapes
		elif [ "$quote" = '"' ]; then
			head="${rest%%[\"\\]*}"                  # double quotes: \ escapes
		else
			head="${rest%%[;\|\&\(\)\`\{\}\'\"\\]*}"
		fi
		if [ "$head" = "$rest" ]; then
			[ -z "$quote" ] || return 1              # unterminated quote
			out+="$rest"
			break
		fi
		rest="${rest#"$head"}"
		# A newline INSIDE quotes is data, not a segment break. The walk kept it
		# verbatim, but the CONSUMER reads segments with `while read -r`, which
		# splits on newlines — so the second line of a multi-line quoted
		# argument became a fresh command word and
		# `git commit -m "feat: x⏎⏎godot --headless is wrapper-only now"` was
		# BLOCKED. That contradicts this function's own claim that a word in
		# quotes can never be a command word, and a multi-line -m body is how
		# agents write commit messages. Same neutralization the herestring
		# placeholder does: keep the word, take away its power to start a
		# command. An UNBALANCED quote still returns 1 above, so unparseable
		# input keeps taking the strict fallback.
		[ -z "$quote" ] || head="${head//$'\n'/ }"
		out+="$head"
		ch="${rest:0:1}"
		rest="${rest:1}"
		if [ -n "$quote" ]; then
			if [ "$ch" = "\\" ]; then
				nxt="${rest:0:1}"; rest="${rest:1}"       # escaped char, still inside
				[ "$nxt" != $'\n' ] || nxt=' '           # …and still not a break
				out+="$ch$nxt"
			else
				quote=""; out+="$ch"                      # the closing quote
			fi
			continue
		fi
		case "$ch" in
			\'|\") quote="$ch"; out+="$ch" ;;
			\\)    out+="$ch${rest:0:1}"; rest="${rest:1}" ;;
			*)     out+=$'\n' ;;                          # an operator, outside quotes
		esac
	done
	printf '%s\n' "$out"
}

# Wrapper words that legitimately precede a real command word.
is_wrapper() {
	case "$1" in
		env|time|nohup|exec|command|nice|sudo|xargs|caffeinate|stdbuf|timeout|gtimeout) return 0 ;;
		[A-Za-z_]*=*) return 0 ;;   # leading VAR=value assignment
		*) return 1 ;;
	esac
}

offender=""
offender_kind="engine"
offender_fn=""
offender_fn_target=""
# Split at shell operators so each segment starts at a command word. `$(`, a
# backtick and a brace group all start a fresh command too.
# The quote-aware walk is pure shell and BEATS the `tr` fork at every size a
# person actually types (measured: 4.3KB → 0.35s, against 0.48s for the fork).
# It degrades on a pathological line — 36KB carrying 4,000 operators took 12s —
# and a hook that stalls the session is its own kind of broken. So past this
# bound the naive split is used instead, which is the STRICT direction: over the
# bound the guard is exactly as strict as it was before the quoting fix, never
# looser. Same fallback an unbalanced quote takes.
SPLIT_MAX_CHARS=8192
SEGMENTS=''
if [ "${#ANALYZE}" -le "$SPLIT_MAX_CHARS" ]; then
	SEGMENTS="$(split_command_segments "$ANALYZE")" || SEGMENTS=''
fi
if [ -z "$SEGMENTS" ]; then
	# shellcheck disable=SC2020  # the fallback tr maps a char SET to newline — exactly the intent
	SEGMENTS="$(printf '%s' "$ANALYZE" | tr ';|&()`{}' '\n\n\n\n\n\n\n\n')"
fi

while IFS= read -r segment; do
	[ -n "$segment" ] || continue
	# shellcheck disable=SC2206  # deliberate word-split; read -ra avoids globbing
	IFS=' 	' read -ra toks <<<"$segment"
	[ "${#toks[@]}" -gt 0 ] || continue

	idx=0
	shifted=0
	in_command=0
	resolves_only=0
	while [ "$idx" -lt "${#toks[@]}" ]; do
		tok="${toks[$idx]}"
		if is_wrapper "$tok"; then
			if [ "$tok" = "command" ]; then in_command=1; fi
			idx=$((idx + 1)); shifted=1; continue
		fi
		# Only AFTER a wrapper do flags / durations belong to it (`timeout 60`,
		# `command -v`); in first position they mean this is not a command word.
		if [ "$shifted" -eq 1 ]; then
			case "$tok" in
				-v|-V)
					# `command -v godot` RESOLVES the binary and runs nothing.
					if [ "$in_command" -eq 1 ]; then resolves_only=1; fi
					idx=$((idx + 1)); continue ;;
				-*|[0-9]*) idx=$((idx + 1)); continue ;;
			esac
		fi
		break
	done
	[ "$idx" -lt "${#toks[@]}" ] || continue
	[ "$resolves_only" -eq 0 ] || continue

	# The command word itself: `godot`, `godot4`, `./godot`, a full
	# /Applications/Godot.app/Contents/MacOS/Godot path — or the engine behind
	# a godot-NAMED variable (`$GODOT`, `"${GODOT}"`, `"$godot_bin"`): quotes,
	# `$` and `{}` are stripped first, so those resolve to a godot* token (the
	# arbitrary-name case is the accepted gap in the header). `godot-devkit`
	# is this toolkit's own CLI in command position — never a boot.
	command_word="${toks[$idx]//[\$\{\}\"\']/}"
	command_word="${command_word##*/}"

	# The sandbox library's boot-in-a-function, in COMMAND position (only when
	# the consumer named one). Position is what keeps this honest: `grep -rn
	# <fn> docs/` has `grep` as its command word and is never flagged.
	fn_idx=0
	while [ "$fn_idx" -lt "${#BOOT_FUNCTIONS[@]}" ]; do
		if [ -n "${BOOT_FUNCTIONS[$fn_idx]}" ] \
				&& [ "$command_word" = "${BOOT_FUNCTIONS[$fn_idx]}" ]; then
			offender="$segment"
			offender_kind="function"
			offender_fn="${BOOT_FUNCTIONS[$fn_idx]}"
			offender_fn_target="${BOOT_FUNCTION_TARGETS[$fn_idx]}"
			break
		fi
		fn_idx=$((fn_idx + 1))
	done
	[ -z "$offender" ] || break

	case "$(printf '%s' "$command_word" | tr '[:upper:]' '[:lower:]')" in
		godot-devkit) continue ;;
		godot*) ;;
		*) continue ;;
	esac

	# The ONLY raw invocations that boot nothing are the pure version/help
	# queries — and only when the WHOLE invocation is one. Everything else
	# reaches real state: a boot flag (`--headless`, `-e`/`--editor`,
	# `--import`, `-s`/`--script`, `--path`, …), a bare scene or project
	# path positional (`godot main.tscn`, `godot .`), and bare `godot`
	# itself (the project manager is a real boot against the real user://).
	# Matching per-token also closes the smuggle: a `--help` buried in a
	# boot's argument list no longer waves the boot through.
	argi=$((idx + 1))
	query_only=1
	if [ "$argi" -ge "${#toks[@]}" ]; then
		query_only=0   # bare `godot` — a boot, not a query
	fi
	while [ "$argi" -lt "${#toks[@]}" ]; do
		case "${toks[$argi]}" in
			--version|--help|-h) argi=$((argi + 1)) ;;
			*) query_only=0; break ;;
		esac
	done
	if [ "$query_only" -eq 1 ]; then
		continue
	fi

	offender="$segment"
	break
done <<<"$SEGMENTS"

[ -n "$offender" ] || exit 0

if [ "$offender_kind" = "function" ]; then
	{
		echo "BLOCKED (user:// sandbox): never call \`$offender_fn\` by hand."
		echo "  offending segment: ${offender# }"
		echo ""
		echo "  That function boots the engine against whatever user:// resolves"
		echo "  to, and it sandboxes NOTHING by itself — it relies on the caller"
		echo "  having set the sandbox HOME first ($SANDBOX_OWNER)."
		echo ""
		if [ -n "$offender_fn_target" ]; then
			echo "  Use the target that owns the job (sandbox + outcome check):"
			echo "    $offender_fn_target"
		else
			echo "  Use the wrapper that owns the job:"
			echo "$WRAPPER_ROSTER"
		fi
	} >&2
	exit 2
fi

{
	echo "BLOCKED (user:// sandbox): never invoke \`godot\` directly."
	echo "  offending segment: ${offender# }"
	echo ""
	echo "  A raw boot runs the full autoload stack against the REAL user:// —"
	echo "  the LIVE game data. Only the scripted wrappers redirect it, by"
	echo "  overriding HOME ($SANDBOX_OWNER:"
	echo "  a week of scenario runs once littered ~40 synthetic save dirs into the"
	echo "  live user://saves/). There is no exception to this."
	echo ""
	echo "  Use the wrapper that owns the job:"
	echo "$WRAPPER_ROSTER"
	echo ""
	echo "  (The wrappers call godot themselves and are unaffected — this guard"
	echo "   only ever sees the command YOU type into the Bash tool.)"
} >&2
exit 2
