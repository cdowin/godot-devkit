"""check defaults — no `.tres` assignment may repeat its script's declared default.

The churn this gate exists for: hand-authored `.tres` spell every property out,
Godot's writer omits any whose value equals the declared default. Hold one form,
open the editor, and the file diffs forever — `git checkout --` on ~20 files per
session, every session, for months, misdiagnosed the whole time as "a headless
boot re-serialises resources" (it does not; a full sandboxed headless run dirties
nothing).

CHECK (HARD): for every scripted `[resource]` / `[sub_resource]` in a tracked
              `.tres`, no assignment may equal the `@export`'s declared default.

SCOPE — read this before wiring it in. This judges ONE dimension of what Godot's
writer would emit: property elision. The writer also reorders properties into
declaration order, respells typed arrays (`[a, b]` -> `Array[Resource]([a, b])`)
and floats (`0.30` -> `0.3`), mints `ext_resource` entries for typed-array
element types, and drops every `;` comment in the file. A PASS here means "no
redundant defaults", NOT "the editor would leave this file alone". Saying more
than that would be the false-PASS sin; the other dimensions are not decidable by
parse, because reproducing them means reimplementing `ResourceFormatSaverText`.

Precision is the design constraint, exactly as in `check props`. Both sides of
every comparison must normalise into one small closed value language, or the
assignment is censused as UNVERIFIED and never reported. Fix a finding with
`godot-devkit scene canonicalize --elide-defaults <file>`.

devkit.toml: [defaults] exclude_prefixes = ["addons/"]
"""
from __future__ import annotations

from collections import Counter

from godot_devkit.godot.index.gdscript import ScriptIndex
from godot_devkit.core.project import git_lines, load_config, repo_root
from godot_devkit.core.config import config_section, str_tuple
from godot_devkit.godot.index.resource_defaults import DefaultAnalyzer
from godot_devkit.godot.format.tscn import parse

DEFAULT_EXCLUDE = ('addons/',)
CONFIG_SECTION = 'defaults'
EXIT_OK = 0
EXIT_FINDINGS = 1
MAX_LISTED = 40


def run() -> int:
    root = repo_root()
    config = config_section(CONFIG_SECTION)
    exclude = tuple(config.get('exclude_prefixes', DEFAULT_EXCLUDE))

    scripts = ScriptIndex(root, [p for p in git_lines('ls-files', '*.gd')
                                 if not p.startswith(exclude)])
    analyzer = DefaultAnalyzer(scripts)
    census: Counter = Counter()
    findings: list[str] = []
    files = 0
    dirty_files = 0

    print('[check:defaults] CHECK — no .tres assignment repeats its script\'s '
          'declared @export default')
    for rel in git_lines('ls-files', '*.tres'):
        if rel.startswith(exclude):
            continue
        files += 1
        redundant = analyzer.analyze(parse(str(root / rel)), census)
        if redundant:
            dirty_files += 1
        for item in redundant:
            findings.append(
                f'  REDUNDANT  {rel} : {item.where}.{item.prop.key} = '
                f'{item.prop.value} — equals the declared default '
                f'({item.default})')

    for line in findings[:MAX_LISTED]:
        print(line)
    if len(findings) > MAX_LISTED:
        print(f'  … and {len(findings) - MAX_LISTED} more')
    census_line = ', '.join(f'{count} {reason}'
                            for reason, count in census.most_common())
    if files == 0:
        print('[check:defaults] FAIL — scanned 0 files; check '
              '[defaults] exclude_prefixes')
        return EXIT_FINDINGS
    if findings:
        print(f'[check:defaults] FAIL — {len(findings)} redundant assignment(s) '
              f'in {dirty_files} of {files} .tres file(s); Godot\'s writer will '
              f'delete them on the next editor save')
        print('  Fix: godot-devkit scene canonicalize --elide-defaults <file>...')
        print(f'  NOT A FINDING: {census_line or "none"}')
        return EXIT_FINDINGS
    print(f'[check:defaults] PASS — no redundant default assignment in '
          f'{files} .tres file(s)')
    print(f'  NOT A FINDING: {census_line or "none"}')
    return EXIT_OK
