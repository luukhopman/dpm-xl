---
description: Task-oriented recipes - start from EBA data, integrate dpm-xl with your data and UI, scale up and build tooling.
---

# How-to guides

Recipes for specific tasks. They assume you have done the
[getting started](../getting-started.md) tutorial; every example runs as
shown (the test suite executes them).

## Start from EBA data

<div class="grid cards" markdown>

-   :lucide-database:{ .lg .middle } [**Start from an EBA DPM release**](from-a-dpm-release.md)

    ---

    Get the EBA's database (its ZIP as published, or as SQLite), export a real module, such as
    COREP_OF, as a module file, generate a test report and check it.

-   :lucide-file-check:{ .lg .middle } [**Check an XBRL report**](end-to-end.md)

    ---

    Read a report with dpm-xbrl, place its facts with a module file,
    evaluate and explain, or run `dpm-xl check-report`.

-   :lucide-file-json:{ .lg .middle } [**Evaluate a rule file**](rule-files.md)

    ---

    Run a rule set against a report, in Python or with `dpm-xl eval`,
    with rule severities, inactive rules and JUnit output.

</div>

## Integrate

<div class="grid cards" markdown>

-   :lucide-plug:{ .lg .middle } [**Connect your data**](provider.md)

    ---

    Write a `DataProvider` for your storage, with the optional
    `open_keys`, `is_template`, `table_group`, `operation` and
    `earlier_report` methods.

-   :lucide-message-square-text:{ .lg .middle } [**Explain failures in a UI**](explain.md)

    ---

    Sentences, filled formulas and the cells to highlight.

-   :lucide-calendar-clock:{ .lg .middle } [**Compare with earlier reports**](time-shift.md)

    ---

    `time_shift` and `annualise`, also across XBRL reports with
    `dpm-xl check-report --previous`.

</div>

## Scale and tooling

<div class="grid cards" markdown>

-   :lucide-rows-3:{ .lg .middle } [**Evaluate large reports**](columnar.md)

    ---

    The columnar engine for millions of open-table rows, with the
    reference fallback.

-   :lucide-cpu:{ .lg .middle } [**Run rules in threads**](threads.md)

    ---

    What is safe to share between threads.

-   :lucide-circle-check:{ .lg .middle } [**Check rules in CI**](ci.md)

    ---

    `dpm-xl check` and its `--strict` mode, and a pytest test.

-   :lucide-code:{ .lg .middle } [**Build editor support**](editor.md)

    ---

    Tokens, error ranges and the TextMate grammar.

-   :lucide-search-code:{ .lg .middle } [**Analyse rules statically**](analyse.md)

    ---

    The tree, the selections and the tables a rule reads.

</div>

The [toolkit tour](toolkit-tour.md) takes one generated report through
dpm-synth, dpm-xbrl and dpm-xl.
