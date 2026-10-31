---
description: The dpm-module/1 JSON format - one module's tables, cells, open keys, datapoints and rules - read by dpm-xl and dpm-synth, and how dpm-xl reads it.
---

# Module file

A module file describes one module of a DPM release, such as `COREP_OF`:
its tables, the cells of each table and the datapoint each cell carries, and
the rules a report of the module must satisfy. It is a JSON document (UTF-8)
in the `dpm-module/1` format, read by
[`load_module`][dpmxl.module.load_module]. dpm-synth's
[`dpm-synth-template/1`](https://luukhopman.github.io/dpm-synth/reference/template-format/)
has the same fields, and each tool reads both formats, so one file serves
both: dpm-synth generates reports from it, and dpm-xl checks its rules and
evaluates them on a report
([`dpm-xl check-report`](cli.md#dpm-xl-check-report)).
[`dpm-xl export-module`](cli.md#dpm-xl-export-module) writes one for a
module of an EBA DPM release; see
[Start from an EBA DPM release](../guides/from-a-dpm-release.md).

## Example

[`examples/module.json`](https://github.com/luukhopman/dpm-xl/blob/main/examples/module.json)
describes the tables of the [example data file](data-formats.md#data-files):

```json
{
  "format": "dpm-module/1",
  "release": "4.2",
  "module": "DEMO",
  "reference_date": "2026-12-31",
  "currency": "EUR",
  "decimals": {"m": 0},
  "filing_indicators": ["C_01.00", "C_27.00"],
  "tables": [
    {
      "code": "C_01.00",
      "cells": [
        {"id": "C_01.00/r0010/c0010", "row": "0010", "column": "0010", "datapoint": "dp1", "data_type": "m"},
        …
      ]
    },
    {
      "code": "C_27.00",
      "open_keys": [{"code": "qCPI", "data_type": "s"}],
      "cells": [
        {"id": "C_27.00/c0010", "row": "*", "column": "0010", "datapoint": "dp7", "data_type": "m"}
      ]
    }
  ],
  "rules": [
    {"code": "v0002", "expression": "{tC_27.00, c0010} > 0", "severity": "warning"},
    …
  ]
}
```

## The module

| Field | Type | Required | Meaning |
| --- | --- | --- | --- |
| `format` | string | yes | `"dpm-module/1"`, or `"dpm-synth-template/1"`. |
| `release` | string | yes | The DPM release, such as `"4.2"`. |
| `module` | string | yes | The module code, such as `"COREP_OF"`. A rule naming `modules` applies only to those. |
| `entry_point` | string or null | no | The module's xBRL-CSV entry point; `ReportProvider` rejects a report of another one. |
| `reference_date` | string or null | no | The reference date, `YYYY-MM-DD`. |
| `currency` | string or null | no | The reporting currency, an ISO 4217 code such as `"EUR"`. |
| `decimals` | object | no | Reporting decimals by data type code, such as `{"m": -3}`; whole numbers from -20 to 20. A report's own `decimals…` parameters take precedence. |
| `filing_indicators` | array of strings | no | The filing indicators of every template of the module; unique, and including every table's `filing_indicator`. |
| `tables` | array | yes | At least one [table](#tables). |
| `rules` | array | no | The [rules](#rules). |

## Tables

| Field | Type | Required | Meaning |
| --- | --- | --- | --- |
| `code` | string | yes | The table code, such as `"C_07.00.a"`, as rules name it. Unique, ignoring case. |
| `filing_indicator` | string or null | no | The filing indicator the table is reported under, such as `"C_07.00"`. Default: the code. A filing indicator that is no table's code stands for its tables in rules ([groups of tables](#groups-of-tables)). |
| `open_keys` | array | no | The keys of an open table: `code` (as rules name it, such as `"qCPI"`), `column` (its column in the xBRL-CSV file; default the code, unique in the table), `data_type` (of a typed key: `i` and `o` integers, `d` and `dt` dates, other codes text) and `items` (the item qnames of an enumerated key; `[]` allows none). |
| `cells` | array | yes | At least one [cell](#cells). |

### Groups of tables

A selected table code that is not the `code` of a table, ignoring case,
selects every table whose `filing_indicator` equals it, ignoring case. This
is how a module file describes an abstract table of the DPM
(`TableVersion.AbstractTableID`): in DPM 4.0, `C_02.00` is the abstract
table of `C_02.00.a` and `C_02.00.b`, the export writes
`"filing_indicator": "C_02.00"` on both, and a rule that selects
`{tC_02.00, …}` reads the cells of both. The module file has no other field
for it; a table's own code always wins.

Rows, columns and sheets are selected as written, in each table that has
them; each cell keeps its own table and the open keys its table has, so a
cell of a table without a key has no value for it. Two cells of different
tables with the same keys in the selection, such as `r0010` and `c0010` in
both, cannot be told apart, and the rule is an error.
DPM-XL v0.11 (operators §3.1.2) defines `table` as the code of a DPM Report
table and says nothing about abstract tables; dpm-xl reads one as the
tables it groups.

## Cells

| Field | Type | Required | Meaning |
| --- | --- | --- | --- |
| `id` | string | yes | An identifier of the cell, unique within the module. |
| `datapoint` | string | yes | The datapoint code, such as `"dp12345"`, that places a reported fact in the cell. |
| `row`, `column`, `sheet` | string or null | no | The cell's codes, such as `"0010"`, without the `r`, `c` or `s`; null for a table without that axis, `"*"` for every row (or sheet) of an open table. |
| `data_type` | string or null | no | The DPM data type, as in the `DataType` table of the EBA's DPM database: `m` monetary, `p` percentage, `i` integer, `r` decimal, `o` ordinal, `e` item (enumeration), `b` Boolean, `t` true (a Boolean that can only be true), `d` date, `dt` date or date and time, `s` text, `es` text that may be empty, `u` URI; anything else text. |
| `items` | array of strings or null | no | The item qnames of an `e` cell; `[]` allows none, and a missing or null `items` any. Ignored for other data types. |
| `unit` | Boolean or null | no | `true` for a monetary cell reported in its currency of denomination. |

A report's values are written as in xBRL-CSV, and
[`ReportProvider`][dpmxl.xbrl.ReportProvider] reads them by the cell's data
type: `m`, `p`, `i` and `r` as numbers with their decimals; `o` as an exact
whole number, such as `3`; `e` as an item, such as `eba_CU:EUR`; `b` as a
Boolean, `true` or `false`, and `t` as `true` only (`false` is an
`invalidValue`); `d` as a date, `2026-12-31`, and `dt` as a date or date
and time read as its date; a time zone is dropped (`2026-12-31Z` reads as
2026-12-31, and `2026-12-31T12:00:00` as 2026-12-31 in a `dt` cell); `s`,
`es` and `u` as text. A value that does not read as its type, such as `NaN` for
a number, is an `invalidValue` finding, and no rule reads it. An `es`
value may be the empty string, which is a value, not null; EBA filing
rule 2.19 forbids reporting it (`#empty` in xBRL-CSV). No module of DPM
4.3 or 4.4 has a `dt`, `u` or `o` datapoint.

Module files use the DPM's own codes, as the EBA database has them. The
`data_types` of a [data file](data-formats.md#data-files), and of a
[`TableLayout`][dpmxl.provider.TableLayout], use the few types that
`dpm-xl check` compares, and DPM-XL has its own value types.
[`cell_type`][dpmxl.module.cell_type] maps the first to the second:

| `data_type` | Data file type | DPM-XL value |
| --- | --- | --- |
| `m`, `p`, `r` | `number` | number |
| `i`, `o` | `integer` | number (whole) |
| `e` | `item` | item |
| `b`, `t` | `boolean` | Boolean |
| `d` | `date` | date |
| `dt` | none (not checked) | date (a time is dropped) |
| `s`, `es`, `u`, other codes | `string` | text |

## Rules

Rules have the fields of a [rule file](data-formats.md#rule-files): `code`
(required, unique), `expression` (required), `precondition`, `severity`
(`error` or `warning`), `active`, `modules` and `source` (default `"eba"`).

## In Python

[`load_module`][dpmxl.module.load_module] reads a file or a parsed
document. [`Module.layouts`][dpmxl.module.Module.layouts] gives the
[`TableLayout`][dpmxl.provider.TableLayout]s that
[`diagnose`][dpmxl.diagnostics.diagnose] checks rules against, and
[`Module.rules`][dpmxl.module.Module] the [`Rule`][dpmxl.rules.Rule]s:

```python
from dpmxl import diagnose
from dpmxl.module import load_module

module = load_module("examples/module.json")
layouts = {layout.code: layout for layout in module.layouts()}
print(layouts["C_27.00"])
for rule in module.rules:
    problems = diagnose(rule.expression, layouts.get, tables=tuple(layouts))
    print(rule.code, rule.severity, rule.active, len(problems))
```

```text
TableLayout(code='C_27.00', rows=(), columns=('0010',), sheets=(), open_keys=('qCPI',), template=None, open_axes=('rows',))
v0001 error True 0
v0002 warning True 0
v0003 error True 0
v0005 error False 0
```

An axis whose every cell is `"*"` is open, and a table whose filing
indicator differs from its code answers `{v_…}` for that template.
[`Module.layout`][dpmxl.module.Module.layout] looks a code up the way
rules select it: a table, or the tables of a filing indicator
([`Module.abstract_tables`][dpmxl.module.Module.abstract_tables]). With the
`xbrl` extra, [`ReportProvider`][dpmxl.xbrl.ReportProvider] evaluates the
rules on a report read with dpm-xbrl.

On the command line, a module file is a rule source like a rule file:
`dpm-xl check` checks its rules against its tables, and `dpm-xl eval`
evaluates them against a data file.

```console
$ dpm-xl check examples/module.json
4/4 expressions parsed; 1 inactive rule skipped
```

## Validation

[`load_module`][dpmxl.module.load_module] raises
[`ModuleError`][dpmxl.module.ModuleError] for the first problem, naming
the field by its JSON path. Fields it does not know, such as dpm-synth's
generation settings, are ignored.

```python
import json
from pathlib import Path

from dpmxl.module import ModuleError, load_module

document = json.loads(Path("examples/module.json").read_text(encoding="utf-8"))
document["tables"][0]["cells"][1]["datapoint"] = 1002
try:
    load_module(document)
except ModuleError as error:
    print(error)
```

```text
tables[0].cells[1].datapoint: expected a non-empty string, got the number 1002
```

The command line reports an invalid module file with exit status 3.
