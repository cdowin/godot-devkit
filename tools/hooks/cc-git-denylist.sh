#!/usr/bin/env bash
# cc-git-denylist.sh — Claude Code PreToolUse Bash hook: refuse only the git
# that cannot be undone or that harms another tree. Refused: a force push
# (--force, -f, --force-with-lease, --mirror, a +refspec); a push whose
# destination is a PROTECTED_BRANCHES branch; reset --hard; clean -f / -x
# (bar a dry run); a whole-tree discard (`checkout .`, `checkout -- .`,
# `restore .`); and stash bar list/show/apply/create, because every worktree
# shares one stash. Everything else passes. Each `;` `&&` `|` `$(...)` part,
# `git -C <dir>`, `bash -c '...'` and `eval` is read. A push with no refspec
# is pre-push's to judge. `bash cc-git-denylist.sh --self-test` replays the
# corpus. Stdin: the PreToolUse JSON. Exit 0 = allow, 2 = block; failures exit 0.
set -u
trap 'exit 0' ERR

# --- project config (yours to edit after install — the file is your repo's) --
# Branches (exact, space-separated) no `git push` may name as its destination.
PROTECTED_BRANCHES="main master"
# -----------------------------------------------------------------------------

# A header carried from an older install may lack a key: it runs at its stock value.
declare -p PROTECTED_BRANCHES >/dev/null 2>&1 || PROTECTED_BRANCHES="main master"

read -r -d '' JUDGE <<'PY' || true
import json, os, re, shlex, sys
PROTECTED = os.environ.get('PROTECTED_BRANCHES', '').split()
GLOBAL_ARG = ('-C', '-c', '--git-dir', '--work-tree', '--namespace', '--config-env')
PUSH_ARG = ('-o', '--push-option', '--repo', '--receive-pack', '--exec')
HEREDOC = re.compile(r"(?<!<)<<-?(?!<)\s*['\"]?([A-Za-z_][A-Za-z0-9_]*)")
FORCE = 'a force push rewrites history others may hold; push a new commit instead'

def segments(text):  # heredoc bodies dropped; split on ; & | ( ) ` and newline
    lines, end = [], None
    for line in text.split('\n'):
        if end is None:
            lines.append(line)
            end = (HEREDOC.search(line) or [None, None])[1]
        elif line.strip() == end:
            end = None
    lex = shlex.shlex('\n'.join(lines).replace('`', ' ; '), posix=True, punctuation_chars=';&|()<>\n')
    lex.whitespace, lex.whitespace_split, lex.commenters = ' \t\r', True, ''
    seg, drop, skip = [], False, False
    for w in list(lex) + [';']:
        if w and set(w) <= set(';&|()\n'):
            if seg:
                yield seg
            seg, drop, skip = [], False, False
        elif drop or skip or w.startswith('#'):
            drop, skip = drop or w.startswith('#'), False
        elif w and set(w) <= set('<>&'):  # a redirect: drop its fd and its target
            seg, skip = seg[:-1] if seg and seg[-1].isdigit() else seg, True
        else:
            seg.append(w)

def git(args):
    i = 0
    while i < len(args) and args[i].startswith('-'):
        i += 2 if args[i] in GLOBAL_ARG else 1
    sub, rest = (args[i], args[i + 1:]) if i < len(args) else ('', [])
    opts = rest[:rest.index('--')] if '--' in rest else rest
    longs = [o[2:].split('=')[0] for o in opts if o.startswith('--') and len(o) > 3]
    shorts = ''.join(o[1:] for o in opts if o.startswith('-') and not o.startswith('--'))
    has = lambda full, letter='': bool(letter and letter in shorts) or any(full.startswith(n) for n in longs)
    if sub == 'push':
        if has('force', 'f') or has('force-with-lease') or has('mirror'):
            return FORCE
        pos = [w for k, w in enumerate(rest) if not w.startswith('-') and (k == 0 or rest[k - 1] not in PUSH_ARG)]
        for spec in pos[1:]:
            dst = re.sub(r'^refs/heads/', '', spec.split(':')[-1])
            if spec.startswith('+') or dst in PROTECTED:
                return FORCE if spec.startswith('+') else f'{dst} is a protected branch; push your feat/ branch and let the lead merge it'
    if sub == 'reset' and has('hard'):
        return 'reset --hard discards uncommitted work; commit it, or restore one named path'
    if sub == 'clean' and not has('dry-run', 'n') and (has('force', 'f') or 'x' in shorts.lower()):
        return 'clean -f deletes untracked files for good; rm the paths you mean'
    if sub in ('checkout', 'restore'):
        paths = rest[rest.index('--') + 1:] if '--' in rest else [w for w in rest if not w.startswith('-')]
        staged = sub == 'restore' and has('staged', 'S') and not has('worktree', 'W')
        if not staged and set(paths) & {'.', './', ':/', ':/.', '*', ':(top)'}:
            return 'a whole-tree discard drops every uncommitted change; name the paths'
    if sub == 'stash' and (rest[0] if rest and not rest[0].startswith('-') else 'push') not in ('list', 'show', 'apply', 'create'):
        return 'every worktree shares one stash; commit on your branch instead (stash list/show/apply pass)'

