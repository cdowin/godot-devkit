# CLAUDE.md — godot-devkit

godot-devkit holds the few files a bare Godot 4 game needs and cannot get from the engine, under
`game/`, for a game to copy once and own. It asks a game for nothing: no install, pin, config or
copy to keep in step. When the engine already does a job, the job is not ours.

## Rules

- A file earns its place only if both games would lose something real without it, and the engine
  cannot do it. `README.md` says what each file is for, one line each; keep that table true.
- Never hack around what the engine does. Read the class reference for the installed version first.
- Public repo, MIT. Prose names a kind of project, never a studio repo.
- `README.md` stays under one page.

## How this repo runs

- `make check`: shellcheck over `game/tools/session-start.sh` and a dry run of `game/Makefile`. It
  runs no Godot. CI (`verify.yml`) runs the same.
- `check.gd` and `sheet.gd` are proven in a game: copy `game/` into one and run `make check` and
  `make sheet` there.
- No version and no release: a game copies the files at whatever commit it reads.
- Commit by path. Never force-push.
