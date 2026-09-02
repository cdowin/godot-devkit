Append with `godot-devkit pm decide <grain-id>` — never by hand; the command stamps the date and the next ordinal.

# 0.18.1/sandbox-hook-quoting The engine-boot guard stops blocking a quoted godot word — decisions

Durable. This log outlives the grain: it is where a choice and its rejected
alternative are recorded, and it survives close.

> Never write what is derivable. `pm status` gives tallies, `git log` gives
> history. This file holds the WHY that neither of them records.

## D1 — 2026-09-02 — The sourced-boot-function guard ships as an empty-default config variable, not a project name

The consumer's fork hard-codes `nullbound_rebuild_import_cache` in four places:
the fast path, the command-word branch, the BLOCK message and the corpus. The
installable cannot carry another repo's function name, so the guard ships as
`SANDBOX_FUNCTION` in the project-config header — empty by default, and every
branch it feeds is skipped when empty. The corpus grows its two block and two
allow cases only when the variable is named, which is why the self-test prints
its counts: `11 block / 9 allow` stock, `13 / 11` armed.

REJECTED — dropping the case entirely: the consumer would fork again on the
next install, which is the thing this milestone exists to end. REJECTED — an
environment variable read at hook time: the hook is invoked by Claude Code, not
by the consumer's Makefile, so nothing would set it where it matters, and the
project-config header is the mechanism this file already uses for exactly this.

The empty value is not free. `case "$INPUT" in *"$SANDBOX_FUNCTION"*)` with an
empty value matches EVERY command, silently retiring the fast path for every
consumer that left the stock value alone — so the fast path tests it in two
steps, and a test pins that direction.

## D2 — 2026-09-02 — The quote-aware split is bounded, and the bound escapes to the STRICT path

The walk beats the `tr` fork at every size a person types (4.3KB: 0.35s against
0.48s) but degrades on a pathological line — 36KB carrying 4,000 operators
measured 12s, and a hook that stalls the session is its own kind of broken.
Past `SPLIT_MAX_CHARS` (8192) the naive split runs instead: over the bound the
guard is exactly as strict as it was before this fix, never looser. Same escape
an unbalanced quote takes, for the same reason.

REJECTED — no bound: 12s of dead air in a PreToolUse hook is a wedge with extra
steps. REJECTED — refusing (exit 2) over the bound: a guard that blocks on
LENGTH blocks legitimate long commands, and a false BLOCK is the class this
release exists to remove.
