---
id: 0.20.0/init-verb/init-on-a-blank-project
feature: 0.20.0/init-verb
milestone: "0.20.0"
name: godot-devkit init writes every installable in order on an empty Godot 4 project
status: todo
owner:
depends_on: []
---

# godot-devkit init writes every installable in order on an empty Godot 4 project

## Goal
`godot-devkit init` composes `pm init` + the `install-*` verbs + the two new files (`devkit.toml` template, two-line `Makefile`) + `.gitignore` entries + a `CLAUDE.md` skeleton, idempotent, `--force`/`--diff` like the installers.
## Verification
`make test` on an empty fixture dir: the written file set is exactly the documented list; a second run writes nothing; `--diff` after a hand edit names the file.
## Commit prefix
`feat(0.20.0/init-verb/S1):`
## Size
m
