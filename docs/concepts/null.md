---
description: Missing facts, defaults, three-valued logic, conditionals and record-level errors such as division by zero.
---

# Null logic

Reports leave cells empty, and rules must not fail because of it. DPM-XL
handles missing values with defaults, null propagation and three-valued
logic.

```python
from dpmxl import MemoryProvider, Number, TableLayout, evaluate_rule

provider = MemoryProvider(
    [
        TableLayout("T", rows=("0010", "0020", "0030"), columns=("0010",)),
        TableLayout("O", columns=("0010", "0020"), open_keys=("qEBB",)),
    ],
    {
        ("T", "0010", "0010", None, ()): Number.of(10, 0),
        ("T", "0020", "0010", None, ()): Number.of(4, 0),
        # T r0030 is not reported
        ("O", None, "0010", None, (("qEBB", "A"),)): Number.of(5, 0),
        ("O", None, "0010", None, (("qEBB", "B"),)): Number.of(-1, 0),
        ("O", None, "0020", None, (("qEBB", "A"),)): Number.of(2, 0),
        ("O", None, "0020", None, (("qEBB", "B"),)): Number.of(0, 0),
    },
)


def show(expression):
    result = evaluate_rule(expression, provider)
    print(
        result.status, result.message or [outcome.passed for outcome in result.outcomes]
    )
```

## Missing facts and defaults

A cell with no fact takes the selection's `default`; with no default it is
null. A provider must therefore return every defined cell of a closed
selection, reported or not ([Connect your data](../guides/provider.md)).
The default also stands in where another operand has an open key the
selection lacks ([Records and keys](records-and-keys.md#defaults-fill-in-missing-records)).

```python
show("{tT, r0030, c0010} > 0")
show("{tT, r0030, c0010, default: 0} >= 0")
show("isnull({tT, r0030, c0010})")
```

```text
not_applicable [None]
passed [True]
passed [True]
```

## Null propagates

Null propagates through arithmetic, comparisons and functions, except
`isnull` and `nvl(x, replacement)`. A record whose result is null is "not
evaluated", never a failure; a rule whose records are all null is
`not_applicable`.

`and`, `or` and `not` use three-valued (Kleene) logic: `null or true` is
true, `null and false` is false, anything else with null is null.

```python
show("{tT, r0030, c0010} > 0 or true")
show("{tT, r0030, c0010} > 0 and false")
```

```text
passed [True]
failed [False]
```

## Conditionals

`if` takes the `else` branch when the condition is null. Without `else`, the
records whose condition is false or null are left out, so a guarded check is
not evaluated where its guard does not hold.

```python
show("if {tT, r0030, c0010} > 0 then false endif")
show("if {tT, r0030, c0010} > 0 then 1 else 2 endif = 2")
```

```text
not_applicable []
passed [True]
```

The result has the condition's record structure. Branch keys the condition
lacks widen it, so each condition record applies to every branch record that
shares its keys. A condition with a `default` also covers the key values only
a branch has ([Records and keys](records-and-keys.md#defaults-fill-in-missing-records)).

## Errors stay in their record

Division by zero is a run-time error, as the specification requires. Like a
type error (a non-Boolean `if` condition included), it fails only its own
record: the rule is an error only if that record reaches the result. A guard
therefore works:

```python
show("{tT, r0010, c0010} / {tT, r0030, c0010, default: 0} > 1")
show(
    "if {tT, r0030, c0010, default: 0} != 0 then {tT, r0010, c0010} / {tT, r0030, c0010, default: 0} > 1 endif"
)
```

```text
error division by zero
not_applicable []
```

## Aggregates

Aggregates over no records are null, except `count`, which is 0, and an
operand with a `default`, which aggregates its default next to other
operands ([Defaults fill in missing records](records-and-keys.md#defaults-fill-in-missing-records)).
`count` counts non-null values; the others skip nulls.

```python
show("count({tT, r0030, c0010}) = 0")
show("sum({tT, r0030, c0010}) = 0")
```

```text
passed [True]
not_applicable [None]
```

## Preconditions

A precondition makes the rule `not_applicable` unless it yields at least one
true record; null and false records do not count. See
[Preconditions and results](results.md).
