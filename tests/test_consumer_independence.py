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

HOW THE CENSUS IS SCOPED, AND WHY IT IS A DENY LIST. Everything under the
checkout is scanned; the exclusions are enumerated, reasoned, and asserted to
account for every file the walk saw. It was an ALLOWLIST of fifteen suffixes
until this release, which meant a file type nobody had thought of arrived
UNSCANNED and stayed that way until somebody remembered to add it — measured at
21 files dropped in silence, 18 of them tracked, including all ten fixture
`project.godot`, which is exactly the artifact a fixture gets vendored FROM a
consumer. A planted name there passed the whole suite. The default is now
SCANNED and the deny list holds only bytes-not-prose, each entry with its
reason. For the same reason a file this gate cannot DECODE is a finding rather
than a skip: one stray non-UTF-8 byte used to remove a whole file from the scan
without a word, so a deny list that forgets a binary type fails loudly instead
of quietly (CLAUDE.md rule 4).
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import NamedTuple

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

# Directories that are not the repo's content. The one exclusion taken on
# trust, and it has to be: `.venv` installs third-party code whose names are
# nobody's business here, and `.git` holds every byte the tree ever had. Each
# is tool output, none is authored, and adding a name to this set is a visible
# act in a diff — unlike the suffix filter this replaced, which excluded by
# forgetting.
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
# ~330 content files today; the floor is well under that and still far above
# zero.
FILE_FLOOR = 120

# The exceptions to "everything is scanned", by lowercased SUFFIX, each with
# its reason. Bytes, not prose: none of these can hold a sentence naming a
# consumer. This list is a convenience, never a correctness dependency — a
# binary type that is NOT here does not slip through, it fails to decode and
# that is a finding. Adding a type here is therefore a comfort measure taken
# after the gate has already shouted, which is the right order.
DENY_SUFFIXES = {
    '.png': 'raster image', '.jpg': 'raster image', '.jpeg': 'raster image',
    '.gif': 'raster image', '.webp': 'raster image', '.ico': 'icon binary',
    '.ttf': 'font binary', '.otf': 'font binary', '.woff': 'font binary',
    '.woff2': 'font binary',
    '.wav': 'audio binary', '.ogg': 'audio binary',
    '.zip': 'archive', '.gz': 'archive', '.tar': 'archive', '.whl': 'built wheel',
    '.pyc': 'compiled bytecode', '.pyo': 'compiled bytecode',
    '.so': 'compiled extension', '.dylib': 'compiled extension',
    '.dll': 'compiled extension',
    '.res': 'Godot binary resource', '.scn': 'Godot binary scene',
    '.ctex': 'Godot compressed texture',
}

# The same, by exact file NAME rather than suffix.
DENY_NAMES = {
    '.DS_Store': 'Finder metadata, written into any directory macOS opens',
}

# The marker every unreadable-file finding carries, so the tombstone test can
# tell "this file names a consumer" from "this file could not be read at all".
UNREADABLE = 'UNREADABLE'


class Census(NamedTuple):
    """What the walk saw, split four ways with nothing left over.

    `walked` is every file, and the other four partition it. A census that
    cannot report its own exclusions is how both of this gate's 0.24.0 holes
    hid: the old one counted what the walk KEPT and never asked what it
    dropped.
    """

    walked: list[Path]
    scanned: list[Path]
    log: list[Path]
    denied: list[tuple[Path, str]]
    tool_output: list[Path]

    def classified(self) -> set[Path]:
        return (set(self.scanned) | set(self.log) | set(self.tool_output)
                | {path for path, _ in self.denied})

    def content(self) -> set[Path]:
        """Everything but the tool output — the files somebody here authored."""
        return set(self.scanned) | set(self.log) | {path for path, _ in self.denied}

    def summary(self) -> str:
        return (f'{len(self.walked)} walked = {len(self.scanned)} scanned + '
                f'{len(self.log)} log + {len(self.denied)} denied + '
                f'{len(self.tool_output)} tool output')

    def denied_report(self) -> str:
        if not self.denied:
            return '(nothing denied)'
        return '\n'.join(f'  {path.name}: {reason}' for path, reason in self.denied)


def _is_log(rel: str) -> bool:
    return any(rel == path or rel.startswith(path) for path in LOG_PATHS)


def deny_reason(path: Path) -> str | None:
    """Why this file is bytes rather than prose, or None — meaning scan it."""
    if path.name in DENY_NAMES:
        return DENY_NAMES[path.name]
    return DENY_SUFFIXES.get(path.suffix.lower())


