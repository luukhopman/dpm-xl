---
description: The dpm-xl command line - check and eval, every option, the exit statuses and the JSON output schema.
---

# CLI

```text
dpm-xl check [--layouts DATA] [--strict] [--references] [--json] SOURCE
dpm-xl eval [--precondition EXPRESSION] [--json] RULES DATA
dpm-xl --version
dpm-xl [COMMAND] --help
```

`dpm-xl` is installed with the package; `python -m dpmxl.cli` runs the same.

## Rule sources

`SOURCE` and `RULES` are one of:

- the path of a `.json` file holding a list of rules
  ([format](data-formats.md#rule-files));
- the path of any other existing file: one expression per line, `#` starts a
  comment line, blank lines are ignored;
- otherwise, the argument itself as one expression. An argument that reads
  as a path (ending in `.json` or `.txt`, or holding a `/` without brackets,
  operators or spaces) but names no file is an error (exit status 3).

Each expression and precondition is labelled in the output: `argument` for
an expression given directly, `<code>:expression` and `<code>:precondition`
for a JSON rule file, `line <n>:expression` for a text file (`eval` labels
the rule itself: `argument` becomes `expression`, the others `<code>` and
`line <n>`).

## `dpm-xl check`

Checks every expression and precondition of a rule source with
[`diagnose`][dpmxl.diagnostics.diagnose]: every syntax error, unknown
functions, calls with the wrong operands and selections without a table.
Expressions may be scripts with `;`, `:=` and `<-`. Every problem is
printed; the exit status is 1 when an expression does not parse, or with
`--strict` when any expression has an error. Warnings never change it.

| Option | Effect |
| --- | --- |
| `--layouts DATA` | Also check tables, coordinates, open-table keys and, when the tables give `data_types`, operand types against the `tables` of a [data file](data-formats.md#data-files), and names against its `parameters`. |
| `--strict` | Exit with status 1 for any error, not only for syntax errors. |
| `--references` | Also print every selection, with its `with` context applied. |
| `--json` | Print one JSON document instead of text. |

```console
$ dpm-xl check "with {tC_01.00}: {r0010} >= 0" --references
argument: {tC_01.00, r0010}
1/1 expressions parsed
$ dpm-xl check "{tC_01.00, r0010} >="
argument: error: expression ends where an operand is expected
{tC_01.00, r0010} >=
                    ^
0/1 expressions parsed; 1 error
$ echo $?
1
$ dpm-xl check "{tC_01.00, r0011, c0010} > 0 or {tC_27.00, r0010, c0010} > 0" --layouts examples/data.json --strict
argument: error: row 0011 is not in table C_01.00; did you mean r0010?
{tC_01.00, r0011, c0010} > 0 or {tC_27.00, r0010, c0010} > 0
           ^~~~~
argument: warning: the rows of C_27.00 are open (key qCPI), so they have no codes such as r0010; select them with r* or leave them out
{tC_01.00, r0011, c0010} > 0 or {tC_27.00, r0010, c0010} > 0
                                           ^~~~~
1/1 expressions parsed; 1 error and 1 warning
$ echo $?
1
```

Problems go to standard error; the summary goes to standard output.

### JSON output

```console
$ dpm-xl check "with {tC_01.00}: {r0010} >= 0" --references --json
{
  "schema_version": 1,
  "parsed": 1,
  "total": 1,
  "errors": [],
  "diagnostics": [],
  "selections": [
    {
      "source": "argument",
      "selection": "{tC_01.00, r0010}"
    }
  ]
}
```

| Field | Type | Content |
| --- | --- | --- |
| `schema_version` | integer | `1`. Changes only with a new major release. |
| `parsed` | integer | Expressions and preconditions that parsed. |
| `total` | integer | Expressions and preconditions checked. |
| `errors` | list | One object per syntax error: `source` (the label), `message` (plain words), `position` and `end` (zero-based character offsets of the problem in that expression). |
| `diagnostics` | list | One object per problem, syntax errors included: `source` (the label) and the fields of a [`Diagnostic`][dpmxl.diagnostics.Diagnostic]: `severity`, `code`, `message`, `start`, `end`, `subject` and `suggestion`. |
| `selections` | list | Only with `--references`: `source` and `selection` (normalized DPM-XL text) per selection. |

## `dpm-xl eval`

Evaluates every rule of a rule source against a JSON
[data file](data-formats.md#data-files) and explains each failing record.

| Option | Effect |
| --- | --- |
| `--precondition EXPRESSION` | Precondition for a single expression given as `RULES`, such as `{v_C_01.00}`. Rule files carry their own. |
| `--json` | Print one JSON document instead of text. |

```console
$ dpm-xl eval examples/rules.json examples/data.json
v0001: failed
  records: 1 passed, 1 failed, 0 not evaluated
  - c=0020: 1,204 should equal 1,211 (1,180 + 31): difference 7, at least 5.5 given the reported precision
v0002: failed
  records: 1 passed, 1 failed, 0 not evaluated
  - qCPI=LEI-B: -5 should exceed 0: difference 5
v0003: passed
  records: 1 passed, 0 failed, 0 not evaluated
v0004: not_applicable
  message: precondition not met
  records: 0 passed, 0 failed, 0 not evaluated
4 rules: 2 failed, 1 passed, 1 not_applicable
```

For one expression the output starts with `status:`, and a failing record
without keys is shown as `scalar`:

```console
$ dpm-xl eval "{tC_01.00, r0010, c0010} / 0 > 1" examples/data.json
status: error
message: division by zero
records: 0 passed, 0 failed, 0 not evaluated
$ echo $?
3
```

### JSON output

```console
$ dpm-xl eval "{tC_27.00, c0010} > 0" examples/data.json --json
{
  "schema_version": 1,
  "results": [
    {
      "rule": "expression",
      "expression": "{tC_27.00, c0010} > 0",
      "status": "failed",
      "message": null,
      "counts": {
        "passed": 1,
        "failed": 1,
        "null": 0
      },
      "failures": [
        {
          "key": {
            "qCPI": "LEI-B"
          },
          "summary": "-5 should exceed 0: difference 5",
          "cells": [
            "{tC_27.00, c0010, qCPI=LEI-B}"
          ]
        }
      ]
    }
  ]
}
```

| Field | Type | Content |
| --- | --- | --- |
| `schema_version` | integer | `1`. Changes only with a new major release. |
| `results` | list | One object per rule, in source order. |
| `results[].rule` | string | The rule's label: its `code`, `line <n>` or `expression`. |
| `results[].expression` | string | The expression evaluated. |
| `results[].status` | string | `passed`, `failed`, `not_applicable`, `error` or `unsupported`. |
| `results[].message` | string or null | Why the status is `error`, `unsupported` or `not_applicable`. |
| `results[].counts` | object | `passed`, `failed` and `null` (not evaluated) record counts. |
| `results[].failures` | list | Per failing record: `key` (key name to value, as text), `summary` (the explanation sentence) and `cells` (each cell used, as DPM-XL text). |

Summaries and messages may be reworded in minor releases; field names,
statuses and keys may not.

## Exit statuses

| Status | `check` | `eval` |
| --- | --- | --- |
| 0 | Everything parsed; with `--strict`, nothing has an error. | Every rule passed or did not apply. |
| 1 | An expression or precondition does not parse; with `--strict`, one has an error. | A rule failed. |
| 2 | Usage error (unknown command or option). | Usage error. |
| 3 | The rule file cannot be read or is malformed. | A rule is `error` or `unsupported`, or the rule or data file cannot be read or is malformed. |

With several rules, `eval` exits with the highest status of any rule.

```console
$ dpm-xl eval "{tC_01.00, r0010, c0010} > 1" missing.json
error: [Errno 2] No such file or directory: 'missing.json'
$ echo $?
3
```
