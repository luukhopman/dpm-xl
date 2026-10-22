"""Tokenizer and recursive-descent parser for DPM-XL 1.0 expressions.

The grammar covers the constructs used by EBA validation rules and similar
checks: ``with`` contexts, cell selections with ranges, lists and
wildcards, ``default``/``interval`` options, arithmetic, comparisons, ``in``
sets, three-valued boolean logic, ``if``/``then``/``else``/``endif``,
function calls with ``group by``, and the ``where``, ``get``, ``sub`` and
``rename`` clauses.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any, Literal, cast

from .ast import (
    AXIS_PREFIXES,
    MISSING,
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
    Rename,
    Selection,
    SelectionSpec,
    SetLiteral,
    Sub,
    TableReported,
    Unary,
    Where,
    With,
)


class DpmXlSyntaxError(ValueError):
    """Raised when an expression does not match the DPM-XL grammar."""

    def __init__(self, message: str, expression: str, position: int) -> None:
        """Record the failing position.

        Args:
            message: What was expected or found.
            expression: The complete source expression.
            position: Zero-based character offset of the error.
        """
        self.message = message
        self.expression = expression
        self.position = position
        super().__init__(f"{message} at position {position}")

    def pointer(self) -> str:
        """Render the source line with a caret under the failing position.

        Returns:
            str: Two lines suitable for terminal output.
        """
        start = self.expression.rfind("\n", 0, self.position) + 1
        end = self.expression.find("\n", self.position)
        line = self.expression[start : end if end >= 0 else None]
        return f"{line}\n{' ' * (self.position - start)}^"


@dataclass(frozen=True, slots=True)
class Token:
    """One lexical token with its source offsets."""

    kind: str
    text: str
    start: int
    end: int


_KEYWORDS = frozenset(
    {
        "and",
        "by",
        "else",
        "endif",
        "false",
        "group",
        "if",
        "in",
        "not",
        "null",
        "or",
        "then",
        "true",
        "xor",
    }
)
_CLAUSES = ("where", "get", "sub", "rename")
_AGGREGATE_ALIASES = {"max_aggr": "max", "min_aggr": "min"}
_NUMBER = re.compile(r"\d+(?:\.\d+)?(?:[eE][+-]?\d+)?|\.\d+")
_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_.]*")
_OPERATORS = ("<>", "!=", "<=", ">=", "=", "<", ">", "+", "-", "*", "/", "%")
_PUNCTUATION = "(),:"
_CLAUSE_START = re.compile(r"\[\s*(where|get|sub|rename)\b", re.IGNORECASE)
_AXIS_PART = re.compile(r"([rcs])(\*|[0-9A-Za-z]+(?:-[0-9A-Za-z]+)?)$")


def tokenize(expression: str) -> list[Token]:
    """Split an expression into tokens.

    Braces and item brackets are captured whole: a ``{...}`` token keeps its
    raw body for the parser to interpret as a selection or a set, and an
    ``[ns:code]`` token keeps the item text. Clause brackets such as
    ``[where`` produce separate ``[`` and keyword tokens.

    Returns:
        list[Token]: Tokens ending with an ``eof`` token.

    Raises:
        DpmXlSyntaxError: On an unterminated literal or unknown character.
    """
    tokens: list[Token] = []
    index = 0
    length = len(expression)
    while index < length:
        char = expression[index]
        if char.isspace():
            index += 1
            continue
        if char in "\"'":
            end = expression.find(char, index + 1)
            if end < 0:
                raise DpmXlSyntaxError("unterminated string", expression, index)
            tokens.append(Token("string", expression[index + 1 : end], index, end + 1))
            index = end + 1
            continue
        if char == "#":
            end = expression.find("#", index + 1)
            if end < 0:
                raise DpmXlSyntaxError("unterminated date", expression, index)
            tokens.append(Token("date", expression[index + 1 : end], index, end + 1))
            index = end + 1
            continue
        if char == "{":
            end = _matching(expression, index, "{", "}")
            tokens.append(Token("brace", expression[index + 1 : end], index, end + 1))
            index = end + 1
            continue
        if char == "[":
            clause = _CLAUSE_START.match(expression, index)
            if clause:
                tokens.append(Token("[", "[", index, index + 1))
                tokens.append(
                    Token(
                        "keyword",
                        clause.group(1).casefold(),
                        clause.start(1),
                        clause.end(1),
                    )
                )
                index = clause.end()
                continue
            end = expression.find("]", index + 1)
            if end < 0:
                raise DpmXlSyntaxError("unterminated item", expression, index)
            tokens.append(Token("item", expression[index + 1 : end], index, end + 1))
            index = end + 1
            continue
        if char == "]":
            tokens.append(Token("]", "]", index, index + 1))
            index += 1
            continue
        number = _NUMBER.match(expression, index)
        if number and (char.isdigit() or char == "."):
            tokens.append(Token("number", number.group(), index, number.end()))
            index = number.end()
            continue
        ident = _IDENT.match(expression, index)
        if ident:
            text = ident.group()
            # Identifiers may contain dots for table codes, but a trailing dot
            # never belongs to one.
            text = text.rstrip(".")
            end = index + len(text)
            kind = "keyword" if text.casefold() in _KEYWORDS else "ident"
            tokens.append(
                Token(kind, text.casefold() if kind == "keyword" else text, index, end)
            )
            index = end
            continue
        for operator in _OPERATORS:
            if expression.startswith(operator, index):
                tokens.append(Token("op", operator, index, index + len(operator)))
                index += len(operator)
                break
        else:
            if char in _PUNCTUATION:
                tokens.append(Token(char, char, index, index + 1))
                index += 1
                continue
            raise DpmXlSyntaxError(f"unexpected character {char!r}", expression, index)
    tokens.append(Token("eof", "", length, length))
    return tokens


def parse(expression: str) -> Node:
    """Parse a complete DPM-XL expression.

    Returns:
        Node: The expression tree.

    Raises:
        DpmXlSyntaxError: If the text is not a valid expression.
    """
    if not expression or not expression.strip():
        raise DpmXlSyntaxError("empty expression", expression or "", 0)
    parser = _Parser(expression, tokenize(expression), offset=0)
    node = parser.parse_root()
    parser.expect("eof")
    return node


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
    fields: dict[str, Any] = {}
    for part, start in _split_top_level(body):
        text = part.strip()
        position = offset + start + (len(part) - len(part.lstrip()))
        if not text:
            raise DpmXlSyntaxError("empty selection component", source, position)
        option = re.match(
            r"(default|interval)\s*:\s*(.*)$", text, re.IGNORECASE | re.DOTALL
        )
        if option:
            name = option.group(1).casefold()
            value = option.group(2).strip()
            if name in fields:
                raise DpmXlSyntaxError(f"duplicate {name} option", source, position)
            if name == "interval":
                if value.casefold() not in {"true", "false"}:
                    raise DpmXlSyntaxError(
                        "interval must be true or false", source, position
                    )
                fields[name] = value.casefold() == "true"
            else:
                fields[name] = _parse_default(value, source, position + option.start(2))
            continue
        if text.startswith("(") and text.endswith(")"):
            selector, axis = _parse_axis_list(text[1:-1], source, position + 1)
        elif text[0] == "t" and len(text) > 1 and _AXIS_PART.match(text) is None:
            if "table" in fields:
                raise DpmXlSyntaxError("duplicate table", source, position)
            fields["table"] = text[1:]
            continue
        else:
            selector, axis = _parse_axis_part(text, source, position)
        if axis in fields:
            raise DpmXlSyntaxError(f"duplicate {axis} selector", source, position)
        fields[axis] = selector
    return SelectionSpec(**fields)


class _Parser:
    def __init__(self, expression: str, tokens: list[Token], *, offset: int) -> None:
        self.expression = expression
        self.tokens = tokens
        self.index = 0
        self.offset = offset

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

    def at(self, kind: str, text: str | None = None) -> bool:
        token = self.current
        return token.kind == kind and (text is None or token.text == text)

    def at_keyword(self, *words: str) -> bool:
        return self.current.kind == "keyword" and self.current.text in words

    def accept(self, kind: str, text: str | None = None) -> Token | None:
        if self.at(kind, text):
            return self.advance()
        return None

    def expect(self, kind: str, text: str | None = None) -> Token:
        if self.at(kind, text):
            return self.advance()
        wanted = text or kind
        found = self.current.text or self.current.kind
        raise self.error(f"expected {wanted!r}, found {found!r}")

    def error(self, message: str, token: Token | None = None) -> DpmXlSyntaxError:
        position = (token or self.current).start + self.offset
        return DpmXlSyntaxError(message, self.expression, position)

    def span(self, start: int, end_token: Token | None = None) -> tuple[int, int]:
        end = (end_token or self.tokens[max(self.index - 1, 0)]).end
        return (start + self.offset, end + self.offset)

    # Grammar -----------------------------------------------------------

    def parse_root(self) -> Node:
        if self.current.kind == "ident" and self.current.text.casefold() == "with":
            start = self.advance().start
            brace = self.expect("brace")
            context = parse_selection(
                brace.text,
                expression=self.expression,
                offset=brace.start + 1 + self.offset,
            )
            condition = None
            if self.at("[") and self.peek().text == "where":
                self.advance()
                self.advance()
                condition = self.parse_expression()
                self.expect("]")
            self.expect(":")
            body = self.parse_root()
            return With(context, body, condition, span=self.span(start))
        return self.parse_expression()

    def parse_expression(self) -> Node:
        return self.parse_or()

    def parse_or(self) -> Node:
        left = self.parse_and()
        while self.at_keyword("or", "xor"):
            op = self.advance().text
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
            operand = self.parse_not()
            return Unary("not", operand, span=(start + self.offset, operand.span[1]))
        return self.parse_comparison()

    def parse_comparison(self) -> Node:
        left = self.parse_additive()
        if self.current.kind == "op" and self.current.text in {
            "=",
            "!=",
            "<>",
            "<",
            "<=",
            ">",
            ">=",
        }:
            op = self.advance().text
            right = self.parse_additive()
            return Binary(
                "!=" if op == "<>" else op,
                left,
                right,
                span=(left.span[0], right.span[1]),
            )
        if self.at_keyword("in"):
            self.advance()
            values = self.parse_set()
            return In(left, values, span=(left.span[0], values.span[1]))
        if (
            self.at_keyword("not")
            and self.peek().kind == "keyword"
            and self.peek().text == "in"
        ):
            start = self.advance().start
            self.advance()
            values = self.parse_set()
            node = In(left, values, span=(left.span[0], values.span[1]))
            return Unary("not", node, span=(start + self.offset, values.span[1]))
        return left

    def parse_set(self) -> SetLiteral:
        token = self.expect("brace")
        body_offset = token.start + 1 + self.offset
        items: list[Node] = []
        for part, start in _split_top_level(token.text):
            if not part.strip():
                raise DpmXlSyntaxError(
                    "empty set member", self.expression, body_offset + start
                )
            sub = _Parser(self.expression, tokenize(part), offset=body_offset + start)
            items.append(sub.parse_expression())
            sub.expect("eof")
        return SetLiteral(
            tuple(items), span=(token.start + self.offset, token.end + self.offset)
        )

    def parse_additive(self) -> Node:
        left = self.parse_multiplicative()
        while self.current.kind == "op" and self.current.text in {"+", "-"}:
            op = self.advance().text
            right = self.parse_multiplicative()
            left = Binary(op, left, right, span=(left.span[0], right.span[1]))
        return left

    def parse_multiplicative(self) -> Node:
        left = self.parse_unary()
        while self.current.kind == "op" and self.current.text in {"*", "/"}:
            op = self.advance().text
            right = self.parse_unary()
            left = Binary(op, left, right, span=(left.span[0], right.span[1]))
        return left

    def parse_unary(self) -> Node:
        if self.current.kind == "op" and self.current.text in {"+", "-"}:
            token = self.advance()
            operand = self.parse_unary()
            op = cast(Literal["+", "-"], token.text)
            return Unary(op, operand, span=(token.start + self.offset, operand.span[1]))
        return self.parse_postfix()

    def parse_postfix(self) -> Node:
        node = self.parse_primary()
        while True:
            if self.at("op", "%"):
                token = self.advance()
                if not (isinstance(node, Literal_) and node.kind == "number"):
                    raise self.error("'%' must follow a number", token)
                assert isinstance(node.value, Decimal)
                node = Literal_(
                    node.value / 100,
                    "number",
                    span=(node.span[0], token.end + self.offset),
                )
                continue
            if self.at("["):
                node = self.parse_clause(node)
                continue
            return node

    def parse_clause(self, operand: Node) -> Node:
        self.expect("[")
        keyword = self.expect("keyword").text
        if keyword == "where":
            condition = self.parse_expression()
            end = self.expect("]")
            return Where(
                operand, condition, span=(operand.span[0], end.end + self.offset)
            )
        if keyword == "get":
            name = self.expect("ident").text
            end = self.expect("]")
            return Get(operand, name, span=(operand.span[0], end.end + self.offset))
        if keyword == "sub":
            name = self.expect("ident").text
            self.expect("op", "=")
            value = self.parse_additive()
            end = self.expect("]")
            return Sub(
                operand, name, value, span=(operand.span[0], end.end + self.offset)
            )
        pairs: list[tuple[str, str]] = []
        while True:
            old = self.expect("ident").text
            if not (
                self.current.kind == "ident" and self.current.text.casefold() == "to"
            ):
                raise self.error("expected 'to' in rename clause")
            self.advance()
            pairs.append((old, self.expect("ident").text))
            if not self.accept(","):
                break
        end = self.expect("]")
        return Rename(
            operand, tuple(pairs), span=(operand.span[0], end.end + self.offset)
        )

    def parse_primary(self) -> Node:
        token = self.current
        if token.kind == "number":
            self.advance()
            try:
                value = Decimal(token.text)
            except InvalidOperation as error:  # pragma: no cover - regex guarantees
                raise self.error("invalid number", token) from error
            return Literal_(value, "number", span=self.span(token.start))
        if token.kind == "string":
            self.advance()
            return Literal_(token.text, "string", span=self.span(token.start))
        if token.kind == "date":
            self.advance()
            try:
                value = date.fromisoformat(token.text.strip())
            except ValueError as error:
                raise self.error(f"invalid date {token.text!r}", token) from error
            return Literal_(value, "date", span=self.span(token.start))
        if token.kind == "item":
            self.advance()
            return Literal_(Item.parse(token.text), "item", span=self.span(token.start))
        if token.kind == "keyword":
            if token.text in {"true", "false"}:
                self.advance()
                return Literal_(
                    token.text == "true", "boolean", span=self.span(token.start)
                )
            if token.text == "null":
                self.advance()
                return Literal_(None, "null", span=self.span(token.start))
            if token.text == "if":
                return self.parse_if()
            raise self.error(f"unexpected keyword {token.text!r}")
        if token.kind == "brace":
            self.advance()
            return self.parse_brace(token)
        if token.kind == "(":
            self.advance()
            inner = self.parse_expression()
            end = self.expect(")")
            # Keep the parenthesized span so explanations can show "( ... )".
            return _with_span(inner, (token.start + self.offset, end.end + self.offset))
        if token.kind == "ident":
            self.advance()
            if self.at("("):
                return self.parse_call(token)
            return Name(token.text, span=self.span(token.start))
        raise self.error(f"unexpected {token.text or token.kind!r}")

    def parse_if(self) -> Node:
        start = self.expect("keyword", "if").start
        condition = self.parse_expression()
        self.expect("keyword", "then")
        then = self.parse_expression()
        otherwise = None
        if self.accept("keyword", "else"):
            otherwise = self.parse_expression()
        end = self.expect("keyword", "endif")
        return If(condition, then, otherwise, span=self.span(start, end))

    def parse_call(self, name: Token) -> Node:
        self.expect("(")
        args: list[Node] = []
        group_by: tuple[str, ...] | None = None
        if not self.at(")"):
            while True:
                args.append(self.parse_expression())
                if self.at_keyword("group"):
                    self.advance()
                    self.expect("keyword", "by")
                    keys = [self.expect("ident").text]
                    while self.accept(","):
                        keys.append(self.expect("ident").text)
                    group_by = tuple(keys)
                    break
                if not self.accept(","):
                    break
        end = self.expect(")")
        function = name.text.casefold()
        if function in _AGGREGATE_ALIASES:
            # max_aggr/min_aggr are the aggregate forms of max/min, which the
            # evaluators recognise by their single operand.
            if len(args) != 1:
                raise self.error(f"{function} takes one operand")
            function = _AGGREGATE_ALIASES[function]
        return Call(function, tuple(args), group_by, span=self.span(name.start, end))

    def parse_brace(self, token: Token) -> Node:
        body = token.text.strip()
        span = (token.start + self.offset, token.end + self.offset)
        if re.fullmatch(r"v_[A-Za-z0-9_.\-]+", body):
            return TableReported(body[2:], span=span)
        if re.fullmatch(r"v[A-Za-z][A-Za-z0-9_]*", body) and not body.startswith("v_"):
            return Parameter(body[1:], span=span)
        spec = parse_selection(
            token.text, expression=self.expression, offset=token.start + 1 + self.offset
        )
        return Selection(spec, span=span)


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
    raise DpmXlSyntaxError(f"unterminated {opening!r}", expression, start)


def _split_top_level(text: str) -> list[tuple[str, int]]:
    """Split on commas outside parentheses, brackets, braces and quotes.

    Returns:
        list[tuple[str, int]]: Each part with its offset inside ``text``.
    """
    parts: list[tuple[str, int]] = []
    depth = 0
    quote: str | None = None
    start = 0
    for index, char in enumerate(text):
        if quote:
            if char == quote:
                quote = None
            continue
        if char in "\"'":
            quote = char
        elif char in "([{":
            depth += 1
        elif char in ")]}":
            depth -= 1
        elif char == "," and depth == 0:
            parts.append((text[start:index], start))
            start = index + 1
    parts.append((text[start:], start))
    if len(parts) == 1 and not parts[0][0].strip():
        return []
    return parts


def _parse_axis_part(text: str, source: str, position: int) -> tuple[AxisSelector, str]:
    match = _AXIS_PART.match(text.strip())
    if match is None:
        raise DpmXlSyntaxError(
            f"unknown selection component {text!r}", source, position
        )
    axis = AXIS_PREFIXES[match.group(1)]
    value = match.group(2)
    if value == "*":
        return AxisSelector(wildcard=True), axis
    if "-" in value:
        low, high = value.split("-", 1)
        return AxisSelector(parts=((low, high),)), axis
    return AxisSelector(parts=(value,)), axis


def _parse_axis_list(text: str, source: str, position: int) -> tuple[AxisSelector, str]:
    parts: list[str | tuple[str, str]] = []
    axis: str | None = None
    for part, start in _split_top_level(text):
        selector, part_axis = _parse_axis_part(part, source, position + start)
        if axis is not None and part_axis != axis:
            raise DpmXlSyntaxError("axis list mixes axes", source, position + start)
        if selector.wildcard:
            raise DpmXlSyntaxError(
                "wildcard inside an axis list", source, position + start
            )
        axis = part_axis
        parts.extend(selector.parts)
    if axis is None:
        raise DpmXlSyntaxError("empty axis list", source, position)
    return AxisSelector(parts=tuple(parts)), axis


def _parse_default(value: str, source: str, position: int) -> Literal_:
    text = value.strip()
    span = (position, position + len(text))
    if text.casefold() == "null":
        return Literal_(None, "null", span=span)
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'":
        return Literal_(text[1:-1], "string", span=span)
    if text.casefold() in {"true", "false"}:
        return Literal_(text.casefold() == "true", "boolean", span=span)
    if text.startswith("[") and text.endswith("]"):
        return Literal_(Item.parse(text[1:-1]), "item", span=span)
    if text.startswith("#") and text.endswith("#"):
        try:
            return Literal_(date.fromisoformat(text[1:-1]), "date", span=span)
        except ValueError as error:
            raise DpmXlSyntaxError("invalid default date", source, position) from error
    try:
        return Literal_(Decimal(text), "number", span=span)
    except InvalidOperation as error:
        raise DpmXlSyntaxError(f"invalid default {text!r}", source, position) from error


_ = MISSING  # re-exported for callers building specs by hand

__all__ = ["DpmXlSyntaxError", "Token", "parse", "parse_selection", "tokenize"]
