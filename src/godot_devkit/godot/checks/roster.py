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
# Stock is what the engine drops silently: `props` (an assigned property no
# script or class declares), `tres-comment` (a comment the saver deletes),
# `unit-disk` (a no-boot test touching live save data).
KNOWN_GATES = ('props', 'tres-comment', 'unit-disk')

# Gates that dispatch and that `[roster] checks` may name, but that the STOCK
# roster leaves out: `uid` (the import pass in `parse` also fails on drift),
# `patterns` (a project's own rules) and `addon` (for add-on repos).
OPT_IN_GATES = ('uid', 'patterns', 'addon')

# Gates 5.0 removed: the engine writes the form they policed, or they were one
# project's house rule. Named so a roster that still lists one is told so.
REMOVED_GATES = ('warnings', 'defaults', 'rng', 'tres', 'canonical',
                 'test-shape', 'ui-layout')

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
    declaring the stock roster get byte-identical output (rule 5, proven in the suite).

    An unknown name is REFUSED rather than skipped: a typo would otherwise
    narrow the aggregate in silence, which is the cardinal sin with a config
    file in front of it.
    """
    if 'godot' in config_section('checks'):
        raise ConfigError('[checks] godot was removed in 4.0; use [roster] checks')
    roster = str_tuple(config_section(ROSTER_SECTION), ROSTER_SECTION,
                       ROSTER_KEY, KNOWN_GATES)
    removed = [c for c in roster if c in REMOVED_GATES]
    if removed:
        raise ConfigError(
            f'[{ROSTER_SECTION}] {ROSTER_KEY} names gate(s) removed in 5.0: '
            f'{", ".join(removed)} — drop them')
    unknown = [c for c in roster if c not in (*KNOWN_GATES, *OPT_IN_GATES)]
    if unknown:
        raise ConfigError(
            f'[{ROSTER_SECTION}] {ROSTER_KEY} names unknown gate(s) {", ".join(unknown)} '
            f'— known gates are {" ".join((*KNOWN_GATES, *OPT_IN_GATES))}')
    # `all` naming itself would recurse forever; it is the one name that cannot
    # appear, and KNOWN_GATES already excludes it.
    return tuple(dict.fromkeys(roster))
