---
description: Parse and evaluate DPM-XL, the validation rules of the EBA Data Point Model (DPM 2.0), in Python - a 30-second example, installation and where to start.
---

# dpm-xl: DPM-XL validation rules in Python

dpm-xl is a Python parser and evaluator for **DPM-XL**, the language in
which the European Banking Authority (EBA) writes the validation rules of
its Data Point Model (DPM 2.0). Give it a rule and your report data, such as
a COREP or FINREP report in xBRL-CSV or XBRL-XML; it tells you which
records fail and explains each failure in plain numbers.

dpm-xl is an independent project, not affiliated with or endorsed by the
European Banking Authority.

It is for teams that check supervisory reports before they are filed, build
validation into a reporting platform, or write and analyse DPM-XL rules. It
has no dependencies.

[Get started](getting-started.md){ .md-button .md-button--primary }
[Check an XBRL report](guides/end-to-end.md){ .md-button }

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

## From an EBA release to explained failures

Four commands take a module of an EBA DPM release to the explained rule
failures of a report:

```bash
dpm-xl list-modules dpm-4.4.sqlite --release 4.3   # the releases and modules
dpm-xl export-module dpm-4.4.sqlite COREP_OF --release 4.3 -o corep_of.json
dpm-synth generate corep_of.json -o report.zip     # or use your own report
dpm-xl check-report corep_of.json report.zip       # filing rules and validation rules
```

`dpm-4.4.sqlite` is the EBA's DPM 2.0 database as SQLite;
[Start from an EBA DPM release](guides/from-a-dpm-release.md) says how to
get it and what the export writes. `corep_of.json` is a
[module file](reference/module-file.md) with the module's tables, cells and
rules, which dpm-xl and [dpm-synth] both read. `check-report` needs the
`xbrl` extra.

## Where to start

<div class="grid cards" markdown>

-   :lucide-file-check:{ .lg .middle } **Check a report**

    ---

    You have a report and want to know which rules it breaks and why.
    Start with the [tutorial](getting-started.md), then
    [check an XBRL report](guides/end-to-end.md) or
    [start from an EBA DPM release](guides/from-a-dpm-release.md).

-   :lucide-plug:{ .lg .middle } **Integrate dpm-xl**

    ---

    You build a reporting platform. [Connect your data](guides/provider.md),
    [explain failures in a UI](guides/explain.md) and
    [evaluate large reports](guides/columnar.md); the
    [Python API](reference/api/index.md) has every name.

-   :lucide-code:{ .lg .middle } **Write rules**

    ---

    You write or maintain DPM-XL rules. The
    [language reference](reference/language.md),
    [check rules in CI](guides/ci.md) and
    [editor support](guides/editor.md); the
    [standards page](reference/standards.md) says what is implemented.

</div>

The [how-to guides](guides/index.md), [concepts](concepts/index.md) and
[reference](reference/index.md) cover the rest, and
[one page for AI agents](agents.md) has the essentials.

## Part of the dpm toolkit

dpm-xl evaluates the rules of reports that [dpm-xbrl] reads and
[dpm-synth] generates, from the same module file; the
[toolkit page](toolkit.md) shows how they fit together.

--8<-- "docs/.snippets/toolkit-cards.md"
