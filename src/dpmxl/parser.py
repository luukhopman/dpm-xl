"""Tokenizer and recursive-descent parser for DPM-XL expressions.

[`tokenize`][dpmxl.parser.tokenize] splits an expression into typed
[`Token`][dpmxl.parser.Token] objects that suit syntax highlighting as well as parsing:
selections are split into their table, axis and option tokens rather than captured
whole. [`parse`][dpmxl.parser.parse] builds the expression tree of
[`dpmxl.ast`][dpmxl.ast] from those tokens.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Literal, NamedTuple, cast

from .ast import (
    AXIS_PREFIXES,
    MISSING,
    Analytic,
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
    PersistentAssignment,
    Program,
    Rename,
    Selection,
    SelectionSpec,
    SetLiteral,
    Sub,
    TypedParameter,
    Unary,
    Variable,
    Where,
    Window,
    WindowBound,
    With,
    _Missing,
)
from .grammar import (
    AGGREGATE_FUNCTIONS,
    ANALYTIC_FUNCTIONS,
    FUNCTION_ALIASES,
    FUNCTIONS,
    KEYWORDS,
    REFERENCE_PREFIXES,
    TIME_PERIODS,
    WINDOW_KEYWORDS,
)
from .values import DECIMAL_CONTEXT


class DpmXlSyntaxError(ValueError):
    """Raised when an expression does not match the DPM-XL grammar.

    Attributes:
        message: What was expected or found, in plain words.
        expression: The complete source expression.
        position: Zero-based offset where the offending text starts.
        end: Offset just past the offending text.

    Examples:
        >>> try:
        ...     parse("{tA} >=")
        ... except DpmXlSyntaxError as error:
        ...     print(error.message, error.position)
        expression ends where an operand is expected 7
    """

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

        Examples:
            >>> try:
            ...     parse("{tA, r0010} +* 1")
            ... except DpmXlSyntaxError as error:
            ...     print(error.pointer())
            {tA, r0010} +* 1
                         ^
        """
        return _pointer(self.expression, self.position, self.end)


def _pointer(expression: str, position: int, end: int) -> str:
    """Render the source line of ``position`` and mark ``[position, end)``.

    Returns:
        str: The line, and below it ``^`` at the start and ``~`` under the
        rest of the range on that line.
    """
    start = expression.rfind("\n", 0, position) + 1
    newline = expression.find("\n", position)
    line_end = newline if newline >= 0 else len(expression)
    line = expression[start:line_end]
    width = max(min(end, line_end) - position, 1)
    return f"{line}\n{' ' * (position - start)}^{'~' * (width - 1)}"


