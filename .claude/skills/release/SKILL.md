---
name: release
description: Cut a godot-devkit release — verify, bump the version everywhere it lives, update the CHANGELOG, tag, push, and remind about consumer pins. Use whenever changes are ready to ship to consumers.
---

# Release protocol

Preconditions — refuse to proceed if any fail:
1. Working tree clean, on the MILESTONE BRANCH with `origin/main` merged in — never on `main`: `main` is merge-commit-only at close ([`CLAUDE.md`](../../../CLAUDE.md)), and the self-hosted `tools/hooks/pre-push` blocks a direct push to it, so a release is a PR merge and a tag, not a push of `main`.
2. **The reviewer has run on the FINAL tree and every finding it raised is landed or explicitly deferred.** A `code-reviewer` pass over the diff since the last tag, verdict RELEASE-SAFE (full review for a minor/major). This comes BEFORE the gate, not after it — see § Why the gate is last.
3. For any gate whose SCOPING changed: a negative probe (introduce the drift class into a scratch copy of a `tests/fixtures/` repo, confirm the gate FAILS with the expected line shape) plus the config-equivalence pass (no `devkit.toml` vs one declaring the stock defaults — byte-identical output). This is the judgment half `make milestone` cannot mechanize; it stays in scratch and never reaches outside this checkout.
4. The code-reviewer agent has reviewed the diff since the last tag with a RELEASE-SAFE verdict (full review for a minor/major).
5. `godot-devkit check all` and `godot-devkit check pm` both exit 0 **in this repo**. This package self-hosts: a release cut from a tree its own gates fail is the one release nobody should trust.
6. The release's notes already exist: `CHANGELOG.md` carries an `## Unreleased` section holding one bullet per consumer-visible change, written as the work landed. If it is thin, the notes were not written as the work landed — write them now, from the diff since the last tag, before anything else in this list runs.

Pick the bump per CLAUDE.md rule 6 (patch/minor/major — output-line-shape changes are minor at least; anything a consumer must edit for is major).

Steps (X.Y.Z = the new version):
1. Edit `src/godot_devkit/__init__.py` `__version__` AND `pyproject.toml` `version` — same value, same commit, no exceptions.
2. Bump the README's two pin sites to `vX.Y.Z` in the same commit: the `uvx --from "…@vX.Y.Z"` install example under "## Install" (and its `# godot-devkit X.Y.Z` trailing comment), and the `DEVKIT_VERSION := vX.Y.Z` line in the Makefile snippet under "## Wiring it into your project". These are the strings consumers copy-paste; a stale pin there ships an old release to every new adopter.
3. **Review, land the fixes, THEN run the gate — in that order.** `pm feature reviewing <fid>` for each feature as its work lands, then `pm feature done <fid> --review-record <path>` once its review is closed — point it at the feature's `decisions.md`, which is where a review's durable half belongs. Then `pm milestone reviewing X.Y.Z`, which silences D6 and unblocks the gate.

   **Now land every fix the review raised.** Only once the tree is final: `pm milestone accepted X.Y.Z` and run `make milestone`. **It is the LAST thing that happens before the milestone is called done** — the full regression suite on every claimed interpreter, answering for the bytes that will actually ship. Nothing has closed yet and nothing is rendered, so `accepted` is still a decision the gate informs rather than one it rubber-stamps.

   ### Why the gate is last

   Chris, 2026-09-04, watching this protocol get it wrong on its own release: *"We just did a make milestone with the full test/regression suite and then did a reviewer which is now asking for fixes. The make milestone with the full test suite is the LAST thing before saying 'yeah, this is done'."*

   A gate that runs before the review answers for a tree nobody is going to ship. Every fix landed afterwards invalidates it, so the expensive run buys nothing and — worse — it reads as readiness. On 0.24.0 it was run twice, at 3:00 and 3:17, and both were void before the tag.

   **This is the third instance of one mistake in this package: the release gate coupled to, or ordered against, the wrong thing.** The first was `bugs/the-release-gate-cannot-run-before-the-close-it-gates` — D6 refused a `building` milestone whose features were all done, so the gate demanded the ship decision it exists to inform. The second was `make smoke` making two consumer checkouts a precondition for the tag (CLAUDE.md rule 8, and `bugs/consumer-names-and-provenance-in-code`). This is the same error one layer up. **When a gate and a judgement both bear on the same decision, the judgement runs first and the gate answers for its result.**

4. **Package — the notes get written at `packaging`, not after `done`.** `pm milestone packaging X.Y.Z`, then **retitle** `CHANGELOG.md`'s `## Unreleased` section to `## vX.Y.Z — <today's ISO date>`, and open a fresh empty `## Unreleased` above it. The file is hand-maintained end to end; the only mechanical part is that the heading names the tag it maps to. Then commit `release: vX.Y.Z — <one-line summary>`.
5. **`pm milestone done X.Y.Z` — the LAST PM action, and the first one that is true when it is written.** Everything inside the tree's authority is finished: changelog written, every review closed, every finding landed, gates green. `done` does not mean shipped and cannot — this flip is itself a commit that has not shipped at the moment it is written. Branch, PR, merge and tag are git events, outside the tree, and they come next.
6. Push the branch, open (or update) the PR to `main`, CI green (`verify.yml` is `make milestone`), merge it as a merge commit. Then on `main` at that merge commit: `git tag vX.Y.Z && git push origin vX.Y.Z` — the TAG ref only. A `git push origin main` is exactly what the pre-push hook exists to block, and the merge already put the commits there.
7. Prove the published artifact: `uvx --from "git+https://github.com/cdowin/godot-devkit@vX.Y.Z" godot-devkit --version` must print the new version (run with a cold cache if uv has the ref cached: `uv cache clean godot-devkit` first).
8. Report the consumer follow-up explicitly, as INSTRUCTIONS for whoever maintains a consuming repo — never as work this session does, and never naming a particular repo. A consumer bumps `DEVKIT_VERSION` in its Makefile, runs `install-* --diff` for what the release shipped, and then decides PER FILE: `--force` is whole-set and has no per-file option, so it replaces every file that verb writes, including ones the consumer deliberately edited (measured on real adoptions: an installed `verify.yml` grown into a two-job sharded workflow 177 lines from the installable; an `auto-tag.yml` carrying a path filter the installable does not). `--force` for a file never touched; hand-apply the diff for one that was. Re-run `pm init` once (a `.gitattributes` line a release added reaches an existing tree only that way), run the gate set, commit the diff. **Integration is proven in the consumer's repo by the consumer's gates** (hard rule 8) — it is not a precondition of this tag, and do NOT edit a consumer repo from this session.

After the release, open the next milestone so the notes have somewhere to go from the first commit: `godot-devkit pm new milestone <next> <name>` then `pm milestone ready|building <next>`. Bullets go into `## Unreleased` as work lands, which is the whole point — the v0.13.0 section ran ~250 lines because nobody wrote it incrementally.

Never: tag without the version-sync commit; force-move a published tag (a bad release gets a new patch version, not a rewritten tag); make a tag wait on another repo's working state; tag a version whose `## Unreleased` section is empty; flip `done` before the changelog is written and the findings are landed — that is the inversion the lifecycle exists to fix.
