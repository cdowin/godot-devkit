"""Hard rule 8, as a gate — this package knows nothing about its consumers.

The rule in one line: no file here names a consuming project, reads a path
outside this checkout, or gates on another repo's content or working state. It
is a gate rather than a convention because the alternative was measured: a
release gate once ran every verb against whichever private consumer checkout
was cloned on the machine, SKIPPED in CI where none was, and so gave a verdict
that depended on whose laptop asked. A gate somebody else's uncommitted work
can redden is not a gate.

WHY THE BANNED NAMES LIVE HERE. Naming them is itself consumer knowledge, so
exactly one place in the tree may hold them: this file, as a tombstone —
`tests/` is the harness, not the package. Files allowed to spell a banned name
go in TOMBSTONES with a reason, and each must still earn its exemption. This
file needs none: it spells the names only inside `\\b...\\b` regexes, which the
same regexes do not match.

WHAT IS SCANNED. Everything under the checkout, as a DENY list: the exclusions
are enumerated with a reason each, and the default for a file type nobody
thought of is SCANNED — an allowlist of suffixes once dropped 21 files in
silence, including every fixture `project.godot`, which is exactly the
artifact a fixture gets vendored FROM a consumer. `pm/`, `CHANGELOG.md` and
`docs/reviews/` are the LOG, dated records of what was measured, and are
excluded by path rather than rewritten. A file this gate cannot DECODE is a
finding, not a skip: one stray non-UTF-8 byte used to remove a whole file from
the scan without a word (rule 4).
"""
from __future__ import annotations

import re
from pathlib import Path

from support import REPO_ROOT
from support import consumers

# The names themselves are maintainer configuration and are NOT in this tree:
# a public guard that spells the list it bans publishes exactly what it exists
# to keep out — and it hid, because a word-bounded search for a name does not
# match that name inside `\\b...\\b` (the `b` of `\\b` is a word character). See
# tests/support/consumers.py; word-bounded there on purpose, because the
# committed corpus is a hiking game's data and legitimately spells
# `trail_mile`, domain vocabulary rather than a project reference.
# PLANTED is synthetic, so the mechanism test below runs configured or not.
PLANTED = 'acmegame'
PLANTED_PATTERN = (rf'(?i)\b{PLANTED}\b',)
# Reaching OUTSIDE the checkout, as literals. A path handed in on the command
# line is the caller's choice; what is banned is the package deciding on its
# own to look elsewhere. `[w]orkspace` matches the same text while keeping THIS
# line out of its own census — load-bearing, not a typo.
OUTSIDE_READS = (r'~/[w]orkspace', r'Path\.home\(\)', r'os\.path\.expanduser\(\s*[\'"]~',
                 r'\$HOME/[w]orkspace', r'os\.environ\[[\'"]HOME[\'"]\]\s*\)?\s*/')
LOG_PATHS = ('pm/', 'docs/reviews/', 'CHANGELOG.md')
# Tool output, not authored content: `.venv` is third-party code and `.git`
# holds every byte the tree ever had. Adding a name here is a visible act.
NOT_CONTENT = {'.git', '.gate-reports', '.pytest_cache', '.ruff_cache', '.venv',
               '__pycache__', 'node_modules', '.mypy_cache'}
# The deny-list this gate sweeps FOR necessarily spells every name. Gitignored,
# never committed, and excluded by name rather than tombstoned: a tombstone is
# for a file in the tree, and this one only exists on a maintainer's disk.
NOT_CONTENT_FILES = {'.consumer-names'}
# Other checkouts of this repo that `tools/dev/agent-worktree.sh` plants inside
# this one (gitignored). Each is its own tree and is swept by its own run; read
# from here, its pm/ is not under LOG_PATHS and its log prose reads as a finding.
OTHER_CHECKOUTS = ('.claude/worktrees/',)
TOMBSTONES: dict[str, str] = {
    # Empty since 0.25.0: no file in the tree needs to spell a banned name.
}
# Bytes, not prose, by lowercased suffix or exact name — none can hold a
# sentence. A convenience, never a correctness dependency: a binary type NOT
# here fails to decode, and that is a finding.
DENY_SUFFIXES = {'.png', '.jpg', '.jpeg', '.gif', '.webp', '.ico', '.ttf', '.otf', '.woff',
                 '.woff2', '.wav', '.ogg', '.zip', '.gz', '.tar', '.whl', '.pyc', '.pyo',
                 '.so', '.dylib', '.dll', '.res', '.scn', '.ctex'}
