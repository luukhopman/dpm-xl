"""Explain a failing record by filling each operand with its value.

For ``{r0010} = {r0020} + {r0030}`` failing at column ``0010`` the
explanation reads ``1,204 = 1,180 + 31`` with the summary
``expected 1,204 = 1,180 + 31, off by 7``. The filled formula is rebuilt from
the original source text, so parentheses, operators and spacing stay as the
rule author wrote them.
"""

from __future__ import annotations

from collections.abc import Hashable, Mapping
from dataclasses import dataclass

from .ast import (
    Binary,
    Call,
    Get,
    Literal_,
    Node,
    Parameter,
    Selection,
    Sub,
    TableReported,
    Where,
    With,
    children,
)
from .evaluator import AGGREGATES, Evaluation
from .provider import DataPoint
from .values import Number, Value, format_decimal, format_value

_COMPARISON_WORDS = {
    "=": "=",
    "!=": "≠",
    "<": "<",
    "<=": "≤",
    ">": ">",
    ">=": "≥",
}


@dataclass(frozen=True, slots=True)
class Operand:
    """One leaf operand of a failing record with its value and cells."""

    source: str
    value: str
    points: tuple[DataPoint, ...]


@dataclass(frozen=True, slots=True)
class Explanation:
    """Human-readable account of one evaluated record."""

    formula: str
    filled: str
    summary: str
    operands: tuple[Operand, ...]
    difference: str | None = None


def explain(
    evaluation: Evaluation, expression: str, key: Mapping[str, Hashable]
) -> Explanation:
    """Explain the record of ``evaluation`` identified by ``key``.

    Args:
        evaluation: A traced evaluation from :class:`dpmxl.evaluator.Evaluator`.
        expression: The source text the tree was parsed from.
        key: The record key, as in :attr:`dpmxl.evaluator.Outcome.key`.

    Returns:
        Explanation: Formula, filled formula, a one-line summary and operands.
    """
    body = evaluation.root
    while isinstance(body, With):
        body = body.body
    renderer = _Renderer(evaluation, expression, key)
    filled = renderer.render(body)
    formula = _source(expression, body)
    comparison = renderer.failing_comparison(body)
    difference = None
    if comparison is not None:
        left = renderer.value(comparison.left)
        right = renderer.value(comparison.right)
        text = (
            f"{renderer.render(comparison.left)} "
            f"{_COMPARISON_WORDS[comparison.op]} {renderer.render(comparison.right)}"
        )
        summary = f"expected {text}"
        if isinstance(left, Number) and isinstance(right, Number):
            delta = left.value - right.value
            difference = format_decimal(abs(delta))
            if comparison.op in {"=", "<=", ">=", "<", ">"} and delta:
                summary += f", off by {difference}"
            tolerance = left.tolerance + right.tolerance
            if tolerance:
                summary += f" (tolerance ±{format_decimal(tolerance)})"
    else:
        summary = f"expected true: {filled}"
    return Explanation(
        formula=formula,
        filled=filled,
        summary=summary,
        operands=tuple(renderer.operands),
        difference=difference,
    )


class _Renderer:
    def __init__(
        self, evaluation: Evaluation, expression: str, key: Mapping[str, Hashable]
    ) -> None:
        self.evaluation = evaluation
        self.expression = expression
        self.key = key
        self.operands: list[Operand] = []
        self._seen: set[int] = set()

    def value(self, node: Node) -> Value | None:
        records = self.evaluation.value_at(node, self.key)
        if len(records) == 1:
            return records[0].value
        return None

    def render(self, node: Node) -> str:
        if _is_leaf(node):
            records = self.evaluation.value_at(node, self.key)
            if len(records) == 1:
                text = format_value(records[0].value)
                points = records[0].points
            elif not records:
                text = "∅"
                points = ()
            else:
                text = f"{len(records)} values"
                points = tuple(point for record in records for point in record.points)
            if not isinstance(node, Literal_) and id(node) not in self._seen:
                self._seen.add(id(node))
                self.operands.append(
                    Operand(_source(self.expression, node), text, points)
                )
            return text
        source = _source(self.expression, node)
        start = node.span[0]
        pieces: list[str] = []
        cursor = 0
        for child in sorted(children(node), key=lambda item: item.span[0]):
            child_start = child.span[0] - start
            child_end = child.span[1] - start
            if child_start < cursor or child_end > len(source):
                continue
            pieces.append(source[cursor:child_start])
            pieces.append(self.render(child))
            cursor = child_end
        pieces.append(source[cursor:])
        return " ".join("".join(pieces).split())

    def failing_comparison(self, node: Node) -> Binary | None:
        pending = [node]
        while pending:
            current = pending.pop(0)
            if (
                isinstance(current, Binary)
                and current.op in _COMPARISON_WORDS
                and self.value(current) is False
            ):
                return current
            if _is_leaf(current):
                continue
            pending.extend(children(current))
        return None


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


__all__ = ["Explanation", "Operand", "explain"]
