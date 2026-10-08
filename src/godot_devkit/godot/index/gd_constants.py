"""gd_constants.py — the GDScript analyzer's constant folding, without the engine.

Godot's POT extractor keeps a string only when the analyzer has REDUCED the
expression to a constant string (`_is_constant_string`: `is_constant &&
reduced_value.is_string()`). So `tr(TOOLTIP_LABEL)` is extracted when
`TOOLTIP_LABEL` is a `const` — in this class, a base class, an outer class,
another script reached by `class_name` or `preload`, or an autoload's script —
and `tr(label)` is not. This module answers that question the way
`modules/gdscript/gdscript_analyzer.cpp` does (`reduce_identifier`,
`reduce_subscript`, `reduce_binary_op`, `reduce_call`, `reduce_ternary_op`,
`reduce_unary_op`, `reduce_cast`, `make_expression_reduced_value`).

Three answers, never a guess:
  * a value (`str`, `StringNameValue`, int, float, bool, None, list, dict, a
    `ClassScope`, or an `Opaque` constant whose value nothing here needs);
  * `NOT_CONSTANT` — the analyzer would not fold it either;
  * `Unsupported` raised — the analyzer WOULD fold it and this module cannot
    compute the value: a float formatted into a string, a `%x` conversion, a
    property of a preloaded resource, an engine constant formatted into a
    string, a constant of a scene autoload. The caller refuses the run: a
    string the editor extracts and this tool drops is the silent miss rule 4
    forbids.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from godot_devkit.godot.format import classdb
from godot_devkit.godot.format.gdscript_syntax import (
    NODE_PATH,
    STRING_NAME,
    ArrayNode,
    Assignment,
    Attribute,
    Await,
    Binary,
    Call,
    Cast,
    ClassDecl,
    ConstMember,
    DictNode,
    EnumMember,
    Expr,
    FuncMember,
    GDSyntaxError,
    GetNode,
    Identifier,
    Lambda,
    Literal,
    OtherMember,
    Preload,
    SelfNode,
    Subscript,
    Ternary,
    TypeTest,
    Unary,
    VarMember,
    parse,
)

RES_PREFIX = 'res://'
BYTE_ORDER_MARK = '\ufeff'
SCRIPT_SUFFIX = '.gd'
# How the engine spells its integer constants (`CoreConstants`, ClassDB).
ENGINE_CONSTANT_RE = re.compile(r'^[A-Z][A-Z0-9_]*$')
CLASS_NAME_RE = re.compile(
    r'^(?:@\w+(?:\([^)]*\))?\s+)*class_name\s+([A-Za-z_]\w*)', re.MULTILINE)

# Builtin type constructors (`GDScriptParser::get_builtin_type`). The analyzer
# folds a constructor call whose arguments are all constant, except for the
# shared types (`Variant::is_type_shared`), which it never folds.
STRING_TYPES = frozenset(('String', 'StringName'))
SHARED_TYPES = frozenset(('Array', 'Dictionary', 'Object', 'Callable', 'Signal'))
BUILTIN_TYPES = frozenset((
    'bool', 'int', 'float', 'String', 'Vector2', 'Vector2i', 'Rect2', 'Rect2i',
    'Vector3', 'Vector3i', 'Transform2D', 'Vector4', 'Vector4i', 'Plane',
    'Quaternion', 'AABB', 'Basis', 'Transform3D', 'Projection', 'Color',
    'StringName', 'NodePath', 'RID', 'Callable', 'Signal', 'Dictionary', 'Array',
    'PackedByteArray', 'PackedInt32Array', 'PackedInt64Array',
    'PackedFloat32Array', 'PackedFloat64Array', 'PackedStringArray',
    'PackedVector2Array', 'PackedVector3Array', 'PackedColorArray',
    'PackedVector4Array',
))
# `GDScriptUtilityFunctions` registered with is_constant = true.
CONSTANT_GDSCRIPT_UTILITIES = frozenset((
    'convert', 'type_exists', 'char', 'ord', 'Color8', 'len', 'is_instance_of'))
# `Variant` utility functions of UTILITY_FUNC_TYPE_MATH: folded, never a string.
MATH_UTILITIES = frozenset((
    'abs', 'absf', 'absi', 'acos', 'acosh', 'angle_difference', 'asin', 'asinh',
    'atan', 'atan2', 'atanh', 'bezier_derivative', 'bezier_interpolate', 'ceil',
    'ceilf', 'ceili', 'clamp', 'clampf', 'clampi', 'cos', 'cosh',
    'cubic_interpolate', 'cubic_interpolate_angle',
    'cubic_interpolate_angle_in_time', 'cubic_interpolate_in_time',
    'db_to_linear', 'deg_to_rad', 'ease', 'exp', 'floor', 'floorf', 'floori',
    'fmod', 'fposmod', 'inverse_lerp', 'is_equal_approx', 'is_finite', 'is_inf',
    'is_nan', 'is_zero_approx', 'lerp', 'lerp_angle', 'lerpf', 'linear_to_db',
    'log', 'max', 'maxf', 'maxi', 'min', 'minf', 'mini', 'move_toward',
    'nearest_po2', 'pingpong', 'posmod', 'pow', 'rad_to_deg', 'remap',
    'rotate_toward', 'round', 'roundf', 'roundi', 'sign', 'signf', 'signi', 'sin',
    'sinh', 'smoothstep', 'snapped', 'snappedf', 'snappedi', 'sqrt',
    'step_decimals', 'tan', 'tanh', 'wrap', 'wrapf', 'wrapi'))

NULL_TEXT = '<null>'
TRUE_TEXT, FALSE_TEXT = 'true', 'false'
FORMAT_MARK = '%'
FORMAT_STRING = 's'
FORMAT_INT = 'd'


class NotConstant:
    """The analyzer leaves this expression unreduced."""

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __repr__(self) -> str:
        return 'NOT_CONSTANT'


NOT_CONSTANT = NotConstant()


class StringNameValue(str):
    """`&"x"`: a string to `Variant::is_string`, the same text as its String."""


@dataclass(frozen=True)
class NodePathValue:
    """`^"x"`: constant, and NOT a string to `Variant::is_string`."""
    text: str


@dataclass(frozen=True)
class Opaque:
    """A constant whose value nothing here models.

    `string_free` says whether it can be a string. `Vector2i(1, 2).x * 3` or a
    `maxi()` result never is, so it answers "is this a constant string?" with
    no, and arithmetic among such values stays string-free. A preloaded
    RESOURCE is the other kind: the analyzer reads its properties
    (`get_named`), one of them may be a string, and only the resource file
    knows — so asking that question of it is `Unsupported`.
    """
    what: str
    string_free: bool = True


@dataclass(frozen=True)
class Instance:
    """A non-constant value of a known script type (an autoload, a typed var).

    Not a constant itself, but `instance.CONST` folds: the analyzer resolves
    the attribute from the static type (`reduce_identifier_from_base`).
    """
    scope: 'ClassScope | None'   # None: a scene autoload, script unknown here


class Unsupported(Exception):
    """The analyzer folds this and this module cannot compute it. Exit 2."""

    def __init__(self, where: str, reason: str):
        super().__init__(f'{where}: {reason}')
        self.where = where
        self.reason = reason


def is_constant(value: object) -> bool:
    return value is not NOT_CONSTANT and not isinstance(value, Instance)


def is_constant_string(value: object, where: str) -> bool:
    """`_is_constant_string`: reduced, and a String or StringName."""
    if isinstance(value, Opaque) and not value.string_free:
        raise Unsupported(where, f'{value.what} may reduce to a string, and only '
                                 f'the editor can read its value')
    return isinstance(value, str)


# --- the project ------------------------------------------------------------------

class Project:
    """Every script the folder may need, parsed once, on demand.

    `read(res_path)` returns a script's text or None; `scripts()` lists every
    `res://…gd` for the `class_name` index. Both are the caller's, so this
    module never enumerates or opens a filesystem itself.
    """

    def __init__(self, read: Callable[[str], str | None],
                 scripts: Callable[[], list[str]],
                 autoloads: dict[str, str]):
        self._read = read
        self._scripts = scripts
        self._autoloads = autoloads
        self._cache: dict[str, ClassScope] = {}
        self._class_names: dict[str, list[str]] | None = None

    def script(self, res_path: str, where: str) -> 'ClassScope':
        if res_path in self._cache:
            return self._cache[res_path]
        text = self._read(res_path)
        if text is None:
            raise Unsupported(where, f'cannot read {res_path}')
        try:
            parsed = parse(text)
        except GDSyntaxError as err:
            raise Unsupported(f'{res_path}:{err.line}',
                              f'cannot parse it ({err.message})') from err
        scope = ClassScope(self, parsed.root, res_path, None)
        self._cache[res_path] = scope
        return scope

    def parsed(self, res_path: str, root: ClassDecl) -> 'ClassScope':
        """Seed the cache with a script the caller already parsed."""
        scope = self._cache.get(res_path)
        if scope is None:
            scope = ClassScope(self, root, res_path, None)
            self._cache[res_path] = scope
        return scope

    def global_class(self, name: str, where: str) -> 'ClassScope | None':
        if self._class_names is None:
            index: dict[str, list[str]] = {}
            for res_path in self._scripts():
                text = self._read(res_path) or ''
                match = CLASS_NAME_RE.search(text)
                if match:
                    index.setdefault(match.group(1), []).append(res_path)
            self._class_names = index
        paths = self._class_names.get(name)
        if not paths:
            return None
        if len(paths) > 1:
            raise Unsupported(where, f'class_name {name} is declared by '
                                     f'{len(paths)} scripts ({", ".join(paths)})')
        return self.script(paths[0], where)

    def autoload(self, name: str, where: str) -> 'ClassScope | None':
        """An autoload's script class; None when `name` is no script autoload."""
        path = self._autoloads.get(name)
        if path is None or not path.endswith(SCRIPT_SUFFIX):
            return None
        return self.script(path, where)

    def is_scene_autoload(self, name: str) -> bool:
        path = self._autoloads.get(name)
        return path is not None and not path.endswith(SCRIPT_SUFFIX)


