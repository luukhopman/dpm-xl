---
description: The dpm-module/1 JSON format - one module's tables, cells, open keys, datapoints and rules - shared with dpm-synth's template format, and how dpm-xl reads it.
---

# Module file

A module file describes one module of a DPM release, such as `COREP_OF`:
its tables, the cells of each table and the datapoint each cell carries, and
the rules a report of the module must satisfy. It is a JSON document (UTF-8)
in the `dpm-module/1` format, read by
[`load_module`][dpmxl.module.load_module]. dpm-synth's
[`dpm-synth-template/1`](https://luukhopman.github.io/dpm-synth/reference/template-format/)
has the same fields, so one file serves both tools: dpm-synth generates
reports from it, and dpm-xl checks its rules and evaluates them on a report
([`dpm-xl check-report`](cli.md#dpm-xl-check-report)). dpm-synth 1.0
reads a file only with `"format": "dpm-synth-template/1"`.
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
| `entry_point` | string or null | no | The module's xBRL-CSV entry point. |
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
| `filing_indicator` | string or null | no | The filing indicator the table is reported under, such as `"C_07.00"`. Default: the code. |
| `open_keys` | array | no | The keys of an open table: `code` (as rules name it, such as `"qCPI"`), `column` (its column in the xBRL-CSV file; default the code, unique in the table), `data_type` (of a typed key: `i` integers, `d` dates, other codes text) and `items` (the item qnames of an enumerated key). |
| `cells` | array | yes | At least one [cell](#cells). |

## Cells

| Field | Type | Required | Meaning |
| --- | --- | --- | --- |
| `id` | string | yes | An identifier of the cell, unique within the module. |
| `datapoint` | string | yes | The datapoint code, such as `"dp12345"`, that places a reported fact in the cell. |
| `row`, `column`, `sheet` | string or null | no | The cell's codes, such as `"0010"`, without the `r`, `c` or `s`; null for a table without that axis, `"*"` for every row (or sheet) of an open table. |
| `data_type` | string or null | no | The DPM data type: `m` monetary, `p` percentage, `i` integer, `r` decimal, `e` item, `es` item set, `b` Boolean, `d` date, anything else text. |
| `items` | array of strings or null | no | The item qnames of an `e` or `es` cell. |
| `unit` | Boolean or null | no | `true` for a monetary cell reported in its currency of denomination. |

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
indicator differs from its code answers `{v_…}` for that template. With the
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
