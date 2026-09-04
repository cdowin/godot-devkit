---
id: 0.24.0/smoke-proves-the-runners-the-release-ships/smoke-installs-into-a-worktree
feature: 0.24.0/smoke-proves-the-runners-the-release-ships
milestone: "0.24.0"
name: check all runs in a git worktree of the consumer carrying the working tree's runners
status: todo
owner:
depends_on: []
---

# check all runs in a git worktree of the consumer carrying the working tree's runners

For each consumer, `smoke()` adds a detached `git worktree` under `tempfile`, runs
`install-runners --force` there from the working tree (`install` is already imported), runs
`check all` + the censuses in that worktree, removes the worktree (`git worktree remove --force` +
`prune`) in a `finally`, and reports one extra row naming how many installed files were ahead of
the consumer's own. The read-only verbs (`scene`, `refs`, `pm status`, `autoloads`) stay on the main
checkout — they are what the consumer's pin runs today.

## Acceptance criteria

- The consumer's main checkout: `git status --porcelain` identical before/after (the existing row),
  and `git worktree list` identical before/after (a new row).
- A consumer with an older `Makefile.devkit` than the working tree's: `check all` row green; the
  `runners ahead` row says N > 0. A consumer already current: N = 0, same green.
- A failing install (a header-edited runner, m1's shape) is a red row naming the file — never a
  silent fallback to the in-place run.
- A unit test drives `smoke()` against a scratch git repo standing in for a consumer (no live
  consumer needed on CI), red on HEAD.
- CHANGELOG `## Unreleased` bullet.

## Out of scope

Installing hooks/agents/CI into the worktree (only runners are what `check` asks for).
