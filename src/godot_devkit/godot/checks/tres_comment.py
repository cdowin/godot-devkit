"""tres_comment.py — check tres-comment: no authored comment in a file Godot rewrites.

Godot's `.tres`/`.tscn` serializer does not round-trip comments. The parser
accepts a leading-`;` line and the writer DROPS it, so rationale authored into
a resource survives only until the next editor save, import or headless run
re-serializes that file — at which point it is gone, silently and permanently,
with no diff to notice. A corpus of hundreds of such lines is hundreds of
explanations one re-serialize from deletion.

The fix is that durable rationale lives where it is durable: the owning
directory's README, or the project's specs. This gate makes that a build
failure instead of a convention, so the corpus cannot regrow.

  CHECK 1  no tracked `.tres`/`.tscn` in scope has a line starting with `;`.

HONEST SCOPE: the match is `^;` on a RAW line, and that is what makes it a hard
gate rather than a heuristic. Godot writes multi-line strings with escaped `\\n`
and packed data as one-line base64, so a real newline followed by a column-0
`;` cannot occur inside a value the engine wrote. `addons/` is excluded by
default: vendored plugin resources are not ours to rewrite.

devkit.toml:

    [tres_comment]
    exclude_prefixes = ["addons/", "tests/fixtures/"]
"""
from __future__ import annotations

from godot_devkit.core.config import config_section, str_tuple
from godot_devkit.core.project import git_lines, repo_root

SECTION = 'tres_comment'
TAG = '[check:tres-comment]'
SUFFIXES = ('.tres', '.tscn')
DEFAULT_EXCLUDE_PREFIXES = ('addons/',)
# The one shape this gate forbids: a resource-file line that opens with `;`.
COMMENT_PREFIX = ';'


def comment_lines(text: str) -> list[tuple[int, str]]:
    """`(lineno, line)` for every authored comment in one resource file."""
    return [(n, line) for n, line in enumerate(text.split('\n'), start=1)
            if line.startswith(COMMENT_PREFIX)]


def run() -> int:
    sect = config_section(SECTION)
    excluded = str_tuple(sect, SECTION, 'exclude_prefixes',
                         DEFAULT_EXCLUDE_PREFIXES)
    root = repo_root()
    tracked = [rel for rel in git_lines('ls-files')
               if rel.endswith(SUFFIXES)]
    scanned = [rel for rel in tracked
               if not rel.startswith(tuple(excluded))]
    if not scanned:
        # Rule 4 — a gate that scanned nothing must say so, and it must say
        # WHICH of the two reasons applies: an empty tree and an exclude that
        # ate the census are different problems with the same silent PASS.
        print(f'{TAG} FAIL — scanned 0 of {len(tracked)} tracked '
              f'{"/".join(SUFFIXES)}; check [{SECTION}] exclude_prefixes')
        return 1

    findings: list[str] = []
    for rel in scanned:
        try:
            text = (root / rel).read_text(encoding='utf-8', errors='replace')
        except OSError:
            continue
        findings.extend(f'  STRIPPED  {rel}:{n}:{line}'
                        for n, line in comment_lines(text))

    if findings:
        for finding in findings:
            print(finding)
        print(f'\n{TAG} FAIL — {len(findings)} authored comment line(s) in '
              f'Godot-rewritten files, across {len(scanned)} scanned')
        print("  Godot's serializer drops these on the next editor save / "
              'import / headless run.')
        print('  Whatever they say is one re-serialize away from being gone, '
              'with no diff to notice.')
        print("  Move durable rationale to the owning directory's README or a "
              'spec; delete it if it only restates the field beside it.')
        return 1

    print(f'{TAG} PASS — {len(scanned)} of {len(tracked)} tracked resource '
          f'file(s) carry no authored comments')
    return 0
