"""The small report that the examples of the language reference run against.

``report()`` returns it as a ``MemoryProvider``; the tests evaluate every
example with a shown result on ``docs/reference/language.md`` against it.
Run this file to evaluate an expression of your own:

    python examples/language_report.py "sum({tT, c0010, r*})"
"""

from __future__ import annotations

import sys
from datetime import date

from dpmxl import (
    DpmXlSyntaxError,
    Item,
    MemoryProvider,
    Number,
    TableLayout,
    ValueSet,
    format_value,
    parse_program,
)
from dpmxl.evaluator import Evaluator
from dpmxl.provider import CellKey
from dpmxl.recordset import EvaluationError, UnsupportedError
from dpmxl.values import Value


def tables() -> list[TableLayout]:
    """Return the layouts: closed tables T, U, S and X, open tables O and P.

    Returns:
        list[TableLayout]: The layouts.
    """
    return [
        TableLayout("T", rows=("0010", "0020", "0030"), columns=("0010", "0020")),
        TableLayout("U", rows=("0010", "0020", "0030"), columns=("0010",)),
        TableLayout("S", rows=("0010",), columns=("0010",), sheets=("0001", "0002")),
        TableLayout("X", rows=("0010",), columns=("0010", "0020", "0030", "0040")),
        TableLayout("O", columns=("0010", "0020"), open_keys=("qKEY", "qDAT")),
        TableLayout("P", columns=("0010",), open_keys=("qKEY",)),
    ]


def facts(shift: int = 0) -> dict[CellKey, Value]:
    """Return the reported values; ``shift`` changes T r0010 c0010.

    Returns:
        dict[CellKey, Value]: The facts. T r0030 c0020 is not reported.
    """
    values: dict[CellKey, Value] = {
        ("T", "0010", "0010", None, ()): Number.of(100 + shift, 0),
        ("T", "0020", "0010", None, ()): Number.of(60, 0),
        ("T", "0030", "0010", None, ()): Number.of(40, 0),
        ("T", "0010", "0020", None, ()): Number.of(5, 0),
        ("T", "0020", "0020", None, ()): Number.of(-5, 0),
        ("U", "0010", "0010", None, ()): Number.of(1),
        ("U", "0020", "0010", None, ()): Number.of(2),
        ("U", "0030", "0010", None, ()): Number.of(3),
        ("S", "0010", "0010", "0001", ()): Number.of(7),
        ("S", "0010", "0010", "0002", ()): Number.of(8),
        ("X", "0010", "0010", None, ()): "LEI-A",
        ("X", "0010", "0020", None, ()): Item.parse("eba_CU:EUR"),
        ("X", "0010", "0030", None, ()): date(2026, 6, 30),
        ("X", "0010", "0040", None, ()): True,
        ("P", None, "0010", None, (("qKEY", "b"),)): Number.of(2),
        ("P", None, "0010", None, (("qKEY", "d"),)): Number.of(4),
    }
    for index, (key, day, currency) in enumerate(
        (
            ("a", date(2026, 3, 31), "EUR"),
            ("b", date(2026, 6, 30), "USD"),
            ("c", date(2026, 9, 30), "JPY"),
        ),
        start=1,
    ):
        keys = (("qKEY", key), ("qDAT", day))
        values["O", None, "0010", None, keys] = Number.of(10 * index)
        values["O", None, "0020", None, keys] = Item.parse(f"eba_CU:{currency}")
    return values


def report() -> MemoryProvider:
    """Return the report with its parameters, table group and operation.

    The report one year earlier, for ``time_shift``, differs only in T r0010
    c0010 (50) and ``refPeriod`` (2025-12-31).

    Returns:
        MemoryProvider: The report.
    """
    earlier = MemoryProvider(
        tables(), facts(shift=-50), parameters={"refPeriod": date(2025, 12, 31)}
    )
    return MemoryProvider(
        tables(),
        facts(),
        parameters={
            "refPeriod": date(2026, 12, 31),
            "Level": "solo",
            "Limit": 5,
            "Allowed": ValueSet((Item("CU", "EUR"), Item("CU", "USD"))),
        },
        table_groups={"G": ("T", "U")},
        operations={"v1": "with {tT, c0010}: {r*} * 2"},
        earlier_reports={("A", 1): earlier},
    )


def show(value: Value) -> str:
    """Format one value as the language reference shows it.

    Numbers appear in full, with ``± tolerance`` for an interval; text in
    quotes, items in brackets and dates in ISO form.

    Returns:
        str: The value's text.
    """
    if isinstance(value, Number):
        text = format(value.value.normalize(), "f")
        if value.tolerance:
            text += " ± " + format(value.tolerance.normalize(), "f")
        return text
    if isinstance(value, ValueSet):
        return "{" + ", ".join(show(member) for member in value.members) + "}"
    failure = getattr(value, "message", None)
    if failure is not None:  # a record whose computation failed, such as 1 / 0
        return f"error: {failure}"
    return format_value(value)


def evaluate(expression: str) -> str:
    """Evaluate an expression or script and show its result as the reference does.

    A result without keys is one value; a keyed result lists its records as
    ``key=value, …: value`` separated by ``;``. An evaluation error shows as
    ``error: message``, a syntax error as ``syntax error: message``.

    Returns:
        str: The result, such as ``6``, ``r=0010: 100; r=0020: 60`` or
        ``error: division by zero``.
    """
    try:
        program = parse_program(expression)
    except DpmXlSyntaxError as error:
        return f"syntax error: {error.message}"
    try:
        result = Evaluator(report()).run(program).result
    except UnsupportedError as error:
        return f"unsupported: {error}"
    except EvaluationError as error:
        return f"error: {error}"
    if not result.keys:
        record = result.single()
        return show(record.value if record else None)
    if not result.records:
        return "no records"
    return "; ".join(
        ", ".join(
            f"{name}={part.isoformat() if isinstance(part, date) else part}"
            for name, part in zip(result.keys, key, strict=True)
        )
        + f": {show(record.value)}"
        for key, record in result.records.items()
    )


if __name__ == "__main__":  # pragma: no cover
    for argument in sys.argv[1:]:
        print(evaluate(argument))
