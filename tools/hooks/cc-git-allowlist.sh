#!/usr/bin/env bash
# cc-git-allowlist.sh — Claude Code PreToolUse Bash hook: the git an agent
# session may run is an ALLOWLIST, because the flow is `git add <paths>`,
# `git commit -m … -- <paths>`, `git push` and the milestone merge, and every
# other verb is a chance to move HEAD, sweep a peer's edits or rewrite what was
# pushed. Allowed: ALLOW_SUBCOMMANDS below with any arguments; `commit` bar
# `--amend` (cc-commit-pathspec.sh judges its paths); `push` bar a force or a
# PROTECTED_BRANCHES destination; `merge` of a MERGE_BRANCHES branch; `config`
# reads; `branch` and `tag` bar delete/move/force; `worktree list|prune`;
# `remote` bar rewiring. Blocked, each with its reason and the boring
# alternative: bisect, stash, reset, checkout, switch, restore, clean, rebase,
# pull, and any subcommand named nowhere here. Only the command the agent TYPES
# is read: git run inside a script or a make target — tools/dev/agent-worktree.sh's
# own `worktree add` — is never seen. `bash cc-git-allowlist.sh --self-test`
# replays the command corpus. Stdin: the PreToolUse JSON (tool_name,
# tool_input.command). Exit 0 = allow, 2 = block; failures exit 0.
set -eu
trap 'exit 0' ERR

# --- project config (yours to edit after install — the file is your repo's) --
# git subcommands allowed with ANY arguments, space-separated. One named here
# skips every judgement below, the named blocks included: widening the list is
# this line, edited in a commit, never a workaround for one call.
ALLOW_SUBCOMMANDS="add status diff log show rev-parse rev-list merge-base ls-files ls-tree ls-remote cat-file grep blame describe shortlog show-ref for-each-ref name-rev range-diff fetch mv rm help version"
# Branches (exact, space-separated) no `git push` may name as its destination.
# Keep in step with pre-push's PROTECTED_BRANCHES, which backstops the rest.
PROTECTED_BRANCHES="main"
# Branch globs (space-separated) a `git merge` may name: the milestone branch,
# and the agent branches tools/dev/agent-worktree.sh cuts (its BRANCH_PREFIX).
MERGE_BRANCHES="milestone/* feat/*"
# -----------------------------------------------------------------------------

# A header carried from an older install may lack a key: it runs at its stock value.
declare -p ALLOW_SUBCOMMANDS >/dev/null 2>&1 || ALLOW_SUBCOMMANDS="add status diff log show rev-parse rev-list merge-base ls-files ls-tree ls-remote cat-file grep blame describe shortlog show-ref for-each-ref name-rev range-diff fetch mv rm help version"
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
	local s="$2"
	s="${s//\\/\\\\}"
	s="${s//\"/\\\"}"
	s="${s//$'\t'/\\t}"
	s="${s//$'\n'/\\n}"
	printf '{"tool_name":"%s","tool_input":{"command":"%s"},"cwd":"/"}' "$1" "$s"
}

# case <hook> <want exit> <tool> <command> — a block must also name its alternative.
self_test_case() {
	local hook="$1" want="$2" tool="$3" line="$4" out rc=0 miss=""
	out="$(self_test_payload "$tool" "$line" | bash "$hook" 2>&1)" || rc=$?
	if [ "$rc" != "$want" ]; then
		miss="wanted exit $want, got $rc"
	elif [ "$want" = 2 ]; then
		case "$out" in
			*"instead: "*) ;;
			*) miss="blocked with no alternative named" ;;
		esac
	fi
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
	stock="$tmp/stock.sh"
	widened="$tmp/widened.sh"
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
2 git switch -c feat/x
2 git restore src/x.py
2 git clean -fdx
2 git rebase milestone/0.9.0
2 git pull
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
2 git tag -f v1.0.0
2 git merge main
2 git merge
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
0 git merge "$BRANCH"
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
0 git tag v0.9.0 && git push origin refs/tags/v0.9.0
0 git tag -l
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
0 make check
0 make pm ARGS='story building st-x'
0 echo git stash
0 grep -n "git reset --hard" SDLC.md
CORPUS
	counts="$(bash "$stock" --self-test-replay <"$tmp/corpus")" || rc=1
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
# cannot know (`$BRANCH`) is never guessed at: it ALLOWS. Prints the block
# message, or nothing; every exception is nothing.
# argv: ALLOW_SUBCOMMANDS PROTECTED_BRANCHES MERGE_BRANCHES [--corpus]
# shellcheck disable=SC2016  # the python source stays literal
ANALYZER='
import fnmatch, json, re, sys

