---
description: Evaluate time_shift against earlier reports through earlier_report, shift date keys within a report, and annualise year-to-date amounts.
---

# Compare with earlier reports

`time_shift(x, period, count[, key])` compares a value with the same value
some periods earlier. It works in one of two ways, depending on `key`:

- **Another report.** When `key` is not a key component of `x` (usually
  `refPeriod`, or no key at all), `x` is evaluated on the report `count`
  periods earlier, which the provider's `earlier_report(period, count)`
  returns. This is how EBA rules compare with the previous reporting period.
- **Within the report.** When `key` is a date key component of `x`, the
  values of that key move `count` periods later, so each record lines up
  with the one `count` periods before it.

Periods are `A` (year), `S` (semester), `Q` (quarter), `M` (month), `W`
(week) and `D` (day). Dates move by calendar months (12, 6, 3 or 1; a
month's last day stays the last day) or by 7 or 1 days. A negative `count`
looks forward.

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
unsupported | time_shift needs the report 1 year(s) earlier, which the provider does not have
```

Without an `earlier_report` method at all, the message says that the rule
compares with the previous reporting period, which a single report does not
include. Evaluating with a shared `SelectionCache` keeps a separate cache for
each earlier report.

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
year: `x · 12 / months`, where `months` counts the months from the start of
the fiscal year that ends in month `fiscalYearEnd` up to and including the
month of the date in `key`. `key` is a date key component of `x`, or else a
report parameter such as `refPeriod`. The month is treated as complete, so
`annualise` is meant for period-end dates.

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
