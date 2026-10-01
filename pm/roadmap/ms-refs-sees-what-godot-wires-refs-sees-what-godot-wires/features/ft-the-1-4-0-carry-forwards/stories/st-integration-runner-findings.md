---
id: st-integration-runner-findings
kind: story
feature: ft-the-1-4-0-carry-forwards
milestone: "ms-refs-sees-what-godot-wires"
name: the integration runner findings
status: building
owner:
depends_on: []
changelog:
---

# the integration runner findings

The nine carry-forwards that live in `installables/integration.sh` (+ `gdk_runners.sh`), each
named by its review (`docs/reviews/2026-09-29-1.4.0-<review>.md`) and its line on 19ce2b0.

| row | where now | fix (decided) |
|---|---|---|
| milestone m3 | integration.sh:1707-1710 | a repair exit 2 passes through as exit 2; other non-zero stays 1 |
| diff m4 | :636 `[ -nt ]` | compare nanosecond mtimes; lift `mtime_ns` from import_cache.sh into integration.sh (installables do not source each other — copy it, same body) |
| diff m5 | :623 `ls-files` | `--cached --others --exclude-standard`, matching what `--diff` counts as touched |
| diff N7 | :1849 / :1904-1908 | a scenario still red after its rerun is summarised from `$n.alone.log`, not the sweep log |
| integ m1 | :1785-1794 | a WARM-ABORT worker's reason survives: print the tail of its log (the lines exit 4 drops today) |
| integ N1 | :1889 | drop the sum clause that is true by construction; keep `missing` |
| integ N2 | :1489 `--cold` | keep consuming it (a no-op when WARM is unset is right); document that in `--help` |
| integ N3 | :349-358 awk | a near-miss `isolated because:` spelling (one `#`, other case) is REFUSED with exit 2 naming the line, never run warm in silence |
| runners N5 | gdk_runners.sh:955-956, integration.sh:651, :661-662 | `unset $(git rev-parse --local-env-vars)` (and the `env -u` form from the same list) in all three places |

## Acceptance criteria

1. Each row's defect, introduced in its runner's `--self-test` corpus, is caught: one new or
   amended self-test case per row whose behaviour changed (N1/N2 are wording — no case).
2. `bash src/godot_devkit/godot/installables/integration.sh --self-test` and
   `… gdk_runners.sh --self-test` pass, with the case count up by the cases added.
3. The installed copies stay byte-identical to the installables (`make pyunit` covers the
   install prefix; `tests/test_runners_installable.py`).

## How this is proven

| criterion | tier | the case that proves it | existing? |
|---|---|---|---|
| 1–2 | shell | each runner's own `--self-test` corpus | amend |
| 3 | unit | tests/test_runners_installable.py | yes |

## Out of scope

`capture.sh`, `scenario.sh`, `import_cache.sh`, `unit.sh` (other lanes). No engine boot: the
self-tests stub Godot. CHANGELOG: report the sentence.
