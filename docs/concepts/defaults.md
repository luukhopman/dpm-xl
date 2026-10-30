---
description: How an operand with a default fills in keys other operands have - in joins, if, filters and aggregates - and where dpm-xl differs from the specification.
---

# Defaults across keys

This page is for rule authors and implementers; [Records and
keys](records-and-keys.md) has the basics. It uses the same tables: a
closed table `T`, and open tables `O` and `P` keyed by `qEBB`, where `O`
has keys `A` and `B` and `P` has `B` and `C`.

In short, for `{tO, c0010} = {tP, c0010}`:

| `qEBB` | `O` | `P` | Without default | `with {default: 0}` |
| --- | --- | --- | --- | --- |
| `A` | 5 | – | no record | 5 = 0: false |
| `B` | -1 | -1 | true | true |
| `C` | – | 3 | no record | 0 = 3: false |

An operand with a written `default` (`default: null` included) stands for
its default where it lacks a key, as a fact variable with a fallback value
does. The rules below say which keys a result has. Their examples use this
report:

```python
from dpmxl import MemoryProvider, Number, TableLayout, evaluate_rule

provider = MemoryProvider(
    [
        TableLayout("T", rows=("0010", "0020", "0030"), columns=("0010", "0020")),
        TableLayout("O", columns=("0010", "0020"), open_keys=("qEBB",)),
        TableLayout("P", columns=("0010",), open_keys=("qEBB",)),
    ],
    {
        ("T", "0010", "0010", None, ()): Number.of(10, 0),
        ("T", "0020", "0010", None, ()): Number.of(4, 0),
        ("T", "0010", "0020", None, ()): Number.of(7, 0),
        ("T", "0020", "0020", None, ()): Number.of(7, 0),
        ("O", None, "0010", None, (("qEBB", "A"),)): Number.of(5, 0),
        ("O", None, "0010", None, (("qEBB", "B"),)): Number.of(-1, 0),
        ("O", None, "0020", None, (("qEBB", "A"),)): Number.of(2, 0),
        ("O", None, "0020", None, (("qEBB", "B"),)): Number.of(0, 0),
        ("P", None, "0010", None, (("qEBB", "B"),)): Number.of(-1, 0),
        ("P", None, "0010", None, (("qEBB", "C"),)): Number.of(3, 0),
    },
)


def show(expression):
    result = evaluate_rule(expression, provider)
    records = [(dict(outcome.key), outcome.passed) for outcome in result.outcomes]
    print(result.status, result.message or records)
```

## Joins

Operators, and functions of several operands such as `nvl`, `max`, `match`
and `filter`: the operands without a default decide the keys, keeping
those all of them have, and the others fill in their default. When every
keyed operand has a default, the result has a record for each key that
any operand with all the result's keys has.

```python
show("{tO, c0010} >= {tP, c0010, default: 0}")  # O has no default: A and B
```

```text
passed [({'qEBB': 'A'}, True), ({'qEBB': 'B'}, True)]
```

## `if`

A keyed condition with a default also covers the keys a branch has and it
lacks, provided every branch without a default has them; the condition
takes its default there. A branch lacking a key takes its default; without
one, the record is null.

```python
show(
    "with {default: null}: if not isnull({tP, c0010}) then not isnull({tO, c0010}) endif"
)
show(
    "with {default: 0}: if {tO, c0010} > 0 then {tO, c0010} < 10 else {tP, c0010} = 0 endif"
)
```

```text
failed [({'qEBB': 'B'}, True), ({'qEBB': 'C'}, False)]
failed [({'qEBB': 'A'}, True), ({'qEBB': 'B'}, False), ({'qEBB': 'C'}, False)]
```

## Which results keep a default

Everything that keeps a record's value tied to the same fact keeps the
default, applied to it: unary operators, `in`, the joins above (when every
keyed operand has a default), `[rename]`, a `time_shift` that moves a date
key, and the selecting clauses `[where]`, `[sub]`, `filter` and a `with`
context's `where`. An `if` keeps the default of the branch its condition's
default takes.

A filter restricts the operand's own records, not the keys the other
operands bring; there the operand falls back to its default:

```python
show('{tO, c0010, default: 0} [where qEBB = "A"] <= {tP, c0010}')
```

```text
failed [({'qEBB': 'B'}, False), ({'qEBB': 'C'}, True)]
```

`O` keeps only `A`, `P` (without a default) decides the keys `B` and `C`,
and `O` is 0 at both.

## Which results have none

- `[get]` turns key components into values, and a default has no key
  components, so a key the operand lacks gives no value (DPM-XL omits
  records without a fact).
- Aggregates and analytic functions build each record from a group or
  window of records: a key without records is no group, and its value is
  not the operand's default (`sum` of nothing is null, not `0`). Their
  results join on shared keys only.

## An operand with no record

An operand with no record at all, such as a `[where]` that filters out
every record, an open table nobody reported or `[sub]` on a key value
nobody reported, stands for its default at every record the other
operands have, whatever their keys. An aggregate other than `count` of
such an operand is the aggregate of its default (`sum` gives `0` with
`default: 0`). On its own, or with constants only, the operand yields no
record.

```python
show('with {default: 0}: {tO, c0010} [where qEBB = "Z"] = {tT, r0010, c0010}')
show('with {default: 0}: sum({tO, c0010} [where qEBB = "Z"]) = {tT, r0010, c0010}')
```

```text
failed [({}, False)]
failed [({}, False)]
```

This is how the EBA's formulas evaluate these rules: a fact variable that
binds to no fact takes its fallback value.

## Why dpm-xl differs

The specification joins inner and fills in defaults only for keys the
operand's own table reports (§2.2.3.3, IM §4.2.1). dpm-xl fills them in
for keys the other operands bring, as the EBA's formulas do; this is a
[deliberate difference](../reference/language.md#where-dpm-xl-differs).
