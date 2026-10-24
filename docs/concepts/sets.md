---
description: Set literals, set parameters, set_of and the set operators, and how in tests membership.
---

# Sets

Sets hold distinct non-null values in first-seen order: numbers compared
exactly, items ignoring the `eba_` prefix. They are written as literals
(`{1, 2}`, `{[eba_CU:EUR], [eba_CU:USD]}`, the empty set `{}`), come from
set parameters (`{p_Allowed, set-item}`), or are built with `set_of(x)` and
the set operators `union`, `intersect`, `setdiff` and `symdiff`. In Python a
set is a [`ValueSet`][dpmxl.values.ValueSet].

```python
from dpmxl import Item, MemoryProvider, Number, TableLayout, ValueSet, evaluate_rule

currencies = ValueSet.of([Item.parse("eba_CU:EUR"), Item.parse("eba_CU:USD")])
provider = MemoryProvider(
    [TableLayout("O", columns=("0010", "0020"), open_keys=("qEBB",))],
    {
        ("O", None, "0010", None, (("qEBB", "A"),)): Item.parse("eba_CU:EUR"),
        ("O", None, "0010", None, (("qEBB", "B"),)): Item.parse("eba_CU:JPY"),
        ("O", None, "0020", None, (("qEBB", "A"),)): Number.of(2, 0),
        ("O", None, "0020", None, (("qEBB", "B"),)): Number.of(3, 0),
    },
    parameters={"Allowed": currencies},
)


def show(expression):
    result = evaluate_rule(expression, provider)
    print(
        result.status, result.message or [outcome.passed for outcome in result.outcomes]
    )


print(ValueSet.of([1, 2, 2, None]))
```

```text
ValueSet(members=(1, 2))
```

## Membership with `in`

`x in s` tests each record of `x` against the set:

```python
show("{tO, c0010} in {[eba_CU:EUR], [eba_CU:USD]}")
show("{tO, c0010} in {p_Allowed, set-item}")
show("{tO, c0010} in union({p_Allowed, set-item}, {[CU:JPY]})")
```

```text
failed [True, False]
failed [True, False]
passed [True, True]
```

An operand of `in` or of a set operator that is not a set stands for the set
of its non-null values, so `{c0010} in {tT, r*, c0020}` tests against the
values of a column, and `{tO, c0020} in setdiff({1, 2, 3}, {tO, c0020})`
against what the column does not hold:

```python
show("{tO, c0020} in setdiff({1, 2, 3}, {tO, c0020})")
```

```text
failed [False, False]
```

## Missing sets

A single null, such as a set parameter the report does not have, is a null
set, which makes `in` and the set operators null. A `default: {…}` on the
parameter supplies a set instead. `set_of(null)` is `{}`.

```python
show("{tO, c0010} in {p_Missing, set-item}")
show("{tO, c0010} in {p_Missing, set-item, default: {[eba_CU:JPY]}}")
```

```text
not_applicable [None, None]
failed [False, True]
```

## Restrictions

Sets cannot be compared with `=` or the other comparison operators, and
cannot be a rule's result. A set `default` on a cell selection is an error.
The columnar evaluator handles `in` with a set literal; it hands every other
set operand (parameters, selections, set operators) to the reference
evaluator.
