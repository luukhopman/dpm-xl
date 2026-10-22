"""Randomly generated rules and data must evaluate alike on both engines.

The cases are seeded, so a failure names a reproducible seed; run
``pytest tests/test_columnar_random.py -k <seed>`` to see its expression.
"""

import random

import pytest

pytest.importorskip("polars")

from dpmxl import (
    Item,
    MemoryProvider,
    Number,
    TableLayout,
    Value,
    evaluate_rule,
)
from dpmxl.columnar import (
    ColumnarUnsupported,
    PointsFrameProvider,
    canonical_key,
    evaluate_rule_columnar,
)
from dpmxl.provider import CellKey

ROWS = ("0010", "0020", "0030")
COLUMNS = ("0010", "0020")
KEYS = tuple(Item("qK", code) for code in ("a", "b", "c", "d"))
CASES = 400


def _number(rng: random.Random) -> Value | None:
    if rng.random() < 0.15:
        return None
    value = rng.choice((0, 0, 1, -3, 7, 15, 60, 100, 1180, 1204, "2.5", "-0.25"))
    return Number.of(value, rng.choice((0, 0, 1, 2, -3)))


def _provider(rng: random.Random) -> MemoryProvider:
    tables = [
        TableLayout("T", rows=ROWS, columns=COLUMNS),
        TableLayout("O", rows=ROWS[:2], columns=("0010",), open_keys=("qKEY",)),
    ]
    values: dict[CellKey, Value] = {}
    for row in ROWS:
        for column in COLUMNS:
            if (value := _number(rng)) is not None:
                values["T", row, column, None, ()] = value
    for key in rng.sample(KEYS, rng.randint(0, len(KEYS))):
        for row in ROWS[:2]:
            if (value := _number(rng)) is not None:
                values["O", row, "0010", None, (("qKEY", key),)] = value
    return MemoryProvider(tables, values, parameters={"refPeriod": None})


class _Rules:
    """Build one rule in a ``with`` context over table T or the open table O."""

    def __init__(self, rng: random.Random) -> None:
        self.rng = rng
        self.open = rng.random() < 0.4
        rows = ROWS[:2] if self.open else ROWS
        self.cells = [f"{{r{row}}}" for row in rows]
        if not self.open:
            self.cells += [f"{{r{row}, c*}}" for row in rows]

    def rule(self) -> str:
        table = "tO, c0010" if self.open else "tT, c*"
        default = self.rng.choice(("default: 0, ", "default: 0, ", ""))
        interval = self.rng.choice(("true", "false"))
        return f"with {{{table}, {default}interval: {interval}}}: {self.boolean(2)}"

    def number(self, depth: int) -> str:
        rng = self.rng
        choice = rng.random() if depth else 0.0
        if choice < 0.55:
            return (
                rng.choice(self.cells)
                if rng.random() < 0.85
                else str(rng.choice((0, 1, 10, 1.5, 100)))
            )
        if choice < 0.8:
            operator = rng.choice(("+", "-", "*", "+", "-"))
            return f"({self.number(depth - 1)} {operator} {self.number(depth - 1)})"
        if choice < 0.85:
            return f"abs({self.number(depth - 1)})"
        if choice < 0.92:
            function = rng.choice(("max", "min"))
            return f"{function}({self.number(depth - 1)}, {self.number(depth - 1)})"
        return self.aggregate()

    def aggregate(self) -> str:
        rng = self.rng
        function = rng.choice(("sum", "count", "avg", "min", "max", "median"))
        cell = rng.choice(self.cells)
        if self.open and rng.random() < 0.4:
            cell += " [where qKEY in {[qK:a], [qK:c]}]"
        group = " group by qKEY" if self.open and rng.random() < 0.4 else ""
        return f"{function}({cell}{group})"

    def boolean(self, depth: int) -> str:
        rng = self.rng
        choice = rng.random() if depth else 0.0
        if choice < 0.55:
            relation = rng.choice(("=", "!=", "<", "<=", ">", ">="))
            left = self.number(depth)
            if self.open and rng.random() < 0.15:
                left = f"{rng.choice(self.cells)} [where qKEY != [qK:b]]"
            return f"{left} {relation} {self.number(depth)}"
        if choice < 0.7:
            joiner = rng.choice(("and", "or", "xor"))
            return f"({self.boolean(depth - 1)} {joiner} {self.boolean(depth - 1)})"
        if choice < 0.8:
            return f"not({self.boolean(depth - 1)})"
        if choice < 0.9:
            return f"isnull({rng.choice(self.cells)})"
        otherwise = f" else {self.boolean(depth - 1)}" if rng.random() < 0.5 else ""
        return (
            f"if {self.boolean(depth - 1)} then {self.boolean(depth - 1)}"
            f"{otherwise} endif"
        )


def _keys(keys) -> list[str]:
    return sorted(str(sorted(key.items())) for key in keys)


@pytest.mark.parametrize("seed", range(CASES))
def test_random_rules_agree(seed: int) -> None:
    rng = random.Random(seed)
    provider = _provider(rng)
    expression = _Rules(rng).rule()
    reference = evaluate_rule(expression, provider)
    try:
        columnar = evaluate_rule_columnar(
            expression, PointsFrameProvider(provider), max_failing_keys=10_000
        )
    except ColumnarUnsupported:
        return
    context = (expression, reference.message, columnar.message)
    assert columnar.status == reference.status, context
    if reference.status in {"error", "unsupported"}:
        return
    assert (columnar.passed, columnar.failed) == (
        reference.counts["passed"],
        reference.counts["failed"],
    ), context
    assert _keys(columnar.failing_keys or []) == _keys(
        canonical_key(outcome.key) for outcome in reference.failures
    ), context
