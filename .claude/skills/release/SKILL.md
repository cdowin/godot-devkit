---
name: release
description: Cut a godot-devkit release — verify, bump the version everywhere it lives, update the CHANGELOG, tag, push, and remind about consumer pins. Use whenever changes are ready to ship to consumers.
---

# Release protocol

Preconditions — refuse to proceed if any fail:
1. Working tree clean, on `main`, up to date with `origin/main`.
2. `godot-devkit task verify` green — the full gate, which is `make milestone`: every check in this repo's `[checks] all` roster, the suite on every claimed interpreter, and the consumer smoke. This is the same command CI runs, so a green release is green for the same reason CI is.
3. The judgment half of `/consumer-smoke` (negative probes for any gate whose scoping changed, and the config-equivalence pass) — `make smoke` covers the census half and the skill says which is which.
4. The code-reviewer agent has reviewed the diff since the last tag with a RELEASE-SAFE verdict (full review for a minor/major).
5. `godot-devkit check all` and `godot-devkit check pm` both exit 0 **in this repo**. This package self-hosts: a release cut from a tree its own gates fail is the one release nobody should trust.
6. The release's notes already exist: `CHANGELOG.md` carries an `## Unreleased` section holding one bullet per consumer-visible change, written as the work landed. If it is thin, the notes were not written as the work landed — write them now, from the diff since the last tag, before anything else in this list runs.

Pick the bump per CLAUDE.md rule 6 (patch/minor/major — output-line-shape changes are minor at least; anything a consumer must edit for is major).

Steps (X.Y.Z = the new version):
1. Edit `src/godot_devkit/__init__.py` `__version__` AND `pyproject.toml` `version` — same value, same commit, no exceptions.
2. **Close the milestone — before the render, not after.** `pm feature review` / `pm feature done <fid> --review-record <path>` for each feature first (point it at the feature's `decisions.md`, not at its `review.md` — the close verb refuses the transient slot and says so) (`pm milestone done X.Y.Z` refuses while any is live), and promote anything durable out of each `review.md` into `decisions.md` before deleting it (D11 fails a `done` grain that still has one). `pm milestone done X.Y.Z` **stamps `actual_date:`** with today's ISO date — close is the moment a milestone acquires one, and a date reconstructed later is a guess. `check pm` at this point is the release gate: D11 on a surviving `review.md`.
3. **Retitle** `CHANGELOG.md`'s `## Unreleased` section to `## vX.Y.Z — <the actual_date just stamped>`, and open a fresh empty `## Unreleased` above it. The file is hand-maintained end to end; the only mechanical part is that the heading names the tag it maps to. Then commit `release: vX.Y.Z — <one-line summary>`.
4. `git tag vX.Y.Z && git push origin main --tags`.
5. Prove the published artifact: `uvx --from "git+https://github.com/cdowin/godot-devkit@vX.Y.Z" godot-devkit --version` must print the new version (run with a cold cache if uv has the ref cached: `uv cache clean godot-devkit` first).
6. Report the consumer follow-up explicitly: each consumer bumps `DEVKIT_VERSION` in its Makefile (trail: `~/workspace/trail/Makefile`; nullbound: `~/workspace/nullbound/Makefile`), runs its gate set, commits the one-line diff. Do NOT edit consumer repos from this session unless the user asks.

After the release, open the next milestone so the notes have somewhere to go from the first commit: `godot-devkit pm new milestone <next> <name>` then `pm milestone ready|building <next>`. Bullets go into `## Unreleased` as work lands, which is the whole point — the v0.13.0 section ran ~250 lines because nobody wrote it incrementally.

Never: tag without the version-sync commit; force-move a published tag (a bad release gets a new patch version, not a rewritten tag); release with a RED or unrun consumer-smoke; tag a version whose `## Unreleased` section is empty.
