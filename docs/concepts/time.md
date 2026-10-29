---
description: Dates, the date functions, time_shift across reports and date keys, and annualise.
---

# Time

## Dates

Date literals are written `#2026-12-31#`, with an optional time
(`#2026-12-31T10:00:00#`). A date equals a date-time at midnight. Report
parameters such as `refPeriod` and date key components hold dates; in Python
they are `datetime.date`.

| Function | Result |
| --- | --- |
| `year(d)`, `month(d)`, `day(d)` | The parts of a date |
| `quarter(d)`, `semester(d)` | 1–4 and 1–2 |
| `week(d)` | The ISO 8601 week |
| `date(y, m, d)` | A date; null for an impossible day such as `date(2026, 2, 30)` |

```dpm-xl
year({p_refPeriod, date}) = 2026
date(2026, 12, 31) = #2026-12-31#
```

`max` and `min` order dates in date order.

## `time_shift`

`time_shift(x, period, count[, key])` presents `x` as it was `count` periods
earlier (later when negative), as in the EBA introduction to DPM-XL.
`period` is `A`, `S`, `Q`, `M`, `W` or `D`.

- When `key` is not a key component of `x` (`refPeriod`, or no key), `x` is
  evaluated on the report the provider's `earlier_report(period, count)`
  returns. Without that method, or when it returns `None`, the rule is
  `unsupported`.
- When `key` is a date key component of `x`, its values move `count` periods
  later instead, within the same report.

Periods move dates by calendar months (12, 6, 3 or 1; a month's last day
stays the last day) or by 7 or 1 days. A `time_shift` that would merge two
records onto one date key is an error.

## `annualise`

`annualise(x, fiscalYearEnd, key)` scales a year-to-date amount to a year:
`x · 12 / months`, where `months` counts the months from the fiscal year
that ends in month `fiscalYearEnd` up to and including the month of the date
in `key` (a date key component, else the report parameter of that name). It
treats that month as complete, so it is meant for period-end dates.

[Compare with earlier reports](../guides/time-shift.md) shows both functions
with runnable examples, and the language reference gives the syntax and
errors of [`time_shift`](../reference/language.md#time_shift), [`annualise`](../reference/language.md#annualise) and
the [date functions](../reference/language.md#date-functions).
