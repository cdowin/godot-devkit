# Changelog

## v0.3.0 — 2026-07-04

Post-review release — all findings from the full code-reviewer pass fixed:

- **CRITICAL fix**: `check repo-hygiene` CHECK 3 could never detect a dangling
  worktree (`git worktree prune -n -v` reports on stderr; the gate read
  stdout). Now parses `git worktree list --porcelain` `prunable` entries.
- **Fix**: an unresolvable `[repo_hygiene] mainline` no longer silently
  disables CHECK 4 — it is a CONFIG ERROR, exit 2.
- **Fix**: a malformed `devkit.toml` exits 2 with a clean message instead of
  a traceback at exit 1 (1 is reserved for findings).
- **Change (upgrade note)**: `check uid` CHECK 1 now censuses ALL tracked
  .tres/.tscn (addons/ exempt) instead of a `[uid] scan_dirs` allowlist — the
  config key is now `exclude_prefixes`; the PASS line reports the ref/file
  census. Attribute matching is order-independent (a reordered ext_resource
  ref is censused, not skipped).
- **Fix**: top-level `--help`/`help` exits 0.

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
