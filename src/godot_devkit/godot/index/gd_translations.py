"""gd_translations.py — the strings Godot's editor extracts from one GDScript.

A port of `GDScriptEditorTranslationParserPlugin`
(`modules/gdscript/editor/gdscript_translation_parser_plugin.cpp`, Godot 4.7):
the same walk, in the same order, keeping the same strings.

  * The walk: class members in source order — a `var` initializer and its
    inline setter then getter, every function's parameter defaults and body,
    inner classes. `const`, `signal` and `enum` members are never walked, nor
    are annotation arguments or `match` patterns (a guard is).
  * A call to `tr`/`atr` keeps (msgid, msgctxt) when EVERY argument reduces to
    a constant string; `tr_n`/`atr_n` keep (msgid, msgid_plural, msgctxt) from
    arguments 0, 1 and 3 on the same terms.
  * `set_text`, `add_item` and the other first-argument calls keep argument 0,
    `set_item_text` and the other second-argument calls keep argument 1, and an
    assignment to `text`, `placeholder_text` or `tooltip_text` (attribute,
    bare name, or constant-string subscript) keeps its value — each only when
    it reduces to a constant string.
  * `FileDialog` filters keep the description after the first `;`.
  * A `# TRANSLATORS:` comment on the line, or ending the run of own-line
    comments above it, becomes the entry's comment; `# NO_TRANSLATE` drops it.

"Reduces to a constant string" is `gd_constants`: a literal, a `const`
anywhere the analyzer looks, and the operators it folds. Godot's own spelling
of `TranslationServer.translate` is not a pattern in 4.7, so it is not one here.
"""
from __future__ import annotations

from dataclasses import dataclass

from godot_devkit.godot.format.gdscript_syntax import (
    ArrayNode,
    AssertStmt,
    Assignment,
    Attribute,
    Await,
    Binary,
    Call,
    Cast,
    ClassDecl,
    Comment,
    ConstStmt,
    DictNode,
    Expr,
    ExprStmt,
    ForStmt,
    FuncMember,
    Function,
    Identifier,
    IfStmt,
    Lambda,
    MatchStmt,
    ReturnStmt,
    Script,
    Subscript,
    Ternary,
    TypeTest,
    Unary,
    VarMember,
    VarStmt,
    WhileStmt,
)
from godot_devkit.godot.index.gd_constants import (
    ClassScope,
    Evaluator,
    Local,
    Project,
    is_constant_string,
)

TR_FUNCS = frozenset(('tr', 'atr'))
TRN_FUNCS = frozenset(('tr_n', 'atr_n'))
# tr_n(id, plural, n, ctx): which argument fills (msgid, msgctxt, msgid_plural).
TRN_ARGUMENT_SLOTS = (0, 3, 1)
ID_CTX_PLURAL = 3
ASSIGNMENT_PATTERNS = frozenset(('text', 'placeholder_text', 'tooltip_text'))
FIRST_ARG_PATTERNS = frozenset((
    'set_text', 'set_tooltip_text', 'set_placeholder', 'add_tab',
    'add_check_item', 'add_item', 'add_multistate_item', 'add_radio_check_item',
    'add_separator', 'add_submenu_item', 'add_submenu_node_item'))
SECOND_ARG_PATTERNS = frozenset((
    'set_tab_title', 'add_icon_check_item', 'add_icon_item',
    'add_icon_radio_check_item', 'set_item_text'))
FD_ADD_FILTER = 'add_filter'
FD_SET_FILTERS = 'set_filters'
FD_FILTERS = 'filters'
FD_FILTER_SEPARATOR = ';'
PACKED_STRING_ARRAY = 'PackedStringArray'

COMMENT_PREFIX = '#'
TRANSLATORS = 'TRANSLATORS:'
NO_TRANSLATE = 'NO_TRANSLATE'
NO_TRANSLATE_PREFIX = 'NO_TRANSLATE:'
# `String::strip_edges` drops every character at or below a space.
EDGE_CHAR_MAX = ' '


@dataclass(frozen=True)
class Extracted:
    msgid: str
    msgctxt: str
    plural: str
    comment: str
    line: int


def strip_edges(text: str, left: bool = True, right: bool = True) -> str:
    start, end = 0, len(text)
    if left:
        while start < end and text[start] <= EDGE_CHAR_MAX:
            start += 1
    if right:
        while end > start and text[end - 1] <= EDGE_CHAR_MAX:
            end -= 1
    return text[start:end]


def _stripped(comment: Comment) -> str:
    text = comment.text
    return strip_edges(text[1:] if text.startswith(COMMENT_PREFIX) else text)