class Token(NamedTuple):
    """One lexical token: its kind, source text and half-open offsets.

    ``text`` is exactly ``expression[start:end]``, quotes, brackets and
    backticks included. ``kind`` is one of [`TOKEN_KINDS`][dpmxl.grammar.TOKEN_KINDS]:

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

    Attributes:
        kind: The token kind, as above.
        text: The exact source text.
        start: Offset of the first character.
        end: Offset just past the last character.
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
# An item: the grammar's ITEM_SIGNATURE (namespace:code), or a property code
# (bare, as in the legacy [ei86], or escaped), between brackets with optional
# spaces.
_ITEM = (
    r"\[\s*(?:[A-Za-z](?:[A-Za-z0-9_\-]*:[A-Za-z0-9._\-]*[A-Za-z0-9])+"
    r"|[A-Za-z](?:[A-Za-z0-9_.]*[A-Za-z0-9])?|`[A-Za-z0-9_.+]+`)\s*\]"
)
_ITEM_TEXT = re.compile(_ITEM)
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
  | (?P<arrow><-)
  | (?P<operator>:=|<>|!=|<=|>=|[=<>+\-*/%&])
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
  | (?P<operator>[+\-%])
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
    expression back. See [`Token`][dpmxl.parser.Token] for the kinds.

    Returns:
        list[Token]: Tokens ending with an ``eof`` token.

    Raises:
        DpmXlSyntaxError: On an unterminated literal, brace or item, or an
            unknown character.

    Examples:
        >>> [(token.kind, token.text) for token in tokenize("{tT, r0010} > 0")]
        ... # doctest: +NORMALIZE_WHITESPACE
        [('brace', '{'), ('table', 'tT'), ('punctuation', ','), ('axis', 'r0010'),
         ('brace', '}'), ('operator', '>'), ('number', '0'), ('eof', '')]
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
            group = match.lastgroup or ""
            value = match.group(group)
            end = match.end()
            start = end - len(value)
            if group in _DIRECT_KINDS:
                kind = group
            elif group == "arrow":
                kind = "operator"
                if modes and modes[-1] == "c":
                    # Clauses have no assignment: {x} [where a<-1] compares.
                    append(
                        new(
                            Token, ("operator", "<", start + offset, start + 1 + offset)
                        )
                    )
                    value, start = "-", start + 1
            elif group == "item":
                # Lexed loosely, then checked once: cheaper than a strict
                # pattern in the scanner.
                if _ITEM_TEXT.fullmatch(value) is None:
                    error = DpmXlSyntaxError(
                        f"invalid item {value!r}", source, start + offset, end + offset
                    )
                    raise error
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
    if char == "[" and "]" in text[index:]:
        end = text.index("]", index) + 1
        return DpmXlSyntaxError(
            f"invalid item {text[index:end]!r}", source, position, end + offset
        )
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
    [`parse_program`][dpmxl.parser.parse_program].

    Returns:
        Node: The expression tree; every node keeps its source ``span``.

    Raises:
        DpmXlSyntaxError: If the text is not a valid expression.

    Examples:
        >>> node = parse("{tT, r0010} > 0")
        >>> type(node).__name__, node.op, node.span
        ('Binary', '>', (0, 15))
        >>> node.left.spec.text()
        '{tT, r0010}'
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
    errors = _rule_errors(program, expression)
    if errors:
        raise errors[0]
    return program.statements[0]


def _rule_errors(program: Program, expression: str) -> list[DpmXlSyntaxError]:
    """Return why a parsed program is not a single rule expression.

    The messages speak to someone typing a rule; parse_program is the entry
    point for scripts with several statements or assignments.

    Returns:
        list[DpmXlSyntaxError]: The problems, the one ``parse`` raises
        first; empty for one plain expression.
    """
    errors: list[DpmXlSyntaxError] = []
    first = program.statements[0]
    if len(program.statements) > 1:
        second = program.statements[1]
        errors.append(
            DpmXlSyntaxError(
                "a rule is one expression; ';' separates the statements of a "
                "script (parse_program)",
                expression,
                second.span[0],
                second.span[1],
            )
        )
    if isinstance(first, PersistentAssignment):
        arrow = expression.find("<-", first.target.span[1])
        errors.append(
            DpmXlSyntaxError(
                "'<-' assigns a value; to compare with a negative number, write '< -'",
                expression,
                arrow,
                arrow + 2,
            )
        )
    elif isinstance(first, Assignment):
        errors.append(
            DpmXlSyntaxError(
                "':=' names a value for later statements of a script "
                "(parse_program); a rule is one expression",
                expression,
                *first.span,
            )
        )
    return errors


def parse_program(source: str) -> Program:
    """Parse statements separated by ``;``, with assignments.

    A statement is an expression (with an optional ``with`` context), a
    temporary assignment ``name := expression`` or a persistent assignment
    ``{target} <- expression``. A trailing ``;`` is allowed.

    Returns:
        Program: The statements, also when there is only one.

    Raises:
        DpmXlSyntaxError: If the text is not a valid program.

    Examples:
        >>> program = parse_program("x := {tT, r0010}; x > 0")
        >>> [type(statement).__name__ for statement in program.statements]
        ['Assignment', 'Binary']
        >>> program.statements[0].name
        'x'
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


