"""Explain a failing record in words and with the formula's values filled in.

For ``{r0010} = {r0020} + {r0030}`` failing at column ``0010``:

* ``summary``: ``1,204 should equal 1,197 (1,180 + 17): difference 7``;
* ``filled``: ``1,204 = 1,180 + 17``;
* ``left`` and ``right``: each side's formula, value, filled text and cells.

Formulas are rendered from the expression tree rather than copied from the
source, so spacing is uniform, negative terms read ``a - 226,000`` (with a
typographic minus) instead of ``a + -226,000``, and long runs of zero terms
collapse to ``+ 0 (x13)``.
Failures that are not comparisons (a value that must be reported, must be
empty, must be one of a set, or must match a pattern) get a sentence of their
own.
"""

from __future__ import annotations

from collections.abc import Hashable, Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal, cast

from .ast import (
    Binary,
    Call,
    Get,
    If,
    In,
    Literal_,
    Name,
    Node,
    Parameter,
    Rename,
    Selection,
    SetLiteral,
    Sub,
    TableReported,
    Unary,
    Where,
    With,
    children,
)
from .evaluator import AGGREGATES, Evaluation
from .provider import DataPoint
from .recordset import unique_points
from .values import Number, Value, format_decimal, format_value

MINUS = "\u2212"
TIMES = "\u00d7"
_SYMBOLS = {
    "=": "=",
    "!=": "≠",
    "<": "<",
    "<=": "≤",
    ">": ">",
    ">=": "≥",
    "+": "+",
    "-": MINUS,
    "*": TIMES,
    "/": "÷",
    "and": "and",
    "or": "or",
    "xor": "xor",
}
_COMPARISONS = frozenset({"=", "!=", "<", "<=", ">", ">="})
VERBS = {
    "=": "should equal",
    "!=": "should differ from",
    "<": "should be less than",
    "<=": "should not exceed",
    ">": "should exceed",
    ">=": "should be at least",
}
_ZERO_RUN = 3

Kind = Literal[
    "comparison", "missing", "not_empty", "membership", "format", "condition"
]
Direction = Literal["too_high", "too_low"]


@dataclass(frozen=True, slots=True)
class Operand:
    """One leaf operand of a failing record with its value and cells."""

    source: str
    value: str
    points: tuple[DataPoint, ...]


@dataclass(frozen=True, slots=True)
class Side:
    """One side of the failing comparison."""

    formula: str
    filled: str
    value: str
    points: tuple[DataPoint, ...]
    terms: int
    """Number of operands (cells, aggregates, parameters) on this side."""
    threshold: str | None = None
    """Half-width of the side's interval from reported precision; None if exact."""
    low: str | None = None
    high: str | None = None

    @property
    def single_cell(self) -> bool:
        """Whether the side is exactly one reported cell."""
        return self.terms == 1 and len(self.points) == 1


@dataclass(frozen=True, slots=True)
class Explanation:
    """Human-readable account of one evaluated record."""

    formula: str
    filled: str
    summary: str
    operands: tuple[Operand, ...]
    difference: str | None = None
    primary: tuple[DataPoint, ...] = ()
    """Cells on the left of the failing comparison: the values that disagree."""
    kind: Kind = "condition"
    relation: str | None = None
    verb: str | None = None
    left: Side | None = None
    right: Side | None = None
    gap: str | None = None
    """How far apart the two sides' intervals are: the smallest difference
    that remains when every value may vary within its reported precision."""
    direction: Direction | None = None
    """Which side is larger (``too_high``: left exceeds right), not a verdict
    on which value is wrong."""
    tolerance: str | None = None


def explain(
    evaluation: Evaluation, expression: str, key: Mapping[str, Hashable]
) -> Explanation:
    """Explain the record of ``evaluation`` identified by ``key``.

    Args:
        evaluation: A traced evaluation from :class:`dpmxl.evaluator.Evaluator`.
        expression: The source text the tree was parsed from.
        key: The record key, as in :attr:`dpmxl.evaluator.Outcome.key`.

    Returns:
        Explanation: Summary sentence, formula, filled formula and operands.
    """
    body = evaluation.root
    while isinstance(body, With):
        body = body.body
    formatter = _Formatter(evaluation, expression, key)
    filled = formatter.render(body, filled=True)
    formula = formatter.render(body, filled=False)
    failing = formatter.failing(body)
    operands = tuple(formatter.operands)

    if isinstance(failing, Binary) and failing.op in _COMPARISONS:
        return _comparison(formatter, failing, formula, filled, operands)
    primary = formatter.points(failing) if failing is not None else ()
    kind, summary = _condition_summary(formatter, failing, filled)
    return Explanation(
        formula=formula,
        filled=filled,
        summary=summary,
        operands=operands,
        primary=primary,
        kind=kind,
    )


