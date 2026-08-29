---
id: 0.14.0/self-hosting/own-gates-green
feature: 0.14.0/self-hosting
milestone: "0.14.0"
name: check all is green inside godot-devkit
status: wip
owner:
estimate:
depends_on: []
labels: []
---

# check all is green inside godot-devkit

Running `godot-devkit check all` at this repo's root exits 0, with no gate
weakened and every gate still firing on the fixture corpus the tests point it
at.

## Acceptance criteria

- The fixture tree is excluded by `exclude_prefixes` in `[uid]`/`[tres]`/
  `[props]`; the tests copy those fixtures into temp repos, so each gate still
  proves it fires.
- `[checks] all` names the gates that apply here; an unknown name is exit 2.
- A 0-file census says how many files it scanned OF how many tracked, so an
  empty repo and a census eaten by an exclude stop reading identically.

## Out of scope

Relaxing rule 4. A gate that scans nothing still fails; what changed is that it
now says which of the two reasons it was.
