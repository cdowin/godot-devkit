# SDLC — how this repo runs the protocol

The protocol — the belts, their checks, and the one thing each writes — is
[`docs/sdlc-protocol.md`](docs/sdlc-protocol.md), rendered by `agentic-sdlc install-sdlc` from this
repo's `devkit.toml`; nothing it says is repeated here. The per-edit loop is
[`.claude/rules/pm-execution.md`](.claude/rules/pm-execution.md), and the rungs as this repo runs
them are in [`CLAUDE.md`](CLAUDE.md). Below is only what is this repo's own.

## Branches

- **One branch per milestone, `milestone/<id>`**, declared in the milestone's `branch:` frontmatter
  (D9). `main` is merge-commit-only, at close; D10 keeps a building milestone off it.
- **The version bumps at close**, in the release commit — so D8 (bump at start) stays off.
- **Forward only.** Nothing pushed is amended, rebased, reset or force-pushed; a botched commit is
  repaired with another commit.

## Reviews

- **A findings doc before a build, not per builder.** An audit pass writes a record under
  `docs/reviews/` with file:line claims, and every dispatch works from it. Records are created,
  resolved and deleted; a milestone closes with none open (`findings-resolved`).
- **The review runs before the gate, and the gate runs last.** A cross-cutting reviewer over the
  milestone's whole commit range — adversarial input RUN, never a diff read — then every finding
  landed or deferred in writing, then `make milestone`, once, the orchestrator's own run. A gate
  that answers before the review answers for a tree nobody will ship.
- **Builders never commit**, never touch `pm/roadmap/`, and never edit the shared docs — README and
  CHANGELOG wording comes back as PROPOSED text. The orchestrator verifies each slice against the
  tree rather than the narration, commits by explicit pathspec, and moves every status through
  `make pm ARGS="…"`.
- **Every fix ships a test that failed at HEAD.** Every new input surface — a verb, an id or path
  grammar, a config key, a payload parser — ships its refusal matrix in the same story: the inputs
  it rejects, enumerated and each proven to refuse without a write, plus hostile cases against its
  own docstring's "never" and "only". `tests/test_fuzz_inputs.py` is the standing floor beneath both.

## Reports

Evidence and deltas: numbers, what ran, what came back, and what was NOT verified. Gate output is
quoted only when it FAILED. Decisions for Chris go at the top, as a numbered `NEEDS YOU` list.