@dataclass
class _Member:
    kind: str           # 'const' | 'class' | 'enum' | 'enum_value' | 'other'
    owner: 'ClassScope'
    node: object = None
    value: object = None


class ClassScope:
    """One class (a script or an inner class) as the analyzer sees its members."""

    def __init__(self, project: Project, decl: ClassDecl, path: str,
                 outer: 'ClassScope | None'):
        self.project = project
        self.decl = decl
        self.path = path
        self.outer = outer
        self.members: dict[str, _Member] = {}
        self.var_types: dict[str, str | None] = {}
        self._values: dict[object, object] = {}
        self._evaluating: set[str] = set()
        self._base: ClassScope | None | NotConstant = NOT_CONSTANT
        for member in decl.members:
            if isinstance(member, ConstMember):
                self.members[member.name] = _Member('const', self, member)
            elif isinstance(member, ClassDecl):
                inner = ClassScope(project, member, path, self)
                self.members[member.name] = _Member('class', self, value=inner)
            elif isinstance(member, EnumMember):
                self._enum(member)
            elif isinstance(member, VarMember):
                self.members[member.name] = _Member('other', self)
                self.var_types[member.name] = member.type_name
            elif isinstance(member, FuncMember) and member.function.name:
                self.members[member.function.name] = _Member('other', self)
            elif isinstance(member, OtherMember):
                self.members[member.name] = _Member('other', self)

    def where(self, line: int) -> str:
        return f'{self.path}:{line}'

    def _enum(self, member: EnumMember) -> None:
        """Declare an enum's names now; reduce its values on first use."""
        if member.name is None:
            for key, _ in member.values:
                self.members[key] = _Member('enum_value', self, member, key)
        else:
            self.members[member.name] = _Member('enum', self, member)

    def _enum_values(self, member: EnumMember) -> dict[str, object]:
        cached = self._values.get(id(member))  # type: ignore[call-overload]
        if cached is not None:
            return cached  # type: ignore[return-value]
        values: dict[str, object] = {}
        current = 0
        for key, expr in member.values:
            if expr is not None:
                value = Evaluator(self, enum_values=values).eval(expr)
                if not isinstance(value, int) or isinstance(value, bool):
                    raise Unsupported(self.where(expr.line),
                                      f'enum value {key} is not a constant integer')
                current = value
            values[key] = current
            current += 1
        self._values[id(member)] = values  # type: ignore[index]
        return values

    def base(self, where: str) -> 'ClassScope | None':
        """The script class this one extends, or None for a native base.

        `resolve_class_inheritance`'s order for `extends Name`: a global
        `class_name`, then an autoload, then a native class, then a class or
        preloaded-script constant of this class or an enclosing one. Nested
        names (`extends A.B`) step through classes.
        """
        if self._base is not NOT_CONSTANT:
            return self._base  # type: ignore[return-value]
        decl = self.decl
        where = self.where(decl.line)
        base: ClassScope | None = None
        if decl.extends_is_path:
            base = self.project.script(decl.extends, where)  # type: ignore[arg-type]
        elif decl.extends is not None:
            head, *rest = decl.extends.split('.')
            project = self.project
            found = project.global_class(head, where) or project.autoload(head, where)
            if found is None and not classdb.is_known(head):
                found = self._class_in_scope(head, where)
                if found is None:
                    raise Unsupported(where, f'cannot resolve the base class '
                                             f'{decl.extends} of {self.path}')
            base = found
            for name in rest:
                member = base.member(name, where) if base is not None else None
                if member is None or member.kind != 'class':
                    raise Unsupported(where, f'cannot resolve {decl.extends}')
                base = member.value
        self._base = base
        return base

    def _class_in_scope(self, name: str, where: str) -> 'ClassScope | None':
        """`get_class_node_current_scope_classes`: this class, then each
        enclosing one — its own name, or a class or constant member."""
        scope: ClassScope | None = self
        while scope is not None:
            if scope.decl.name == name:
                return scope
            member = scope.members.get(name)
            if member is not None:
                if member.kind == 'class':
                    return member.value  # type: ignore[return-value]
                if member.kind == 'const':
                    value = scope.value_of(member, name)
                    return value if isinstance(value, ClassScope) else None
                return None
            scope = scope.outer
        return None

    def member(self, name: str, where: str) -> _Member | None:
        """This class's member, else its bases' (`reduce_identifier_from_base`)."""
        scope: ClassScope | None = self
        seen: set[int] = set()
        while scope is not None and id(scope) not in seen:
            seen.add(id(scope))
            found = scope.members.get(name)
            if found is not None:
                return found
            scope = scope.base(where)
        return None

    def value_of(self, member: _Member, name: str) -> object:
        """A member's reduced value — memoized, cycle-guarded."""
        if member.kind == 'class':
            return member.value
        if member.kind == 'enum':
            return dict(member.owner._enum_values(member.node))  # type: ignore[arg-type]
        if member.kind == 'enum_value':
            return member.owner._enum_values(member.node)[member.value]  # type: ignore[arg-type]
        if member.kind != 'const':
            return NOT_CONSTANT
        owner = member.owner
        if name in owner._values:
            return owner._values[name]
        node: ConstMember = member.node  # type: ignore[assignment]
        if name in owner._evaluating:
            raise Unsupported(owner.where(node.line), f'constant {name} refers to itself')
        owner._evaluating.add(name)
        try:
            value = Evaluator(owner).eval_initializer(node.initializer)
        finally:
            owner._evaluating.discard(name)
        if not is_constant(value):
            # The analyzer refuses a non-constant const initializer, so the
            # script fails analysis — and the extractor reads nothing from it.
            raise Unsupported(owner.where(node.line),
                              f'constant {name} does not reduce to a constant')
        owner._values[name] = value
        return value