def _comparison(
    formatter: _Formatter,
    node: Binary,
    formula: str,
    filled: str,
    operands: tuple[Operand, ...],
) -> Explanation:
    left, right = formatter.side(node.left), formatter.side(node.right)
    left_value, right_value = formatter.value(node.left), formatter.value(node.right)
    verb = VERBS[node.op]
    summary = f"{left.value} {verb} {right.value}"
    if right.terms > 1 or (right.filled != right.value and right.terms):
        summary += f" ({right.filled})"
    difference = direction = tolerance = gap = None
    if isinstance(left_value, Number) and isinstance(right_value, Number):
        delta = left_value.value - right_value.value
        difference = format_decimal(abs(delta))
        direction = _direction(node.op, delta)
        width = left_value.tolerance + right_value.tolerance
        if delta:
            # A failed rule shows the values disagree, not which one is wrong.
            summary += f": difference {difference}"
        if width:
            tolerance = format_decimal(_round_threshold(width))
            distance = _gap(node.op, left_value, right_value)
            if distance is not None and distance > 0:
                gap = format_decimal(_round_threshold(distance, at_least=distance))
                summary += f", at least {gap} given the reported precision"
    return Explanation(
        formula=formula,
        filled=filled,
        summary=summary,
        operands=operands,
        difference=difference,
        primary=left.points,
        kind="comparison",
        relation=_SYMBOLS[node.op],
        verb=verb,
        left=left,
        right=right,
        direction=direction,
        tolerance=tolerance,
        gap=gap,
    )


def _round_threshold(width: Decimal, *, at_least: Decimal | None = None) -> Decimal:
    """Round an interval width for display: 82.477425 reads 82.5, 0.0001 stays.

    Args:
        width: The exact width.
        at_least: Keep at least this value's integer part (for gaps).

    Returns:
        Decimal: The width to two significant digits, at least one decimal.
    """
    if not width:
        return width
    if at_least is not None and abs(at_least) >= 1:
        return round(width, 1).normalize()
    exponent = width.adjusted()
    places = max(1, 1 - exponent)
    return round(width, places)


def _gap(op: str, left: Number, right: Number) -> Decimal | None:
    """Distance between the sides' intervals in the direction the rule forbids.

    Returns:
        Decimal | None: Positive when no values within the reported precision
        satisfy the rule.
    """
    width = left.tolerance + right.tolerance
    match op:
        case "=":
            return abs(left.value - right.value) - width
        case "<=" | "<":
            return (left.value - right.value) - width
        case ">=" | ">":
            return (right.value - left.value) - width
    return None


def _direction(op: str, delta: Decimal) -> Direction | None:
    if op == "=":
        return "too_high" if delta > 0 else "too_low" if delta < 0 else None
    if op in {"<", "<="}:
        return "too_high"
    if op in {">", ">="}:
        return "too_low"
    return None


def _condition_summary(
    formatter: _Formatter, node: Node | None, filled: str
) -> tuple[Kind, str]:
    match node:
        case Unary(op="not", operand=Call(name="isnull", args=(operand,))):
            return (
                "missing",
                f"{formatter.render(operand, filled=False)} must be reported",
            )
        case Call(name="isnull", args=(operand,)):
            value = formatter.render(operand, filled=True)
            return "not_empty", (
                f"{formatter.render(operand, filled=False)} must be empty, "
                f"but {value} is reported"
            )
        case In(operand=operand, values=values):
            options = ", ".join(
                formatter.render(item, filled=True) for item in values.items[:6]
            )
            more = f" and {len(values.items) - 6} more" if len(values.items) > 6 else ""
            value = formatter.render(operand, filled=True)
            return "membership", f"{value} is not one of {options}{more}"
        case Call(name="match", args=(operand, _pattern)):
            value = formatter.render(operand, filled=True)
            return "format", f"{value} does not have the required format"
    return "condition", f"Condition not met: {filled}"