ALLOW = set(sys.argv[1].split())
PROTECTED = set(sys.argv[2].split())
MERGEABLE = sys.argv[3].split()
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
              "to watch a test fail at HEAD, copy the file to a scratch path; the pathspec form is still a stash"),
    "reset": ("moves HEAD or rewrites the index and tree under every agent in this checkout, and a pushed branch is forward-only",
              "fix forward with a new commit that names its paths — `git commit -m \"…\" -- <path>`; a stray staged file is harmless when every commit names its paths"),
    "checkout": ("rewrites the working tree: a path form discards uncommitted edits, a peer\x27s included, and a branch form switches the branch under every agent in this checkout",
                 "read a committed file with `git show HEAD:<path>`; another branch is a tree of your own — `" + TOOL + " new <slug>`"),
    "switch": ("switches the branch under every agent sharing this checkout",
               "another branch is a tree of your own — `" + TOOL + " new <slug>`"),
    "restore": ("discards uncommitted edits, a peer\x27s included, or unstages what a peer staged",
                "read a committed file with `git show HEAD:<path>`; to watch a test fail at HEAD, copy the file to a scratch path"),
    "clean": ("deletes untracked files, a peer\x27s new files included",
              "`rm` the one path you created"),
    "rebase": ("rewrites history, and nothing pushed is rebased",
               "take upstream work with a merge — `git merge <milestone-branch>`"),
    "pull": ("fetches and then merges or rebases whatever the upstream config says, in one step you did not choose",
             "`git fetch`, then `git merge <milestone-branch>`"),
}
AMEND = ("rewrites the commit HEAD names, and a pushed branch is forward-only",
         "a new commit that names its paths — `git commit -m \"…\" -- <path>`")
FORCE = ("rewrites the remote branch — nothing pushed is amended, rebased, reset or force-pushed",
         "push a new commit on top; a rejected push is `git fetch` and `git merge <branch>`, then push again")
CONFIG = ("writes configuration that every worktree of this repository shares — a stray `core.bare = true` is one such write",
          "`git -c <key>=<value> <command>` scopes a setting to one command; a standing change is the operator\x27s")
BRANCH = ("deletes, renames or force-moves a branch, and agent branches are made and retired by the worktree tool",
          "`" + TOOL + " done <slug>` retires one and keeps unmerged work; `git branch -a` lists")
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


def git_call(words):
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
    if i >= n or words[i].rsplit("/", 1)[-1] != "git":
        return None
    i += 1
    while i < n and words[i].startswith("-"):
        i += 2 if words[i] in ("-C", "-c", "--git-dir", "--work-tree", "--namespace", "--config-env") else 1
    if i >= n:
        return None
    return words[i], words[i + 1:]


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


def unknowable(word):
    return "$" in word or OPAQUE in word


def commit(args):
    opts, _, _ = split_args(args, ("--message", "--file", "--reuse-message", "--reedit-message", "--author", "--date", "--template", "--cleanup", "--trailer", "--fixup", "--squash", "--pathspec-from-file"), "mFCct")
    return AMEND if "--amend" in opts else None


def push(args):
    opts, pos, letters = split_args(args, ("--repo", "--push-option", "--receive-pack", "--exec"), "o")
    refspecs = pos[1:]
    if opts & {"--force", "--force-with-lease", "--mirror"} or "f" in letters or any(r.startswith("+") for r in refspecs):
        return FORCE
    for ref in refspecs:
        dst = ref.lstrip("+").rsplit(":", 1)[-1]
        if dst.startswith("refs/heads/"):
            dst = dst[len("refs/heads/"):]
        if dst in PROTECTED:
            return ("`" + dst + "` is the mainline, which takes a merge commit through the PR at close and never a direct push",
                    "`git push -u origin <milestone-branch>`, then the PR")
    return None


def merge(args):
    opts, pos, _ = split_args(args, ("--message", "--file", "--strategy", "--strategy-option", "--into-name"), "mFsX")
    if opts & {"--abort", "--continue", "--quit"}:
        return None
    if not pos:
        return MERGE_NOTHING
    for name in pos:
        bare = name[len("refs/heads/"):] if name.startswith("refs/heads/") else name
        if unknowable(bare) or any(fnmatch.fnmatchcase(bare, glob) for glob in MERGEABLE):
            continue
        return ("`" + name + "` is not a branch this flow merges (MERGE_BRANCHES: " + " ".join(MERGEABLE) + ")",
                "merge the milestone branch or your own agent branch; anything else is the operator\x27s")
    return None


