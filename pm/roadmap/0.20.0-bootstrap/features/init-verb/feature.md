---
id: 0.20.0/init-verb
milestone: "0.20.0"
name: godot-devkit init — a blank Godot 4 project gets everything in one command
status: planning
reviewed:
phase: 3
depends_on: ["0.20.0/makefile-include", "0.20.0/ci-set"]
consumed_by: []
---

# godot-devkit init — a blank Godot 4 project gets everything in one command

What it makes true: `godot-devkit init` on an empty Godot 4 project writes, in order:
`devkit.toml` (from a template with every `[section]` the gates read), the PM tree (`pm init`),
`Makefile` (two lines) + `Makefile.devkit`, the runners, the hooks + `setup-hooks.sh` run, the
agents, the skills, the CI set, `.gitignore` entries (`.gate-reports/`, the sandbox dir), and a
`CLAUDE.md` skeleton pointing at starter rules the project owns after the write. Idempotent:
re-running fills missing slots and reports drift, never overwrites without `--force`.

## Existing-construct audit

`pm init` and the four `install-*` verbs are the pieces; `init` is their ordered composition plus
the two files nothing writes today (`devkit.toml`, `Makefile`). It calls them; it does not
re-implement them.

## Ship criterion

The fresh-game test: empty project → `init` → `make doctor` + `make precommit` green, zero hand
edits (asserted in the devkit's CI as the written file set + `make -n` of every standard target;
the real boot is `consumer-smoke`).
