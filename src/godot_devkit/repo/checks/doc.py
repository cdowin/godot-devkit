#!/usr/bin/env python3
"""doc_scan.py — verifies claims in the ALWAYS-LOADED docs against the live tree.

Sibling of uid_scan.sh / capability_scan.sh: a fast, static gate over
CLAUDE.md + .claude/rules/*.md + .claude/agents/*.md that catches the class
of drift the doc-hygiene agent otherwise has to grep-verify by hand — a dead
`res://` path, a `make <target>` that no longer exists, a markdown link to a
moved file. NOT a substitute for doc-hygiene's judgment (duplication, scope
creep, "is this claim still true" symbol-identity checks) — just the
objectively-checkable subset: does this path/link/make-target resolve.

Deliberately scoped to INLINE single-backtick spans and markdown links —
fenced ``` code blocks are skipped entirely (they're illustrative command
examples full of `<placeholder>` syntax, not precise claims; the project's
own docs confirm this split empirically: every real `make <target>`
invocation in-repo is backtick-wrapped, every bare "make sense"/"make it"
false-positive is prose). An UNTERMINATED fence skips nothing and is
REPORTED: a marker that hides the rest of a file must never do it in
silence. A line ending in `<!-- doc-scan:allow -->` is
never flagged (the capability-scan inline-marker doctrine, applied here).
Pure parse — never writes, never boots Godot.

    make doc-scan
    python3 tools/dev/checks/doc_scan.py
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path
from godot_devkit.core.markdown import non_fenced_lines
from godot_devkit.core import walk
from godot_devkit.core.walk import Kind
from godot_devkit.core.project import repo_root
from godot_devkit.core.config import config_section, str_tuple

REPO_ROOT = repo_root()
_CFG = config_section('doc')
DEFAULT_SCOPE = ('CLAUDE.md', '.claude/rules/*.md', '.claude/agents/*.md')
SCOPE_GLOBS = str_tuple(_CFG, 'doc', 'scope', DEFAULT_SCOPE)
MAKEFILE = REPO_ROOT / 'Makefile'
ALLOW_MARKER = 'doc-scan:allow'

INLINE_CODE = re.compile(r'`([^`]+)`')
MD_LINK_TEXT = re.compile(r'`[^`]+`\]\(')  # a backtick span used as [`text`](href) link text —
                                            # its path claim is the link's real href, checked separately
MD_LINK = re.compile(r'\[[^\]]*\]\(([^)]+)\)')
MAKE_TARGET_RECIPE = re.compile(r'^([a-zA-Z][a-zA-Z0-9_-]*):', re.MULTILINE)
MAKE_INVOCATION = re.compile(r'\bmake\s+([a-zA-Z][a-zA-Z0-9_-]*)')
PATH_CANDIDATE = re.compile(r'^[A-Za-z0-9_./-]+\.(gd|tscn|tres|py|sh|md)$')
PLACEHOLDER_CHARS = ('<', '>', '*', '$')
URL_PREFIXES = ('http://', 'https://', 'mailto:')
# docs/reviews/ is create-resolve-DELETE by design (docs/reviews/README.md) — an
# example filename cited there is expected to no longer exist, not a claim.
DEFAULT_EPHEMERAL = ('docs/reviews/',)
EPHEMERAL_DIRS = str_tuple(_CFG, 'doc', 'ephemeral', DEFAULT_EPHEMERAL)


def scope_files() -> list[Path]:
    files: list[Path] = []
    for pattern in SCOPE_GLOBS:
        if '*' in pattern:
            files.extend(walk.matching(REPO_ROOT, pattern, Kind.FILE).kept)
        else:
            literal = REPO_ROOT / pattern
            if literal.is_file():
                files.append(literal)
    return files


def real_make_targets() -> set[str]:
    """Every recipe name the Makefile actually defines.

    A repo with no Makefile has no make targets — an empty set, not a crash.
    (Any `make x` a doc still claims is then reported as dead, which is right.)
    """
    if not MAKEFILE.is_file():
        return set()
    text = MAKEFILE.read_text(encoding='utf-8', errors='replace')
    return set(MAKE_TARGET_RECIPE.findall(text))


def is_allowed(line: str) -> bool:
    return ALLOW_MARKER in line


def resolve_path(candidate: str, relative_to: Path) -> bool:
    candidate = candidate.removeprefix('res://')
    if candidate.startswith(EPHEMERAL_DIRS):
        return True
    if (relative_to.parent / candidate).exists():
        return True
    return (REPO_ROOT / candidate).exists()


def check_links(doc: Path, lines: list[tuple[int, str]]) -> list[str]:
    findings: list[str] = []
    for lineno, line in lines:
        if is_allowed(line):
            continue
        for target in MD_LINK.findall(line):
            path_part = target.split('#', 1)[0].strip()
            if not path_part or target.startswith(URL_PREFIXES):
                continue
            if not resolve_path(path_part, doc):
                findings.append(f'{doc.relative_to(REPO_ROOT)}:{lineno}  dead link target: {target}')
    return findings


def check_make_targets(doc: Path, lines: list[tuple[int, str]], real_targets: set[str]) -> list[str]:
    findings: list[str] = []
    for lineno, line in lines:
        if is_allowed(line):
            continue
        for span in INLINE_CODE.findall(line):
            for match in MAKE_INVOCATION.finditer(span):
                target = match.group(1)
                if target not in real_targets:
                    findings.append(f'{doc.relative_to(REPO_ROOT)}:{lineno}  unknown make target: `make {target}`')
    return findings


def check_backtick_paths(doc: Path, lines: list[tuple[int, str]]) -> list[str]:
    findings: list[str] = []
    for lineno, line in lines:
        if is_allowed(line):
            continue
        link_text_ends = {m.end() for m in MD_LINK_TEXT.finditer(line)}
        for match in INLINE_CODE.finditer(line):
            if match.end() + 2 in link_text_ends:  # `text`](  — the '](' follows right after
                continue
            span = match.group(1)
            if '/' not in span or any(ch in span for ch in PLACEHOLDER_CHARS):
                continue
            if not PATH_CANDIDATE.match(span):
                continue
            if not resolve_path(span, doc):
                findings.append(f'{doc.relative_to(REPO_ROOT)}:{lineno}  dead path: `{span}`')
    return findings


def run() -> int:
    real_targets = real_make_targets()
    findings: list[str] = []
    defects: list[str] = []
    skipped = 0
    docs = scope_files()
    for doc in docs:
        text = doc.read_text(encoding='utf-8', errors='replace')
        lines, unterminated = non_fenced_lines(text)
        skipped += len(text.split('\n')) - len(lines)
        if unterminated:
            # The fence masked nothing (core/markdown.py), so the claims below
            # are still checked — but a document whose fences this gate cannot
            # delimit is a document it has not honestly scanned, and saying so
            # is the whole difference between this and the silent PASS a stray
            # marker used to buy.
            defects.append(
                f'{doc.relative_to(REPO_ROOT)}:{unterminated}  opens a code '
                f'fence that is never terminated — the rest of the file was '
                f'scanned UNMASKED; close the fence, or shorten the run of '
                f'backticks if you meant an inline span')
        findings.extend(check_links(doc, lines))
        findings.extend(check_make_targets(doc, lines, real_targets))
        findings.extend(check_backtick_paths(doc, lines))

    if findings or defects:
        counts = ', '.join(
            part for part in (
                f'{len(findings)} unresolved claim(s)' if findings else '',
                f'{len(defects)} malformed doc(s)' if defects else '') if part)
        # The census rides the FAIL line too, exactly as it rides the PASS. A
        # verdict that does not say what was read is half a verdict whichever
        # way it went — "1 malformed doc(s)" out of one doc and out of two
        # hundred are different reports, and only one of them printed.
        print(f'[check:doc] FAIL — {counts}, across {len(docs)} doc(s), '
              f'{skipped} fenced line(s) skipped')
        for finding in sorted(defects) + sorted(findings):
            print(f'  {finding}')
        print(f'\nA genuine exception (a deliberate retired-thing citation) gets a trailing '
              f'<!-- {ALLOW_MARKER} --> on its line, not a code change.')
        return 1

    if not docs:
        # Rule 4 — a gate that scanned nothing must say so. A misconfigured
        # exclude or a wrong root is indistinguishable from a clean tree,
        # and that PASS is the most dangerous output this package emits.
        print('[check:doc] FAIL — scanned 0 docs; check [doc] scope')
        return 1
    # The census counts FILES, and files are not what a fence hides. What was
    # SKIPPED is the other half of "what did this gate actually read", and a
    # PASS that never says it is a PASS over an unknown amount of unread text.
    print(f'[check:doc] PASS — {len(docs)} doc(s), {skipped} fenced line(s) '
          f'skipped, 0 unresolved claims')
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.parse_args(argv)
    return run()


if __name__ == '__main__':
    raise SystemExit(main())
