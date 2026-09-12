"""baseline.py — a gate adopted FROZEN, then paid down: the per-file debt ratchet.

A gate that reddens an existing tree on the day it lands gets switched off, and
a gate that is off is worth nothing. `[test_shape] ledger` showed the way out:
record each file's debt at its CURRENT measurement, fail only when it grows,
and let the record only shrink. This is that ledger, generalised to any gate
whose findings belong to a file — keyed by the gate's own `[<section>]
baseline`, valued by how many findings that file carries today:

    [defaults]
    baseline = { "data/enemies/grunt.tres" = 3 }

Per file, against its entry:

  held    findings == entry  frozen: not printed, counted on the BASELINED line
  GREW    findings >  entry  every one of the file's findings is printed and
                             fails the gate as if the file had no entry — a
                             count cannot say which one is new, so all are shown
  SHRUNK  0 < findings < entry  held, but the ENTRY fails: lower it, so the debt
                             paid down cannot silently grow back to the old number
  STALE   no findings        the entry fails: drop it

A BARE TOTAL is deliberately not a shape this accepts. One number across the
tree lets a fix in one file pay for a new finding in another, and the gate
PASSes over fresh drift — the read-side cardinal sin, dressed as a ratchet.

Every run with a baseline declared prints one `  BASELINED  …` line, so frozen
debt is visible rather than quiet. A baseline that is absent (or `{}`) prints
nothing and changes nothing: the output is byte-identical to a gate without
this module (rule 5).
"""
from __future__ import annotations

from collections import Counter
from collections.abc import Iterable

from godot_devkit.core.config import path_count_table

KEY = 'baseline'


def _plural(count: int, one: str, many: str) -> str:
    return one if count == 1 else many


class Judgement:
    """What one run's findings came to against a baseline."""

    def __init__(self, section: str, declared: bool) -> None:
        self.section = section
        self.declared = declared
        self.frozen: set[str] = set()    # files whose findings are held back
        self.held = 0                    # findings those files carry
        self.ratchet: list[str] = []     # GREW / SHRUNK / STALE lines
        self.out_of_date = 0             # SHRUNK + STALE: entries that fail
        self.open: list[str] = []        # finding lines still standing, in order

    @property
    def failed(self) -> bool:
        """True when an ENTRY fails on its own (a grown file fails by its findings)."""
        return self.out_of_date > 0

    def report(self) -> None:
        """The ratchet lines, then the BASELINED line — nothing when undeclared."""
        for line in self.ratchet:
            print(line)
        if self.declared:
            print(f'  BASELINED  {self.held} finding(s) in {len(self.frozen)} '
                  f'file(s) frozen by [{self.section}] {KEY} — this number '
                  f'should only shrink')

    def verdict(self, tag: str, census: str) -> str:
        """The FAIL line for a run whose only findings are out-of-date entries."""
        entries = _plural(self.out_of_date, 'entry', 'entries')
        return (f'{tag} FAIL — {self.out_of_date} [{self.section}] {KEY} '
                f'{entries} above the findings left, across {census}; the '
                f'{KEY} only shrinks')


class Baseline:
    """One gate's `[<section>] baseline`: `{repo-relative path: findings}`."""

    def __init__(self, section: str, entries: dict[str, int]) -> None:
        self.section = section
        self.entries = dict(entries)

    @classmethod
    def read(cls, sect: dict, section: str) -> Baseline:
        """From a loaded config section; a bad shape is ConfigError (exit 2)."""
        return cls(section, path_count_table(sect, section, KEY))

    def judge(self, findings: Iterable[tuple[str, str]]) -> Judgement:
        """Split `(rel, line)` findings into held and open, and grade the entries.

        `open` keeps the input order, so a gate that prints `judgement.open`
        where it printed its findings prints the same bytes when nothing is
        declared.
        """
        pairs = list(findings)
        counts = Counter(rel for rel, _ in pairs)
        judged = Judgement(self.section, bool(self.entries))
        for rel in sorted(self.entries):
            ceiling, found = self.entries[rel], counts.get(rel, 0)
            if found > ceiling:
                judged.ratchet.append(
                    f'  GREW  {rel} — {found} finding(s), over its '
                    f'[{self.section}] {KEY} of {ceiling}; every one is a '
                    f'finding again, unfrozen')
                continue
            if found == 0:
                judged.out_of_date += 1
                judged.ratchet.append(
                    f'  STALE  {rel} — no finding left in the scanned tree; '
                    f'drop it from [{self.section}] {KEY}')
                continue
            judged.frozen.add(rel)
            judged.held += found
            if found < ceiling:
                judged.out_of_date += 1
                judged.ratchet.append(
                    f'  SHRUNK  {rel} — {found} finding(s), under its '
                    f'[{self.section}] {KEY} of {ceiling}; lower the entry to '
                    f'"{rel}" = {found}')
        judged.open = [line for rel, line in pairs if rel not in judged.frozen]
        return judged