DENY_NAMES = {'.DS_Store'}
# Rule 4: a census that collapses must FAIL. The tree is ~330 content files.
FILE_FLOOR = 120


def scanned_files(root: Path = REPO_ROOT) -> list[Path]:
    """Every file under `root` that is content and prose. The worktree rather
    than `git ls-files`, deliberately: a rule-8 violation arrives as a NEW file,
    and an index census would not see it until somebody staged it."""
    out = []
    for path in sorted(root.rglob('*')):
        rel = path.relative_to(root)
        if (not path.is_file() or path.is_symlink() or set(rel.parts) & NOT_CONTENT
                or rel.as_posix() in NOT_CONTENT_FILES
                or rel.as_posix().startswith(LOG_PATHS + OTHER_CHECKOUTS)
                or path.name in DENY_NAMES or path.suffix.lower() in DENY_SUFFIXES):
            continue
        out.append(path)
    return out


def offending_lines(path: Path, patterns: tuple[str, ...], root: Path = REPO_ROOT) -> list[str]:
    """Findings for one file — including "I could not read it"."""
    rel = path.relative_to(root).as_posix()
    try:
        text = path.read_text(encoding='utf-8')
    except (UnicodeDecodeError, OSError) as err:
        return [f'{rel}:0: UNREADABLE — {err}; this gate cannot clear bytes it cannot read. '
                'If the file is genuinely binary, give it a reason in DENY_SUFFIXES or DENY_NAMES.']
    return [f'{rel}:{n}: {line.strip()[:120]}' for n, line in enumerate(text.splitlines(), 1)
            if any(re.search(p, line) for p in patterns)]


def test_no_file_names_a_consumer_or_reaches_outside_this_checkout():
    """Both clauses of the rule, over the whole tree, after the scan has proven
    it saw the tree. A worked example names a SHAPE — "a project whose `check`
    carries extra gates" — never a repo; a check that needs realistic data
    VENDORS it under tests/fixtures/."""
    files = scanned_files()
    assert len(files) >= FILE_FLOOR, (
        f'census collapsed to {len(files)} file(s), floor {FILE_FLOOR} — the walk broke, '
        'or the tree shrank and this floor is now a lie')
    tops = {path.relative_to(REPO_ROOT).parts[0] for path in files}
    assert {'src', 'tests', 'CLAUDE.md', 'README.md', 'Makefile'} <= tops, sorted(tops)
    patterns = consumers.require()
    names: list[str] = []
    outside: list[str] = []
    for path in files:
        rel = path.relative_to(REPO_ROOT).as_posix()
        hits = offending_lines(path, patterns)
        if rel in TOMBSTONES:   # an exemption is earned by a readable file that still needs it
            assert hits and 'UNREADABLE' not in hits[0], (
                f'{rel}: its exemption ({TOMBSTONES[rel]}) covers nothing — delete it from TOMBSTONES')
        else:
            names += hits
        outside += offending_lines(path, OUTSIDE_READS)
    assert not names, ('a consuming project is named in the tool (CLAUDE.md hard rule 8). '
                       'Rewrite the sentence generically:\n' + '\n'.join(names[:25]))
    assert not outside, ('something reads a path outside this checkout (CLAUDE.md hard rule 8):\n'
                         + '\n'.join(outside[:25]))


def test_the_scan_catches_every_shape_that_used_to_escape(tmp_path):
    """The repo must not contain a violation, so the classifier and the reader
    are attacked on a scratch tree instead: a planted name under a suffix
    nobody classified (scanned by default), the same name plus a non-UTF-8
    tail (a finding, not a silent skip), a denied binary and a tool-output
    directory (excluded, and nothing else)."""
    plant = f'{PLANTED} is the consumer\n'
    (tmp_path / 'src').mkdir()
    (tmp_path / '.git').mkdir()
    (tmp_path / '.git' / 'COMMIT_EDITMSG').write_text(plant, encoding='utf-8')
    (tmp_path / 'src' / 'notes.wat').write_text(plant, encoding='utf-8')
    (tmp_path / 'src' / 'notes.md').write_bytes(plant.encode() + b'\xff\xfe binary tail\n')
    (tmp_path / 'src' / 'logo.png').write_bytes(b'\x89PNG\r\n')
    hits = [hit for path in scanned_files(tmp_path)
            for hit in offending_lines(path, PLANTED_PATTERN, tmp_path)]
    assert sorted(hit.split(':')[0] for hit in hits) == ['src/notes.md', 'src/notes.wat'], hits
    assert any('src/notes.md:0: UNREADABLE' in hit for hit in hits), hits
