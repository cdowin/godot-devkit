"""walk.py — the ONE place this package enumerates a filesystem.

A day of review found the same defect in six places: something left a census in
silence. The fence masked a decision log; `check doc` masked
a file's tail; D14 never descended into `bugs/<subdir>/`; damaged frontmatter
dropped a grain; the dotted-name filter dropped another. Every fix was an
INSTANCE — a filter taught to report itself — so the next feature reintroduced
the shape somewhere new. Fixing grain detection literally created a new
narrowing, because the fix added a `.` filter and nothing made it disclose.

The shape is not "somebody forgot". The shape is that a `glob`/`rglob`/
`iterdir`/`os.walk` returns ONE list, so a filter applied to it produces one
list too, and the entries it removed have nowhere to go. This module returns
BOTH halves. `Walk.kept` is what survived; `Walk.skipped` is every entry that
did not, each carrying a reason drawn from `SkipReason` — a CLOSED enum. A
filter that cannot name its reason from the fixed set cannot be written:
`Walk.filter` takes a `SkipReason` and refuses anything else.

Two kinds of reason, and the difference is deterministic rather than judged:

  * A UNIVERSE reason (`census` is None) says the entry was never a candidate —
    a directory when files were asked for, a `.txt` when `.md` was asked for.
    Those are declared by the ENUMERATOR's arguments, up front, once.
  * A NARROWING reason (`census` is a template) says the entry WAS a candidate
    and a filter removed it. Every narrowing renders into the census, always.

`Walk.filter` accepts narrowing reasons only, so a hand-rolled narrowing cannot
be silent by construction; universe reasons are reachable only by declaring
them as an enumerator argument.

The count and its disclosures are the SAME STRING. `Walk` has no length —
`len(walk)` raises, pointing at `census()` — and `tests/test_boundaries.py`
forbids `len(x.kept)` outside this file, so a renderer cannot obtain a number
without carrying what the number left out.

`tests/test_boundaries.py` also asserts that `glob`, `rglob`, `iterdir` and
`os.walk` appear NOWHERE ELSE in `src/`. A new gate that enumerates directly
breaks the build.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Callable, Iterator


class SkipReason(Enum):
    """Every reason an entry may leave a walk. CLOSED — adding a reason is an
    edit HERE, reviewed here, and the census learns to render it here.

    The value is the census template, or None for a universe reason. Declaration
    order is render order, so the disclosure string is stable across runs and
    across platforms: two censuses of the same tree are byte-identical.
    """

    # --- universe: never a candidate ------------------------------------------
    NOT_A_FILE = None
    NOT_A_DIRECTORY = None
    SUFFIX_MISMATCH = None

    # --- narrowing: was a candidate, a filter removed it ----------------------
    # The two the PM census has always disclosed, in the order it disclosed
    # them. Their wording is the wording that shipped; this is where it lives.
    NO_FRONTMATTER = '{n} note(s) skipped (no frontmatter — not a grain)'
    DOTTED_NAME = '{n} hidden (dot-prefixed — skipped, as D13 skips them)'
    NO_GRAIN_FILE = '{n} dir(s) with no grain file'
    EXCLUDED_PATH = '{n} path(s) excluded from scope'

    @property
    def census(self) -> str | None:
        return self.value

    @property
    def is_narrowing(self) -> bool:
        return self.value is not None


class Kind(Enum):
    """What an enumerator is asked FOR. The universe declaration."""

    FILE = 'file'
    DIR = 'dir'
    ANY = 'any'


@dataclass(frozen=True)
class Skip:
    path: Path
    reason: SkipReason


@dataclass(frozen=True)
class Walk:
    """Both halves of one enumeration.

    Deliberately has no length. A census that wants a number calls `census()`,
    which renders the number and its narrowings together.
    """

    kept: tuple[Path, ...]
    skipped: tuple[Skip, ...] = ()

    def __len__(self) -> int:  # pragma: no cover - the message IS the API
        raise TypeError(
            'a Walk has no length: call .census(label) so the count and the '
            'entries the walk skipped render together, or iterate .kept when '
            'you want the paths rather than a number')

    def __iter__(self) -> Iterator[Path]:
        return iter(self.kept)

    def filter(self, keep: Callable[[Path], bool], reason: SkipReason) -> 'Walk':
        """A narrower walk, with everything it removed recorded under `reason`.

        Refuses a universe reason: "this was never a candidate" is a statement
        the ENUMERATOR makes from its arguments, not something a downstream
        predicate may claim after the fact. Without that refusal, `filter` is a
        hole through which any narrowing can call itself a universe and vanish.
        """
        if not reason.is_narrowing:
            raise ValueError(
                f'{reason.name} is a universe reason — it may only be produced '
                f'by an enumerator argument. A filter must name a narrowing '
                f'reason, because a narrowing is what the census discloses.')
        kept: list[Path] = []
        skipped = list(self.skipped)
        for path in self.kept:
            (kept.append(path) if keep(path) else skipped.append(Skip(path, reason)))
        return Walk(tuple(kept), tuple(skipped))

    def partition(self, keep: Callable[[Path], bool], reason: SkipReason) -> tuple['Walk', tuple[Path, ...]]:
        """`(the narrower walk, the paths it removed)` — for the caller that
        needs to REPORT the removed entries as findings rather than only count
        them. The removals stay in `skipped` either way."""
        removed = tuple(p for p in self.kept if not keep(p))
        return self.filter(keep, reason), removed

    def merge(self, other: 'Walk') -> 'Walk':
        return Walk(self.kept + other.kept, self.skipped + other.skipped)

    def counts(self) -> dict[SkipReason, int]:
        """How many entries each narrowing reason removed. Universe reasons are
        absent: they answer "what was this walk OF", not "what did it drop"."""
        out: dict[SkipReason, int] = {}
        for skip in self.skipped:
            if skip.reason.is_narrowing:
                out[skip.reason] = out.get(skip.reason, 0) + 1
        return out

    def disclosures(self) -> str:
        """`', 2 note(s) skipped (…)'` for every narrowing that removed
        something, in `SkipReason` declaration order. Empty when the walk
        narrowed nothing: a walk that skipped nothing has nothing to disclose."""
        counts = self.counts()
        return ''.join(f', {reason.census.format(n=counts[reason])}'
                       for reason in SkipReason if reason in counts)

    def census(self, label: str) -> str:
        """`'3 bug(s), 1 note(s) skipped (…)'` — THE counting API.

        One string, produced once, holding the number and everything the number
        left out. There is no way to ask this object for the first without the
        second, which is the whole point of the type.
        """
        return f'{len(self.kept)} {label}{self.disclosures()}'


# --- the enumerators ----------------------------------------------------------
# Every `glob`, `rglob`, `iterdir` and `os.walk` in this package is below this
# line. `tests/test_boundaries.py` asserts it, naming file:line when it is not.

def _classify(paths: list[Path], kind: Kind) -> Walk:
    """Split a raw listing against the universe `kind` declares."""
    if kind is Kind.ANY:
        return Walk(tuple(paths))
    want_dir = kind is Kind.DIR
    # `is_dir()` / `is_file()`, never `not is_dir()`: a BROKEN SYMLINK is
    # neither, and the negation would hand it to a reader that then fails to
    # open it. Asked for one kind, an entry that is not that kind is skipped.
    reason = SkipReason.NOT_A_DIRECTORY if want_dir else SkipReason.NOT_A_FILE
    kept: list[Path] = []
    skipped: list[Skip] = []
    for path in paths:
        if path.is_dir() if want_dir else path.is_file():
            kept.append(path)
        else:
            skipped.append(Skip(path, reason))
    return Walk(tuple(kept), tuple(skipped))


def entries(path: Path) -> dict[str, str]:
    """{exact name: 'file'|'dir'} for one directory — EXACT names, always.

    Never `Path.is_file()` for an existence question: macOS resolves
    `decisions.md` to an existing `DECISIONS.md` and Linux does not, so the same
    tree would be clean on one platform and drifting on the other. A listing
    compares the bytes git stores.

    Not a `Walk`: nothing is filtered, so there is nothing to disclose. This is
    the raw listing the case-sensitivity rules read.
    """
    try:
        return {p.name: ('dir' if p.is_dir() else 'file') for p in path.iterdir()}
    except OSError:
        return {}


def children(path: Path, kind: Kind = Kind.ANY) -> Walk:
    """One directory's immediate entries, sorted. A missing directory is an
    empty walk, never a crash — the callers all treat "no such tree" as "no
    such entries"."""
    try:
        raw = sorted(path.iterdir())
    except OSError:
        return Walk(())
    return _classify(raw, kind)


