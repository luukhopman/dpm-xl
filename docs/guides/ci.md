---
description: Fail a CI job when a rule in a rule repository does not parse, with dpm-xl check or a pytest test.
---

# Check rule syntax in CI

A repository of rules (exported from a DPM release, or written by hand)
should never hold an expression that does not parse. `dpm-xl check` parses
every expression and precondition of a rule source and exits with status 1
when any of them fails. With `--strict` it also fails on other errors, such
as an unknown function or a call with the wrong operands, and with
`--layouts` it checks tables and coordinates too
([CLI reference](../reference/cli.md#dpm-xl-check)).

## With the CLI

```console
$ dpm-xl check examples/rules.json
6/6 expressions parsed
$ echo $?
0
```

A syntax error names the rule and points at the offending text:

```console
$ dpm-xl check "with {tC_01.00, c0010}: {r0010} = {r0020} +* {r0030}"
argument: error: unexpected '*' where an operand is expected
with {tC_01.00, c0010}: {r0010} = {r0020} +* {r0030}
                                           ^
0/1 expressions parsed; 1 error
$ echo $?
1
```

In a rule file the source is `<code>:expression` or `<code>:precondition`
(JSON rule files) or `line <n>:expression` (text files). `--json` prints the
same as a document, with the zero-based character `start` and `end` of each
problem, for annotating a pull request:

```console
$ dpm-xl check "if {tC_01.00, r0010} > 0 then true" --json
{
  "schema_version": 1,
  "parsed": 0,
  "total": 1,
  "errors": [
    {
      "source": "argument",
      "message": "expected 'endif', found end of expression",
      "position": 34,
      "end": 34
    }
  ],
  "diagnostics": [
    {
      "source": "argument",
      "severity": "error",
      "code": "syntax",
      "message": "expected 'endif', found end of expression",
      "start": 34,
      "end": 34,
      "subject": null,
      "suggestion": null
    }
  ]
}
```

!!! note "A missing rule file is an error"
    An argument that reads as a path (it ends in `.json` or `.txt`, or
    holds a `/` without any brackets, operators or spaces) but names no
    file fails with `error: no such rule file: ...` and exit status 3, so a
    mistyped path cannot pass as an expression.

## A GitHub Actions job

```yaml
name: Rules
on: [push, pull_request]
jobs:
  check:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v6
      - run: test -f rules/rules.json
      - run: uvx dpm-xl check rules/rules.json --strict
```

Pin the version (`uvx dpm-xl@1.0.0 ...`) if you want a new release to be a
deliberate change.

## With pytest

A test can check more than syntax: that every rule only refers to tables your
release defines, for example. [`parse_program`][dpmxl.parser.parse_program]
accepts everything `dpm-xl check` accepts, and
[`tables`][dpmxl.references.tables] lists the tables an expression selects
from.

```python
import json
from pathlib import Path

from dpmxl import DpmXlSyntaxError, parse_program, tables

KNOWN_TABLES = {"C_01.00", "C_27.00"}


def check_rules(path):
    problems = []
    for rule in json.loads(Path(path).read_text()):
        for part in ("expression", "precondition"):
            if not rule.get(part):
                continue
            try:
                tree = parse_program(rule[part])
            except DpmXlSyntaxError as error:
                problems.append(f"{rule['code']} {part}: {error.message}")
                continue
            unknown = set(tables(tree)) - KNOWN_TABLES
            if unknown:
                problems.append(
                    f"{rule['code']} {part}: unknown tables {sorted(unknown)}"
                )
    return problems


print(check_rules("examples/rules.json"))
```

```text
["v0004 expression: unknown tables ['C_99.00']"]
```

In a test, `assert not check_rules("rules/rules.json")` fails the job and
lists every problem.

## What parses

dpm-xl parses every construct of the DPM-XL grammar and every EBA validation
rule and precondition of DPM releases 3.4–4.4, except two EBA expressions with
typos (`trueendif`, `ornot`). A few readings differ from the grammar on
purpose; [Language](../reference/language.md#where-dpm-xl-differs-from-the-grammar)
lists them.
