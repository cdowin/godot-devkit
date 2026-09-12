---
id: ft-tres-canonical-respell-and-order
kind: feature
milestone: "1.1.0"
name: .tres value spelling and property order are canonicalized and gated
status: done
reviewed: docs/reviews/2026-09-12-1.1.0-ft-tres-canonical-respell-and-order.md
depends_on: []
consumed_by: []
changelog: check canonical and scene canonicalize --respell/--order gate and fix .tres float spelling, typed arrays and scripted property order (#11).
---

# .tres value spelling and property order are canonicalized and gated

GitHub issue #11. Only default elision is canonicalized and gated today (`check defaults` +
`scene canonicalize --elide-defaults`). Godot 4.6's `ResourceFormatSaverText` normalizes more, and
an editor SAVE of a resource re-spells it, so every save is churn in review. Measured on a consumer's
559 tracked `.tres`: value respelling touches 340 files, property order 137. Both can be reproduced
by pure parse; the bulk re-save through Godot is the obvious fix and is measured to empty resources
whose script needs an autoload, destroy `;` comments and drop every `uid=`.

## Ship criterion

- `check canonical` reports every property whose value spelling or position differs from what the
  saver writes — one `  DRIFT  …` line per finding, the census counted, a zero-file census FAILS.
  NOT in `check all` by default (a pin bump must not redden a consumer), same as `check defaults`.
- `scene canonicalize --respell` and `--order` make exactly those edits as LINE edits, never a
  re-serialization: comments, `uid=` and every untouched line byte-identical; a value the tool
  cannot prove it respells correctly is refused and named, not guessed; a second run is a no-op.
- Respelling covers the forms the saver is known to rewrite and nothing speculative: float
  spelling (`0.30` → `0.3`, the saver's shortest round-trip form) and typed-array wrapping
  (`[a,b]` → `Array[T]([a,b])` where the property's type is knowable from the file's own script
  or the class db the defaults check already uses). An unknown type is a refusal, not a rewrite.
- Property order follows the order the saver writes, from the same source the defaults check reads
  property metadata from; where the order is not knowable, the section is left alone and counted.

## Proof budget

  cases: ~15
  tier: pyunit
  lands in: the existing canonicalize/defaults test modules; a vendored scrubbed `.tres` in
    `tests/fixtures/corpus/` for each construct the corpus lacks
  what already covers this: round-trip byte identity over the corpus, and `--elide-defaults`'s
    refusal/idempotence tests — the new passes reuse that harness rather than a new one
