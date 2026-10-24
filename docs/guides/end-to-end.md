---
description: Read an xBRL-CSV report with dpm-xbrl, bind its facts to a dpm-xl provider, evaluate rules with the columnar engine and the reference fallback, and explain the failures.
---

# From an XBRL report to explained failures

dpm-xl evaluates rules but reads no files;
[dpm-xbrl](https://luukhopman.github.io/dpm-xbrl/) reads xBRL-CSV and
XBRL-XML reports but evaluates no rules. This guide connects the two: it
reads an EBA-style xBRL-CSV report, binds its facts to table cells, evaluates
validation rules with the columnar engine (falling back to the reference
evaluator where needed) and explains every failure.

```bash
pip install dpm-xbrl "dpm-xl[columnar]"
```

The report is a small leverage-ratio package in the repository,
[`examples/xbrl-report/`](https://github.com/luukhopman/dpm-xl/tree/main/examples/xbrl-report):
a closed table `C_47.00` and an open table `C_48.02` keyed by counterparty
(`qRDT`). Run the code from a checkout of the repository, or point
`read_report` at your own report.

## 1. Read the report

```python
from dpmxbrl import read_report

report = read_report("examples/xbrl-report")
print(report.format, report.entity_id, report.reference_date)
print(report.filing_indicators)
print(report.decimals_parameters)
for fact in report.facts[:3]:
    print(fact.template, fact.datapoint, dict(fact.keys), fact.value, fact.location)
```

```text
xbrl-csv SYNTHETICDPMXL000002.CON 2026-03-31
{'C_47.00': True, 'C_48.02': True, 'C_43.00': False}
{'decimalsMonetary': -3, 'decimalsPercentage': 4}
c_47.00 dp9001 {} 812000 reports/c_47.00.csv:2
c_47.00 dp9002 {} 190000 reports/c_47.00.csv:3
c_47.00 dp9003 {} 40000 reports/c_47.00.csv:4
```

An EBA xBRL-CSV report holds facts by *datapoint* code (`dp9001`), with the
key columns of open tables in `fact.keys`. Values are text as written; the
precision of numbers comes from the report's `decimals*` parameters by data
type. See the [dpm-xbrl documentation](https://luukhopman.github.io/dpm-xbrl/)
for the fact model, XBRL-XML and the EBA filing rules it checks.

## 2. Map datapoints to cells

DPM-XL rules address cells by table, row and column, so each datapoint needs
its position. In production that mapping comes from the DPM release (the
table layouts of the taxonomy or the DPM database). For this example it is
written out:

```python
# datapoint -> (table, row, column, data type); open tables have no row.
DATAPOINTS = {
    "dp9001": ("C_47.00", "0010", "0010", "monetary"),  # exposure component
    "dp9002": ("C_47.00", "0020", "0010", "monetary"),  # exposure component
    "dp9003": ("C_47.00", "0030", "0010", "monetary"),  # exposure component
    "dp9004": ("C_47.00", "0040", "0010", "monetary"),  # total exposure
    "dp9005": ("C_47.00", "0050", "0010", "monetary"),  # tier 1 capital
    "dp9006": ("C_47.00", "0060", "0010", "percentage"),  # leverage ratio
    "dp9101": ("C_48.02", None, "0010", "monetary"),  # exposure
    "dp9102": ("C_48.02", None, "0020", "string"),  # counterparty LEI
}
OPEN_KEYS = {"C_48.02": ("qRDT",)}  # key columns of the open tables
DECIMALS = {"monetary": "decimalsMonetary", "percentage": "decimalsPercentage"}
```

## 3. Bind the facts to a provider

A [provider](provider.md) answers the evaluator's questions from the report:
the cells of a selection, the filing indicators and the report parameters.
Two things matter. A closed selection returns **every defined cell**, with
`value=None` where nothing was reported, so `default` and `isnull` work.
And numbers carry their reported precision: `Number.of(text, decimals)`.

```python
from collections import defaultdict

from dpmxl import CellQuery, DataPoint, Number, axis_matcher


class XbrlReportProvider:
    """A dpm-xl DataProvider over a dpm-xbrl Report."""

    def __init__(self, report, datapoints, open_keys):
        self.report = report
        self.open_keys_by_table = open_keys
        self.cells = defaultdict(list)  # closed table -> [(row, column)]
        self.columns = defaultdict(set)  # open table -> {column}
        for table, row, column, _ in datapoints.values():
            if table in open_keys:
                self.columns[table].add(column)
            else:
                self.cells[table].append((row, column))
        self.values = {}  # (table, row, column, keys) -> value
        self.rows = defaultdict(dict)  # open table -> {keys: None}, in report order
        for fact in report.facts:
            if fact.datapoint not in datapoints:
                continue
            table, row, column, kind = datapoints[fact.datapoint]
            keys = tuple((name, fact.keys[name]) for name in open_keys.get(table, ()))
            self.values[table, row, column, keys] = self._value(fact.value, kind)
            if keys:
                self.rows[table][keys] = None

    def _value(self, text, kind):
        if text is None or kind == "string":
            return text
        return Number.of(text, self.report.decimals_parameters.get(DECIMALS[kind]))

    def select(self, query):
        rows, columns = axis_matcher(query.rows), axis_matcher(query.columns)
        if query.table in self.cells:
            return [
                DataPoint(
                    query.table,
                    row=row,
                    column=column,
                    value=self.values.get((query.table, row, column, ())),
                    ref=f"{query.table}/r{row}/c{column}",
                )
                for row, column in self.cells[query.table]
                if rows(row) and columns(column)
            ]
        if query.table in self.columns:
            return [
                DataPoint(
                    query.table,
                    column=column,
                    keys=dict(keys),
                    value=self.values.get((query.table, None, column, keys)),
                    ref=f"{query.table}/c{column}/{keys[0][1]}",
                )
                for keys in self.rows[query.table]
                for column in sorted(self.columns[query.table])
                if columns(column)
            ]
        raise LookupError(f"unknown table {query.table}")

    def open_keys(self, table):
        return self.open_keys_by_table.get(table, ())

    def table_reported(self, table):
        return self.report.filing_indicators.get(table)

    def parameter(self, name):
        return self.report.parameters.get(name)


provider = XbrlReportProvider(report, DATAPOINTS, OPEN_KEYS)
print(provider.select(CellQuery("C_47.00", rows=None, columns=None))[3])
```

```text
DataPoint(table='C_47.00', row='0040', column='0010', sheet=None, keys={}, value=Number(value=Decimal('1045000'), tolerance=Decimal('5E+2')), ref='C_47.00/r0040/c0010')
```

The total exposure was reported with `decimalsMonetary = -3`, rounded to
thousands, so it stands for 1,045,000 ± 500.

## 4. Evaluate with the columnar engine and fall back

[`PointsFrameProvider`][dpmxl.columnar.PointsFrameProvider] presents the
same provider as polars frames. Each rule runs on the columnar engine first;
when it raises [`ColumnarUnsupported`][dpmxl.columnar.ColumnarUnsupported],
the reference evaluator takes over. Both share a cache per report.

```python
from dpmxl import SelectionCache, evaluate_rule
from dpmxl.columnar import (
    ColumnarUnsupported,
    FrameCache,
    PointsFrameProvider,
    evaluate_rule_columnar,
)

RULES = [
    (
        "e0001",
        "with {tC_47.00, c0010, default: 0, interval: true}: {r0040} = {r0010} + {r0020} + {r0030}",
        "{v_C_47.00}",
    ),
    (
        "e0002",
        "with {tC_47.00, c0010, interval: true}: {r0060} = {r0050} / {r0040}",
        "{v_C_47.00}",
    ),
    ("e0003", "{tC_48.02, c0010} >= 0", "{v_C_48.02}"),
    ("e0004", 'match({tC_48.02, c0020}, "[A-Z0-9]{18}[0-9]{2}")', "{v_C_48.02}"),
    ("e0005", "{tC_43.00, r0010, c0010} > 0", "{v_C_43.00}"),
    (
        "e0006",
        "total := sum({tC_48.02, c0010}); total <= {tC_47.00, r0040, c0010}",
        None,
    ),
]

frames, frame_cache, cache = (
    PointsFrameProvider(provider),
    FrameCache(),
    SelectionCache(),
)
statuses = {}
for code, expression, precondition in RULES:
    try:
        result = evaluate_rule_columnar(
            expression, frames, precondition=precondition, cache=frame_cache
        )
        engine, status = "columnar", result.status
    except ColumnarUnsupported:
        result = evaluate_rule(
            expression, provider, precondition=precondition, cache=cache, trace=False
        )
        engine, status = "reference", result.status
    statuses[code] = status
    print(f"{code}: {status:15} ({engine})")
```

```text
e0001: failed          (columnar)
e0002: passed          (columnar)
e0003: failed          (columnar)
e0004: failed          (columnar)
e0005: not_applicable  (columnar)
e0006: passed          (reference)
```

`e0006` is a script with a temporary assignment (`total := …`), which the
columnar engine leaves to the reference evaluator. `e0005` does not apply:
its precondition tests `C_43.00`, which the report's filing indicators mark
as not reported.

## 5. Explain the failures

The columnar result has the failing keys but no trace, so evaluate the
failed rules again with [`evaluate_rule`][dpmxl.evaluator.evaluate_rule] and
explain each failing record. Its points carry the provider's `ref`s, which
lead back to the cells, and through the mapping to the report's datapoints
and file locations.

```python
from dpmxl import explain

for code, expression, precondition in RULES:
    if statuses[code] != "failed":
        continue
    result = evaluate_rule(expression, provider, precondition=precondition, cache=cache)
    for outcome in result.failures:
        explanation = explain(result.evaluation, expression, outcome.key)
        print(f"{code} {dict(outcome.key)}: {explanation.summary}")
        print("    cells:", ", ".join(str(point.ref) for point in explanation.primary))
```

```text
e0001 {}: 1,045,000 should equal 1,042,000 (812,000 + 190,000 + 40,000): difference 3,000, at least 1,000 given the reported precision
    cells: C_47.00/r0040/c0010
e0003 {'qRDT': 'QW4KNDKKV7QH2LA40639'}: -12,000 should be at least 0: difference 12,000
    cells: C_48.02/c0010/QW4KNDKKV7QH2LA40639
e0004 {'qRDT': 'QW4KNDKKV7QH2LA40639'}: "QW4KNDKKV7QH2LA4063" does not have the required format
    cells: C_48.02/c0020/QW4KNDKKV7QH2LA40639
```

The total exposure is 3,000 above the sum of its components. Four amounts
rounded to thousands could explain up to 2,000 of that; at least 1,000
cannot. The leverage ratio rule `e0002` passed because 52,000 / 1,045,000 is
within the precision of the reported 4.98 %.

## In production

- **Mapping.** Build `DATAPOINTS` from the DPM release the report's entry
  point names, once per release, rather than by hand.
- **Large reports.** For open tables with millions of rows, build polars
  frames directly from dpm-xbrl's columnar reader
  (`dpmxbrl.frames.read_xbrl_csv_frames`) in the
  [frame schema](../reference/api/columnar.md#dpmxl.columnar--frame-schema) instead of going
  through `DataPoint`s; see [Evaluate large reports](columnar.md).
- **Filing rules first.** dpm-xbrl records the EBA filing rules a report
  breaks in `report.filing`; check them before evaluating validation rules.
- **Threads.** The provider above is read-only after construction, so rules
  can run on a thread pool ([Run rules in threads](threads.md)).
