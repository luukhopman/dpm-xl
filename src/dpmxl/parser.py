"""Tokenizer and recursive-descent parser for DPM-XL expressions.

:func:`tokenize` splits an expression into typed :class:`Token` objects that
suit syntax highlighting as well as parsing: selections are split into their
table, axis and option tokens rather than captured whole. :func:`parse` builds
the expression tree of :mod:`dpmxl.ast` from those tokens.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Literal, NamedTuple, cast

from .ast import (
    AXIS_PREFIXES,
    MISSING,
    Assignment,
    AxisSelector,
    Binary,
    Call,
    Get,
    If,
    In,
    Item,
    Literal_,
    Name,
    Node,
    Parameter,
    PersistentAssignment,
    Program,
    Rename,
    Selection,
    SelectionSpec,
    SetLiteral,
    Sub,
    TableReported,
    TypedParameter,
    Unary,
    Where,
    With,
    _Missing,
)
from .grammar import (
    FUNCTION_ALIASES,
    FUNCTIONS,
    KEYWORDS,
    REFERENCE_PREFIXES,
    TIME_PERIODS,
    WINDOW_KEYWORDS,
)
from .values import DECIMAL_CONTEXT


class DpmXlSyntaxError(ValueError):
    """Raised when an expression does not match the DPM-XL grammar."""

    def __init__(
        self, message: str, expression: str, position: int, end: int | None = None
    ) -> None:
        """Record the failing source range.

        Args:
            message: What was expected or found.
            expression: The complete source expression.
            position: Zero-based character offset where the error starts.
            end: Offset just past the offending text; defaults to one
                character after ``position`` (or ``position`` at the end of
                the expression).
        """
        self.message = message
        self.expression = expression
        self.position = position
        if end is None:
            end = min(position + 1, len(expression))
        self.end = max(end, position)
        super().__init__(f"{message} at position {position}")

    def pointer(self) -> str:
        """Render the source line and mark the failing range.

        Returns:
            str: Two lines suitable for terminal output: the source line and a
            ``^`` under the error's start, followed by ``~`` under the rest of
            the offending text on that line.
        """
        start = self.expression.rfind("\n", 0, self.position) + 1
        end = self.expression.find("\n", self.position)
        line_end = end if end >= 0 else len(self.expression)
        line = self.expression[start:line_end]
        width = max(min(self.end, line_end) - self.position, 1)
        return f"{line}\n{' ' * (self.position - start)}^{'~' * (width - 1)}"


class Token(NamedTuple):
    """One lexical token: its kind, source text and half-open offsets.

    ``text`` is exactly ``expression[start:end]``, quotes, brackets and
    backticks included. ``kind`` is one of :data:`dpmxl.grammar.TOKEN_KINDS`:

    * ``keyword``: ``if``, ``and``, ``with``, ``where``, ``group by``, window
      keywords inside ``over (...)``, and ``default``/``interval`` in a
      selection;
    * ``type``: a parameter type such as ``number`` or ``set-item``;
    * ``function``: a known function name followed by ``(``;
    * ``operator``: ``+ - * / & % = != <> < <= > >= := <-``;
    * ``punctuation``: ``( ) , : ; [ ]``;
    * ``brace``: ``{`` or ``}`` around a selection or set;
    * ``table``, ``table_group``, ``variable``, ``operation``, ``parameter``:
      a selection reference with its prefix, such as ``tC_01.00``;
    * ``axis``: a row, column or sheet coordinate, range or wildcard, such as
      ``r0010``, ``c0010-0050`` or ``s*``;
    * ``number``, ``string``, ``date``, ``boolean``, ``null``: literals;
    * ``item``: an item such as ``[eba_qEC:qx01]``;
    * ``period``: a ``time_shift`` or window period code (``A``, ``Q``, ...);
    * ``identifier``: a key, temporary or other name, including escaped
      names such as ```x.y```;
    * ``eof``: the empty token that ends every token list.
    """

    kind: str
    text: str
    start: int
    end: int


_EOF = Token("eof", "", 0, 0)
_CALLERS = frozenset({"function", "identifier"})


_KIND_NAMES = {
    "eof": "end of expression",
    "identifier": "a name",
    "number": "a number",
    "string": "a string",
    "keyword": "a keyword",
}


def _describe(token: Token) -> str:
    """Name a token for an error message.

    Returns:
        str: For example ``end of expression``, ``number 5`` or ``')'``.
    """
    if token.kind == "eof":
        return "end of expression"
    if token.kind == "number":
        return f"number {token.text}"
    return repr(token.text) if token.text else _KIND_NAMES.get(token.kind, token.kind)


_EXPRESSION_KEYWORDS = KEYWORDS - {"group by"}
_COMPARISON_OPERATORS = frozenset({"=", "!=", "<>", "<", "<=", ">", ">="})
_NUMBER = r"\d+(?:\.\d+)?(?:[eE][+-]?\d+)?|\.\d+"
# Expression mode: everything outside braces, clause brackets included. Most
# groups are named after the token kind they produce; leading whitespace is
# skipped by the pattern itself.
_EXPRESSION = re.compile(
    rf"""\s*(?:
    (?P<number>{_NUMBER})
  | (?P<call>[A-Za-z_](?:[A-Za-z0-9_.]*[A-Za-z0-9_])?(?=\s*\())
  | (?P<keyword>(?i:(?:group|partition|order)\s+by|current\s+data\s+point
        |data\s+points)(?![A-Za-z0-9_]))
  | (?P<word>[A-Za-z_](?:[A-Za-z0-9_.]*[A-Za-z0-9_])?)
  | (?P<operator>:=|<-|<>|!=|<=|>=|[=<>+\-*/%&])
  | (?P<punctuation>[(),:;\]])
  | (?P<brace>[{{}}])
  | (?P<string>"[^"]*"|'[^']*')
  | (?P<clause>\[(?=\s*(?i:where|get|sub|rename)(?![A-Za-z0-9_])))
  | (?P<item>\[[^\]]*\])
  | (?P<date>\#[^#]*\#)
  | (?P<identifier>`[^`]*`)
  | (?P<error>\S)
    )""",
    re.VERBOSE,
)
# Selection mode: inside braces.
_SELECTION = re.compile(
    rf"""\s*(?:
    (?P<type>(?i:set-(?:number|integer|string|date|boolean|item)
        |number|integer|string|date|boolean|item)(?![A-Za-z0-9_.\-]))
  | (?P<axis>[rcs](?:\*|[0-9A-Za-z]+(?:-[0-9A-Za-z]+)?)(?![A-Za-z0-9_.\-]))
  | (?P<punctuation>[(),:])
  | (?P<brace>[{{}}])
  | (?P<keyword>(?i:default|interval)(?![A-Za-z0-9_.\-]))
  | (?P<literal>(?i:true|false|null)(?![A-Za-z0-9_.\-]))
  | (?P<reference>[tgvop](?:`[^`]*`|[A-Za-z0-9_.\-]+))
  | (?P<number>{_NUMBER})
  | (?P<identifier>[A-Za-z_][A-Za-z0-9_.\-]*)
  | (?P<operator>[+\-])
  | (?P<string>"[^"]*"|'[^']*')
  | (?P<item>\[[^\]]*\])
  | (?P<date>\#[^#]*\#)
  | (?P<error>\S)
    )""",
    re.VERBOSE,
)
# Groups whose name is the token kind.
_DIRECT_KINDS = frozenset(
    {
        "number",
        "operator",
        "keyword",
        "identifier",
        "axis",
        "type",
        "string",
        "item",
        "date",
    }
)
_UNTERMINATED = {
    '"': "unterminated string",
    "'": "unterminated string",
    "#": "unterminated date",
    "[": "unterminated item",
    "`": "unterminated escaped name",
}
# Parentheses, signs, not, if, calls, with contexts and chained clauses
# ({x} [where ...] [sub ...]) nest at most this deep (EBA rules nest below
# ten), well within Python's recursion limit when the tree is evaluated and
# explained.
MAX_NESTING = 50


def tokenize(expression: str) -> list[Token]:
    """Split an expression into typed tokens.

    The tokenizer follows the lexical modes of the DPM-XL grammar: inside
    ``{...}`` it reads selection components (table, axis and option tokens,
    parameter types), elsewhere expression tokens. Whitespace is skipped;
    concatenating the token texts with the source between them gives the
    expression back. See :class:`Token` for the kinds.

    Returns:
        list[Token]: Tokens ending with an ``eof`` token.

    Raises:
        DpmXlSyntaxError: On an unterminated literal, brace or item, or an
            unknown character.
    """
    return _scan(expression)


def _scan(
    text: str, *, source: str | None = None, offset: int = 0, selection: bool = False
) -> list[Token]:
    """Tokenize ``text``, which starts at ``offset`` in ``source``.

    Args:
        text: The text to tokenize.
        source: The complete expression, for errors; defaults to ``text``.
        offset: Offset of ``text`` in ``source``, added to token offsets.
        selection: Start inside a selection (for :func:`parse_selection`).

    Returns:
        list[Token]: Tokens ending with an ``eof`` token.

    Raises:
        DpmXlSyntaxError: On a lexical error.
    """
    source = text if source is None else source
    tokens: list[Token] = []
    append = tokens.append
    new = tuple.__new__
    # Open braces ("s") and clause brackets ("c"); the top decides the mode.
    modes: list[str] = ["s"] if selection else []
    braces: list[int] = []
    # What each open parenthesis belongs to: a function name, "over" or None.
    owners: list[str | None] = []
    previous = _EOF
    position = 0
    pattern = _SELECTION if selection else _EXPRESSION
    while True:
        # Scan in one mode until a brace switches it.
        switch = None
        for match in pattern.finditer(text, position):
            group = cast(str, match.lastgroup)
            value = match.group(group)
            end = match.end()
            start = end - len(value)
            if group in _DIRECT_KINDS:
                kind = group
            elif group == "punctuation":
                kind = group
                if value == "(":
                    owners.append(
                        previous.text.casefold()
                        if previous.kind in _CALLERS
                        or (
                            previous.kind == "keyword"
                            and previous.text.casefold() == "over"
                        )
                        else None
                    )
                elif value == ")":
                    if owners:
                        owners.pop()
                elif value == "]" and modes and modes[-1] == "c":
                    modes.pop()
            elif group == "word" or group == "call":
                kind = _word_kind(value, group, owners, previous)
            elif group == "brace":
                kind = group
                if value == "{":
                    modes.append("s")
                    braces.append(start + offset)
                    switch = _SELECTION
                elif modes and modes[-1] == "s":
                    modes.pop()
                    if braces:
                        braces.pop()
                    switch = _SELECTION if modes and modes[-1] == "s" else _EXPRESSION
            elif group == "clause":
                kind = "punctuation"
                modes.append("c")
            elif group == "literal":
                kind = "null" if value.casefold() == "null" else "boolean"
            elif group == "reference":
                kind = REFERENCE_PREFIXES[value[0]]
            else:
                error = _lex_error(
                    text, source, offset, start, braces, selecting=pattern is _SELECTION
                )
                raise error
            previous = new(Token, (kind, value, start + offset, end + offset))
            append(previous)
            if switch is not None:
                break
        if switch is None:
            break
        pattern = switch
        position = end
    if braces:
        _matching(source, braces[0], "{", "}")
    length = len(text) + offset
    append(new(Token, ("eof", "", length, length)))
    return tokens


def _word_kind(word: str, group: str, owners: list[str | None], previous: Token) -> str:
    """Classify a word outside selections by its text and context.

    Returns:
        str: The token kind.
    """
    folded = word.casefold()
    if folded in _EXPRESSION_KEYWORDS:
        return "keyword"
    if folded in {"true", "false"}:
        return "boolean"
    if folded == "null":
        return "null"
    owner = owners[-1] if owners else None
    if owner == "over" and folded in WINDOW_KEYWORDS:
        return "keyword"
    if word in TIME_PERIODS and (
        (owner == "time_shift" and previous.text == ",")
        or (owner == "over" and previous.kind == "number")
    ):
        return "period"
    if group == "call" and folded in FUNCTIONS:
        return "function"
    return "identifier"


def _lex_error(
    text: str,
    source: str,
    offset: int,
    index: int,
    braces: list[int],
    *,
    selecting: bool,
) -> DpmXlSyntaxError:
    """Describe the character the tokenizer cannot read.

    Returns:
        DpmXlSyntaxError: The error to raise.
    """
    position = index + offset
    if braces:
        # An unterminated brace explains the rest better than its content.
        _matching(source, braces[0], "{", "}")
    char = text[index]
    if char in _UNTERMINATED:
        return DpmXlSyntaxError(_UNTERMINATED[char], source, position)
    if selecting:
        component = re.match(r"[^,{}]*", text[index:])
        found = component.group().strip() if component else char
        return DpmXlSyntaxError(
            f"unknown selection component {found!r}",
            source,
            position,
            position + len(found),
        )
    return DpmXlSyntaxError(f"unexpected character {char!r}", source, position)


def parse(expression: str) -> Node:
    """Parse a complete DPM-XL expression.

    A trailing ``;`` is allowed. Several statements and assignments need
    :func:`parse_program`.

    Returns:
        Node: The expression tree.

    Raises:
        DpmXlSyntaxError: If the text is not a valid expression.
    """
    if not expression or not expression.strip():
        raise DpmXlSyntaxError("empty expression", expression or "", 0)
    if not _may_be_program(expression):
        parser = _Parser(expression, _scan(expression))
        try:
            node = parser.parse_root()
        except RecursionError:  # pragma: no cover - MAX_NESTING applies first
            raise DpmXlSyntaxError(
                "expression too deeply nested", expression, 0
            ) from None
        parser.expect_end()
        return node
    program = parse_program(expression)
    first = program.statements[0]
    if len(program.statements) > 1:
        second = program.statements[1]
        raise DpmXlSyntaxError(
            "several statements need parse_program",
            expression,
            second.span[0],
            second.span[1],
        )
    if isinstance(first, Assignment | PersistentAssignment):
        raise DpmXlSyntaxError(
            "assignments need parse_program", expression, *first.span
        )
    return first


def parse_program(source: str) -> Program:
    """Parse statements separated by ``;``, with assignments.

    A statement is an expression (with an optional ``with`` context), a
    temporary assignment ``name := expression`` or a persistent assignment
    ``{target} <- expression``. A trailing ``;`` is allowed.

    Returns:
        Program: The statements, also when there is only one.

    Raises:
        DpmXlSyntaxError: If the text is not a valid program.
    """
    if not source or not source.strip():
        raise DpmXlSyntaxError("empty expression", source or "", 0)
    parser = _Parser(source, _scan(source))
    statements = [parser.parse_statement()]
    while parser.accept(";"):
        if parser.current.kind == "eof":
            break
        statements.append(parser.parse_statement())
    parser.expect_end()
    return Program(
        tuple(statements), span=(statements[0].span[0], statements[-1].span[1])
    )


def _may_be_program(expression: str) -> bool:
    return ";" in expression or ":=" in expression or "<-" in expression


def parse_selection(
    body: str, *, expression: str = "", offset: int = 0
) -> SelectionSpec:
    """Parse the inside of a ``{...}`` cell selection or ``with`` context.

    Args:
        body: Text between the braces.
        expression: Complete source for error reporting.
        offset: Offset of ``body`` inside ``expression``.

    Returns:
        SelectionSpec: Parsed table, axes and options.

    Raises:
        DpmXlSyntaxError: On an unknown selection component.
    """
    source = expression or body
    if not expression:
        offset = 0
    parser = _Parser(source, _scan(body, source=source, offset=offset, selection=True))
    return parser.parse_spec(offset, closing="")


class _Parser:
    def __init__(self, expression: str, tokens: list[Token]) -> None:
        self.expression = expression
        self.tokens = tokens
        self.index = 0
        self.depth = 0

    # Token helpers -----------------------------------------------------

    @property
    def current(self) -> Token:
        return self.tokens[self.index]

    def peek(self, distance: int = 1) -> Token:
        return self.tokens[min(self.index + distance, len(self.tokens) - 1)]

    def advance(self) -> Token:
        token = self.tokens[self.index]
        if token.kind != "eof":
            self.index += 1
        return token

    def at(self, text: str) -> bool:
        """Check for a punctuation, brace or operator token.

        Returns:
            bool: Whether the current token is ``text`` of such a kind.
        """
        token = self.tokens[self.index]
        return token.text == text and token.kind in _SYMBOL_KINDS

    def at_keyword(self, *words: str) -> bool:
        token = self.tokens[self.index]
        return token.kind == "keyword" and _keyword(token) in words

    def accept(self, text: str) -> Token | None:
        if self.at(text):
            return self.advance()
        return None

    def expect(self, text: str) -> Token:
        if self.at(text):
            return self.advance()
        raise self.error(f"expected {text!r}, found {_describe(self.current)}")

    def expect_keyword(self, word: str) -> Token:
        if self.at_keyword(word):
            return self.advance()
        raise self.error(f"expected {word!r}, found {_describe(self.current)}")

    def expect_kind(self, kind: str) -> Token:
        if self.current.kind == kind:
            return self.advance()
        wanted = _KIND_NAMES.get(kind, repr(kind))
        raise self.error(f"expected {wanted}, found {_describe(self.current)}")

    def expect_name(self) -> str:
        return _name(self.expect_kind("identifier"))

    def expect_end(self) -> None:
        if self.current.kind != "eof":
            raise self.error(
                f"expected end of expression, found {_describe(self.current)}"
            )

    def error(self, message: str, token: Token | None = None) -> DpmXlSyntaxError:
        token = token or self.current
        return DpmXlSyntaxError(message, self.expression, token.start, token.end)

    def nest(self) -> None:
        self.depth += 1
        if self.depth > MAX_NESTING:
            raise self.error("expression too deeply nested")

    def span(self, start: int, end_token: Token | None = None) -> tuple[int, int]:
        end = (end_token or self.tokens[max(self.index - 1, 0)]).end
        return (start, end)

    # Grammar -----------------------------------------------------------

    def parse_statement(self) -> Node:
        token = self.current
        if token.kind == "identifier" and self.peek().text == ":=":
            self.advance()
            self.advance()
            value = self.parse_assigned()
            return Assignment(_name(token), value, span=(token.start, value.span[1]))
        return self.parse_assigned()

    def parse_assigned(self) -> Node:
        """Parse a persistent assignment or an expression with its context.

        Returns:
            Node: The statement.
        """
        token = self.current
        if token.kind == "brace" and token.text == "{":
            closing = self._closing_brace(self.index)
            following = self.tokens[closing + 1]
            if following.kind == "operator" and following.text == "<-":
                self.advance()
                target = self.parse_brace(token)
                if isinstance(target, TableReported):
                    target = Parameter(target.table, span=target.span)
                elif not isinstance(target, Selection | Parameter):
                    raise self.error("assignment target must be a selection", token)
                self.advance()
                value = self.parse_root()
                return PersistentAssignment(
                    target, value, span=(token.start, value.span[1])
                )
        return self.parse_root()

    def _closing_brace(self, index: int) -> int:
        depth = 0
        for position in range(index, len(self.tokens)):
            token = self.tokens[position]
            if token.kind == "brace":
                depth += 1 if token.text == "{" else -1
                if depth == 0:
                    return position
        return len(self.tokens) - 2

    def parse_root(self) -> Node:
        if self.at_keyword("with"):
            start = self.advance().start
            opening = self.expect("{")
            context = self.parse_spec(opening.end)
            condition = None
            if self.at("[") and self.peek().text.casefold() == "where":
                self.advance()
                self.advance()
                condition = self.parse_expression()
                self.expect("]")
            self.expect(":")
            self.nest()
            body = self.parse_root()
            self.depth -= 1
            return With(context, body, condition, span=self.span(start))
        return self.parse_expression()

    def parse_expression(self) -> Node:
        # Every nested expression (in parentheses, if, calls, clause conditions
        # and sets) starts here; parse_postfix counts chained clauses. A
        # syntax error ends the parse, so the depth needs no unwinding.
        self.nest()
        node = self.parse_or()
        self.depth -= 1
        return node

    def parse_or(self) -> Node:
        left = self.parse_and()
        while self.at_keyword("or", "xor"):
            op = _keyword(self.advance())
            right = self.parse_and()
            left = Binary(op, left, right, span=(left.span[0], right.span[1]))
        return left

    def parse_and(self) -> Node:
        left = self.parse_not()
        while self.at_keyword("and"):
            self.advance()
            right = self.parse_not()
            left = Binary("and", left, right, span=(left.span[0], right.span[1]))
        return left

    def parse_not(self) -> Node:
        if self.at_keyword("not"):
            start = self.advance().start
            self.nest()
            operand = self.parse_not()
            self.depth -= 1
            return Unary("not", operand, span=(start, operand.span[1]))
        return self.parse_comparison()

    def parse_comparison(self) -> Node:
        left = self.parse_concat()
        token = self.current
        if token.kind == "operator" and token.text in _COMPARISON_OPERATORS:
            op = self.advance().text
            right = self.parse_concat()
            return Binary(
                "!=" if op == "<>" else op,
                left,
                right,
                span=(left.span[0], right.span[1]),
            )
        if self.at_keyword("in"):
            self.advance()
            values = self.parse_set_operand()
            return In(left, values, span=(left.span[0], values.span[1]))
        if self.at_keyword("not") and _is_keyword(self.peek(), "in"):
            start = self.advance().start
            self.advance()
            values = self.parse_set_operand()
            node = In(left, values, span=(left.span[0], values.span[1]))
            return Unary("not", node, span=(start, values.span[1]))
        return left

    def parse_set_operand(self) -> Node:
        if self.at("{") and self.starts_set(self.index + 1):
            return self.parse_set()
        return self.parse_concat()

    def starts_set(self, index: int) -> bool:
        """Whether a brace whose first inner token is at ``index`` is a set.

        Returns:
            bool: True for ``{}`` and braces that start with a literal, an
            item or a signed number; selections start with a reference or
            axis instead.
        """
        token = self.tokens[index]
        kind = token.kind
        if kind in _LITERAL_KINDS or (kind == "brace" and token.text == "}"):
            return True
        if kind == "operator":
            return token.text in {"+", "-"}
        if kind == "punctuation" and token.text == "(":
            following = self.tokens[index + 1]
            return following.kind == "number" or following.text in {"+", "-"}
        return False

    def parse_set(self) -> SetLiteral:
        opening = self.expect("{")
        items: list[Node] = []
        if not self.at("}"):
            while True:
                if self.at(",") or self.at("}"):
                    raise self.error("empty set member")
                items.append(self.parse_expression())
                if not self.accept(","):
                    break
        closing = self.expect("}")
        return SetLiteral(tuple(items), span=(opening.start, closing.end))

    def parse_concat(self) -> Node:
        left = self.parse_additive()
        while True:
            token = self.current
            if token.kind != "operator" or token.text != "&":
                return left
            self.advance()
            right = self.parse_additive()
            left = Binary("&", left, right, span=(left.span[0], right.span[1]))

    def parse_additive(self) -> Node:
        left = self.parse_multiplicative()
        while True:
            token = self.current
            if token.kind != "operator" or token.text not in {"+", "-"}:
                return left
            op = self.advance().text
            right = self.parse_multiplicative()
            left = Binary(op, left, right, span=(left.span[0], right.span[1]))

    def parse_multiplicative(self) -> Node:
        left = self.parse_unary()
        while True:
            token = self.current
            if token.kind != "operator" or token.text not in {"*", "/"}:
                return left
            op = self.advance().text
            right = self.parse_unary()
            left = Binary(op, left, right, span=(left.span[0], right.span[1]))

    def parse_unary(self) -> Node:
        token = self.current
        if token.kind == "operator" and token.text in {"+", "-"}:
            self.advance()
            self.nest()
            operand = self.parse_unary()
            self.depth -= 1
            op: Literal["+", "-"] = "-" if token.text == "-" else "+"
            return Unary(op, operand, span=(token.start, operand.span[1]))
        return self.parse_postfix()

    def parse_postfix(self) -> Node:
        node = self.parse_primary()
        clauses = 0
        while True:
            token = self.current
            if token.text == "%" and token.kind == "operator":
                self.advance()
                if not (isinstance(node, Literal_) and node.kind == "number"):
                    raise self.error("'%' must follow a number", token)
                assert isinstance(node.value, Decimal)
                node = Literal_(
                    node.value.scaleb(-2, DECIMAL_CONTEXT),
                    "number",
                    span=(node.span[0], token.end),
                )
                if self.at("%"):
                    raise self.error("'%' must follow a number, not a percentage")
                continue
            if token.text == "[" and token.kind == "punctuation":
                # Each clause wraps the node once more.
                self.nest()
                clauses += 1
                node = self.parse_clause(node)
                continue
            self.depth -= clauses
            return node

    def parse_clause(self, operand: Node) -> Node:
        self.expect("[")
        keyword = _keyword(self.expect_kind("keyword"))
        if keyword == "where":
            condition = self.parse_expression()
            end = self.expect("]")
            return Where(operand, condition, span=(operand.span[0], end.end))
        if keyword == "get":
            name = self.expect_name()
            end = self.expect("]")
            return Get(operand, name, span=(operand.span[0], end.end))
        if keyword == "sub":
            name = self.expect_name()
            self.expect("=")
            value = self.parse_additive()
            end = self.expect("]")
            return Sub(operand, name, value, span=(operand.span[0], end.end))
        pairs: list[tuple[str, str]] = []
        while True:
            old = self.expect_name()
            if not self.at_keyword("to"):
                raise self.error("expected 'to' in rename clause")
            self.advance()
            pairs.append((old, self.expect_name()))
            if not self.accept(","):
                break
        end = self.expect("]")
        return Rename(operand, tuple(pairs), span=(operand.span[0], end.end))

    def parse_primary(self) -> Node:
        token = self.current
        kind = token.kind
        if kind == "number":
            self.advance()
            try:
                value = _number(token.text)
            except InvalidOperation as error:
                raise self.error("number out of range", token) from error
            return Literal_(value, "number", span=(token.start, token.end))
        if kind == "string":
            self.advance()
            return Literal_(token.text[1:-1], "string", span=(token.start, token.end))
        if kind == "date":
            self.advance()
            return Literal_(_date(self, token), "date", span=(token.start, token.end))
        if kind == "item":
            self.advance()
            return Literal_(
                Item.parse(token.text[1:-1]), "item", span=(token.start, token.end)
            )
        if kind == "boolean":
            self.advance()
            return Literal_(
                token.text.casefold() == "true",
                "boolean",
                span=(token.start, token.end),
            )
        if kind == "null":
            self.advance()
            return Literal_(None, "null", span=(token.start, token.end))
        if kind == "keyword":
            if _keyword(token) == "if":
                return self.parse_if()
            raise self.error(f"unexpected keyword {token.text!r}")
        if kind == "brace" and token.text == "{":
            self.advance()
            return self.parse_brace(token)
        if kind == "punctuation" and token.text == "(":
            self.advance()
            inner = self.parse_expression()
            end = self.expect(")")
            # Keep the parenthesized span so explanations can show "( ... )".
            return _with_span(inner, (token.start, end.end))
        if kind in {"identifier", "function", "period"}:
            self.advance()
            if self.at("("):
                return self.parse_call(token)
            return Name(_name(token), span=(token.start, token.end))
        if kind == "eof":
            raise self.error("expression ends where an operand is expected")
        raise self.error(f"unexpected {_describe(token)} where an operand is expected")

    def parse_if(self) -> Node:
        start = self.expect_keyword("if").start
        condition = self.parse_expression()
        self.expect_keyword("then")
        then = self.parse_expression()
        otherwise = None
        if self.at_keyword("else"):
            self.advance()
            otherwise = self.parse_expression()
        end = self.expect_keyword("endif")
        return If(condition, then, otherwise, span=self.span(start, end))

    def parse_call(self, name: Token) -> Node:
        self.expect("(")
        args: list[Node] = []
        group_by: tuple[str, ...] | None = None
        if not self.at(")"):
            while True:
                args.append(self.parse_expression())
                if self.at_keyword("group by"):
                    self.advance()
                    keys = [self.expect_name()]
                    while self.accept(","):
                        keys.append(self.expect_name())
                    group_by = tuple(keys)
                    break
                if not self.accept(","):
                    break
        end = self.expect(")")
        function = _name(name).casefold()
        if function in FUNCTION_ALIASES:
            # max_aggr/min_aggr are the aggregate forms of max/min, which the
            # evaluators recognise by their single operand.
            if len(args) != 1:
                raise self.error(f"{function} takes one operand")
            function = FUNCTION_ALIASES[function]
        return Call(function, tuple(args), group_by, span=self.span(name.start, end))

    # Selections ----------------------------------------------------------

    def parse_brace(self, opening: Token) -> Node:
        first = self.current
        if self.starts_set(self.index):
            self.index -= 1
            return self.parse_set()
        if first.kind == "variable" and self.peek().text == "}":
            self.advance()
            closing = self.advance()
            span = (opening.start, closing.end)
            body = first.text
            if re.fullmatch(r"v_[A-Za-z0-9_.\-]+", body):
                return TableReported(body[2:], span=span)
            if re.fullmatch(r"v[A-Za-z][A-Za-z0-9_]*", body):
                return Parameter(body[1:], span=span)
            if body[1:2] == "`":
                return Parameter(_reference_name(body), span=span)
            raise self.error(f"unknown selection component {body!r}", first)
        if first.kind == "parameter":
            return self.parse_parameter(opening)
        spec = self.parse_spec(opening.end)
        return Selection(spec, span=(opening.start, self.tokens[self.index - 1].end))

    def parse_parameter(self, opening: Token) -> Node:
        name = _reference_name(self.advance().text)
        self.expect(",")
        kind = self.current
        if kind.kind != "type":
            raise self.error(
                f"expected a parameter type, found {_describe(kind)}", kind
            )
        self.advance()
        default: Literal_ | SetLiteral | _Missing = MISSING
        if self.accept(","):
            if not self.at_keyword("default"):
                raise self.error(f"expected 'default', found {_describe(self.current)}")
            self.advance()
            self.expect(":")
            default = self.parse_default()
        closing = self.expect("}")
        return TypedParameter(
            name,
            kind.text.casefold(),
            default,
            span=(opening.start, closing.end),
        )

    def parse_spec(self, body_start: int, closing: str = "}") -> SelectionSpec:
        """Parse selection components up to and including ``closing``.

        Args:
            body_start: Offset just after the opening brace.
            closing: ``"}"``, or ``""`` to read up to the end of the tokens.

        Returns:
            SelectionSpec: The selection.
        """
        fields: dict[str, Any] = {}
        if self._at_spec_end(closing):
            self._finish_spec(closing)
            return SelectionSpec()
        while True:
            token = self.current
            if token.text in {",", "}"} or token.kind == "eof":
                raise self.error("empty selection component")
            if token.kind == "keyword" and _keyword(token) in {"default", "interval"}:
                name = _keyword(self.advance())
                if name in fields:
                    raise self.error(f"duplicate {name} option", token)
                self.expect(":")
                if name == "interval":
                    value = self.current
                    if value.kind != "boolean":
                        raise self.error("interval must be true or false", token)
                    self.advance()
                    fields[name] = value.text.casefold() == "true"
                else:
                    fields[name] = self.parse_default()
            elif token.kind in _SOURCES:
                if (
                    "table" in fields
                    or "table_group" in fields
                    or "operation" in fields
                ):
                    raise self.error("duplicate table", token)
                self.advance()
                fields[_SOURCES[token.kind]] = _reference_name(token.text)
            elif token.kind == "axis" or (
                token.kind == "punctuation" and token.text == "("
            ):
                selector, axis = self.parse_axis()
                if axis in fields:
                    raise self.error(f"duplicate {axis} selector", token)
                fields[axis] = selector
            else:
                raise self.error(
                    f"unknown selection component {self._component(token)!r}", token
                )
            if self.accept(","):
                continue
            if self._at_spec_end(closing):
                self._finish_spec(closing)
                return SelectionSpec(**fields)
            raise self.error(
                f"unknown selection component {self._component(token)!r}", token
            )

    def _at_spec_end(self, closing: str) -> bool:
        if closing:
            return self.at(closing)
        return self.current.kind == "eof"

    def _finish_spec(self, closing: str) -> None:
        if closing:
            self.advance()

    def _component(self, token: Token) -> str:
        """Return the source of the selection component starting at ``token``.

        Returns:
            str: The text up to the next comma or brace.
        """
        match = re.match(r"[^,{}]*", self.expression[token.start :])
        return (match.group().strip() if match else "") or token.text

    def parse_axis(self) -> tuple[AxisSelector, str]:
        token = self.current
        if token.kind == "axis":
            self.advance()
            return _axis_part(token.text)
        opening = self.expect("(")
        parts: list[str | tuple[str, str]] = []
        axis: str | None = None
        while not self.at(")"):
            part = self.current
            if part.kind != "axis":
                if part.text in {",", ")"} and axis is None:
                    break
                raise self.error(
                    f"unknown selection component {self._component(part)!r}", part
                )
            self.advance()
            selector, part_axis = _axis_part(part.text)
            if axis is not None and part_axis != axis:
                raise self.error("axis list mixes axes", part)
            if selector.wildcard:
                raise self.error("wildcard inside an axis list", part)
            axis = part_axis
            parts.extend(selector.parts)
            if not self.accept(","):
                break
        self.expect(")")
        if axis is None:
            raise self.error("empty axis list", opening)
        return AxisSelector(parts=tuple(parts)), axis

    def parse_default(self) -> Literal_ | SetLiteral:
        token = self.current
        start = token.start
        if token.kind == "brace" and token.text == "{":
            return self.parse_set()
        if token.text == "(" and token.kind == "punctuation":
            # The grammar writes a negative integer literal as (-5).
            self.advance()
            inner = self.parse_default()
            closing = self.expect(")")
            return cast(Literal_ | SetLiteral, _with_span(inner, (start, closing.end)))
        sign = ""
        if token.kind == "operator" and token.text in {"+", "-"}:
            sign = "-" if token.text == "-" else ""
            self.advance()
            token = self.current
            if token.kind != "number":
                raise self.error(f"invalid default {self._component(token)!r}")
        span = (start, token.end)
        kind = token.kind
        if kind == "number":
            self.advance()
            try:
                return Literal_(_number(sign + token.text), "number", span=span)
            except InvalidOperation as error:
                raise DpmXlSyntaxError(
                    f"invalid default {self.expression[start : token.end]!r}",
                    self.expression,
                    start,
                    token.end,
                ) from error
        if kind == "null":
            self.advance()
            return Literal_(None, "null", span=span)
        if kind == "string":
            self.advance()
            return Literal_(token.text[1:-1], "string", span=span)
        if kind == "boolean":
            self.advance()
            return Literal_(token.text.casefold() == "true", "boolean", span=span)
        if kind == "item":
            self.advance()
            return Literal_(Item.parse(token.text[1:-1]), "item", span=span)
        if kind == "date":
            self.advance()
            try:
                return Literal_(_date_value(token.text[1:-1]), "date", span=span)
            except ValueError as error:
                raise self.error("invalid default date", token) from error
        raise self.error(f"invalid default {self._component(token)!r}", token)


_SYMBOL_KINDS = frozenset({"punctuation", "brace", "operator"})
_LITERAL_KINDS = frozenset({"number", "string", "date", "item", "boolean", "null"})


def _keyword(token: Token) -> str:
    """Return a keyword token's normalized text: lower case, single spaces.

    Returns:
        str: For example ``group by``.
    """
    text = token.text.casefold()
    return text if text.isalpha() else " ".join(text.split())


_SOURCES = {"table": "table", "table_group": "table_group", "operation": "operation"}


def _reference_name(text: str) -> str:
    """Return a selection reference's code without its prefix.

    The ``_`` after the prefix is cosmetic (``t_T1`` is ``tT1``), and an
    escaped code drops its backticks.

    Returns:
        str: The code, such as ``C_01.00`` for ``tC_01.00``.
    """
    code = text[1:]
    if code[:1] == "`":
        return code[1:-1]
    return code[1:] if code[:1] == "_" else code


def _is_keyword(token: Token, word: str) -> bool:
    return token.kind == "keyword" and _keyword(token) == word


def _name(token: Token) -> str:
    """Return a name without the backticks of an escaped identifier.

    Returns:
        str: The name.
    """
    text = token.text
    return text[1:-1] if text[:1] == "`" else text


def _date(parser: _Parser, token: Token) -> date:
    try:
        return _date_value(token.text[1:-1])
    except ValueError as error:
        raise parser.error(f"invalid date {token.text[1:-1]!r}", token) from error


def _date_value(text: str) -> date:
    """Read ``YYYY-MM-DD`` or ``YYYY-MM-DDThh:mm:ss``.

    Returns:
        date: A date, or a ``datetime`` when the text has a time part.

    Raises:
        ValueError: For any other text.
    """
    text = text.strip()
    if "T" in text:
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}", text):
            raise ValueError(text)
        return datetime.fromisoformat(text)
    return date.fromisoformat(text)


def _axis_part(text: str) -> tuple[AxisSelector, str]:
    axis = AXIS_PREFIXES[text[0]]
    value = text[1:]
    if value == "*":
        return AxisSelector(wildcard=True), axis
    if "-" in value:
        low, high = value.split("-", 1)
        return AxisSelector(parts=((low, high),)), axis
    return AxisSelector(parts=(value,)), axis


def _with_span(node: Node, span: tuple[int, int]) -> Node:
    # Frozen slotted dataclasses: rebuild with the wider span.
    values = {
        name: getattr(node, name)
        for name in node.__dataclass_fields__
        if name != "span"
    }
    return type(node)(**values, span=span)


def _matching(expression: str, start: int, opening: str, closing: str) -> int:
    depth = 0
    index = start
    quote: str | None = None
    while index < len(expression):
        char = expression[index]
        if quote:
            if char == quote:
                quote = None
        elif char in "\"'":
            quote = char
        elif char == opening:
            depth += 1
        elif char == closing:
            depth -= 1
            if depth == 0:
                return index
        index += 1
    raise DpmXlSyntaxError(
        f"unterminated {opening!r}: no matching {closing!r}", expression, start
    )


def _number(text: str) -> Decimal:
    """Read a number literal within the range of decimal arithmetic.

    Returns:
        Decimal: The value.

    Raises:
        InvalidOperation: For text that is not a number, or a number whose
            exponent arithmetic would overflow (``1e99999999999``).
    """
    value = Decimal(text)
    if value and not DECIMAL_CONTEXT.Emin <= value.adjusted() <= DECIMAL_CONTEXT.Emax:
        raise InvalidOperation(text)
    return value


__all__ = [
    "DpmXlSyntaxError",
    "Token",
    "parse",
    "parse_program",
    "parse_selection",
    "tokenize",
]
