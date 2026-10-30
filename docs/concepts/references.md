---
description: Filing indicators, report parameters, typed parameters, operation references and table groups, and the reference prefixes.
---

# Parameters, operations and table groups

Besides table cells, a rule can read report-level data and other rules'
results. Each kind of reference goes to a provider method
([Connect your data](../guides/provider.md)).

| Reference | Reads | Provider method |
| --- | --- | --- |
| `{v_C_01.00}`, `{vC_01.00}` | Whether table or template `C_01.00` was reported (its filing indicator) | `table_reported(table)` |
| `{vName}`, `{v_Name}` | Report parameter `Name`, as given | `parameter(name)` |
| `{p_Name, type[, default: v]}` | Report parameter `Name`, checked against a type | `parameter(name)` |
| `{o_Code[, r…, c…, default: v, interval: b]}` | The result of operation `Code` | `operation(code)` (optional) |
| `{g_Group, r…, c…, …}` | The same cells of every table in a group | `table_group(code)` (optional) |

## Prefixes

A `_` after a prefix is cosmetic, as the DPM-XL specification says
(§3.1.1): `{t_T1}` is `{tT1}` and `{v_X}` is `{vX}`. A backtick escapes a
code that is not a plain name: `` {t`C 01.00`} ``.

## Variables

`{vX}` and `{v_X}` both read variable `X` of the report
([`read_variable`][dpmxl.provider.read_variable]):

- when `X` has the shape of an EBA template code, such as `C_01.00` or
  `F_01.01.dp`, or the provider's optional `is_template(code)` knows it, the
  variable is that template's filing indicator, `table_reported(X)`;
- otherwise it is report parameter `X`, `parameter(X)`;
- either is null when the provider does not know it.

A template is an EBA reporting form, such as `C_07.00`, and is filed
under one filing indicator; it may be split into several tables, such as
`C_07.00.a` and `C_07.00.b`, which rules select by table code. In the EBA
rules every `{v_…}` names a template and `{vReportingLevel}` is
the only parameter, so both spellings keep their usual meaning.

```python
from dpmxl import MemoryProvider, TableLayout, evaluate_rule, parse

provider = MemoryProvider(
    [TableLayout("T", rows=("0010",))],
    {},
    reported=["C_01.00"],
    parameters={"ReportingLevel": "con"},
)
for expression in (
    "{v_C_01.00}",
    "{vC_02.00}",
    '{vReportingLevel} = "con"',
    '{v_ReportingLevel} = "con"',
    "{vT}",
):
    print(expression, evaluate_rule(expression, provider).status)
```

```text
{v_C_01.00} passed
{vC_02.00} failed
{vReportingLevel} = "con" passed
{v_ReportingLevel} = "con" passed
{vT} failed
```

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

`{o_Code, …}` reads temporary `Code` of the same script (`Code := …`), or
else evaluates the expression the provider's `operation(code)` returns, on
its own: the referring rule's context, temporaries and
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
