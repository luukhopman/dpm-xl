---
description: What dpm-xl is, a 30-second example in Python and on the command line, installation, the standards it implements, four commands from an EBA DPM release to explained failures, and where to go next.
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

On the example module and report in the repository's
[`examples/`](https://github.com/luukhopman/dpm-xl/tree/main/examples),
with the previous quarter's report for the `time_shift` rule `e0007`, the
last step prints:

```console
$ dpm-xl check-report examples/xbrl-module.json examples/xbrl-report --previous examples/xbrl-report-previous
report: examples/xbrl-report (xbrl-csv); module COREP_LR, release 4.2
previous: examples/xbrl-report-previous (2025-12-31)
warning: reports/report.json: 1 extended metadata document could not be resolved offline (http://www.eba.europa.eu/eu/fr/xbrl/crr/fws/corep/4.2/mod/corep_lr.json); tables without resolved metadata use the EBA datapoint/factValue convention
filing rules broken: 0 errors, 0 warnings
e0001: failed
  records: 0 passed, 1 failed, 0 null
  - scalar: 1,045,000 should equal 1,042,000 (812,000 + 190,000 + 40,000): difference 3,000, at least 1,000 given the reported precision
e0003: failed
  records: 1 passed, 1 failed, 0 null
  - qRDT=QW4KNDKKV7QH2LA40639: -12,000 should be at least 0: difference 12,000
e0004: failed (warning)
  records: 1 passed, 1 failed, 0 null
  - qRDT=QW4KNDKKV7QH2LA40639: "QW4KNDKKV7QH2LA4063" does not have the required format
e0007: failed (warning)
  records: 0 passed, 1 failed, 0 null
  - scalar: 1,045,000 should be at least 1,062,000 (0.9 × time_shift(1,180,000, Q, 1, refPeriod)): difference 17,000
7 rules: 4 failed, 2 passed, 1 not_applicable (3 not listed; --all lists every rule)
$ echo $?
1
```

Only rules that failed, are an error or are unsupported are listed;
`--all` lists every rule. The exit status is 1 because rules of severity
`error` failed; failing `warning` rules, such as `e0004`, fail the run only
with `--fail-on warning`. `--format junit` writes the same results as a
JUnit XML report for CI ([CLI](reference/cli.md#dpm-xl-check-report)).

## Find your way

<div class="grid cards" markdown>

-   :lucide-graduation-cap:{ .lg .middle } **Getting started**

    ---

    Install dpm-xl, evaluate a first rule, read the explanation and run the
    command line, in about ten minutes.

    [:lucide-arrow-right: Tutorial](getting-started.md)

-   :lucide-list-checks:{ .lg .middle } **How-to guides**

    ---

    Recipes for one task each: export a module from an EBA DPM release,
    connect your data, check an XBRL report, explain failures in a UI,
    evaluate large reports, check rules in CI.

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
  [editors](guides/editor.md) and [CI](guides/ci.md). `non-portable`
  warnings mark syntax other DPM-XL engines may reject, and
  `dpm-xl check --strict` fails on them
  ([where dpm-xl differs](reference/language.md#where-dpm-xl-differs)).
- **Any data source.** A three-method [provider](guides/provider.md), so
  the same evaluator runs against a report upload, a database or test
  fixtures.
- **Modules from the EBA's DPM.** `dpm-xl export-module` and
  `list-modules` (or `dpmxl.dpm` in Python) write a module of an EBA DPM
  2.0 database as a [module file](reference/module-file.md); see
  [start from an EBA DPM release](guides/from-a-dpm-release.md).
- **XBRL reports.** With the `xbrl` extra, `dpm-xl check-report` checks a
  report against a module file: the filing rules [dpm-xbrl] checks, and
  the module's rules, with earlier reports as `--previous` for
  `time_shift`; see
  [from an XBRL report to explained failures](guides/end-to-end.md).
- **Rule metadata.** Rules carry a `severity` (`error` or `warning`) and
  `active`; inactive rules are skipped and `--fail-on` sets which failures
  fail a run ([rule files](reference/data-formats.md#rule-files)).
- **Output for people and CI.** Text that lists only what needs attention
  (`--all` for every rule), [JSON](reference/cli.md#json-output_1) and
  [JUnit XML](reference/cli.md#junit-xml).
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
