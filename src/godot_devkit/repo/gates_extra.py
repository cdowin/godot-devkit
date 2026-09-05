"""gates_extra.py — `[gates] extra`: the project's OWN gate targets, listed.

`Makefile.devkit` ships one standard `check`: the devkit gates, and then
whatever this prints. A project that has gates of its own — architecture
scans, generator freshness checks, a house style rule — names them here as make
TARGETS, and the include runs them after `godot-devkit check all`:

    [gates]
    extra = ["codex-check", "behaviors-check", "game-shell-scan"]

That is rule 5 one layer up: per-project variation is a devkit.toml section,
never a forked copy of the include.

WHY A VERB AND NOT A GREP IN THE MAKEFILE. The alternative is make parsing TOML
— a `sed` over section headers that gets the first `#`-in-a-string wrong, or a
`python3 -c` one-liner that reimplements `core.config` without its refusals.
Either is a second TOML reader, and a second reader is a second answer. The
include shells out ONCE per `check` run instead, and everything below is
decided in the one place config values are decided.

THE REFUSAL MATRIX. This value is INTERPOLATED INTO A MAKE COMMAND LINE, so the
grammar is narrow on purpose: a make goal, and nothing that could be anything
else. Refused, each with a reason and exit 2 — never a silently-dropped entry,
because a gate that quietly leaves the roster is this package's cardinal sin:

  * whitespace inside a name  (`"lint scan"` would run TWO goals)
  * shell metacharacters      (`;`, `|`, `&`, `$(...)`, backticks, quotes)
  * make metacharacters       (`$`, `%`, `=`, `:`)
  * a path                    (`/`, `..`, `~`, a leading `-` posing as a flag)
  * an empty string, and anything longer than a target plausibly is
  * a non-list, a bare string, an empty list — `core.config.str_tuple` refuses
    all three before this file sees them

NOT refused here: a name that re-enters `check` itself. That one is caught by
the include, which passes a marker into the sub-make and refuses a second
entry — a guard that holds for `check`, `precommit`, `milestone` AND for a
project target that runs `make check` two levels down, none of which a list of
names in this file could know about.
"""
from __future__ import annotations

import re
import sys

from godot_devkit.core.config import ConfigError, config_section, str_tuple

SECTION = 'gates'
KEY = 'extra'

USAGE = """usage: godot-devkit gates-extra

Prints `[gates] extra` from devkit.toml, one make target per line — the
project's own gate targets, which Makefile.devkit's `check` runs after the
devkit ones. No section, or no key: prints nothing, exits 0.

Exit: 0 = printed (possibly nothing) | 2 = the value is not a usable roster."""

# A make goal, and nothing that could be read as anything else. Anchored whole,
# so every rejection below is a rejection of the WHOLE name rather than of a
# suffix somebody could smuggle past.
TARGET = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._+-]*$')
# Long enough for any real target, short enough that a pasted paragraph or a
# base64 blob is refused as the mistake it is.
MAX_LENGTH = 64


def targets() -> tuple[str, ...]:
    """`[gates] extra`, validated. Raises ConfigError on anything unusable.

    Duplicates collapse in declaration order — the same gate named twice is
    waste, not a second gate — and that is the ONLY thing dropped silently.
    """
    roster = str_tuple(config_section(SECTION), SECTION, KEY, ())
    bad = [name for name in roster
           if not TARGET.match(name) or len(name) > MAX_LENGTH]
    if bad:
        raise ConfigError(
            f'[{SECTION}] {KEY} names {len(bad)} value(s) that are not make '
            f'targets: {", ".join(repr(name) for name in bad)} — a target is '
            f'[A-Za-z0-9][A-Za-z0-9._+-]* and at most {MAX_LENGTH} '
            f'characters, because the include interpolates it into a make '
            f'command line')
    return tuple(dict.fromkeys(roster))


def main(argv: list[str]) -> int:
    for arg in argv:
        if arg in ('-h', '--help', 'help'):
            print(USAGE)
            return 0
        print(f'godot-devkit gates-extra: unexpected argument {arg!r}',
              file=sys.stderr)
        print(USAGE, file=sys.stderr)
        return 2
    try:
        roster = targets()
    except ConfigError as err:
        # A devkit.toml mistake is exit 2, the same as every gate's — and the
        # include propagates it rather than running a narrowed `check`.
        print(f'godot-devkit: {err}', file=sys.stderr)
        return 2
    for name in roster:
        print(name)
    return 0
