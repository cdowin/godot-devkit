# godot-devkit

The few files a bare Godot 4 game needs and cannot get from the engine. Copy them into your project
once; then they are yours. Nothing to install, pin, configure or keep in step with this repo.

```sh
cp -R godot-devkit/game/. my-game/      # Makefile, tools/, .github/workflows/check.yml
```

The engine does the rest: it imports, parses, compiles, resolves uids and reports every error at
load. Edit `.tscn` and `.tres` as text or in the editor; the proof is that they load.

## What you copy, and what you lose without it

| File | Without it |
|---|---|
| `Makefile` (`import`, `check`, `sheet`, `script`, `play`, `editor`) | Every headless run reads and writes the real `user://` of whoever is at the machine: the engine keeps it under `HOME` and has no flag for a per-run one. The Makefile gives each run a throwaway `HOME`, and `make script S=<path>` runs a scratch script that way, so an agent denied direct `godot` can still prove something at runtime. |
| `tools/check.gd` | `godot --import` and `--check-only` parse files but run no scene. Without it a broken `_ready`, a missing `%Name`, a script or shader that does not compile, or an `ext_resource` whose path is not the file its uid names (the engine loads the uid's file and says nothing) reaches a player. A scene whose root's `_get_configuration_warnings()` says it needs a host is a part: judged inside each scene that instances it, not alone. |
| `tools/sheet.gd` | No way to see every screen at once without clicking through the game. It draws each folder of scenes onto one page, and fails on a scene that errors while drawn. |
| `.github/workflows/check.yml` | No `make check` on each push. The engine version is `config/features` in `project.godot` plus `GODOT_PATCH` here. |
| `tools/session-start.sh` | A Claude Code cloud session has no Godot binary, so it cannot run `make check`. |

## Cloud sessions

A cloud container starts with no Godot. `tools/session-start.sh` installs the version that
`project.godot` and the workflow's `GODOT_PATCH` name into `/usr/local/bin/godot`, imports the
project, and fetches `origin/main` when the clone lacks it. It needs `curl`, `unzip`, `make`, a
network path to github.com and write access to `/usr/local/bin`, all present in a Claude Code
cloud container. It does nothing on a local machine. Wire it, and keep typed Godot runs off real
user data, in `.claude/settings.json`:

```json
"permissions": { "deny": ["Bash(godot:*)", "Bash(godot4:*)", "Bash(*/godot:*)"] },
"hooks": { "SessionStart": [{ "hooks": [{ "type": "command",
  "command": "bash \"$CLAUDE_PROJECT_DIR/tools/session-start.sh\"" }] }] }
```

## Make it yours

- `make sheet DIRS="ui game/hud"` draws chosen folders; set the default `DIRS` in your copy.
  Add `.sheet/` to `.gitignore`.
- `check.gd` checks `gd`, `tscn`, `tres`, `gdshader`, `gdshaderinc` and `json`. An addon with its own resource
  type (a dialogue timeline, say) gets its own line in your copy.
- `check.gd` and `sheet.gd` skip `addons/` and any folder holding a `.gdignore`.
- Add your own targets (`pot`, `playtest`) at the end of the `Makefile`, below the line that says
  so. The file is yours.

## What is gone, and why

The Python CLI, scene parser and scene-edit tool, uid and canonicalize checkers, lints, pattern
rules, scans, pin and version checks, the runner and gate frameworks, GUT wiring, fit sweeps,
renders, installers, the `godot-devkit.toml` config, the release workflow and the agent skills.
The engine reports what they checked when a file loads; the rest asked every game to install, pin
and keep vendored copies in step. A game's release workflow is its own (`godot --export-release`).
The last release with them is v5.0.0.

MIT. See [LICENSE](LICENSE).