# --- the evaluator ----------------------------------------------------------------

@dataclass
class Local:
    kind: str                     # 'const' | 'var'
    expr: Expr | None = None
    type_name: str | None = None
    value: object = NOT_CONSTANT
    done: bool = False


@dataclass
class Evaluator:
    """Reduce one expression in one lexical position."""
    scope: ClassScope
    locals_: list[dict[str, Local]] = field(default_factory=list)
    enum_values: dict[str, object] | None = None

    def where(self, line: int) -> str:
        return self.scope.where(line)

    def eval_initializer(self, expr: Expr) -> object:
        """`make_expression_reduced_value`: arrays and dicts reduce too."""
        if isinstance(expr, ArrayNode):
            values = [self.eval_initializer(e) for e in expr.elements]
            return values if all(is_constant(v) for v in values) else NOT_CONSTANT
        if isinstance(expr, DictNode):
            out: dict = {}
            for key_expr, value_expr in expr.pairs:
                key = self.eval_initializer(key_expr)
                value = self.eval_initializer(value_expr)
                if not (is_constant(key) and is_constant(value)):
                    return NOT_CONSTANT
                out[_dict_key(key)] = value
            return out
        return self.eval(expr)

    def eval(self, expr: Expr | None) -> object:
        if expr is None:
            return NOT_CONSTANT
        if isinstance(expr, Literal):
            if expr.flavor == STRING_NAME:
                return StringNameValue(expr.value)
            if expr.flavor == NODE_PATH:
                return NodePathValue(expr.value)  # type: ignore[arg-type]
            return expr.value
        if isinstance(expr, Identifier):
            return self.identifier(expr)
        if isinstance(expr, Attribute):
            return self.attribute(expr)
        if isinstance(expr, Subscript):
            return self.subscript(expr)
        if isinstance(expr, Binary):
            return self.binary(expr)
        if isinstance(expr, Unary):
            return self.unary(expr)
        if isinstance(expr, Ternary):
            return self.ternary(expr)
        if isinstance(expr, Call):
            return self.call(expr)
        if isinstance(expr, Cast):
            return self.cast(expr)
        if isinstance(expr, Preload):
            return self.preload(expr)
        if isinstance(expr, TypeTest):
            operand = self.eval(expr.operand)
            return Opaque('bool') if is_constant(operand) else NOT_CONSTANT
        if isinstance(expr, (ArrayNode, DictNode, Lambda, Await, Assignment,
                             GetNode, SelfNode)):
            return NOT_CONSTANT
        raise Unsupported(self.where(expr.line), f'unknown expression {type(expr).__name__}')

    # --- names ---
    def identifier(self, expr: Identifier) -> object:
        name = expr.name
        where = self.where(expr.line)
        if self.enum_values is not None and name in self.enum_values:
            return self.enum_values[name]
        for frame in reversed(self.locals_):
            local = frame.get(name)
            if local is None:
                continue
            if local.kind == 'var':
                scope = self._type_scope(local.type_name, where)
                return Instance(scope) if scope is not None else NOT_CONSTANT
            if not local.done:
                local.value = self.eval_initializer(local.expr)  # type: ignore[arg-type]
                local.done = True
            return local.value
        scope: ClassScope | None = self.scope
        while scope is not None:
            member = scope.member(name, where)
            if member is not None:
                if member.kind == 'other':
                    type_name = member.owner.var_types.get(name)
                    typed = Evaluator(member.owner)._type_scope(type_name, where)
                    return Instance(typed) if typed is not None else NOT_CONSTANT
                return member.owner.value_of(member, name)
            scope = scope.outer
        found = self.scope.project.global_class(name, where)
        if found is not None:
            return found
        autoload = self.scope.project.autoload(name, where)
        if autoload is not None:
            return Instance(autoload)
        if self.scope.project.is_scene_autoload(name):
            return Instance(None)
        if ENGINE_CONSTANT_RE.match(name):
            # A global or ClassDB constant (`KEY_A`, `NOTIFICATION_READY`):
            # the analyzer folds it to an integer this module does not know.
            return Opaque(name)
        return NOT_CONSTANT

    def _type_scope(self, type_name: str | None, where: str) -> ClassScope | None:
        """The script class a declared type names, or None (native, builtin)."""
        if not type_name:
            return None
        head, *rest = type_name.split('.')
        if head in BUILTIN_TYPES or classdb.is_known(head):
            return None
        value = self.identifier(Identifier(0, head)) if head else NOT_CONSTANT
        scope = value if isinstance(value, ClassScope) else None
        for name in rest:
            if scope is None:
                return None
            member = scope.member(name, where)
            scope = member.value if member is not None and member.kind == 'class' else None
        return scope

    def attribute(self, expr: Attribute) -> object:
        where = self.where(expr.line)
        if isinstance(expr.base, SelfNode):
            member = self.scope.member(expr.name, where)
            if member is None or member.kind == 'other':
                return NOT_CONSTANT
            return member.owner.value_of(member, expr.name)
        base = self.eval(expr.base)
        if isinstance(base, Instance):
            if base.scope is None:
                raise Unsupported(where, 'a constant of a scene autoload: the editor '
                                         'reads its root script from the running scene')
            base = base.scope
            member = base.member(expr.name, where)
            if member is None or member.kind not in ('const', 'enum', 'enum_value', 'class'):
                return NOT_CONSTANT
            return member.owner.value_of(member, expr.name)
        if isinstance(base, ClassScope):
            member = base.member(expr.name, where)
            if member is None:
                return NOT_CONSTANT
            return member.owner.value_of(member, expr.name)
        if not is_constant(base):
            return NOT_CONSTANT
        if isinstance(base, dict):
            key = _dict_key(expr.name)
            return base[key] if key in base else NOT_CONSTANT
        if isinstance(base, Opaque):
            return Opaque(f'{base.what}.{expr.name}', base.string_free)
        return NOT_CONSTANT

    def subscript(self, expr: Subscript) -> object:
        base = self.eval(expr.base)
        if not is_constant(base):
            return NOT_CONSTANT
        index = self.eval(expr.index)
        if not is_constant(index):
            return NOT_CONSTANT
        where = self.where(expr.line)
        if isinstance(base, (list, str)) and isinstance(index, int) and not isinstance(index, bool):
            if -len(base) <= index < len(base):
                return base[index]
            raise Unsupported(where, f'index {index} is out of range')
        if isinstance(base, dict):
            key = _dict_key(index)
            if key in base:
                return base[key]
            raise Unsupported(where, f'key {index!r} is not in the constant dictionary')
        if isinstance(base, Opaque) and base.string_free:
            return base
        raise Unsupported(where, f'cannot fold a subscript of {_kind(base)}')

    # --- operators ---
    def binary(self, expr: Binary) -> object:
        left = self.eval(expr.left)
        right = self.eval(expr.right)
        if not (is_constant(left) and is_constant(right)):
            return NOT_CONSTANT
        if isinstance(left, (list, dict)) or isinstance(right, (list, dict)):
            return NOT_CONSTANT  # `is_shared()`: the analyzer folds no shared operand
        return _evaluate(expr.op, left, right, self.where(expr.line))

    def unary(self, expr: Unary) -> object:
        operand = self.eval(expr.operand)
        if not is_constant(operand):
            return NOT_CONSTANT
        where = self.where(expr.line)
        if isinstance(operand, Opaque) and operand.string_free:
            return operand
        if expr.op == '!':
            return not _booleanize(operand, where)
        if isinstance(operand, bool) or not isinstance(operand, (int, float)):
            raise Unsupported(where, f'cannot fold {expr.op} on {_kind(operand)}')
        if expr.op == '-':
            return -operand
        if expr.op == '+':
            return operand
        if expr.op == '~' and isinstance(operand, int):
            return ~operand
        raise Unsupported(where, f'cannot fold {expr.op} on {_kind(operand)}')

    def ternary(self, expr: Ternary) -> object:
        condition = self.eval(expr.condition)
        true_value = self.eval(expr.true_expr)
        false_value = self.eval(expr.false_expr)
        if not (is_constant(condition) and is_constant(true_value)
                and is_constant(false_value)):
            return NOT_CONSTANT
        if (isinstance(condition, Opaque) and condition.string_free
                and _string_free(true_value) and _string_free(false_value)):
            return Opaque('ternary')
        return true_value if _booleanize(condition, self.where(expr.line)) else false_value

    def cast(self, expr: Cast) -> object:
        operand = self.eval(expr.operand)
        if not is_constant(operand):
            return NOT_CONSTANT
        if expr.type_name in STRING_TYPES and isinstance(operand, str):
            return StringNameValue(operand) if expr.type_name == 'StringName' else str(operand)
        if isinstance(operand, str) or not _string_free(operand):
            raise Unsupported(self.where(expr.line),
                              f'cannot fold {_kind(operand)} cast to {expr.type_name}')
        return Opaque(f'cast to {expr.type_name}')

    def preload(self, expr: Preload) -> object:
        path = self.eval(expr.path)
        if not isinstance(path, str):
            raise Unsupported(self.where(expr.line), 'preload() of a path this cannot fold')
        if path.endswith(SCRIPT_SUFFIX):
            return self.scope.project.script(path, self.where(expr.line))
        return Opaque(f'preload("{path}")', string_free=False)

    def call(self, expr: Call) -> object:
        if expr.is_super or not isinstance(expr.callee, Identifier):
            return NOT_CONSTANT  # no builtin method folds (`reduce_call`)
        name = expr.function_name
        known = (name in BUILTIN_TYPES or name in CONSTANT_GDSCRIPT_UTILITIES
                 or name in MATH_UTILITIES)
        if not known:
            return NOT_CONSTANT
        args = [self.eval(a) for a in expr.args]
        if not all(is_constant(a) for a in args):
            return NOT_CONSTANT
        where = self.where(expr.line)
        if name in BUILTIN_TYPES:
            if name in SHARED_TYPES:
                return NOT_CONSTANT
            return _construct(name, args, where)
        if name in MATH_UTILITIES:
            return Opaque(f'{name}()')
        if name == 'char' and len(args) == 1 and isinstance(args[0], int):
            return chr(args[0])
        if name == 'len' and len(args) == 1 and isinstance(args[0], (str, list, dict)):
            return len(args[0])
        if name == 'ord' and len(args) == 1 and isinstance(args[0], str) and args[0]:
            return ord(args[0][0])
        if name in ('type_exists', 'is_instance_of', 'Color8'):
            return Opaque(f'{name}()')
        if name == 'convert':
            return Opaque(f'{name}()', string_free=False)
        raise Unsupported(where, f'cannot fold {name}() of {", ".join(map(_kind, args))}')


