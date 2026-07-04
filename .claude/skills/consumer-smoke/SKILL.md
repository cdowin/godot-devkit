---
name: consumer-smoke
description: Run every godot-devkit subcommand against the live consumer checkouts (trail, nullbound) and verify censuses + pass/fail semantics. The behavior gate for this toolkit — run before any release and after touching a check's scoping.
---

# Consumer smoke

The consumers are the fixtures. For each available checkout (`~/workspace/trail`, `~/workspace/nullbound` — skip cleanly with a note if absent), run from INSIDE the consumer (tools resolve the repo from cwd), invoking the WORKING TREE build: `uvx --from ~/workspace/godot-devkit godot-devkit …` — never the published tag (that would smoke-test the previous release).

1. **Introspection**: `scene` on a real .tscn; `scene-diff <file> --git HEAD` (expect "no structural differences" on a clean tree); `refs <a-known-class_name>`; `autoloads` (expect the census header count to equal `grep -c '=' project.godot`'s [autoload] section entries); `orphans` may be slow — run it last, `--tests` off.
2. **Gates**: `check uid`, `check tres`, `check doc`, `check shell` — all must PASS on a clean consumer, AND their printed censuses must match an independent count (e.g. `check tres`'s file count vs `git ls-files '*.tres' '*.tscn' | grep -v ^addons/ | wc -l`). A PASS with a census mismatch is a FAIL of this smoke (false-PASS hazard).
3. **Negative probe** (any gate whose scoping changed): copy the consumer's tree shallowly to scratch (`git worktree` in the CONSUMER is forbidden — use `cp -R` of the few relevant dirs + `git init` scratch), introduce the drift class (e.g. strip a `uid=` from one ext_resource line), confirm the gate FAILS with the expected line shape.
4. **Config equivalence**: in the scratch copy, run once with no `devkit.toml` and once with a `devkit.toml` declaring the stock defaults — outputs must be identical.

Report a per-consumer table: subcommand → result + census vs independent count. Any mismatch, unexpected exit code, or traceback = smoke RED; name the offending tool and stop there.
