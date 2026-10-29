---
description: The dpm-xl command line - check and eval, every option, the exit statuses and the JSON output schema.
---

# CLI

```text
dpm-xl check [--layouts DATA] [--strict] [--references] [--json] SOURCE
dpm-xl eval [--precondition EXPRESSION] [--format text|json|junit] [--json]
            [--fail-on error|warning] RULES DATA
dpm-xl --version
dpm-xl [COMMAND] --help
```

`dpm-xl` is installed with the package; `python -m dpmxl.cli` runs the same.

## Rule sources

`SOURCE` and `RULES` are one of:

- the path of a `.json` file holding a list of rules
  ([format](data-formats.md#rule-files));
- the path of a [module file](module-file.md), whose rules `check` checks
  against the module's tables (unless `--layouts` is given);
- the path of any other existing file: one expression per line, `#` starts a
  comment line, blank lines are ignored;
- otherwise, the argument itself as one expression. An argument that reads
  as a path (ending in `.json` or `.txt`, or holding a `/` without brackets,
  operators or spaces) but names no file is an error (exit status 3).

Each expression and precondition is labelled in the output: `expression`
for an expression given directly, `<code>:expression` and
`<code>:precondition` for a JSON rule file, `line <n>:expression` for a text
file (`eval` labels the rule itself: `expression`, `<code>` or `line <n>`).
Inactive rules are skipped.

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
expression: {tC_01.00, r0010}
1/1 expressions parsed
$ dpm-xl check "{tC_01.00, r0010} >="
expression: error: expression ends where an operand is expected
{tC_01.00, r0010} >=
                    ^
0/1 expressions parsed; 1 error
$ echo $?
1
$ dpm-xl check "{tC_01.00, r0011, c0010} > 0 or {tC_27.00, r0010, c0010} > 0" --layouts examples/data.json --strict
expression: error: row 0011 is not in table C_01.00; did you mean r0010?
{tC_01.00, r0011, c0010} > 0 or {tC_27.00, r0010, c0010} > 0
           ^~~~~
expression: warning: the rows of C_27.00 are open (key qCPI), so they have no codes such as r0010; select them with r* or leave them out
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
  "schema_version": 2,
  "tool": "dpm-xl",
  "version": "1.2.3",
  "summary": {
    "total": 1,
    "parsed": 1,
    "errors": 0,
    "warnings": 0,
    "skipped": 0
  },
  "skipped": [],
  "errors": [],
  "diagnostics": [],
  "selections": [
    {
      "source": "expression",
      "selection": "{tC_01.00, r0010}"
    }
  ]
}
```

| Field | Type | Content |
| --- | --- | --- |
| `schema_version` | integer | `2`. Changes only when the layout does. |
| `tool`, `version` | string | `dpm-xl` and its version. |
| `summary` | object | `total` expressions and preconditions checked, of which `parsed`; the number of `errors` and `warnings` among the diagnostics; the number of `skipped` inactive rules. |
| `skipped` | list | The codes of the inactive rules, which are not checked. |
| `errors` | list | One object per syntax error: `source` (the label), `message` (plain words), `position` and `end` (zero-based character offsets of the problem in that expression). |
| `diagnostics` | list | One object per problem, syntax errors included: `source` (the label) and the fields of a [`Diagnostic`][dpmxl.diagnostics.Diagnostic]: `severity`, `code`, `message`, `start`, `end`, `subject` and `suggestion`. |
| `selections` | list | Only with `--references`: `source` and `selection` (normalized DPM-XL text) per selection. |

## `dpm-xl eval`

Evaluates every rule of a rule source against a JSON
[data file](data-formats.md#data-files) and explains each failing record.

| Option | Effect |
| --- | --- |
| `--precondition EXPRESSION` | Precondition for a single expression given as `RULES`, such as `{v_C_01.00}`. Rule files carry their own. |
| `--format text\|json\|junit` | Print text (the default), one [JSON document](#json-output_1) or a [JUnit XML report](#junit-xml). |
| `--json` | Short for `--format json`. |
| `--fail-on error\|warning` | Exit with status 1 when a rule of this severity or worse fails. Default `error`: a failing `warning` rule is shown but does not fail the run. |

```console
$ dpm-xl eval examples/rules.json examples/data.json
v0001: failed
  records: 1 passed, 1 failed, 0 null
  - c=0020: 1,204 should equal 1,211 (1,180 + 31): difference 7, at least 5.5 given the reported precision
v0002: failed (warning)
  records: 1 passed, 1 failed, 0 null
  - qCPI=LEI-B: -5 should exceed 0: difference 5
v0003: passed
  records: 1 passed, 0 failed, 0 null
v0004: not_applicable
  message: precondition not met
  records: 0 passed, 0 failed, 0 null
v0005: skipped (inactive rule)
5 rules: 2 failed, 1 passed, 1 not_applicable, 1 skipped
```

For one expression the output starts with `status:`, and a failing record
without keys is shown as `scalar`:

```console
$ dpm-xl eval "{tC_01.00, r0010, c0010} / 0 > 1" examples/data.json
status: error
message: division by zero
records: 0 passed, 0 failed, 0 null
$ echo $?
3
```

### JSON output

```console
$ dpm-xl eval "{tC_27.00, c0010} > 0" examples/data.json --json
{
  "schema_version": 2,
  "tool": "dpm-xl",
  "version": "1.2.3",
  "summary": {
    "rules": 1,
    "passed": 0,
    "failed": 1,
    "not_applicable": 0,
    "error": 0,
    "unsupported": 0,
    "skipped": 0
  },
  "results": [
    {
      "rule": "expression",
      "expression": "{tC_27.00, c0010} > 0",
      "severity": "error",
      "active": true,
      "modules": [],
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
| `schema_version` | integer | `2`. Changes only when the layout does. |
| `tool`, `version` | string | `dpm-xl` and its version. |
| `summary` | object | The number of `rules`, and of rules with each status: `passed`, `failed`, `not_applicable`, `error`, `unsupported` and `skipped`. |
| `results` | list | One object per rule, in source order. |
| `results[].rule` | string | The rule's label: its `code`, `line <n>` or `expression`. |
| `results[].expression` | string | The expression evaluated. |
| `results[].severity` | string | `error` or `warning`, from the rule file; `error` otherwise. |
| `results[].active` | Boolean | Whether the rule is active. |
| `results[].modules` | list | The module codes the rule applies to; empty for every module. |
| `results[].status` | string | `passed`, `failed`, `not_applicable`, `error` or `unsupported`; `skipped` for an inactive rule. |
| `results[].message` | string or null | Why the status is `error`, `unsupported`, `not_applicable` or `skipped`. |
| `results[].counts` | object | `passed`, `failed` and `null` (not evaluated) record counts, as the text output's `records:` line. |
| `results[].failures` | list | Per failing record: `key` (key name to value, as text), `summary` (the explanation sentence) and `cells` (each cell used, as DPM-XL text). |

Summaries and messages may be reworded in minor releases; field names,
statuses and keys may not.

### JUnit XML

`--format junit` writes one test case per rule, for CI systems that show
test reports. A failing rule at or above `--fail-on` is a failure, a rule
that is `error` or `unsupported` an error, and a skipped or not applicable
rule is skipped; a failing rule below `--fail-on` passes, with its failures
in `system-out`.

```console
$ dpm-xl eval examples/rules.json examples/data.json --format junit
<?xml version="1.0" encoding="UTF-8"?>
<testsuite name="rules.json" tests="5" failures="1" errors="0" skipped="2">
  <properties>
    <property name="tool" value="dpm-xl" />
    <property name="version" value="1.2.3" />
  </properties>
  <testcase classname="dpm-xl.rules" name="v0001">
    <failure message="1 failing record" type="error">c=0020: 1,204 should equal 1,211 (1,180 + 31): difference 7, at least 5.5 given the reported precision</failure>
  </testcase>
  <testcase classname="dpm-xl.rules" name="v0002">
    <system-out>1 failing record [warning]
qCPI=LEI-B: -5 should exceed 0: difference 5</system-out>
  </testcase>
  <testcase classname="dpm-xl.rules" name="v0003" />
  <testcase classname="dpm-xl.rules" name="v0004">
    <skipped message="precondition not met" />
  </testcase>
  <testcase classname="dpm-xl.rules" name="v0005">
    <skipped message="inactive rule" />
  </testcase>
</testsuite>
```

## Exit statuses

The three dpm toolkit commands, dpm-xl, dpm-xbrl and dpm-synth, share these
statuses.

| Status | `check` | `eval` |
| --- | --- | --- |
| 0 | Everything parsed; with `--strict`, nothing has an error. | No rule at or above `--fail-on` failed. |
| 1 | An expression or precondition does not parse; with `--strict`, one has an error. | A rule at or above `--fail-on` failed. |
| 2 | Usage error (unknown command or option). | Usage error. |
| 3 | The rule file cannot be read or is malformed. | A rule is `error` or `unsupported`, or the rule or data file cannot be read or is malformed. |

`dpmxl.cli` names them `EXIT_OK`, `EXIT_FAILED`, `EXIT_USAGE` and
`EXIT_INPUT`.

```console
$ dpm-xl eval "{tC_01.00, r0010, c0010} > 1" missing.json
error: missing.json: no such file
$ echo $?
3
```
