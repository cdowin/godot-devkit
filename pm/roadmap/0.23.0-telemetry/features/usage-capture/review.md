# Feature Review — 0.23.0/usage-capture

**Commit range:** `236af3f..HEAD` (`dffa207`, `f44c0df`, and the
`pm(0.23.0/usage-capture)` closes), plus the uncommitted working tree at review time.
**Reviewer:** independent, cold. Adversarial input, run — no diff-reading (SDLC § 5).

## What I ran

- **`shellcheck -x`** on both couriers: **exit 0, zero findings**, before and after
  my fix.
- **Both `--self-test` corpora:** `SELF-TEST OK` on each, before and after. After the
  fix each carries one case more (the silent vehicle, U1).
- **Real payloads through the real hook**, into a scratch consumer tree with a real
  `make pm` vehicle, six cases, ledger row count compared before and after each:

  | payload | exit | rows | said |
  | --- | --- | --- | --- |
  | a good transcript | 0 | +1 | `[pm] ledger dispatch row appended to …` |
  | a path containing a space | 0 | +1 | same — `printf %q` + the `$`→`$$` escape hold |
  | a symlink to the transcript | 0 | +1 | same |
  | `agent_transcript_path` = a DIRECTORY | 0 | +0 | `[pm] ERROR — … is not a file`, then `make -s pm exited 2` |
  | a path that does not exist | 0 | +0 | the same refusal, passed through verbatim |
  | `cwd` inside another repo's worktree | 0 | +0 | finding U1 (see below) |

  Every path out is exit 0, as the story requires, and no case invented a row.
- **`~` expansion:** the self-test's `~/t.jsonl` case proves the hook expands it and
  the shell does not, end to end through `make`.
- **D3's tree snapshot, live:** a dispatch recorded with one story `wip` and one
  feature `building` carries exactly those ids; `zz_archive/` is excluded (mutation
  proved: including it FAILS the suite); a grain with no `id:` is left out; empty
  buckets are recorded as `[]`, not dropped.
- **Row shape vs `feature.md`, key for key:** `dispatch` and `session` rows minted
  through the hook and through `--event Stop` and compared against the documented
  examples — **doc-only: none, emitted-only: none**, both kinds.
- **Duplication census:** `cc-ledger-subagent.sh` 319 lines / 159 code lines,
  `cc-ledger-session.sh` 325 / 155, **42 differing code lines** — about 130 lines
  identical verbatim. Finding U3.
- **`install-hooks` roster:** both couriers are in `install.py:110-127` and reach
  `tools/hooks/`; `test_install.py` covers registration (`async: true`, unmatched
  matcher), the exec bit, and replaying their corpora from the installed copy.
  `test_install.py` **50 passed**; `test_hooks_payloads.py` **110 passed**.
- **Gate mutation:** 30 mutants across the milestone, **30/30 caught** (enumerated in
  the `ledger` record). None of my mutants survived, including the ones aimed at this
  feature's consumer — `record` picking the first of two building milestones, the
  snapshot including `zz_archive/`, `--from-transcript` accepting a directory.
- **Suite:** 1371 passed / 1 skipped / 3737 subtests before; 1397 / 1 / 3737 after.
  +4 are mine (in `test_pm_ledger_record.py`); +22 are a live peer's report tests.

## Fixed in place (uncommitted — no hash to cite; see the verdict-block note)

**U1 (MAJOR) — the couriers cannot tell "the verb wrote a row" from "the vehicle did
nothing", and counted the second as success.**
`src/godot_devkit/repo/installables/cc-ledger-subagent.sh` and
`cc-ledger-session.sh`, the final `"${MAKE_PM[@]}" ARGS=…` block.

`make -s pm` exits **0 and prints nothing** when the `pm` target is absent, or
present but not `.PHONY:`, in a repo that has a `pm/` DIRECTORY — which is every
repo this hook is for, because a PM tree *is* a `pm/` directory, so make finds a file
by that name and calls the target up to date. The old code took `verb_rc == 0` as
success and said nothing.

Reproduced against this very repo, whose root `Makefile` has no `pm` target:

```text
$ cd /Users/cdowin/workspace/godot-devkit-0.23.0
$ make -s pm ARGS="ledger record --grain x"; echo "exit=$?"
exit=0
$ make pm            # without -s, to see what make thinks
make: Nothing to be done for `pm'.
$ cd /tmp/mk1 && printf 'all:\n\t@true\n' > Makefile
$ make -s pm; echo $?          # no pm/ directory
make: *** No rule to make target `pm'.  Stop.
2
$ mkdir pm && make -s pm; echo $?   # with a pm/ directory
0
```

