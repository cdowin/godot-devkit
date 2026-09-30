#!/usr/bin/env bash
# cc-git-allowlist.sh — Claude Code PreToolUse Bash hook: the git an agent
# session may run is an ALLOWLIST, because the flow is `git add <paths>`,
# `git commit -m … -- <paths>`, `git push` and the milestone merge, and every
# other verb is a chance to move HEAD, sweep a peer's edits or rewrite what was
# pushed. Allowed: ALLOW_SUBCOMMANDS below with any arguments; `commit` bar
# `--amend` (cc-commit-pathspec.sh judges its paths); `push` bar a force or a
# PROTECTED_BRANCHES destination; `merge` of a MERGE_BRANCHES branch, or
# `--ff-only` of a remote-tracking ref; `pull --ff-only [<remote> [<branch>]]`;
# `config` reads; `branch` bar force-delete/move/force (`-d` is the safe
# delete); `tag` bar delete/move/force; `switch <branch>` and
# `switch -c <new> [<start>]`; `symbolic-ref <ref>` (a read); `stash list`;
# `worktree list|prune`; `remote` bar rewiring; `archive` bar `-o`/`--remote`;
# and a scratch probe's git: `init`, `clone`, or any verb, whose every `-C`,
# init target and clone destination is an ABSOLUTE path (`~/` reads as $HOME/)
# outside every checkout of this repository (the hook's own, CLAUDE_PROJECT_DIR's
# and cwd's) — never in a command that runs `ln` or sets a GIT_* location,
# `--git-dir`, `--work-tree`, `--namespace` or a `-c` location key (core.worktree,
# core.bare, core.hooksPath, core.gitdir, include.*, includeIf.*), and no `~` in
# a command that sets HOME. A refusal whose `-C`, init target or clone destination
# is outside this checkout, or whose `-C` is a `$VAR`, names that absolute `-C`
# route. A word the verdict turns on — the subcommand, a merge source, a push
# destination — typed as a `$VAR` or a backtick span is blocked: the hook reads the
# typed text, so it cannot know what that word names.
# Every judged verb takes its long options spelled EXACTLY (git expands an
# abbreviation, so `--forc` is `--force`); a short bundle is judged letter by
# letter. Blocked, each with its reason and the boring alternative: bisect, stash,
# reset, checkout, restore, clean, rebase, a pull or switch that could lose
# work, and any subcommand named nowhere here. Only the command the agent TYPES
# is read: git run inside a script or a make target — tools/dev/agent-worktree.sh's
# own `worktree add` — is never seen. `bash cc-git-allowlist.sh --self-test`
# replays the command corpus. Stdin: the PreToolUse JSON (tool_name,
# tool_input.command). Exit 0 = allow, 2 = block; failures exit 0.
set -eu
trap 'exit 0' ERR

# --- project config (yours to edit after install — the file is your repo's) --
# git subcommands allowed with ANY arguments, space-separated. One named here
# skips every judgement below, the named blocks included: widening the list is
# this line, edited in a commit, never a workaround for one call. `switch` is
# here because lanes work in their own worktrees: the root checkout is the
# orchestrator's alone (operator-approved 2026-09-12).
ALLOW_SUBCOMMANDS="add status diff log show switch rev-parse rev-list merge-base ls-files ls-tree ls-remote cat-file grep blame describe shortlog show-ref for-each-ref name-rev range-diff fetch mv rm help version"
# Branches (exact, space-separated) no `git push` may name as its destination.
# Keep in step with pre-push's PROTECTED_BRANCHES, which backstops the rest.
PROTECTED_BRANCHES="main"
# Branch globs (space-separated) a `git merge` may name: the milestone branch,
# the agent branches tools/dev/agent-worktree.sh cuts (its BRANCH_PREFIX), and
# the mainline, which the release skill merges INTO the milestone branch.
MERGE_BRANCHES="milestone/* feat/* main origin/main"
# -----------------------------------------------------------------------------

# A header carried from an older install may lack a key: it runs at its stock value.
declare -p ALLOW_SUBCOMMANDS >/dev/null 2>&1 || ALLOW_SUBCOMMANDS="add status diff log show rev-parse rev-list merge-base ls-files ls-tree ls-remote cat-file check-ignore check-attr var grep blame describe shortlog show-ref for-each-ref name-rev range-diff fetch mv rm help version"
declare -p PROTECTED_BRANCHES >/dev/null 2>&1 || PROTECTED_BRANCHES="main"
declare -p MERGE_BRANCHES >/dev/null 2>&1 || MERGE_BRANCHES="milestone/* feat/*"

# --- --self-test — the command corpus -----------------------------------------
# The corpus runs against a copy of THIS file at the header's STOCK values (the
# block dropped, so the fallbacks above fill it in): a project that widened its
# own header still replays the kit's corpus. The table replays in ONE python
# process (`--self-test-replay`, a fork per row made it seconds); the rows below
# it go through the whole hook, payload to exit code and stderr.
HOOK_NAME="cc-git-allowlist.sh"

# The payload, escaped by hand, so a row costs one fork rather than two.
self_test_payload() {
	local s="$2" cwd="${3:-/}"
	s="${s//\\/\\\\}"
	s="${s//\"/\\\"}"
	s="${s//$'\t'/\\t}"
	s="${s//$'\n'/\\n}"
	printf '{"tool_name":"%s","tool_input":{"command":"%s"},"cwd":"%s"}' "$1" "$s" "$cwd"
}

# case <hook> <want exit> <tool> <command> [cwd] [text] — a block must also name its
# alternative; with <text>, the output must carry it, and with `!<text>`, must not.
self_test_case() {
	local hook="$1" want="$2" tool="$3" line="$4" text="${6:-}" out rc=0 miss=""
	out="$(self_test_payload "$tool" "$line" "${5:-/}" | bash "$hook" 2>&1)" || rc=$?
	if [ "$rc" != "$want" ]; then
		miss="wanted exit $want, got $rc"
	elif [ "$want" = 2 ]; then
		case "$out" in
			*"instead: "*) ;;
			*) miss="blocked with no alternative named" ;;
		esac
	fi
	case "$text" in
		"") ;;
		!*) case "$out" in *"${text#!}"*) miss="${miss:-says what it must not: ${text#!}}" ;; esac ;;
		*) case "$out" in *"$text"*) ;; *) miss="${miss:-does not say: $text}" ;; esac ;;
	esac
	[ -n "$miss" ] || return 0
	printf '  MISS — %s: %s\n    %s\n' "${line//$'\n'/ \\n }" "$miss" \
		"${out//$'\n'/ | }" >&2
	return 1
}

