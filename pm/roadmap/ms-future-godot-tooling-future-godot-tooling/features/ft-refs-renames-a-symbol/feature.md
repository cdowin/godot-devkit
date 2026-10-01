---
id: ft-refs-renames-a-symbol
kind: feature
milestone: "ms-future-godot-tooling"
name: refs renames a symbol
status: planning
reviewed:
depends_on: ["ft-refs-reads-scene-connections"]
consumed_by: []
changelog:
---

# refs renames a symbol

Renaming a `class_name`, method or signal is a by-hand change with no deterministic command:
`refs --retarget` rewrites resource paths after a `git mv`, and nothing rewrites a symbol across
`.gd` and `.tscn`. `refs` already computes the hit set a rename needs, in the same buckets, so a
`refs --rename <symbol> <new>` is that set fed to `core/apply` as one plan.

Depends on ft-refs-reads-scene-connections: a rename that misses a `[connection] method=` or an
autoload site is a diff that looks legitimate and is not (rule 4's write-side sin).

The hard part is `.gd` text: the comment-stripped scan is not string-literal-aware, so a hit inside a
string must refuse rather than rewrite. Any dynamic-bucket hit refuses the WHOLE plan, naming each
site — never a partial rename.

Proposed in a DeepWiki design review of the repo (suggestion 3):
https://deepwiki.com/search/are-there-improvements-you-wou_13405135-c567-462c-baf2-cd2dca92dd81

## Ship criterion

`refs --rename A B [--dry-run]` rewrites every typed hit in one plan, or refuses with every blocking
site named and touches nothing; the same command twice is a no-op; a corpus scene round-trips
byte-identical outside the renamed spans.

## Proof budget

<!-- Roughly how many test cases this feature should cost, written before it is
     built and compared after. Name the tier and the existing module they land
     in; say what the suite already checks and why that is not enough. -->

  cases:
  tier:
  lands in:
  what already covers this:
