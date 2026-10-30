---
description: Write a DataProvider for your own storage, including the optional open_keys, is_template, table_group, operation and earlier_report methods.
---

# Connect your data

The evaluator never reads report files. Everything it knows about a report
comes from a *provider*: an object with three methods, plus up to five
optional ones. This guide builds a provider over plain Python data, one
method at a time; replace the dictionaries with queries against your database,
a report loader or test fixtures.

## The contract

```python
from collections.abc import Sequence
from typing import Protocol

from dpmxl import CellQuery, DataPoint, Value


class DataProvider(Protocol):
    def select(self, query: CellQuery) -> Sequence[DataPoint]: ...
    def table_reported(self, table: str) -> bool | None: ...
    def parameter(self, name: str) -> Value: ...
```

| Method | Answers | Contract |
| --- | --- | --- |
| `select(query)` | Every selection `{tT, r…, c…, s…}` | Return **every defined cell** of the closed axes the query covers, with `value=None` where nothing was reported, so `default` and `isnull` work. For an open table, return one point per reported key combination with the key components in `DataPoint.keys`. Raise `LookupError` for an unknown table. |
| `table_reported(table)` | `{v_TABLE}` filing-indicator tests | `True` or `False`; `None` when the provider cannot tell. |
| `parameter(name)` | `{vName}` and `{p_Name, type}` | The report parameter, such as `refPeriod`, or `None` when unknown. |

| Optional method | Answers | Without it, or when it returns `None` |
| --- | --- | --- |
| `open_keys(table) -> Sequence[str]` | The key names of an open table | An open table with no reported rows yields a selection without keys. |
| `is_template(code) -> bool` | Whether `{vCode}` names a table or template | Only codes shaped like `C_01.00` are templates; other variables are parameters. |
| `table_group(code) -> Sequence[str] \| None` | `{g_Group, …}` table groups | The rule is `unsupported`. |
| `operation(code) -> str \| None` | `{o_Code, …}` operation references | The rule is `unsupported`. |
| `earlier_report(period, count) -> DataProvider \| None` | `time_shift` on another period's report | The rule is `unsupported`. |

The protocol is [`DataProvider`][dpmxl.provider.DataProvider]. It is
`runtime_checkable`, so `isinstance(provider, DataProvider)` checks the three
required methods.

## The data

Two tables: `C_02.00` is closed (fixed rows and columns), `C_27.00` is open
(one row per counterparty, keyed by `qCPI`). Row `0030` of `C_02.00` was not
reported.

```python
from dpmxl import Number

CLOSED = {"C_02.00": {"rows": ("0010", "0020", "0030"), "columns": ("0010",)}}
FACTS = {
    ("C_02.00", "0010", "0010"): Number.of("250.4", 1),
    ("C_02.00", "0020", "0010"): Number.of(-3, 0),
}
OPEN = {"C_27.00": {"columns": ("0010", "0020"), "keys": ("qCPI",)}}
ROWS = {
    "C_27.00": [
        {"qCPI": "LEI-A", "0010": Number.of(120, 0), "0020": "bank"},
        {"qCPI": "LEI-B", "0010": Number.of(-5, 0), "0020": "fund"},
    ]
}
```

Values are `Number` (use `Number.of(value, decimals)` for reported facts, with
the fact's XBRL `decimals`; `None` or `"INF"` means exact), `str`, `bool`,
`datetime.date`, [`Item`][dpmxl.ast.Item] (`Item.parse("eba_qEC:qx01")`),
[`ValueSet`][dpmxl.values.ValueSet] or `None`.

## Required methods

`select` receives a [`CellQuery`][dpmxl.provider.CellQuery]: the table code
and the row, column and sheet selectors, each `None` when the rule does not
restrict that axis. [`axis_matcher`][dpmxl.provider.axis_matcher] compiles a
selector into a fast callable that handles single codes, ranges (`r0010-0050`),
lists and wildcards, and compares codes the way DPM does
([`normalize_code`][dpmxl.provider.normalize_code]: `r310` matches `0310`).

```python
from collections.abc import Sequence

from dpmxl import CellQuery, DataPoint, Value, axis_matcher


class DictProvider:
    """A DataProvider over CLOSED, FACTS, OPEN and ROWS."""

    def __init__(self, rows=ROWS, reported=("C_02.00", "C_27.00")):
        self.rows = rows
        self.reported = set(reported)

    def select(self, query: CellQuery) -> Sequence[DataPoint]:
        rows, columns = axis_matcher(query.rows), axis_matcher(query.columns)
        if query.table in CLOSED:
            layout = CLOSED[query.table]
            return [  # every defined cell, reported or not
                DataPoint(
                    query.table,
                    row=row,
                    column=column,
                    value=FACTS.get((query.table, row, column)),
                    ref=f"{query.table}/{row}/{column}",
                )
                for row in layout["rows"]
                if rows(row)
                for column in layout["columns"]
                if columns(column)
            ]
        if query.table in OPEN:
            layout = OPEN[query.table]
            return [  # one point per reported key combination and column
                DataPoint(
                    query.table,
                    column=column,
                    keys={key: record[key] for key in layout["keys"]},
                    value=record.get(column),
                    ref=f"{query.table}/{record['qCPI']}/{column}",
                )
                for record in self.rows.get(query.table, [])
                for column in layout["columns"]
                if columns(column)
            ]
        raise LookupError(f"unknown table {query.table}")

    def table_reported(self, table: str) -> bool | None:
        return table in self.reported

    def parameter(self, name: str) -> Value:
        return {"refPeriod": "2026-12-31"}.get(name)
```

`DataPoint.ref` is whatever identity you give the cell (a database id, a
location in the report file); it comes back in every outcome so a user
interface can highlight the cell. It must be hashable.

```python
from dpmxl import DataProvider, evaluate_rule, explain

provider = DictProvider()
print(isinstance(provider, DataProvider))

for expression in (
    "{tC_02.00, c0010} >= 0",
    "{tC_27.00, c0010} > 0",
    '{tC_27.00, c0020} = "bank"',
    "{tC_99.00, c0010} > 0",
):
    result = evaluate_rule(expression, provider)
    print(expression, "->", result.status, result.counts, result.message or "")
    for outcome in result.failures:
        cells = [point.ref for point in outcome.points]
        print(
            "  ",
            outcome.key,
            cells,
            explain(result.evaluation, expression, outcome.key).summary,
        )
```

```text
True
{tC_02.00, c0010} >= 0 -> failed {'passed': 1, 'failed': 1, 'null': 1}
   {'r': '0020'} ['C_02.00/0020/0010'] -3 should be at least 0: difference 3
{tC_27.00, c0010} > 0 -> failed {'passed': 1, 'failed': 1, 'null': 0}
   {'qCPI': 'LEI-B'} ['C_27.00/LEI-B/0010'] -5 should exceed 0: difference 5
{tC_27.00, c0020} = "bank" -> failed {'passed': 1, 'failed': 1, 'null': 0}
   {'qCPI': 'LEI-B'} ['C_27.00/LEI-B/0020'] "fund" should equal "bank"
{tC_99.00, c0010} > 0 -> error {'passed': 0, 'failed': 0, 'null': 0} unknown table C_99.00
```

Row `0030` was not reported, so its record is null ("not evaluated") rather
than a failure; with `default: 0` in the selection it would be compared as 0.
That only works because `select` returned the unreported cell with
`value=None`. The unknown table became the status `error` with the
`LookupError` message.

!!! warning "Return unreported cells"
    A provider that returns only reported facts for a closed table silently
    turns "missing" into "absent": `default` never applies, `isnull` never
    sees the cell and presence checks such as
    `if not isnull({r0010}) then not isnull({r0030}) endif` pass when they
    should fail.

## `open_keys`: the keys of an empty open table

When an open table has no reported rows, `select` returns nothing, and the
evaluator cannot know that the selection is keyed by `qCPI`. A rule that
groups by that key is then an error:

```python
empty = DictProvider(rows={})
expression = "sum({tC_27.00, c0010} group by qCPI) > 0"
result = evaluate_rule(expression, empty)
print(result.status, result.message)
```

```text
error group by 'qCPI' is not a key of the operand (no keys)
```

`open_keys(table)` names the key components, so the empty selection keeps the
table's key structure, as the specification requires:

```python
class KeyedProvider(DictProvider):
    def open_keys(self, table: str) -> Sequence[str]:
        return OPEN.get(table, {}).get("keys", ())


result = evaluate_rule(expression, KeyedProvider(rows={}))
print(result.status, result.counts)
```

```text
not_applicable {'passed': 0, 'failed': 0, 'null': 0}
```

## `table_group`: `{g_…}` selections

A table group selects the same cells from several tables. `table_group(code)`
returns the group's table codes, or `None` for an unknown group. With several
tables, records are keyed by the table code `t`, and the tables must share
their keys.

```python
CLOSED["C_02.01"] = {"rows": ("0010",), "columns": ("0010",)}
FACTS["C_02.01", "0010", "0010"] = Number.of(7, 0)


class GroupProvider(KeyedProvider):
    def table_group(self, code: str) -> Sequence[str] | None:
        return {"G_02": ("C_02.00", "C_02.01")}.get(code)


result = evaluate_rule("{g_G_02, r0010, c0010} > 0", GroupProvider())
print(result.status, [outcome.key for outcome in result.outcomes])
print(evaluate_rule("{g_G_02, r0010, c0010} > 0", KeyedProvider()).message)
```

```text
passed [{'t': 'C_02.00'}, {'t': 'C_02.01'}]
table group G_02 needs a provider that resolves table groups
```

## `operation`: `{o_…}` references

An operation reference evaluates another rule's expression. `operation(code)`
returns that expression's text, or `None` for an unknown operation. The
expression is evaluated on its own: the referring rule's context, temporaries
and assignments do not reach it. Axes on the reference keep the matching
records, `default` fills nulls and `interval: false` makes numbers exact. An
operation that refers to itself is an error.

```python
class OperationProvider(KeyedProvider):
    def operation(self, code: str) -> str | None:
        return {"v1000_a": "{tC_02.00, c0010} * 2"}.get(code)


expression = "{o_v1000_a, r0010} > 600"
result = evaluate_rule(expression, OperationProvider())
outcome = result.failures[0]
print(result.status, [point.ref for point in outcome.points])
print(explain(result.evaluation, expression, outcome.key).summary)
```

```text
failed ['C_02.00/0010/0010']
500.8 should exceed 600: difference 99.2
```

## `earlier_report`: `time_shift` across periods

`time_shift(x, Q, 1, refPeriod)` compares with the report one quarter
earlier. `earlier_report(period, count)` returns that report as another
provider, or `None` when you do not have it; `period` is `A`, `S`, `Q`, `M`,
`W` or `D`, and `count` is positive for earlier and negative for later
reports.

```python
from dataclasses import replace


class PreviousQuarter(KeyedProvider):
    """The same report one quarter earlier, with C_02.00 r0010 at 240."""

    def select(self, query):
        return [
            replace(point, value=Number.of(240, 0)) if point.row == "0010" else point
            for point in super().select(query)
        ]


class TimeProvider(KeyedProvider):
    def earlier_report(self, period: str, count: int):
        return PreviousQuarter() if (period, count) == ("Q", 1) else None


expression = (
    "{tC_02.00, r0010, c0010} <= time_shift({tC_02.00, r0010, c0010}, Q, 1) * 1.01"
)
result = evaluate_rule(expression, TimeProvider())
outcome = result.failures[0]
print([point.ref for point in outcome.points])
print(explain(result.evaluation, expression, outcome.key).summary)

shifted_year = "{tC_02.00, r0010, c0010} >= time_shift({tC_02.00, r0010, c0010}, A, 1)"
print(evaluate_rule(shifted_year, TimeProvider()).message)
```

```text
['C_02.00/0010/0010', EarlierRef(period='Q', count=1, ref='C_02.00/0010/0010')]
250.4 should not exceed 242.4 (time_shift(240, Q, 1) × 1.01): difference 8
time_shift needs the report 1 year(s) earlier, which the provider does not have
```

Points read from the earlier report carry
[`EarlierRef(period, count, ref)`][dpmxl.provider.EarlierRef] as their `ref`,
so they stay distinct from the current report's cell with the same `ref`.
[Compare with earlier reports](time-shift.md) covers `time_shift` in depth.

## `MemoryProvider`

[`MemoryProvider`][dpmxl.provider.MemoryProvider] implements all of the above
for data you can hold in memory. Its values are keyed by
`(table, row, column, sheet, keys)`, where `keys` is a tuple of
`(name, value)` pairs for open tables and `()` for closed ones; the optional
hooks take `table_groups`, `operations` and `earlier_reports` mappings:

```python
from dpmxl import MemoryProvider, TableLayout

memory = MemoryProvider(
    [
        TableLayout("C_02.00", rows=("0010", "0020"), columns=("0010",)),
        TableLayout("C_27.00", columns=("0010",), open_keys=("qCPI",)),
    ],
    {
        ("C_02.00", "0010", "0010", None, ()): Number.of(250, 0),
        ("C_27.00", None, "0010", None, (("qCPI", "LEI-A"),)): Number.of(120, 0),
    },
    reported=["C_02.00", "C_27.00"],
    parameters={"refPeriod": "2026-12-31"},
    table_groups={"G_02": ["C_02.00"]},
    operations={"v1000_a": "{tC_02.00, c0010} * 2"},
    earlier_reports={("Q", 1): MemoryProvider([], {})},
)
print(evaluate_rule("{tC_27.00, c0010} > 0", memory).status)
```

```text
passed
```

`reported` defaults to every table that has a value; a `TableLayout` with a
`template` code also answers `{v_TEMPLATE}` for that template.

## Performance and threads

- To evaluate many rules against one report, pass one
  [`SelectionCache`][dpmxl.evaluator.SelectionCache] per report
  (`evaluate_rule(..., cache=cache)`) so each selection is read once.
- `select` is called once per distinct selection, so a provider over a
  database should fetch a table's cells in one query.
- A provider shared across threads must be safe to read concurrently;
  `MemoryProvider` is. See [Run rules in threads](threads.md).
- For reports with millions of open-table rows, a columnar provider returns
  polars frames instead of `DataPoint`s; see
  [Evaluate large reports](columnar.md).

The repository's
[`examples/custom_provider.py`](https://github.com/luukhopman/dpm-xl/blob/main/examples/custom_provider.py)
is a complete provider in 40 lines.
