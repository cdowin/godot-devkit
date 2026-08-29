Append with `godot-devkit pm decide <grain-id>` — never by hand; the command stamps the date and the next ordinal.

# 0.14.0 self hosting — decisions

Durable. This log outlives the grain: when the milestone closes it collapses to
pointers, and everything that still explains a live constraint stays.

> Never write what is derivable. `pm status` gives tallies, `git log` gives
> history. This file holds the WHY that neither of them records.

## D1 — 2026-08-29 — changelog.md is a milestone slot
**Chose:** make changelog.md a canonical MILESTONE file slot
**Over:** a per-feature changelog.md
**Because:** a release is a milestone; a feature contributes to it through the entry Evidence pointer, not through a log of its own
**Evidence:** e432831

## D2 — 2026-08-29 — the notes survive the close
**Chose:** keep changelog.md on a `done` grain
**Over:** skipping it at close the way the transient review.md is skipped
**Because:** a closed milestone is exactly when its release notes matter most
**Evidence:** e432831

## D3 — 2026-08-29 — one log implementation, two schemas
**Chose:** parameterise the decision machinery by a LogSchema value
**Over:** a second copy of the parser, validator, writer and gate for changelog.md
**Because:** the writer must refuse exactly what the gate reports, and two implementations of one entry format drift apart
**Evidence:** e432831

## D4 — 2026-08-29 — --render writes to stdout
**Chose:** print the render to stdout and every count, skip and defect to stderr
**Over:** having --render write the changelog file itself
**Because:** the consumer redirects the document, and redirecting it must not swallow the report of a half-written entry
**Evidence:** e432831

## D5 — 2026-08-29 — versions compare component-wise
**Chose:** order rendered milestones by declared version compared component-wise
**Over:** sorting the version strings descending
**Because:** string order publishes 0.9 as newer than 0.10, wrong in the one place a reader trusts a changelog most
**Evidence:** e432831

## D6 — 2026-08-29 — D16 is not part of D15
**Chose:** a separate D16 for whether a done milestone has notes at all
**Over:** folding the emptiness test into D15
**Because:** a conforming EMPTY log satisfies a schema rule forever, so the schema can never ask that question
**Evidence:** e432831

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

## D9 — 2026-08-29 — prose-ledger will not raise a ceiling
**Chose:** make pm prose-ledger refuse to raise an existing ceiling
**Over:** regenerating whatever the tree currently measures
**Because:** otherwise every growth is absorbed by a regeneration and the gate is decorative
**Evidence:** dcb2511

## D10 — 2026-08-29 — the caps are config
**Chose:** ship the prose caps as [pm] config keys
**Over:** constants baked in from one consumer measured distribution
**Because:** those numbers are that consumer p90, not a law, and a cap that fits one repo misfires on the next
**Evidence:** dcb2511

## D11 — 2026-08-29 — the mandated header is not prose
**Chose:** exclude the tool-mandated slot header from every prose line count
**Over:** counting it like any other line
**Because:** D13 asserts it is present, so counting a constant an author cannot trim silently shrinks every cap by two
**Evidence:** dcb2511

## D12 — 2026-08-29 — the info-string rule is backticks only
**Chose:** apply the info-string-may-not-contain-a-backtick rule to backtick fences only
**Over:** applying it to tilde fences as well
**Because:** a tilde fence info string may legally carry backticks, so over-applying would mask a document real sample
**Evidence:** 2eaae12

## D13 — 2026-08-29 — a grain is its frontmatter
**Chose:** define a grain document as one carrying a frontmatter block
**Over:** an ignore list of non-grain filenames under bugs/ and stories/
**Because:** it is the tree own existing definition rather than a second one, and it cannot reopen the hole recursion just closed
**Evidence:** 2eaae12

## D14 — 2026-08-29 — an unreadable definition leaves the census
**Chose:** report an undecodable agent definition and take it OUT of the scanned count
**Over:** skipping it while still counting it as scanned
**Because:** a census that counts what it could not read is the silent mask this package calls its cardinal sin
**Evidence:** 2eaae12

## D15 — 2026-08-29 — one answer on every interpreter
**Chose:** answer False for a path the filesystem refuses, on every supported Python
**Over:** letting Path.exists raise through 3.13 and return False from 3.14
**Because:** a tool whose refusal-versus-traceback depends on which interpreter uvx picked is not a tool
**Evidence:** 2eaae12

## D16 — 2026-08-29 — the new rules ship off
**Chose:** ship D11 through D18 OFF by default
**Over:** enabling them for every consumer on upgrade
**Because:** a tree predating the canonical slots fails most of them, and a rule that reddens a consumer on upgrade day is unshippable
**Evidence:** e432831