def _is_no_translate(stripped: str) -> bool:
    return stripped == NO_TRANSLATE or stripped.startswith(NO_TRANSLATE_PREFIX)


def parse_comment(comments: dict[int, Comment], line: int) -> tuple[str, bool]:
    """`_parse_comment`: (comment, skip) for a string on `line`."""
    inline = comments.get(line)
    if inline is not None:
        stripped = _stripped(inline)
        if stripped.startswith(TRANSLATORS):
            return strip_edges(stripped[len(TRANSLATORS):], right=False), False
        if _is_no_translate(stripped):
            return '', True
    multiline = ''
    current = line - 1
    while current in comments and comments[current].own_line:
        stripped = _stripped(comments[current])
        current -= 1
        if not stripped:
            continue
        multiline = stripped if not multiline else f'{stripped}\n{multiline}'
        if stripped.startswith(TRANSLATORS):
            return strip_edges(multiline[len(TRANSLATORS):], right=False), False
        if _is_no_translate(stripped):
            return '', True
    return '', False


class _Extractor:
    def __init__(self, comments: dict[int, Comment]):
        self.comments = comments
        self.found: list[Extracted] = []

    # --- adding ---
    def add(self, msgid: str, line: int, msgctxt: str = '', plural: str = '') -> None:
        comment, skip = parse_comment(self.comments, line)
        if not skip:
            self.found.append(Extracted(msgid, msgctxt, plural, comment, line))

    # --- the walk ---
    def traverse_class(self, scope: ClassScope) -> None:
        for member in scope.decl.members:
            if isinstance(member, ClassDecl):
                self.traverse_class(scope.members[member.name].value)  # type: ignore[index]
            elif isinstance(member, FuncMember):
                self.traverse_function(member.function, Evaluator(scope))
            elif isinstance(member, VarMember):
                ctx = Evaluator(scope)
                self.assess(member.initializer, ctx)
                if member.inline_property:
                    self.traverse_function(member.setter, ctx)
                    self.traverse_function(member.getter, ctx)

    def traverse_function(self, function: Function | None, outer: Evaluator) -> None:
        if function is None:
            return
        frame = {p.name: Local('var', type_name=p.type_name) for p in function.params}
        ctx = Evaluator(outer.scope, [*outer.locals_, frame])
        for param in function.params:
            self.assess(param.default, ctx)
        self.traverse_block(function.body, ctx)

    def traverse_block(self, statements: list, outer: Evaluator) -> None:
        ctx = Evaluator(outer.scope, [*outer.locals_, {}])
        frame = ctx.locals_[-1]
        for stmt in statements:
            if isinstance(stmt, VarStmt):
                self.assess(stmt.initializer, ctx)
                frame[stmt.name] = Local('var', type_name=stmt.type_name)
            elif isinstance(stmt, ConstStmt):
                frame[stmt.name] = Local('const', stmt.initializer)
            elif isinstance(stmt, AssertStmt):
                self.assess(stmt.condition, ctx)
                self.assess(stmt.message, ctx)
            elif isinstance(stmt, ForStmt):
                self.assess(stmt.iterable, ctx)
                loop = Evaluator(ctx.scope, [*ctx.locals_, {stmt.variable: Local('var')}])
                self.traverse_block(stmt.body, loop)
            elif isinstance(stmt, IfStmt):
                self.assess(stmt.condition, ctx)
                self.traverse_block(stmt.true_block, ctx)
                self.traverse_block(stmt.false_block, ctx)
            elif isinstance(stmt, MatchStmt):
                self.assess(stmt.test, ctx)
                for branch in stmt.branches:
                    binds = Evaluator(ctx.scope, [*ctx.locals_,
                                                  {b: Local('var') for b in branch.binds}])
                    if branch.guard is not None:
                        self.assess(branch.guard, binds)
                    self.traverse_block(branch.body, binds)
            elif isinstance(stmt, ReturnStmt):
                self.assess(stmt.value, ctx)
            elif isinstance(stmt, WhileStmt):
                self.assess(stmt.condition, ctx)
                self.traverse_block(stmt.body, ctx)
            elif isinstance(stmt, ExprStmt):
                self.assess(stmt.expr, ctx)

    def assess(self, expr: Expr | None, ctx: Evaluator) -> None:
        if expr is None:
            return
        if isinstance(expr, ArrayNode):
            for element in expr.elements:
                self.assess(element, ctx)
        elif isinstance(expr, Assignment):
            self.assess_assignment(expr, ctx)
        elif isinstance(expr, Await):
            self.assess(expr.operand, ctx)
        elif isinstance(expr, Binary):
            self.assess(expr.left, ctx)
            self.assess(expr.right, ctx)
        elif isinstance(expr, Call):
            self.assess_call(expr, ctx)
        elif isinstance(expr, Cast):
            self.assess(expr.operand, ctx)
        elif isinstance(expr, DictNode):
            for key, value in expr.pairs:
                self.assess(key, ctx)
                self.assess(value, ctx)
        elif isinstance(expr, Lambda):
            self.traverse_function(expr.function, ctx)
        elif isinstance(expr, Attribute):
            self.assess(expr.base, ctx)
        elif isinstance(expr, Subscript):
            self.assess(expr.base, ctx)
            self.assess(expr.index, ctx)
        elif isinstance(expr, Ternary):
            self.assess(expr.condition, ctx)
            self.assess(expr.true_expr, ctx)
            self.assess(expr.false_expr, ctx)
        elif isinstance(expr, (TypeTest, Unary)):
            self.assess(expr.operand, ctx)

    def constant_string(self, expr: Expr, ctx: Evaluator) -> str | None:
        value = ctx.eval(expr)
        return str(value) if is_constant_string(value) else None

    def assess_assignment(self, expr: Assignment, ctx: Evaluator) -> None:
        self.assess(expr.target, ctx)
        self.assess(expr.value, ctx)
        target = expr.target
        name = None
        if isinstance(target, Identifier):
            name = target.name
        elif isinstance(target, Attribute):
            name = target.name
        elif isinstance(target, Subscript):
            name = self.constant_string(target.index, ctx)
        if name in ASSIGNMENT_PATTERNS:
            value = self.constant_string(expr.value, ctx)
            if value is not None:
                self.add(value, expr.value.line)
        elif name == FD_FILTERS:
            self.filter_array(expr.value, ctx)

    def assess_call(self, call: Call, ctx: Evaluator) -> None:
        self.assess(call.callee, ctx)
        for arg in call.args:
            self.assess(arg, ctx)
        name = call.function_name
        args = call.args
        if name in TR_FUNCS or name in TRN_FUNCS:
            # (slot in msgid/msgctxt/plural, argument index)
            pairs = (list(enumerate(range(len(args)))) if name in TR_FUNCS
                     else [(slot, index) for slot, index in enumerate(TRN_ARGUMENT_SLOTS)
                           if index < len(args)])
            out = [''] * ID_CTX_PLURAL
            for slot, index in pairs:
                value = self.constant_string(args[index], ctx)
                if value is None:
                    return
                if slot < ID_CTX_PLURAL:
                    out[slot] = value
            self.add(out[0], call.line, msgctxt=out[1], plural=out[2])
        elif name in FIRST_ARG_PATTERNS:
            if args:
                value = self.constant_string(args[0], ctx)
                if value is not None:
                    self.add(value, args[0].line)
        elif name in SECOND_ARG_PATTERNS:
            if len(args) > 1:
                value = self.constant_string(args[1], ctx)
                if value is not None:
                    self.add(value, args[1].line)
        elif name == FD_ADD_FILTER:
            if len(args) == 1:
                self.filter_string(args[0], args[0].line, ctx)
            elif len(args) >= 2:
                value = self.constant_string(args[1], ctx)
                if value is not None:
                    self.add(value, args[1].line)
        elif name == FD_SET_FILTERS:
            if args:
                self.filter_array(args[0], ctx)

    def filter_string(self, expr: Expr, line: int, ctx: Evaluator) -> None:
        value = self.constant_string(expr, ctx)
        if value is None:
            return
        parts = value.split(FD_FILTER_SEPARATOR, 1)
        if len(parts) >= 2:
            description = strip_edges(parts[1])
            if description:
                self.add(description, line)

    def filter_array(self, expr: Expr, ctx: Evaluator) -> None:
        array = None
        if isinstance(expr, ArrayNode):
            array = expr
        elif (isinstance(expr, Call) and isinstance(expr.callee, Identifier)
              and expr.function_name == PACKED_STRING_ARRAY and expr.args
              and isinstance(expr.args[0], ArrayNode)):
            array = expr.args[0]
        if array is not None:
            for element in array.elements:
                self.filter_string(element, element.line, ctx)


def extract(project: Project, res_path: str, script: Script) -> list[Extracted]:
    """Every entry the editor's GDScript parser plugin emits for one script."""
    extractor = _Extractor(script.comments)
    extractor.traverse_class(project.parsed(res_path, script.root))
    return extractor.found
