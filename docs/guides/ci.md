---
description: Fail a CI job when a rule in a rule repository does not parse, with dpm-xl check or a pytest test.
---

# Check rule syntax in CI

A repository of rules (exported from a DPM release, or written by hand)
should never hold an expression that does not parse or names a function
that does not exist. `dpm-xl check` checks every expression and
precondition of a rule source and fails when any of them has an error.
`--strict` also fails on warnings, such as syntax that other DPM-XL engines
may reject (`.5`), and `--layouts` checks tables and coordinates too
([CLI reference](../reference/cli.md#dpm-xl-check)).

## With the CLI

```console
$ dpm-xl check examples/rules.json
6/6 expressions parsed; 1 inactive rule skipped
$ echo $?
0
```

A syntax error names the rule and points at the offending text:

```console
$ dpm-xl check "with {tC_01.00, c0010}: {r0010} = {r0020} +* {r0030}"
expression: error: unexpected '*' where an operand is expected
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
  "schema_version": 2,
  "tool": "dpm-xl",
  "version": "1.3.0",
  "summary": {
    "total": 1,
    "parsed": 0,
    "errors": 1,
    "warnings": 0,
    "skipped": 0
  },
  "skipped": [],
  "errors": [
    {
      "source": "expression",
      "message": "expected 'endif', found end of expression",
      "position": 34,
      "end": 34
    }
  ],
  "diagnostics": [
    {
      "source": "expression",
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

Pin a version (`uvx dpm-xl@VERSION ...`) if you want a new release to be a
deliberate change.

## With pytest

A test can check the rules against the tables of your release, as `check
--layouts` does. [`load_rules`][dpmxl.rules.load_rules] reads a rule file,
[`Module.layouts`][dpmxl.module.Module.layouts] gives a module's tables and
[`diagnose`][dpmxl.diagnostics.diagnose] finds the problems:

```python
from dpmxl import diagnose
from dpmxl.module import load_module
from dpmxl.rules import load_rules

module = load_module("examples/module.json")
layouts = {layout.code: layout for layout in module.layouts()}


def check_rules(path):
    problems = []
    for rule in load_rules(path):
        for part in ("expression", "precondition"):
            text = getattr(rule, part)
            if rule.active and text:
                for problem in diagnose(text, layouts.get, tables=tuple(layouts)):
                    if problem.severity == "error":
                        problems.append(f"{rule.code} {part}: {problem.message}")
    return problems


print(check_rules("examples/rules.json"))
```

```text
['v0004 expression: unknown table C_99.00']
```

In a test, `assert not check_rules("rules/rules.json")` fails the job and
lists every problem.

## What parses

dpm-xl parses every construct of the DPM-XL grammar and every EBA validation
rule and precondition of DPM releases 3.4–4.4, except two EBA expressions with
typos (`trueendif`, `ornot`). A few readings differ from the grammar on
purpose; [Language](../reference/language.md#where-dpm-xl-differs)
lists them.