def _parse_recovering(
    source: str, *, program: bool = False
) -> tuple[Program | None, list[DpmXlSyntaxError]]:
    """Parse as far as possible, collecting every syntax error.

    Unlike [`parse_program`][dpmxl.parser.parse_program] the parse carries on
    after an error: a missing token is taken as left out, unreadable text up
    to where the enclosing construct can continue is skipped, and an
    unreadable selection component is dropped. An error that starts inside
    an earlier one is not reported. Lexical errors (an unterminated string
    or brace, an unknown character) and too deep nesting end the parse.

    Args:
        source: The expression or program.
        program: Accept a script (``;``, ``:=`` and ``<-``); otherwise the
            text must be one rule expression, as for
            [`parse`][dpmxl.parser.parse].

    Returns:
        tuple[Program | None, list[DpmXlSyntaxError]]: The statements read,
        with placeholders for unreadable text, or ``None`` when the parse
        ended early; and the errors in source order.
    """
    if not source or not source.strip():
        return None, [DpmXlSyntaxError("empty expression", source or "", 0)]
    try:
        tokens = _scan(source)
    except DpmXlSyntaxError as error:
        return None, [error]
    parser = _Parser(source, tokens, recover=True)
    statements: list[Node] = []
    try:
        while True:
            statements.append(parser.parse_statement())
            if parser.accept(";"):
                if parser.current.kind == "eof":
                    break
                continue
            if parser.current.kind == "eof":
                break
            parser.report(
                parser.error(
                    f"expected end of expression, found {_describe(parser.current)}"
                )
            )
            separator = parser.find(
                lambda token: token.kind == "punctuation" and token.text == ";"
            )
            if separator is None:
                break
            parser.index = separator + 1
            if parser.current.kind == "eof":
                break
    except (_TooDeep, RecursionError) as error:
        if isinstance(error, RecursionError):  # pragma: no cover - MAX_NESTING
            error = DpmXlSyntaxError("expression too deeply nested", source, 0)
        parser.report(error)
        return None, sorted(parser.errors, key=lambda found: found.position)
    tree = Program(
        tuple(statements), span=(statements[0].span[0], statements[-1].span[1])
    )
    errors = list(parser.errors)
    if not program:
        errors.extend(_rule_errors(tree, source))
    return tree, sorted(errors, key=lambda found: found.position)


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

    Examples:
        >>> spec = parse_selection("tC_01.00, r0010-0050, c*")
        >>> spec.table, spec.rows.parts, spec.columns.wildcard
        ('C_01.00', (('0010', '0050'),), True)
    """
    source = expression or body
    if not expression:
        offset = 0
    parser = _Parser(source, _scan(body, source=source, offset=offset, selection=True))
    return parser.parse_spec(offset, closing="")


class _TooDeep(DpmXlSyntaxError):
    """Nesting beyond MAX_NESTING; a recovering parse stops on it."""


@dataclass(frozen=True, slots=True)
class _Invalid(Node):
    """Text a recovering parse could not read; it has no children."""


class _Parser:
    def __init__(
        self, expression: str, tokens: list[Token], *, recover: bool = False
    ) -> None:
        self.expression = expression
        self.tokens = tokens
        self.index = 0
        self.depth = 0
        # A recovering parse records errors and carries on; see
        # _parse_recovering.
        self.recover = recover
        self.errors: list[DpmXlSyntaxError] = []

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
        error = self.error(
            f"expected {text!r}, found {_describe(self.tokens[self.index])}"
        )
        return self.missing(
            error, lambda token: token.text == text and token.kind in _SYMBOL_KINDS
        )

    def expect_keyword(self, word: str, message: str | None = None) -> Token:
        if self.at_keyword(word):
            return self.advance()
        error = self.error(
            message or f"expected {word!r}, found {_describe(self.tokens[self.index])}"
        )
        return self.missing(error, lambda token: _is_keyword(token, word))

    def expect_kind(self, kind: str) -> Token:
        if self.tokens[self.index].kind == kind:
            return self.advance()
        wanted = _KIND_NAMES.get(kind, repr(kind))
        error = self.error(
            f"expected {wanted}, found {_describe(self.tokens[self.index])}"
        )
        return self.missing(error, None)

    # Recovery ----------------------------------------------------------

    def fail(self, error: DpmXlSyntaxError) -> None:
        """Raise ``error``, or record it and carry on when recovering.

        Raises:
            DpmXlSyntaxError: Unless the parse is recovering.
        """
        if not self.recover:
            raise error
        self.report(error)

    def report(self, error: DpmXlSyntaxError) -> None:
        """Record an error, unless it follows from one already recorded.

        The parse reads left to right, so an error that starts before the
        last one, or inside an earlier one's text, results from an earlier
        error; only the first is kept.
        """
        if self.errors and error.position < self.errors[-1].position:
            return
        for earlier in self.errors:
            if (
                earlier.position
                <= error.position
                < max(earlier.end, earlier.position + 1)
            ):
                return
        self.errors.append(error)

    def missing(
        self, error: DpmXlSyntaxError, wanted: Callable[[Token], bool] | None
    ) -> Token:
        """Recover from a token that is not the one the grammar needs.

        When the wanted token follows later in the same group, the text
        before it is skipped; otherwise it is taken as left out.

        Returns:
            Token: The wanted token, or an empty one where it is missing.

        Raises:
            DpmXlSyntaxError: Unless the parse is recovering.
        """
        self.fail(error)
        found = self.find(wanted) if wanted is not None else None
        if found is not None:
            self.index = found
            return self.advance()
        start = self.tokens[self.index].start
        return Token("eof", "", start, start)

    def find(self, wanted: Callable[[Token], bool]) -> int | None:
        """Return the index of the next wanted token in the current group.

        The search skips nested brackets and stops at the group's end, a
        ``;`` and the branch keywords of an enclosing ``if``.

        Returns:
            int | None: The token's index, or ``None`` when it is not there.
        """
        depth = 0
        for position in range(self.index, len(self.tokens)):
            token = self.tokens[position]
            if depth == 0 and wanted(token):
                return position
            if token.kind == "eof":
                return None
            if _opens(token):
                depth += 1
            elif _closes(token):
                if depth == 0:
                    return None
                depth -= 1
            elif depth == 0 and (
                (token.kind == "punctuation" and token.text == ";")
                or (token.kind == "keyword" and _keyword(token) in _BRANCH_WORDS)
            ):
                return None
        return None

    def skip_to_follower(self, start: int) -> None:
        """Move past unreadable text to a token that can follow an operand.

        Brackets opened at or after ``start`` are skipped whole, so the parse
        resumes in the group the failed operand belongs to.
        """
        depth = 0
        position = start
        while True:
            token = self.tokens[position]
            if token.kind == "eof":
                break
            at_or_after = position >= self.index
            if at_or_after and depth == 0 and _follows_operand(token):
                break
            if _opens(token):
                depth += 1
            elif _closes(token) and depth > 0:
                depth -= 1
            position += 1
        self.index = max(position, self.index)

    def invalid(self, start: int) -> _Invalid:
        """Return a placeholder for the tokens from ``start`` to here.

        Returns:
            _Invalid: A node spanning the skipped text (empty when none was).
        """
        first = self.tokens[start].start
        end = self.tokens[self.index - 1].end if self.index > start else first
        return _Invalid(span=(first, max(first, end)))

    def expect_name(self) -> str:
        return _name(self.expect_kind("identifier"))

    def expect_end(self) -> None:
        token = self.tokens[self.index]
        if token.kind != "eof":
            raise self.error(f"expected end of expression, found {_describe(token)}")

    def error(self, message: str, token: Token | None = None) -> DpmXlSyntaxError:
        token = token or self.tokens[self.index]
        return DpmXlSyntaxError(message, self.expression, token.start, token.end)

    def nest(self) -> None:
        self.depth += 1
        if self.depth > MAX_NESTING:
            token = self.tokens[self.index]
            raise _TooDeep(
                "expression too deeply nested", self.expression, token.start, token.end
            )

    def span(self, start: int, end_token: Token | None = None) -> tuple[int, int]:
        end = (end_token or self.tokens[max(self.index - 1, 0)]).end
        return (start, end)

    # Grammar -----------------------------------------------------------

    def parse_statement(self) -> Node:
        token = self.tokens[self.index]
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
        token = self.tokens[self.index]
        if token.kind == "brace" and token.text == "{":
            closing = self._closing_brace(self.index)
            following = self.tokens[closing + 1]
            if following.kind == "operator" and following.text == "<-":
                self.advance()
                target = self.parse_brace(token)
                if not isinstance(target, Selection | Variable):
                    self.fail(
                        self.error("assignment target must be a selection", token)
                    )
                self.advance()
                value = self.parse_root()
                return PersistentAssignment(
                    cast(Selection | Variable, target),
                    value,
                    span=(token.start, value.span[1]),
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
        # syntax error ends a strict parse, so the depth needs no unwinding.
        if not self.recover:
            self.nest()
            node = self.parse_or()
            self.depth -= 1
            return node
        start, depth = self.index, self.depth
        try:
            self.nest()
            node = self.parse_or()
            self.depth -= 1
            return node
        except _TooDeep:
            raise
        except DpmXlSyntaxError as error:
            # An error without a recovery of its own: skip to where the
            # enclosing construct can carry on.
            self.report(error)
            self.depth = depth
            self.skip_to_follower(start)
            return self.invalid(start)

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
        token = self.tokens[self.index]
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
        # As in the grammar, the right of in is a whole operand: {1, 2} - x.
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
                    self.fail(self.error("empty set member"))
                    if self.accept(","):
                        continue
                    break
                items.append(self.parse_expression())
                if not self.accept(","):
                    break
        closing = self.expect("}")
        return SetLiteral(tuple(items), span=(opening.start, closing.end))

    def parse_concat(self) -> Node:
        left = self.parse_additive()
        while True:
            token = self.tokens[self.index]
            if token.kind != "operator" or token.text != "&":
                return left
            self.advance()
            right = self.parse_additive()
            left = Binary("&", left, right, span=(left.span[0], right.span[1]))

    def parse_additive(self) -> Node:
        left = self.parse_multiplicative()
        while True:
            token = self.tokens[self.index]
            if token.kind != "operator" or token.text not in {"+", "-"}:
                return left
            op = self.advance().text
            right = self.parse_multiplicative()
            left = Binary(op, left, right, span=(left.span[0], right.span[1]))

    def parse_multiplicative(self) -> Node:
        left = self.parse_unary()
        while True:
            token = self.tokens[self.index]
            if token.kind != "operator" or token.text not in {"*", "/"}:
                return left
            op = self.advance().text
            right = self.parse_unary()
            left = Binary(op, left, right, span=(left.span[0], right.span[1]))

    def parse_unary(self) -> Node:
        token = self.tokens[self.index]
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
            token = self.tokens[self.index]
            if token.text == "%" and token.kind == "operator":
                self.advance()
                if not (isinstance(node, Literal_) and node.kind == "number"):
                    self.fail(self.error("'%' must follow a number", token))
                    continue
                assert isinstance(node.value, Decimal)
                node = Literal_(
                    node.value.scaleb(-2, DECIMAL_CONTEXT),
                    "number",
                    span=(node.span[0], token.end),
                )
                if self.at("%"):
                    self.fail(self.error("'%' must follow a number, not a percentage"))
                    self.advance()
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
            self.expect_keyword("to", "expected 'to' in rename clause")
            pairs.append((old, self.expect_name()))
            if not self.accept(","):
                break
        end = self.expect("]")
        return Rename(operand, tuple(pairs), span=(operand.span[0], end.end))

    def parse_primary(self) -> Node:
        token = self.tokens[self.index]
        kind = token.kind
        if kind == "number":
            self.advance()
            try:
                value = _number(token.text)
            except InvalidOperation as error:
                if not self.recover:
                    raise self.error("number out of range", token) from error
                self.report(self.error("number out of range", token))
                return _Invalid(span=(token.start, token.end))
            return Literal_(value, "number", span=(token.start, token.end))
        if kind == "string":
            self.advance()
            return Literal_(token.text[1:-1], "string", span=(token.start, token.end))
        if kind == "date":
            self.advance()
            try:
                value = _date(self, token)
            except DpmXlSyntaxError as error:
                if not self.recover:
                    raise
                self.report(error)
                return _Invalid(span=(token.start, token.end))
            return Literal_(value, "date", span=(token.start, token.end))
        if kind == "item":
            self.advance()
            return Literal_(_item(token.text), "item", span=(token.start, token.end))
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
            return self.no_operand(self.error(f"unexpected keyword {token.text!r}"))
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
            return self.no_operand(
                self.error("expression ends where an operand is expected")
            )
        return self.no_operand(
            self.error(f"unexpected {_describe(token)} where an operand is expected")
        )

    def no_operand(self, error: DpmXlSyntaxError) -> Node:
        """Recover where an operand is missing.

        Text that can neither start nor follow an operand, such as the second
        ``=`` of ``a = = 1``, is skipped; the next operand is read in place of
        the missing one, or a placeholder stands in for it.

        Returns:
            Node: The operand read after the skipped text, or a placeholder.

        Raises:
            DpmXlSyntaxError: Unless the parse is recovering.
        """
        self.fail(error)
        start = self.tokens[self.index].start
        while not _follows_operand(self.current) and not _starts_operand(self.current):
            self.advance()
        if _starts_operand(self.current):
            return self.parse_unary()
        return _Invalid(span=(start, start))

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
        function = _name(name).casefold()
        if not self.at(")"):
            while True:
                args.append(self.parse_expression())
                if self.at_keyword("over") and len(args) == 1:
                    return self.parse_analytic(name, function, args[0])
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
        if function in ANALYTIC_FUNCTIONS:
            self.fail(self.error(f"{function} needs an over clause", name))
        if function in FUNCTION_ALIASES:
            # max_aggr/min_aggr are the aggregate forms of max/min, which the
            # evaluators recognise by their single operand.
            if len(args) != 1:
                self.fail(self.error(f"{function} takes one operand", name))
            function = FUNCTION_ALIASES[function]
        return Call(function, tuple(args), group_by, span=self.span(name.start, end))

    def parse_analytic(self, name: Token, function: str, operand: Node) -> Node:
        over = self.advance()
        if function not in _ANALYTIC_NAMES:
            self.fail(self.error(f"{function} takes no over clause", over))
        self.expect("(")
        partition: list[str] = []
        order: list[tuple[str, bool]] = []
        window = None
        if self.at_keyword("partition by"):
            self.advance()
            partition.append(self.expect_name())
            while self.accept(","):
                partition.append(self.expect_name())
        if self.at_keyword("order by"):
            self.advance()
            while True:
                key = self.expect_name()
                descending = False
                if self.at_keyword("asc", "desc"):
                    descending = _keyword(self.advance()) == "desc"
                order.append((key, descending))
                if not self.accept(","):
                    break
        if self.at_keyword("data points", "range"):
            unit = cast(Literal["data points", "range"], _keyword(self.advance()))
            self.expect_keyword("between")
            start = self.parse_bound()
            self.expect_keyword("and")
            window = Window(unit, start, self.parse_bound())
        self.expect(")")
        end = self.expect(")")
        if function == "rank" and not order:
            self.fail(self.error("rank needs an order by clause", over))
        return Analytic(
            FUNCTION_ALIASES.get(function, function),
            operand,
            tuple(partition),
            tuple(order),
            window,
            span=self.span(name.start, end),
        )

    def parse_bound(self) -> WindowBound:
        if self.at_keyword("unbounded"):
            self.advance()
            direction = self.tokens[self.index]
            if not self.at_keyword("preceding", "following"):
                raise self.error(
                    f"expected 'preceding' or 'following', found {_describe(direction)}"
                )
            self.advance()
            return WindowBound(
                "unbounded preceding"
                if _keyword(direction) == "preceding"
                else "unbounded following"
            )
        if self.at_keyword("current data point"):
            self.advance()
            return WindowBound("current data point")
        count = self.expect_kind("number")
        if not count.text.isdigit():
            self.fail(self.error("a window offset is a whole number", count))
        period = None
        if self.tokens[self.index].kind in {"period", "identifier"} and (
            self.tokens[self.index].text in TIME_PERIODS
        ):
            period = self.advance().text
        direction = self.tokens[self.index]
        if not self.at_keyword("preceding", "following"):
            raise self.error(
                f"expected 'preceding' or 'following', found {_describe(direction)}"
            )
        self.advance()
        return WindowBound(
            "preceding" if _keyword(direction) == "preceding" else "following",
            # A recovering parse may have read a fraction or nothing here.
            int(count.text) if count.text.isdigit() else 0,
            period,
        )

    # Selections ----------------------------------------------------------

    def parse_brace(self, opening: Token) -> Node:
        first = self.tokens[self.index]
        if self.starts_set(self.index):
            self.index -= 1
            return self.parse_set()
        if first.kind == "variable" and self.peek().text == "}":
            self.advance()
            closing = self.advance()
            span = (opening.start, closing.end)
            body = first.text
            if re.fullmatch(r"v_[A-Za-z0-9_.\-]+", body):
                return Variable(body[2:], span=span)
            if re.fullmatch(r"v[A-Za-z](?:[A-Za-z0-9_.]*[A-Za-z0-9])?", body):
                return Variable(body[1:], span=span)
            if body[1:2] == "`":
                return Variable(_reference_name(body), span=span)
            self.fail(self.error(f"unknown selection component {body!r}", first))
            return _Invalid(span=span)
        if first.kind == "parameter":
            return self.parse_parameter(opening)
        spec = self.parse_spec(opening.end)
        return Selection(spec, span=(opening.start, self.tokens[self.index - 1].end))

    def parse_parameter(self, opening: Token) -> Node:
        name = _reference_name(self.advance().text)
        self.expect(",")
        kind = self.tokens[self.index]
        if kind.kind != "type":
            raise self.error(
                f"expected a parameter type, found {_describe(kind)}", kind
            )
        self.advance()
        default: Literal_ | SetLiteral | _Missing = MISSING
        if self.accept(","):
            if not self.at_keyword("default"):
                raise self.error(
                    f"expected 'default', found {_describe(self.tokens[self.index])}"
                )
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
            SelectionSpec: The selection; when recovering, without the
            components that could not be read.

        Raises:
            DpmXlSyntaxError: On a malformed component, unless recovering.
            _TooDeep: When a default nests too deeply.
        """
        fields: dict[str, Any] = {}
        if self._at_spec_end(closing):
            self._finish_spec(closing)
            return SelectionSpec()
        while True:
            token = self.tokens[self.index]
            try:
                self._spec_component(token, fields)
                if self.accept(","):
                    continue
                if self._at_spec_end(closing):
                    self._finish_spec(closing)
                    return SelectionSpec(**fields)
                raise self._unknown_component(token)
            except _TooDeep:
                raise
            except DpmXlSyntaxError as error:
                if not self.recover:
                    raise
                # Skip the rest of the component; the others still count.
                self.report(error)
                self._skip_component()
                if self.accept(","):
                    continue
                if closing and self.at(closing):
                    self.advance()
                return SelectionSpec(**fields)

    def _spec_component(self, token: Token, fields: dict[str, Any]) -> None:
        """Parse one selection component into ``fields``.

        Raises:
            DpmXlSyntaxError: On an empty, unknown or malformed component.
        """
        if token.text in {",", "}"} or token.kind == "eof":
            raise self.error("empty selection component")
        if token.kind == "keyword" and _keyword(token) in {"default", "interval"}:
            name = _keyword(self.advance())
            duplicate = name in fields
            if duplicate:
                self.fail(self.error(f"duplicate {name} option", token))
            self.expect(":")
            if name == "interval":
                value = self.tokens[self.index]
                if value.kind != "boolean":
                    raise self.error("interval must be true or false", token)
                self.advance()
                if not duplicate:
                    fields[name] = value.text.casefold() == "true"
            else:
                default = self.parse_default()
                if not duplicate:
                    fields[name] = default
        elif token.kind in _SOURCES:
            if "source_span" in fields:
                self.fail(self.error("duplicate table", token))
                self.advance()
                return
            self.advance()
            fields[_SOURCES[token.kind]] = _reference_name(token.text)
            fields["source_span"] = (token.start, token.end)
        elif token.kind == "axis" or (
            token.kind == "punctuation" and token.text == "("
        ):
            selector, axis = self.parse_axis()
            if axis in fields:
                self.fail(self.error(f"duplicate {axis} selector", token))
                return
            fields[axis] = selector
        else:
            raise self._unknown_component(token)

    def _skip_component(self) -> None:
        """Move to the ``,`` or ``}`` that ends the current selection component."""
        depth = 0
        while True:
            token = self.tokens[self.index]
            if token.kind == "eof":
                return
            if depth == 0 and (
                (token.kind == "punctuation" and token.text == ",")
                or (token.kind == "brace" and token.text == "}")
            ):
                return
            if _opens(token):
                depth += 1
            elif _closes(token):
                depth -= 1
            self.advance()

    def _at_spec_end(self, closing: str) -> bool:
        if closing:
            return self.at(closing)
        return self.tokens[self.index].kind == "eof"

    def _finish_spec(self, closing: str) -> None:
        if closing:
            self.advance()

    def _unknown_component(self, token: Token) -> DpmXlSyntaxError:
        """Describe the unreadable selection component starting at ``token``.

        Returns:
            DpmXlSyntaxError: An error spanning the whole component.
        """
        component = self._component(token)
        return DpmXlSyntaxError(
            f"unknown selection component {component!r}",
            self.expression,
            token.start,
            token.start + len(component),
        )

    def _component(self, token: Token) -> str:
        """Return the source of the selection component starting at ``token``.

        Returns:
            str: The text up to the next comma or brace.
        """
        match = re.match(r"[^,{}]*", self.expression[token.start :])
        return (match.group().strip() if match else "") or token.text

    def parse_axis(self) -> tuple[AxisSelector, str]:
        token = self.tokens[self.index]
        if token.kind == "axis":
            self.advance()
            return _axis_part(token)
        opening = self.expect("(")
        if self.at(")"):
            raise self.error("empty axis list", opening)
        parts: list[str | tuple[str, str]] = []
        spans: list[tuple[int, int]] = []
        axis: str | None = None
        while True:
            part = self.tokens[self.index]
            if part.kind != "axis":
                if part.text in {",", ")"}:
                    raise self.error("empty axis list member", part)
                raise self._unknown_component(part)
            self.advance()
            selector, part_axis = _axis_part(part)
            if axis is not None and part_axis != axis:
                raise self.error("axis list mixes axes", part)
            if selector.wildcard:
                raise self.error("wildcard inside an axis list", part)
            axis = part_axis
            parts.extend(selector.parts)
            spans.extend(selector.spans)
            if not self.accept(","):
                break
        closing = self.expect(")")
        return (
            AxisSelector(
                parts=tuple(parts),
                span=(opening.start, closing.end),
                spans=tuple(spans),
            ),
            axis,
        )

    def parse_default(self) -> Literal_ | SetLiteral:
        token = self.tokens[self.index]
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
            token = self.tokens[self.index]
            if token.kind != "number":
                raise self.error(f"invalid default {self._component(token)!r}")
        span = (start, token.end)
        kind = token.kind
        if kind == "number":
            self.advance()
            try:
                value = _number(sign + token.text)
            except InvalidOperation as error:
                raise DpmXlSyntaxError(
                    f"invalid default {self.expression[start : token.end]!r}",
                    self.expression,
                    start,
                    token.end,
                ) from error
            percent = self.tokens[self.index]
            if percent.kind == "operator" and percent.text == "%":
                self.advance()
                value = value.scaleb(-2, DECIMAL_CONTEXT)
                span = (start, percent.end)
            return Literal_(value, "number", span=span)
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
            return Literal_(_item(token.text), "item", span=span)
        if kind == "date":
            self.advance()
            try:
                return Literal_(_date_value(token.text[1:-1]), "date", span=span)
            except ValueError as error:
                raise self.error("invalid default date", token) from error
        raise self.error(f"invalid default {self._component(token)!r}", token)


