"""gdscript_syntax.py — a GDScript 4 tokenizer and parser, built for the tree
Godot's translation extractor walks.

`godot-devkit pot` must find the strings the editor's POT generator finds, and
the editor finds them by walking the PARSED tree
(`modules/gdscript/editor/gdscript_translation_parser_plugin.cpp`), not by
matching text. A regex cannot tell a `const` initializer (never walked) from a
`var` initializer (walked), a `match` pattern from a guard, or a `tr(` inside a
string from a call. So this module parses: the same statement and expression
grammar, the same precedence table (`GDScriptParser::get_rule`), and the same
node line (`start_line` — the first token of the node, a grouping's
parenthesis excluded).

It is not a validator. It accepts what Godot accepts and keeps only what the
extractor and the constant folder read; anything it cannot parse raises
`GDSyntaxError` with the line, and the caller refuses the whole run (exit 2) —
a script read halfway is the silent miss rule 4 forbids.

Comments are kept per line (`comments[line] = Comment(text, own_line)`), the
same table `GDScriptTokenizer::comments` builds, because `# TRANSLATORS:` and
`# NO_TRANSLATE` are read from it by line number.
"""
from __future__ import annotations

from dataclasses import dataclass, field

# --- tokens -------------------------------------------------------------------
NAME = 'name'
STRING = 'string'
NUMBER = 'number'
OP = 'op'
ANNOTATION = 'annotation'
EOF = 'eof'

# String flavors: the prefix that typed the literal.
PLAIN = ''
STRING_NAME = '&'
NODE_PATH = '^'
RAW = 'r'
QUOTES = ('"', "'")

# Longest first: the tokenizer takes the first that matches.
OPERATORS = (
    '**=', '<<=', '>>=', '...',
    '**', '<<', '>>', '<=', '>=', '==', '!=', '&&', '||', '+=', '-=', '*=',
    '/=', '%=', '&=', '|=', '^=', '->', '..',
    '+', '-', '*', '/', '%', '<', '>', '=', '!', '&', '|', '^', '~', '(', ')',
    '[', ']', '{', '}', ',', ';', '.', ':', '$', '?',
)
OPEN_BRACKETS = {'(': ')', '[': ']', '{': '}'}
CLOSE_BRACKETS = frozenset(OPEN_BRACKETS.values())
# What may legally follow the last statement of a lambda body written inside
# brackets: the bracket closes, or the next argument starts.
LAMBDA_TERMINATORS = CLOSE_BRACKETS | {','}

ESCAPES = {'a': '\a', 'b': '\b', 'f': '\f', 'n': '\n', 'r': '\r', 't': '\t',
           'v': '\v', "'": "'", '"': '"', '\\': '\\'}
UNICODE_ESCAPE_DIGITS = {'u': 4, 'U': 6}
HEX_PREFIXES = ('0x', '0X')
BIN_PREFIXES = ('0b', '0B')
HEX_BASE = 16
BIN_BASE = 2
SURROGATE_MASK = 0xFFFFFC00
LEAD_SURROGATE = 0xD800
TRAIL_SURROGATE = 0xDC00
SURROGATE_SHIFT = 10
SUPPLEMENTARY_BASE = 0x10000

# Literal keywords and the builtin float constants (`GDScriptParser::parse_builtin_constant`).
LITERAL_NAMES = {'true': True, 'false': False, 'null': None}
BUILTIN_CONSTANTS = {'PI': 3.141592653589793, 'TAU': 6.283185307179586,
                     'INF': float('inf'), 'NAN': float('nan')}

# --- precedence (GDScriptParser::Precedence, in order) -------------------------
(PREC_NONE, PREC_ASSIGNMENT, PREC_CAST, PREC_TERNARY, PREC_LOGIC_OR,
 PREC_LOGIC_AND, PREC_LOGIC_NOT, PREC_CONTENT_TEST, PREC_COMPARISON,
 PREC_BIT_OR, PREC_BIT_XOR, PREC_BIT_AND, PREC_BIT_SHIFT, PREC_ADDITION,
 PREC_FACTOR, PREC_SIGN, PREC_BIT_NOT, PREC_POWER, PREC_TYPE_TEST, PREC_AWAIT,
 PREC_CALL, PREC_ATTRIBUTE, PREC_SUBSCRIPT, PREC_PRIMARY) = range(24)

ASSIGNMENT_OPS = frozenset(('=', '+=', '-=', '*=', '**=', '/=', '%=', '<<=',
                            '>>=', '&=', '|=', '^='))
BINARY_OPS = {
    '<': PREC_COMPARISON, '<=': PREC_COMPARISON, '>': PREC_COMPARISON,
    '>=': PREC_COMPARISON, '==': PREC_COMPARISON, '!=': PREC_COMPARISON,
    'and': PREC_LOGIC_AND, '&&': PREC_LOGIC_AND,
    'or': PREC_LOGIC_OR, '||': PREC_LOGIC_OR,
    'in': PREC_CONTENT_TEST,
    '&': PREC_BIT_AND, '|': PREC_BIT_OR, '^': PREC_BIT_XOR,
    '<<': PREC_BIT_SHIFT, '>>': PREC_BIT_SHIFT,
    '+': PREC_ADDITION, '-': PREC_ADDITION,
    '*': PREC_FACTOR, '/': PREC_FACTOR, '%': PREC_FACTOR,
    '**': PREC_POWER,
}
# Spellings that are one operator to the folder.
OP_ALIASES = {'and': '&&', 'or': '||'}
UNARY_OPS = {'-': PREC_SIGN, '+': PREC_SIGN, '~': PREC_BIT_NOT,
             '!': PREC_LOGIC_NOT, 'not': PREC_LOGIC_NOT}


