"""Serve report data to the evaluator from your own storage.

The evaluator asks a provider three things: the data points of a selection,
whether a table was reported, and the value of a report parameter. This
provider answers from a list of facts, as a loader for a database or a report
file would. Run with ``python examples/custom_provider.py``.
"""

from collections.abc import Sequence

from dpmxl import (
    CellQuery,
    DataPoint,
    Number,
    Value,
    axis_matcher,
    evaluate_rule,
    explain,
)

# Closed table C_02.00: every defined cell, reported or not.
CELLS = {"C_02.00": [("0010", "0010"), ("0020", "0010"), ("0030", "0010")]}
FACTS = {
    ("C_02.00", "0010", "0010"): Number.of("250.4", 1),
    ("C_02.00", "0020", "0010"): Number.of("-3", 0),
    # r0030 is not reported.
}
# Open table C_27.00: one row per reported counterparty (key qCPI).
OPEN_ROWS = [
    {"qCPI": "LEI-A", "c0010": Number.of(120, 0)},
    {"qCPI": "LEI-B", "c0010": Number.of(-5, 0)},
]


class FactProvider:
    """A DataProvider over the facts above."""

    def select(self, query: CellQuery) -> Sequence[DataPoint]:
        """Every defined cell a selection covers, with None where unreported."""
        rows, columns = axis_matcher(query.rows), axis_matcher(query.columns)
        if query.table == "C_27.00":
            return [
                DataPoint(
                    "C_27.00",
                    column="0010",
                    keys={"qCPI": row["qCPI"]},
                    value=row["c0010"],
                    ref=f"C_27.00/{row['qCPI']}",
                )
                for row in OPEN_ROWS
                if columns("0010")
            ]
        if query.table not in CELLS:
            raise LookupError(f"unknown table {query.table}")
        return [
            DataPoint(
                query.table,
                row=row,
                column=column,
                value=FACTS.get((query.table, row, column)),
                ref=f"{query.table}/{row}/{column}",
            )
            for row, column in CELLS[query.table]
            if rows(row) and columns(column)
        ]

    def table_reported(self, table: str) -> bool | None:
        """The filing indicator of a table, for {v_TABLE} preconditions."""
        return table in {"C_02.00", "C_27.00"}

    def parameter(self, name: str) -> Value:
        """A report parameter such as refPeriod, for {vName}."""
        return None

    def open_keys(self, table: str) -> Sequence[str]:
        """Optional: the key names of an open table."""
        return ("qCPI",) if table == "C_27.00" else ()


provider = FactProvider()
rules = {
    "non-negative amounts": "{tC_02.00, (r0010, r0020), c0010} >= 0",
    "reported when total is": "if not isnull({tC_02.00, r0010, c0010}) "
    "then not isnull({tC_02.00, r0030, c0010}) endif",
    "exposures are positive": "{tC_27.00, c0010} > 0",
}
for name, expression in rules.items():
    result = evaluate_rule(expression, provider)
    print(f"{name}: {result.status}", result.message or "")
    for outcome in result.failures:
        cells = ", ".join(str(point.ref) for point in outcome.points)
        summary = explain(result.evaluation, expression, outcome.key).summary
        print(f"  {cells}: {summary}")
