#!/usr/bin/env python3
"""gen_classdb.py — regenerate `src/godot_devkit/data/classdb.json`.

The `check props` gate needs to know which assigned scene properties are ENGINE
built-ins (`position`, `texture`, `layer`, ...) so it can tell them apart from a
script's `@export`s. That knowledge lives in Godot's ClassDB, which we snapshot
ONCE into a static data file — the gate itself stays pure-parse and never boots
Godot.

Regenerate when the target Godot minor version moves:

    godot --headless --dump-extension-api        # writes ./extension_api.json
    python3 tools/gen_classdb.py extension_api.json

Only Object/Node/Resource descendants are kept (those are the classes that can
appear as a `type=` in a .tscn/.tres); the editor-only and server singletons are
dropped to keep the shipped file small.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / 'src' / 'godot_devkit' / 'data' / 'classdb.json'
# A scene/resource file can only instantiate something in these hierarchies.
KEPT_ROOTS = ('Node', 'Resource', 'Object')


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print(__doc__.strip(), file=sys.stderr)
        return 2
    api = json.loads(Path(argv[0]).read_text(encoding='utf-8'))
    classes = {c['name']: c for c in api['classes']}

    def roots_to(name: str) -> bool:
        seen = set()
        while name and name not in seen:
            if name in KEPT_ROOTS:
                return True
            seen.add(name)
            name = classes.get(name, {}).get('inherits')
        return False

    table = {
        name: {
            'inherits': cls.get('inherits'),
            'props': sorted({p['name'] for p in cls.get('properties', [])}),
        }
        for name, cls in classes.items() if roots_to(name)
    }
    payload = {
        'godot_version': '{version_major}.{version_minor}.{version_patch}'.format(
            **api['header']),
        'classes': table,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, separators=(',', ':'), sort_keys=True) + '\n',
                   encoding='utf-8')
    props = sum(len(v['props']) for v in table.values())
    print(f'{OUT}: {len(table)} classes, {props} properties '
          f'(Godot {payload["godot_version"]})')
    return 0


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))
