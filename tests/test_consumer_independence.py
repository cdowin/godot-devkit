"""Hard rule 8, as a gate — this package knows nothing about its consumers.

The rule in one line: no file here names a consuming project, reads a path
outside this checkout, or gates on another repo's content or working state.

It is a gate rather than a convention because the alternative was measured. The
package was extracted from two private game repos, kept their names in its
prose as worked examples, and then grew a release gate (`tools/consumer_smoke.py`,
971 lines) that ran every verb against whichever of those two checkouts happened
to be cloned on the machine. In CI, where neither is, it SKIPPED — so a tag's
verdict depended on whose laptop asked, and somebody else's uncommitted work
could redden it. A release gate that can be reddened by another repo's working
state is not a gate.

WHY THE BANNED NAMES LIVE HERE. Naming them is itself consumer knowledge, so
there is exactly one place in the tree allowed to hold them: this file, as a
tombstone. `tests/` is the harness, not the package — nothing shipped imports
this — and a regression guard that cannot say what regressed cannot fire. Three
narrower guards predate it and stay, because each also pins a claim of its own
about the file set it reads: test_ci_workflows (workflows), test_makefile_include
(the include), test_runners_installable and test_install (the installables).
This one is the whole-tree form.

WHAT IS DELIBERATELY OUT OF SCOPE. `pm/`, `CHANGELOG.md` and `docs/reviews/` are
the LOG: dated records of what was measured on a given day. Rewriting a record
to say something other than what was measured is falsifying it, so they are
excluded by path, out loud, here. The rule governs what is WRITTEN from now on —
a new CHANGELOG bullet describes behaviour generically ("a 251-story tree"),
never by naming a private repo.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from support import REPO_ROOT

# The projects this package was extracted from. Word-bounded on purpose: the
# committed corpus is a hiking game's data and legitimately spells `trail_mile`
# and `c_on_trail`, which are domain vocabulary and not a project reference.
CONSUMER_NAMES = (r'\bnullbound\b', r'\bNullBound\b', r'\bNULLBOUND\b',
                  r'\btrail\b', r'\bTrail\b', r'\bTRAIL\b',
                  r'\bappalachian\b', r'\bAppalachian\b')

# Reaching OUTSIDE the checkout, as literals. A path handed in on the command
# line is the caller's choice and is not this (`pm ledger record
# --from-transcript` takes an absolute path under ~/.claude/ by design); what is
# banned is the package deciding on its own to go looking somewhere else.
#
# The `[w]orkspace` spelling is load-bearing, not a typo: it matches the same
# text while keeping THIS line out of its own census, so the file needs no
# exemption and a real literal added here later is still caught. The rest are
# already escaped enough not to match themselves.
OUTSIDE_READS = (r'~/[w]orkspace', r'Path\.home\(\)',
                 r'os\.path\.expanduser\(\s*[\'"]~',
                 r'\$HOME/[w]orkspace',
                 r'os\.environ\[[\'"]HOME[\'"]\]\s*\)?\s*/')

# The LOG. Dated records of what was measured; not rewritable without lying.
LOG_PATHS = ('pm/', 'docs/reviews/', 'CHANGELOG.md')

# Directories that are not the repo's content.
NOT_CONTENT = {'.git', '.gate-reports', '.pytest_cache', '.ruff_cache', '.venv',
               '__pycache__', 'node_modules', '.mypy_cache'}

# The tombstones: files allowed to spell a banned name, because banning it is
# what they do. Every entry carries its reason — an allowlist without one is
# how a scanner gets narrowed until it reports nothing.
# This file is NOT among them: it spells the names only inside `\b...\b`
# regexes, which the same regexes do not match, so it needs no exemption and a
# bare name added here in future is caught like anywhere else.
TOMBSTONES = {
    'tests/test_ci_workflows.py': 'guards the workflows against the same names',
    'tests/test_makefile_include.py': 'guards Makefile.devkit against them',
    'tests/test_runners_installable.py': 'guards every install-runners file',
    'tests/test_install.py': 'guards every installed hook',
}

# Rule 4: a census that collapses must FAIL, not pass over nothing. The tree is
# ~250 files today; the floor is well under that and still far above zero.
FILE_FLOOR = 120

SUFFIXES_READ = {'.py', '.md', '.sh', '.yml', '.yaml', '.toml', '.cfg', '.txt',
                 '.tscn', '.tres', '.gd', '.json', '.jsonl', ''}


def _is_log(rel: str) -> bool:
    return any(rel == path or rel.startswith(path) for path in LOG_PATHS)


def scanned_files() -> list[Path]:
    """Every content file in the WORKTREE, minus the log.

    The worktree rather than `git ls-files`, deliberately: a rule-8 violation
    arrives as a NEW file, and a census taken from the index would not see it
    until somebody staged it — which is one commit too late.
    """
    found = []
    for path in sorted(REPO_ROOT.rglob('*')):
        if not path.is_file() or path.is_symlink():
            continue
        rel = path.relative_to(REPO_ROOT).as_posix()
        if set(Path(rel).parts) & NOT_CONTENT or _is_log(rel):
            continue
        if path.suffix not in SUFFIXES_READ:
            continue
        found.append(path)
    return found


def offending_lines(path: Path, patterns: tuple[str, ...]) -> list[str]:
    try:
        text = path.read_text(encoding='utf-8')
    except (OSError, UnicodeDecodeError):
        return []
    return [f'{path.relative_to(REPO_ROOT).as_posix()}:{n}: {line.strip()[:120]}'
            for n, line in enumerate(text.splitlines(), 1)
            if any(re.search(p, line) for p in patterns)]


def test_the_census_is_not_empty_and_covers_the_package_and_the_harness():
    """The scan itself, before anything it claims. A glob that matched nothing
    would make every assertion below vacuously true — this package's cardinal
    sin wearing a green tick (CLAUDE.md rule 4)."""
    files = scanned_files()
    assert len(files) >= FILE_FLOOR, (
        f'census collapsed to {len(files)} file(s), floor {FILE_FLOOR} — the '
        f'walk broke, or the tree shrank and this floor is now a lie')
    tops = {path.relative_to(REPO_ROOT).parts[0] for path in files}
    for required in ('src', 'tests', 'CLAUDE.md', 'README.md', 'Makefile'):
        assert required in tops, f'{required} is outside the scan: {sorted(tops)}'


@pytest.mark.parametrize('rel, why', sorted(TOMBSTONES.items()))
def test_every_tombstone_still_earns_its_exemption(rel, why):
    """An allowlist entry that no longer needs to be there is an entry that
    will one day cover a real violation. Each must still spell a banned name."""
    path = REPO_ROOT / rel
    assert path.is_file(), f'{rel} is allowlisted and does not exist ({why})'
    assert offending_lines(path, CONSUMER_NAMES), (
        f'{rel} no longer names a consumer, so its exemption ({why}) covers '
        f'nothing and must be deleted from TOMBSTONES')


def test_no_file_names_a_consuming_project():
    """The rule's first clause. A worked example names a SHAPE — "a project
    whose `check` carries extra gates" — never a repo: the reader of a generic
    example learns the rule, and the reader of a named one learns that this
    tool has favourites."""
    hits = []
    for path in scanned_files():
        rel = path.relative_to(REPO_ROOT).as_posix()
        if rel in TOMBSTONES:
            continue
        hits.extend(offending_lines(path, CONSUMER_NAMES))
    assert not hits, (
        'a consuming project is named in the tool (CLAUDE.md hard rule 8). '
        'Rewrite the sentence generically — do not delete it and leave a '
        f'dangling explanation:\n' + '\n'.join(hits[:25]))


def test_nothing_reaches_for_a_path_outside_this_checkout():
    """The rule's second clause, and the one the deleted smoke gate broke. A
    verdict computed from a directory that may or may not exist on the machine
    running it is a different verdict on every machine."""
    hits = []
    for path in scanned_files():
        rel = path.relative_to(REPO_ROOT).as_posix()
        if rel in TOMBSTONES:
            continue
        hits.extend(offending_lines(path, OUTSIDE_READS))
    assert not hits, (
        'something reads a path outside this checkout (CLAUDE.md hard rule 8). '
        'A check that needs realistic data VENDORS it under tests/fixtures/:\n'
        + '\n'.join(hits[:25]))


def test_the_full_gate_is_a_composition_of_self_contained_targets():
    """`make milestone` must not acquire a member that needs another repo. The
    three it has all read this checkout alone, which is why CI and a laptop
    reach the same verdict."""
    body = (REPO_ROOT / 'Makefile').read_text(encoding='utf-8')
    match = re.search(r'^milestone:(.*)$', body, re.M)
    assert match, 'the Makefile no longer declares a `milestone` target'
    members = match.group(1).split()
    assert members == ['gates', 'hooks-self-test', 'matrix'], members
    for member in members:
        recipe = re.search(rf'^{member}:.*?\n((?:\t.*\n|\n)*)', body, re.M)
        assert recipe, f'{member} has no recipe in this Makefile'
        assert not re.search(r'\.\./|~/|\$\(HOME\)|\$\$HOME', recipe.group(1)), (
            f'`{member}` reaches outside the checkout: {recipe.group(1)!r}')
