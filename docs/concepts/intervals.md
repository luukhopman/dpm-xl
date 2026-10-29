---
description: How reported precision (XBRL decimals) turns numbers into intervals, how arithmetic and comparisons treat them, and why explanations report a gap.
---

# Interval arithmetic

A fact reported as 1,204 with XBRL `decimals="0"` is a rounded amount: the
true value lies anywhere from 1,203.5 to 1,204.5. A rule that adds such
amounts must allow for the rounding, or it fails reports that are correct.
EBA validation rules therefore use interval arithmetic (EBA Filing Rules
2.18), with the formulas of DPM-XL §4 and §7, which follow the Eurofiling
interval arithmetic functions (`iaf:*`, version 1.1.1).

## Numbers with a tolerance

A [`Number`][dpmxl.values.Number] is a decimal value with a symmetric
tolerance. `Number.of(value, decimals)` derives the tolerance from XBRL
`decimals`: `0.5 · 10^-decimals`. `INF` (in any case) or `None` means exact;
constants in rules and selection defaults are exact.

```python
from dpmxl import Number

print(Number.of(1204, 0))
print(Number.of(1204000, -3).tolerance, Number.of("0.0498", 4).tolerance)
print(Number.of(5, "INF"))
```

```text
Number(value=Decimal('1204'), tolerance=Decimal('0.5'))
5E+2 0.00005
Number(value=Decimal('5'), tolerance=Decimal('0'))
```

## Arithmetic

| Operation | Tolerance of the result |
| --- | --- |
| `a + b`, `a - b` | `δa + δb` |
| `a * b` | `|a·δb| + |b·δa| + δa·δb` |
| `a / b` | The largest deviation of the four endpoint quotients from `a / b`; an error when `b`'s interval contains zero |
| `-a`, `abs(a)` | `δa` |
| `min`, `max` | The chosen value's tolerance; among equal values, the largest |
| `median` | The middle value's tolerance, or the mean of the two middle ones' |

```python
a, b = Number.of(10, 0), Number.of("7.0", 1)
print(a + b)
print(a * b)
```

```text
Number(value=Decimal('17.0'), tolerance=Decimal('0.55'))
Number(value=Decimal('70.0'), tolerance=Decimal('4.025'))
```

Arithmetic keeps 34 significant digits (IEEE decimal128) in any thread
decimal context; the caller's `decimal` context has no effect.

## Comparisons

Two numbers compare as intervals:

| Comparison | Holds when |
| --- | --- |
| `a = b` | `|a − b| ≤ δa + δb` (the intervals overlap) |
| `a != b` | the intervals do not overlap |
| `a <= b` | `a − b ≤ δa + δb` |
| `a >= b` | `a ≥ b − (δa + δb)` |
| `a < b`, `a > b` | likewise, strictly |

```python
from dpmxl.values import compare

print(compare("=", Number.of(10, 0), Number.of("10.4")))
print(compare("=", Number.of(10, 0), Number.of("10.6")))
```

```text
True
False
```

## Switching it on and off

Interval arithmetic applies to selections with `interval: true`:
`{tC_01.00, r0010, interval: true}`, usually set once in a `with` context.
With `interval: false`, or without the option, facts are compared exactly
as reported. EBA rules state the option explicitly. Each operator and
function in the [language reference](../reference/language.md#interval)
says what it does with a tolerance.

## The gap in explanations

When a comparison fails despite the tolerance, [`explain`](../guides/explain.md)
reports each side's interval and the *gap*: how far apart the closest values
within those intervals still are. In

```text
1,204 should equal 1,211 (1,180 + 31): difference 7, at least 5.5 given the reported precision
```

the left side is 1,204 ± 0.5 and the right side 1,211 ± 1, so the difference
of 7 shrinks to at least 5.5. The gap is rounded down, so "at least" never
overstates it.

## Quotients with a negative divisor

The quotient's tolerance in DPM-XL §4.3.4.4 takes the absolute value of the
numerator's endpoints only, so for a negative divisor it comes out negative.
dpm-xl takes the largest deviation of the four endpoint quotients, which is
the same for a positive divisor and stays sound for a negative one. The
columnar evaluator uses `Decimal(38, 12)`; see
[Evaluate large reports](../guides/columnar.md#precision).
