# HQ note for #193 (working note for the lead; delete before landing)

Read from `origin/main` of each repo on 2026-11-14. Each line: where, what it says now, what changes.

## HQ (cdowin/signalandecho)

- `.claude/skills/onboard-project/SKILL.md` step 6 and its description: "Add the dev dependency ...
  `install-gates`, `install-runners` and `install-skills` ... `make check` includes `Makefile.gates`."
  Becomes: copy `godot-devkit/game/.` into the repo, wire `tools/session-start.sh` and the deny list
  in `.claude/settings.json` (README "Cloud sessions"), set `GODOT_PATCH` in `check.yml` (MAJOR.MINOR is `project.godot`'s `config/features`).
- `.claude/skills/branch-audit/SKILL.md` line 27 (wiki version pin for `godot-devkit`) and line 29
  ("Godot code without `Makefile.gates`, the devkit dependency and the devkit skills"): drop both;
  at most check that a Godot repo has `tools/check.gd` and a CI job running `make check`.
- `bin/repo-web-audit` (`GODOT_EXEMPT`, the `godot-devkit` pyproject test at lines 65-70, the
  FAIL at 152-158) and `tests/repo-web-audit/run.sh` line 13 (`godot-devkit==4.8.0`): same change.
- `.claude/skills/work-intake/SKILL.md` line 19 ("adopts godot-devkit first (#253)"): becomes
  "copies godot-devkit's `game/` files". Line 29 lists godot-devkit as a shared system: still true.
- `.claude/skills/game-kickoff/SKILL.md` line 63: ".tres, checked by the devkit content validator".
  No such validator exists now: `make check` loads every `.tres`.
- `.claude/skills/retro/SKILL.md` line 20: "`cdowin/godot-devkit`: Godot gates and lint." Becomes
  "the files a bare Godot game copies once".
- `.claude/skills/ci-gate/SKILL.md` line 32 and README lines 207-247 name `bin/devkit`. That is the
  studio image runner (`devkit/Containerfile`, `studio-devkit:<arch>`), not godot-devkit: it runs a
  repo's command in the image CI uses. It needs no change for #193; only the shared word "devkit"
  is confusing. `devkit/steps/godot` puts Godot at `/opt/godot/<version>/godot`, which the new
  `check.yml` still uses when present.
- `README.md` line 22 ("Shared game contracts live ... in `godot-devkit`, tested once"), line 172
  ("Godot tooling, skills and the gate framework for every repo that ships Godot code"), line 189
  ("godot-devkit's `release.yml` is the Godot build mechanism"; it is gone, each game owns its own
  release workflow), line 193 ("godot-devkit gates serve every repo that ships Godot code"),
  lines 302 and 310 (godot-devkit's nightly at 08:00; the nightly workflow is gone).
- `runner/repos` line 9 ("studio-design-system's check runs Chrome and the godot-devkit gates"):
  true until the design system moves off `Makefile.gates`.
- The workstation `bin/` (`~/workspace/bin`) has no `devkit` wrapper; the issue's "workstation
  `bin/devkit` wrapper" is HQ's `bin/devkit` above, which is not godot-devkit.

## Other repos and wikis

- `cdowin/studio-design-system` `main`: `Makefile` and `Makefile.gates` are the installed gate
  framework, and `CLAUDE.md` line 34 sends Godot work to the devkit skills `godot-native-first` and
  `godot-ui`, which this branch deletes. `.claude/reference/layout-system.md` line 39 needs the
  fit sweep, also deleted. Its own branch, like the games'.
- `cdowin/nullbound` `4159-lean-native`: `.claude/settings.json` still enables the
  `godot-devkit@godot-devkit` plugin at `v4.4.0`; `assets/world/sky/depth/_authoring/build_city_depth.py`
  line 518 and `build_sewer_depth.py` line 224 import `godot_devkit.godot.index.uid_codec`. Both
  break once nothing installs the package. `production_art_brief.txt` line 32 names
  `make/tools/dev/devkit`.
- `cdowin/trail` and `cdowin/nullbound` `main`: about 20 to 30 files each name devkit; both
  integration branches remove them.
- `cdowin/rainbow-riders` `main`: `design/rebuild/carried-over.md`, `data.md`, `layout.md` name it.
- Wikis that describe the old devkit: `godot-devkit.wiki` (10 pages: install, pin, config, the eight
  gates, migrations; replace with one page or delete), `signalandecho.wiki` (6 pages: Repo-Map,
  Glossary, Game-Visuals, Home, Studio-status, The-Rhythm), `trail.wiki` (11), `nullbound.wiki` (10),
  `studio-design-system.wiki` (Home), `agentic-sdlc.wiki` (one migration page).

## Open issues in cdowin/godot-devkit made moot

All of them except #193:

- #192 Skills teach retired habits: wireframes, captures, override exceptions, a missing scene
- #181 Install and update a pinned Godot add-on from a tag
- #180 Gate: no Color literals in UI code or hand-made StyleBox colors
- #175 Game framework gates: content validator, journey runner, fit sweep over size classes
- #171 ui-fit: fully elided labels and unowned runtime nodes are never reported
- #169 ui-fit: capture is unreadable for tall scenes and marks no finding
- #150 canonicalize: two sub_resource ShaderMaterials in one .tscn get mixed shader_parameter defaults
- #148 check uid: judge the spelling of .uid sidecars
- #140 release.yml gate checkout is shallow, so ratchet scans fail
- #139 Shader traps and a headed render check for Godot 4 games (`check.gd` loads every shader)
- #120 A machine-wide Godot lane cap: a counting semaphore every make target takes (workstation `bin/heavy`)
- #115 check patterns: rule errors name the row
- #114 check patterns: tests for multi-id opt-out and glob_re
- #113 check patterns: lint-allow works outside a comment
- #110 Release calls the shared kit-released workflow