_SYMBOL_KINDS = frozenset({"punctuation", "brace", "operator"})
# Keywords that end an if branch; a recovering search does not pass them.
_BRANCH_WORDS = frozenset({"then", "else", "endif"})
# Keywords that may follow an operand, where a recovering parse resumes.
_FOLLOW_WORDS = _BRANCH_WORDS | {"and", "or", "xor", "in", "group by", "over", "to"}
_FOLLOW_SYMBOLS = frozenset({")", "]", "}", ",", ";", ":"})


def _opens(token: Token) -> bool:
    return (token.kind == "punctuation" and token.text in {"(", "["}) or (
        token.kind == "brace" and token.text == "{"
    )


def _closes(token: Token) -> bool:
    return (token.kind == "punctuation" and token.text in {")", "]"}) or (
        token.kind == "brace" and token.text == "}"
    )


def _follows_operand(token: Token) -> bool:
    """Whether a token can come right after an operand, ending it.

    Returns:
        bool: True for the end, closing brackets, separators and keywords
        such as ``then`` and ``and``.
    """
    if token.kind == "eof":
        return True
    if token.kind in {"punctuation", "brace"}:
        return token.text in _FOLLOW_SYMBOLS
    return token.kind == "keyword" and _keyword(token) in _FOLLOW_WORDS