def matching(path: Path, pattern: str, kind: Kind = Kind.ANY) -> Walk:
    """One directory's entries matching a glob PATTERN, sorted.

    The pattern is the caller's literal; ids reaching here as patterns is a
    separate defect the id validators own (`model.id_is_literal`).
    """
    try:
        raw = sorted(path.glob(pattern))
    except OSError:
        return Walk(())
    return _classify(raw, kind)


def descendants(path: Path, kind: Kind = Kind.ANY, suffix: str | None = None,
                pattern: str = '*') -> Walk:
    """Everything under a tree, recursively, sorted.

    `suffix` is compared case-INSENSITIVELY and is a UNIVERSE declaration, not a
    filter: `glob('*.md')` saw neither `<slot>/<topic>/<doc>.md` nor `<DOC>.MD`,
    and both were invisible to every rule at once while the census printed the
    smaller number without saying it had looked less far.
    """
    try:
        raw = sorted(path.rglob(pattern))
    except OSError:
        return Walk(())
    walk = _classify(raw, kind)
    if suffix is None:
        return walk
    want = suffix.lower()
    kept: list[Path] = []
    skipped = list(walk.skipped)
    for candidate in walk.kept:
        (kept.append(candidate) if candidate.suffix.lower() == want
         else skipped.append(Skip(candidate, SkipReason.SUFFIX_MISMATCH)))
    return Walk(tuple(kept), tuple(skipped))


def named(root: Path, name: str, prune: tuple[str, ...] = ()) -> tuple[list[Path], list[Path]]:
    """`(files named exactly `name`, files whose LOWERCASED name matches)`.

    EXACT names, from a directory listing — never `rglob(name)`. A pattern whose
    final segment holds no wildcard resolves through `Path.exists()`, so on
    macOS `rglob('decisions.md')` answers an on-disk `DECISIONS.md` with the
    path `x/decisions.md`: a path that does not exist, and a NON-EMPTY list,
    which is what silences a scanned-nothing guard while every other log goes
    unopened.

    The case variants come back SEPARATELY to be reported: never folded in (the
    two platforms would emit opposite findings about the same file) and never
    dropped (a log the rule cannot see is a log the rule has not checked).

    `prune` names directories the walk does not descend into.
    """
    exact: list[Path] = []
    variants: list[Path] = []
    low = name.lower()
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in prune]
        for entry in filenames:
            if entry == name:
                exact.append(Path(dirpath) / entry)
            elif entry.lower() == low:
                variants.append(Path(dirpath) / entry)
    return sorted(exact), sorted(variants)
