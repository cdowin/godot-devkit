# Agent workflow — the devkit SDLC

The loop this repo actually runs, codified after running it. A contract, not a
narrative: each rule below was the resolution of a real failure or a real
decision (the decisions logs under `pm/roadmap/` hold the WHY). The base agent
roster that executes this SDLC in consumer repos is installed by
`godot-devkit install-agents`; the sources live under
`src/godot_devkit/repo/installables/`, and this repo self-hosts the pair it
runs itself (partial-roster self-hosting — see `tests/test_install.py`).

## 1. Milestone-branch SDLC

- **Work happens on `milestone/<id>`.** The milestone's `branch:` frontmatter
  declares it — that is rule **D9** (`godot-devkit check pm`): a `building`
  milestone with no `branch:` stamp leaves a fresh session guessing at
  `git branch -a`.
- **`main` is merge-commit-only, at close.** No direct commits to main while a
  milestone is building; close = merge-commit + tag, via the `/release` skill.
- **D10 (opt-in) holds a building milestone off the mainline:** a `building`
  milestone's `branch:` must not equal the `[repo_hygiene] mainline`. This
  repo turns it on for itself — the single-maintainer work-on-main carve-out
  is exactly how the divergence from the consumers' SDLC went unnoticed
  (decision D3, 0.16.0).
- Version bump is at CLOSE here, not at start (D8 stays off in `devkit.toml`;
  the consumers bump at start — both flows are legal, each repo declares one).
- **Forward only.** Nothing pushed is ever amended, rebased, reset or
  force-pushed; a botched commit is repaired with another commit.

## 2. The dispatch loop

**Scout once, not per-agent.** An audit / PO pass runs first and produces a
findings doc under `docs/reviews/` with file:line claims. That doc becomes
every dispatch's reference — each builder gets the claims it needs, already
verified, instead of re-deriving the survey N times.

**PM scaffold before build.** The milestone is a real PM tree
(`godot-devkit pm new …`), with features/stories for the ratified scope and a
decisions log appended through `pm decide` — never by hand.

**Phased parallel dispatch on DISJOINT file sets.** Builders run in parallel
only when their file sets cannot collide; overlapping work is serialized.
A dispatch prompt names the files the builder may touch and the files it must
stay out of.

**Builders:**

- never commit — they write, verify their slice, and report;
- never touch `pm/roadmap/`;
- never edit shared docs — README / CHANGELOG wording is returned as
  **PROPOSED** text in the report, and the orchestrator applies it;
- ship, with every fix, a test that **failed at HEAD** — watched failing on
  the unfixed code, passing on the fixed code;
- run **scoped** verification only (the slice's test file, the affected
  check) — never the full gate.

**The orchestrator:**

- verifies each reported slice against the actual tree (never the narration —
  subagents misreport pre-existing state);
- runs the one authoritative full gate (`make milestone`) itself;
- commits per feature by **explicit pathspec**;
- moves every status through the pm CLI (`pm story wip/review`,
  `pm feature done`, …) — `check pm` is the drift gate;
- applies proposed shared-doc wording, appends decisions, opens the close.

## 3. The model mix

Every roster agent carries `model:` and `effort:` frontmatter. **Effort
tracks how much judgment under UNCERTAINTY a role needs — not how important
it sounds.** Table borrowed from the consumers (set 2026-08-27), carried into
the installables:

| role | model | effort | why |
|---|---|---|---|
| `architect` | opus | high | every dispatch inherits its framing |
| `po` | opus | high | writes the briefs N agents execute verbatim — a wrong brief is N wrong builds |
| `developer` / `verification-builder` | opus | high | the job is judgment under a possibly-WRONG premise |
| `reviewer` / `verification-reviewer` | opus | **xhigh** | the gate, and it runs last; a miss here ships |
| `milestone-reviewer` | opus | high | pressure-tests the spec everything downstream builds from |
| `simplifier` | fable | high | *"should this exist"* has no ground truth — the most abstract pass |
| `test-writer` | sonnet | medium | audit-shaped work against a known diff |
| `tech-writer` / `changelog-writer` / `doc-hygiene` / `pm-operator` | sonnet | medium | prose sync + structured ops against a known diff |

**`model:` is overridable per-dispatch, downward.** For genuinely mechanical
stories — doc sweeps, retirements, template chores, renames — drop to a
cheaper model at lower effort in the dispatch itself. Keep the strong model
wherever the brief might be WRONG: judgment-under-possibly-wrong-premise is
the case the strong builders repeatedly earn their keep on. The closing
reviewer always runs strong at the highest effort.

> **`effort:` as a frontmatter key is UNVERIFIED.** A misspelled or
> unsupported frontmatter key is silently ignored — it does not error, it
> just does nothing — and the agent registry loads at session start, so it
> cannot be probed from the session that sets it. `model:` is the field with
> proven effect. To verify: put a deliberately invalid value on a throwaway
> agent and dispatch it; an error means the field is real, silent success
> means the whole column is inert.

## 4. Token economy

- **Builders run scoped test slices only.** One authoritative full-gate run
  per landing point, owned by the orchestrator. N builders each running the
  full suite is N-1 wasted runs — and a builder's green full gate still gets
  re-run before commit, so it bought nothing.
- **Reports are evidence + deltas.** What changed, what ran, what came back —
  numbers, not adjectives — plus what was NOT verified. No narrative recap of
  the dispatch prompt, no pasted PASS walls: gate output is quoted only when
  it FAILED.
- **Reports are capped.** A dispatch report that cannot fit in roughly a
  screenful of findings is doing the orchestrator's synthesis job badly.
  Proposed shared-doc wording rides in the report; artifacts ride in files.
- **Every report ends with its token cost**, so an over-budget dispatch is
  visible while the session can still act on it.

## Close protocol (ordered)

Only once all features report and the tree is reconciled:

1. **Full gate** — `make milestone` (gates + matrix + smoke), orchestrator's
   own run.
2. **Cross-cutting review** — a fresh strong reviewer over the milestone's
   whole commit range (adversarial input, run — never diff-reading); land
   wrap-up fixes; re-green.
3. **Docs + changelog** — sync drifted docs; retitle `CHANGELOG.md`'s
   Unreleased section per the release skill.
4. **Resolve findings** — every `docs/reviews/` doc for the milestone
   resolved and deleted (create → resolve → delete).
5. **Bump + merge + tag** — version bump (`__init__.py` and `pyproject.toml`
   together), merge-commit to `main`, tag via the `/release` skill, consumer
   pins reminded.
