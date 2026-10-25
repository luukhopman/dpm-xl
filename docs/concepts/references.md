---
description: Filing indicators, report parameters, typed parameters, operation references and table groups, and the reference prefixes.
---

# Parameters, operations and table groups

Besides table cells, a rule can read report-level data and other rules'
results. Each kind of reference goes to a provider method
([Connect your data](../guides/provider.md)).

| Reference | Reads | Provider method |
| --- | --- | --- |
| `{v_C_01.00}` | Whether table or template `C_01.00` was reported (its filing indicator) | `table_reported(table)` |
| `{vName}` | Report parameter `Name`, as given | `parameter(name)` |
| `{p_Name, type[, default: v]}` | Report parameter `Name`, checked against a type | `parameter(name)` |
| `{o_Code[, r…, c…, default: v, interval: b]}` | The result of operation `Code` | `operation(code)` (optional) |
| `{g_Group, r…, c…, …}` | The same cells of every table in a group | `table_group(code)` (optional) |

## Prefixes

A `_` after the `t`, `g`, `o` and `p` prefixes is cosmetic, as the DPM-XL
grammar says: `{t_T1}` is `{tT1}`. After `v` it is not: `{v_X}` tests a
filing indicator, `{vX}` reads a parameter. A backtick escapes a code that
is not a plain name: `` {t`C 01.00`} ``.

## Typed parameters

`{p_Name, type}` reads `parameter(Name)` and checks its type. The types are
`number`, `integer`, `string`, `date`, `boolean`, `item` and the set types
`set-number`, `set-string`, `set-date`, `set-item` and so on. Python numbers
become `Number`, text becomes an item or a date for those types, and a list
or set becomes a set ([Sets](sets.md)). A missing value takes the `default`,
or is null.

```python
from dpmxl import MemoryProvider, Number, TableLayout, evaluate_rule

provider = MemoryProvider(
    [TableLayout("T", rows=("0010",), columns=("0010",))],
    {("T", "0010", "0010", None, ()): Number.of(10, 0)},
    parameters={"refPeriod": "2026-12-31", "Limit": 5, "Ccy": "eba_CU:EUR"},
)
for expression in (
    "{p_refPeriod, date} = #2026-12-31#",
    "{p_Limit, number} < {tT, r0010, c0010}",
    "{p_Ccy, item} = [eba_CU:EUR]",
    "{p_Missing, number, default: 3} = 3",
    "{p_Missing, number} = 3",
    "{p_Limit, date} = #2026-01-01#",
):
    result = evaluate_rule(expression, provider)
    print(f"{result.status:15} {result.message or ''}")
```

```text
passed
passed
passed
passed
not_applicable
error           parameter Limit is not a date
```

## Operation references

`{o_Code, …}` evaluates the expression the provider's `operation(code)`
returns, on its own: the referring rule's context, temporaries and
assignments neither reach it nor receive its own. On the result:

- axes keep the matching `r`/`c`/`s` records, dropping a key selected by one
  code;
- `default` fills nulls;
- `interval: false` makes numbers exact.

An operation that refers to itself, directly or through others, is an error.
Without the provider method, the rule is `unsupported`.

## Table groups

`{g_Group, …}` selects from every table the provider's `table_group(code)`
lists. With several tables the records are keyed by the table code `t`, and
the tables must share their keys. Without the provider method, the rule is
`unsupported`.

In static analysis, [`references`][dpmxl.references.references] reports
group and operation reads with `kind` and `code`, and
[`tables(node, provider)`][dpmxl.references.tables] counts a group read as
reading every table of the group ([Analyse rules statically](../guides/analyse.md)).

The language reference gives the syntax of every
[reference](../reference/language.md#references) and [parameter type](../reference/language.md#typed-parameter).
