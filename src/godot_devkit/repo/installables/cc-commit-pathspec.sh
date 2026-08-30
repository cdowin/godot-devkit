#!/usr/bin/env bash
# cc-commit-pathspec.sh — Claude Code PreToolUse Bash hook: a commit names its
# own paths.
#
# `git commit` commits the WHOLE INDEX. In this shared tree — several agents,
# one working directory, one index — an explicit `git add <files>` buys you
# nothing: whatever a peer staged (or whatever a tool auto-staged) rides along
# in YOUR commit. The rule is `git commit -m "..." -- <paths>`, it is written in
# .claude/rules/execution.md (or wherever your repo writes it down), it is
# restated by hand in every dispatch prompt, and it is still breached: a
# peer's untracked sidecar rides into somebody else's commit.
#
# WHY A BLOCK AND NOT A WARNING. The branch is shared and pushed, so the repo is
# forward-only: a swept commit cannot be reset or amended away, only apologised
# for in a follow-up commit. A PreToolUse warning is delivered AFTER the command
# runs, i.e. after the irreversible event — it could only ever narrate the
# damage. The block costs one round trip and the fix is mechanical.
#
# WHY IT WILL NOT ANNOY ANYONE INTO DISABLING IT. Every commit for which a
# pathspec is not the answer is detected and waved through, not argued with:
#   - a pathspec already present (`--`, a bare path argument, or
#     `--pathspec-from-file` in either spelling — paths named via a file)
#   - `--amend` (a different rule bans it here; a pathspec is not its fix)
#   - `--dry-run`, `--help`/`-h`, `--interactive`/`--patch`
#   - a merge / rebase / cherry-pick / revert in progress, where git itself
#     refuses a partial commit ("cannot do a partial commit during a merge")
# What is left is exactly the case whose fix IS a pathspec — including `-a`,
# which in a shared tree is the sweep in its purest form.
#
# The git pre-commit hook cannot enforce this: by the time it runs, a pathspec
# has already been folded into the commit git is building, and the hook sees
# only the resulting tree. This is the only layer that can see the intent.
#
# Protocol: Claude Code feeds the PreToolUse event as JSON on stdin (tool_name,
# tool_input.command, cwd). Exit 0 = allow, exit 2 = BLOCK with stderr returned
# to the agent. Any internal failure exits 0 (fail open).
set -eu
trap 'exit 0' ERR

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

# Fast path: pure shell, no fork, no JSON decode for the vast majority of calls.
case "$INPUT" in
	*commit*) ;;
	*) exit 0 ;;
esac

# Decode + normalise in ONE pass. Everything here exists because the FIRST
# thing this guard did on a real commit was fire on a correct one: the standard
# agent spelling of a long message is
#
#     git commit -m "$(cat <<'MSG'
#     …message…
#     MSG
#     )" -- <paths>
#
# and any tokenizer that splits on `(` or newline tears that into fragments,
# losing the `-- <paths>` that was right there. So, in order:
#   1. heredoc BODIES are dropped (they are data — a message, or a doc that
#      merely TALKS about `git commit`), and the `<<DELIM` opener with them;
#   2. `$(…)` and `` `…` `` spans collapse to one opaque token, innermost
#      first — which also swallows the newlines a multi-line substitution
#      spreads the command over, putting `git commit … -- <paths>` back on one
#      line where it belongs;
#   3. quoted runs collapse to the same opaque token, so a commit MESSAGE can
#      never be misread as a pathspec.
# A malformed pairing leaves extra bare tokens, which reads as "a pathspec was
# given" — every parse ambiguity in this hook resolves toward ALLOW.
#
# Needs python3; without it this guard yields (exit 0) rather than guessing at
# shell quoting with regexes, which is how it fired on a correct commit.
command -v python3 >/dev/null 2>&1 || exit 0
# SC2016 intentional: the python source below must stay LITERAL — the shell must
# not expand anything inside it.
# shellcheck disable=SC2016
ANALYZE="$(printf '%s' "$INPUT" | python3 -c '
import json, re, sys

try:
	event = json.load(sys.stdin)
except Exception:
	sys.exit(0)
if event.get("tool_name") != "Bash":
	sys.exit(0)
command = event.get("tool_input", {}).get("command")
if not isinstance(command, str):
	sys.exit(0)

OPAQUE = " __NBSTR__ "
OPENER = re.compile(r"<<-?\s*([\x27\"]?)([A-Za-z_][A-Za-z0-9_]*)\1")

kept, delimiter = [], None
for line in command.split("\n"):
	if delimiter is not None:
		if line.strip() == delimiter:
			delimiter = None
		continue
	found = OPENER.search(line)
	if found:
		delimiter = found.group(2)
	kept.append(OPENER.sub(OPAQUE, line))
text = "\n".join(kept)

previous = None
while previous != text:
	previous = text
	text = re.sub(r"\$\([^()]*\)", OPAQUE, text, flags=re.S)
text = re.sub(r"`[^`]*`", OPAQUE, text, flags=re.S)
text = re.sub(r"\"[^\"]*\"", OPAQUE, text, flags=re.S)
text = re.sub(r"\x27[^\x27]*\x27", OPAQUE, text, flags=re.S)
sys.stdout.write(text)
' 2>/dev/null || true)"
[ -n "$ANALYZE" ] || exit 0   # not a Bash call, or unparseable → fail open