def take_census(root: Path = REPO_ROOT) -> Census:
    """Every file under `root`, classified — nothing dropped in silence.

    The worktree rather than `git ls-files`, deliberately: a rule-8 violation
    arrives as a NEW file, and a census taken from the index would not see it
    until somebody staged it — which is one commit too late.

    `root` is a parameter so the classifier can be exercised on a scratch tree
    holding the shapes this repo does not (and must not) contain: a planted
    consumer name, a non-UTF-8 tail, an unclassified binary.
    """
    census = Census([], [], [], [], [])
    for path in sorted(root.rglob('*')):
        if not path.is_file() or path.is_symlink():
            continue
        census.walked.append(path)
        rel = path.relative_to(root).as_posix()
        if set(Path(rel).parts) & NOT_CONTENT:
            census.tool_output.append(path)
        elif _is_log(rel):
            census.log.append(path)
        elif (reason := deny_reason(path)) is not None:
            census.denied.append((path, reason))
        else:
            census.scanned.append(path)
    return census


def scanned_files(root: Path = REPO_ROOT) -> list[Path]:
    """The files the name/path clauses below read."""
    return take_census(root).scanned


def offending_lines(path: Path, patterns: tuple[str, ...],
                    root: Path = REPO_ROOT) -> list[str]:
    """Findings for one file — including "I could not read it".

    A file this gate cannot decode is a file it cannot CLEAR, so the decode
    failure is a finding rather than a skip. This returned `[]` on
    `UnicodeDecodeError` until this release, which meant one stray byte
    anywhere in a file removed the whole file from the scan without a word: the
    planted name plus a two-byte tail passed the suite. Same shape as the write
    plane's own refusal (`godot/write.utf8_refusal_reason` — "not valid UTF-8
    (… at byte N) — refusing to rewrite bytes this tool cannot read"), stated
    here rather than imported, because nothing in the repo family may reach
    into the godot family (CLAUDE.md § Where things live).
    """
    rel = path.relative_to(root).as_posix()
    try:
        text = path.read_text(encoding='utf-8')
    except UnicodeDecodeError as err:
        return [f'{rel}:0: {UNREADABLE} — not valid UTF-8 ({err.reason} at byte '
                f'{err.start}); this gate cannot clear bytes it cannot read. If '
                f'the file is genuinely binary, give it a reason in '
                f'DENY_SUFFIXES or DENY_NAMES.']
    except OSError as err:
        return [f'{rel}:0: {UNREADABLE} — {err.strerror or err}; this gate '
                f'cannot clear a file it cannot open.']
    return [f'{rel}:{n}: {line.strip()[:120]}'
            for n, line in enumerate(text.splitlines(), 1)
            if any(re.search(p, line) for p in patterns)]


def _unreadable(hits: list[str]) -> list[str]:
    return [hit for hit in hits if f': {UNREADABLE} — ' in hit]


def test_the_census_is_not_empty_and_covers_the_package_and_the_harness():
    """The scan itself, before anything it claims. A glob that matched nothing
    would make every assertion below vacuously true — this package's cardinal
    sin wearing a green tick (CLAUDE.md rule 4)."""
    census = take_census()
    files = census.scanned
    assert len(files) >= FILE_FLOOR, (
        f'census collapsed to {len(files)} file(s), floor {FILE_FLOOR} — the '
        f'walk broke, or the tree shrank and this floor is now a lie. '
        f'{census.summary()}')
    tops = {path.relative_to(REPO_ROOT).parts[0] for path in files}
    for required in ('src', 'tests', 'CLAUDE.md', 'README.md', 'Makefile'):
        assert required in tops, f'{required} is outside the scan: {sorted(tops)}'


def test_the_census_accounts_for_every_file_it_walked():
    """The question the old census could not answer: what did you DROP?

    Both holes this gate shipped with hid behind a count of what the walk KEPT
    — 313 files, floor 120, green — while 21 files left the scan unnamed. The
    walk is repeated INDEPENDENTLY here rather than read off the census, so a
    silent `continue` growing back inside `take_census` stops covering this one
    and that is the failure.

    The comparison is over content only: the tool-output directories churn
    (`.pytest_cache` is written by the very run making this assertion), and a
    file that appears between the two walks would fail an equality that means
    nothing. Their accounting is still asserted — by the partition below, which
    is taken from a single snapshot.
    """
    census = take_census()
    independent = {path for path in REPO_ROOT.rglob('*')
                   if path.is_file() and not path.is_symlink()
                   and not set(path.relative_to(REPO_ROOT).parts) & NOT_CONTENT}
    unclassified = sorted(independent - census.content())
    assert not unclassified, (
        f'{len(unclassified)} file(s) left the census unclassified — the walk '
        f'dropped them without naming them, which is how a suffix allowlist '
        f'hides 18 files. {census.summary()}\n'
        + '\n'.join(str(path.relative_to(REPO_ROOT)) for path in unclassified[:25]))
    parts = (len(census.scanned) + len(census.log) + len(census.denied)
             + len(census.tool_output))
    assert parts == len(census.walked), (
        f'the four buckets do not partition the walk: {census.summary()}')
    assert len(census.classified()) == len(census.walked), (
        f'a file is in two buckets at once: {census.summary()}')


