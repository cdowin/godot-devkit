"""The consumer deny-list — maintainer configuration, deliberately uncommitted.

`tests/test_consumer_independence.py` asserts rule 8's first clause: no file in
this tool names a consuming project. That guard needs the names to look for,
and the names are the maintainer's own repositories — so in a PUBLIC tree the
guard would publish exactly the list it exists to keep out. (It did, until
v1.0.0: the names sat in a `CONSUMER_NAMES` tuple as `\\b<name>\\b` regexes,
where a word-bounded search for a name does not match it, because the `b` of
`\\b` is itself a word character.)

They live in the environment (`GODOT_DEVKIT_CONSUMER_NAMES`, comma-separated)
or in a `.consumer-names` file at the repo root, one name per line, `#` for a
comment. Both are gitignored.

When neither is configured the sweep has nothing to sweep FOR. Rule 4 forbids a
silent pass over an empty census, so `require()` SKIPS with the reason spelled
out rather than looping over an empty tuple and reporting green: a skip is on
the report, a vacuous pass is not.
"""
from __future__ import annotations

import functools
import os
import re
from pathlib import Path

import pytest

ENV_VAR = 'GODOT_DEVKIT_CONSUMER_NAMES'
NAMES_FILE = Path(__file__).resolve().parents[2] / '.consumer-names'

WHY_EMPTY = (
    f'no consumer names configured, so rule 8\'s first clause has nothing to '
    f'sweep for. Set {ENV_VAR}="name1,name2" or write one name per line into '
    f'{NAMES_FILE.name} at the repo root (both gitignored — the names are '
    f'maintainer configuration and this tree is public).')


@functools.lru_cache(maxsize=1)
def consumer_names() -> tuple[str, ...]:
    """Every configured consumer name, lowercased. Empty when unconfigured.

    The environment wins over the file, so CI can supply the list from a secret
    without a checkout carrying one.
    """
    raw = os.environ.get(ENV_VAR, '')
    if not raw and NAMES_FILE.exists():
        raw = ','.join(line.split('#', 1)[0].strip()
                       for line in NAMES_FILE.read_text(encoding='utf-8').splitlines())
    return tuple(sorted({part.strip().lower() for part in raw.split(',') if part.strip()}))


def name_patterns() -> tuple[str, ...]:
    """The configured names as word-bounded, case-insensitive regexes.

    Word-bounded on purpose: the committed corpus is a hiking game's data and
    legitimately spells `trail_mile`, which is domain vocabulary rather than a
    project reference.
    """
    return tuple(rf'(?i)\b{re.escape(name)}\b' for name in consumer_names())


def require() -> tuple[str, ...]:
    """The patterns, or a DISCLOSED skip — never an empty loop read as a pass."""
    patterns = name_patterns()
    if not patterns:
        pytest.skip(WHY_EMPTY)
    return patterns
