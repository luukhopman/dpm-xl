---
description: Evaluate rules on polars frames for reports with millions of open-table rows, falling back to the reference evaluator on ColumnarUnsupported.
---

# Evaluate large reports

Some EBA reports have open tables with millions of rows. The reference
evaluator builds one Python record per row, which takes seconds per rule at
that size. [`dpmxl.columnar`](../reference/api/columnar.md) evaluates the same
language with the same semantics on polars frames, in milliseconds per rule.
It needs the `columnar` extra:

```bash
pip install "dpm-xl[columnar]"
```

The columnar evaluator covers the constructs of almost every EBA rule. For
anything else it raises
[`ColumnarUnsupported`][dpmxl.columnar.ColumnarUnsupported], and you evaluate
that rule with the reference evaluator instead. The two evaluators agree;
the test suite checks them case by case.

## A frame provider

A [`FrameProvider`][dpmxl.columnar.FrameProvider] is a
[`DataProvider`][dpmxl.provider.DataProvider] whose `select_frame(query)`
returns a polars frame instead of a list of `DataPoint`s. The frame has one
row per selected data point, in the
[frame schema](../reference/api/columnar.md#dpmxl.columnar--frame-schema):

| Column | Type | Content |
| --- | --- | --- |
| `cell` | any | Opaque cell reference |
| `r`, `c`, `s` | text or null | Raw closed coordinates |
| `k:<code>` | text (may be categorical) | One per open key: text, canonical items (`category:code`) or ISO dates |
| `num` | `Decimal(38, 12)` | Numeric value |
| `thr` | `Decimal(38, 12)` | Its interval threshold, `0.5·10^-decimals` (0 when exact) |
| `txt` | text | Text, canonical item or ISO date value |
| `flag` | Boolean | Boolean value |

All four value columns are null for a cell with no fact, and a cell and
open-key combination appears at most once.

Here an open table of 20,000 counterparties, with amounts reported in whole
units:

```python
from decimal import Decimal

import polars as pl

from dpmxl.columnar import CELL, DEC, FLAG, NUM, THR, TXT

exposures = pl.DataFrame(
    {
        "counterparty": [f"LEI-{i:06d}" for i in range(20_000)],
        "amount": [Decimal(i % 1000 - 3) for i in range(20_000)],
    }
)


class ExposureFrames:
    """A frame provider over one open table, C_27.00, keyed by qCPI."""

    def select_frame(self, query):
        if query.table != "C_27.00":
            raise LookupError(f"unknown table {query.table}")
        return exposures.select(
            pl.concat_str(pl.lit("C_27.00/"), pl.col("counterparty")).alias(CELL),
            pl.lit(None, pl.String).alias("r"),
            pl.lit("0010").alias("c"),
            pl.lit(None, pl.String).alias("s"),
            pl.col("counterparty").alias("k:qCPI"),
            pl.col("amount").cast(DEC).alias(NUM),
            pl.lit(Decimal("0.5")).cast(DEC).alias(THR),  # decimals = 0
            pl.lit(None, pl.String).alias(TXT),
            pl.lit(None, pl.Boolean).alias(FLAG),
        )

    def table_reported(self, table):
        return table == "C_27.00"

    def parameter(self, name):
        return None
```

The query's selectors are applied by the evaluator, so `select_frame` may
return the whole table; filtering by `query.columns` first saves memory on
wide tables. [`value_columns`][dpmxl.columnar.value_columns] maps one Python
value to the four value columns, and
[`frame_from_points`][dpmxl.columnar.frame_from_points] builds a frame from
`DataPoint`s.

## Evaluate

[`evaluate_rule_columnar`][dpmxl.columnar.evaluate_rule_columnar] returns a
[`ColumnarResult`][dpmxl.columnar.ColumnarResult] with the status, the record
counts and the keys of the failing records. Share one
[`FrameCache`][dpmxl.columnar.FrameCache] across the rules of a report.

```python
from dpmxl.columnar import FrameCache, evaluate_rule_columnar

cache = FrameCache()
result = evaluate_rule_columnar("{tC_27.00, c0010} > 0", ExposureFrames(), cache=cache)
print(result.status, result.passed, result.failed, result.null)
print(result.failing_keys[:2])
print(result.failing_frame.height)
```

```text
failed 19920 80 0
[{'qCPI': 'LEI-000000'}, {'qCPI': 'LEI-000001'}]
80
```

`failing_keys` lists the first `max_failing_keys` (1,000 by default) failing
keys as dictionaries; `failing_frame` has all of them, one string column per
key. Statuses are the same five as the reference evaluator's.

## Fall back on `ColumnarUnsupported`

Statements and assignments, set operators such as `union`, analytic
functions, the `&` operator, functions other than the aggregates, `filter`,
`abs`, `isnull`, `nvl`, `match`, `len` and `min`/`max` (so `time_shift`,
`annualise`, `substr`, the mathematical and the date functions), typed
parameter, operation and table-group references, values that do not fit
`Decimal(38, 12)`, arithmetic that would overflow it, record-level errors
(a zero divisor or a type error, which the reference evaluator confines to
its record) and ordering items or text that may be an item all raise
`ColumnarUnsupported`. Catch it and evaluate the rule with
[`evaluate_rule`][dpmxl.evaluator.evaluate_rule], which needs `select`. A
provider can offer both: here `select` builds `DataPoint`s from the same
frame.

```python
from dpmxl import DataPoint, Number, SelectionCache, evaluate_rule, explain
from dpmxl.columnar import ColumnarUnsupported


class Exposures(ExposureFrames):
    """Both interfaces: frames for the columnar evaluator, points for the rest."""

    def select(self, query):
        if query.table != "C_27.00":
            raise LookupError(f"unknown table {query.table}")
        return [
            DataPoint(
                "C_27.00",
                column="0010",
                keys={"qCPI": lei},
                value=Number.of(amount, 0),
                ref=f"C_27.00/{lei}",
            )
            for lei, amount in exposures.iter_rows()
        ]

    def open_keys(self, table):
        return ("qCPI",) if table == "C_27.00" else ()


def run_rule(expression, provider, frames, points):
    """Evaluate on frames; fall back to the reference evaluator."""
    try:
        result = evaluate_rule_columnar(expression, provider, cache=frames)
    except ColumnarUnsupported as reason:
        result = evaluate_rule(expression, provider, cache=points, trace=False)
        return "reference", result.status, result.counts["failed"], str(reason)
    return "columnar", result.status, result.failed, None


provider, frames, points = Exposures(), FrameCache(), SelectionCache()
for expression in (
    "{tC_27.00, c0010} > -5",
    "total := sum({tC_27.00, c0010}); total > 0",
):
    print(run_rule(expression, provider, frames, points))
```

```text
('columnar', 'passed', 0, None)
('reference', 'passed', 0, 'Program')
```

The `ColumnarUnsupported` message names what the columnar evaluator lacks.
Log it if you want to know which rules take the slower path.

## Explain the failures

A `ColumnarResult` carries no trace, so explanations come from the reference
evaluator. Evaluate only the rules that failed again with `evaluate_rule`
(on a large table this takes as long as any reference evaluation, so cap the
number of explanations you show):

```python
expression = "{tC_27.00, c0010} > 0"
traced = evaluate_rule(expression, provider, cache=points)
for outcome in traced.failures[:3]:
    print(
        outcome.key["qCPI"], explain(traced.evaluation, expression, outcome.key).summary
    )
```

```text
LEI-000000 -3 should exceed 0: difference 3
LEI-000001 -2 should exceed 0: difference 2
LEI-000002 -1 should exceed 0: difference 1
```

## Precision

Columnar values are `Decimal(38, 12)`: sums and differences are exact,
products and quotients round to 12 decimals (thresholds of quotients round
up), where the reference evaluator keeps 34 significant digits. An exact
comparison that hinges on the 13th decimal can therefore differ; values that
do not fit `Decimal(38, 12)` raise `ColumnarUnsupported` rather than being
rounded.

## Any `DataProvider` as frames

[`PointsFrameProvider`][dpmxl.columnar.PointsFrameProvider] adapts any
`DataProvider`, which is the quickest way to try the columnar evaluator on
existing data. It converts each selection's `DataPoint`s, so the speed-up is
smaller than with frames built directly from your storage:

```python
from dpmxl.columnar import PointsFrameProvider

print(
    evaluate_rule_columnar(
        "{tC_27.00, c0010} > 0", PointsFrameProvider(provider)
    ).failed
)
```

```text
80
```

## Threads

`evaluate_rule_columnar` may run concurrently on one report, and polars
releases the GIL, so threads speed up a rule run on several cores. A shared
`FrameCache` builds each selection once while other threads wait for it,
within its row budget (`FrameCache(max_rows=20_000_000)`, least recently used
selections evicted first). See [Run rules in threads](threads.md).