class _Formatter:
    def __init__(
        self, evaluation: Evaluation, expression: str, key: Mapping[str, Hashable]
    ) -> None:
        self.evaluation = evaluation
        self.expression = expression
        self.key = key
        self.operands: list[Operand] = []
        self._seen: set[int] = set()

    # Values -------------------------------------------------------------

    def records(self, node: Node) -> list:
        return self.evaluation.value_at(node, self.key)

    def value(self, node: Node) -> Value | None:
        records = self.records(node)
        return records[0].value if len(records) == 1 else None

    def points(self, node: Node) -> tuple[DataPoint, ...]:
        return unique_points(
            point for record in self.records(node) for point in record.points
        )

    def side(self, node: Node) -> Side:
        records = self.records(node)
        value = format_value(records[0].value) if len(records) == 1 else "\u2205"
        number = records[0].value if len(records) == 1 else None
        threshold = low = high = None
        if isinstance(number, Number) and number.tolerance:
            shown = _round_threshold(number.tolerance)
            threshold = format_decimal(shown)
            exponent = shown.as_tuple().exponent
            places = max(-exponent, 0) if isinstance(exponent, int) else 0
            low = format_decimal(round(number.low, places))
            high = format_decimal(round(number.high, places))
        return Side(
            formula=self.render(node, filled=False),
            filled=self.render(node, filled=True),
            value=value,
            points=self.points(node),
            terms=sum(1 for leaf in _leaves(node) if not isinstance(leaf, Literal_)),
            threshold=threshold,
            low=low,
            high=high,
        )

    def failing(self, node: Node) -> Node | None:
        """Return the outermost false comparison or condition, breadth first."""
        pending = [node]
        fallback: Node | None = None
        while pending:
            current = pending.pop(0)
            verdict = self.value(current)
            if verdict is False:
                if isinstance(current, Binary) and current.op in _COMPARISONS:
                    return current
                if isinstance(current, In | Call) or (
                    isinstance(current, Unary) and isinstance(current.operand, Call)
                ):
                    fallback = fallback or current
            if _is_leaf(current):
                continue
            if isinstance(current, If):
                condition = self.value(current.condition)
                branch = current.then if condition is True else current.otherwise
                if branch is not None:
                    pending.append(branch)
                continue
            pending.extend(children(current))
        return fallback

    # Rendering -----------------------------------------------------------

    def render(self, node: Node, *, filled: bool) -> str:
        text = self._render(node, filled=filled)
        if self._parenthesized(node) and not _is_leaf(node):
            return f"({text})"
        return text

    def _render(self, node: Node, *, filled: bool) -> str:
        if _is_leaf(node):
            return self._leaf(node, filled=filled)
        match node:
            case Binary(op="+" | "-"):
                return self._additive(node, filled=filled)
            case Binary(op=op, left=left, right=right):
                return (
                    f"{self.render(left, filled=filled)} {_SYMBOLS.get(op, op)} "
                    f"{self.render(right, filled=filled)}"
                )
            case Unary(op="not", operand=operand):
                return f"not {self.render(operand, filled=filled)}"
            case Unary(op=op, operand=operand):
                sign = MINUS if op == "-" else "+"
                return f"{sign}{self.render(operand, filled=filled)}"
            case Call(name=name, args=args):
                inner = ", ".join(self.render(arg, filled=filled) for arg in args)
                return f"{name}({inner})"
            case In(operand=operand, values=values):
                members = ", ".join(
                    self.render(item, filled=filled) for item in values.items
                )
                return f"{self.render(operand, filled=filled)} in {{{members}}}"
            case SetLiteral(items=items):
                return (
                    "{"
                    + ", ".join(self.render(item, filled=filled) for item in items)
                    + "}"
                )
            case If(condition=condition, then=then, otherwise=otherwise):
                text = (
                    f"if {self.render(condition, filled=filled)} "
                    f"then {self.render(then, filled=filled)}"
                )
                if otherwise is not None:
                    text += f" else {self.render(otherwise, filled=filled)}"
                return text
            case Rename(operand=operand):
                return self.render(operand, filled=filled)
            case With(body=body):
                return self.render(body, filled=filled)
            case Name(name=name):
                return name
        return _source(self.expression, node)

    def _leaf(self, node: Node, *, filled: bool) -> str:
        source = _compact(_source(self.expression, node))
        if isinstance(node, Literal_):
            if node.kind == "number" and source.endswith("%"):
                return source
            return format_value(_literal_value(node)) if filled else source
        records = self.records(node)
        if len(records) == 1:
            text = format_value(records[0].value)
            points = unique_points(records[0].points)
        elif not records:
            text, points = "∅", ()
        else:
            text = f"{len(records)} values"
            points = tuple(point for record in records for point in record.points)
        if id(node) not in self._seen:
            self._seen.add(id(node))
            self.operands.append(Operand(source, text, points))
        return text if filled else source

    def _additive(self, node: Node, *, filled: bool) -> str:
        terms = _flatten_additive(node)
        rendered: list[tuple[int, str, bool]] = []
        for sign, term in terms:
            text = self.render(term, filled=filled)
            value = self.value(term) if filled else None
            zero = isinstance(value, Number) and value.value == 0
            if (
                filled
                and isinstance(value, Number)
                and value.value < 0
                and text.startswith("-")
            ):
                sign, text = -sign, text[1:]
            rendered.append((sign, text, zero))
        zeros = [item for item in rendered[1:] if item[2]]
        if filled and len(zeros) >= _ZERO_RUN:
            kept = [rendered[0], *(item for item in rendered[1:] if not item[2])]
            suffix = f" + 0 ({TIMES}{len(zeros)})"
        else:
            kept, suffix = rendered, ""
        first_sign, first_text, _ = kept[0]
        parts = [(MINUS if first_sign < 0 else "") + first_text]
        for sign, text, _zero in kept[1:]:
            parts.append(f"{'+' if sign > 0 else MINUS} {text}")
        return " ".join(parts) + suffix

    def _parenthesized(self, node: Node) -> bool:
        start, end = node.span
        text = self.expression[start:end].strip()
        return text.startswith("(") and text.endswith(")") and isinstance(node, Binary)


