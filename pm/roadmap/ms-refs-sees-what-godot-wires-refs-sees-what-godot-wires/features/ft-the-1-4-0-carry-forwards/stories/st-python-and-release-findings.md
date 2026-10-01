---
id: st-python-and-release-findings
kind: story
feature: ft-the-1-4-0-carry-forwards
milestone: "ms-refs-sees-what-godot-wires"
name: the python and release findings
status: done
owner:
depends_on: []
changelog:
---

# the python and release findings

The small carry-forwards outside the big runners, each named by its review
(`docs/reviews/2026-09-29-1.4.0-<review>.md`) and its line on 19ce2b0.

| row | where now | fix (decided) |
|---|---|---|
| milestone m2 | godot/checks/rng.py:108-120 | an outer `func randf()` must not suppress a bare `randf()` inside `class Inner:` — shadowing is scoped per class body (indentation), both directions |
| read-verbs N1 | cli.py:96 | point tests/test_check_uid.py:374 and tests/test_tres_canonical.py:183 at `godot.checks.roster`; delete the "Re-exported" comment (touch only that line of cli.py) |
| read-verbs N2 | godot/checks/roster.py:41 | two blank lines before `def all_roster` |
| milestone N3 | installables/ci-godot-toolchain.yml:24-25 | correct the comment: CI syncs the lock whenever uv.lock names the kit, even when a Makefile pin wins |
| wheel m3 | .github/workflows/release.yml:125-143 | a re-dispatched tag whose release already carries a wheel with the same sha256 skips build/attach and still runs `index`; a different hash still refuses. Header claim at :16-18 made true |
| wheel n1 | release.yml:42-45 | per-job permissions: release `contents: write`, index `contents: read`, deploy `pages: write` + `id-token: write` |
| wheel n2 | tools/release/build_index.py:97-102 | drop `--project`; the test that passed it calls `render(project=)` |
| wheel n3 | build_index.py:67-82 | refuse an asset whose filename is not this project's; emit `data-requires-python` from pyproject's `requires-python` |
| wheel n4 | godot/install.py:213 | REJECTED, no change: an installed package's `__version__` is a released one; only a dev checkout differs. Record it in the report |
| runners N6 | installables/unit.sh:172-173 | print the factor actually applied, not the rounded load ratio |
| runners N7 | unit.sh:421-423 | log the timeout bound after `gdk_gate_log` exists, so the transcript records it |
| (feature) | pyproject.toml:8 | `description` says what ships: scene introspection, surgical scene/tile/autoload edits, the eight Godot gates, the runners — no doc/shell/repo-hygiene/PM |

## Acceptance criteria

1. rng: an inner-class shadow and an outer shadow each leave the other scope's bare draw flagged.
2. build_index: a foreign asset refuses; the index carries `data-requires-python`.
3. `unit.sh --self-test` passes with the N6/N7 behaviour covered.
4. `make pyunit` green. release.yml has no local proof: keep its edit minimal and report it as
   NOT verified until a tag runs it.

## How this is proven

| criterion | tier | the case that proves it | existing? |
|---|---|---|---|
| 1 | unit | tests/test_check_rng.py | amend |
| 2 | unit | tests/test_release_index.py | amend |
| 3 | shell | unit.sh's own `--self-test` | amend |

## Out of scope

`integration.sh`, `gdk_runners.sh`, `scenario.sh`, `import_cache.sh`, `capture.sh`; any other
cli.py line. CHANGELOG: report the sentence.
