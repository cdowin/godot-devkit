---
id: 0.18.1/sandbox-hook-quoting/01-quote-aware-tokenizer
feature: 0.18.1/sandbox-hook-quoting
milestone: "0.18.1"
name: Quote-aware segment split plus the self-test corpus
status: done
owner:
depends_on: []
---

# Quote-aware segment split plus the self-test corpus

## Acceptance criteria

- `split_command_segments` walks the line tracking single/double quote state and emits a
  segment break only for an operator OUTSIDE quotes; an unbalanced quote returns non-zero
  and the caller falls back to the `tr` split.
- Every BLOCK case the v0.16.0 matrix pins still exits 2, including the godot-named
  variable spellings, which are quoted and genuinely first in their segment.
- `bash tools/hooks/cc-godot-sandbox.sh --self-test` replays the corpus through the real
  hook and exits non-zero on any wrong verdict (the `set -e` + fail-open ERR trap must not
  convert a self-test failure into exit 0).
- The consumer's sourced-boot-function guard ships as `SANDBOX_FUNCTION` in the project
  config header, empty by default and inert when empty — including the fast path.
- README + `install-hooks` next-step name the `--self-test` wiring.

## Out of scope

The consumer's own copy — nullbound re-installs with `--force` after the tag.
