# The protocol, as the machine runs it

<!-- Written by `agentic-sdlc install-sdlc`. Do not hand-edit: the check lists
     below are RENDERED from this repo's devkit.toml and the registry that runs
     them, so change those and re-run the verb. -->

Run it — one verb per level, and none of them is "run the biggest thing":

```
agentic-sdlc close story   <story-id>      the inner loop, seconds
agentic-sdlc close feature <feature-id>    once its stories are done
agentic-sdlc release       <version>       once its features are done
agentic-sdlc adopt         <version>       a devkit pin bump, scoped to the adoption
```

**A belt is its checks, then one write or a clean error** (D12). Every check
prints one line — `ok: <check> — <detail>`, or `error: <check>: <what is
false>` — and then the belt writes AT MOST ONE thing: the status of the grain
it was asked about, set to the first state of that kind's `done` category. All
true: the write, exit `0`. Any false: no write, exit `1`, every false check
named; `--force` writes anyway and the milestone's `ledger.jsonl` gets one
`deviation` row naming them. Exit `2` is a declaration that could not be read.
A check that cannot be decided prints `unverifiable:` and counts as false.

Nothing else is written, moved, bumped, pushed or tagged; what is yours to do
after a write is printed as `next:` lines and listed under each belt below.
Whether a false check should stop you is YOUR question — that is what
`--force` is for, on the record; `agentic-sdlc check <gate>` is what FAILS a
tree, in CI and pre-push.

## `release` — the checks

| # | check | runs | what must be true |
|---|---|---|---|
| 1 | `tree-clean` | — *(reads the tree)* | `git status --porcelain` is empty. |
| 2 | `on-milestone-branch` | — *(reads the tree)* | HEAD is the branch the milestone document stamps in `branch:` (D9). |
| 3 | `changelog-unreleased-nonempty` | — *(reads the tree)* | the changelog's `## Unreleased` section holds at least one bullet. |
| 4 | `features-done` | `agentic-sdlc pm ready-for milestone <id>` *(shipped)* | `pm ready-for milestone <milestone>` exits 0 — every feature is in the `done` category and no open bug names the milestone. |
| 5 | `findings-resolved` | `agentic-sdlc pm ready-for tag <id>` *(shipped)* | `pm ready-for tag <milestone>` exits 0 — no finding in any record the milestone's grains point at is `open`. |
| 6 | `version-sync` | — *(reads the tree)* | every configured version site names the release version; read, never bumped. |
| 7 | `gate` | `make milestone` | the configured gate command exits 0. |

**Then, all true:** the milestone's status → the first state of `[pm.states.milestone] done` (`pm vocabulary` prints it), through `pm milestone <state> <id>`, which mints the ledger's `status` row. Any check false → `error:` lines, exit 1, no status written. `--force` writes anyway and the ledger's `deviation` row names the false checks.

**Yours, after the write** (printed as `next:` lines):

- retitle the changelog: `## Unreleased` becomes `## v<version> — <ISO date>`, with a fresh empty `## Unreleased` above it
- commit the roadmap directory and the changelog as the release commit
- push the branch: `git push -u origin <branch>` — never the mainline
- open the PR from <branch> to <mainline>
- wait for the required checks on the PR to go green
- merge it as a MERGE COMMIT — the mainline is merge-commit-only, and a squash loses the milestone's range
- tag the merge commit and push the TAG ref only: `git tag v<version> && git push origin refs/tags/v<version>` — a published tag is never force-moved
- prove the published artifact reports <version> from a cold cache — configure `[release.commands] prove-artifact` to name how
- open the next milestone, so the next release's notes have somewhere to go from the first commit

## `adopt` — the checks

| # | check | runs | what must be true |
|---|---|---|---|
| 1 | `pin-bumped` | — *(reads the tree)* | the `DEVKIT_VERSION` line in this repo's own makefile names the version of the package that is running. |
| 2 | `installables-current` | — *(reads the tree)* | every installed file is byte-current with what this version ships, or differs only in its project-config header; each that differs is named with the `install-* --diff` that shows it. |
| 3 | `config-updated` | — *(reads the tree)* | every devkit.toml section this version reads accepts what this repo declares. |
| 4 | `hooks-self-test` | `agentic-sdlc check hooks` *(shipped)* | `check hooks` exits 0 — the installed guards still return the verdicts their own corpus asserts. |
| 5 | `runner-targets-resolve` | `make -n <[adopt] runner_targets>` *(shipped)* | the composed gate targets resolve under `make -n`; an empty tier list passes and says so. |
| 6 | `checks-pass` | `agentic-sdlc check all` *(shipped)* | this package's `agentic-sdlc check all` exits 0 — not `make check`, which verifies your code against your rules. |
| 7 | `pm-validates` | `agentic-sdlc pm validate` *(shipped)* | `pm validate` exits 0; a repo with no PM tree is refused. |

