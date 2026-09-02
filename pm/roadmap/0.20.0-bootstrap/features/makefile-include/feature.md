---
id: 0.20.0/makefile-include
milestone: "0.20.0"
name: Makefile.devkit — one standard target set, projects extend by config
status: building
reviewed:
phase: 2
depends_on: ["0.20.0/generic-runners", "0.20.0/generic-scans"]
consumed_by: ["0.20.0/init-verb"]
---

# Makefile.devkit — one standard target set, projects extend by config

What it makes true: `installables/Makefile.devkit` — devkit-owned, overwritten on `--force` —
carries the standard target set: `doctor`, `parse`, `lint`, `warnings`, `unit`, `integration`,
`scenario`, `smoke`, `capture`, `import-cache`, `refs`, `scene`, `scene-diff`, `orphans`,
`autoloads`, `pm`, `pm-scan`, `check`, `precommit`, `milestone`, `help`, plus the quiet-by-default
convention (one verdict line naming `.gate-reports/<gate>.log`; `VERBOSE=1` streams). A project's
`Makefile` is `include Makefile.devkit` + its own targets. Extra gates (nullbound's 19 scans) join
`check` through `[gates] extra = [...]` in `devkit.toml`, read by the include — extension by config,
never by fork.

## Existing-construct audit

The pinned `DEVKIT := uvx --from "git+…@$(DEVKIT_VERSION)" godot-devkit` line, the `tools/dev/`
delegation, and the `check`/`precommit`/`milestone` layering are already identical in both
consumers — this lifts them, it does not design them. `Makefile.devkit` is the file the two
Makefiles were already copying from each other.

## Ship criterion

Nullbound's Makefile drops from 59 targets to the include + its own; trail's likewise; `make
help` in both prints the standard set plus the project's; `make precommit` green in both.