def judge(text, depth=0):
    for seg in segments(text):
        shell = [k for k, w in enumerate(seg) if os.path.basename(w) in ('bash', 'sh', 'zsh', 'dash', 'ksh')]
        inner = [seg[k + 1] for k in range(shell[0] + 1 if shell else len(seg), len(seg) - 1)
                 if re.fullmatch(r'-[a-z]*c[a-z]*', seg[k])][:1] + ([' '.join(seg[1:])] if seg[0] == 'eval' else [])
        gits = [k for k, w in enumerate(seg) if os.path.basename(w) == 'git'][:1]
        for said in [judge(t, depth + 1) for t in inner if depth < 3] + [git(seg[k + 1:]) for k in gits]:
            if said:
                return said

if sys.argv[1:] == ['--self-test']:
    rows = [r.replace('\\n', '\n') for line in sys.stdin.read().splitlines() for r in line.split(' ;; ') if r.strip()]
    bad = [f'  wanted {r[0]}: {r[2:]}' for r in rows if (judge(r[2:]) is not None) != (r[0] == 'B')]
    print('\n'.join(bad) or f'{len(rows)} case(s)')
    sys.exit(1 if bad else 0)
data = json.load(sys.stdin)
if data.get('tool_name') == 'Bash':
    print(judge(str((data.get('tool_input') or {}).get('command') or '')) or '')
PY

if [ "${1:-}" = "--self-test" ]; then
	trap - ERR
	# Rows are `B|A <command>`, ` ;; `-separated; `\n` is a newline. Stock header values.
	out="$(PROTECTED_BRANCHES="main master" python3 -c "$JUDGE" --self-test <<'ROWS'
B git push --force origin feat/x ;; B git push -f ;; B git push --force-with-lease origin feat/x
B git push origin +feat/x ;; B git push --mirror origin ;; B git push origin main
B git push origin HEAD:refs/heads/master ;; B cd /tmp/x && git -C repo reset --hard origin/feat/x
B git status; git clean -fd ;; B git clean -x -f ;; B git checkout -- . ;; B git checkout .
B git restore . ;; B git stash ;; B git stash push -m wip ;; B git stash save wip ;; B git stash -u
B bash -c 'cd x && git stash' ;; B echo $(git reset --hard) ;; B eval "git stash pop"
B git commit -F - <<'EOF'\nmsg\nEOF\ngit stash ;; B git log # note\ngit stash drop
A git push origin feat/x ;; A git push -u origin feat/x:feat/x ;; A git push origin main:feat/copy
A git reset --soft HEAD~1 ;; A git clean -n -fd ;; A git checkout -- src/a.py ;; A git checkout feat/x
A git restore --staged . ;; A git stash list ;; A git stash show -p stash@{0}
A git worktree add ../x -b feat/x ;; A git worktree remove x ;; A git worktree prune
A git branch -D y ;; A git switch feat/x ;; A git merge feat/x ;; A git bundle create a b
A git commit -m "never git reset --hard" ;; A git commit -F - <<'EOF'\ndo not git stash\nEOF\ngit status
A git push origin feat/x 2>&1 | tail -3 ;; A echo done
ROWS
)" || { printf '[cc-git-denylist.sh] SELF-TEST FAIL\n%s\n' "$out" >&2; exit 1; }
	printf '{"tool_name":"Bash","tool_input":{"command":"git reset --hard"}}' | bash "$0" 2>/dev/null
	[ $? = 2 ] || { echo "[cc-git-denylist.sh] SELF-TEST FAIL — a payload did not block" >&2; exit 1; }
	printf 'not json {{{' | bash "$0" || { echo "[cc-git-denylist.sh] SELF-TEST FAIL — garbage did not fail open" >&2; exit 1; }
	echo "[cc-git-denylist.sh] SELF-TEST OK — $out"
	exit 0
fi

INPUT="$(cat)"
case "$INPUT" in *git*) ;; *) exit 0 ;; esac
command -v python3 >/dev/null 2>&1 || exit 0
VERDICT="$(printf '%s' "$INPUT" | PROTECTED_BRANCHES="$PROTECTED_BRANCHES" python3 -c "$JUDGE" 2>/dev/null || true)"
[ -n "$VERDICT" ] || exit 0
printf 'BLOCKED (cc-git-denylist): %s\n' "$VERDICT" >&2
exit 2
