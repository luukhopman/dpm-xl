---
description: The JSON rule file and data file formats that dpm-xl check and dpm-xl eval read.
---

# Data formats

The CLI reads two JSON formats: rule files and data files. Python callers
normally build a provider instead
([Connect your data](../guides/provider.md)); the CLI's
[`load_memory_provider(document)`][dpmxl.provider.load_memory_provider]
turns a data document into a
[`MemoryProvider`][dpmxl.provider.MemoryProvider] if you want the same
format in Python. The `--json` output of the CLI is described in the
[CLI reference](cli.md#json-output).

## Rule files

A `.json` rule file is a list of objects, one per rule
([`examples/rules.json`](https://github.com/luukhopman/dpm-xl/blob/main/examples/rules.json)):

| Field | Type | Content |
| --- | --- | --- |
| `code` | string | The rule's label in the output. Defaults to the rule's 1-based position. |
| `expression` | string | The rule. A rule without one is skipped. |
| `precondition` | string, optional | An expression that must yield a true record for the rule to apply. |
| `severity` | string, optional | `error` (the default) or `warning`. Shown in the output. |
| `active` | Boolean, optional | `false` skips the rule, as for a rule the EBA has deactivated; it is reported as `skipped`. Default `true`. |
| `modules` | list of strings, optional | The module codes the rule applies to, such as `["COREP_OF"]`; none for every module. |
| `source` | string, optional | Who defines the rule, such as `eba`. Informative. |

`expression` and `precondition` may also be objects with an `expression`
field, as some rule exports nest them. Other fields are ignored.
[`load_rules`][dpmxl.rules.load_rules] reads a rule file in Python. A file
that does not hold a list, or a field of the wrong type, is an error (exit
status 3) that names the field by its JSON path:

```console
$ dpm-xl check tests/data/bad-severity.json
error: tests/data/bad-severity.json: [0].severity: expected "error" or "warning", got "fatal"
```

```json
[
  {
    "code": "v0001",
    "expression": "with {tC_01.00, c*, default: 0, interval: true}: {r0010} = {r0020} + {r0030}",
    "precondition": "{v_C_01.00}"
  },
  {"code": "v0002", "expression": "{tC_27.00, c0010} > 0"}
]
```

Any other file is a text rule file: one expression per line, `#` starts a
comment line, blank lines are ignored
([`examples/rules.txt`](https://github.com/luukhopman/dpm-xl/blob/main/examples/rules.txt)).

## Data files

A data file is one JSON object describing a report
([`examples/data.json`](https://github.com/luukhopman/dpm-xl/blob/main/examples/data.json)).
Every field is optional.

| Field | Type | Content |
| --- | --- | --- |
| `tables` | list | Table layouts: `code`; `rows`, `columns` and `sheets` (lists of codes); `open_keys` (key names of an open table); `template` (a template code whose filing indicator `{v_…}` this table answers); `open_axes` (which of `rows`, `columns` and `sheets` are open, identified by the open keys); `data_types` (cells' data types, each `row`, `column`, `sheet` and `type`: `number`, `integer`, `string`, `date`, `boolean` or `item`). The last two are optional and used only by [`dpm-xl check --layouts`](cli.md#dpm-xl-check). |
| `facts` | list | Reported values, below. |
| `reported` | list | Table or template codes with a positive filing indicator. Defaults to every table with a fact. |
| `parameters` | object | Report parameters by name, typed like fact values; a list is a set. |
| `table_groups` | object | Group code to a list of table codes, for `{g_…}`. |
| `operations` | object | Operation code to its expression, for `{o_…}`. |
| `earlier` | list | Other periods' reports for `time_shift`: `period` (`A`, `S`, `Q`, `M`, `W` or `D`), `count` (periods earlier, negative for later) and `data`, a nested data document. |

### Facts

| Field | Type | Content |
| --- | --- | --- |
| `table` | string | Table code (required). |
| `row`, `column`, `sheet` | string, optional | Closed coordinates; omit the ones the table does not have. |
| `keys` | object, optional | Open key components by name, for open tables. |
| `value` | any | The value; `null` for a nil fact. |
| `decimals` | integer or `"INF"`, optional | XBRL decimals of a number; `"INF"` or absent means exact. |
| `type` | string, optional | `number`, `item` or `date`, to read a string value as that type. |

Values are typed as follows: JSON numbers (and strings with `"type":
"number"`) become `Number` with the given `decimals`; strings starting with
`[` (or with `"type": "item"`) become items such as `[eba_CU:EUR]`; strings
with `"type": "date"` become dates; lists become sets; Booleans and other
strings stay as they are. Open key values are typed the same way, without
`type`.

### Example

This document uses every field; the Python below loads it the way
`dpm-xl eval` does and evaluates a rule against each part.

```python
from dpmxl import evaluate_rule
from dpmxl.provider import load_memory_provider

document = {
    "tables": [
        {"code": "C_01.00", "rows": ["0010", "0020"], "columns": ["0010"]},
        {
            "code": "C_27.00",
            "columns": ["0010", "0020", "0030"],
            "open_keys": ["qCPI"],
            "template": "C_27",
            "open_axes": ["rows"],
            "data_types": [{"column": "0010", "type": "number"}],
        },
    ],
    "facts": [
        {
            "table": "C_01.00",
            "row": "0010",
            "column": "0010",
            "value": 1204,
            "decimals": 0,
        },
        {
            "table": "C_01.00",
            "row": "0020",
            "column": "0010",
            "value": "1180.5",
            "decimals": "INF",
            "type": "number",
        },
        {
            "table": "C_27.00",
            "column": "0010",
            "keys": {"qCPI": "LEI-A"},
            "value": 120,
            "decimals": -3,
        },
        {
            "table": "C_27.00",
            "column": "0020",
            "keys": {"qCPI": "LEI-A"},
            "value": "[eba_CU:EUR]",
        },
        {
            "table": "C_27.00",
            "column": "0030",
            "keys": {"qCPI": "LEI-A"},
            "value": "2026-06-30",
            "type": "date",
        },
    ],
    "reported": ["C_01.00", "C_27.00"],
    "parameters": {
        "refPeriod": "2026-12-31",
        "Currencies": ["[eba_CU:EUR]", "[eba_CU:USD]"],
    },
    "table_groups": {"G_01": ["C_01.00"]},
    "operations": {"v0001_a": "{tC_01.00, r0010, c0010} * 2"},
    "earlier": [
        {
            "period": "Q",
            "count": 1,
            "data": {
                "tables": [{"code": "C_01.00", "rows": ["0010"], "columns": ["0010"]}],
                "facts": [
                    {
                        "table": "C_01.00",
                        "row": "0010",
                        "column": "0010",
                        "value": 1100,
                        "decimals": 0,
                    }
                ],
            },
        },
    ],
}
provider = load_memory_provider(document)
for expression in (
    "{tC_01.00, r0010, c0010} > {tC_01.00, r0020, c0010}",
    "{tC_27.00, c0020} in {p_Currencies, set-item}",
    "{tC_27.00, c0030} < {p_refPeriod, date}",
    "{v_C_27}",
    "{g_G_01, r0010, c0010} > 0",
    "{o_v0001_a} > 2000",
    "{tC_01.00, r0010, c0010} >= time_shift({tC_01.00, r0010, c0010}, Q, 1)",
):
    print(evaluate_rule(expression, provider).status, expression)
```

```text
passed {tC_01.00, r0010, c0010} > {tC_01.00, r0020, c0010}
passed {tC_27.00, c0020} in {p_Currencies, set-item}
passed {tC_27.00, c0030} < {p_refPeriod, date}
passed {v_C_27}
passed {g_G_01, r0010, c0010} > 0
passed {o_v0001_a} > 2000
passed {tC_01.00, r0010, c0010} >= time_shift({tC_01.00, r0010, c0010}, Q, 1)
```

A malformed document is reported as `error: …` with exit status 3: an
invalid value (a number that does not parse, `decimals` that is neither an
integer nor `INF` or is beyond the decimal128 range) names the fact by its
1-based position, as in `error: fact 1: invalid number 'x1'`; a missing
required field such as `table` gives `malformed data document`.