def config(args):
    opts, pos, letters = split_args(args, ("--file", "--blob", "--type", "--default", "--comment", "--value"), "f")
    verb = pos[0] if pos else ""
    if opts & {"--add", "--unset", "--unset-all", "--replace-all", "--rename-section", "--remove-section", "--edit"} \
            or "e" in letters or verb in ("set", "unset", "rename-section", "remove-section", "edit"):
        return CONFIG
    if opts & {"--get", "--get-all", "--get-regexp", "--get-urlmatch", "--get-color", "--get-colorbool", "--list"} \
            or "l" in letters or verb in ("get", "list"):
        return None
    return CONFIG if len(pos) > 1 else None


def branch(args):
    opts, _, letters = split_args(args, ("--contains", "--no-contains", "--merged", "--no-merged", "--points-at", "--sort", "--format", "--set-upstream-to"), "u")
    return BRANCH if opts & {"--delete", "--move", "--force"} or letters & set("dDmMCf") else None


def tag(args):
    opts, _, letters = split_args(args, ("--message", "--file", "--local-user", "--cleanup", "--sort", "--format", "--contains", "--no-contains", "--merged", "--no-merged", "--points-at"), "mFu")
    return TAG if opts & {"--delete", "--force"} or letters & set("df") else None


def worktree(args):
    verb = next((a for a in args if not a.startswith("-")), "")
    if verb in ("", "list", "prune"):
        return None
    return WORKTREE_ADD if verb == "add" else WORKTREE_OTHER


def remote(args):
    verb = next((a for a in args if not a.startswith("-")), "")
    return REMOTE if verb in ("add", "rename", "rm", "remove", "set-url", "set-branches") else None


JUDGES = {"commit": commit, "push": push, "merge": merge, "config": config,
          "branch": branch, "tag": tag, "worktree": worktree, "remote": remote}


def judge(sub, args):
    if unknowable(sub) or sub in ALLOW or "--help" in args:
        return None
    if sub in JUDGES:
        return JUDGES[sub](args)
    if sub in NAMED:
        return NAMED[sub]
    return ("`git " + sub + "` is not on this project\x27s git allowlist", "the flow is " + FLOW)


def verdict(command):
    try:
        for words in segments(command):
            found = git_call(words)
            said = judge(*found) if found else None
            if said:
                return "\n".join([
                    "BLOCKED (git allowlist): `git " + found[0] + "` — " + said[0] + ".",
                    "  offending segment: " + " ".join(words),
                    "  instead: " + said[1] + ".",
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
    except Exception:
        return ""
    return verdict(command) if isinstance(command, str) else ""


def corpus():
    counts, missed = {"2": 0, "0": 0}, 0
    for row in sys.stdin.buffer.read().decode("utf-8").splitlines():
        want, _, command = row.strip().partition(" ")
        if not want or want.startswith("#"):
            continue
        got = "2" if verdict(command) else "0"
        if got == want:
            counts[got] += 1
        else:
            missed += 1
            sys.stderr.write("  MISS — " + command + ": wanted exit " + want + ", got " + got + "\n")
    sys.stdout.write(str(counts["2"]) + " " + str(counts["0"]) + "\n")
    return 1 if missed else 0


if sys.argv[4:] == ["--corpus"]:
    sys.exit(corpus())
sys.stdout.buffer.write(payload().encode("utf-8"))
'

if [ "${1:-}" = "--self-test" ]; then
	# Through `||`, so the fail-open ERR trap cannot turn a self-test failure into exit 0.
	self_test_rc=0
	self_test || self_test_rc=$?
	exit "$self_test_rc"
fi
if [ "${1:-}" = "--self-test-replay" ]; then
	# The corpus table on stdin, judged at THIS file's values; self_test runs it on the stock copy.
	replay_rc=0
	python3 -c "$ANALYZER" "$ALLOW_SUBCOMMANDS" "$PROTECTED_BRANCHES" "$MERGE_BRANCHES" --corpus || replay_rc=$?
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
	"$ALLOW_SUBCOMMANDS" "$PROTECTED_BRANCHES" "$MERGE_BRANCHES" 2>/dev/null || true)"
[ -n "$VERDICT" ] || exit 0   # allowed, not a Bash call, or unparseable → fail open

printf '%s\n' "$VERDICT" >&2
exit 2