**Then:** nothing. `adopt` writes nothing; it is checks only, and `--force` is refused.

**Yours, after the write** (printed as `next:` lines):

- commit the pin bump and every installable you took or hand-applied

## `story` — the checks

| # | check | runs | what must be true |
|---|---|---|---|
| 1 | `story-exists` | — *(reads the tree)* | the story id resolves to exactly one document. |
| 2 | `story-verified` | `agentic-sdlc verify --story` *(shipped)* | `agentic-sdlc verify --story` exits 0 — the make target `[verify] story` names, the way `feature-verified` runs its rung. |
| 3 | `committed` | — *(reads the tree)* | nothing is uncommitted outside the roadmap directory; it names what is and never commits. |
| 4 | `evidence-written` | — *(reads the tree)* | the story file carries `done: <hash(es)> — <what shipped>`; read, never written. |

**Then, all true:** the story's status → the first state of `[pm.states.story] done` (`pm vocabulary` prints it), through `pm story <state> <id>`, which mints the ledger's `status` row. Any check false → `error:` lines, exit 1, no status written. `--force` writes anyway and the ledger's `deviation` row names the false checks.

**Yours, after the write** (printed as `next:` lines):

- commit the roadmap directory — the status line and the ledger row this belt wrote
- when every story of the feature is done: `agentic-sdlc close feature <feature-id>`

## `feature` — the checks

| # | check | runs | what must be true |
|---|---|---|---|
| 1 | `stories-done` | `agentic-sdlc pm ready-for feature <id>` *(shipped)* | `pm ready-for feature <id>` exits 0 — every story under this feature is in the `done` category. |
| 2 | `feature-verified` | `agentic-sdlc verify --feature` *(shipped)* | `agentic-sdlc verify --feature` exits 0; not in the shipped list, add it to `[feature] steps`. |
| 3 | `review-recorded` | — *(reads the tree)* | the feature's `reviewed:` record exists, is repo-relative, and its verdict block parses. |
| 4 | `findings-landed` | — *(reads the tree)* | no finding in that record sits at `disposition: open`. |

**Then, all true:** the feature's status → the first state of `[pm.states.feature] done` (`pm vocabulary` prints it), through `pm feature <state> <id>`, which mints the ledger's `status` row. Any check false → `error:` lines, exit 1, no status written. `--force` writes anyway and the ledger's `deviation` row names the false checks.

**Yours, after the write** (printed as `next:` lines):

- commit the roadmap directory — the status line and the ledger row this belt wrote
- when every feature of the milestone is done: `agentic-sdlc release <version>`

## Not checks, and why

A check earns its place by having something to READ in the tree. What follows is real protocol with nothing to read, so the machine states it and does not pretend to enforce it.

**Pick the bump yourself.** Patch, minor or major is a semver judgement about the interface, and no check can make it. Output-line-shape changes are minor at least; anything a consumer must edit for is major.

**The negative probe for a gate whose scoping changed.** Introduce the drift class into a scratch copy of a fixture repo and confirm the gate FAILS. It is not a check: the artifact is a judgement made in scratch, with nothing in the tree to read.

**The consumer follow-up.** A consumer bumps its pin, runs `install-* --diff`, and decides PER FILE. It is not a check: those are instructions for somebody in another repo, and this package gates on no other repo's state (hard rule 8).

**Forward only.** Nothing pushed is ever amended, rebased, reset or force-pushed. A botched commit is repaired with another commit, and a bad release is a new patch version — never a rewritten tag.

## Changing this document

Edit `[<operation>] steps` (or `[<operation>.commands]`) in `devkit.toml` and
re-run `agentic-sdlc install-sdlc --force`; every line above is derived.
