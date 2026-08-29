---
id: 0.14.0/self-hosting/story-id-recursion
feature: 0.14.0/self-hosting
milestone: "0.14.0"
name: a nested story is addressable by id
status: done
owner:
estimate:
depends_on: []
labels: []
---

# a nested story is addressable by id

`pm story wip <id>` resolves a story anywhere under `stories/`, matching the
walk `check pm` already uses.

## Acceptance criteria

- `story_file` resolves through `story_files`/`grain_docs` — one definition of
  what a story is, two readers.
- A story at `stories/parked/s2.md` is both counted by the gate and moved by
  the verb.
- Two files claiming one id refuse rather than pick; an exact stem still beats
  an ordinal-prefixed sibling.

## Out of scope

Changing what `grain_docs` considers a grain. A `.md` with no frontmatter stays
a note parked beside the stories.