self_test() {
	local rc=0 tmp stock widened counts blocked=0 allowed=0
	if ! command -v python3 >/dev/null 2>&1; then
		echo "[$HOOK_NAME] SELF-TEST FAIL — python3 is not on PATH, so this guard yields on every call and guards nothing" >&2
		return 1
	fi
	tmp="$(mktemp -d "${TMPDIR:-/tmp}/cc-git-allowlist-selftest.XXXXXX")"
	# The copies sit in `repo`, and the table replays from its linked worktree `wt`: the bug's seat.
	mkdir -p "$tmp/repo/.git/worktrees/wt" "$tmp/repo/sub" "$tmp/wt" "$tmp/scratch/.git" "$tmp/home"
	printf 'gitdir: %s\n' "$tmp/repo/.git/worktrees/wt" >"$tmp/wt/.git"
	printf '%s\n' "$tmp/wt/.git" >"$tmp/repo/.git/worktrees/wt/gitdir"
	printf '../..\n' >"$tmp/repo/.git/worktrees/wt/commondir"
	# The one remote it declares: `origin/<branch>` is remote-tracking, `upstream/<branch>` is not.
	printf '[remote "origin"]\n\turl = /nowhere\n' >"$tmp/repo/.git/config"
	stock="$tmp/repo/stock.sh"
	widened="$tmp/repo/widened.sh"
	# The opening marker is split so this line is never mistaken for it.
	awk 'BEGIN { opening = "--- project " "config (yours" }
		!done && index($0, opening) { skip = 1; next }
		skip && /^# ---+$/ { skip = 0; done = 1; next }
		!skip { print }' "$0" >"$stock"
	{ echo 'ALLOW_SUBCOMMANDS="stash"'; cat "$stock"; } >"$widened"

	# <want exit> <command>, one per line; the replay prints `<blocked> <allowed>`.
	cat >"$tmp/corpus" <<'CORPUS'
# Blocked: every named verb, its dangerous shapes, and each way a segment hides it.
2 git bisect run make unit
2 git bisect start
2 git stash
2 git stash push -- src/x.py
2 git reset --hard
2 git reset HEAD~1
2 git checkout -- .
2 git checkout milestone/0.9.0
2 git switch -f main
2 git switch --discard-changes main
2 git switch -C feat/x
2 git switch --detach HEAD~1
2 git switch --orphan scratch
2 git switch -m main
2 git restore src/x.py
2 git clean -fdx
2 git rebase milestone/0.9.0
2 git pull
2 git pull origin main
2 git pull --rebase
2 git pull --no-ff origin main
2 git pull --ff-only --rebase
2 git pull --ff-only -r origin main
2 git pull --ff-only --autostash
2 git pull --ff-only origin main:main
2 git stash pop
2 git stash drop
2 git stash clear
2 git symbolic-ref refs/remotes/origin/HEAD refs/remotes/origin/main
2 git symbolic-ref HEAD refs/heads/feat/x
2 git symbolic-ref -d HEAD
2 git symbolic-ref --delete refs/remotes/origin/HEAD
2 git worktree add ../elsewhere -b feat/x
2 git worktree remove .claude/worktrees/x
2 git commit --amend --no-edit
2 git commit -m "fix: x" --amend -- src/x.py
2 git push --force origin milestone/0.9.0
2 git push -f
2 git push --force-with-lease=milestone/0.9.0
2 git push origin +milestone/0.9.0
2 git push origin main
2 git push origin HEAD:refs/heads/main
2 git config core.bare true
2 git config --unset core.hooksPath
2 git branch -D feat/x
2 git branch -d -f feat/x
2 git branch --delete --force feat/x
2 git branch -m feat/x feat/y
2 git branch -M feat/y
2 git branch -f feat/x HEAD
2 git branch -dr origin/feat/x
# A long option is judged spelled exactly — git expands any unambiguous abbreviation — and a short bundle letter by letter.
2 git branch -d --forc feat/x
2 git branch --del --forc feat/x
2 git branch -dD feat/x
2 git branch -df feat/x
2 git symbolic-ref --del refs/remotes/origin/HEAD
2 git symbolic-ref -qd HEAD
2 git switch --discard main
2 git pull --ff-only --reb
2 git pull --ff-only --refmap=+refs/heads/*:refs/heads/*
2 git merge --ff-only --autostash origin/main
2 git merge --autostash feat/x
2 git merge --no-ff --autost feat/x
2 git stash list --onel
2 git worktree prune --exp=now
2 git archive --out=x.tar HEAD
2 git archive --rem=origin HEAD
2 git init -q --sep=/r/.git /tmp/x
2 git init -q /tmp/x --separate-git-dir=/r/.git
2 git config --unse core.hooksPath
2 git tag --forc v1.0.0
2 git tag --del v1.0.0
2 git commit --am --no-edit
2 git push --force-w origin milestone/0.9.0
2 git push --forc
2 git tag -f v1.0.0
2 git merge main
2 git merge
2 git merge origin/main
2 git merge --ff-only main
2 git merge --ff-only --no-ff origin/main
2 git merge --ff-only upstream/main
# A word the verdict turns on, typed as a variable, is a word this guard cannot read: it blocks.
2 git merge origin/lane/$b
2 GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=core.worktree GIT_CONFIG_VALUE_0=/r git -C /tmp/x reset --hard
2 GIT_CONFIG_PARAMETERS=x git -C /tmp/x reset --hard
2 git merge --ff-only origin/$b
2 git merge "$BRANCH"
2 for b in x y; do git merge --no-ff -q origin/lane/$b -m "m"; done
2 git push origin HEAD:$TARGET
2 v=stash; git $v
2 git cherry-pick 1a2b3c4
2 git remote set-url origin https://example.invalid/x.git
2 git -C .claude/worktrees/x stash
2 git -c core.bare=false bisect start
2 /usr/bin/git stash
2 env GIT_TRACE=1 git stash
2 cd src && git stash
2 make unit; git reset --hard
2 echo $(git stash)
2 if git stash; then :; fi
2 timeout 60 git bisect run make unit
2 git init
2 git init -q 2>/dev/null; git add -A
2 cd /tmp/x && git init -q
2 git -C sub init -q
2 git init -q ../repo/sub
2 git -C ../repo init
2 git -C ../repo stash
2 GIT_DIR=/r/.git/worktrees/x git init -q /tmp/zz
2 git -C /tmp --git-dir=/r/.git --work-tree=/r reset --hard
2 env GIT_WORK_TREE=/r git -C /tmp/x reset --hard
2 git --namespace x -C /tmp/x reset --hard
2 GIT_INDEX_FILE=/r/.git/index git -C /tmp/x reset
2 cd src && git -C .. reset --hard
2 cd .claude && git -C .. init
# A `~/` path is $HOME/ and judged there, so it is not blanket-exempt.
2 git -C ~/../repo reset --hard
2 git -C ~/../repo/sub init -q
# A command that sets HOME expands `~` where this hook cannot see, so `~` is not read.
2 HOME=/r; git -C ~/x reset --hard
2 export HOME=/r && git -C ~/x reset --hard
2 declare -x HOME; git -C ~/x reset --hard
2 env HOME=/r git -C ~/x reset --hard
2 git -C /tmp -C src reset --hard
# A `-c` location key redirects git as `--work-tree` does; git config keys are case-insensitive.
2 git -c core.worktree=/r -C /tmp/x reset --hard
2 git clone -c core.worktree=/r https://example.invalid/x.git /tmp/x
2 git -c Core.HooksPath=/r/hooks -C /tmp/x reset --hard
2 git -c includeIf.gitdir:/tmp/.path=/r/cfg -C /tmp/x reset --hard
2 git clone --config=core.bare=true https://example.invalid/x.git /tmp/x
2 ln -s /r /tmp/l && git -C /tmp/l reset --hard
2 ln -s /r /tmp/l && git -C /tmp/l switch -f main
2 git -C /tmp --git-dir=/r/.git branch -D feat/x
2 GIT_DIR=/r/.git git -C /tmp/x symbolic-ref HEAD refs/heads/x
2 git -C ../repo pull
2 git archive -o /r/.git/config HEAD
2 git archive --output=x.tar HEAD
2 git archive --remote=origin HEAD
# A clone is judged by its destination: none, a relative one, a location option, or an option
# this guard cannot parse keeps the block.
2 git clone https://example.invalid/x.git
2 git clone https://example.invalid/x.git rel
2 git clone https://example.invalid/x.git ../repo/sub/x
2 git clone --separate-git-dir=/r/.git https://example.invalid/x.git /tmp/x
2 git clone --template /t https://example.invalid/x.git /tmp/x
2 git clone --sep /r/.git https://example.invalid/x.git /tmp/x
2 git clone --upload-pack=/tmp/cmd https://example.invalid/x.git /tmp/x
2 git clone -u /tmp/cmd https://example.invalid/x.git /tmp/x
2 git clone --reference-if-able /abs/a /abs/src
2 git clone --frobnicate /abs/a /abs/src
2 git clone -x /abs/a /abs/src
# Allowed: the flow itself, the reads, the kit's own tools, and git named as data.
0 git add src/x.py tests/test_x.py
0 git commit -m "feat: x" -- src/x.py
0 git commit -m "docs: never git stash; never git reset --hard" -- README.md
0 git push -u origin milestone/0.9.0
0 git push origin refs/tags/v0.9.0
0 git push
0 git push origin feat/x:milestone/0.9.0
0 git merge --no-ff feat/x -m "merge feat/x"
0 git -C /repo merge milestone/0.9.0
0 git merge --abort
0 git merge feat/x
0 git push -u origin feat/x
2 git push $REMOTE feat/x
2 git branch $X feat/x
2 git switch -c $N
2 git switch --create $N
2 git push --repo=$R feat/x
2 git switch "$BRANCH"
0 git switch feat/x
0 git status --porcelain
0 git diff HEAD -- src/x.py
0 git log --oneline -10
0 git log --grep stash
0 git show HEAD:src/x.py
0 git rev-parse --show-toplevel
0 git config --get core.hooksPath
0 git config core.hooksPath
0 git config --list
0 git branch -a
0 git branch --show-current
0 git branch milestone/0.10.0
0 git branch
0 git branch -r
0 git branch --list 'feat/*'
0 git branch --merged
0 git branch --no-merged main
0 git branch -d feat/x
0 git branch -d feat/x feat/y
0 git branch --delete feat/x
0 git branch --list --merged main
0 git symbolic-ref --quiet --short refs/remotes/origin/HEAD
0 git pull --ff-only --prune origin main
0 git merge --ff-only --no-autostash origin/main
0 git merge --no-ff --no-edit --message "merge feat/x" feat/x
0 git stash list --oneline
0 git worktree prune --expire now
0 git archive --format=tar --prefix=x/ HEAD
0 git init -q --initial-branch=main /tmp/x
0 git config --get-regexp remote
0 git tag --list 'v*'
0 git commit --signoff -m "feat: x" -- src/x.py
0 git push --set-upstream origin milestone/0.9.0
0 git switch main
0 git switch -
0 git switch -c feat/x
0 git switch -c feat/x milestone/0.9.0
0 git switch --create feat/x --no-track origin/main
0 git switch main && git pull --ff-only
0 git pull --ff-only
0 git pull --ff-only origin
0 git pull --ff-only origin main
0 git merge --ff-only origin/main
0 git merge --ff-only refs/remotes/origin/main
0 git symbolic-ref refs/remotes/origin/HEAD
0 git symbolic-ref --short -q refs/remotes/origin/HEAD
0 git symbolic-ref HEAD
0 git stash list
0 git stash list --date=relative
0 git tag v0.9.0 && git push origin refs/tags/v0.9.0
0 git tag -l
0 git worktree list
0 git worktree list --porcelain
0 git worktree prune
0 git fetch --prune
0 git remote -v
0 git remote set-head origin --auto
0 git help stash
0 git status 2>&1 | head -5
0 git merge feat/x 2>&1
0 bash tools/dev/agent-worktree.sh new --no-warm x milestone/0.9.0
0 bash tools/dev/agent-worktree.sh done x
0 cd /repo && bash tools/dev/agent-worktree.sh new l-guards
0 cd /repo && bash tools/dev/agent-worktree.sh done l-guards
0 git -C /repo merge --no-ff --no-edit feat/l-guards
0 git -C /repo/.claude/worktrees/x add src/x.py
0 git -C /repo/.claude/worktrees/x commit -m "feat: x" -- src/x.py
0 git -C /tmp/x init -q
0 git init -q /tmp/x
0 git -C /tmp/x commit -qm base
0 git -C /tmp/x reset --hard
0 git -c color.ui=never -C /tmp/x status
0 git -c color.ui=never -C /tmp/x reset --hard
0 git -C ~/scratch init -q
0 git init -q ~/scratch
0 git -C ~/x worktree add /tmp/y origin/main
0 git clone https://example.invalid/x.git /tmp/scratch/x
0 git clone --depth 1 -b main --origin up https://example.invalid/x.git /tmp/scratch/x
0 git clone -qj 4 --filter blob:none --single-branch https://example.invalid/x.git /tmp/scratch/x
0 git clone https://example.invalid/x.git ~/scratch/x
0 git -C /tmp/scratch clone https://example.invalid/x.git x
0 git check-ignore -v f
0 git check-attr -a f
0 git var GIT_EDITOR
0 mkdir -p /tmp/s && git archive HEAD | tar -x -C /tmp/s && git -C /tmp/s init -q && git -C /tmp/s add -A && git -C /tmp/s -c user.name=probe -c user.email=probe@local commit -qm base
0 make check
0 make pm ARGS='story building st-x'
0 echo git stash
0 grep -n "git reset --hard" SDLC.md
CORPUS
	# HOME sits beside the copies, so a `~/` row reads the same on every machine.
	counts="$(cd "$tmp/wt" && HOME="$tmp/home" bash "$stock" --self-test-replay <"$tmp/corpus")" || rc=1
	case "$counts" in
		*[0-9]" "[0-9]*) blocked="${counts% *}"; allowed="${counts#* }" ;;
		*) rc=1 ;;
	esac

	# A heredoc body is data; the line after it is code again.
	self_test_case "$stock" 0 Bash "git commit -m \"\$(cat <<'EOF'
fix: stop the drift

The body may say git stash, git reset --hard; git bisect run.
EOF
)\" -- src/x.py" && allowed=$((allowed + 1)) || rc=1
	self_test_case "$stock" 2 Bash "cat <<EOF >notes.txt
git status
EOF
git stash" && blocked=$((blocked + 1)) || rc=1
	# "This repository" is the hook's own checkout too, wherever a `cd` left cwd.
	self_test_case "$stock" 2 Bash "git -C $tmp/repo reset --hard" "$tmp/scratch" && blocked=$((blocked + 1)) || rc=1
	self_test_case "$stock" 2 Bash "git -C $tmp/wt init -q" "$tmp/scratch" && blocked=$((blocked + 1)) || rc=1
	self_test_case "$stock" 2 Bash "git -C $tmp/wt init -q" / && blocked=$((blocked + 1)) || rc=1
	self_test_case "$stock" 0 Bash "git -C /tmp/x init -q" / && allowed=$((allowed + 1)) || rc=1
	# A refusal whose `-C` target, init target or clone destination is outside this checkout
	# names the route to that repository; a pathspec or a bare `~` does not, and a `-C $VAR`
	# is told the hook reads the typed text.
	route="for another repository, spell its absolute path: \`git -C /abs/path worktree …\`"
	self_test_case "$stock" 2 Bash "git -C /tmp/s clone --template /t https://example.invalid/x.git x" "$tmp/wt" \
		"for another repository, spell its absolute path: \`git -C /abs/path clone …\`" && blocked=$((blocked + 1)) || rc=1
	self_test_case "$stock" 2 Bash "git clone -u /c https://example.invalid/x.git /tmp/x" "$tmp/wt" \
		"for another repository" && blocked=$((blocked + 1)) || rc=1
	for line in "git worktree add /tmp/x origin/main" "git worktree add .claude/worktrees/x -b feat/x" \
		"git stash push /tmp/x" "git reset --hard ~"; do
		self_test_case "$stock" 2 Bash "$line" "$tmp/wt" "!for another repository" && blocked=$((blocked + 1)) || rc=1
	done
	self_test_case "$stock" 2 Bash "N=/tmp/x; git -C \$N worktree add /tmp/y origin/main" "$tmp/wt" \
		"$route — this hook reads the typed text, so \`\$N\` is not expanded" && blocked=$((blocked + 1)) || rc=1
	# Only a Bash call is judged.
	self_test_case "$stock" 0 Edit "git stash" && allowed=$((allowed + 1)) || rc=1
	# The header is what widens the list, and it widens only what it names.
	self_test_case "$widened" 0 Bash "git stash" || rc=1
	self_test_case "$widened" 2 Bash "git reset --hard" || rc=1

	rm -rf "$tmp"
	if [ "$rc" -eq 0 ]; then
		echo "[$HOOK_NAME] SELF-TEST OK — $blocked blocked, each naming its alternative; $allowed allowed; ALLOW_SUBCOMMANDS widens exactly what it names"
	else
		echo "[$HOOK_NAME] SELF-TEST FAIL — see the case(s) above" >&2
	fi
	return "$rc"
}

# --- the judgement ------------------------------------------------------------
# A real tokenizer, because a regex over the command line reads a commit
# message as commands. Heredoc bodies are dropped, backtick spans are opaque,
# quotes are honoured, and each `;` `&&` `|` `(` or newline starts a new
# segment, so `cd x && git stash` and `$(git stash)` are both seen. A word it
# cannot know (`$BRANCH`) is never guessed at: where the verdict turns on it,
# it BLOCKS. Prints the block
# message, or nothing; every exception is nothing.
# argv: ALLOW_SUBCOMMANDS PROTECTED_BRANCHES MERGE_BRANCHES HOOK_DIR [--corpus]
# shellcheck disable=SC2016  # the python source stays literal
ANALYZER='
import fnmatch, json, os, re, sys

ALLOW = set(sys.argv[1].split())
PROTECTED = set(sys.argv[2].split())
MERGEABLE = sys.argv[3].split()
HOOK_DIR = sys.argv[4]
REDIRECTS = ("GIT_DIR=", "GIT_WORK_TREE=", "GIT_COMMON_DIR=", "GIT_INDEX_FILE=", "GIT_CONFIG", "--git-dir", "--work-tree", "--namespace")
# A config key that points git at another tree, git directory or config file, or runs hooks from
# elsewhere: set with `-c`, `--config-env` or clone\x27s `--config`, it redirects as `--work-tree` does.
LOCATION_KEYS = ("core.worktree", "core.bare", "core.hookspath", "core.gitdir")
LOCATION_SECTIONS = ("include.", "includeif.")
OPAQUE = "__OPAQUE__"
OPENER = re.compile(r"(?<!<)<<(?!<)-?\s*([\x27\"]?)([A-Za-z_][A-Za-z0-9_]*)\1")
OPS = ";&|()<>\n"
WRAPPERS = {"env", "time", "nohup", "exec", "command", "builtin", "nice", "sudo",
            "xargs", "!", "{", "if", "then", "else", "elif", "do", "while", "until"}
ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
TOOL = "bash tools/dev/agent-worktree.sh"
FLOW = "`git add <paths>`, `git commit -m \"…\" -- <paths>`, `git push`, and the milestone merge"

NAMED = {
    "bisect": ("walks HEAD of the checkout through history under every agent in it, and a `bisect run` left mid-way in a linked worktree has flipped a repository to `core.bare = true`",
               "read history without checking it out — `git log --oneline <range>`, `git show <rev>:<path>`; to watch a test fail at HEAD, copy the file to a scratch path"),
    "stash": ("`refs/stash` is shared by every worktree, and a stash sweeps every uncommitted edit out of the tree — a peer\x27s included",
              "to watch a test fail at HEAD, copy the file to a scratch path; the pathspec form is still a stash; `git stash list` reads"),
    "reset": ("moves HEAD or rewrites the index and tree under every agent in this checkout, and a pushed branch is forward-only",
              "fix forward with a new commit that names its paths — `git commit -m \"…\" -- <path>`; a stray staged file is harmless when every commit names its paths"),
    "checkout": ("rewrites the working tree: a path form discards uncommitted edits, a peer\x27s included, and a branch form switches the branch under every agent in this checkout",
                 "read a committed file with `git show HEAD:<path>`; another branch is a tree of your own — `" + TOOL + " new <slug>`"),
    "restore":("discards uncommitted edits, a peer\x27s included, or unstages what a peer staged",
                "read a committed file with `git show HEAD:<path>`; to watch a test fail at HEAD, copy the file to a scratch path"),
    "clean": ("deletes untracked files, a peer\x27s new files included",
              "`rm` the one path you created"),
    "rebase": ("rewrites history, and nothing pushed is rebased",
               "take upstream work with a merge — `git merge <milestone-branch>`"),
}
PULL = ("fetches and then merges or rebases whatever the upstream config says, in one step you did not choose",
        "`git pull --ff-only [<remote> [<branch>]]` — a fast-forward cannot lose work; or `git fetch`, then `git merge --ff-only <remote>/<branch>`")
SWITCH = ("discards or overwrites work in this checkout, force-resets a branch, or leaves HEAD somewhere no branch names",
          "`git switch <branch>`, or `git switch -c <new> [<start>]` — git refuses over conflicting edits; a branch to work on beside a peer is a tree of your own — `" + TOOL + " new <slug>`")
SYMREF = ("writes or deletes a symbolic ref — `HEAD` of a checkout, or a remote\x27s HEAD every worktree reads",
          "read it with one ref argument — `git symbolic-ref --short <ref>`; a remote\x27s HEAD is reset with `git remote set-head <remote> --auto`")
AMEND = ("rewrites the commit HEAD names, and a pushed branch is forward-only",
         "a new commit that names its paths — `git commit -m \"…\" -- <path>`")
FORCE = ("rewrites the remote branch — nothing pushed is amended, rebased, reset or force-pushed",
         "push a new commit on top; a rejected push is `git fetch` and `git merge <branch>`, then push again")
CONFIG = ("writes configuration that every worktree of this repository shares — a stray `core.bare = true` is one such write",
          "`git -c <key>=<value> <command>` scopes a setting to one command; a standing change is the operator\x27s")
BRANCH = ("force-deletes, renames or force-moves a branch, or deletes a remote-tracking one, and agent branches are made and retired by the worktree tool",
          "`git branch -d <branch>` deletes a merged one and refuses unmerged work; `" + TOOL + " done <slug>` retires an agent\x27s; `git branch -a` lists")
TAG = ("moves or deletes a tag, and a published tag is never force-moved",
       "tag a new version; `git tag -l` lists")
WORKTREE_ADD = ("an ad-hoc worktree bases wherever it is told and carries no scope marker, so no guard knows an agent works there",
                "`" + TOOL + " new <slug>` — it bases on the milestone\x27s declared `branch:` and writes the marker")
WORKTREE_OTHER = ("tears down or moves a worktree an agent may still be working in",
                  "`" + TOOL + " done <slug>` — it refuses uncommitted or unmerged work; `git worktree list` lists")
REMOTE = ("rewires where this repository fetches from and pushes to",
          "that is the operator\x27s; `git remote -v` lists")
MERGE_NOTHING = ("names no branch, so it merges whatever the upstream config says",
                 "name it — `git merge <milestone-branch>`")
INIT = ("with no target outside this repository it re-initialises a checkout of it, and in a linked worktree that writes `core.bare = true` into the config every checkout shares",
        "build a scratch repository by absolute path, in one command — `git -C /abs/scratch init -q && git -C /abs/scratch add -A`")
AUTOSTASH = ("stashes every uncommitted edit in the tree, a peer\x27s included, and replays them after",
             "merge without it — git refuses a merge that would overwrite an uncommitted edit, and that edit is someone\x27s")
ARCHIVE = ("writes the archive to a path, or reads another repository",
           "stream it — `git archive HEAD | tar -x -C /abs/scratch`")
CLONE = ("with no destination outside this repository, or a location flag, it writes a new repository into a checkout of it",
         "clone to an absolute path outside this checkout, in one command — `git clone <url> /abs/scratch/<name>`")


def tokens(text):
    word, has, i, n = [], False, 0, len(text)
    while i < n:
        c = text[i]
        if c == "\\" and i + 1 < n:
            word.append(text[i + 1]); has = True; i += 2
        elif c == "\x27":
            end = text.index("\x27", i + 1)
            word.append(text[i + 1:end]); has = True; i = end + 1
        elif c == "\"":
            i += 1
            while text[i] != "\"":
                if text[i] == "\\" and text[i + 1] in "\"\\$`":
                    i += 1
                word.append(text[i]); i += 1
            has = True; i += 1
        elif c in " \t\r":
            if has:
                yield "word", "".join(word)
            word, has = [], False
            i += 1
        elif c == "#" and not has:
            while i < n and text[i] != "\n":
                i += 1
        elif c in OPS:
            if has:
                yield "word", "".join(word)
            word, has = [], False
            end = i
            while end < n and text[end] in OPS:
                end += 1
            yield "op", text[i:end]
            i = end
        else:
            word.append(c); has = True; i += 1
    if has:
        yield "word", "".join(word)


def segments(command):
    kept, delimiter = [], None
    for line in command.split("\n"):
        if delimiter is not None:
            if line.strip() == delimiter:
                delimiter = None
            continue
        found = OPENER.search(line)
        if found:
            delimiter = found.group(2)
        kept.append(OPENER.sub(" " + OPAQUE + " ", line))
    text = "\n".join(kept).replace("\\\n", " ")
    text = re.sub(r"`[^`]*`", " " + OPAQUE + " ", text)
    current, target = [], False
    for kind, value in tokens(text):
        if kind == "word":
            if target:
                target = False
            else:
                current.append(value)
        elif any(c in ";|()\n" for c in value) or ("&" in value and not any(c in "<>" for c in value)):
            if current:
                yield current
            current, target = [], False
        else:
            # A redirection: its fd number and its target are not arguments.
            if current and current[-1].isdigit():
                current.pop()
            target = True
    if current:
        yield current


def command_word(words):
    i, n = 0, len(words)
    while i < n:
        if words[i] == "timeout":
            i += 1
            while i < n and words[i].startswith("-"):
                i += 1
            i += 1
        elif words[i] in WRAPPERS:
            i += 1
            while i < n and words[i].startswith("-"):
                i += 1
        elif ASSIGNMENT.match(words[i]):
            i += 1
        else:
            break
    return i, (words[i].rsplit("/", 1)[-1] if i < n else "")


def git_call(words):
    i, name = command_word(words)
    n = len(words)
    if name != "git":
        return None
    i, cdirs = i + 1, []
    while i < n and words[i].startswith("-"):
        if words[i] == "-C" and i + 1 < n:
            cdirs.append(words[i + 1])
        i += 2 if words[i] in ("-C", "-c", "--git-dir", "--work-tree", "--namespace", "--config-env") else 1
    if i >= n:
        return None
    return words[i], words[i + 1:], cdirs


def toplevel(path):
    while True:
        dotgit = os.path.join(path, ".git")
        if os.path.exists(dotgit):
            return path, dotgit
        if os.path.dirname(path) == path:
            return None, None
        path = os.path.dirname(path)


def read(path):
    with open(path, encoding="utf-8") as handle:
        return handle.read().strip()


def common_dir(cwd):
    """The checkout `cwd` is in and the git directory every checkout of it shares, or Nones."""
    top, common = toplevel(os.path.realpath(cwd))
    if top is None:
        return None, None
    if os.path.isfile(common):
        common = os.path.join(top, read(common).partition("gitdir:")[2].strip())
        if os.path.isfile(os.path.join(common, "commondir")):
            common = os.path.join(common, read(os.path.join(common, "commondir")))
    return top, os.path.realpath(common)


def remotes(where):
    """The remotes the repository at `where` declares, read from its shared config as text."""
    _, common = common_dir(where)
    if common is None or not os.path.isfile(os.path.join(common, "config")):
        return set()
    return set(re.findall(r"(?m)^\s*\[remote\s+\"([^\"]+)\"\s*\]", read(os.path.join(common, "config"))))


def checkouts(cwd):
    """Every checkout of the repository `cwd` is in, read as text: git is never spawned."""
    top, common = common_dir(cwd)
    if top is None:
        return []
    found = {top}
    if os.path.basename(common) == ".git":
        found.add(os.path.dirname(common))
    linked = os.path.join(common, "worktrees")
    for name in os.listdir(linked) if os.path.isdir(linked) else ():
        if os.path.isfile(os.path.join(linked, name, "gitdir")):
            found.add(os.path.dirname(os.path.realpath(read(os.path.join(linked, name, "gitdir")))))
    return sorted(found)


def settings(words):
    """Every value a word sets as config, in each spelling git parses: `-c k=v`, `-ck=v`, a short
    bundle `-qc k=v`, `--config k=v`, `--config=k=v`, and `--config-env` in both forms. Any word
    is read, so a value that is not config can only take the exemption away, never grant it."""
    found = []
    for at, word in enumerate(words):
        after = words[at + 1] if at + 1 < len(words) else ""
        if word in ("--config", "--config-env"):
            found.append(after)
        elif word.startswith(("--config=", "--config-env=")):
            found.append(word.split("=", 1)[1])
        elif word.startswith("-") and not word.startswith("--") and "c" in word[1:]:
            found.append(word[word.index("c", 1) + 1:] or after)
    return found


def location_key(setting):
    """True when a `-c` setting names a location key; git config keys are case-insensitive."""
    key = setting.split("=", 1)[0].lower()
    return key in LOCATION_KEYS or key.startswith(LOCATION_SECTIONS)


def repo_roots(cwd, segs):
    """This repository: the hook\x27s own checkout, CLAUDE_PROJECT_DIR\x27s and cwd\x27s, each with
    every checkout it shares a repository with. None at all when the command redirects git
    (a GIT_* location, --git-dir, --work-tree, --namespace, a `-c` location key) or makes a
    link, so no `-C` is exempt."""
    for words in segs:
        if command_word(words)[1] == "ln" or any(w.startswith(REDIRECTS) for w in words) \
                or any(location_key(s) for s in settings(words)):
            return []
    anchors = [HOOK_DIR, os.environ.get("CLAUDE_PROJECT_DIR", ""), cwd]
    return sorted({r for a in anchors if a for r in checkouts(a)})


# The $HOME a `~` expands to: the hook\x27s own, or none when the command itself sets HOME.
HOME = [""]
REHOME = re.compile(r"^HOME\+?=|\{HOME:?=")


def rehomed(segs):
    """True when any word sets, exports or declares HOME (`HOME=`, `export HOME`, `env HOME=`)."""
    return any(w == "HOME" or REHOME.search(w) for words in segs for w in words)


def home(word):
    """`word` with a leading `~/` (or a bare `~`) read as $HOME, the way the shell expands it."""
    if (word == "~" or word.startswith("~/")) and HOME[0].startswith("/"):
        return HOME[0] + word[1:]
    return word


def outside(parts, roots):
    """True when every part is an absolute literal path and they land outside every root."""
    parts = [home(p) for p in parts]
    if not parts or not roots or not all(p.startswith("/") and not unknowable(p) for p in parts):
        return False
    target = os.path.realpath(os.path.join(*parts))
    return not any(target == r or target.startswith(r.rstrip(os.sep) + os.sep) for r in roots)


def split_args(args, long_values=(), short_values=""):
    opts, pos, letters, i = [], [], "", 0
    while i < len(args):
        arg = args[i]
        if arg == "--":
            pos.extend(args[i + 1:])
            break
        if arg.startswith("--"):
            opts.append(arg.split("=", 1)[0])
            if "=" not in arg and arg in long_values:
                i += 1
        elif arg.startswith("-") and len(arg) > 1:
            opts.append(arg)
            for at, letter in enumerate(arg[1:]):
                letters += letter
                if letter in short_values:
                    if at == len(arg) - 2:
                        i += 1
                    break
        else:
            pos.append(arg)
        i += 1
    return set(opts), pos, set(letters)


def variable_word(verb, pos):
    """An unquoted `$X` splits into options the verdict never read, and the typed
    text cannot tell `$X` from `"$X"`: a word this guard cannot read blocks,
    an option\x27s value included (`switch -c $N`, `push --repo=$R`)."""
    word = next((w for w in pos if unknowable(w)), None)
    if word is None:
        return None
    return ("`" + word + "` is a word this guard cannot read — it judges the typed text, and an unquoted variable can carry options into `git " + verb + "`",
            "type it literally — `git " + verb + " <name>`")


def unknowable(word):
    return "$" in word or OPAQUE in word


# Every verb judged on its options, and its long options spelled EXACTLY: git expands
# any unambiguous abbreviation (`--forc` is `--force`, `--del` is `--delete`), so a
# spelling in neither set is refused rather than guessed at. Each entry is (the options
# that pass, the options its judge refuses by name); `--autostash` is in no pass set,
# because an autostash sweeps every uncommitted edit, a peer\x27s included.
LONG = {
    "commit": ({"--all", "--patch", "--reuse-message", "--reedit-message", "--fixup", "--squash", "--reset-author",
                "--short", "--branch", "--porcelain", "--long", "--null", "--file", "--author", "--date", "--message",
                "--template", "--signoff", "--no-signoff", "--trailer", "--verify", "--no-verify", "--allow-empty",
                "--allow-empty-message", "--cleanup", "--edit", "--no-edit", "--no-post-rewrite", "--include",
                "--only", "--pathspec-from-file", "--pathspec-file-nul", "--untracked-files", "--verbose", "--quiet",
                "--dry-run", "--status", "--no-status", "--gpg-sign", "--no-gpg-sign"},
               {"--amend"}),
    "push": ({"--all", "--branches", "--prune", "--dry-run", "--porcelain", "--delete", "--tags", "--follow-tags",
              "--no-follow-tags", "--signed", "--no-signed", "--atomic", "--no-atomic", "--push-option",
              "--receive-pack", "--exec", "--repo", "--set-upstream", "--thin", "--no-thin", "--quiet", "--verbose",
              "--progress", "--no-progress", "--recurse-submodules", "--no-recurse-submodules", "--verify",
              "--no-verify", "--ipv4", "--ipv6", "--no-force-with-lease", "--force-if-includes",
              "--no-force-if-includes"},
             {"--force", "--force-with-lease", "--mirror"}),
    "merge": ({"--ff-only", "--ff", "--no-ff", "--squash", "--no-squash", "--abort", "--continue", "--quit",
               "--message", "--file", "--strategy", "--strategy-option", "--into-name", "--edit", "--no-edit",
               "--quiet", "--verbose", "--stat", "--no-stat", "--summary", "--no-summary", "--log", "--no-log",
               "--signoff", "--no-signoff", "--commit", "--no-commit", "--verify", "--no-verify", "--progress",
               "--no-progress", "--allow-unrelated-histories", "--cleanup", "--rerere-autoupdate",
               "--no-rerere-autoupdate", "--no-autostash", "--gpg-sign", "--no-gpg-sign"},
              {"--autostash"}),
    "pull": ({"--ff-only", "--no-rebase", "--quiet", "--verbose", "--prune", "--tags", "--no-tags", "--stat",
              "--no-stat", "--progress", "--no-progress", "--no-autostash", "--edit", "--no-edit"},
             {"--rebase", "--ff", "--no-ff", "--squash", "--autostash"}),
    "config": ({"--get", "--get-all", "--get-regexp", "--get-urlmatch", "--get-color", "--get-colorbool", "--list",
                "--show-origin", "--show-scope", "--name-only", "--null", "--type", "--bool", "--int",
                "--bool-or-int", "--path", "--expiry-date", "--default", "--global", "--system", "--local",
                "--worktree", "--file", "--blob", "--includes", "--no-includes", "--fixed-value", "--all",
                "--regexp", "--url", "--value", "--comment"},
               {"--add", "--unset", "--unset-all", "--replace-all", "--rename-section", "--remove-section", "--edit"}),
    "branch": ({"--list", "--all", "--remotes", "--show-current", "--verbose", "--quiet", "--abbrev", "--no-abbrev",
                "--column", "--no-column", "--sort", "--merged", "--no-merged", "--contains", "--no-contains",
                "--points-at", "--format", "--color", "--no-color", "--ignore-case", "--omit-empty", "--track",
                "--no-track", "--recurse-submodules", "--create-reflog", "--set-upstream-to", "--unset-upstream",
                "--edit-description", "--copy", "--delete"},
               {"--force", "--move"}),
    "tag": ({"--list", "--sort", "--format", "--contains", "--no-contains", "--merged", "--no-merged",
             "--points-at", "--column", "--no-column", "--ignore-case", "--omit-empty", "--color", "--annotate",
             "--sign", "--no-sign", "--local-user", "--message", "--file", "--edit", "--no-edit", "--cleanup",
             "--create-reflog", "--trailer", "--verify"},
            {"--delete", "--force"}),
    "worktree": ({"--porcelain", "--verbose", "--expire", "--dry-run"}, set()),
    "switch": ({"--create", "--quiet", "--track", "--no-track", "--guess", "--no-guess", "--progress",
                "--no-progress"},
               {"--discard-changes", "--force", "--force-create", "--orphan", "--merge", "--detach", "--conflict",
                "--ignore-other-worktrees", "--recurse-submodules", "--no-recurse-submodules",
                "--overwrite-ignore", "--no-overwrite-ignore"}),
    "symbolic-ref": ({"--quiet", "--short", "--no-short", "--recurse", "--no-recurse"}, {"--delete"}),
    "stash": ({"--date", "--oneline", "--format", "--pretty", "--abbrev-commit", "--no-abbrev-commit",
               "--relative-date", "--stat", "--patch", "--max-count", "--decorate", "--no-decorate", "--color",
               "--no-color"},
              set()),
    # `--separate-git-dir` is in neither: it points a new checkout at a git directory anywhere.
    "init": ({"--template", "--object-format", "--ref-format", "--initial-branch", "--bare", "--quiet", "--shared"},
             set()),
    "archive": ({"--format", "--prefix", "--list", "--verbose", "--worktree-attributes", "--add-file",
                 "--add-virtual-file", "--mtime", "--exec"},
                {"--output", "--remote"}),
}


def inexact(sub, opts):
    """The refusal for a long option on neither of `sub`\x27s lists, or None."""
    passes, judged = LONG[sub]
    odd = sorted(o for o in opts if o.startswith("--") and o not in passes and o not in judged)
    if not odd:
        return None
    return ("`" + odd[0] + "` is not an option this guard knows for `git " + sub + "`, spelled exactly — git expands an abbreviation (`--forc` is `--force`), so only an exact spelling can be judged",
            "spell the option in full; `git " + sub + "` passes with " + " ".join(sorted(passes)))


def commit(args):
    opts, _, _ = split_args(args, ("--message", "--file", "--reuse-message", "--reedit-message", "--author", "--date", "--template", "--cleanup", "--trailer", "--fixup", "--squash", "--pathspec-from-file"), "mFCct")
    return inexact("commit", opts) or (AMEND if "--amend" in opts else None)


def push(args):
    opts, pos, letters = split_args(args, ("--repo", "--push-option", "--receive-pack", "--exec"), "o")
    said = inexact("push", opts)
    if said:
        return said
    refspecs = pos[1:]
    said = variable_word("push", args)
    if said:
        return said
    if opts & {"--force", "--force-with-lease", "--mirror"} or "f" in letters or any(r.startswith("+") for r in refspecs):
        return FORCE
    for ref in refspecs:
        dst = ref.lstrip("+").rsplit(":", 1)[-1]
        if dst.startswith("refs/heads/"):
            dst = dst[len("refs/heads/"):]
        if unknowable(dst):
            return ("`" + ref + "` names a destination this guard cannot read — it judges the typed text, so a shell variable could name the mainline",
                    "type the destination branch literally — `git push origin <branch>`")
        if dst in PROTECTED:
            return ("`" + dst + "` is the mainline, which takes a merge commit through the PR at close and never a direct push",
                    "`git push -u origin <milestone-branch>`, then the PR")
    return None


def tracking(name, where):
    """True when `name` spells a remote-tracking ref of a remote the repository at `where` declares."""
    if name.startswith("refs/remotes/"):
        return name.count("/") >= 3
    remote, slash, rest = name.partition("/")
    return bool(slash and rest) and remote in remotes(where)


def merge(args, where):
    opts, pos, _ = split_args(args, ("--message", "--file", "--strategy", "--strategy-option", "--into-name"), "mFsX")
    said = inexact("merge", opts)
    if said:
        return said
    if "--autostash" in opts:
        return AUTOSTASH
    if opts & {"--abort", "--continue", "--quit"}:
        return None
    if not pos:
        return MERGE_NOTHING
    # A fast-forward cannot lose work, and a later `--ff` or `--no-ff` would override it.
    ff_only = "--ff-only" in opts and not opts & {"--ff", "--no-ff", "--squash"}
    for name in pos:
        bare = name[len("refs/heads/"):] if name.startswith("refs/heads/") else name
        if unknowable(bare):
            return ("`" + name + "` names a source this guard cannot read — it judges the typed text, so a shell variable could name any branch",
                    "type the branch name literally, one `git merge <branch>` per branch")
        if any(fnmatch.fnmatchcase(bare, glob) for glob in MERGEABLE):
            continue
        if ff_only and tracking(name, where):
            continue
        return ("`" + name + "` is not a branch this flow merges (MERGE_BRANCHES: " + " ".join(MERGEABLE) + ")",
                "merge the milestone branch or your own agent branch; a remote-tracking ref fast-forwards — `git merge --ff-only <remote>/<branch>`; anything else is the operator\x27s")
    return None


def pull(args):
    opts, pos, letters = split_args(args, ("--strategy", "--strategy-option", "--depth", "--deepen", "--shallow-since", "--shallow-exclude", "--upload-pack", "--negotiation-tip", "--server-option"), "sXo")
    said = inexact("pull", opts)
    if said:
        return said
    if "--ff-only" not in opts or opts & {"--rebase", "--ff", "--no-ff", "--squash", "--autostash"} \
            or "r" in letters or len(pos) > 2 or any(":" in p or p.startswith("+") for p in pos):
        return PULL
    return None


def config(args):
    opts, pos, letters = split_args(args, ("--file", "--blob", "--type", "--default", "--comment", "--value"), "f")
    said = inexact("config", opts)
    if said:
        return said
    verb = pos[0] if pos else ""
    if opts & {"--add", "--unset", "--unset-all", "--replace-all", "--rename-section", "--remove-section", "--edit"} \
            or "e" in letters or verb in ("set", "unset", "rename-section", "remove-section", "edit"):
        return CONFIG
    if opts & {"--get", "--get-all", "--get-regexp", "--get-urlmatch", "--get-color", "--get-colorbool", "--list"} \
            or "l" in letters or verb in ("get", "list"):
        return None
    return CONFIG if len(pos) > 1 else None


def branch(args):
    opts, pos, letters = split_args(args, ("--contains", "--no-contains", "--merged", "--no-merged", "--points-at", "--sort", "--format", "--set-upstream-to"), "u")
    said = inexact("branch", opts) or variable_word("branch", args)
    if said:
        return said
    if opts & {"--move", "--force"} or letters & set("DmMCf"):
        return BRANCH
    # `-d` is the safe delete: git refuses a branch whose work is merged nowhere.
    deleting = "--delete" in opts or "d" in letters
    return BRANCH if deleting and (opts & {"--remotes", "--all"} or letters & set("ra")) else None


def tag(args):
    opts, _, letters = split_args(args, ("--message", "--file", "--local-user", "--cleanup", "--sort", "--format", "--contains", "--no-contains", "--merged", "--no-merged", "--points-at"), "mFu")
    return inexact("tag", opts) or (TAG if opts & {"--delete", "--force"} or letters & set("df") else None)


def worktree(args):
    verb = next((a for a in args if not a.startswith("-")), "")
    if verb in ("", "list", "prune"):
        return inexact("worktree", split_args(args, ("--expire",))[0])
    return WORKTREE_ADD if verb == "add" else WORKTREE_OTHER


def remote(args):
    verb = next((a for a in args if not a.startswith("-")), "")
    return REMOTE if verb in ("add", "rename", "rm", "remove", "set-url", "set-branches") else None


def switch(args):
    # Only what never discards: a branch, or `-c <new> [<start>]`; any other option is refused.
    opts, pos, letters = split_args(args, ("--create",), "c")
    said = inexact("switch", opts) or variable_word("switch", args)
    if said:
        return said
    creating = "--create" in opts or "c" in letters
    if {o for o in opts if o.startswith("--")} - LONG["switch"][0] or letters - set("cqt") \
            or len(pos) > 1 or (not creating and len(pos) != 1):
        return SWITCH
    return None


def symbolic_ref(args):
    # One ref argument reads; a second writes it, and `-d` deletes it.
    opts, pos, letters = split_args(args, (), "m")
    return inexact("symbolic-ref", opts) or (SYMREF if len(pos) != 1 or "--delete" in opts or letters & set("dm") else None)


def stash(args):
    if args[:1] != ["list"]:
        return NAMED["stash"]
    return inexact("stash", split_args(args[1:], ("--date", "--format", "--pretty", "--max-count", "--color"))[0])


JUDGES = {"commit": commit, "push": push, "config": config, "pull": pull,
          "branch": branch, "tag": tag, "worktree": worktree, "remote": remote,
          "switch": switch, "symbolic-ref": symbolic_ref, "stash": stash}


def init_split(args):
    return split_args(args, ("--template", "--separate-git-dir", "--object-format", "--ref-format", "--initial-branch"), "b")


def init(args, cdirs, roots):
    opts, pos, _ = init_split(args)
    said = inexact("init", opts)
    if said:
        return said
    return None if outside(cdirs + pos[:1], roots) else INIT


# Every clone option this guard can parse, spelled exactly. Any other option, an abbreviation
# git would expand included, may take a value, so the positionals are unknown and the clone
# keeps the block. A location option points the new repository, or the command it runs, anywhere.
CLONE_VALUES = ("--branch", "--depth", "--reference", "--reference-if-able", "--origin", "--config",
                "--jobs", "--server-option", "--filter", "--shallow-since", "--shallow-exclude",
                "--bundle-uri", "--ref-format", "--separate-git-dir", "--template", "--upload-pack")
CLONE_FLAGS = {"--quiet", "--verbose", "--progress", "--no-progress", "--bare", "--mirror", "--local",
               "--no-local", "--no-hardlinks", "--shared", "--dissociate", "--no-checkout", "--recursive",
               "--recurse-submodules", "--remote-submodules", "--no-remote-submodules", "--single-branch",
               "--no-single-branch", "--no-tags", "--shallow-submodules", "--no-shallow-submodules",
               "--also-filter-submodules", "--reject-shallow", "--no-reject-shallow", "--sparse"}
CLONE_LOCATION = {"--separate-git-dir", "--template", "--upload-pack"}


def clone_split(args):
    return split_args(args, CLONE_VALUES, "bocuj")


def clone(args, cdirs, roots):
    """A clone is judged by where it writes: `-C` joined with the destination, or `-C` alone."""
    opts, pos, letters = clone_split(args)
    long_opts = {o for o in opts if o.startswith("--")}
    if long_opts - CLONE_FLAGS - set(CLONE_VALUES) or long_opts & CLONE_LOCATION or letters - set("qvlsnbocj"):
        return CLONE
    # The destination resolves against `-C` as git resolves it, so `-C /abs clone <url> rel` lands in /abs.
    where = cdirs + pos[1:]
    return None if len(pos) in (1, 2) and where and outside([os.path.join(*map(home, where))], roots) else CLONE


def archive(args):
    opts, _, letters = split_args(args, ("--output", "--remote", "--format", "--prefix", "--exec", "--add-file"), "o")
    return inexact("archive", opts) or (ARCHIVE if opts & {"--output", "--remote"} or "o" in letters else None)


def judge(sub, args, cdirs, roots, cwd):
    if unknowable(sub):
        return ("`" + sub + "` is a subcommand this guard cannot read — it judges the typed text, so a shell variable could name any verb",
                "type the subcommand literally — the flow is " + FLOW)
    if sub in ALLOW or "--help" in args:
        return None
    if sub == "init":
        return init(args, cdirs, roots)
    if sub == "clone":
        return clone(args, cdirs, roots)
    if outside(cdirs, roots):
        return None
    if sub == "archive":
        return archive(args)
    if sub == "merge":
        return merge(args, os.path.join(cwd, *map(home, cdirs)))
    if sub in JUDGES:
        return JUDGES[sub](args)
    if sub in NAMED:
        return NAMED[sub]
    return ("`git " + sub + "` is not on this project\x27s git allowlist", "the flow is " + FLOW)


def route(sub, args, cdirs, roots, cwd):
    """The cross-repository route, when a blocked command names another repository outside this
    checkout — a `-C` target, an init target or a clone destination, never a pathspec: the
    exemption exists, and the refusal is where the operator is standing (rule 11)."""
    spelled = "; for another repository, spell its absolute path: `git -C /abs/path " + sub + " …`"
    typed = next((c for c in cdirs if c.startswith("$")), None)
    if typed:
        return spelled + " — this hook reads the typed text, so `" + typed + "` is not expanded"
    target = []
    if sub == "init":
        target = init_split(args)[1][:1]
    elif sub == "clone":
        target = clone_split(args)[1][1:2]
    places = [cdirs + target] if cdirs else [target] if target else []
    return spelled if any(outside([os.path.join(cwd, *map(home, p))], roots) for p in places) else ""


def verdict(command, cwd):
    try:
        segs = list(segments(command))
        # A command that sets HOME expands `~` to a path this hook cannot know, so `~` is not read.
        HOME[0] = "" if rehomed(segs) else os.environ.get("HOME", "")
        roots = repo_roots(cwd, segs)
        for words in segs:
            found = git_call(words)
            said = judge(*found, roots, cwd) if found else None
            if said:
                return "\n".join([
                    "BLOCKED (git allowlist): `git " + found[0] + "` — " + said[0] + ".",
                    "  offending segment: " + " ".join(words),
                    "  instead: " + said[1] + route(*found, roots, cwd) + ".",
                    "",
                    "  This list is the project\x27s own: ALLOW_SUBCOMMANDS, PROTECTED_BRANCHES and",
                    "  MERGE_BRANCHES in the project-config header of tools/hooks/cc-git-allowlist.sh.",
                    "  Widening it is the operator\x27s edit, in a commit — never a workaround for one call.",
                ])
    except Exception:
        pass
    return ""


def payload():
    try:
        event = json.loads(sys.stdin.buffer.read().decode("utf-8", "replace"))
        tool_input = event.get("tool_input") if event.get("tool_name") == "Bash" else None
        command = tool_input.get("command") if isinstance(tool_input, dict) else None
        cwd = event.get("cwd") if isinstance(event.get("cwd"), str) else os.getcwd()
    except Exception:
        return ""
    return verdict(command, cwd) if isinstance(command, str) else ""


def corpus():
    counts, missed = {"2": 0, "0": 0}, 0
    for row in sys.stdin.buffer.read().decode("utf-8").splitlines():
        want, _, command = row.strip().partition(" ")
        if not want or want.startswith("#"):
            continue
        got = "2" if verdict(command, os.getcwd()) else "0"
        if got == want:
            counts[got] += 1
        else:
            missed += 1
            sys.stderr.write("  MISS — " + command + ": wanted exit " + want + ", got " + got + "\n")
    sys.stdout.write(str(counts["2"]) + " " + str(counts["0"]) + "\n")
    return 1 if missed else 0


if sys.argv[5:] == ["--corpus"]:
    sys.exit(corpus())
sys.stdout.buffer.write(payload().encode("utf-8"))
'

# This hook's own directory, without a fork: its checkout is "this repository" wherever cwd is.
case "$0" in
	/*) HOOK_DIR="${0%/*}" ;;
	*/*) HOOK_DIR="$PWD/${0%/*}" ;;
	*) HOOK_DIR="$PWD" ;;
