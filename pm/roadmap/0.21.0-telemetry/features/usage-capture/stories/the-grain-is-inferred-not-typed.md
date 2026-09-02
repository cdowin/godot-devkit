---
id: 0.21.0/usage-capture/the-grain-is-inferred-not-typed
feature: 0.21.0/usage-capture
milestone: "0.21.0"
name: the hook resolves the story or feature from the dispatch prompt or the commit prefix on the branch since spawn
status: todo
owner:
depends_on: []
---

# the hook resolves the story or feature from the dispatch prompt or the commit prefix on the branch since spawn

## Goal
The hook resolves `grain` from (1) a `0.NN.N/<feature>/<story>` id in the dispatch prompt, else (2) the commit prefixes `type(<grain>/S<n>)` on the branch since the spawn time, else `?`. Ambiguity (two grains) → `?` plus both candidates in `notes`; never a guess.
## Verification
`make test` (prompt fixture, git fixture with two prefixed commits, ambiguous case).
## Commit prefix
`feat(0.21.0/usage-capture/S2):`
## Size
s
