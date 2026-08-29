Append with `godot-devkit pm decide <grain-id>` — never by hand; the command stamps the date and the next ordinal.

# 0.14.0 self hosting — decisions

Durable. This log outlives the grain: when the milestone closes it collapses to
pointers, and everything that still explains a live constraint stays.

Collapsed at close. The full trail of 16 decisions is in git history
(`git log -p` on this file); the design detail that produced them lives at the
feature grain, `features/self-hosting/decisions.md`. Twelve described choices now
embodied in the code and the README — the changelog slot, the log schema, stdout
for the render, component-wise version ordering, D16's separation from D15, the
ledger ceiling rule, the mandated-header exclusion, the backticks-only
info-string rule, grain detection, the unreadable-definition census, and one
answer on every interpreter. Four remain because a consumer still runs into them.

## D7 — 2026-08-29 — the ratchet lives inside check pm
**Chose:** put D17/D18 inside check pm
**Over:** a gate of their own
**Because:** the ledger needs the grain vocabulary D13/D14 already own, and splitting them means two implementations of what a grain document is
**Evidence:** dcb2511

## D8 — 2026-08-29 — a debt ledger entry carries a ceiling
**Chose:** require a line ceiling on every prose_grandfather entry
**Over:** allowing a whole-file exemption the way the log ledgers do
**Because:** an uncapped entry is a permanent pass, which is the one thing a ratchet cannot have
**Evidence:** dcb2511

## D10 — 2026-08-29 — the caps are config
**Chose:** ship the prose caps as [pm] config keys
**Over:** constants baked in from one consumer measured distribution
**Because:** those numbers are that consumer p90, not a law, and a cap that fits one repo misfires on the next
**Evidence:** dcb2511

## D16 — 2026-08-29 — the new rules ship off
**Chose:** ship D11 through D18 OFF by default
**Over:** enabling them for every consumer on upgrade
**Because:** a tree predating the canonical slots fails most of them, and a rule that reddens a consumer on upgrade day is unshippable
**Evidence:** e432831
