---
description: Evaluate every rule of a rule file against one report, in Python or with dpm-xl eval, and read the results.
---

# Evaluate a rule file

A validation run evaluates a few hundred to a few thousand rules, each with an
optional precondition, against one report. This guide does that in Python and
on the command line, using the files in the repository's
[`examples/`](https://github.com/luukhopman/dpm-xl/tree/main/examples) folder.

## Rule files

A rule source is one of:

- a single expression, given on the command line;
- a text file with one expression per line, where `#` starts a comment line
  and blank lines are ignored
  ([`examples/rules.txt`](https://github.com/luukhopman/dpm-xl/blob/main/examples/rules.txt));
- a `.json` file holding a list of objects with `code`, `expression` and an
  optional `precondition`, `severity` (`error` or `warning`), `active` and
  `modules`
  ([`examples/rules.json`](https://github.com/luukhopman/dpm-xl/blob/main/examples/rules.json)).

```json
[
  {
    "code": "v0001",
    "expression": "with {tC_01.00, c*, default: 0, interval: true}: {r0010} = {r0020} + {r0030}",
    "precondition": "{v_C_01.00}"
  },
  {"code": "v0002", "expression": "{tC_27.00, c0010} > 0", "severity": "warning"},
  {"code": "v0005", "expression": "{tC_01.00, r0010, c0010} > 1000", "active": false}
]
```

An inactive rule, such as one the EBA has deactivated, is skipped.

[Data formats](../reference/data-formats.md#rule-files) has the details.

## In Python

Share one [`SelectionCache`][dpmxl.evaluator.SelectionCache] across the rules
of a report, so each selection is read from the provider once. Parsing is
memoized for you ([`parse_cached`][dpmxl.evaluator.parse_cached]).

```python
import json
from pathlib import Path

from dpmxl import SelectionCache, evaluate_rule, explain
from dpmxl.cli import load_memory_provider
from dpmxl.rules import load_rules

provider = load_memory_provider(json.loads(Path("examples/data.json").read_text()))
rules = load_rules("examples/rules.json")

cache = SelectionCache()
for rule in rules:
    if not rule.active:
        print(f"{rule.code}: skipped")
        continue
    result = evaluate_rule(
        rule.expression, provider, precondition=rule.precondition, cache=cache
    )
    print(f"{rule.code} [{rule.severity}]: {result.status}")
    for outcome in result.failures:
        explanation = explain(result.evaluation, rule.expression, outcome.key)
        print("  ", explanation.summary)
```

```text
v0001 [error]: failed
   1,204 should equal 1,211 (1,180 + 31): difference 7, at least 5.5 given the reported precision
v0002 [warning]: failed
   -5 should exceed 0: difference 5
v0003 [error]: passed
v0004 [error]: not_applicable
v0005: skipped
```

[`load_rules`][dpmxl.rules.load_rules] reads a rule file into
[`Rule`][dpmxl.rules.Rule] objects. `load_memory_provider` builds the
in-memory report the CLI reads from a
[data file](../reference/data-formats.md#data-files); in your application the
provider is your own ([Connect your data](provider.md)).

Each result has one of five statuses:

| Status | Meaning |
| --- | --- |
| `passed` | At least one record held and none failed. |
| `failed` | At least one record failed; `result.failures` lists them. |
| `not_applicable` | The precondition was not met, or no record could be evaluated (all null). |
| `error` | Syntax error, unknown table, type mismatch, or a division by zero that reaches the result; `result.message` says which. |
| `unsupported` | A `time_shift`, `{o_…}` or `{g_…}` the provider cannot resolve. |

[Preconditions and results](../concepts/results.md) explains each one.
`evaluate_rule` never raises for a bad rule or bad data, so one broken rule
does not stop the run.

## On the command line

`dpm-xl eval` evaluates a rule source against a data file and explains every
failure:

```console
$ dpm-xl eval examples/rules.txt examples/data.json
line 2: failed
  records: 1 passed, 1 failed, 0 not evaluated
  - c=0020: 1,204 should equal 1,211 (1,180 + 31): difference 7, at least 5.5 given the reported precision
line 3: failed
  records: 1 passed, 1 failed, 0 not evaluated
  - qCPI=LEI-B: -5 should exceed 0: difference 5
line 4: passed
  records: 1 passed, 0 failed, 0 not evaluated
3 rules: 2 failed, 1 passed
```

A single expression takes its precondition from `--precondition`:

```console
$ dpm-xl eval "{tC_01.00, r0010, c0010} > 200" examples/data.json --precondition "{v_C_01.00}"
status: failed
records: 0 passed, 1 failed, 0 not evaluated
- scalar: 100 should exceed 200: difference 100
```

`--json` prints the same results as one JSON document for other programs:

```console
$ dpm-xl eval "{tC_27.00, c0010} > 0" examples/data.json --json
{
  "schema_version": 1,
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

The exit status is 0 when every rule passed or did not apply, 1 when a rule
failed and 3 when a rule is an error or unsupported, or the input cannot be
read. The [CLI reference](../reference/cli.md) lists every option and the JSON
layout.
