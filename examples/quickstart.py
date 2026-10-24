"""Evaluate one EBA-style validation rule against in-memory data.

Run with ``python examples/quickstart.py``.
"""

from dpmxl import MemoryProvider, Number, TableLayout, evaluate_rule, explain

# The layout of table C_01.00: three rows and two columns.
layout = TableLayout("C_01.00", rows=("0010", "0020", "0030"), columns=("0010", "0020"))

# Reported values, keyed by (table, row, column, sheet, open keys). Number.of
# takes the XBRL decimals, so 1204 reported in units is 1204 ± 0.5.
values = {
    ("C_01.00", "0010", "0010", None, ()): Number.of(100, 0),
    ("C_01.00", "0020", "0010", None, ()): Number.of(60, 0),
    ("C_01.00", "0030", "0010", None, ()): Number.of(40, 0),
    ("C_01.00", "0010", "0020", None, ()): Number.of(1204, 0),
    ("C_01.00", "0020", "0020", None, ()): Number.of(1180, 0),
    ("C_01.00", "0030", "0020", None, ()): Number.of(31, 0),
}
provider = MemoryProvider([layout], values)

# Row 0010 must be the sum of rows 0020 and 0030, in every column.
expression = (
    "with {tC_01.00, c*, default: 0, interval: true}: {r0010} = {r0020} + {r0030}"
)
result = evaluate_rule(expression, provider, precondition="{v_C_01.00}")

print(result.status, result.counts)
for outcome in result.failures:
    explanation = explain(result.evaluation, expression, outcome.key)
    print(outcome.key, explanation.summary)
