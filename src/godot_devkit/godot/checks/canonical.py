"""check canonical — no `.tres` value may be spelled, or placed, other than the way Godot's saver writes it.

The churn this gate exists for is the same as `check defaults`'s, in the two
dimensions that one leaves out: an editor save of a hand-authored resource
re-spells its floats (`0.30` -> `0.3`), wraps a bare list on a typed-array
export (`[a, b]` -> `Array[T]([a, b])`) and moves its properties into
declaration order — so the file diffs on every save until one form wins, and
the bulk re-save that would settle it empties resources, deletes every `;`
comment and drops every `uid=`.

CHECK (HARD): for every `[resource]` / `[sub_resource]` in a tracked `.tres`,
              no property may be spelled or positioned other than as the saver
              would write it, where a parse can PROVE how the saver writes it.

SCOPE — read this before wiring it in. What is judged is exactly what
`scene canonicalize --respell --order` fixes, and nothing else:

  * floats, in the saver's shortest round-trip spelling — only where the
    32- and 64-bit spellings agree, so the verdict never depends on a build;
  * a bare list on an `@export var x: Array[T]`, where T is a builtin, an
    engine class, or a `class_name` script the file already references;
  * the order of a scripted section's properties — only where every key is
    `script` or one of the script's `@export`s. An engine property's place is
    not in the ClassDB snapshot, so such a section is counted, not judged.

Anything else — an engine-typed float, an enum element type, an export with
an accessor — is censused as NOT A FINDING and never reported. A PASS means
"nothing provable drifts", not "the editor would leave this file alone";
default elision is `check defaults`'s, and a `;` comment is `check
tres-comment`'s. Out of `check all` unless `[checks] godot` names it: a pin
bump must not redden a tree that was never canonicalized.

Fix a finding with `godot-devkit scene canonicalize --respell --order <file>`.

devkit.toml: [canonical] exclude_prefixes = ["addons/"]
"""
from __future__ import annotations

from collections import Counter
from pathlib import Path

from godot_devkit.core.config import config_section, str_tuple
from godot_devkit.core.project import git_lines, repo_root
from godot_devkit.godot import VENDORED_DEFAULT
from godot_devkit.godot.format.tscn_document import TscnDocument, read_scene_text
from godot_devkit.godot.index.gdscript import ScriptIndex
from godot_devkit.godot.index.resource_canonical import CanonicalAnalyzer

CONFIG_SECTION = 'canonical'
EXIT_OK = 0
EXIT_FINDINGS = 1
MAX_LISTED = 40
NOT_UTF8 = 'file is not UTF-8 (unread)'
GATE = '[check:canonical]'


def run() -> int:
    root = repo_root()
    config = config_section(CONFIG_SECTION)
    exclude = str_tuple(config, CONFIG_SECTION, 'exclude_prefixes', VENDORED_DEFAULT)
    scripts = ScriptIndex(root, [p for p in git_lines('ls-files', '*.gd')
                                 if not p.startswith(exclude)])
    files = [p for p in git_lines('ls-files', '*.tres') if not p.startswith(exclude)]
    return report(root, files, CanonicalAnalyzer(scripts))


def findings_of(root: Path, rel: str, analyzer: CanonicalAnalyzer,
                census: Counter) -> list[str] | None:
    """One `  DRIFT  …` line per drifting property of one file; None if unread."""
    try:
        doc = TscnDocument(read_scene_text(root / rel))
    except UnicodeDecodeError:
        census[NOT_UTF8] += 1
        return None
    analysis = analyzer.analyze(doc.lines, doc.sections, census)
    lines = [f'  DRIFT  {rel} : {item.where}.{item.prop.key} = {item.prop.value} '
             f'— the saver writes {", ".join(item.changes)}'
             for item in analysis.rewrites]
    for item in analysis.reorders:
        lines += [f'  DRIFT  {rel} : {item.where}.{prop.key} — the saver writes it '
                  f'at position {position} of {len(item.order)} (declaration order)'
                  for prop, position in item.moved]
    return lines


def report(root: Path, files: list[str], analyzer: CanonicalAnalyzer) -> int:
    """Judge `files` (repo-relative) and print the verdict; -> the exit code."""
    census: Counter = Counter()
    findings: list[str] = []
    scanned = 0
    dirty = 0
    print(f'{GATE} CHECK — .tres value spelling and property order match '
          f'what Godot\'s saver writes, where a parse can prove it')
    for rel in files:
        lines = findings_of(root, rel, analyzer, census)
        if lines is None:
            continue
        scanned += 1
        dirty += bool(lines)
        findings += lines
    for line in findings[:MAX_LISTED]:
        print(line)
    if len(findings) > MAX_LISTED:
        print(f'  … and {len(findings) - MAX_LISTED} more')
    census_line = ', '.join(f'{count} {reason}' for reason, count in census.most_common())
    if scanned == 0:
        print(f'{GATE} FAIL — scanned 0 files; check [{CONFIG_SECTION}] exclude_prefixes')
        return EXIT_FINDINGS
    if findings:
        print(f'{GATE} FAIL — {len(findings)} drifting propert(ies) in {dirty} of '
              f'{scanned} .tres file(s); Godot\'s saver will rewrite them on the '
              f'next editor save')
        print('  Fix: godot-devkit scene canonicalize --respell --order <file>...')
        print(f'  NOT A FINDING: {census_line or "none"}')
        return EXIT_FINDINGS
    print(f'{GATE} PASS — no provable spelling or order drift in {scanned} .tres file(s)')
    print(f'  NOT A FINDING: {census_line or "none"}')
    return EXIT_OK
