---
description: How selections become keyed records, how operators join them, and how key names match.
---

# Records and keys

DPM-XL operates on sets of *records*. A rule's result has one record per
combination of keys, and each record passes, fails or is not evaluated. Keys
are what make "row 0010 equals rows 0020 + 0030 *in every column*" one rule.

The examples on this page use a closed table `T` (rows `0010`–`0030`,
columns `0010`–`0020`) and an open table `O` keyed by `qEBB`:

```python
from dpmxl import MemoryProvider, Number, TableLayout, evaluate_rule

provider = MemoryProvider(
    [
        TableLayout("T", rows=("0010", "0020", "0030"), columns=("0010", "0020")),
        TableLayout("O", columns=("0010", "0020"), open_keys=("qEBB",)),
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
    },
)


def show(expression):
    result = evaluate_rule(expression, provider)
    records = [(dict(outcome.key), outcome.passed) for outcome in result.outcomes]
    print(result.status, result.message or records)
```

## Selections yield records

A selection yields one record per data point. Its key holds every closed axis
that selects more than one coordinate (`r`, `c`, `s`) plus the open key
components, such as `qEBB`. An axis that is not written counts when the
table has several coordinates on it.

```python
show("{tT, r*, c0010} > 0")  # key r: three records
show("{tT, r0010, c0010} > 0")  # no key: one record
show("{tO, c0010} > 0")  # key qEBB
```

```text
passed [({'r': '0010'}, True), ({'r': '0020'}, True), ({'r': '0030'}, None)]
passed [({}, True)]
failed [({'qEBB': 'A'}, True), ({'qEBB': 'B'}, False)]
```

Row `0030` was not reported, so its record is null: not evaluated, never a
failure (see [Null logic](null.md)).

## Operators join on shared keys

Binary operators natural-join their operands on the keys they share. A
scalar (a record without keys) broadcasts to every record of the other side.
Operands whose keys are unrelated are an error.

```python
show("{tT, r0010, c*} > {tT, r0020, c*}")  # joined on c
show("{tT, r0010, c0010} > {tT, r*, c0020}")  # scalar broadcast over r
show("{tO, c0010} > {tO, c0020}")  # joined on qEBB
show("{tT, r0010} > {tT, c0010}")  # keys r and c: unrelated
```

```text
failed [({'c': '0010'}, True), ({'c': '0020'}, False)]
passed [({'r': '0010'}, True), ({'r': '0020'}, True), ({'r': '0030'}, None)]
failed [({'qEBB': 'A'}, True), ({'qEBB': 'B'}, False)]
error operands have incompatible keys (r) and (c)
```

A join that would produce more than 2,000,000 records is an error rather
than a memory problem (`recordset.MAX_JOIN_RECORDS`).

## Clauses change keys and records

| Clause | Effect |
| --- | --- |
| `[where condition]` | Keeps the records whose keys satisfy the condition. |
| `[get key]` | Replaces each value by the value of a key component; records whose fact is null are omitted. |
| `[sub key = value]` | Fixes a key to a value and removes it from the key. |
| `[rename a to b]` | Renames a key, so it joins with another operand's `b`. |
| `group by k, …` | In an aggregate: one record per value of the listed keys. |

A `where` or `sub` on a selection inside a `with` body overrides the terms of
the context's `where` (split at `and`) that name the same key; the other
terms still apply.

## Key names

Key names in `where`, `group by`, `sub` and `get` match with or without the
DPM 2.0 `q` prefix and ignore case, so `EBB` and `ebb` find `qEBB`:

```python
show('{tO, c0010}[where EBB = "A"] > 0')
show("sum({tO, c0010} group by qEBB) > 0")
```

```text
passed [({'qEBB': 'A'}, True)]
failed [({'qEBB': 'A'}, True), ({'qEBB': 'B'}, False)]
```

Inside a clause, a key component wins over a temporary of the same name
([Statements](statements.md)).

## Codes and items

Axis codes compare the way DPM does: numeric codes as numbers padded to four
digits, so `r310` in an older rule matches row `0310`
([`normalize_code`][dpmxl.provider.normalize_code]). Items compare by code and
category, ignoring the `eba_` prefix and a category missing on either side:
`[eba_qEC:qx01]` equals `[qEC:qx01]` and `[qx01]`.
