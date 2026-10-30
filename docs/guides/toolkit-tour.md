---
description: One report through the dpm toolkit - generate it with dpm-synth, read it with dpm-xbrl, then evaluate and explain its DPM-XL rules with dpm-xl.
---

# Toolkit tour

Each package of the dpm toolkit does one job:
[dpm-synth](https://luukhopman.github.io/dpm-synth/) generates test reports,
[dpm-xbrl](https://luukhopman.github.io/dpm-xbrl/) reads and writes them,
and dpm-xl evaluates their validation rules. This tour takes one report
through all three: generate it, plant an error, read it back, then evaluate
the rules and explain the failure. The [toolkit page](../toolkit.md) shows how the
packages and the module file fit together.

```bash
pip install dpm-synth "dpm-xl[xbrl]"   # dpm-synth, dpm-xl and dpm-xbrl
```

The module is a small template in the repository,
[`examples/toolkit-tour/template.json`](https://github.com/luukhopman/dpm-xl/blob/main/examples/toolkit-tour/template.json):
a closed table `T_01.00` whose row 0010 is the sum of rows 0020 and 0030, an
open table `T_02.00` of exposures by counterparty (`qCP`), and four DPM-XL
rules. Run the code from a checkout of the repository.

## 1. Generate a report with dpm-synth

```python
from dpmsynth import generate, load_template

template = load_template("examples/toolkit-tour/template.json")
generated = generate(template, seed=7)
print(generated.passed, "of", generated.rules, "rules pass")
for fact in generated.report.facts:
    print(fact.datapoint, dict(fact.keys), fact.value)
```

```text
4 of 4 rules pass
dp101 {} 1126000
dp102 {} 971000
dp103 {} 155000
dp201 {'qCP': 'SYNTHZDE8GXD6NCF1086'} 571000
dp201 {'qCP': 'SYNTHEPF91DHODZDOC37'} 555000
```

Every value is generated and the counterparties are fictional LEIs. The
same seed gives the same report.

## 2. Plant an error and write the package

A synthetic report is for testing a pipeline. Change one value, as a faulty
upstream system might, and write the report as an xBRL-CSV package with
dpm-xbrl:

```python
import io
from dataclasses import replace

from dpmxbrl import write_xbrl_csv

facts = tuple(
    replace(fact, value="978000") if fact.datapoint == "dp102" else fact
    for fact in generated.report.facts
)
package = io.BytesIO()  # or a path such as "report.zip"
write_xbrl_csv(replace(generated.report, facts=facts), package)
```

Row 0020 now says 978,000 instead of 971,000.

## 3. Read it with dpm-xbrl

```python
from dpmxbrl import read_report

report = read_report(package.getvalue())
print(report.format, report.entity_id, report.reference_date)
print(report.decimals_parameters, report.filing_indicators)
print(report.filing)
```

```text
xbrl-csv SYNTHETICDPMXL000002.CON 2026-12-31
{'decimalsMonetary': -3} {'T_01.00': True, 'T_02.00': True}
()
```

The package breaks no EBA filing rule that the file can show; read from
bytes without a `name`, its file name is not checked. Amounts are reported
in thousands (`decimalsMonetary = -3`).

## 4. Evaluate and explain with dpm-xl

dpm-xl reads no files: it asks a [provider](provider.md) for the cells of
each selection. The template is also a dpm-xl
[module file](../reference/module-file.md), which places every datapoint at
a table, row and column, so the shipped
[`ReportProvider`][dpmxl.xbrl.ReportProvider] (the `xbrl` extra) answers
from the facts dpm-xbrl read. It types each value by the cell's data type
and keeps the reported precision: 978,000 reported in thousands stands for
978,000 ± 500.

```python
from dpmxl import evaluate_rule, explain
from dpmxl.module import load_module
from dpmxl.xbrl import ReportProvider

module = load_module("examples/toolkit-tour/template.json")
provider = ReportProvider(module, report)
for rule in module.rules:
    result = evaluate_rule(rule.expression, provider, precondition=rule.precondition)
    print(rule.code, result.status)
    for outcome in result.failures:
        print("   ", explain(result.evaluation, rule.expression, outcome.key).summary)
```

```text
v1 failed
    1,126,000 should equal 1,133,000 (978,000 + 155,000): difference 7,000, at least 5,500 given the reported precision
v2 passed
v3 passed
v4 passed
```

dpm-xl finds the planted error. Three amounts rounded to thousands could
explain up to 1,500 of the difference; at least 5,500 they cannot.

## Where next

- [dpm-synth](https://luukhopman.github.io/dpm-synth/): write a template
  for your own module, or build one from a DPM release.
- [dpm-xbrl](https://luukhopman.github.io/dpm-xbrl/): read XBRL-XML as well,
  check the EBA filing rules, and read large packages as frames.
- [From an XBRL report to explained failures](end-to-end.md): the same
  provider for a real report layout, with the columnar engine, and
  `check_report`, which checks the filing rules too.
- [Explain failures in a UI](explain.md): the cells and the filled formula
  behind each summary.
