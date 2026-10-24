---
description: Task-oriented recipes for connecting data, evaluating and explaining rules, scaling up and building tooling.
---

# How-to guides

Recipes for specific tasks. They assume you have done the
[getting started](../getting-started.md) tutorial; every example runs as
shown (the test suite executes them).

**Connect and evaluate**

- [Connect your data](provider.md): write a `DataProvider` for your storage,
  including the optional `open_keys`, `table_group`, `operation` and
  `earlier_report` hooks.
- [Evaluate a rule file](rule-files.md): run a rule set against a report, in
  Python or with `dpm-xl eval`.
- [Explain failures in a UI](explain.md): sentences, filled formulas and the
  cells to highlight.
- [From an XBRL report to explained failures](end-to-end.md): read a report
  with dpm-xbrl, bind it to a provider, evaluate and explain.

**Scale up**

- [Evaluate large reports](columnar.md): the columnar engine for millions of
  open-table rows, with the reference fallback.
- [Run rules in threads](threads.md): what is safe to share.
- [Compare with earlier reports](time-shift.md): `time_shift` and
  `annualise`.

**Build tooling**

- [Check rule syntax in CI](ci.md): `dpm-xl check` and a pytest test.
- [Build editor support](editor.md): tokens, error ranges and the TextMate
  grammar.
- [Analyse rules statically](analyse.md): the tree, the selections and the
  tables a rule reads.