def _string_free(value: object) -> bool:
    """Known never to be a String or StringName."""
    if isinstance(value, Opaque):
        return value.string_free
    return not isinstance(value, str)


def _dict_key(value: object) -> object:
    """Godot compares String and StringName keys as equal."""
    return str(value) if isinstance(value, str) else value


def _kind(value: object) -> str:
    if isinstance(value, StringNameValue):
        return 'StringName'
    if isinstance(value, str):
        return 'String'
    if isinstance(value, bool):
        return 'bool'
    if isinstance(value, int):
        return 'int'
    if isinstance(value, float):
        return 'float'
    if value is None:
        return 'null'
    if isinstance(value, Opaque):
        return value.what
    return type(value).__name__


def _booleanize(value: object, where: str) -> bool:
    if value is None:
        return False
    if isinstance(value, (bool, int, float, str, list, dict)):
        return bool(value)
    if isinstance(value, NodePathValue):
        return bool(value.text)
    if isinstance(value, ClassScope):
        return True
    raise Unsupported(where, f'cannot fold the truth of {_kind(value)}')


def _stringify(value: object, where: str) -> str:
    """`Variant::stringify` for the kinds this module models exactly."""
    if isinstance(value, str):
        return str(value)
    if isinstance(value, bool):
        return TRUE_TEXT if value else FALSE_TEXT
    if isinstance(value, int):
        return str(value)
    if value is None:
        return NULL_TEXT
    if isinstance(value, NodePathValue):
        return value.text
    raise Unsupported(where, f'cannot fold {_kind(value)} into a string')


