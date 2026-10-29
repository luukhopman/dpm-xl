---
description: What dpm-xl is, a 30-second example in Python and on the command line, installation, the standards it implements and where to go next.
---

# dpm-xl

A Python parser and evaluator for **DPM-XL**, the expression language of EBA
validation rules and similar checks. Give it a rule and your report data; it
tells you which records fail and explains each failure in plain numbers.

dpm-xl is an independent project, not affiliated with or endorsed by the
European Banking Authority.

<div class="toolkit-badges" markdown>

[DPM-XL 0.11](reference/standards.md#dpm-xl)
[EBA Filing Rules 5.9, rule 2.18](reference/standards.md#eba-filing-rules)
[VTL 2.1](reference/standards.md#vtl)
[Python 3.11+](project/stability.md#supported-python-versions)

</div>

It is for teams that check supervisory reports before they are filed, build
validation into a reporting platform, or analyse and edit DPM-XL rules. It
has no dependencies.

[Get started](getting-started.md){ .md-button .md-button--primary }
[Standards and conformance](reference/standards.md){ .md-button }

## In 30 seconds

=== "Python"

    ```python
    from dpmxl import MemoryProvider, Number, TableLayout, evaluate_rule, explain

    layout = TableLayout("C_01.00", rows=("0010", "0020", "0030"), columns=("0010", "0020"))
    values = {  # (1)!
        ("C_01.00", "0010", "0010", None, ()): Number.of(100, 0),
        ("C_01.00", "0020", "0010", None, ()): Number.of(60, 0),
        ("C_01.00", "0030", "0010", None, ()): Number.of(40, 0),
        ("C_01.00", "0010", "0020", None, ()): Number.of(1204, 0),
        ("C_01.00", "0020", "0020", None, ()): Number.of(1180, 0),
        ("C_01.00", "0030", "0020", None, ()): Number.of(31, 0),
    }
    provider = MemoryProvider([layout], values)  # (2)!

    expression = (
        "with {tC_01.00, c*, default: 0, interval: true}: {r0010} = {r0020} + {r0030}"
    )
    result = evaluate_rule(expression, provider, precondition="{v_C_01.00}")  # (3)!

    print(result.status, result.counts)
    for outcome in result.failures:
        print(outcome.key, explain(result.evaluation, expression, outcome.key).summary)
    ```

    1. Each cell is keyed by table, row, column, sheet and open keys.
       `Number.of(1204, 0)` is 1,204 reported with XBRL `decimals="0"`, so
       anything from 1,203.5 to 1,204.5.
    2. The evaluator reads no files: a provider answers its queries. Write
       your own for a database or a report upload, or use the shipped
       one for dpm-xbrl reports.
    3. One record per column, because `c*` selects both. It never raises for
       a bad rule or bad data; the status says what happened.

    ```text
    failed {'passed': 1, 'failed': 1, 'null': 0}
    {'c': '0020'} 1,204 should equal 1,211 (1,180 + 31): difference 7, at least 5.5 given the reported precision
    ```

=== "Command line"

    The same rule against a JSON data file of the repository's
    [`examples/`](https://github.com/luukhopman/dpm-xl/tree/main/examples):

    ```console
    $ dpm-xl eval "with {tC_01.00, c*, default: 0, interval: true}: {r0010} = {r0020} + {r0030}" examples/data.json
    status: failed
    records: 1 passed, 1 failed, 0 null
    - c=0020: 1,204 should equal 1,211 (1,180 + 31): difference 7, at least 5.5 given the reported precision
    $ echo $?
    1
    ```

Column `0010` adds up; in column `0020`, 1,204 is 7 short of 1,180 + 31, more
than the rounding of three whole-unit amounts (±1.5) can explain.

## Install

=== "pip"

    ```text
    pip install dpm-xl               # standard library only
    pip install "dpm-xl[columnar]"   # polars: the columnar evaluator
    pip install "dpm-xl[xbrl]"       # dpm-xbrl: check XBRL reports
    ```

=== "uv"

    ```text
    uv add dpm-xl
    uv add "dpm-xl[columnar]"
    uv add "dpm-xl[xbrl]"
    ```

The import name is `dpmxl`; the command is `dpm-xl`.

## Find your way

<div class="grid cards" markdown>

-   :lucide-graduation-cap:{ .lg .middle } **Getting started**

    ---

    Install dpm-xl, evaluate a first rule, read the explanation and run the
    command line, in about ten minutes.

    [:lucide-arrow-right: Tutorial](getting-started.md)

-   :lucide-list-checks:{ .lg .middle } **How-to guides**

    ---

    Recipes for one task each: connect your data, check an XBRL report,
    explain failures in a UI, evaluate large reports, check rules in CI.

    [:lucide-arrow-right: Guides](guides/index.md)

-   :lucide-lightbulb:{ .lg .middle } **Concepts**

    ---

    How rules are evaluated: records and keys, null logic, interval
    arithmetic, sets, time and the rest of the semantics.

    [:lucide-arrow-right: Concepts](concepts/index.md)

-   :lucide-library:{ .lg .middle } **Reference**

    ---

    The language, the command line, the data and module file formats, the
    Python API, and the standards implemented.

    [:lucide-arrow-right: Reference](reference/index.md)

</div>

## Features

- **The whole language.** Every construct of the DPM-XL grammar, each with
  tested examples in the [language reference](reference/language.md). All
  14,174 distinct EBA rule and precondition expressions of DPM releases
  3.4–4.4 parse but the two with typos in the EBA source, about 0.1 ms
  each; see [how conformance is tested](reference/standards.md#how-conformance-is-tested).
- **EBA semantics.** Interval arithmetic, null logic and key joins, and
  each failure pointed at the cells involved; see the
  [concepts](concepts/index.md).
- **Problems before evaluation.** Every syntax error, unknown functions and
  tables, coordinates a table lacks, keys and operand types, each with its
  position and, where one fits, a suggested fix, for
  [editors](guides/editor.md) and [CI](guides/ci.md).
- **Any data source.** A three-method [provider](guides/provider.md), so
  the same evaluator runs against a report upload, a database or test
  fixtures.
- **XBRL reports.** With the `xbrl` extra, `dpm-xl check-report` checks a
  report against a [module file](reference/module-file.md): the filing
  rules [dpm-xbrl] checks, and the module's rules; see
  [from an XBRL report to explained failures](guides/end-to-end.md).
- **Millions of rows.** The `columnar` extra adds a polars evaluator for
  large open tables; see [evaluate large reports](guides/columnar.md).
- **For AI agents too.** The essentials on [one page](agents.md), and
  every page as Markdown in [`llms.txt`](llms.txt) and
  [`llms-full.txt`](llms-full.txt).

## Part of the dpm toolkit

dpm-xl evaluates the rules of reports that [dpm-xbrl] reads and
[dpm-synth] generates, from the same module file; the
[toolkit page](toolkit.md) shows how they fit together.

--8<-- "docs/.snippets/toolkit-cards.md"
