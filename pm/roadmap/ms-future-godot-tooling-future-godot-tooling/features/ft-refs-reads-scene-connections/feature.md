---
id: ft-refs-reads-scene-connections
kind: feature
milestone: ms-future-godot-tooling
name: refs sees what Godot wires
status: planning
reviewed:
depends_on: []
consumed_by: []
changelog:
---

# refs sees what Godot wires

`refs` reports a symbol as unreferenced when Godot itself wires it, and an unreferenced verdict is
the one that gets a handler or an autoload deleted — rule 4's read-side sin. Three holes, each
reproduced on 657a0e4 with exit 0:

1. **Scene connections** (1.4.0 read-verbs review M3). `scan_scene_refs` (read/refs.py) reads only
   `ext_resource`/`sub_resource`, never `[connection signal=… method=…]`. A handler wired in the
   editor prints `## definitions (1)` and nothing else; deleting it breaks the connection at runtime
   with no parse error. The fix is a scene-side scan over the parsed sections, not a regex.
2. **Autoload names.** Declared in `project.godot`, not by `class_name`, so `refs GameManager`
   prints `(no references found)` over `GameManager.start()`. `read/autoloads.py`'s
   `list_autoloads()` already parses the file; `refs` should index those names as it does a
   `class_name`. Closes the known gap CLAUDE.md names.
3. **A handler or signal named as an argument.** `is_connected("died", _on_x)`, `has_signal("died")`
   and `Signal(obj, "died")` land in no bucket (1.4.0 read-verbs review N3 — moved here from the
   carry-forwards). They belong in the dynamic bucket at least, so the zero verdict cannot print.

Holes 2 and 3 were raised by a DeepWiki review of the repo, then reproduced here:
https://deepwiki.com/search/are-there-improvements-you-wou_13405135-c567-462c-baf2-cd2dca92dd81 —
its line numbers predate 2.0.0, and its claims that `rng` inner-class shadowing is open and that
nothing parses `project.godot` were checked and are false.

## Ship criterion

Each of the three spellings above, in a scratch project, shows under a named bucket of `refs <symbol>`
and the zero verdict does not print; a symbol with genuinely no references still prints it.
`refs --retarget` behaviour is unchanged.

## Proof budget

<!-- Roughly how many test cases this feature should cost, written before it is
     built and compared after. Name the tier and the existing module they land
     in; say what the suite already checks and why that is not enough. -->

  cases:
  tier:
  lands in:
  what already covers this:
