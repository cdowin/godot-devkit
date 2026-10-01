# SDLC — how this repo runs the protocol

The loop is agentic-sdlc's: build wide, integrate once. The architect writes a story, moves it,
and dispatches a builder; the builder runs the spot check (`make pyunit` here), commits, pushes
`feat/<slug>` and stops; `make sdlc ARGS='integrate <slug>...'` merges a batch and proves it once;
`make sdlc ARGS='release <version>'` writes the milestone and CI runs the full tiers on the PR.
The installed `run-the-sdlc` skill has the commands, the per-edit loop is
[`.claude/rules/pm-execution.md`](.claude/rules/pm-execution.md), and the rungs are in
[`CLAUDE.md`](CLAUDE.md). Below is only what is this repo's own.

## Branches

- **One branch per milestone, `milestone/<id>`**, declared in the milestone's `branch:` frontmatter
  (D9). `main` is merge-commit-only, at close; D10 keeps a building milestone off it.
- **The version bumps at close**, in the release commit — so D8 (bump at start) stays off.
- **Forward only.** Nothing pushed is amended, rebased, reset or force-pushed; a botched commit is
  repaired with another commit.

## Reviews

- **A review is a judgement, not a step.** One reviewer over a batch when its risk asks for one (a
  gate's scoping, a grammar, a persisted format, input). A finding is a bug in the tree.
- **Every fix ships a test that failed at HEAD.** Every new input surface — a verb, an id or path
  grammar, a config key, a payload parser — ships its refusal matrix in the same story.
  `tests/test_fuzz_inputs.py` is the standing floor beneath it.

## Reports

Evidence and deltas: numbers, what ran, what came back, and what was NOT verified. Gate output is
quoted only when it FAILED. Decisions for Chris go at the top, as a numbered `NEEDS YOU` list.
