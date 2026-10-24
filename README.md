<p align="center">
  <a href="https://luukhopman.github.io/dpm-xl/"><img src="https://luukhopman.github.io/dpm-xl/assets/logo.svg" alt="" width="96" height="96"></a>
</p>

# dpm-xl

A Python parser and evaluator for **DPM-XL**, the expression language of EBA
validation rules and similar checks. Give it a rule and your report data; it
tells you which records fail and explains each failure in plain numbers:

```text
1,204 should equal 1,211 (1,180 + 31): difference 7, at least 5.5 given the reported precision
```

**Documentation: https://luukhopman.github.io/dpm-xl/**

- Parses every construct of the DPM-XL grammar, including every EBA
  validation rule and precondition of DPM releases 3.4–4.4 (14,000+ distinct
  expressions, about 0.1 ms each).
- Evaluates them with EBA's interval arithmetic, null logic and key joins, and
  points each failure at the cells involved.
- Has no dependencies. The optional `columnar` extra adds a polars evaluator
  for reports with millions of open-table rows.
- Reads no files and knows no DPM release: data comes through a three-method
  provider, so the same evaluator runs against a report upload, a database or
  test fixtures. [dpm-xbrl](https://pypi.org/project/dpm-xbrl/) reads
  xBRL-CSV and XBRL-XML reports.

dpm-xl is an independent project, not affiliated with or endorsed by the
European Banking Authority.

## Installation

```bash
pip install dpm-xl               # Python 3.11+, no dependencies
pip install "dpm-xl[columnar]"   # adds the polars evaluator
```

## Quickstart

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

On the command line, against a JSON data file:

```bash
dpm-xl check rules.json            # parse every expression and precondition
dpm-xl eval rules.json data.json   # evaluate and explain every rule
```

## Documentation

- [Getting started](https://luukhopman.github.io/dpm-xl/getting-started/):
  a first rule, end to end.
- [How-to guides](https://luukhopman.github.io/dpm-xl/guides/): connect your
  data, evaluate rule files, explain failures in a UI, evaluate large
  reports, run rules in threads, check rules in CI, build editor support, and
  [read an XBRL report and evaluate it](https://luukhopman.github.io/dpm-xl/guides/end-to-end/)
  with dpm-xbrl.
- [Concepts](https://luukhopman.github.io/dpm-xl/concepts/): records and
  keys, null logic, interval arithmetic and the rest of the semantics.
- [Reference](https://luukhopman.github.io/dpm-xl/reference/): the language,
  the CLI, the data formats and the Python API.
- [Using dpm-xl with AI agents](https://luukhopman.github.io/dpm-xl/agents/),
  with [`llms.txt`](https://luukhopman.github.io/dpm-xl/llms.txt) and
  [`llms-full.txt`](https://luukhopman.github.io/dpm-xl/llms-full.txt).
- [Changelog](https://github.com/luukhopman/dpm-xl/blob/main/CHANGELOG.md),
  [stability policy](https://luukhopman.github.io/dpm-xl/project/stability/),
  [benchmarks](https://luukhopman.github.io/dpm-xl/project/benchmarks/) and
  [contributing](https://luukhopman.github.io/dpm-xl/project/contributing/).

## Licence

MIT. See [LICENSE](https://github.com/luukhopman/dpm-xl/blob/main/LICENSE).
