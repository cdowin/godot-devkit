#!/usr/bin/env bash
# cc-commit-pathspec.sh — Claude Code PreToolUse Bash hook: a `git commit` must
# name its own paths (`-- <paths>`), because in a shared tree it commits the
# whole index and a pushed branch is forward-only. Waved through: a pathspec
# already present (`--`, a bare path, `--pathspec-from-file`), `--amend`,
# `--dry-run`, `--help`, `--interactive`/`--patch`, and a merge/rebase/
# cherry-pick/revert in progress. Stdin: the PreToolUse JSON (tool_name,
# tool_input.command, cwd). Exit 0 = allow, 2 = block; failures exit 0.
set -eu
trap 'exit 0' ERR

# hook_json_field <payload> <dotted.key> — echo a STRING field, or nothing.
# Inline, and a real JSON parser: a command embeds escaped quotes, which a
# grep extractor truncates at, handing the guard half a command line.
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

# Decode and normalise in one pass: heredoc bodies are dropped, `$(…)` and
# backtick spans and quoted runs collapse to one opaque token, so a multi-line
# message never hides the `-- <paths>` after it. Every ambiguity resolves to
# ALLOW, and without python3 the guard yields rather than guess with regexes.
command -v python3 >/dev/null 2>&1 || exit 0
# shellcheck disable=SC2016  # the python source stays literal
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

# An operation in progress is a commit git itself refuses a pathspec for;
# consulted only on the way to a block.
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
				# Naming paths via a file is naming paths; must precede the generic `--*=*` skip.
				verdict="pathspec"; break ;;
			--*=*) idx=$((idx + 1)) ;;
			--message|--file|--reuse-message|--reedit-message|--author|--date|--template|--cleanup|--trailer|--fixup|--squash)
				idx=$((idx + 2)) ;;
			--*) idx=$((idx + 1)) ;;
			-*)
				# A short-option cluster: `a` anywhere is --all; a trailing m/F/C/c/t takes the next token.
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
