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

The module file is a small one in the repository,
[`examples/toolkit-tour/module.json`](https://github.com/luukhopman/dpm-xl/blob/main/examples/toolkit-tour/module.json):
a closed table `T_01.00` whose row 0010 is the sum of rows 0020 and 0030, an
open table `T_02.00` of exposures by counterparty (`qCP`), and four DPM-XL
rules. Run the code from a checkout of the repository.

## 1. Generate a report with dpm-synth

<!-- docs: skip -->
```python
from dpmsynth import generate, load_template

tour = load_template("examples/toolkit-tour/module.json")
generated = generate(tour, seed=7)
print(generated.summary["passed"], "of", generated.summary["rules"], "rules pass")
for fact in generated.report.facts:
    print(fact.datapoint, dict(fact.keys), fact.value)
```

<!-- docs: skip -->
```text
4 of 4 rules pass
dp101 {} 9253000
dp102 {} 283000
dp103 {} 8970000
dp201 {'qCP': 'SYNTHE8GXD6NCF10EP96'} 739000
dp201 {'qCP': 'SYNTHF91DHODZDOC9I07'} 271000
```

Every value is generated and the counterparties are fictional LEIs. The
same seed gives the same report.

## 2. Plant an error and write the package

A synthetic report is for testing a pipeline. Change one value, as a faulty
upstream system might, and write the report as an xBRL-CSV package with
dpm-xbrl:

<!-- docs: skip -->
```python
import io
from dataclasses import replace

from dpmxbrl import write_xbrl_csv

facts = tuple(
    replace(fact, value="290000") if fact.datapoint == "dp102" else fact
    for fact in generated.report.facts
)
package = io.BytesIO()  # or a path such as "report.zip"
write_xbrl_csv(replace(generated.report, facts=facts), package)
```

Row 0020 now says 290,000 instead of 283,000.

## 3. Read it with dpm-xbrl

<!-- docs: skip -->
```python
from dpmxbrl import read_report

report = read_report(package.getvalue())
print(report.format, report.entity_id, report.reference_date)
print(report.decimals_parameters, report.filing_indicators)
print(report.filing)
```

<!-- docs: skip -->
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
each selection. The [module file](../reference/module-file.md) dpm-synth
generated from places every datapoint at a table, row and column, so the
shipped
[`ReportProvider`][dpmxl.xbrl.ReportProvider] (the `xbrl` extra) answers
from the facts dpm-xbrl read. It types each value by the cell's data type
and keeps the reported precision: 290,000 reported in thousands stands for
290,000 ± 500.

<!-- docs: skip -->
```python
from dpmxl import evaluate_rule, explain
from dpmxl.module import load_module
from dpmxl.xbrl import ReportProvider

module = load_module("examples/toolkit-tour/module.json")
provider = ReportProvider(module, report)
for rule in module.rules:
    result = evaluate_rule(rule.expression, provider, precondition=rule.precondition)
    print(rule.code, result.status)
    for outcome in result.failures:
        print("   ", explain(result.evaluation, rule.expression, outcome.key).summary)
```

<!-- docs: skip -->
```text
v1 failed
    9,253,000 should equal 9,260,000 (290,000 + 8,970,000): difference 7,000, at least 5,500 given the reported precision
v2 passed
v3 passed
v4 passed
```

dpm-xl finds the planted error. Three amounts rounded to thousands could
explain up to 1,500 of the difference; at least 5,500 they cannot.

## Where next

- [dpm-synth](https://luukhopman.github.io/dpm-synth/): generate reports
  for your own module, from a module file exported from a DPM release.
- [dpm-xbrl](https://luukhopman.github.io/dpm-xbrl/): read XBRL-XML as well,
  check the EBA filing rules, and read large packages as frames.
- [Check an XBRL report](end-to-end.md): the same
  provider for a real report layout, with the columnar engine, and
  `check_report`, which checks the filing rules too.
- [Explain failures in a UI](explain.md): the cells and the filled formula
  behind each summary.
