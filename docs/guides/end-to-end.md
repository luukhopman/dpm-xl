---
description: Check an xBRL-CSV report with dpm-xl check-report, or in Python - read it with dpm-xbrl, place its facts with a module file and the shipped ReportProvider, evaluate rules with the columnar engine and the reference fallback, and explain the failures.
---

# Check an XBRL report

dpm-xl evaluates rules but reads no files;
[dpm-xbrl](https://luukhopman.github.io/dpm-xbrl/) reads xBRL-CSV and
XBRL-XML reports but evaluates no rules. The `xbrl` extra connects the two:
a [module file](../reference/module-file.md) places each datapoint of the
report in a table cell, and [`ReportProvider`][dpmxl.xbrl.ReportProvider]
answers the evaluator from the report.

```bash
pip install "dpm-xl[xbrl,columnar]"
```

The report is a small leverage-ratio package in the repository,
[`examples/xbrl-report/`](https://github.com/luukhopman/dpm-xl/tree/main/examples/xbrl-report):
a closed table `C_47.00` and an open table `C_48.02` keyed by counterparty
(`qRDT`). Its module file is
[`examples/xbrl-module.json`](https://github.com/luukhopman/dpm-xl/blob/main/examples/xbrl-module.json).
Run the commands from a checkout of the repository, or point them at your
own report and module file.

## On the command line

`dpm-xl check-report` checks the report's filing rules and evaluates the
module's validation rules. `e0007` compares with the previous quarter, so
pass that report too:

```console
$ dpm-xl check-report examples/xbrl-module.json examples/xbrl-report --previous examples/xbrl-report-previous
report: examples/xbrl-report (xbrl-csv); module COREP_LR, release 4.2
previous: examples/xbrl-report-previous (2025-12-31)
warning: reports/report.json: 1 extended metadata document could not be resolved offline (http://www.eba.europa.eu/eu/fr/xbrl/crr/fws/corep/4.2/mod/corep_lr.json); tables without resolved metadata use the EBA datapoint/factValue convention
filing rules broken: 0 errors, 0 warnings
e0001: failed
  records: 0 passed, 1 failed, 0 null
  - scalar: 1,045,000 should equal 1,042,000 (812,000 + 190,000 + 40,000): difference 3,000, at least 1,000 given the reported precision
e0003: failed
  records: 1 passed, 1 failed, 0 null
  - qRDT=QW4KNDKKV7QH2LA40639: -12,000 should be at least 0: difference 12,000
e0004: failed (warning)
  records: 1 passed, 1 failed, 0 null
  - qRDT=QW4KNDKKV7QH2LA40639: "QW4KNDKKV7QH2LA4063" does not have the required format
e0007: failed (warning)
  records: 0 passed, 1 failed, 0 null
  - scalar: 1,045,000 should be at least 1,062,000 (0.9 × time_shift(1,180,000, Q, 1, refPeriod)): difference 17,000
7 rules: 4 failed, 2 passed, 1 not_applicable (3 not listed; --all lists every rule)
$ echo $?
1
```

The warning means the EBA taxonomy was not available offline; the report
is still read, and
[`--taxonomy-package`](../reference/cli.md#dpm-xl-check-report) resolves it.
Only rules that failed, are an error or are unsupported are listed, and
the run fails because `error` rules failed; failing `warning` rules, such
as `e0004`, fail it only with `--fail-on warning`. `--format junit` writes
the results as a JUnit XML report for CI.

## In Python

The rest of this guide does the same step by step: read the report,
evaluate its module's rules with the columnar engine (falling back to the
reference evaluator where needed) and explain every failure.

### 1. Read the report

```python
from dpmxbrl import read_report

report = read_report("examples/xbrl-report")
print(report.format, report.entity_id, report.reference_date)
print(report.filing_indicators)
print(report.decimals_parameters)
for fact in report.facts[:3]:
    print(fact.datapoint, dict(fact.keys), fact.value, fact.location)
```

```text
xbrl-csv SYNTHETICDPMXL000002.CON 2026-03-31
{'C_47.00': True, 'C_48.02': True, 'C_43.00': False}
{'decimalsMonetary': -3, 'decimalsPercentage': 4}
dp9001 {} 812000 reports/c_47.00.csv:2
dp9002 {} 190000 reports/c_47.00.csv:3
dp9003 {} 40000 reports/c_47.00.csv:4
```

An EBA xBRL-CSV report holds facts by *datapoint* code (`dp9001`), with the
key columns of open tables in `fact.keys`. Values are text as written; the
precision of numbers comes from the report's `decimals*` parameters by data
type. See the [dpm-xbrl documentation](https://luukhopman.github.io/dpm-xbrl/)
for the fact model, XBRL-XML and the EBA filing rules it checks.

### 2. Place the facts with the module

DPM-XL rules address cells by table, row and column, so each datapoint needs
its position. The module file gives it: each cell names its row, column,
datapoint and data type, and each open table its keys. In production the
module file is exported from the DPM release the report's entry point
names, once per release.

```python
from dpmxl import CellQuery
from dpmxl.module import load_module
from dpmxl.xbrl import ReportProvider

module = load_module("examples/xbrl-module.json")
provider = ReportProvider(module, report)
print(provider.select(CellQuery("C_47.00"))[3])
print(provider.unplaced)
```

```text
DataPoint(table='C_47.00', row='0040', column='0010', sheet=None, keys={}, value=Number(value=Decimal('1045000'), tolerance=Decimal('5E+2')), ref=('C_47.00', 'C_47.00/r0040/c0010', ()))
()
```

A closed selection returns **every defined cell**, with `value=None` where
nothing was reported, so `default` and `isnull` work, and numbers carry
their reported precision: the total exposure was reported with
`decimalsMonetary = -3`, rounded to thousands, so it stands for
1,045,000 ± 500. `unplaced` lists the facts in no table of the module.

### 3. Evaluate with the columnar engine and fall back

[`PointsFrameProvider`][dpmxl.columnar.PointsFrameProvider] presents the
same provider as polars frames. Each rule of the module runs on the
columnar engine first; when it raises
[`ColumnarUnsupported`][dpmxl.columnar.ColumnarUnsupported], the reference
evaluator takes over. Both share a cache per report.

```python
from dpmxl import SelectionCache, evaluate_rule
from dpmxl.columnar import (
    ColumnarUnsupported,
    FrameCache,
    PointsFrameProvider,
    evaluate_rule_columnar,
)

frames, frame_cache, cache = (
    PointsFrameProvider(provider),
    FrameCache(),
    SelectionCache(),
)
statuses = {}
for rule in module.rules:
    try:
        result = evaluate_rule_columnar(
            rule.expression, frames, precondition=rule.precondition, cache=frame_cache
        )
        engine = "columnar"
    except ColumnarUnsupported:
        result = evaluate_rule(
            rule.expression,
            provider,
            precondition=rule.precondition,
            cache=cache,
            trace=False,
        )
        engine = "reference"
    statuses[rule.code] = result.status
    print(f"{rule.code}: {result.status:15} ({engine}, {rule.severity})")
```

```text
e0001: failed          (columnar, error)
e0002: passed          (columnar, error)
e0003: failed          (columnar, error)
e0004: failed          (columnar, warning)
e0005: not_applicable  (columnar, error)
e0006: passed          (reference, error)
e0007: unsupported     (reference, warning)
```

`e0006` is a script with a temporary assignment (`total := …`), which the
columnar engine leaves to the reference evaluator, like `e0007`'s
`time_shift`; `e0007` compares with the previous quarter's report, which
this provider does not have (see [All at once](#all-at-once)). `e0005` does not apply:
its precondition tests `C_43.00`, which the report's filing indicators mark
as not reported. `e0004` is a `warning`: it is reported, but would not fail
a [`check-report`](../reference/cli.md#dpm-xl-check-report) run on its own.

### 4. Explain the failures

The columnar result has the failing keys but no trace, so evaluate the
failed rules again with [`evaluate_rule`][dpmxl.evaluator.evaluate_rule] and
explain each failing record. [`ReportProvider.fact`][dpmxl.xbrl.ReportProvider.fact]
leads from each cell back to the reported fact and its place in the file.

```python
from dpmxl import explain

for rule in module.rules:
    if statuses[rule.code] != "failed":
        continue
    result = evaluate_rule(
        rule.expression, provider, precondition=rule.precondition, cache=cache
    )
    for outcome in result.failures:
        explanation = explain(result.evaluation, rule.expression, outcome.key)
        print(f"{rule.code} {dict(outcome.key)}: {explanation.summary}")
        for point in explanation.primary:
            print("   ", point.label(), "at", provider.fact(point).location)
```

```text
e0001 {}: 1,045,000 should equal 1,042,000 (812,000 + 190,000 + 40,000): difference 3,000, at least 1,000 given the reported precision
    {tC_47.00, r0040, c0010} at reports/c_47.00.csv:5
e0003 {'qRDT': 'QW4KNDKKV7QH2LA40639'}: -12,000 should be at least 0: difference 12,000
    {tC_48.02, c0010, qRDT=QW4KNDKKV7QH2LA40639} at reports/c_48.02.csv:4
e0004 {'qRDT': 'QW4KNDKKV7QH2LA40639'}: "QW4KNDKKV7QH2LA4063" does not have the required format
    {tC_48.02, c0020, qRDT=QW4KNDKKV7QH2LA40639} at reports/c_48.02.csv:5
```

The total exposure is 3,000 above the sum of its components. Four amounts
rounded to thousands could explain up to 2,000 of that; at least 1,000
cannot. The leverage ratio rule `e0002` passed because 52,000 / 1,045,000 is
within the precision of the reported 4.98 %.

### All at once

[`check_report`][dpmxl.xbrl.check_report] reads the report, checks the EBA
filing rules dpm-xbrl knows and evaluates every active rule of the module,
skipping inactive ones and those for other modules:

```python
from dpmxl.xbrl import check_report

check = check_report("examples/xbrl-module.json", "examples/xbrl-report")
print(check.filing)
print([(run.rule.code, run.status) for run in check.rules])
print(check.failed(), check.failed("warning"))
```

```text
()
[('e0001', 'failed'), ('e0002', 'passed'), ('e0003', 'failed'), ('e0004', 'failed'), ('e0005', 'not_applicable'), ('e0006', 'passed'), ('e0007', 'unsupported')]
True True
```

`e0007` compares with the previous quarter through `time_shift`, which one
report cannot answer. Pass the earlier reports as `previous`
([Compare with earlier reports](time-shift.md#against-earlier-xbrl-reports)).

## In production

- **Module files.** Export one per module and release from the DPM release,
  with each rule's severity and whether the EBA has deactivated it
  (`"active": false`).
- **Large reports.** For open tables with millions of rows, build polars
  frames directly from dpm-xbrl's columnar reader
  (`dpmxbrl.frames.read_xbrl_csv_frames`) in the
  [frame schema](../reference/api/columnar.md#dpmxl.columnar--frame-schema) instead of going
  through `DataPoint`s; see [Evaluate large reports](columnar.md).
- **Filing rules first.** dpm-xbrl records the EBA filing rules a report
  breaks in `report.filing`, and `check_report` returns them with the rule
  results.
- **Threads.** A `ReportProvider` is read-only after construction, so rules
  can run on a thread pool ([Run rules in threads](threads.md)).
