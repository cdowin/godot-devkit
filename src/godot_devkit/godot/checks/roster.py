"""roster.py — THE gate roster: which gates exist, and which `check all` runs.

One module, read by every reader of `[roster] checks` — `cli.py`'s `check all`
and `install-runners`' retired-file line (`godot/install.py`). Two readers with
two fallbacks disagreed about the same key (#28): one said "safe to delete"
over a value the other refused at exit 2.
"""
from __future__ import annotations

from godot_devkit.core.config import ConfigError, config_section, str_tuple

# THE gate roster, in the order `check all` runs it. One list: a gate that is
# dispatchable is in the stock aggregate or in OPT_IN_GATES, and a name
# `[roster] checks` may carry is a name `check <name>` runs — there is no
# second list for either fact to drift from.
#
# Stock is what the engine does NOT already catch. `warnings` reads the
# project's analyzer levels; `props`, `defaults`, `rng`, `tres-comment`,
# `unit-disk` and `test-shape` find what the engine drops silently or the
# editor rewrites. A repo narrows by config, never the other way round.
KNOWN_GATES = ('warnings', 'props', 'defaults', 'rng', 'tres-comment',
               'unit-disk', 'test-shape')

# Gates that dispatch and that `[roster] checks` may name, but that the STOCK
# roster leaves out. `uid` and `tres` police what the editor owns, and the
# import pass in `parse` already fails on uid drift. `canonical` and `patterns`
# each start red on any tree its fixer never ran over. A repo opts in by naming
# a gate; the aggregate never grows under anyone.
OPT_IN_GATES = ('uid', 'tres', 'canonical', 'patterns')

ROSTER_SECTION = 'roster'
ROSTER_KEY = 'checks'


def all_roster() -> tuple[str, ...]:
    """Which gates `check all` runs HERE — `[roster] checks`, else the stock list.

    Applicability is per-repo and the aggregate is where it shows. Most of the
    roster reads `.tscn`/`.tres`/`.gd`, so a repo holding none of those gets
    a handful of 0-file censuses, and rule 4 correctly turns every one of them
    red. That is not drift and it is not a reason to weaken a gate — it is the
    roster being wrong for the repo, which is exactly the kind of variation
    rule 5 puts in godot-devkit.toml. A repo with no godot-devkit.toml and one
    declaring the eight get byte-identical output (rule 5, proven in the suite).

    An unknown name is REFUSED rather than skipped: a typo would otherwise
    narrow the aggregate in silence, which is the cardinal sin with a config
    file in front of it.
    """
    roster = str_tuple(config_section(ROSTER_SECTION), ROSTER_SECTION,
                       ROSTER_KEY, KNOWN_GATES)
    unknown = [c for c in roster if c not in (*KNOWN_GATES, *OPT_IN_GATES)]
    if unknown:
        raise ConfigError(
            f'[{ROSTER_SECTION}] {ROSTER_KEY} names unknown gate(s) {", ".join(unknown)} '
            f'— known gates are {" ".join((*KNOWN_GATES, *OPT_IN_GATES))}')
    # `all` naming itself would recurse forever; it is the one name that cannot
    # appear, and KNOWN_GATES already excludes it.
    return tuple(dict.fromkeys(roster))
