---
description: Aggregates with group by, and analytic functions (rank and windowed aggregates) with partitions, ordering and windows.
---

# Aggregates and analytic functions

## Aggregates

`sum`, `count`, `avg`, `min`, `max` and `median` (also spelled `min_aggr`
and `max_aggr`, as in the specification) reduce an operand's records to one
value, or to one value per group with `group by`:

```dpm-xl
sum({tC_27.00, c0010}) <= {tC_01.00, r0010, c0010}
sum({tC_27.00, c0010} group by qCPI) >= 0
```

- Over no records they are null, except `count`, which is 0.
- `count` counts non-null values; the others skip nulls.
- `max` and `min` also order dates, text and items by their text (ISO dates
  in date order, items by category and code), as presence checks expect.
  Booleans, and numbers mixed with other values in one group, are an error.
- With several operands, `min(a, b)` and `max(a, b)` are scalar functions
  that pick per record.

## Analytic functions

An analytic function keeps the operand's records: each record gets the
aggregate of the records in its *window* (or its rank) within its
*partition*.

```dpm-xl
with {tC_08.02}: rank({c0010} over (partition by qEEA order by qEEA desc)) > 0
with {tC_08.02}: sum({c0010} over (order by qEEA data points between unbounded preceding and current data point)) > 0
```

The examples below use an open table keyed by entity `qEBB` and date `qDAT`:

```python
from datetime import date

from dpmxl import MemoryProvider, Number, TableLayout, evaluate_rule

facts = [
    ("A", date(2026, 1, 31), 5),
    ("A", date(2026, 2, 28), 7),
    ("A", date(2026, 3, 31), 3),
    ("B", date(2026, 1, 31), -1),
    ("B", date(2026, 2, 28), 4),
    ("B", date(2026, 3, 31), 4),
]
provider = MemoryProvider(
    [TableLayout("O", columns=("0010",), open_keys=("qEBB", "qDAT"))],
    {
        ("O", None, "0010", None, (("qEBB", entity), ("qDAT", day))): Number.of(
            amount, 0
        )
        for entity, day, amount in facts
    },
)


def show(expression):
    result = evaluate_rule(expression, provider)
    for outcome in result.outcomes:
        print(outcome.key["qEBB"], outcome.key["qDAT"], outcome.passed)
```

A running total per entity, in date order:

```python
show("with {tO}: sum({c0010} over (partition by qEBB order by qDAT)) > 0")
```

```text
A 2026-01-31 True
A 2026-02-28 True
A 2026-03-31 True
B 2026-01-31 False
B 2026-02-28 True
B 2026-03-31 True
```

The average of each month and the month before:

```python
show(
    "with {tO}: avg({c0010} over (partition by qEBB order by qDAT data points between 1 preceding and current data point)) >= 3"
)
```

```text
A 2026-01-31 True
A 2026-02-28 True
A 2026-03-31 True
B 2026-01-31 False
B 2026-02-28 False
B 2026-03-31 True
```

## Partitions, order and windows

- **Partition and order keys** must be keys of the operand. Without
  `partition by` the whole operand is one partition.
- **`rank`** needs `order by` and ranks by those keys; ties share the lowest
  rank and leave gaps (1, 1, 3).
- **Default window.** Without a window clause the window is the whole
  partition, or, with `order by`, every record up to the current one and its
  *peers*, the records with the same values for every order key (`range
  between unbounded preceding and current data point`).
- **`data points` windows** count records: `between 2 preceding and current
  data point` is the current record and the two before it.
- **`range` windows** with an offset need a single number or date order key:
  `3 preceding` is 3 less (3 days earlier for a date), `3 M preceding` three
  calendar months earlier. A period on a number key is an error.
- **Bounds** are `unbounded preceding`, `unbounded following`, `current data
  point`, and `n [A|S|Q|M|W|D] preceding|following`. `preceding` follows the
  sort direction.

Analytic calls parse to [`Analytic`][dpmxl.ast.Analytic] nodes with a
[`Window`][dpmxl.ast.Window], not to `Call`s, and `rank` is not in
`evaluator.AGGREGATES`. The columnar evaluator hands analytic functions to the
reference evaluator.