def _format(template: str, value: object, where: str) -> str:
    """`String::sprintf` with one argument, for `%s`, `%d` and `%%` only."""
    out: list[str] = []
    used = False
    i = 0
    while i < len(template):
        ch = template[i]
        if ch != FORMAT_MARK:
            out.append(ch)
            i += 1
            continue
        conv = template[i + 1] if i + 1 < len(template) else ''
        if conv == FORMAT_MARK:
            out.append(FORMAT_MARK)
        elif conv in (FORMAT_STRING, FORMAT_INT) and not used:
            if conv == FORMAT_INT:
                if isinstance(value, bool) or not isinstance(value, int):
                    raise Unsupported(where, f'cannot fold %d of {_kind(value)}')
                out.append(str(value))
            else:
                out.append(_stringify(value, where))
            used = True
        else:
            raise Unsupported(where, f'cannot fold the format {template!r}')
        i += 2
    if not used:
        raise Unsupported(where, f'cannot fold the format {template!r}: unused argument')
    return ''.join(out)


def _construct(name: str, args: list, where: str) -> object:
    if name in STRING_TYPES:
        if not args:
            text = ''
        elif len(args) == 1:
            text = _stringify(args[0], where)
        else:
            raise Unsupported(where, f'cannot fold {name}() of {len(args)} arguments')
        return StringNameValue(text) if name == 'StringName' else text
    if name == 'NodePath' and len(args) == 1 and isinstance(args[0], str):
        return NodePathValue(str(args[0]))
    if any(isinstance(a, str) for a in args) and name in ('int', 'float', 'bool'):
        raise Unsupported(where, f'cannot fold {name}() of a string')
    return Opaque(f'{name}()')


