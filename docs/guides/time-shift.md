---
description: Evaluate time_shift against earlier reports through earlier_report or earlier XBRL reports, shift date keys within a report, and annualise year-to-date amounts.
---

# Compare with earlier reports

`time_shift(x, period, count[, key])` compares a value with the same value
some periods earlier: on an earlier report, or, when `key` is a date key of
`x`, within the same report. [Time](../concepts/time.md) explains both
modes and the periods; this guide shows the code for each.

## Against the previous report

`MemoryProvider` takes the earlier reports as `earlier_reports`, keyed by
`(period, count)`. Your own provider implements `earlier_report`
([Connect your data](provider.md#earlier_report-time_shift-across-periods)).

```python
from datetime import date

from dpmxl import MemoryProvider, Number, TableLayout, evaluate_rule, explain

layout = [TableLayout("C_02.00", rows=("0010",), columns=("0010",))]
september = MemoryProvider(
    layout,
    {("C_02.00", "0010", "0010", None, ()): Number.of(240, 0)},
    parameters={"refPeriod": date(2026, 9, 30)},
)
december = MemoryProvider(
    layout,
    {("C_02.00", "0010", "0010", None, ()): Number.of(260, 0)},
    parameters={"refPeriod": date(2026, 12, 31)},
    earlier_reports={("Q", 1): september},
)

growth = "{tC_02.00, r0010, c0010} <= time_shift({tC_02.00, r0010, c0010}, Q, 1, refPeriod) * 1.05"
result = evaluate_rule(growth, december)
outcome = result.failures[0]
print(explain(result.evaluation, growth, outcome.key).summary)
for point in outcome.points:
    print(point.ref)
```

```text
260 should not exceed 252 (time_shift(240, Q, 1, refPeriod) × 1.05): difference 8
('C_02.00', '0010', '0010', None, ())
EarlierRef(period='Q', count=1, ref=('C_02.00', '0010', '0010', None, ()))
```

The explanation shows the earlier report's value. Points read from the earlier
report carry [`EarlierRef`][dpmxl.provider.EarlierRef] as their `ref`,
wrapping that report's own `ref`, so a user interface can tell the two cells
apart and link to the earlier report.

When the provider has no such report, the rule is `unsupported` rather than
failed:

```python
year_on_year = "{tC_02.00, r0010, c0010} >= time_shift({tC_02.00, r0010, c0010}, A, 1)"
result = evaluate_rule(year_on_year, december)
print(result.status, "|", result.message)
```

```text
unsupported | time_shift needs the report 1 year(s) earlier (reference date 2025-12-31), which the provider does not have
```

Without an `earlier_report` method at all, the message says that the rule
compares with the previous reporting period, which a single report does not
include. Evaluating with a shared `SelectionCache` keeps a separate cache for
each earlier report.

## Against earlier XBRL reports

A report read with dpm-xbrl holds one period, so on real EBA modules
`time_shift` rules are `unsupported` until you supply the earlier reports.
[`ReportProvider`][dpmxl.xbrl.ReportProvider] takes them as `previous`, in
any order, and picks by reference date: `time_shift(x, Q, 1)` on the report
for 2026-03-31 reads the one for 2025-12-31, placed and typed by the same
module.

```python
from dpmxbrl import read_report

from dpmxl import evaluate_rule, explain
from dpmxl.module import load_module
from dpmxl.xbrl import ReportProvider

module = load_module("examples/xbrl-module.json")
provider = ReportProvider(
    module,
    read_report("examples/xbrl-report"),
    previous=[read_report("examples/xbrl-report-previous")],
)
print(list(provider.previous))
rule = module.rules[-1]
result = evaluate_rule(rule.expression, provider)
print(rule.code, result.status)
print(explain(result.evaluation, rule.expression, result.failures[0].key).summary)
```

```text
[datetime.date(2025, 12, 31)]
e0007 failed
1,045,000 should be at least 1,062,000 (0.9 × time_shift(1,180,000, Q, 1, refPeriod)): difference 17,000
```

The previous reports can shift among themselves too, so a nested
`time_shift` or a negative `count` reaches any of them. A shift to a period
none of them covers leaves the rule `unsupported`, and the message names the
reference date it needs:

```python
provider = ReportProvider(module, read_report("examples/xbrl-report"))
print(evaluate_rule(rule.expression, provider).message)
```

```text
time_shift needs the report 1 quarter(s) earlier (reference date 2025-12-31), which the provider does not have
```

[`check_report`][dpmxl.xbrl.check_report] takes the same `previous` (reports
or paths, read with the same taxonomy packages), and so does the command
line, as `--previous`:

```bash
dpm-xl check-report examples/xbrl-module.json examples/xbrl-report --previous examples/xbrl-report-previous
```

[Check an XBRL report](end-to-end.md#on-the-command-line) shows its
output, with `e0007` evaluated.

## Within one report, on a date key

An open table keyed by a date can compare each date with the one before it:

```python
history = MemoryProvider(
    [TableLayout("C_99.00", columns=("0010",), open_keys=("qDAT",))],
    {
        ("C_99.00", None, "0010", None, (("qDAT", date(2026, 3, 31)),)): Number.of(
            100, 0
        ),
        ("C_99.00", None, "0010", None, (("qDAT", date(2026, 6, 30)),)): Number.of(
            90, 0
        ),
        ("C_99.00", None, "0010", None, (("qDAT", date(2026, 9, 30)),)): Number.of(
            120, 0
        ),
    },
)
rising = "{tC_99.00, c0010} >= time_shift({tC_99.00, c0010}, Q, 1, qDAT)"
result = evaluate_rule(rising, history)
for outcome in result.outcomes:
    print(outcome.key["qDAT"], outcome.passed)
```

```text
2026-06-30 False
2026-09-30 True
```

The shifted operand has records for June and September (March plus one
quarter, June plus one quarter, and September moved past the data), so the
comparison has records where both sides do: June fails (90 < 100), September
passes (120 ≥ 90).

The explanation fills the shifted operand with the value of the record it
came from, here March's:

```python
june = result.failures[0]
print(explain(result.evaluation, rising, june.key).summary)
```

```text
90 should be at least 100 (time_shift(100, Q, 1, qDAT)): difference 10
```

## `annualise`

`annualise(x, fiscalYearEnd, key)` scales a year-to-date amount to a full
year ([Time](../concepts/time.md#annualise)):

```python
result = evaluate_rule("annualise({tC_99.00, c0010}, 12, qDAT) > 300", history)
for outcome in result.outcomes:
    print(outcome.key["qDAT"], outcome.passed)
```

```text
2026-03-31 True
2026-06-30 False
2026-09-30 False
```

March annualises to 100 · 12 / 3 = 400, June to 90 · 12 / 6 = 180 and
September to 120 · 12 / 9 = 160.

## Columnar evaluation

The columnar evaluator hands every `time_shift` and `annualise` rule to the
reference evaluator by raising `ColumnarUnsupported`
([Evaluate large reports](columnar.md)).
