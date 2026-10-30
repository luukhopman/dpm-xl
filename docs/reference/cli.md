---
description: The dpm-xl command line - check, eval, check-report, list-modules and export-module, every option, the exit statuses and the JSON output schema.
---

# CLI

```text
dpm-xl check [--layouts DATA] [--strict] [--references] [--json] SOURCE
dpm-xl eval [--precondition EXPRESSION] [--format text|json|junit] [--json]
            [--fail-on error|warning] [--all] RULES DATA
dpm-xl check-report [--format text|json|junit] [--json] [--fail-on error|warning]
                    [--all] [--taxonomy-package ZIP] [--previous REPORT]
                    MODULE REPORT
dpm-xl list-modules [--release R] [--json] DATABASE
dpm-xl export-module [--release R] [-o FILE] [--format FORMAT] DATABASE MODULE
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
printed with its severity: an `error` (the expression would fail or select
nothing) fails the run, a `warning` (it evaluates but probably does not
mean what it says) fails it only with `--strict`. Syntax other DPM-XL
engines may reject is a `non-portable` warning (see
[Where dpm-xl differs](language.md#where-dpm-xl-differs)).

The summary counts expressions, not rules: a rule with a precondition is
two expressions, so 4 active rules, 2 of them with a precondition, make
`6/6 expressions parsed`.

| Option | Effect |
| --- | --- |
| `--layouts DATA` | Also check tables, coordinates, open-table keys and, when the tables give `data_types`, operand types against the `tables` of a [data file](data-formats.md#data-files), and names against its `parameters`. |
| `--strict` | Exit with status 1 for a warning too, such as `non-portable`. |
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
  "version": "1.3.0",
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
| `--all` | In text output, list every rule. Without it, only rules that failed, are an error or are unsupported are listed, and the summary line says how many are not. |

```console
$ dpm-xl eval examples/rules.json examples/data.json
v0001: failed
  records: 1 passed, 1 failed, 0 null
  - c=0020: 1,204 should equal 1,211 (1,180 + 31): difference 7, at least 5.5 given the reported precision
v0002: failed (warning)
  records: 1 passed, 1 failed, 0 null
  - qCPI=LEI-B: -5 should exceed 0: difference 5
