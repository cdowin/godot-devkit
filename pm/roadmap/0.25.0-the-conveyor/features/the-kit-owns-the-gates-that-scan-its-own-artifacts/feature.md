---
id: 0.25.0/the-kit-owns-the-gates-that-scan-its-own-artifacts
milestone: "0.25.0"
name: A gate that scans an artifact this kit owns belongs to this kit, not to each consumer
status: planning
reviewed:
risk: medium
size: m
phase: 1
depends_on: []
consumed_by: ["0.25.0/every-gate-reports-its-cost"]
labels: ["gates", "installables", "consumers", "subtraction"]
---

# A gate that scans an artifact this kit owns belongs to this kit

**Chris, 2026-09-04:**

> *"And these checks. Who's authoring them? These seem like good things for agentic-sdlc to own right?
> The code/processes to scan its own stuff? This way when we fix this, all consumers get fixed."*

## The rule, and it draws a line rather than a blanket

**If a gate scans an artifact THIS KIT owns — grain documents, the hook corpus, the runners, the
sandbox — this kit owns the gate. If it scans the consumer's own code, the consumer owns it.**

The test is one question: **does every consumer want it?** A prose cap on grain documents: yes, every PM
tree has them. A scan asserting Godot draw order is named from one game's z-layer vocabulary: no.

Moving the second kind here would be the cross-wiring rule 8 bans, running the other direction.

## Measured, not assumed — and the split is 4 of 20

Timed and traced across one consumer's twenty `[gates] extra` entries:

| gate | scans | verdict |
|---|---|---|
| `pm-shape-scan` | grain-document prose caps | **MOVE** — pure SDLC schema |
| `hooks-self-test` | the hook corpus this kit installs | **MOVE** — artifact is already ours |
| `runners-self-test` | the runners this kit installs | **MOVE** — same |
| `hermetic-scan` | `hermetic_run_scan.sh`, already our installable | **MOVE** — same |
| the other **16** | that game's own architecture — capability contracts, effect dispatch, draw order, tile clearance, signal emitters | **STAY**. Not ours, and never should be. |

## The evidence that settles it

**`pm_shape_scan.sh` is NOT in this kit's installables — a consumer authored it.** It enforces THIS
package's grain schema, and it lives in one game repo.

**The other consumer does not have it at all.** Its `tools/dev/checks/` holds `config_pins.sh`,
`content_schema_lint.py` and `doctor.sh` — no prose-cap gate of any kind. So a rule this package defines,
and documents in its own templates, is enforced in exactly one of two trees and unenforced in the other.
Nobody decided that; it is just where the file happened to be written.

**And the cost of that misplacement is already measured.** `pm-shape-scan` runs **34.8 s** — half of that
consumer's entire gate set — because `_doc_lines` spawns four subprocesses per file across 683 markdown
files. One `awk` pass does it in under a second. Fixed where it lives, one repo gets a 34-second gate
back. Fixed here, **every consumer gets it on their next pin bump, and the tree that never had the gate
gains it.** That is the whole argument in one number.

## The second, subtler half — the artifact is ours and the WIRING is not

`hooks-self-test`, `runners-self-test` and `hermetic-scan` invoke scripts this kit already installs
(`cc-godot-sandbox.sh --self-test`, `gdk_runners.sh`, `hermetic_run_scan.sh`). We ship the thing; each
consumer must then remember to wire a make target and add it to `[gates] extra`.

**A guard nobody wired is a guard that is not there** — the same failure mode as a hook that fails open,
which this package has already shipped once. If the artifact is ours, its gate belongs in `[checks] all`
where it runs by default and a consumer opts OUT, rather than in twenty per-consumer make targets where a
consumer must opt IN and can silently never do so.

## Scope

| Thing | Action |
|---|---|
| a prose-cap check over grain documents | NEW here, rewritten as one pass rather than per-file spawns |
| the hooks / runners / sandbox self-tests | MOVE into `[checks] all` from per-consumer wiring |
| `[checks] all` default roster | GROW — and each addition argued, since it now runs everywhere |
| consumer `[gates] extra` | SHRINK by four in the tree that had them |

## Risks

1. **A gate that lands in `[checks] all` reds every consumer at once.** The prose-cap check in particular
   will find things in a tree that never had it. It ships reporting-only first, or with the ceiling read
   from config so a tree adopts at its own pace — the same posture the deprecation window took.
2. **Not every consumer has a PM tree.** The check must be a no-op, not a failure, on a repo with no
   `pm/roadmap` — the way the Godot gates already degrade on a repo with no Godot tree.
3. **This grows the default roster, which is the thing releases keep having to justify.** Four gates is
   the argued set; a fifth needs the same "does every consumer want it" test, in writing.