class GDSyntaxError(Exception):
    """A script this parser cannot read. Carries the 1-based line."""

    def __init__(self, line: int, message: str):
        super().__init__(f'line {line}: {message}')
        self.line = line
        self.message = message


@dataclass(frozen=True)
class Token:
    kind: str
    text: str            # name / operator spelling, or a string's decoded value
    line: int
    bol: bool            # first token of a logical line (not after a `\` join)
    indent: int          # that line's leading-whitespace width
    flavor: str = PLAIN  # a string's prefix; unused otherwise
    value: object = None  # a number's value


@dataclass(frozen=True)
class Comment:
    text: str            # from the `#` to the end of the line
    own_line: bool       # nothing but whitespace before it (CommentData::new_line)


# --- tokenizer ------------------------------------------------------------------

class _Scanner:
    def __init__(self, source: str):
        self.src = source
        self.i = 0
        self.line = 1
        self.tokens: list[Token] = []
        self.comments: dict[int, Comment] = {}
        self.line_has_token = False
        self.joined = False      # this line continues the previous one (`\`)
        self.indent = 0

    def peek(self, k: int = 0) -> str:
        j = self.i + k
        return self.src[j] if j < len(self.src) else ''

    def emit(self, kind: str, text: str, line: int, flavor: str = PLAIN,
             value: object = None) -> None:
        bol = not self.line_has_token and not self.joined
        self.tokens.append(Token(kind, text, line, bol, self.indent, flavor, value))
        self.line_has_token = True

    def start_line(self) -> None:
        start = self.i
        while self.peek() in (' ', '\t'):
            self.i += 1
        self.indent = self.i - start

    def run(self) -> tuple[list[Token], dict[int, Comment]]:
        self.start_line()
        while self.i < len(self.src):
            c = self.peek()
            if c in (' ', '\t', '\r'):
                self.i += 1
            elif c == '\n':
                self.newline(joined=False)
            elif c == '\\' and self.peek(1) in ('\n', '\r'):
                self.i += 1
                if self.peek() == '\r':
                    self.i += 1
                self.newline(joined=True)
            elif c == '#':
                self.comment()
            elif c in QUOTES:
                self.string(PLAIN)
            elif c in (STRING_NAME, NODE_PATH) and self.peek(1) in QUOTES:
                self.i += 1
                self.string(c)
            elif c == RAW and self.peek(1) in QUOTES:
                self.i += 1
                self.string(RAW)
            elif c.isdigit() or (c == '.' and self.peek(1).isdigit()):
                self.number()
            elif c.isalpha() or c == '_':
                start = self.i
                while self.peek() and (self.peek().isalnum() or self.peek() == '_'):
                    self.i += 1
                self.emit(NAME, self.src[start:self.i], self.line)
            elif c == '@':
                start = self.i
                self.i += 1
                while self.peek() and (self.peek().isalnum() or self.peek() == '_'):
                    self.i += 1
                self.emit(ANNOTATION, self.src[start + 1:self.i], self.line)
            else:
                self.operator()
        self.emit(EOF, '', self.line)
        return self.tokens, self.comments

    def newline(self, joined: bool) -> None:
        self.i += 1
        self.line += 1
        self.joined = joined
        if not joined:
            self.line_has_token = False
        self.start_line()

    def comment(self) -> None:
        start = self.i
        while self.peek() and self.peek() != '\n':
            self.i += 1
        own_line = not self.line_has_token and not self.joined
        self.comments[self.line] = Comment(self.src[start:self.i], own_line)

    def operator(self) -> None:
        for op in OPERATORS:
            if self.src.startswith(op, self.i):
                self.i += len(op)
                self.emit(OP, op, self.line)
                return
        raise GDSyntaxError(self.line, f'unexpected character {self.peek()!r}')

    def number(self) -> None:
        start, line = self.i, self.line
        src = self.src
        if src.startswith(HEX_PREFIXES, self.i) or src.startswith(BIN_PREFIXES, self.i):
            base = HEX_BASE if src[self.i + 1] in 'xX' else BIN_BASE
            self.i += 2
            while self.peek() and (self.peek().isalnum() or self.peek() == '_'):
                self.i += 1
            digits = src[start + 2:self.i].replace('_', '')
            try:
                value: object = int(digits, base)
            except ValueError as err:
                raise GDSyntaxError(line, f'bad number {src[start:self.i]!r}') from err
            self.emit(NUMBER, src[start:self.i], line, value=value)
            return
        is_float = False
        while self.peek().isdigit() or self.peek() == '_':
            self.i += 1
        if self.peek() == '.' and self.peek(1) != '.' and not (
                self.peek(1).isalpha() or self.peek(1) == '_'):
            is_float = True
            self.i += 1
            while self.peek().isdigit() or self.peek() == '_':
                self.i += 1
        if self.peek() in ('e', 'E') and (self.peek(1).isdigit() or (
                self.peek(1) in '+-' and self.peek(2).isdigit())):
            is_float = True
            self.i += 2
            while self.peek().isdigit() or self.peek() == '_':
                self.i += 1
        text = src[start:self.i].replace('_', '')
        value = float(text) if is_float else int(text)
        self.emit(NUMBER, src[start:self.i], line, value=value)

    def string(self, flavor: str) -> None:
        """`GDScriptTokenizerText::string()`: escapes, raw strings, triple quotes."""
        line = self.line
        quote = self.peek()
        self.i += 1
        multiline = self.peek() == quote and self.peek(1) == quote
        if multiline:
            self.i += 2
        out: list[str] = []
        lead = 0
        while True:
            if self.i >= len(self.src):
                raise GDSyntaxError(line, 'unterminated string')
            ch = self.peek()
            if ch == '\\':
                self.i += 1
                if self.i >= len(self.src):
                    raise GDSyntaxError(line, 'unterminated string')
                if flavor == RAW:
                    if self.peek() in (quote, '\\'):
                        out.append('\\' + self.peek())
                        self.i += 1
                    else:
                        out.append('\\')
                    continue
                code = self.peek()
                self.i += 1
                if code in ESCAPES:
                    out.append(ESCAPES[code])
                elif code in UNICODE_ESCAPE_DIGITS:
                    n = UNICODE_ESCAPE_DIGITS[code]
                    digits = self.src[self.i:self.i + n]
                    try:
                        point = int(digits, HEX_BASE)
                    except ValueError as err:
                        raise GDSyntaxError(self.line, 'bad unicode escape') from err
                    self.i += n
                    if (point & SURROGATE_MASK) == LEAD_SURROGATE:
                        lead = point
                        continue
                    if (point & SURROGATE_MASK) == TRAIL_SURROGATE and lead:
                        point = ((lead << SURROGATE_SHIFT) + point
                                 - ((LEAD_SURROGATE << SURROGATE_SHIFT)
                                    + TRAIL_SURROGATE - SUPPLEMENTARY_BASE))
                        lead = 0
                    out.append(chr(point))
                elif code == '\n':
                    self.line += 1          # an escaped newline adds nothing
                elif code == '\r' and self.peek() == '\n':
                    self.i += 1
                    self.line += 1
                else:
                    raise GDSyntaxError(self.line, f'invalid escape \\{code}')
                continue
            if ch == quote:
                self.i += 1
                if not multiline:
                    break
                if self.peek() == quote and self.peek(1) == quote:
                    self.i += 2
                    break
                out.append(quote)
                continue
            out.append(ch)
            self.i += 1
            if ch == '\n':
                if not multiline:
                    raise GDSyntaxError(line, 'unterminated string')
                self.line += 1
        self.emit(STRING, ''.join(out), line, flavor=flavor)


