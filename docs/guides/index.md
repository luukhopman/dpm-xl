---
description: Task-oriented recipes for connecting data, evaluating and explaining rules, checking XBRL reports, scaling up and building tooling.
---

# How-to guides

Recipes for specific tasks. They assume you have done the
[getting started](../getting-started.md) tutorial; every example runs as
shown (the test suite executes them).

## Connect and evaluate

<div class="grid cards" markdown>

-   :lucide-plug:{ .lg .middle } [**Connect your data**](provider.md)

    ---

    Write a `DataProvider` for your storage, with the optional
    `open_keys`, `table_group`, `operation` and `earlier_report` hooks.

-   :lucide-file-json:{ .lg .middle } [**Evaluate a rule file**](rule-files.md)

    ---

    Run a rule set against a report, in Python or with `dpm-xl eval`.

-   :lucide-message-square-text:{ .lg .middle } [**Explain failures in a UI**](explain.md)

    ---

    Sentences, filled formulas and the cells to highlight.

-   :lucide-file-check:{ .lg .middle } [**From an XBRL report to explained failures**](end-to-end.md)

    ---

    Read a report with dpm-xbrl, place its facts with a module file,
    evaluate and explain, or run `dpm-xl check-report`.

-   :lucide-workflow:{ .lg .middle } [**Toolkit tour**](toolkit-tour.md)

    ---

    Generate a report with dpm-synth, read it with dpm-xbrl, then evaluate
    and explain its rules.

</div>

## Scale up

<div class="grid cards" markdown>

-   :lucide-rows-3:{ .lg .middle } [**Evaluate large reports**](columnar.md)

    ---

    The columnar engine for millions of open-table rows, with the
    reference fallback.

-   :lucide-cpu:{ .lg .middle } [**Run rules in threads**](threads.md)

    ---

    What is safe to share between threads.

-   :lucide-calendar-clock:{ .lg .middle } [**Compare with earlier reports**](time-shift.md)

    ---

    `time_shift` and `annualise`.

</div>

## Build tooling

<div class="grid cards" markdown>

-   :lucide-circle-check:{ .lg .middle } [**Check rule syntax in CI**](ci.md)

    ---

    `dpm-xl check` and a pytest test.

-   :lucide-code:{ .lg .middle } [**Build editor support**](editor.md)

    ---

    Tokens, error ranges and the TextMate grammar.

-   :lucide-search-code:{ .lg .middle } [**Analyse rules statically**](analyse.md)

    ---

    The tree, the selections and the tables a rule reads.

</div>
