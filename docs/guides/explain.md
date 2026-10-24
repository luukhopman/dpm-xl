---
description: Turn a failing record into a sentence, a filled formula and the cells to highlight, for a review screen or an API response.
---

# Explain failures in a UI

A failing rule is only useful when someone can see why. For every failing
record, [`explain`][dpmxl.explain.explain] returns an
[`Explanation`][dpmxl.explain.Explanation]: a sentence, the formula with the
reported values filled in, both sides of the comparison with their intervals,
and the cells involved. This guide turns that into a payload for a review
screen.

## The report

```python
from dpmxl import MemoryProvider, Number, TableLayout, evaluate_rule, explain

amounts = {
    ("0010", "0010"): 100,
    ("0020", "0010"): 60,
    ("0030", "0010"): 40,
    ("0010", "0020"): 1204,
    ("0020", "0020"): 1180,
    ("0030", "0020"): 31,
}
provider = MemoryProvider(
    [TableLayout("C_01.00", rows=("0010", "0020", "0030"), columns=("0010", "0020"))],
    {
        ("C_01.00", row, column, None, ()): Number.of(amount, 0)
        for (row, column), amount in amounts.items()
    },
)
expression = (
    "with {tC_01.00, c*, default: 0, interval: true}: {r0010} = {r0020} + {r0030}"
)
result = evaluate_rule(expression, provider)
outcome = result.failures[0]
explanation = explain(result.evaluation, expression, outcome.key)
```

`result.evaluation` holds the intermediate values of every node, which
`explain` reads. Pass the same `expression` text the rule was evaluated from.

## What an explanation holds

```python
print(explanation.kind)
print(explanation.summary)
print(explanation.formula)
print(explanation.filled)
print(explanation.relation, "|", explanation.verb)
print(
    explanation.difference,
    explanation.gap,
    explanation.tolerance,
    explanation.direction,
)
```

```text
comparison
1,204 should equal 1,211 (1,180 + 31): difference 7, at least 5.5 given the reported precision
{r0010} = {r0020} + {r0030}
1,204 = 1,180 + 31
= | should equal
7 5.5 1.5 too_low
```

