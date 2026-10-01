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

The file also carries the engine's method and signal NAMES (`engine_methods`,
`engine_signals`, stamped `names_from`): `refs --rename` refuses a name the
engine also owns, because without types `x.play()` or a Button's
`[connection signal="pressed"]` may be the engine's. A full regeneration
writes them from the same dump; to refresh ONLY the names, leaving every other
key byte-identical:

    python3 tools/gen_classdb.py --names-only extension_api.json

The names may come from a NEWER dump than the props. That is the safe
direction: a name a newer engine adds only adds a refusal (a rename declines
that it could have made), while a props table from the wrong engine would make
`check props` pass or fail scenes it should not.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / 'src' / 'godot_devkit' / 'data' / 'classdb.json'
# A scene/resource file can only instantiate something in these hierarchies.
KEPT_ROOTS = ('Node', 'Resource', 'Object')
NAMES_ONLY = '--names-only'


def engine_names(api: dict) -> dict:
    """Every method name the engine owns — on any class, any builtin type, or a
    utility function — and every class signal name, each sorted and unique."""
    methods = {f['name'] for f in api.get('utility_functions', [])}
    for group in ('classes', 'builtin_classes'):
        for cls in api.get(group, []):
            methods.update(m['name'] for m in cls.get('methods', []))
    signals = {s['name'] for cls in api.get('classes', []) for s in cls.get('signals', [])}
    return {
        'engine_methods': sorted(methods),
        'engine_signals': sorted(signals),
        'names_from': api['header']['version_full_name'],
    }


def write(payload: dict) -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, separators=(',', ':'), sort_keys=True) + '\n',
                   encoding='utf-8')


def main(argv: list[str]) -> int:
    names_only = argv[:1] == [NAMES_ONLY]
    if names_only:
        argv = argv[1:]
    if len(argv) != 1:
        print(__doc__.strip(), file=sys.stderr)
        return 2
    api = json.loads(Path(argv[0]).read_text(encoding='utf-8'))
    names = engine_names(api)
    if names_only:
        if not OUT.is_file():
            print(f'{OUT}: missing — {NAMES_ONLY} merges into an existing file; '
                  f'run a full regeneration first', file=sys.stderr)
            return 2
        payload = json.loads(OUT.read_text(encoding='utf-8'))
        payload.update(names)
        write(payload)
        print(f'{OUT}: {len(names["engine_methods"])} engine methods, '
              f'{len(names["engine_signals"])} engine signals ({names["names_from"]}); '
              f'every other key untouched')
        return 0
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
        **names,
    }
    write(payload)
    props = sum(len(v['props']) for v in table.values())
    print(f'{OUT}: {len(table)} classes, {props} properties, '
          f'{len(names["engine_methods"])} engine methods, '
          f'{len(names["engine_signals"])} engine signals '
          f'(Godot {payload["godot_version"]})')
    return 0


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))
