---
id: 0.20.0/init-verb/init-on-a-blank-project
feature: 0.20.0/init-verb
milestone: "0.20.0"
name: godot-devkit init writes every installable in order on an empty Godot 4 project
status: review
owner: developer
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

## Done

done: c7e58e3 — `godot-devkit init` composes `pm init` + the four `install-*`
verbs in order and writes the three files nothing else wrote: the `devkit.toml`
template (every gate section, all commented at the stock default, so the file
is inert on arrival), the two-line `Makefile` with the pin substituted, and the
`CLAUDE.md` skeleton. Plus the four run-artifact `.gitignore` entries (appended,
never rewritten — the one merge in the package) and a real `setup-hooks.sh` run.

OWNERSHIP is the shape: installed files are devkit-owned and `--force`
overwrites them; devkit.toml / Makefile / CLAUDE.md / the PM tree are the
project's from the first write, so a differing seed is REPORTED, not refused.
Refusal matrix: no `project.godot`, no git repo, unknown flag, a seed
destination that is a directory — each exit 2 (or 1) with a census proving
nothing was written. 24 cases.

DEVIATION — two adjacent fixes the skeleton's own ship criterion required,
each with a test watched failing at HEAD: `check doc` now resolves the Makefile
INCLUDE chain (a two-line consumer Makefile made every `make <target>` claim in
every doc read as dead), and `doctor.sh` has three GUT states instead of two
(no `addons/gut/` at all is a fresh project → warn; the directory present with
the entry point missing → still FAIL). Without the second, `make doctor` was
un-greenable on a just-init'd project. `install.main` grew `next_step=False` so
the composition does not print four paragraphs asking for work it just did.
