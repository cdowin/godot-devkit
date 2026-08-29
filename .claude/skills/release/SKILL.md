---
name: release
description: Cut a godot-devkit release — verify, bump the version everywhere it lives, update the CHANGELOG, tag, push, and remind about consumer pins. Use whenever changes are ready to ship to consumers.
---

# Release protocol

Preconditions — refuse to proceed if any fail:
1. Working tree clean, on `main`, up to date with `origin/main`.
2. Parse gate green: `python3 -c "import ast,pathlib; [ast.parse(p.read_text()) for p in pathlib.Path('src').rglob('*.py')]"`.
3. `/consumer-smoke` green against at least the trail checkout.
4. The code-reviewer agent has reviewed the diff since the last tag with a RELEASE-SAFE verdict (full review for a minor/major).
5. `godot-devkit check all` and `godot-devkit check pm` both exit 0 **in this repo**. This package self-hosts: a release cut from a tree its own gates fail is the one release nobody should trust.
6. The release's notes already exist. `X.Y.Z` is a milestone id under `pm/roadmap/`, it is `building`, and its `changelog.md` holds an entry per consumer-visible change — appended with `godot-devkit pm changelog X.Y.Z --what … --evidence …`, never typed into a file. **D16 is this precondition as a gate**, so flipping the milestone `done` in step 4 fails on an empty or non-conforming log rather than shipping one. Nothing is written by hand at release time; if the log is thin, the notes were not written as the work landed, and they get written now through the verb.

Pick the bump per CLAUDE.md rule 6 (patch/minor/major — output-line-shape changes are minor at least; anything a consumer must edit for is major).

Steps (X.Y.Z = the new version):
1. Edit `src/godot_devkit/__init__.py` `__version__` AND `pyproject.toml` `version` — same value, same commit, no exceptions.
2. **Render** the CHANGELOG; never write a section into it:
   ```
   godot-devkit pm changelog --render > /tmp/rendered.md
   ```
   Then rebuild `CHANGELOG.md` as that render, followed by the `## Below this line: frozen, not rendered` boundary note and the frozen historical text beneath it, byte-identical. Everything above the boundary is generated — a hand edit there is overwritten by the next render and is the drift this step exists to remove. Verify: re-run the render and diff it against the top of the committed file; they must be identical.
3. Close the milestone, then commit. `pm feature review` / `pm feature done <fid> --review-record <path>` for each feature first — `pm milestone done X.Y.Z` refuses while any is live — and promote anything durable out of each `review.md` into `decisions.md` before deleting it (D11 fails a `done` grain that still has one). Then commit `release: vX.Y.Z — <one-line summary>`. `check pm` at this point is the release gate: D16 on an empty log, D11 on a surviving `review.md`, D18 on a raw decision trail that was never collapsed to pointers.
4. `git tag vX.Y.Z && git push origin main --tags`.
5. Prove the published artifact: `uvx --from "git+https://github.com/cdowin/godot-devkit@vX.Y.Z" godot-devkit --version` must print the new version (run with a cold cache if uv has the ref cached: `uv cache clean godot-devkit` first).
6. Report the consumer follow-up explicitly: each consumer bumps `DEVKIT_VERSION` in its Makefile (trail: `~/workspace/trail/Makefile`; nullbound: `~/workspace/nullbound/Makefile`), runs its gate set, commits the one-line diff. Do NOT edit consumer repos from this session unless the user asks.

After the release, open the next milestone so the notes have somewhere to go from the first commit: `godot-devkit pm new milestone <next> <name>` then `pm milestone ready|building <next>`. Entries are appended as work lands, which is the whole point — the v0.13.0 section ran ~250 lines because nobody wrote it incrementally.

Never: tag without the version-sync commit; force-move a published tag (a bad release gets a new patch version, not a rewritten tag); release with a RED or unrun consumer-smoke; hand-write a CHANGELOG section above the frozen boundary.