def _starts_operand(token: Token) -> bool:
    """Whether a token can start an operand below ``not``.

    Returns:
        bool: True for literals, names, calls, braces, ``(``, signs and ``if``.
    """
    kind = token.kind
    if kind in _LITERAL_KINDS or kind in {"identifier", "function", "period"}:
        return True
    if kind == "brace":
        return token.text == "{"
    if kind == "punctuation":
        return token.text == "("
    if kind == "operator":
        return token.text in {"+", "-"}
    return kind == "keyword" and _keyword(token) == "if"


_ANALYTIC_NAMES = AGGREGATE_FUNCTIONS | ANALYTIC_FUNCTIONS | {"max", "min"}
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


def _item(text: str) -> Item:
    """Read an item token, dropping the backticks of an escaped code.

    Returns:
        Item: The item.
    """
    inner = text[1:-1].strip()
    return Item.parse(inner[1:-1] if inner[:1] == "`" else inner)


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


def _axis_part(token: Token) -> tuple[AxisSelector, str]:
    text = token.text
    axis = AXIS_PREFIXES[text[0]]
    value = text[1:]
    span = (token.start, token.end)
    if value == "*":
        return AxisSelector(wildcard=True, span=span), axis
    part: str | tuple[str, str] = value
    if "-" in value:
        low, high = value.split("-", 1)
        letter = text[0]
        # A range may repeat its axis letter (see AxisSelector).
        if high[:1] == letter and low[:1] != letter:
            high = high[1:]
        part = (low, high)
    return AxisSelector(parts=(part,), span=span, spans=(span,)), axis


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