esac

if [ "${1:-}" = "--self-test" ]; then
	# Through `||`, so the fail-open ERR trap cannot turn a self-test failure into exit 0.
	self_test_rc=0
	self_test || self_test_rc=$?
	exit "$self_test_rc"
fi
if [ "${1:-}" = "--self-test-replay" ]; then
	# The corpus table on stdin, judged at THIS file's values; self_test runs it on the stock copy.
	replay_rc=0
	python3 -c "$ANALYZER" "$ALLOW_SUBCOMMANDS" "$PROTECTED_BRANCHES" "$MERGE_BRANCHES" "$HOOK_DIR" --corpus || replay_rc=$?
	exit "$replay_rc"
fi

# --- the hook -----------------------------------------------------------------
INPUT="$(cat)"

# Fast path: pure shell, no fork, for every call that cannot name git.
case "$INPUT" in
	*git*) ;;
	*) exit 0 ;;
esac

# Without python3 the guard yields rather than guess with regexes.
command -v python3 >/dev/null 2>&1 || exit 0
VERDICT="$(printf '%s' "$INPUT" | python3 -c "$ANALYZER" \
	"$ALLOW_SUBCOMMANDS" "$PROTECTED_BRANCHES" "$MERGE_BRANCHES" "$HOOK_DIR" 2>/dev/null || true)"
[ -n "$VERDICT" ] || exit 0   # allowed, not a Bash call, or unparseable → fail open

printf '%s\n' "$VERDICT" >&2
exit 2
