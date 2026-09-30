---
id: ft-the-integration-tier-boots-once
kind: feature
milestone: 1.4.0
name: the integration tier boots once
status: done
reviewed: docs/reviews/2026-09-29-1.4.0-the-integration-tier-boots-once.md
depends_on: []
consumed_by: []
changelog:
---

# the integration tier boots once

Issues: #36. Pulled from 1.5.0 into 1.4.0 so that a consumer gets #36 and #37 in one pin bump.

Every integration scenario is one cold Godot process, and each boot costs 13–15 s of CPU before
the first assertion. NullBound's full tier is 166 boots, about 2,200 s of CPU and 37 minutes. Warm
mode boots Godot once per worker and runs a slice of scenarios in sequence, each against a fresh
World. Cold one-process-per-scenario stays for the scenarios that need it, and as the fallback.

The kit owns the runners (`scenario.sh`, `integration.sh`). The consumer owns its GDScript scenario
runner and `scenario_base`, which is where the reset (autoload state, World, player) lives. So this
feature ships the runner side plus a written CONTRACT the consumer's runner implements. The kit ships
no GDScript here.

## Decided (do not re-plan)

- **Opt-in, default off.** `GDK_INTEGRATION_WARM=1` (env; a value other than 0 or 1 exits 2)
  switches `integration.sh --all|--diff|--system` to warm mode. Unset, every path behaves
  byte-identically to today (rule 5): a consumer turns it on only once its runner implements the
  contract. `--cold` forces today's path for one run.
- **The contract** (a README section, and the header of `scenario.sh`). Booted with
  `-- <GDK_SCENARIO_SUITE_ARG> a,b,c` (default `--scenarios`, comma-separated), the consumer's
  runner:
  1. prints `[SCENARIO] <name> START` before each scenario (the START marker, an ERE
     `GDK_SCENARIO_START_RE` built the same way as `GDK_SCENARIO_RESULT_RE`);
  2. runs it against a fresh World, with the reset its `scenario_base` owns;
  3. prints its usual verdict line (`GDK_SCENARIO_RESULT_RE`, `… PASS|FAIL …`);
  4. exits after the last one.
  The single-scenario `--scenario <name>` path is unchanged.
- **`scenario.sh --suite <name> [<name>…]`** is the warm worker, so the engine-error layer and noise
  allowlist stay in ONE file. It boots once and splits the stream at the START markers. Engine
  errors between START and a verdict belong to that scenario, and upgrade a PASS to FAIL exactly as
  today. Each scenario's slice is published to `.scenario-reports/<name>.log` by the same
  private-file-then-move rule. One console line per scenario, same shape as today.
  - **Bound (the hang).** A worker is killed when no new START or verdict arrives within
    `GDK_SCENARIO_HARD_TIMEOUT` (per scenario, not per suite).
  - **Crash or hang mid-suite.** The scenario in progress and every scenario that never started
    get NO verdict from the warm run. They are handed back to the caller as "unrun". The worker
    prints `  WARM-ABORT  after <last finished> — N scenario(s) handed back` and exits with a code
    that tells unrun from failed (pick one, document it in the exit table).
- **`integration.sh` warm fan-out.** The roster (after `--diff` slicing) is split into `JOBS`
  slices, balanced by count. A scenario whose file carries `## Isolated because: <reason>` never
  goes warm and always runs cold; the reason must be non-empty or it exits 2 naming the file. Each
  slice runs through `scenario.sh --suite`. Every unrun scenario then runs cold through today's
  path.
  - **The #34 rerun still applies**, and it reruns COLD. A scenario that failed warm and passes cold
    prints `  WARM-ONLY  <name> — failed warm, passed cold: it leans on process state; mark it
    "## Isolated because:" or fix its reset`, and counts green. It is kept distinct from FLAKE and
    counted in the verdict line (`N passed (K flaky, W warm-only)`).
  - **`--no-rerun` in warm mode** leaves a warm failure red.
  - **Census (rule 4).** The verdict line reports how many ran warm, how many cold, and how many
    were handed back, and the counts must sum to the roster. A mismatch is a FAIL naming the
    missing scenarios, never a PASS over fewer.
- **Measurement.** The run prints the wall-clock split (warm workers vs cold remainder). The
  before/after comparison is the consumer's, from its own ledger. Name it under NOT verified.
- Minor bump: a new mode, flags, env vars, output lines and a documented contract.

## Ship criterion

- `scenario.sh --self-test` over a stub godot that honours the contract:
  - three scenarios become three reports and three verdicts;
  - an engine ERROR between B's START and B's verdict fails B only;
  - a stub that crashes during B hands back B and C with WARM-ABORT;
  - a stub that stalls is killed at the per-scenario bound.
- `integration.sh --self-test`:
  - warm mode sums its census;
  - an `## Isolated because:` scenario runs cold, and an empty reason exits 2;
  - handed-back scenarios run cold;
  - failed warm and passed cold prints WARM-ONLY and counts green;
  - with `GDK_INTEGRATION_WARM` unset, the recorded stub argv matches today's.
- `make pyunit` green. The `tests/test_runners_installable.py` corpus test covers the installed
  copies.

## Proof budget

  cases: ~10 across the two self-test corpora (stub godot, temp trees)
  tier: the runners' own self-tests
  lands in: src/godot_devkit/godot/installables/scenario.sh, integration.sh
  what already covers this: the cold-path cases; they must still pass unchanged