| Field | Meaning |
| --- | --- |
| `kind` | `comparison`, or for other failures `missing` (a cell must be reported), `not_empty` (must be empty), `membership` (must be one of a set), `format` (must match a pattern) or `condition`. |
| `summary` | One sentence for the reviewer. |
| `formula`, `filled` | The failing statement's formula, and the same with values (`1,204 = 1,180 + 31`). Formulas are rendered from the tree, with uniform spacing, a typographic minus for negative terms and long runs of zeros collapsed to `+ 0 (x13)`. |
| `relation`, `verb` | The comparison symbol (`=`, `≠`, `≤`, …) and its wording (`should equal`). |
| `difference` | Left minus right, as text. |
| `tolerance` | How far apart the sides may be from reported precision alone (the sum of both sides' thresholds). |
| `gap` | The distance that remains after allowing for that precision, rounded down so that "at least" never overstates it. |
| `direction` | `too_high` when the left side exceeds the right, `too_low` otherwise. It says which side is larger, not which value is wrong. |
| `left`, `right` | Each side as a [`Side`][dpmxl.explain.Side]. |
| `operands` | Every leaf operand (cell, aggregate, parameter) as an [`Operand`][dpmxl.explain.Operand]: its source text, value and cells. |
| `primary` | The cells on the left of the failing comparison: the values that disagree. |

Fields that do not apply are `None`; a failure that is not a comparison has
no sides, difference or gap.

## Sides and intervals

```python
for side in (explanation.left, explanation.right):
    print(
        side.formula,
        "|",
        side.filled,
        "|",
        side.value,
        f"[{side.low}, {side.high}]",
        side.terms,
    )
```

```text
{r0010} | 1,204 | 1,204 [1,203.5, 1,204.5] 1
{r0020} + {r0030} | 1,180 + 31 | 1,211 [1,210, 1,212] 2
```

With `interval: true`, each reported number stands for an interval (see
[Interval arithmetic](../concepts/intervals.md)). The left side can be at
most 1,204.5 and the right side at least 1,210, so they are at least 5.5
apart: that is the `gap`.

## Highlight the cells

Every data point carries the `ref` your provider gave it.
`outcome.points` are all the cells the record used; `explanation.primary` is
the subset that disagrees. `MemoryProvider` uses the cell key as its `ref`;
your provider can use a database id or a location in the report file.

```python
def payload(rule_code, expression, result, outcome):
    explanation = explain(result.evaluation, expression, outcome.key)
    return {
        "rule": rule_code,
        "record": {name: str(value) for name, value in outcome.key.items()},
        "summary": explanation.summary,
        "formula": explanation.filled,
        "highlight": [point.label() for point in explanation.primary],
        "cells": [point.label() for point in outcome.points],
    }


import json

print(json.dumps(payload("v0001", expression, result, outcome), indent=2))
```

```text
{
  "rule": "v0001",
  "record": {
    "c": "0020"
  },
  "summary": "1,204 should equal 1,211 (1,180 + 31): difference 7, at least 5.5 given the reported precision",
  "formula": "1,204 = 1,180 + 31",
  "highlight": [
    "{tC_01.00, r0010, c0020}"
  ],
  "cells": [
    "{tC_01.00, r0010, c0020}",
    "{tC_01.00, r0020, c0020}",
    "{tC_01.00, r0030, c0020}"
  ]
}
```

[`DataPoint.label()`][dpmxl.provider.DataPoint.label] renders a cell as a
DPM-XL selection; `point.ref` is the identity to look it up by.

## Failures that are not comparisons

Presence checks, membership and pattern rules get their own sentence:

```python
from dpmxl import Item

layout = TableLayout("T", rows=("0010", "0020", "0030", "0040"), columns=("0010",))
values = {
    ("T", "0010", "0010", None, ()): Number.of(5, 0),
    ("T", "0020", "0010", None, ()): "AB-12",
    ("T", "0030", "0010", None, ()): Item.parse("eba_qEC:qx9"),
}
report = MemoryProvider([layout], values)
for rule in (
    "if not isnull({tT, r0010, c0010}) then not isnull({tT, r0040, c0010}) endif",
    "isnull({tT, r0010, c0010})",
    "{tT, r0030, c0010} in {[eba_qEC:qx1], [eba_qEC:qx2]}",
    'match({tT, r0020, c0010}, "[0-9]+")',
):
    failed = evaluate_rule(rule, report)
    explained = explain(failed.evaluation, rule, failed.failures[0].key)
    print(f"{explained.kind}: {explained.summary}")
```

```text
missing: {tT, r0040, c0010} must be reported
not_empty: {tT, r0010, c0010} must be empty, but 5 is reported
membership: [qEC:qx9] is not one of [qEC:qx1], [qEC:qx2]
format: "AB-12" does not have the required format
```

## Many failures on a large report

- Explaining is cheap per record, but a rule on a large open table can fail
  thousands of times. Explain the first few hundred for the screen and count
  the rest with `result.counts`.
- `evaluate_rule(..., trace=False)` skips keeping intermediate values: faster
  and leaner when you only need statuses. Such a result cannot be explained.
- To explain a few known failing records of a large closed selection, evaluate
  again with `only_keys={"c": ["0020"]}`, which keeps only those closed-axis
  codes in every selection. Do not use it for rules with aggregates, whose
  totals would cover only the kept records.
- The columnar evaluator returns failing keys but no trace; explain its
  failures by evaluating those rules again with `evaluate_rule`
  ([Evaluate large reports](columnar.md)).

Explanation and error wording may improve in minor releases; the field names
and `kind` values may not ([Stability](../project/stability.md)).
