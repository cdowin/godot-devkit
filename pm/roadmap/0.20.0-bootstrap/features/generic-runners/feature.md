---
id: 0.20.0/generic-runners
milestone: "0.20.0"
name: The six Godot/GUT runners every consumer re-invents become installables
status: building
reviewed:
phase: 1
depends_on: ["0.19.0/install-runners"]
consumed_by: ["0.20.0/makefile-include", "0.20.0/init-verb"]
---

# The six Godot/GUT runners every consumer re-invents become installables

What it makes true: `install-runners` (0.19.0) carries every Godot/GUT runner a consumer needs —
`parse.sh`, `lint.sh`, `warnings.sh`, `unit.sh` (GUT), `scenario.sh`, `integration.sh`,
`capture.sh` — on the `gdk_*` library, so a project's `tools/dev/` holds only what is its own.
Reference: nullbound `tools/dev/checks/parse.sh|lint.sh|warnings.sh` + `tools/dev/runners/*.sh`
at `d3df6e5cb`; trail's `parse.sh|lint.sh` are the ancestors.

## Existing-construct audit

`gdk_runners.sh` + `import_cache.sh` (0.19.0) are the library and the first runner; these are the
next six on the same installable, not a new mechanism. Consumer-specific bits (nullbound's
`boot_to_hub` smoke scenario name, its report-quarantine paths) become documented `GDK_*`
variables with defaults, never branches on a project name.

## Ship criterion

Both consumers' Makefiles call the installed runners for parse/lint/warnings/unit/scenario/
integration/capture with byte-identical verdict lines before and after; their copies are deleted.
