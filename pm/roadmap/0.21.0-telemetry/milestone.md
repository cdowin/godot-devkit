---
id: "0.21.0"
name: telemetry
status: planning
depends_on: ["0.20.0"]
branch: milestone/0.21.0-telemetry
risk: medium
---

# telemetry

Filed 2026-09-02 (Chris: *"Our goal is efficiency towards the goal, not necessarily no tokens
spent."*). After the 0.19.0/0.20.0 efficiency work the only evidence that it helped was the
orchestrator tallying agent reports by hand — small N, self-reported, features of different size.
This milestone makes the devkit record what a dispatch cost and what it bought, so the trend is a
report and not an anecdote, across milestones and across consumers.

## The five questions, each with a denominator

1. **Cost per shipped unit** — tokens per story closed / feature done / bug fixed, normalized by
   `size:`, split by role (developer, po, reviewer, simplifier, tech-writer).
2. **Yield per role** — per review pass: findings by severity, landed / rejected-with-reason /
   deferred-to-a-named-feature. A 200k review that finds two real bugs is efficient; a 200k
   review of nits is not. Simplifier: lines deleted per landed finding.
3. **Rework** — commits after a story's `review` flip, fixup commits per feature, verdict
   distribution (SHIP / SHIP-WITH-FIXES / HOLD), stories reopened.
4. **Escapes** — a failure found later than it should have been: a scenario red after a feature
   closed, a bug whose `caused_by:` names a closed feature. Progress that had to be re-bought is the
   most direct measure of "toward the goal".
5. **Overhead shape** — dispatches per story (one cold start per story is the floor), tool calls
   before the first write (orientation), gate runs per story and how many re-ran the same gate on
   the same range, NEEDS-YOU items per feature and how long each blocked.

## What this is NOT

Not a budget, not a gate, not a leaderboard. Token minimization as a target Goodharts into skipped
reviews; the devkit informs and never enforces (devkit charter: integrity checks stay, process
enforcement is deleted). `pm ledger report` prints one quiet table; nothing exits non-zero on a
number.

## Where the data comes from, for free

The `pm` verbs already touch every status flip → they stamp the ledger. Every agent report already
carries tokens / tool calls / duration → a `SubagentStop` hook records it with no orchestrator
effort. Review records need one small parseable block. Bugs need one field.

## Ship criterion

`pm ledger report 0.90.3` in nullbound prints the five questions for that milestone from the
ledger, with this session's dispatches backfilled as the baseline (0.19.0/0.20.0 before/after);
trail's first milestone reports the same table from a hook-captured ledger with no hand entry.

## Risks

- The hook's view of a dispatch: does `SubagentStop` see usage and the prompt? Story
  `subagent-stop-hook-records-usage` spikes it first and falls back to `pm ledger record`.
- Grain attribution: a dispatch that spans two stories is attributed to the one its commit
  prefixes name most; ambiguity is recorded as `grain: ?`, never guessed.