Firing the unfixed hook with `cwd` = this repo produced **exit 0, no row, and not one
word on stderr**. That is hard rule 4's read-side shape with a hook around it: the
measurement records nothing and reports success, and afterwards a milestone that was
never captured is indistinguishable from a cheap one. The header comment at
`cc-ledger-subagent.sh:52-55` warns about exactly this ("the vehicle exits 0, prints
nothing, and no row is ever written") — and a warning in a comment has never caught
anything.

**The fix** (`cc-ledger-subagent.sh:341-349`, `cc-ledger-session.sh:347-355`):
capture the vehicle's combined output, pass it through verbatim as before, and when
it exits 0 having said **nothing at all**, say so:

```text
[cc-ledger-subagent] make -s pm exited 0 without a word — the vehicle never
reached the verb (is the `pm` target present, and .PHONY?) — no ledger row
```

Nothing parses the output — the test is "did it speak", not "what did it say" — so
this adds no coupling to the verb's line shapes. The verb always speaks:
`[pm] ledger … row appended` on success, `[pm] ERROR — …` on a refusal. Silence is
neither, and it is now named. Every path is still exit 0.

**The test:** a new `--self-test` case in each hook
(`cc-ledger-subagent.sh:227-235`, `cc-ledger-session.sh:241-249`) — a Makefile with
no `pm` target beside a `pm/` directory, asserting the hook says `without a word`.
**Watched failing on the unfixed code**:

```text
  MISS — a vehicle that exits 0 without reaching the verb
    wanted: without a word
    got:  | exit=0
[cc-ledger-subagent] SELF-TEST FAIL — see the case(s) above
```

and passing on the fix. `shellcheck -x` still exit 0; `test_hooks_payloads.py` and
`test_install.py` still green (160 tests).

## Findings

### MAJOR

**U2 — this repo cannot run its own couriers, so the milestone measuring this repo's
dispatch cost cannot measure itself.** `Makefile` (root) has no `pm` target.

CLAUDE.md § Self-hosting says `install-hooks` is deliberately not self-hosted
*"because this package has no Godot tree and no shared-agent worktree, so a raw-
engine-boot guard here would guard nothing."* That reasoning is sound and it does
**not** extend to these two. Their subject exists here: this repo has a real PM tree
scaffolded by `pm new`, runs the milestone-branch SDLC, and dispatches subagents —
it is the first hook installable whose thing-to-guard is present. The milestone's own
ship criterion is *"a milestone worked with the hooks armed and no hand entry"*, and
the milestone being worked is this one, in this tree.

Answering the brief's self-hosting question directly: **yes, the two couriers should
be self-hosted here, and they cannot be until the root `Makefile` gains a `.PHONY:`'d
`pm` target.** That target is the prerequisite, not an optional convenience — every
consumer-facing instruction the couriers carry routes through `make pm ARGS=…`, and
this repo tells its consumers to use a vehicle it does not have. Arming them also
needs `tools/hooks/` and a `.claude/settings.json` entry, which changes this session's
own agent runtime mid-milestone; that is the orchestrator's call and the reason I
raised it rather than doing it.

Note that U1's fix makes the failure loud here today: fire either courier with `cwd`
inside this repo and it now says the vehicle never reached the verb. Before the fix
it said nothing, which is how a missing `pm` target survived this long.

### SUGGESTION

**U3 — the two couriers are one file written twice.** 159 and 155 code lines, **42
differing** (`diff` over both files with comments and blanks stripped). The whole
difference is three constants (`HOOK_NAME`, `EVENT`, `TRANSCRIPT_KEY`), the key list
handed to `read_event`, two `if [ -n … ]` blocks for the agent flags, and the
self-test's payload arity. Everything else — `expand_tilde`, `mk_arg`, `read_event`,
the ERR trap, `self_test_fire`/`_says`/`_case`, the repo-root walk, the Makefile
check, and now U1's silence check — is duplicated verbatim, which means every future
fix is two edits and a chance to fix one.

Flagging as a SUGGESTION rather than higher because the existing `cc-*.sh` corpus is
deliberately standalone: each hook is installed individually, is the consumer's file
to edit after install, and shares nothing. A `_ledger_courier.sh` would be a new
installable and a new sourcing relationship for a five-file corpus — plausibly worse.
The cheaper half is real regardless: U1's fix had to be applied twice today, and I
applied it by copying the tail from one file to the other.

The story calls each *"a thin shell"*. 319 lines is not thin. Most of it is comment
and self-test, both of which earn their place — but the description in `feature.md`
should say what these are, because a reader expecting thirty lines will not review
them.

### MINOR

**U4 — the hand form mints a `session` row carrying a `grain`, a shape nothing
documents.** `src/godot_devkit/repo/pm/cli.py:1558`.

```text
$ pm ledger record --grain 0.1/alpha/s0 --event Stop --tokens-in 3
[pm] ledger session row appended to …
{"ts":"…","kind":"session","grain":"0.1/alpha/s0","usage":{"input":3},"tree":{…}}
```

`feature.md`'s `session` example carries no `grain`, and a session is not about one
grain by construction — that is what the `tree` snapshot is for. `ROW_KEYS` permits
the combination and `--event` is accepted on the hand form (documented in USAGE as
`[--event E]`, with no statement of what it does there). Under "copy what the caller
said, judge nothing" this is defensible, and I would not add a refusal — but the
report will meet a `session` row with a `grain` and has to decide what it means. One
sentence in `_by_hand`'s docstring, or in USAGE, is enough.

## Passed

- Fail-open is real and it is never silent. Every one of the eleven failure paths I
  drove exits 0 and says why on stderr first, and the ERR trap catches the ones
  nobody enumerated. This is the hardest property in the feature and it holds.
- The division of labour is honoured exactly. The couriers read no transcript, sum no
  number, name no grain, and never look at `last_assistant_message` or
  `stop_hook_active`. I went looking for judgement leaking into the hook and found
  none.
- `mk_arg`'s two-expander escape (`printf %q` for the shell, `$`→`$$` for make) is
  the kind of thing that is written once and never tested; the self-test's stub `pm`
  target with an unquoted `$(ARGS)` actually proves it, and a path with a space
  recorded correctly through the real vehicle.
- The event kind is a constant, not `hook_event_name` off the payload. A mis-wired
  `settings.json` entry therefore cannot file a `dispatch` row for a session stop —
  and the comment at `cc-ledger-subagent.sh:59-64` says why, which is where that
  reasoning belongs.
- `cwd` in another repo does not contaminate it: with `cwd` pointed at a second
  checkout, no row was written there. (For the right reason after U1's fix, and for
  the wrong reason before it — that case was U1 in disguise.)
- An absent id is an omitted flag, not an empty one, and both self-tests assert it
  negatively (they fail if the flag appears at all), which is the right shape for
  that claim.

## Not verified

- **The couriers under real Claude Code.** Everything here is a synthesised payload
  through the hook file. I did not arm them in `.claude/settings.json` and watch a
  real `SubagentStop` fire, and that is the ship criterion.
- **`async: true` behaviour.** I proved the entry is printed with the flag
  (`test_install.py`); I did not prove a stop is not blocked, and I did not time
  `--from-transcript` against a tens-of-MB orchestrator transcript, which is the case
  `async` exists for. My largest transcript was the 60-record fixture.
- **`stop_hook_active` and one-row-per-stop.** The story says to respect the field
  "only to avoid double rows"; both hooks deliberately ignore it and leave
  de-duplication to the verb, and the verb does not de-duplicate either. I did not
  find a double-row case, and I did not construct one — a re-entrant stop needs real
  Claude Code.
- `make milestone`, `make gates`, `make smoke` — not run.
- The consumer checkouts — deliberately untouched.

## Note on the verdict block

U1 was fixed **in place and uncommitted**: SDLC § 2 says the orchestrator commits per
feature by pathspec, so no hash exists to cite, and `verdict.py`'s `landed` takes a
7–40 character hex hash and nothing else. It is described in full above and is not in
the table below. That gap is raised as R2 in the `review-record-shape` record.

```text
verdict: SHIP-WITH-FIXES
| id | severity | disposition |
| U2 | MAJOR | rejected: the root Makefile and .claude/settings.json are outside this pass's edit scope; arming the couriers here is the orchestrator's call |
| U3 | SUGGESTION | rejected: the cc-*.sh corpus is standalone by design; a shared library is a new installable, not a local cleanup |
| U4 | MINOR | deferred: 0.23.0/ledger-report |
```
