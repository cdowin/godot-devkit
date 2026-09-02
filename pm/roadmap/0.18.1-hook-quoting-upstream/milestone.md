---
id: "0.18.1"
name: hook-quoting-upstream
status: building
depends_on: []
branch: milestone/0.18.1-hook-quoting-upstream
---

# 0.18.1 — hook-quoting-upstream

A consumer forked `cc-godot-sandbox.sh` 183 lines away from the installable to fix a
false-BLOCK: the segment tokenizer cut at shell operators without tracking quote state,
so a `godot`-looking word inside quotes became the next segment's COMMAND word.
`echo "foo; godot --headless"` was blocked. The fork also grew a `--self-test` corpus so
the verdicts are replayed rather than claimed. This milestone brings both home and leaves
the consumer with a stock installable again.

## Ship criterion

The installable's tokenizer never makes a quoted word a command-word candidate; every
pre-existing BLOCK case still blocks; `bash tools/hooks/cc-godot-sandbox.sh --self-test`
replays the whole corpus and is a documented `make check` member for consumers; the
devkit's own hook matrix pins the quoting cases.

## Risks

- A quote-aware split that slides OPEN is the cardinal sin here: an unbalanced quote must
  fall back to the strict naive split, never to "allow".
- The consumer's sourced-function guard is project-named. It ships as an empty-default
  config variable — an empty value must not degrade the fast path into matching everything.
