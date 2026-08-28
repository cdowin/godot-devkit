"""pm — filesystem-backed milestone/feature/story/bug tracking.

The PM tree is markdown with YAML frontmatter under `pm/roadmap/`; a grain's
`status:` is the only field this package writes. Two halves that MUST agree:

    model.py   the invariants — vocabularies, transition graphs, id<->path
               resolution, frontmatter IO, the review-record definition, the
               drift predicates
    cli.py     the write side: precondition-checked transitions, scaffolding,
               reporting, prune

...plus `godot_devkit.repo.checks.pm`, the read side (the drift gate), which imports
the SAME predicates from model.py. One definition, two readers — that invariant
is why this ships as one package instead of a CLI and a separate linter.

Engine-agnostic: nothing here parses a scene, and the package works on any repo
laid out to the schema. It lives in godot-devkit because that is the pinned-tag
channel its consumers already share.
"""