def tokenize(source: str) -> tuple[list[Token], dict[int, Comment]]:
    return _Scanner(source).run()


# --- tree -------------------------------------------------------------------------
# One small class per node kind the extractor or the folder distinguishes.
# `line` is GDScriptParser's `start_line`.

@dataclass
class Expr:
    line: int


@dataclass
class Literal(Expr):
    value: object
    flavor: str = PLAIN


@dataclass
class Identifier(Expr):
    name: str


@dataclass
class SelfNode(Expr):
    pass


@dataclass
class Call(Expr):
    callee: Expr | None      # None for a bare `super(...)`
    function_name: str
    args: list[Expr]
    is_super: bool = False


@dataclass
class Attribute(Expr):
    base: Expr
    name: str


@dataclass
class Subscript(Expr):
    base: Expr
    index: Expr


@dataclass
class Binary(Expr):
    op: str
    left: Expr
    right: Expr


@dataclass
class Unary(Expr):
    op: str
    operand: Expr


@dataclass
class Ternary(Expr):
    condition: Expr
    true_expr: Expr
    false_expr: Expr


@dataclass
class ArrayNode(Expr):
    elements: list[Expr]


@dataclass
class DictNode(Expr):
    pairs: list[tuple[Expr, Expr]]


@dataclass
class Lambda(Expr):
    function: 'Function'


@dataclass
class Await(Expr):
    operand: Expr


@dataclass
class Cast(Expr):
    operand: Expr
    type_name: str


@dataclass
class TypeTest(Expr):
    operand: Expr


@dataclass
class Assignment(Expr):
    op: str
    target: Expr
    value: Expr


@dataclass
class GetNode(Expr):
    pass


@dataclass
class Preload(Expr):
    path: Expr   # a constant expression; a literal in practice


# Statements.

@dataclass
class Stmt:
    line: int


@dataclass
class VarStmt(Stmt):
    name: str
    type_name: str | None
    initializer: Expr | None


@dataclass
class ConstStmt(Stmt):
    name: str
    type_name: str | None
    initializer: Expr


@dataclass
class IfStmt(Stmt):
    condition: Expr
    true_block: list[Stmt]
    false_block: list[Stmt]


@dataclass
class ForStmt(Stmt):
    variable: str
    iterable: Expr
    body: list[Stmt]