is_wrapper() {
	case "$1" in
		env|time|nohup|exec|command|nice|sudo|xargs) return 0 ;;
		[A-Za-z_]*=*) return 0 ;;
		*) return 1 ;;
	esac
}

# An operation in progress (merge/rebase/cherry-pick/revert) is a commit with no
# sensible pathspec — git rejects a partial commit outright there. Consulted
# ONLY on the way to a block, so the (comparatively expensive) cwd decode and
# the git call stay off the path every allowed commit takes.
operation_in_progress() {
	local session_cwd gitdir
	session_cwd="$(hook_json_field "$INPUT" cwd)"
	[ -n "$session_cwd" ] || session_cwd="$PWD"
	gitdir="$(git -C "$session_cwd" rev-parse --absolute-git-dir 2>/dev/null || true)"
	[ -n "$gitdir" ] || return 1
	[ -e "$gitdir/MERGE_HEAD" ] && return 0
	[ -e "$gitdir/CHERRY_PICK_HEAD" ] && return 0
	[ -e "$gitdir/REVERT_HEAD" ] && return 0
	[ -d "$gitdir/rebase-merge" ] && return 0
	[ -d "$gitdir/rebase-apply" ] && return 0
	return 1
}

sweeping=""
sweeps_all=0
# shellcheck disable=SC2020  # the tr below maps a char SET to newline — exactly the intent
while IFS= read -r segment; do
	[ -n "$segment" ] || continue
	IFS=' 	' read -ra toks <<<"$segment"
	[ "${#toks[@]}" -gt 0 ] || continue

	# --- command word must be git ---
	idx=0
	while [ "$idx" -lt "${#toks[@]}" ] && is_wrapper "${toks[$idx]}"; do
		idx=$((idx + 1))
	done
	[ "$idx" -lt "${#toks[@]}" ] || continue
	case "${toks[$idx]##*/}" in
		git) ;;
		*) continue ;;
	esac
	idx=$((idx + 1))

	# --- git's own options, before the subcommand ---
	while [ "$idx" -lt "${#toks[@]}" ]; do
		case "${toks[$idx]}" in
			-C|-c|--git-dir|--work-tree|--namespace|--exec-path) idx=$((idx + 2)) ;;
			-*) idx=$((idx + 1)) ;;
			*) break ;;
		esac
	done
	[ "$idx" -lt "${#toks[@]}" ] || continue
	[ "${toks[$idx]}" = "commit" ] || continue

	# --- the commit's own arguments ---
	idx=$((idx + 1))
	verdict="sweep"
	all=0
	while [ "$idx" -lt "${#toks[@]}" ]; do
		case "${toks[$idx]}" in
			--) verdict="pathspec"; break ;;
			--amend|--dry-run|--help|-h|--interactive|--patch|-p) verdict="exempt"; break ;;
			--pathspec-from-file|--pathspec-from-file=*)
				# Naming paths via a file IS naming paths — this earns the
				# pathspec verdict in both spellings. Must precede the generic
				# `--*=*` skip, which would otherwise swallow the `=` form.
				verdict="pathspec"; break ;;
			--*=*) idx=$((idx + 1)) ;;
			--message|--file|--reuse-message|--reedit-message|--author|--date|--template|--cleanup|--trailer|--fixup|--squash)
				idx=$((idx + 2)) ;;
			--*) idx=$((idx + 1)) ;;
			-*)
				# Short-option cluster. `a` anywhere means -a/--all; a trailing
				# m/F/C/c/t consumes the next token as its argument.
				case "${toks[$idx]}" in *a*) all=1 ;; esac
				case "${toks[$idx]}" in
					*[mFCct]) idx=$((idx + 2)) ;;
					*) idx=$((idx + 1)) ;;
				esac
				;;
			*) verdict="pathspec"; break ;;   # a bare argument IS a pathspec
		esac
	done

	if [ "$verdict" = "sweep" ]; then
		sweeping="$segment"
		sweeps_all="$all"
		break
	fi
done <<<"$(printf '%s' "$ANALYZE" | tr ';|&()`{}' '\n\n\n\n\n\n\n\n')"

[ -n "$sweeping" ] || exit 0
operation_in_progress && exit 0

{
	echo "BLOCKED (shared-tree commit guard): this \`git commit\` names no paths."
	echo "  offending segment: ${sweeping# }"
	echo ""
	if [ "$sweeps_all" -eq 1 ]; then
		echo "  \`-a\`/\`--all\` stages EVERY modified tracked file in the tree — including"
		echo "  every file a peer agent is editing right now. This is the sweep itself."
	else
		echo "  \`git commit\` commits the whole INDEX. \`git add <files>\` does not protect"
		echo "  you from what a peer already staged in this shared tree, and a pushed"
		echo "  branch is forward-only, so a swept commit cannot be taken back."
	fi
	echo ""
	echo "  Fix — name your paths, last, after \`--\`:"
	echo "    git commit -m \"<type>(<scope>): <msg>\" -- <path> [<path>...]"
	echo ""
	echo "  Exempt (waved through, no need to work around this guard): --amend,"
	echo "  --dry-run, --interactive/--patch, and any commit finishing a merge /"
	echo "  rebase / cherry-pick / revert."
} >&2
exit 2
