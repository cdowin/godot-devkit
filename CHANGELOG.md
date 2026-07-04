# Changelog

## v0.2.0 — 2026-07-04

- Converted from a vendored file-set to a real Python package: one
  `godot-devkit` entry point with subcommands (`scene`, `scene-diff`, `refs`,
  `orphans`, `autoloads`, `check <gate>`).
- Ported the four bash gates (uid, tres-format, repo-hygiene, shellcheck
  wrapper) to Python — cross-platform, config-driven.
- Per-project variation moved out of file edits into `devkit.toml` at the
  consuming repo root (`[autoloads]`, `[doc]`, `[uid]`, `[tres]`,
  `[repo_hygiene]`, `[shell]`).
- Retired `sync.sh` + the vendored-manifest model; consumers now pin a git
  tag: `uvx --from git+https://github.com/cdowin/godot-devkit@v0.2.0 godot-devkit …`.

## v0.1.0 — 2026-07-04

- Initial extraction from two shipping Godot 4.6 projects: introspect suite
  (shared .tscn/.tres parser, scene summary, structural scene-diff, refs,
  orphans, autoload census) + five static gates, consumed by vendored sync
  with a drift manifest.
