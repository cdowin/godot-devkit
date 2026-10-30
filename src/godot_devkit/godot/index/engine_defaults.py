"""engine_defaults.py — vendored engine defaults for the built-in resource types met so far.

Godot's saver omits a stored property whose value equals the class default.
Those defaults live in the engine, not in any file a parse can read, so they
are VENDORED here, per class, spelled exactly as the 4.7 saver writes them
(`var_to_str` of `ClassDB.class_get_property_default_value`, dumped once from
Godot 4.7.2). An assignment is elided only when its text EQUALS the entry; a
class or a property not listed is never judged. Grow the table by dumping the
new class the same way and vendoring an editor-saved pair for it under
`tests/fixtures/editor_parity/`.
"""
from __future__ import annotations

GODOT_VERSION = '4.7.2'
_RESOURCE = {'resource_local_to_scene': 'false', 'resource_name': '""'}

DEFAULTS: dict[str, dict[str, str]] = {
    'Gradient': {**_RESOURCE,
                 'colors': 'PackedColorArray(0, 0, 0, 1, 1, 1, 1, 1)',
                 'interpolation_color_space': '0',
                 'interpolation_mode': '0',
                 'offsets': 'PackedFloat32Array(0, 1)'},
    'GradientTexture1D': {**_RESOURCE,
                          'gradient': 'null', 'use_hdr': 'false', 'width': '256'},
    'GradientTexture2D': {**_RESOURCE,
                          'fill': '0', 'fill_from': 'Vector2(0, 0)', 'fill_to': 'Vector2(1, 0)',
                          'gradient': 'null', 'height': '64', 'repeat': '0',
                          'use_hdr': 'false', 'width': '64'},
    'PlaceholderTexture2D': {**_RESOURCE, 'size': 'Vector2(1, 1)'},
}


def default_of(class_name: str | None, key: str) -> str | None:
    """The saver's spelling of `class_name.key`'s default, or None if not vendored."""
    return DEFAULTS.get(class_name or '', {}).get(key)
