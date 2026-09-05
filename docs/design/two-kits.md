# Two kits — splitting this package in half

**Status: a shape, ruled but not scheduled. Chris and the architect, 2026-09-04.** Not for 0.24.0 — a
repo split during a tag is how commits get lost. This is the design; the milestone comes after the tag.

## The observation

Chris, 2026-09-04:

> *"Godot dev kit is probably doing two things now, and I think it's two separate utility repos that we
> should split. So everything we talked about today is call it just dev kit, I guess, and it… handles the
> SDLC, the CI, hooks, agentic development. It's like the agentic dev kit. But then there's another part,
> and those are Godot utilities. Things that let you work with scene files and other things like that that
> have nothing to do with the rest of the kit."*

## The code already agrees — measured, not asserted

**There are ZERO imports between `repo/` and `godot/`, in either direction.** Not loose coupling; none.
The two halves have been separate for some time and only the repository boundary has not caught up.

| | lines | the checks it owns |
|---|---|---|
| **`repo/`** — the agentic kit | 9,334 | `doc`, `hooks`, `pm`, `repo_hygiene`, `shell` — no Godot knowledge |
| **`godot/`** — the Godot utilities | 6,844 | `defaults`, `props`, `rng`, `test_shape`, `tres`, `tres_comment`, `uid`, `unit_disk` |
| **`core/`** — shared substrate | 981 | — |

Plus 44 installable files, every one of them `repo/`-side.

**The checks sorted themselves by side with nobody enforcing it.** That is the strongest evidence the seam
is real: two people adding checks over months put every agnostic one in `repo/checks/` and every
Godot-specific one in `godot/checks/`, because the boundary was already obvious from inside the code.

## `core/` mostly sorts too

| module | lines | used by `repo/` | by `godot/` |
|---|---|---|---|
| `apply` | 373 | 5 | **0** |
| `markdown` | 113 | 2 | **0** |
| `config` | 156 | 5 | 12 |
| `project` | 54 | 7 | 15 |
| `walk` | 285 | 3 | 2 |

`apply` and `markdown` are repo-only — **486 of the 981 lines go to the agentic kit with no argument.**
What is genuinely shared is `config` + `project` + `walk` = 495 lines, and `project.py` is 54 lines that
read `project.godot`, which arguably makes it Godot-side rather than shared. So the real shared surface is
roughly **440 lines of `config` + `walk`** — "read a TOML section" and "walk tracked files".

## The ruling: duplicate it

Three options were weighed. A third `devkit-core` package gives the cleanest graph and costs three repos
and a version matrix for 440 lines. Having the Godot utilities depend on the agentic kit is simple and
one-directional, but it means a scene parser drags in a PM tree, hooks and installables — **the exact
cross-wiring rule 8 was written to end**, one level up.

**Chris ruled duplication**, with the condition stated:

> *"Duplicating shared in this case is fine. If both projects want to be config-forward we either need a
> good published/public shared config utility or it's small enough that hand-duplicating isn't a big deal
> right now."*

So duplication is the pragmatic answer **now**, and the trigger for revisiting it is named: if both kits
stay config-forward and the shared surface grows, the answer becomes a published shared config utility —
not a private third package, and not a dependency edge between the two kits.

**Duplication needs a gate.** 440 lines copied in two repos drift silently, and this package already has
the pattern for that — the hook corpora self-test rather than trusting that two copies agree. Whatever
form it takes, the copies must be asserted identical by something that runs, not by intention.

## The open question, and it decides how clean the split is

**Can `[checks] all` compose a check from another package?** The whole value of the split rests on it: the
agentic kit provides the gate framework and the runner, the Godot utilities provide Godot gates, and a
consumer's `devkit.toml` composes both into one roster. The config-driven roster and `[gates] extra`
already look like the right seam, but **this has not been verified** — nothing has ever registered a check
from outside the package.

If it cannot, the split still works but the halves each grow their own runner, which is a second name for
the same fact and would want arguing before it ships.

## What the split does NOT change

Rule 8 applies to both kits equally: neither knows anything about a consuming project. The Godot utilities
are not exempt because they parse Godot files — `tests/fixtures/` is still where realistic data lives, and
a consumer still proves its own integration when it bumps its pin.

## Sequencing

After the 0.24.0 tag, and probably after `0.25.0/the-release-is-a-conveyor` — the conveyor makes releases
cheap and repeatable, which is worth having *before* there are two things to release rather than after.
