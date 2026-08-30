"""godot — everything that knows what a `.tscn` is.

Layered `format/` → `index/` → `read/`+`write/` → `checks/`; a layer imports
downward, never up. This root holds the one cross-layer FACT:

`VENDORED_DEFAULT` — the stock answer to "which prefixes are vendored, not
yours". Four gates and the orphans read verb each keep their OWN config key
(rule 5: per-gate scoping is a real per-repo choice), but the default VALUE
is one fact, and five spellings of `('addons/',)` were five chances for a new
gate to ship a different one.
"""
VENDORED_DEFAULT = ('addons/',)