@dataclass
class WhileStmt(Stmt):
    condition: Expr
    body: list[Stmt]


@dataclass
class MatchBranch:
    binds: list[str]
    guard: Expr | None
    body: list[Stmt]


@dataclass
class MatchStmt(Stmt):
    test: Expr
    branches: list[MatchBranch]


@dataclass
class ReturnStmt(Stmt):
    value: Expr | None


@dataclass
class AssertStmt(Stmt):
    condition: Expr | None
    message: Expr | None


@dataclass
class ExprStmt(Stmt):
    expr: Expr


@dataclass
class PassStmt(Stmt):
    pass


@dataclass
class Parameter:
    name: str
    type_name: str | None
    default: Expr | None


@dataclass
class Function:
    line: int
    name: str | None
    params: list[Parameter]
    body: list[Stmt]


# Class members, in source order (`ClassNode::members`).

@dataclass
class VarMember:
    line: int
    name: str
    type_name: str | None
    initializer: Expr | None
    inline_property: bool = False
    setter: Function | None = None
    getter: Function | None = None


@dataclass
class ConstMember:
    line: int
    name: str
    type_name: str | None
    initializer: Expr


@dataclass
class EnumMember:
    line: int
    name: str | None
    values: list[tuple[str, Expr | None]]


@dataclass
class FuncMember:
    function: Function


@dataclass
class OtherMember:
    """A signal: declared, never walked, but it occupies its name."""
    line: int
    name: str


@dataclass
class ClassDecl:
    line: int
    name: str | None                  # an inner class's name; None at the top
    class_name: str | None = None     # `class_name X` (top level only)
    extends: str | None = None        # the raw target: a quoted path or a dotted name
    extends_is_path: bool = False
    members: list = field(default_factory=list)


@dataclass
class Script:
    root: ClassDecl
    comments: dict[int, Comment]


# --- parser -----------------------------------------------------------------------

STATEMENT_KEYWORDS = frozenset(('pass', 'break', 'continue', 'breakpoint'))


