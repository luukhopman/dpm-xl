---
description: What dpm-xl is, who it is for, a 30-second example and where to go next.
---

# dpm-xl

A Python parser and evaluator for **DPM-XL**, the expression language of EBA
validation rules and similar checks. Give it a rule and your report data; it
tells you which records fail and explains each failure in plain numbers.

dpm-xl is an independent project, not affiliated with or endorsed by the
European Banking Authority.

A failure reads like this:

```text
1,204 should equal 1,211 (1,180 + 31): difference 7, at least 5.5 given the reported precision
```

It is for teams that check supervisory reports before they are filed, build
validation into a reporting platform, or analyse and edit DPM-XL rules.

- Parses every construct of the DPM-XL grammar, including every EBA
  validation rule and precondition of DPM releases 3.4–4.4 (14,000+ distinct
  expressions, about 0.1 ms each).
- Evaluates them with EBA's interval arithmetic, null logic and key joins, and
  points each failure at the cells involved.
- Finds problems before evaluation, for [editors](guides/editor.md) and
  [CI](guides/ci.md): every syntax error, unknown functions and tables,
  coordinates a table lacks, keys and operand types, each with its position
  and, where one fits, a suggested fix.
- Has no dependencies. The optional `columnar` extra adds a polars evaluator
  for reports with millions of open-table rows.
- Reads no files and knows no DPM release: data comes through a three-method
  [provider](guides/provider.md), so the same evaluator runs against a report
  upload, a database or test fixtures. [dpm-xbrl](https://luukhopman.github.io/dpm-xbrl/)
  reads xBRL-CSV and XBRL-XML reports; the
  [end-to-end guide](guides/end-to-end.md) connects the two.

## Installation

```bash
pip install dpm-xl               # Python 3.11+, no dependencies
pip install "dpm-xl[columnar]"   # adds the polars evaluator
pip install "dpm-xl[xbrl]"       # adds dpm-xbrl, to check XBRL reports
```

## In 30 seconds

```python
from dpmxl import MemoryProvider, Number, TableLayout, evaluate_rule, explain

layout = TableLayout("C_01.00", rows=("0010", "0020", "0030"), columns=("0010", "0020"))
values = {  # (table, row, column, sheet, open keys) -> value with XBRL decimals
    ("C_01.00", "0010", "0010", None, ()): Number.of(100, 0),
    ("C_01.00", "0020", "0010", None, ()): Number.of(60, 0),
    ("C_01.00", "0030", "0010", None, ()): Number.of(40, 0),
    ("C_01.00", "0010", "0020", None, ()): Number.of(1204, 0),
    ("C_01.00", "0020", "0020", None, ()): Number.of(1180, 0),
    ("C_01.00", "0030", "0020", None, ()): Number.of(31, 0),
}
provider = MemoryProvider([layout], values)

expression = (
    "with {tC_01.00, c*, default: 0, interval: true}: {r0010} = {r0020} + {r0030}"
)
result = evaluate_rule(expression, provider, precondition="{v_C_01.00}")

print(result.status, result.counts)
for outcome in result.failures:
    print(outcome.key, explain(result.evaluation, expression, outcome.key).summary)
```

```text
failed {'passed': 1, 'failed': 1, 'null': 0}
{'c': '0020'} 1,204 should equal 1,211 (1,180 + 31): difference 7, at least 5.5 given the reported precision
```

Column `0010` adds up; in column `0020`, 1,204 is 7 short of 1,180 + 31, more
than the rounding of three whole-unit amounts (±1.5) can explain.

## Toolkit

--8<-- "docs/.snippets/toolkit.md"

## Where next

<div class="grid cards" markdown>

- **[Getting started](getting-started.md)**: install, evaluate a first rule,
  read the explanation and use the CLI.
- **[How-to guides](guides/index.md)**: connect your storage, evaluate rule
  files, explain failures in a UI, evaluate large reports, run in threads.
- **[Concepts](concepts/index.md)**: records and keys, null logic, interval
  arithmetic and the rest of the semantics.
- **[Reference](reference/index.md)**: the language, the CLI, the data
  formats and the Python API.
- **[AI agents](agents.md)**: the essential API on one page, and
  [`llms.txt`](https://luukhopman.github.io/dpm-xl/llms.txt) /
  [`llms-full.txt`](https://luukhopman.github.io/dpm-xl/llms-full.txt).
- **[Project](project/changelog.md)**: changelog, stability policy, security,
  contributing and licence.

</div>