def _number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _evaluate(op: str, left: object, right: object, where: str) -> object:
    """`Variant::evaluate` for the operand kinds modeled exactly."""
    if isinstance(left, Opaque) or isinstance(right, Opaque):
        # Neither side a string and both string-free: the result is a
        # number, vector or bool — constant, and never a string.
        free = all(not isinstance(v, str) and (not isinstance(v, Opaque) or v.string_free)
                   for v in (left, right))
        if free:
            return Opaque(f'{_kind(left)} {op} {_kind(right)}')
        raise Unsupported(where, f'cannot fold {_kind(left)} {op} {_kind(right)}')
    if op in ('&&', '||'):
        a, b = _booleanize(left, where), _booleanize(right, where)
        return (a and b) if op == '&&' else (a or b)
    if isinstance(left, str) and isinstance(right, str):
        a, b = str(left), str(right)
        if op == '+':
            return a + b
        if op == FORMAT_MARK:
            return _format(a, right, where)
        if op == 'in':
            return a in b
        comparisons = {'==': a == b, '!=': a != b, '<': a < b, '>': a > b,
                       '<=': a <= b, '>=': a >= b}
        if op in comparisons:
            return comparisons[op]
    if isinstance(left, str) and op == FORMAT_MARK:
        return _format(str(left), right, where)
    if _number(left) and _number(right):
        return _arith(op, left, right, where)  # type: ignore[arg-type]
    if isinstance(left, bool) and isinstance(right, bool) and op in ('==', '!='):
        return (left == right) == (op == '==')
    raise Unsupported(where, f'cannot fold {_kind(left)} {op} {_kind(right)}')