class _Parser:
    def __init__(self, tokens: list[Token]):
        self.toks = tokens
        self.i = 0
        self.multiline = False
        self.lambda_depth = 0

    # --- token helpers ---
    def peek(self, k: int = 0) -> Token:
        j = min(self.i + k, len(self.toks) - 1)
        return self.toks[j]

    def advance(self) -> Token:
        tok = self.toks[self.i]
        if tok.kind != EOF:
            self.i += 1
        return tok

    @staticmethod
    def is_op(tok: Token, *texts: str) -> bool:
        return tok.kind == OP and tok.text in texts

    @staticmethod
    def is_name(tok: Token, *texts: str) -> bool:
        return tok.kind == NAME and tok.text in texts

    def expect_op(self, text: str) -> Token:
        tok = self.advance()
        if not self.is_op(tok, text):
            raise GDSyntaxError(tok.line, f'expected {text!r}, got {tok.text!r}')
        return tok

    def expect_name(self) -> Token:
        tok = self.advance()
        if tok.kind != NAME:
            raise GDSyntaxError(tok.line, f'expected a name, got {tok.text!r}')
        return tok

    def breaks_line(self, tok: Token) -> bool:
        """Does `tok` start a new statement line in the current mode?"""
        return tok.kind == EOF or (tok.bol and not self.multiline)

    # --- statement ends ---
    def end_statement(self) -> None:
        tok = self.peek()
        if self.breaks_line(tok):
            return
        if self.lambda_depth and self.is_op(tok, *LAMBDA_TERMINATORS):
            return
        raise GDSyntaxError(tok.line, f'unexpected {tok.text!r} after a statement')

    def statement_line(self, parse_one) -> list:
        """One statement, then any `;`-joined statements on the same line."""
        out = [parse_one()]
        while self.is_op(self.peek(), ';'):
            self.advance()
            tok = self.peek()
            if self.breaks_line(tok) or (self.lambda_depth and self.is_op(tok, *LAMBDA_TERMINATORS)):
                break
            out.append(parse_one())
        out = [s for s in out if s is not None]
        self.end_statement()
        return out

    def block(self, parse_one) -> list:
        """The suite after a `:` — indented lines, or the rest of this line."""
        saved = self.multiline
        self.multiline = False
        tok = self.peek()
        out: list = []
        if tok.bol and tok.kind != EOF:
            indent = tok.indent
            while True:
                tok = self.peek()
                if tok.kind == EOF or not tok.bol or tok.indent < indent:
                    break
                out.extend(self.statement_line(parse_one))
        else:
            out.extend(self.statement_line(parse_one))
        self.multiline = saved
        return out

    # --- types ---
    def type_name(self) -> str:
        tok = self.expect_name()
        parts = [tok.text]
        while self.is_op(self.peek(), '.') and self.peek(1).kind == NAME:
            self.advance()
            parts.append(self.advance().text)
        if self.is_op(self.peek(), '['):
            self.skip_balanced()
        return '.'.join(parts)

    def skip_balanced(self) -> None:
        """Skip one bracketed group, opening bracket included."""
        opener = self.advance()
        stack = [OPEN_BRACKETS[opener.text]]
        while stack:
            tok = self.advance()
            if tok.kind == EOF:
                raise GDSyntaxError(opener.line, f'unclosed {opener.text!r}')
            if tok.kind == OP and tok.text in OPEN_BRACKETS:
                stack.append(OPEN_BRACKETS[tok.text])
            elif tok.kind == OP and tok.text in CLOSE_BRACKETS:
                if tok.text != stack.pop():
                    raise GDSyntaxError(tok.line, f'mismatched {tok.text!r}')

    def annotation(self) -> None:
        self.advance()
        if self.is_op(self.peek(), '(') and not self.peek().bol:
            self.skip_balanced()

    # --- class body ---
    def script(self) -> ClassDecl:
        root = ClassDecl(1, None)
        while self.peek().kind != EOF:
            tok = self.peek()
            if not tok.bol:
                raise GDSyntaxError(tok.line, f'unexpected {tok.text!r}')
            self.statement_line(lambda: self.member(root))
        return root

    def member(self, cls: ClassDecl):
        tok = self.peek()
        while tok.kind == ANNOTATION:
            self.annotation()
            tok = self.peek()
            if tok.kind == EOF or (tok.bol and not self.multiline):
                return None  # a standalone annotation line (`@tool`, `@export_group(...)`)
        if self.is_op(tok, ';'):
            return None
        if tok.kind != NAME:
            raise GDSyntaxError(tok.line, f'unexpected {tok.text!r} in a class body')
        word = tok.text
        if word == 'pass':
            self.advance()
            return None
        if word == 'class_name':
            self.advance()
            cls.class_name = self.expect_name().text
            if self.is_name(self.peek(), 'extends'):
                self.advance()
                self.extends(cls)
            return None
        if word == 'extends':
            self.advance()
            self.extends(cls)
            return None
        if word == 'static':
            self.advance()
            return self.member(cls)
        if word == 'var':
            member = self.var_member()
        elif word == 'const':
            member = self.const_member()
        elif word == 'func':
            member = FuncMember(self.function(named=True))
        elif word == 'signal':
            self.advance()
            name = self.expect_name()
            if self.is_op(self.peek(), '('):
                self.skip_balanced()
            member = OtherMember(name.line, name.text)
        elif word == 'enum':
            member = self.enum_member()
        elif word == 'class':
            member = self.inner_class()
        else:
            raise GDSyntaxError(tok.line, f'unexpected {word!r} in a class body')
        cls.members.append(member)
        return None

    def extends(self, cls: ClassDecl) -> None:
        tok = self.peek()
        if tok.kind == STRING:
            self.advance()
            cls.extends, cls.extends_is_path = tok.text, True
            while self.is_op(self.peek(), '.'):
                self.advance()
                cls.extends = None  # `extends "a.gd".Inner`: not followed
                self.expect_name()
            return
        cls.extends = self.type_name()

    def inner_class(self) -> ClassDecl:
        self.advance()
        name = self.expect_name()
        decl = ClassDecl(name.line, name.text)
        if self.is_name(self.peek(), 'extends'):
            self.advance()
            self.extends(decl)
        self.expect_op(':')
        self.block(lambda: self.member(decl))
        return decl

    def var_member(self) -> VarMember:
        self.advance()
        name = self.expect_name()
        member = VarMember(name.line, name.text, None, None)
        property_follows = False
        if self.is_op(self.peek(), ':'):
            self.advance()
            nxt = self.peek()
            if self.is_op(nxt, '='):
                pass
            elif nxt.bol or nxt.kind == EOF:
                property_follows = True
            else:
                member.type_name = self.type_name()
        if not property_follows and self.is_op(self.peek(), '='):
            self.advance()
            member.initializer = self.expression()
        if property_follows or self.is_op(self.peek(), ':'):
            if not property_follows:
                self.advance()
            self.property(member)
        return member

    def property(self, member: VarMember) -> None:
        saved = self.multiline
        self.multiline = False
        tok = self.peek()
        if tok.bol and tok.kind != EOF:
            indent = tok.indent
            while self.peek().kind != EOF and self.peek().bol and self.peek().indent >= indent:
                self.property_item(member)
                if self.is_op(self.peek(), ','):
                    self.advance()
        else:
            self.property_item(member)
            while self.is_op(self.peek(), ','):
                self.advance()
                self.property_item(member)
        self.multiline = saved

    def property_item(self, member: VarMember) -> None:
        tok = self.expect_name()
        if tok.text not in ('set', 'get'):
            raise GDSyntaxError(tok.line, f'expected set or get, got {tok.text!r}')
        if self.is_op(self.peek(), '='):
            self.advance()
            self.expect_name()
            return
        params: list[Parameter] = []
        if self.is_op(self.peek(), '('):
            params = self.parameters()
        self.expect_op(':')
        body = self.block(self.statement)
        function = Function(tok.line, tok.text, params, body)
        member.inline_property = True
        if tok.text == 'set':
            member.setter = function
        else:
            member.getter = function

    def const_member(self) -> ConstMember:
        stmt = self.const_statement()
        return ConstMember(stmt.line, stmt.name, stmt.type_name, stmt.initializer)

    def enum_member(self) -> EnumMember:
        start = self.advance()
        name = None
        if self.peek().kind == NAME:
            name = self.advance().text
        self.expect_op('{')
        saved = self.multiline
        self.multiline = True
        values: list[tuple[str, Expr | None]] = []
        while not self.is_op(self.peek(), '}'):
            key = self.expect_name().text
            value = None
            if self.is_op(self.peek(), '='):
                self.advance()
                value = self.expression()
            values.append((key, value))
            if self.is_op(self.peek(), ','):
                self.advance()
            elif not self.is_op(self.peek(), '}'):
                raise GDSyntaxError(self.peek().line, 'expected , or } in an enum')
        self.advance()
        self.multiline = saved
        return EnumMember(start.line, name, values)

    def parameters(self) -> list[Parameter]:
        self.expect_op('(')
        saved = self.multiline
        self.multiline = True
        params: list[Parameter] = []
        while not self.is_op(self.peek(), ')'):
            if self.is_op(self.peek(), '...'):
                self.advance()
            name = self.expect_name().text
            type_name = None
            default = None
            if self.is_op(self.peek(), ':'):
                self.advance()
                if not self.is_op(self.peek(), '='):
                    type_name = self.type_name()
            if self.is_op(self.peek(), '='):
                self.advance()
                default = self.expression()
            params.append(Parameter(name, type_name, default))
            if self.is_op(self.peek(), ','):
                self.advance()
            elif not self.is_op(self.peek(), ')'):
                raise GDSyntaxError(self.peek().line, 'expected , or ) in parameters')
        self.advance()
        self.multiline = saved
        return params

    def function(self, named: bool) -> Function:
        start = self.advance()  # `func`
        name = None
        if named or self.peek().kind == NAME:
            name = self.expect_name().text
        params = self.parameters()
        if self.is_op(self.peek(), '->'):
            self.advance()
            if self.is_name(self.peek(), 'void'):
                self.advance()
            else:
                self.type_name()
        if named and self.breaks_line(self.peek()):
            return Function(start.line, name, params, [])  # `@abstract`: no body
        self.expect_op(':')
        body = self.block(self.statement)
        return Function(start.line, name, params, body)

    # --- statements ---
    def statement(self):
        tok = self.peek()
        while tok.kind == ANNOTATION:
            self.annotation()
            tok = self.peek()
        if self.is_op(tok, ';'):
            return None
        if tok.kind == NAME:
            word = tok.text
            if word in STATEMENT_KEYWORDS:
                self.advance()
                return PassStmt(tok.line)
            if word == 'return':
                self.advance()
                nxt = self.peek()
                value = None
                if not (self.breaks_line(nxt) or self.is_op(nxt, ';')
                        or (self.lambda_depth and self.is_op(nxt, *LAMBDA_TERMINATORS))):
                    value = self.expression()
                return ReturnStmt(tok.line, value)
            if word == 'var':
                return self.var_statement()
            if word == 'const':
                return self.const_statement()
            if word == 'if':
                return self.if_statement()
            if word == 'for':
                return self.for_statement()
            if word == 'while':
                self.advance()
                condition = self.expression()
                self.expect_op(':')
                return WhileStmt(tok.line, condition, self.block(self.statement))
            if word == 'match':
                return self.match_statement()
            if word == 'assert':
                return self.assert_statement()
            if word == 'static':
                self.advance()
                return self.statement()
        expr = self.expression(can_assign=True)
        return ExprStmt(expr.line, expr)

    def var_statement(self) -> VarStmt:
        start = self.advance()
        name = self.expect_name().text
        type_name = None
        initializer = None
        if self.is_op(self.peek(), ':'):
            self.advance()
            if not self.is_op(self.peek(), '='):
                type_name = self.type_name()
        if self.is_op(self.peek(), '='):
            self.advance()
            initializer = self.expression()
        return VarStmt(start.line, name, type_name, initializer)

    def const_statement(self) -> ConstStmt:
        start = self.advance()
        name = self.expect_name().text
        type_name = None
        if self.is_op(self.peek(), ':'):
            self.advance()
            if not self.is_op(self.peek(), '='):
                type_name = self.type_name()
        self.expect_op('=')
        return ConstStmt(start.line, name, type_name, self.expression())

    def if_statement(self) -> IfStmt:
        start = self.advance()
        condition = self.expression()
        self.expect_op(':')
        true_block = self.block(self.statement)
        false_block: list = []
        nxt = self.peek()
        if self.is_name(nxt, 'elif'):
            false_block = [self.if_statement()]
        elif self.is_name(nxt, 'else'):
            self.advance()
            self.expect_op(':')
            false_block = self.block(self.statement)
        return IfStmt(start.line, condition, true_block, false_block)

    def for_statement(self) -> ForStmt:
        start = self.advance()
        variable = self.expect_name().text
        if self.is_op(self.peek(), ':'):
            self.advance()
            self.type_name()
        tok = self.advance()
        if not self.is_name(tok, 'in'):
            raise GDSyntaxError(tok.line, 'expected in')
        iterable = self.expression()
        self.expect_op(':')
        return ForStmt(start.line, variable, iterable, self.block(self.statement))

    def assert_statement(self) -> AssertStmt:
        start = self.advance()
        self.expect_op('(')
        saved = self.multiline
        self.multiline = True
        condition = message = None
        if not self.is_op(self.peek(), ')'):
            condition = self.expression()
            if self.is_op(self.peek(), ','):
                self.advance()
                if not self.is_op(self.peek(), ')'):
                    message = self.expression()
                    if self.is_op(self.peek(), ','):
                        self.advance()
        self.expect_op(')')
        self.multiline = saved
        return AssertStmt(start.line, condition, message)

    def match_statement(self) -> MatchStmt:
        start = self.advance()
        test = self.expression()
        self.expect_op(':')
        saved = self.multiline
        self.multiline = False
        branches: list[MatchBranch] = []
        tok = self.peek()
        if not tok.bol:
            raise GDSyntaxError(tok.line, 'expected match branches on new lines')
        indent = tok.indent
        while self.peek().kind != EOF and self.peek().bol and self.peek().indent >= indent:
            while self.peek().kind == ANNOTATION:
                self.annotation()
            branches.append(self.match_branch())
        self.multiline = saved
        return MatchStmt(start.line, test, branches)

    def match_branch(self) -> MatchBranch:
        binds: list[str] = []
        stack: list[str] = []
        guard = None
        while True:
            tok = self.peek()
            if tok.kind == EOF:
                raise GDSyntaxError(tok.line, 'unterminated match pattern')
            if not stack and self.is_op(tok, ':'):
                self.advance()
                break
            if not stack and self.is_name(tok, 'when'):
                self.advance()
                guard = self.expression()
                self.expect_op(':')
                break
            self.advance()
            if self.is_name(tok, 'var') and self.peek().kind == NAME:
                binds.append(self.advance().text)
            elif tok.kind == OP and tok.text in OPEN_BRACKETS:
                stack.append(OPEN_BRACKETS[tok.text])
            elif tok.kind == OP and tok.text in CLOSE_BRACKETS:
                if not stack or stack.pop() != tok.text:
                    raise GDSyntaxError(tok.line, f'mismatched {tok.text!r}')
        return MatchBranch(binds, guard, self.block(self.statement))

    # --- expressions (Pratt, GDScriptParser::parse_precedence) ---
    def expression(self, can_assign: bool = False) -> Expr:
        return self.precedence(PREC_ASSIGNMENT if can_assign else PREC_CAST)

    def infix_precedence(self, tok: Token) -> int:
        if tok.kind == EOF or (tok.bol and not self.multiline):
            return PREC_NONE
        if tok.kind == OP:
            if tok.text in ASSIGNMENT_OPS:
                return PREC_ASSIGNMENT
            if tok.text == '(':
                return PREC_CALL
            if tok.text == '[':
                return PREC_SUBSCRIPT
            if tok.text == '.':
                return PREC_ATTRIBUTE
            return BINARY_OPS.get(tok.text, PREC_NONE)
        if tok.kind == NAME:
            if tok.text == 'if':
                return PREC_TERNARY
            if tok.text == 'as':
                return PREC_CAST
            if tok.text == 'is':
                return PREC_TYPE_TEST
            if tok.text == 'not':
                return PREC_CONTENT_TEST
            return BINARY_OPS.get(tok.text, PREC_NONE)
        return PREC_NONE

    def precedence(self, minimum: int) -> Expr:
        left = self.prefix()
        while True:
            tok = self.peek()
            prec = self.infix_precedence(tok)
            if prec == PREC_NONE or prec < minimum:
                return left
            if isinstance(left, Lambda) and not self.multiline:
                return left
            left = self.infix(left, tok, prec)

    def infix(self, left: Expr, tok: Token, prec: int) -> Expr:
        self.advance()
        text = tok.text
        if tok.kind == OP and text in ASSIGNMENT_OPS:
            return Assignment(left.line, text, left, self.precedence(PREC_ASSIGNMENT))
        if tok.kind == OP and text == '(':
            return self.call(left)
        if tok.kind == OP and text == '[':
            saved = self.multiline
            self.multiline = True
            index = self.expression()
            self.expect_op(']')
            self.multiline = saved
            return Subscript(left.line, left, index)
        if tok.kind == OP and text == '.':
            name = self.advance()
            if name.kind != NAME:
                raise GDSyntaxError(name.line, f'expected an attribute, got {name.text!r}')
            return Attribute(left.line, left, name.text)
        if text == 'if':
            condition = self.precedence(PREC_TERNARY)
            tok_else = self.advance()
            if not self.is_name(tok_else, 'else'):
                raise GDSyntaxError(tok_else.line, 'expected else in a ternary')
            false_expr = self.precedence(PREC_TERNARY)
            return Ternary(left.line, condition, left, false_expr)
        if text == 'as':
            return Cast(left.line, left, self.type_name())
        if text == 'is':
            if self.is_name(self.peek(), 'not'):
                self.advance()
            self.type_name()
            return TypeTest(left.line, left)
        if text == 'not':
            tok_in = self.advance()
            if not self.is_name(tok_in, 'in'):
                raise GDSyntaxError(tok_in.line, 'expected in after not')
            right = self.precedence(PREC_CONTENT_TEST + 1)
            return Unary(left.line, '!', Binary(left.line, 'in', left, right))
        right = self.precedence(prec + 1)
        return Binary(left.line, OP_ALIASES.get(text, text), left, right)

    def call(self, callee: Expr) -> Call:
        args = self.arguments()
        if isinstance(callee, Identifier):
            name = callee.name
        elif isinstance(callee, Attribute):
            name = callee.name
        else:
            name = ''
        return Call(callee.line, callee, name, args)

    def arguments(self) -> list[Expr]:
        """After the `(`: the comma-separated arguments and the `)`."""
        saved = self.multiline
        self.multiline = True
        args: list[Expr] = []
        while not self.is_op(self.peek(), ')'):
            args.append(self.expression())
            if self.is_op(self.peek(), ','):
                self.advance()
            elif not self.is_op(self.peek(), ')'):
                raise GDSyntaxError(self.peek().line, f'expected , or ) — got {self.peek().text!r}')
        self.advance()
        self.multiline = saved
        return args

    def prefix(self) -> Expr:
        tok = self.advance()
        line = tok.line
        if tok.kind == NUMBER:
            return Literal(line, tok.value)
        if tok.kind == STRING:
            return Literal(line, tok.text, tok.flavor)
        if tok.kind == NAME:
            word = tok.text
            if word in LITERAL_NAMES:
                return Literal(line, LITERAL_NAMES[word])
            if word in BUILTIN_CONSTANTS:
                return Literal(line, BUILTIN_CONSTANTS[word])
            if word == 'self':
                return SelfNode(line)
            if word == 'super':
                return self.super_call(tok)
            if word == 'preload':
                self.expect_op('(')
                saved = self.multiline
                self.multiline = True
                path = self.expression()
                if self.is_op(self.peek(), ','):
                    self.advance()
                self.expect_op(')')
                self.multiline = saved
                return Preload(line, path)
            if word == 'func':
                self.i -= 1
                return self.lambda_()
            if word == 'await':
                return Await(line, self.precedence(PREC_AWAIT))
            if word == 'not':
                return Unary(line, '!', self.precedence(PREC_LOGIC_NOT))
            return Identifier(line, word)
        if tok.kind == OP:
            text = tok.text
            if text == '(':
                saved = self.multiline
                self.multiline = True
                inner = self.expression()
                self.expect_op(')')
                self.multiline = saved
                return inner
            if text == '[':
                return ArrayNode(line, self.items(']'))
            if text == '{':
                return self.dictionary(line)
            if text in UNARY_OPS:
                return Unary(line, '!' if text == 'not' else text, self.precedence(UNARY_OPS[text]))
            if text in ('$', '%'):
                return self.get_node(line)
        raise GDSyntaxError(line, f'unexpected {tok.text!r} in an expression')

    def items(self, closer: str) -> list[Expr]:
        saved = self.multiline
        self.multiline = True
        out: list[Expr] = []
        while not self.is_op(self.peek(), closer):
            out.append(self.expression())
            if self.is_op(self.peek(), ','):
                self.advance()
            elif not self.is_op(self.peek(), closer):
                raise GDSyntaxError(self.peek().line, f'expected , or {closer}')
        self.advance()
        self.multiline = saved
        return out

    def dictionary(self, line: int) -> DictNode:
        saved = self.multiline
        self.multiline = True
        pairs: list[tuple[Expr, Expr]] = []
        while not self.is_op(self.peek(), '}'):
            if self.peek().kind == NAME and self.is_op(self.peek(1), '='):
                key_tok = self.advance()
                self.advance()
                key: Expr = Literal(key_tok.line, key_tok.text)
            else:
                key = self.expression()
                self.expect_op(':')
            pairs.append((key, self.expression()))
            if self.is_op(self.peek(), ','):
                self.advance()
            elif not self.is_op(self.peek(), '}'):
                raise GDSyntaxError(self.peek().line, 'expected , or } in a dictionary')
        self.advance()
        self.multiline = saved
        return DictNode(line, pairs)

    def get_node(self, line: int) -> GetNode:
        """`$Path/To`, `$"path"`, `%Unique`: one node, nothing to extract."""
        if self.peek().kind == STRING:
            self.advance()
            return GetNode(line)
        while True:
            if self.is_op(self.peek(), '%'):
                self.advance()
            tok = self.advance()
            if not (tok.kind in (NAME, NUMBER) or self.is_op(tok, '.', '..')):
                raise GDSyntaxError(tok.line, f'unexpected {tok.text!r} in a node path')
            if self.is_op(self.peek(), '/') and not self.peek().bol:
                self.advance()
                continue
            return GetNode(line)

    def super_call(self, tok: Token) -> Expr:
        if self.is_op(self.peek(), '.'):
            self.advance()
            name = self.expect_name()
            self.expect_op('(')
            return Call(tok.line, None, name.text, self.arguments(), is_super=True)
        self.expect_op('(')
        return Call(tok.line, None, '', self.arguments(), is_super=True)

    def lambda_(self) -> Lambda:
        start = self.peek()
        saved_depth = self.lambda_depth
        if self.multiline:
            self.lambda_depth += 1
        function = self.function(named=False)
        self.lambda_depth = saved_depth
        return Lambda(start.line, function)


def parse(source: str) -> Script:
    """Parse one script, or raise `GDSyntaxError`."""
    tokens, comments = tokenize(source)
    return Script(_Parser(tokens).script(), comments)
