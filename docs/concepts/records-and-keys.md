---
description: How selections become keyed records, how operators join them, and how key names match.
---

# Records and keys

DPM-XL operates on sets of *records*. A rule's result has one record per
combination of keys, and each record passes, fails or is not evaluated. Keys
are what make "row 0010 equals rows 0020 + 0030 *in every column*" one rule.

The examples on this page use a closed table `T` (rows `0010`–`0030`,
columns `0010`–`0020`) and open tables `O` and `P` keyed by `qEBB`:

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

## Defaults fill in missing records

An open table has records only for the key combinations reported in it, so
two tables, or two parts of one template, may each lack keys the other has.
An operand with a written `default` (`default: null` included) then stands
for its default where it lacks a key, as a fact variable with a fallback
value does. One rule covers every construct that combines keyed operands:

- **Joins** (operators, and functions of several operands such as `nvl`,
  `max`, `match` and `filter`): the operands without a default decide the
  keys, keeping those all of them have, and the others fill in their
  default. When every keyed operand has a default, the result has a record
  for each key any operand with all the result's keys has. Without
  defaults, a join keeps only the keys both sides have.
- **`if`**: a keyed condition with a default also covers the keys a branch
  has and it lacks, provided every branch without a default has them; the
  condition takes its default there. A branch lacking a key takes its
  default; without one, the record is null.
- **Which results keep a default**: everything that keeps a record's value
  tied to the same fact keeps it, applied to the default: unary operators,
  `in`, the operators and functions above (when every keyed operand has a
  default), `[rename]`, a `time_shift` that moves a date key, and the
  selecting clauses `[where]`, `[sub]`, `filter` and a `with` context's
  `where`. A filter restricts the operand's own records, not the keys the
  other operands bring: there the operand falls back to its default. An
  `if` keeps the default of the branch its condition's default takes.
- **Which results have none**: `[get]` turns key components into values,
  and a default has no key components, so a key the operand lacks gives
  no value (DPM-XL omits records without a fact). Aggregates and analytic
  functions build each record from a group or window of records: a key
  without records is no group, and its value is not the operand's default
  (`sum` of nothing is null, not `0`). Their results join on shared keys
  only.
- A key-less operand without its record, such as `[sub]` on a key value
  nobody reported, stands for its default next to keyed operands or
  reported values; on its own, or with constants only, it yields no record.

```python
show("{tO, c0010} = {tP, c0010}")
show("with {default: 0}: {tO, c0010} = {tP, c0010}")
show("{tO, c0010} >= {tP, c0010, default: 0}")
show(
    "with {default: null}: if not isnull({tP, c0010}) then not isnull({tO, c0010}) endif"
)
show(
    "with {default: 0}: if {tO, c0010} > 0 then {tO, c0010} < 10 else {tP, c0010} = 0 endif"
)
show('{tO, c0010, default: 0} [where qEBB = "A"] <= {tP, c0010}')
```

```text
passed [({'qEBB': 'B'}, True)]
failed [({'qEBB': 'A'}, False), ({'qEBB': 'B'}, True), ({'qEBB': 'C'}, False)]
passed [({'qEBB': 'A'}, True), ({'qEBB': 'B'}, True)]
failed [({'qEBB': 'B'}, True), ({'qEBB': 'C'}, False)]
failed [({'qEBB': 'A'}, True), ({'qEBB': 'B'}, False), ({'qEBB': 'C'}, False)]
failed [({'qEBB': 'B'}, False), ({'qEBB': 'C'}, True)]
```

## Clauses change keys and records

| Clause | Effect |
| --- | --- |
| `[where condition]` | Keeps the records whose keys satisfy the condition. |
| `[get key]` | Replaces each value by the value of a key component; records whose fact is null are omitted. |
| `[sub key = value]` | Fixes a key to a value and removes it from the key. |
| `[rename a to b]` | Renames a key, so it joins with another operand's `b`; an error if the record set already has `b`. |
| `group by k, …` | In an aggregate: one record per value of the listed keys. |

A `with` context's `where` applies to each selection in its body that has
the keys it names. Its terms (split at `and`) that name a key the selection
lacks, neither a key nor a report parameter, leave that selection alone, and
a key-less selection takes none of it. A `where` or `sub` on a selection
inside the body overrides the terms that name the same key; the other terms
still apply.

```python
show('with {tO, c0010} [where qEBB = "A"]: {tO} > {tT, r0020, c0010}')
```

```text
passed [({'qEBB': 'A'}, True)]
```

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
