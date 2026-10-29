---
description: Install dpm-xl, evaluate a first rule against in-memory data, read the explanation and use the CLI.
---

# Getting started

This tutorial takes you from installation to an explained rule failure, first
in Python and then on the command line. It takes about ten minutes.

## Install

dpm-xl needs Python 3.11 or newer and has no dependencies.

```bash
pip install dpm-xl
```

or, in a project managed with uv:

```bash
uv add dpm-xl
```

Check the installation; it prints the installed version:

```bash
dpm-xl --version
```

## Parse a rule

A DPM-XL rule compares cells of report tables. This one says that in every
column of table `C_01.00`, row `0010` is the sum of rows `0020` and `0030`:

```python
from dpmxl import parse, tables

expression = (
    "with {tC_01.00, c*, default: 0, interval: true}: {r0010} = {r0020} + {r0030}"
)
tree = parse(expression)
print(type(tree).__name__, tables(tree))
```

```text
With ('C_01.00',)
```

`with {...}:` sets a context that every selection in the body inherits:
`{r0010}` means `{tC_01.00, r0010, c*, default: 0, interval: true}`. `c*`
selects every column; `default: 0` fills cells that were not reported;
`interval: true` allows for the rounding of reported amounts (see
[Interval arithmetic](concepts/intervals.md)).

A rule that does not parse raises
[`DpmXlSyntaxError`][dpmxl.parser.DpmXlSyntaxError] with a plain message and
the position of the offending text:

```python
from dpmxl import DpmXlSyntaxError

try:
    parse("with {tC_01.00, c0010}: {r0010} = {r0020} +* {r0030}")
except DpmXlSyntaxError as error:
    print(error.message)
    print(error.pointer())
```

```text
unexpected '*' where an operand is expected
with {tC_01.00, c0010}: {r0010} = {r0020} +* {r0030}
                                           ^
```

## Provide report data

The evaluator reads no files. It asks a *provider* for the cells a selection
covers. [`MemoryProvider`][dpmxl.provider.MemoryProvider] holds a report in
memory: table layouts plus values keyed by `(table, row, column, sheet, open
keys)`.

```python
from dpmxl import MemoryProvider, Number, TableLayout

layout = TableLayout("C_01.00", rows=("0010", "0020", "0030"), columns=("0010", "0020"))
values = {
    ("C_01.00", "0010", "0010", None, ()): Number.of(100, 0),
    ("C_01.00", "0020", "0010", None, ()): Number.of(60, 0),
    ("C_01.00", "0030", "0010", None, ()): Number.of(40, 0),
    ("C_01.00", "0010", "0020", None, ()): Number.of(1204, 0),
    ("C_01.00", "0020", "0020", None, ()): Number.of(1180, 0),
    ("C_01.00", "0030", "0020", None, ()): Number.of(31, 0),
}
provider = MemoryProvider([layout], values)
```

`Number.of(1204, 0)` is a fact reported with XBRL `decimals="0"`: 1,204
rounded to whole units, so anything from 1,203.5 to 1,204.5.

```python
amount = Number.of(1204, 0)
print(amount.low, amount.high)
```

```text
1203.5 1204.5
```

For your own storage you write a provider with three methods; see
[Connect your data](guides/provider.md).

## Evaluate

[`evaluate_rule`][dpmxl.evaluator.evaluate_rule] returns a
[`RuleResult`][dpmxl.evaluator.RuleResult]. It never raises for a bad rule or
bad data; problems become the status `error`.

```python
from dpmxl import evaluate_rule

result = evaluate_rule(expression, provider, precondition="{v_C_01.00}")
print(result.status, result.counts)
for outcome in result.outcomes:
    print(outcome.key, outcome.passed)
```

```text
failed {'passed': 1, 'failed': 1, 'null': 0}
{'c': '0010'} True
{'c': '0020'} False
```

The rule has one *record* per column, because `c*` selects two columns; the
record key `{'c': '0020'}` names the failing one. The precondition
`{v_C_01.00}` makes the rule apply only when table `C_01.00` was reported;
`MemoryProvider` treats every table with a value as reported.

## Explain a failure

[`explain`][dpmxl.explain.explain] fills the failing record's formula with the
reported values:

```python
from dpmxl import explain

explanation = explain(result.evaluation, expression, {"c": "0020"})
print(explanation.summary)
print(explanation.filled)
print(explanation.difference, explanation.gap, explanation.direction)
print([point.ref for point in explanation.primary])
```

```text
1,204 should equal 1,211 (1,180 + 31): difference 7, at least 5.5 given the reported precision
1,204 = 1,180 + 31
7 5.5 too_low
[('C_01.00', '0010', '0020', None, ())]
```

The sides differ by 7. Each of the three amounts may be off by up to 0.5, so
1.5 of that difference could be rounding; 5.5 cannot. `primary` holds the
cells on the left of the comparison, the values that disagree; a user
interface can highlight them by their `ref`.

## Use the CLI

The same evaluation runs from the command line against a JSON data file. The
repository's [`examples/`](https://github.com/luukhopman/dpm-xl/tree/main/examples)
folder has a rule file and a data file:

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
$ echo $?
1
```

The exit status is 1 because a rule failed. `dpm-xl check` only parses, which
is what a CI job for a rule repository needs:

```console
$ dpm-xl check examples/rules.json
6/6 expressions parsed; 1 inactive rule skipped
```

## Next steps

- [Connect your data](guides/provider.md): write a provider for your own
  storage.
- [Explain failures in a UI](guides/explain.md): everything an
  [`Explanation`][dpmxl.explain.Explanation] holds.
- [Records and keys](concepts/records-and-keys.md): how selections become
  records and how operators join them.
- [Language reference](reference/language.md): every construct with its
  syntax, types, errors and tested examples; the
  [quick reference](reference/quick-reference.md) has it on one page.
