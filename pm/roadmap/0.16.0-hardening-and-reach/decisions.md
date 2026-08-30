Append with `godot-devkit pm decide <grain-id>` — never by hand; the command stamps the date and the next ordinal.

# 0.16.0 hardening-and-reach — decisions

Durable. This log outlives the grain: it is where a choice and its rejected
alternative are recorded, and it survives close.

> Never write what is derivable. `pm status` gives tallies, `git log` gives
> history. This file holds the WHY that neither of them records.

## D1 — 2026-08-30 — Scope ratified: all seven audit decisions, one milestone

The 2026-08-30 fresh-eyes audit (docs/reviews/2026-08-30-fresh-eyes-audit.md) surfaced seven
decisions; Chris ratified all seven into this one milestone: (1) the full correctness fix pass,
(2) a committed scrubbed corpus so CI proves byte-fidelity — rejected: keeping the corpus
laptop-only and weakening the CLAUDE.md claim, (3) retiring the case-rename migration machinery —
rejected: holding it until a major, since it is internal and interface-free, (4) upstreaming the
duplicated consumer hook corpus, (5) both written upstream asks (sub_resource values model;
uid untracked coverage + base36 codec), (6) all six new verbs, (7) the consumer adoption chores.
The milestone closes with a full technical readability review as its own feature, not a courtesy.

## D2 — 2026-08-30 — rm refuses a path that resolves nothing, --force restores the no-op

With no node present there is no evidence a removal ever happened — unlike `rename`, which can
prove "already renamed" by the target's existence — so a typo'd path was indistinguishable from
success at exit 0. `scene rm` now refuses (exit 1, file untouched); `--force` restores the exit-0
no-op for scripted re-runs, keeping hard-rule-3 idempotence available on request. Rejected: keeping
the unconditional no-op (hides typos), and refusing even under `--force` (breaks retry loops).
Flagged for Chris's end-of-run review: would have asked? NO — it follows the refuse-rather-than-
mangle doctrine directly.

## D3 — 2026-08-30 — Milestone work branches like the consumers do - main is merge-only here too

Chris's call, mid-milestone. Devkit's codified flow was work-on-main (`devkit.toml`'s D9 comment,
CLAUDE.md self-hosting, 0.15.0 built that way), and the orchestrator followed it without surfacing
the divergence from the consumers' branch-per-milestone SDLC — the toolkit that writes the SDLC
should live the same one. Ten local commits were moved to `milestone/0.16.0-hardening-and-reach`
before anything was pushed (no history rewrite; main restored to origin/main). Close = merge-commit
to main + tag. New feature `branch-discipline` encodes it: opt-in rule D10 (a `building`
milestone's `branch:` must not be the `[repo_hygiene] mainline`), devkit turns it on for itself,
and CLAUDE.md/devkit.toml stop describing the old flow. Rejected: leaving devkit on-main as a
single-maintainer carve-out — the carve-out is exactly how the divergence went unnoticed.