5 rules: 2 failed, 1 passed, 1 not_applicable, 1 skipped (3 not listed; --all lists every rule)
```

For one expression the output starts with `status:`, and a failing record
without keys is shown as `scalar`:

```console
$ dpm-xl eval "{tC_01.00, r0010, c0010} / 0 > 1" examples/data.json
status: error
message: division by zero
records: 0 passed, 0 failed, 0 null
$ echo $?
1
```

### JSON output

```console
$ dpm-xl eval "{tC_27.00, c0010} > 0" examples/data.json --json
{
  "schema_version": 2,
  "tool": "dpm-xl",
  "version": "1.3.0",
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
that is `error` an error, and a skipped, not applicable or `unsupported`
rule is skipped, with the reason as its message; a failing rule below
`--fail-on` passes, with its failures in `system-out`.

```console
$ dpm-xl eval examples/rules.json examples/data.json --format junit
<?xml version="1.0" encoding="UTF-8"?>
<testsuite name="rules.json" tests="5" failures="1" errors="0" skipped="2">
  <properties>
    <property name="tool" value="dpm-xl" />
    <property name="version" value="1.3.0" />
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

## `dpm-xl check-report`

Checks an xBRL-CSV package or XBRL-XML instance against a
[module file](module-file.md): the EBA filing rules
[dpm-xbrl](https://luukhopman.github.io/dpm-xbrl/) checks, and the module's
rules, evaluated with [`ReportProvider`][dpmxl.xbrl.ReportProvider]. Needs
the `xbrl` extra (`pip install "dpm-xl[xbrl]"`); without it the command
exits with status 2.

| Option | Effect |
| --- | --- |
| `--format text\|json\|junit` | Print text (the default), one JSON document or a JUnit XML report. |
| `--json` | Short for `--format json`. |
| `--fail-on error\|warning` | Exit with status 1 when a filing finding or a failing rule of this severity or worse is found. Default `error`. |
| `--all` | In text output, list every rule, not only those that failed, are an error or are unsupported. |
| `--taxonomy-package ZIP` | A local taxonomy package, repeatable: it resolves xBRL-CSV metadata and adds the filing rules that need the taxonomy. |
| `--previous REPORT` | A report of the same module for an earlier period, repeatable, read with the same taxonomy packages: `time_shift` rules compare with the one whose reference date they need ([Compare with earlier reports](../guides/time-shift.md#against-earlier-xbrl-reports)). Only `REPORT` is checked against the filing rules. |

```console
$ dpm-xl check-report examples/xbrl-module.json examples/xbrl-report
report: examples/xbrl-report (xbrl-csv); module COREP_LR, release 4.2
warning: reports/report.json: 1 extended metadata document could not be resolved offline (http://www.eba.europa.eu/eu/fr/xbrl/crr/fws/corep/4.2/mod/corep_lr.json); tables without resolved metadata use the EBA datapoint/factValue convention
filing rules broken: 0 errors, 0 warnings
e0001: failed
  records: 0 passed, 1 failed, 0 null
  - scalar: 1,045,000 should equal 1,042,000 (812,000 + 190,000 + 40,000): difference 3,000, at least 1,000 given the reported precision
e0003: failed
  records: 1 passed, 1 failed, 0 null
  - qRDT=QW4KNDKKV7QH2LA40639: -12,000 should be at least 0: difference 12,000
e0004: failed (warning)
  records: 1 passed, 1 failed, 0 null
  - qRDT=QW4KNDKKV7QH2LA40639: "QW4KNDKKV7QH2LA4063" does not have the required format
e0007: unsupported (warning)
  message: time_shift needs the report 1 quarter(s) earlier (reference date 2025-12-31), which the provider does not have
  records: 0 passed, 0 failed, 0 null
7 rules: 3 failed, 2 passed, 1 not_applicable, 1 unsupported (3 not listed; --all lists every rule)
```

`e0007` compares with the previous quarter, which one report does not hold;
the message names the reference date of the report it needs. With that
report as `--previous`, the rule is evaluated:

```console
$ dpm-xl check-report examples/xbrl-module.json examples/xbrl-report --previous examples/xbrl-report-previous
report: examples/xbrl-report (xbrl-csv); module COREP_LR, release 4.2
previous: examples/xbrl-report-previous (2025-12-31)
warning: reports/report.json: 1 extended metadata document could not be resolved offline (http://www.eba.europa.eu/eu/fr/xbrl/crr/fws/corep/4.2/mod/corep_lr.json); tables without resolved metadata use the EBA datapoint/factValue convention
filing rules broken: 0 errors, 0 warnings
e0001: failed
  records: 0 passed, 1 failed, 0 null
  - scalar: 1,045,000 should equal 1,042,000 (812,000 + 190,000 + 40,000): difference 3,000, at least 1,000 given the reported precision
e0003: failed
  records: 1 passed, 1 failed, 0 null
  - qRDT=QW4KNDKKV7QH2LA40639: -12,000 should be at least 0: difference 12,000
e0004: failed (warning)
  records: 1 passed, 1 failed, 0 null
  - qRDT=QW4KNDKKV7QH2LA40639: "QW4KNDKKV7QH2LA4063" does not have the required format
e0007: failed (warning)
  records: 0 passed, 1 failed, 0 null
  - scalar: 1,045,000 should be at least 1,062,000 (0.9 × time_shift(1,180,000, Q, 1, refPeriod)): difference 17,000
7 rules: 4 failed, 2 passed, 1 not_applicable (3 not listed; --all lists every rule)
```


The JSON document has the layout of `eval`'s, with more in `summary`
(`filing_errors`, `filing_warnings` and `unplaced_facts`, the facts in no
table of the module) and these fields:

| Field | Type | Content |
| --- | --- | --- |
| `report` | object | `path`, `format`, `entry_point`, `entity_id` and `reference_date` of the report, and `previous`: the `path` and `reference_date` of each `--previous` report. |
| `module` | object | `module` and `release` of the module file. |
| `warnings` | list | dpm-xbrl's warnings about the report, as text. |
| `filing_rules` | list | One object per filing rule broken: `rule`, `title`, `code`, `severity`, `message`, `count` and `examples`, as dpm-xbrl gives them. |
| `results` | list | One object per rule of the module, as for `eval`. |
| `unplaced` | list | The facts in no table of the module: `template`, `datapoint` and `location`. |

In JUnit XML each broken filing rule is a test case (class
`dpm-xbrl.filing-rules`) besides one per rule of the module.

## `dpm-xl list-modules`

Lists the releases of an EBA DPM 2.0 database and the modules of one
release: code, version and name. The database is a SQLite file with the
EBA's table and column names, or the EBA's Access file when `mdb-export`
(mdbtools) is on `PATH`; see
[Start from an EBA DPM release](../guides/from-a-dpm-release.md#2-get-the-database-as-sqlite).

| Option | Effect |
| --- | --- |
| `--release R` | The release whose modules to list, such as `4.3`. Default: the latest release of the database. |
| `--json` | Print one JSON document: `releases` (`id`, `code`, `date`, `type`), `release` and `modules` (`code`, `name`, `version`, `framework`, `release` that introduced the version, `from_date`, `to_date`). |

```console
$ dpm-xl list-modules examples/dpm-demo.sqlite --release 1.0
releases: 1.0, 2.0, 2.0.1
modules of release 1.0: 3
  DEMO   1.0.0    Demo module
  DOCS   1.0.0    Documents
  OTHER  1.0.0    Other module
```

## `dpm-xl export-module`

Writes one module of a release of an EBA DPM 2.0 database as a
[module file](module-file.md): its tables, open keys, cells, filing
indicators and the rules whose scope is the module alone. Notes on the EBA
data it corrects or leaves out go to standard error
([which and why](../guides/from-a-dpm-release.md#eba-data-the-export-corrects-or-leaves-out)).
The module code ignores case.

| Option | Effect |
| --- | --- |
| `--release R` | The release, such as `4.3`. Default: the latest release of the database. |
| `-o FILE`, `--output FILE` | Write the module file to `FILE`, and a summary to standard error. Default: standard output. |
| `--format dpm-module/1\|dpm-synth-template/1` | The file's `format`. Default `dpm-module/1`; dpm-synth 1.0 reads only `dpm-synth-template/1`, which dpm-xl reads too. |

```console
$ dpm-xl export-module examples/dpm-demo.sqlite OTHER
note: OTHER: left out 1 rule whose scope spans several modules: v3
note: OTHER: rule v7551_m: corrected 'trueendif' to 'true endif' (no space before endif)
{
 "format": "dpm-module/1",
 "release": "2.0.1",
 "module": "OTHER",
 "entry_point": "http://www.eba.europa.eu/eu/fr/xbrl/crr/fws/demo/1.0/mod/other.json",
 "reference_date": "2025-03-31",
 "decimals": {
  "m": 0,
  "p": 4,
  "i": 0,
  "r": 2
 },
 "filing_indicators": [
  "O_01.00"
 ],
 "tables": [
  {
   "code": "O_01.00",
   "cells": [
    {
     "id": "O_01.00/r0010/c0010",
     "row": "0010",
     "column": "0010",
     "sheet": null,
     "datapoint": "dp520",
     "data_type": "m"
    }
   ]
  }
 ],
 "rules": [
  {
   "code": "v7551_m",
   "expression": "if {tT_02.00, c0010} > 0 then true else true endif",
   "severity": "warning",
   "active": true,
   "modules": [
    "DEMO",
    "OTHER"
   ]
  }
 ]
}
```

A database that cannot be read, a release or module it does not have, and
a module without tables exit with status 3.

## Exit statuses

The three dpm toolkit commands, dpm-xl, dpm-xbrl and dpm-synth, share these
statuses.

| Status | `check` | `eval` and `check-report` |
| --- | --- | --- |
| 0 | No expression has an error; with `--strict`, none has a warning either. | No rule (or filing finding) at or above `--fail-on` failed. |
| 1 | An expression or precondition has an error, such as a syntax error or an unknown function; with `--strict`, also a warning. | A rule (or filing finding) at or above `--fail-on` failed, or such a rule is `error`. An `unsupported` rule does not count. |
| 2 | Usage error (unknown command or option). | Usage error, or `check-report` without the `xbrl` extra. |
| 3 | The rule file cannot be read or is malformed. | An input file cannot be read or is malformed. |

`list-modules` and `export-module` exit with 0 when done, 2 for a usage
error and 3 for a database, release or module they cannot read.
`dpmxl.cli` names them `EXIT_OK`, `EXIT_FAILED`, `EXIT_USAGE` and
`EXIT_INPUT`.

```console
$ dpm-xl eval "{tC_01.00, r0010, c0010} > 1" missing.json
error: missing.json: no such file
$ echo $?
3
```
