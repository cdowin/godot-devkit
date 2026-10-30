"""shader_uniforms.py — the `shader_parameter/*` lines a windowed editor save writes for a ShaderMaterial.

A windowed Godot 4.7 editor writes EVERY material uniform of the material's
shader, in declaration order, each with its value — the shader's default when
the material sets none. (A headless save writes `null` instead; the windowed
form is the one people produce, so it is the target.) Samplers and `instance`
/ `global` uniforms are not written. Read from the `.gdshader` text, never by
compiling it; measured on a 4.7.2 save and pinned by the pairs under
`tests/fixtures/editor_parity/`:

    float  = 0.75           -> 0.75          (no default -> 0.0)
    int    = 3              -> 3
    bool   = true           -> true
    vec2/3/4 / ivec2/3/4    -> Vector2(1, 0.5) / Vector2i(2, 3) ...
    vec3/vec4 : source_color -> Color(r, g, b, a)  (a vec3 gets alpha 1)

Anything else — a preprocessor directive, an array, a default that is not a
literal, a type or a missing default not listed above — raises
`UniformRefusal`: the tool says it cannot prove the line rather than writing one.
"""
from __future__ import annotations

import re

from godot_devkit.godot.format.value_spelling import (
    COMPONENT_CONTEXT,
    FLOAT_CONTEXT,
    canonical_float,
)

BLOCK_COMMENT = re.compile(r'/\*.*?\*/', re.S)
LINE_COMMENT = re.compile(r'//[^\n]*')
PREPROCESSOR = re.compile(r'^\s*#', re.M)
STATEMENT = re.compile(r'[^;{}]*;')
UNIFORM = re.compile(r'^\s*(?:(global|instance)\s+)?uniform\s+(\w+)\s+(\w+)\s*(\[[^\]]*\])?'
                     r'\s*(?::\s*([^=]*?))?\s*(?:=\s*(.*?))?\s*;$', re.S)
NUMBER = re.compile(r'^[-+]?(?:\d+\.\d*|\.\d+|\d+)(?:[eE][-+]?\d+)?$')
INT = re.compile(r'^[-+]?\d+$')
CALL = re.compile(r'^(\w+)\s*\((.*)\)$', re.S)
SOURCE_COLOR = 'source_color'
VECTORS = {'vec2': ('Vector2', 2, False), 'vec3': ('Vector3', 3, False),
           'vec4': ('Vector4', 4, False), 'ivec2': ('Vector2i', 2, True),
           'ivec3': ('Vector3i', 3, True), 'ivec4': ('Vector4i', 4, True)}
COLOR_SIZES = (3, 4)
OPAQUE_ALPHA = '1'


class UniformRefusal(ValueError):
    """The editor would write this material's parameters; the tool cannot prove how."""


def _float(text: str, style: str) -> str:
    if not NUMBER.match(text):
        raise UniformRefusal(f'default {text!r} is not a number literal')
    spelled = canonical_float(float(text), style)
    if spelled is None:
        raise UniformRefusal(f'default {text!r} has no build-independent spelling')
    return spelled


def _int(text: str) -> str:
    if not INT.match(text):
        raise UniformRefusal(f'default {text!r} is not an int literal')
    return str(int(text))


def _vector(kind: str, hints: str, default: str) -> str:
    call = CALL.match(default)
    args = [a.strip() for a in call.group(2).split(',')] if call else []
    ctor, size, integral = VECTORS[kind]
    if call is None or call.group(1) != kind or len(args) != size:
        raise UniformRefusal(f'default {default!r} is not a {kind}() of {size} literals')
    parts = [_int(a) if integral else _float(a, COMPONENT_CONTEXT) for a in args]
    if SOURCE_COLOR in hints:
        if integral or size not in COLOR_SIZES:
            raise UniformRefusal(f'{kind} : source_color is not a measured form')
        return f'Color({", ".join(parts + [OPAQUE_ALPHA] * (4 - size))})'
    return f'{ctor}({", ".join(parts)})'


def _spell(kind: str, hints: str, default: str | None) -> str:
    if kind == 'float':
        return _float(default, FLOAT_CONTEXT) if default is not None else '0.0'
    if default is None:
        raise UniformRefusal(f'a {kind} uniform with no default is not a measured form')
    if kind == 'int':
        return _int(default)
    if kind == 'bool':
        if default not in ('true', 'false'):
            raise UniformRefusal(f'default {default!r} is not a bool literal')
        return default
    if kind in VECTORS:
        return _vector(kind, hints, default)
    raise UniformRefusal(f'uniform type {kind} is not a measured form')


def material_parameters(source: str) -> list[tuple[str, str]]:
    """-> `[(uniform name, value as the editor writes it)]`, declaration order."""
    code = LINE_COMMENT.sub('', BLOCK_COMMENT.sub('', source))
    if PREPROCESSOR.search(code):
        raise UniformRefusal('the shader uses the preprocessor — its uniforms are not '
                             'readable without compiling it')
    params = []
    for statement in STATEMENT.findall(code):
        match = UNIFORM.match(statement)
        if match is None:
            continue
        scope, kind, name, array, hints, default = match.groups()
        if scope is not None or kind.startswith(('sampler', 'isampler', 'usampler')):
            continue
        if array is not None:
            raise UniformRefusal(f'uniform {name} is an array — not a measured form')
        try:
            params.append((name, _spell(kind, hints or '', default.strip() if default else None)))
        except UniformRefusal as refusal:
            raise UniformRefusal(f'uniform {name}: {refusal}') from refusal
    return params
