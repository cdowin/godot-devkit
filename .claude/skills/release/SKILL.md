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

Pick the bump per CLAUDE.md rule 6 (patch/minor/major — output-line-shape changes are minor at least; anything a consumer must edit for is major).

Steps (X.Y.Z = the new version):
1. Edit `src/godot_devkit/__init__.py` `__version__` AND `pyproject.toml` `version` — same value, same commit, no exceptions.
2. Prepend a `## vX.Y.Z — <date>` section to CHANGELOG.md: one bullet per consumer-visible change; call out anything a consumer must do on upgrade.
3. Commit: `release: vX.Y.Z — <one-line summary>`.
4. `git tag vX.Y.Z && git push origin main --tags`.
5. Prove the published artifact: `uvx --from "git+https://github.com/cdowin/godot-devkit@vX.Y.Z" godot-devkit --version` must print the new version (run with a cold cache if uv has the ref cached: `uv cache clean godot-devkit` first).
6. Report the consumer follow-up explicitly: each consumer bumps `DEVKIT_VERSION` in its Makefile (trail: `~/workspace/trail/Makefile`; nullbound: `~/workspace/nullbound/Makefile`), runs its gate set, commits the one-line diff. Do NOT edit consumer repos from this session unless the user asks.

Never: tag without the version-sync commit; force-move a published tag (a bad release gets a new patch version, not a rewritten tag); release with a RED or unrun consumer-smoke.