def _arith(op: str, a: int | float, b: int | float, where: str) -> object:
    both_int = isinstance(a, int) and isinstance(b, int)
    if op == '+':
        return a + b
    if op == '-':
        return a - b
    if op == '*':
        return a * b
    if op == '/':
        if b == 0:
            raise Unsupported(where, 'division by zero')
        if both_int:
            quotient = abs(a) // abs(b)
            return quotient if (a >= 0) == (b >= 0) else -quotient
        return a / b
    if op == '%' and both_int:
        if b == 0:
            raise Unsupported(where, 'modulo by zero')
        remainder = abs(a) % abs(b)
        return remainder if a >= 0 else -remainder
    if op == '**':
        return a ** b
    comparisons = {'==': a == b, '!=': a != b, '<': a < b, '>': a > b,
                   '<=': a <= b, '>=': a >= b}
    if op in comparisons:
        return comparisons[op]
    if both_int and op in ('&', '|', '^', '<<', '>>'):
        return {'&': a & b, '|': a | b, '^': a ^ b,  # type: ignore[operator]
                '<<': a << b, '>>': a >> b}[op]  # type: ignore[operator]
    raise Unsupported(where, f'cannot fold {_kind(a)} {op} {_kind(b)}')


def res_to_rel(res_path: str) -> str:
    return res_path[len(RES_PREFIX):] if res_path.startswith(RES_PREFIX) else res_path


def read_res(root: Path) -> Callable[[str], str | None]:
    """A `Project.read` over a checkout: `res://x.gd` → its text, or None."""
    def read(res_path: str) -> str | None:
        try:
            text = (root / res_to_rel(res_path)).read_text(encoding='utf-8')
        except (OSError, UnicodeDecodeError):
            return None
        return text.removeprefix(BYTE_ORDER_MARK)
    return read