def _flatten_additive(node: Node, sign: int = 1) -> list[tuple[int, Node]]:
    # Sums and differences flatten without changing their value, whatever
    # the source's parentheses: a - (b - c) is a - b + c.
    if isinstance(node, Binary) and node.op in {"+", "-"}:
        right_sign = sign if node.op == "+" else -sign
        return _flatten_additive(node.left, sign) + _flatten_additive(
            node.right, right_sign
        )
    if isinstance(node, Unary) and node.op in {"+", "-"} and _is_leaf(node.operand):
        return [(sign if node.op == "+" else -sign, node.operand)]
    return [(sign, node)]


def _leaves(node: Node) -> list[Node]:
    if _is_leaf(node):
        return [node]
    return [leaf for child in children(node) for leaf in _leaves(child)]


def _literal_value(node: Literal_) -> Value:
    if node.kind == "number" and isinstance(node.value, Decimal):
        return Number(node.value)
    return cast(Value, node.value)


def _is_leaf(node: Node) -> bool:
    if isinstance(node, Selection | Literal_ | Parameter | TableReported):
        return True
    if (
        isinstance(node, Call)
        and node.name in AGGREGATES
        and (len(node.args) == 1 or node.group_by is not None)
    ):
        return True
    return isinstance(node, Where | Get | Sub)


def _source(expression: str, node: Node) -> str:
    start, end = node.span
    return " ".join(expression[start:end].split())


def _compact(text: str) -> str:
    """Normalize spacing inside a leaf, e.g. ``sum ({r0010})`` to ``sum({r0010})``.

    Returns:
        str: The compacted text.
    """
    for name in ("sum", "count", "avg", "max", "min", "median"):
        text = text.replace(f"{name} (", f"{name}(")
    text = text.replace("( ", "(").replace(" )", ")")
    if text.startswith("(") and text.endswith(")") and text.count("(") == 1:
        text = text[1:-1].strip()
    return text


__all__ = ["VERBS", "Explanation", "Operand", "Side", "explain"]
