"""roster.py — THE gate roster: which gates exist, and which `check all` runs.

One module, read by every reader of `[roster] checks` — `cli.py`'s `check all`
and `install-runners`' retired-file line (`godot/install.py`). Two readers with
two fallbacks disagreed about the same key (#28): one said "safe to delete"
over a value the other refused at exit 2.
"""
from __future__ import annotations

from godot_devkit.core.config import ConfigError, config_section, str_tuple
from godot_devkit.core.project import deprecated

# THE gate roster, in the order `check all` runs it. One list: a gate that is
# dispatchable is in the stock aggregate, and a name `[roster] checks` may
# carry is a name `check <name>` runs — there is no second list for either
# fact to drift from. Eight ship; eight stay (0.25.0).
#
# Stock is ALL EIGHT, and a repo narrows by config, never the other way
# round. Until 0.25.0 five of these were out of the default — `defaults`
# floods a never-canonicalized tree, `rng` scans the whole tree by default,
# `unit-disk` and `test-shape` name test roots a fresh project lacks,
# `tres-comment` reddens a never-swept tree — and each was one config entry
# away. That was the right default for a kit whose `check all` was mostly
# repo-discipline gates. It is the wrong one for the Godot kit alone: a roster
# that runs three of eight and prints PASS is the quieter cardinal sin, and a
# project on the first day sees exactly which gates its tree is not shaped
# for, each naming the section that scopes it.
KNOWN_GATES = ('uid', 'tres', 'props', 'defaults', 'rng', 'tres-comment',
               'unit-disk', 'test-shape')

# Gates that dispatch and that `[roster] checks` may name, but that the STOCK
# roster leaves out: each starts red on any tree its fixer never ran over, so
# shipping it in `check all` would redden every consumer on a pin bump. A repo
# opts in by naming it; the aggregate never grows under anyone.
OPT_IN_GATES = ('canonical',)

# The godot-devkit.toml key that narrows the roster. It was `[checks] godot`
# until 3.0, when `[checks]` was agentic-sdlc's table too; 3.x still reads
# the old key, with one deprecation line (remove in 4.0).
ROSTER_SECTION = 'roster'
ROSTER_KEY = 'checks'
LEGACY_SECTION = 'checks'
LEGACY_KEY = 'godot'


def all_roster() -> tuple[str, ...]:
    """Which gates `check all` runs HERE — `[roster] checks`, else all eight.

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
    sect = config_section(ROSTER_SECTION)
    legacy = config_section(LEGACY_SECTION)
    if ROSTER_KEY in sect or LEGACY_KEY not in legacy:
        section, key = ROSTER_SECTION, ROSTER_KEY
        roster = str_tuple(sect, ROSTER_SECTION, ROSTER_KEY, KNOWN_GATES)
    else:
        # Remove in 4.0: the pre-3.0 spelling of the roster key.
        deprecated(f'[{LEGACY_SECTION}] {LEGACY_KEY} is read as a fallback — '
                   f'move it to [{ROSTER_SECTION}] {ROSTER_KEY} (the '
                   f'fallback is removed in 4.0)')
        section, key = LEGACY_SECTION, LEGACY_KEY
        roster = str_tuple(legacy, LEGACY_SECTION, LEGACY_KEY, KNOWN_GATES)
    unknown = [c for c in roster if c not in (*KNOWN_GATES, *OPT_IN_GATES)]
    if unknown:
        raise ConfigError(
            f'[{section}] {key} names unknown gate(s) {", ".join(unknown)} '
            f'— known gates are {" ".join((*KNOWN_GATES, *OPT_IN_GATES))}')
    # `all` naming itself would recurse forever; it is the one name that cannot
    # appear, and KNOWN_GATES already excludes it.
    return tuple(dict.fromkeys(roster))