def test_nothing_that_reads_as_text_is_excluded_as_binary():
    """The deny list may only hold bytes, never prose.

    An exclusion that covers a readable file is a hole with a reason attached,
    and it would be permanent — nothing else looks at what this list drops.
    The tree denies nothing today, which `Census.summary()` reports out loud
    rather than leaving to be inferred; the live case is exercised on the
    scratch tree below, where a `.png` is both written and denied.
    """
    census = take_census()
    prose = []
    for path, reason in census.denied:
        try:
            path.read_text(encoding='utf-8')
        except (OSError, UnicodeDecodeError):
            continue
        prose.append(f'{path.relative_to(REPO_ROOT).as_posix()} (excluded as {reason})')
    assert not prose, (
        'these files are excluded from the rule-8 scan as binary and decode as '
        'UTF-8 — scan them instead of exempting them:\n' + '\n'.join(prose))


@pytest.mark.parametrize('rel, why', sorted(TOMBSTONES.items()))
def test_every_tombstone_still_earns_its_exemption(rel, why):
    """An allowlist entry that no longer needs to be there is an entry that
    will one day cover a real violation. Each must still spell a banned name —
    and must still be READABLE, because an exemption earned by a file nobody
    can decode is the skip this gate just stopped taking."""
    path = REPO_ROOT / rel
    assert path.is_file(), f'{rel} is allowlisted and does not exist ({why})'
    hits = offending_lines(path, CONSUMER_NAMES)
    assert not _unreadable(hits), (
        f'{rel} is allowlisted ({why}) and cannot be read:\n'
        + '\n'.join(_unreadable(hits)))
    assert hits, (
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


# --------------------------------------------------------------------------
# The census, attacked on a scratch tree.
#
# The two holes this gate shipped with were both proven by planting a consumer
# name in THIS repo and watching the suite stay green, which is a measurement
# nothing here can repeat: the repo must not contain a violation. So the
# classifier and the reader are pointed at a tree built to hold every shape
# that used to escape — an allowlist miss, a non-UTF-8 tail, a binary nobody
# classified — and each is asserted to produce a finding rather than a skip.
# --------------------------------------------------------------------------

# The planted violation, assembled from the pattern rather than spelled out.
# This file's whole exemption is that it holds no BARE consumer name (see the
# docstring), so a literal here would end it and force an entry in TOMBSTONES —
# which would then cover a real name added later. Same reason as the
# `[w]orkspace` spelling above: load-bearing, not a flourish.
PLANT = CONSUMER_NAMES[0].replace(r'\b', '') + ' is the consumer'


def _scratch_tree(root: Path) -> None:
    """A miniature of this repo's shapes, with no violation in it."""
    (root / 'src').mkdir()
    (root / 'pm').mkdir()
    (root / '.git').mkdir()
    (root / 'tests' / 'fixtures' / 'canon_repo').mkdir(parents=True)
    (root / 'src' / 'tool.py').write_text('print("hello")\n', encoding='utf-8')
    (root / 'README.md').write_text('a project whose check carries extra gates\n',
                                    encoding='utf-8')
    (root / 'tests' / 'fixtures' / 'canon_repo' / 'project.godot').write_text(
        '[application]\n\nconfig/name="props fixture"\n', encoding='utf-8')
    (root / 'tests' / 'fixtures' / 'canon_repo' / 'icon.svg.uid').write_text(
        'uid://abc\n', encoding='utf-8')
    (root / 'pm' / 'review.md').write_text(f'{PLANT}\n', encoding='utf-8')
    (root / '.git' / 'COMMIT_EDITMSG').write_text(f'{PLANT}\n', encoding='utf-8')


def _names_found(root: Path) -> list[str]:
    hits = []
    for path in scanned_files(root):
        hits.extend(offending_lines(path, CONSUMER_NAMES, root))
    return hits


class TestTheCensusOnAScratchTree:

    def test_a_name_in_a_project_godot_is_a_finding(self, tmp_path):
        """The exact file the suffix allowlist dropped, and the exact artifact
        a fixture gets vendored from. Ten of them are in this repo; a planted
        name in one passed all 1,761 tests before this release."""
        _scratch_tree(tmp_path)
        target = tmp_path / 'tests' / 'fixtures' / 'canon_repo' / 'project.godot'
        assert not _names_found(tmp_path), 'the scratch tree started dirty'
        target.write_text(target.read_text(encoding='utf-8') + f'\n; {PLANT}\n',
                          encoding='utf-8')
        hits = _names_found(tmp_path)
        assert any('project.godot' in hit for hit in hits), hits

    def test_a_name_in_a_uid_sidecar_is_a_finding(self, tmp_path):
        """`.uid` was the other dropped suffix — eight tracked files of it."""
        _scratch_tree(tmp_path)
        target = tmp_path / 'tests' / 'fixtures' / 'canon_repo' / 'icon.svg.uid'
        target.write_text(f'{PLANT}\n', encoding='utf-8')
        assert any('icon.svg.uid' in hit for hit in _names_found(tmp_path))

    def test_a_suffix_nobody_has_ever_seen_is_scanned_not_dropped(self, tmp_path):
        """The inversion, as a property: coverage by default, not by memory."""
        _scratch_tree(tmp_path)
        (tmp_path / 'src' / 'notes.wat').write_text(f'{PLANT}\n', encoding='utf-8')
        assert any('notes.wat' in hit for hit in _names_found(tmp_path))

    def test_a_non_utf8_tail_does_not_remove_a_file_from_the_scan(self, tmp_path):
        """Hole two, and the worse one: it is not suffix-bounded. The same
        planted name plus `\\xff\\xfe` turned one failure into eight passes."""
        _scratch_tree(tmp_path)
        target = tmp_path / 'src' / 'notes.md'
        target.write_bytes(PLANT.encode() + b'\n\xff\xfe binary tail\n')
        hits = _names_found(tmp_path)
        assert hits, 'a non-UTF-8 byte silently emptied the scan for this file'
        assert _unreadable(hits), hits
        assert 'not valid UTF-8' in hits[0] and 'src/notes.md' in hits[0], hits

    def test_an_unclassified_binary_is_a_finding_rather_than_a_skip(self, tmp_path):
        """A deny list that forgets a type must fail LOUDLY. This is what makes
        the list a convenience instead of a correctness dependency."""
        _scratch_tree(tmp_path)
        (tmp_path / 'src' / 'blob.dat').write_bytes(b'\x00\x01\xff\xfe\x00')
        hits = _names_found(tmp_path)
        assert _unreadable(hits) and 'blob.dat' in hits[0], hits

    def test_a_classified_binary_is_excluded_with_its_reason(self, tmp_path):
        """And a type that IS classified drops out quietly, carrying why."""
        _scratch_tree(tmp_path)
        (tmp_path / 'src' / 'logo.png').write_bytes(b'\x89PNG\r\n\x1a\n\xff\xfe')
        census = take_census(tmp_path)
        denied = {path.name: reason for path, reason in census.denied}
        assert denied == {'logo.png': 'raster image'}, denied
        assert not _names_found(tmp_path)

    def test_the_log_and_the_tool_output_stay_out_of_the_scan(self, tmp_path):
        """Both scratch plants live in excluded trees, and both must stay
        excluded — the LOG is a dated record and `.git` is not content."""
        _scratch_tree(tmp_path)
        census = take_census(tmp_path)
        assert [path.name for path in census.log] == ['review.md']
        assert [path.name for path in census.tool_output] == ['COMMIT_EDITMSG']
        assert not _names_found(tmp_path)

    def test_every_walked_file_lands_in_exactly_one_bucket(self, tmp_path):
        """The accounting property, on a tree small enough to enumerate."""
        _scratch_tree(tmp_path)
        (tmp_path / 'src' / 'logo.png').write_bytes(b'\x89PNG\r\n')
        census = take_census(tmp_path)
        assert len(census.walked) == 7, census.summary()
        assert len(census.classified()) == len(census.walked), census.summary()
        assert (len(census.scanned) + len(census.log) + len(census.denied)
                + len(census.tool_output)) == len(census.walked), census.summary()

    def test_the_census_reports_what_it_dropped(self, tmp_path):
        """A census that cannot name its exclusions is how both holes hid."""
        _scratch_tree(tmp_path)
        (tmp_path / 'src' / 'logo.png').write_bytes(b'\x89PNG\r\n')
        census = take_census(tmp_path)
        assert census.denied_report() == '  logo.png: raster image'
        assert '1 denied' in census.summary()
