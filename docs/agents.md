---
description: The essential dpm-xl API on one page for AI agents and their users - contracts, a complete example and common pitfalls.
---

# Using dpm-xl with AI agents

This page is for AI coding agents (and the people prompting them) writing
code that *uses* dpm-xl. It holds the essential API, the contracts that
matter and the mistakes to avoid. Agents working *on* the dpm-xl repository
should read
[`AGENTS.md`](https://github.com/luukhopman/dpm-xl/blob/main/AGENTS.md)
instead.

Machine-readable documentation, following [llmstxt.org](https://llmstxt.org):

- [`llms.txt`](https://luukhopman.github.io/dpm-xl/llms.txt): an index of
  every page with a one-line description.
- [`llms-full.txt`](https://luukhopman.github.io/dpm-xl/llms-full.txt): every
  page, API reference included, as one Markdown file.
- Each page as Markdown: replace the trailing `/` of a page URL with `.md`,
  for example
  [`guides/provider.md`](https://luukhopman.github.io/dpm-xl/guides/provider.md).

## The essential API

```python
from dpmxl import (
    DataPoint,
    CellQuery,
    MemoryProvider,
    TableLayout,
    Number,  # data
    evaluate_rule,
    explain,
    SelectionCache,  # evaluation
    parse,
    parse_program,
    DpmXlSyntaxError,  # parsing
    references,
    tables,  # analysis
    axis_matcher,  # providers
)
```

| Call | Returns | Raises |
| --- | --- | --- |
| `evaluate_rule(expression, provider, *, precondition=None, trace=True, cache=None, only_keys=None)` | `RuleResult` with `status`, `message`, `outcomes`, `failures`, `counts`, `evaluation`, `assignments` | Nothing for bad rules or data: those are statuses |
| `explain(result.evaluation, expression, outcome.key)` | `Explanation` with `summary`, `filled`, `difference`, `gap`, `direction`, `left`, `right`, `primary`, `kind` | |
| `parse(expression)` / `parse_program(source)` | Expression tree / `Program` | `DpmXlSyntaxError` (`message`, `position`, `end`, `pointer()`) |
| `references(tree)`, `tables(tree, provider=None)` | Selections with context applied; table codes | |
| `dpmxl.columnar.evaluate_rule_columnar(expression, frame_provider, *, precondition=None, cache=None)` | `ColumnarResult` with `status`, `passed`, `failed`, `null`, `failing_keys`, `failing_frame` | `ColumnarUnsupported`: evaluate with `evaluate_rule` instead |
| `dpmxl.diagnostics.diagnose(expression, layout=None, *, tables=None, parameters=None, program=False)` | `Diagnostic`s with `severity`, `code` (such as `syntax`, `unknown-table`, `non-portable`), `message`, `start`, `end`, `suggestion` | |
| `dpmxl.rules.load_rules(path)` / `evaluate_rules(rules, provider, *, module=None, cache=None)` | `Rule`s (`code`, `expression`, `precondition`, `severity`, `active`, `modules`) / one `RuleRun` per rule with `status` (`skipped` for an inactive rule), `message`, `result` | `RuleFileError` naming the JSON path |
| `dpmxl.module.load_module(path)` | `Module` with `tables`, `rules` (`Rule`s), `layouts()`; reads `dpm-module/1` and `dpm-synth-template/1` | `ModuleError` naming the JSON path |
| `dpmxl.dpm.open_release(path)` / `export_module(db, module_code, release=None, *, format="dpm-module/1")` | An open EBA DPM 2.0 database (`releases()`, `modules(release)`) / the module file as a `dict` | `DpmError` |
| `dpmxl.xbrl.ReportProvider(module, report, *, previous=(), taxonomy_packages=())` / `check_report(module, report, *, previous=(), taxonomy_packages=())` | A provider over a dpm-xbrl `Report` / `ReportCheck` with `filing`, `rules`, `unplaced`, `findings`, `failed(fail_on)` | `dpmxbrl.ReportError` for an unreadable report; `ValueError` for a report of another entry point or XBRL-XML without taxonomy packages; needs the `xbrl` extra |

Statuses: `passed`, `failed`, `not_applicable`, `error`, `unsupported`,
and `skipped` for an inactive rule; see
[Preconditions and results](concepts/results.md).

## A complete, correct example

```python
from dpmxl import (
    MemoryProvider,
    Number,
    SelectionCache,
    TableLayout,
    evaluate_rule,
    explain,
)

provider = MemoryProvider(
    [TableLayout("C_01.00", rows=("0010", "0020", "0030"), columns=("0010",))],
    {
        ("C_01.00", "0010", "0010", None, ()): Number.of(1204, 0),
        ("C_01.00", "0020", "0010", None, ()): Number.of(1180, 0),
        ("C_01.00", "0030", "0010", None, ()): Number.of(31, 0),
    },
)
rules = [
    (
        "v1",
        "with {tC_01.00, c0010, interval: true}: {r0010} = {r0020} + {r0030}",
        "{v_C_01.00}",
    )
]
cache = SelectionCache()
for code, expression, precondition in rules:
    result = evaluate_rule(expression, provider, precondition=precondition, cache=cache)
    print(code, result.status, result.message or "")
    for outcome in result.failures:
        print(" ", explain(result.evaluation, expression, outcome.key).summary)
```

```text
v1 failed
  1,204 should equal 1,211 (1,180 + 31): difference 7, at least 5.5 given the reported precision
```

## Commands

```text
dpm-xl check SOURCE [--strict] [--json]          # diagnose every expression; exit 1 on an error
dpm-xl eval RULES DATA [--format text|json|junit] [--fail-on error|warning] [--all]
dpm-xl check-report MODULE REPORT [--previous REPORT] [--format text|json|junit] [--fail-on error|warning]
dpm-xl list-modules DATABASE [--release R] [--json]
dpm-xl export-module DATABASE MODULE [--release R] [-o FILE]
```

- `SOURCE` and `RULES` are a JSON rule file, a module file, a text file of
  expressions or one expression; `MODULE` is a
  [module file](reference/module-file.md); `DATABASE` an EBA DPM 2.0
  database as SQLite ([how to get one](guides/from-a-dpm-release.md)).
- `check` exits 1 when an expression has an error, and with `--strict`
  also on a warning; `eval` and `check-report` exit 1 when a rule at or
  above `--fail-on` failed or is `error`. All
  [exit statuses](reference/cli.md#exit-statuses) are in the CLI reference.
- `--json` (`--format json`) prints `{"schema_version": 2, "tool":
  "dpm-xl", "version", "summary": {...}, "results": [...]}`; each result
  has `rule`, `expression`, `severity`, `active`, `modules`, `status`,
  `message`, `counts` and `failures` (`key`, `summary`, `cells`).
  `check-report` adds `report`, `module`, `warnings`, `filing_rules`,
  `fact_findings` and `unplaced`; `check` has `errors` and `diagnostics` instead of `results`
  ([CLI](reference/cli.md)). Field names and statuses are stable;
  summaries and messages may be reworded.

## Contracts

- **Providers** implement `select(query) -> Sequence[DataPoint]`,
  `table_reported(table) -> bool | None` and `parameter(name) -> Value`;
  optionally `open_keys`, `is_template`, `table_group`, `operation`,
  `earlier_report`
  ([Connect your data](guides/provider.md)).
- **`select` returns every defined cell of a closed selection**, with
  `value=None` for unreported ones, and one point per reported key
  combination for open tables (keys in `DataPoint.keys`). It raises
  `LookupError` for an unknown table.
- **Numbers** are `Number.of(value, decimals)` with the fact's XBRL
  `decimals` (`None` or `"INF"` for exact). Pass strings or `Decimal`, not
  floats, for exact values.
- **`MemoryProvider` value keys** are `(table, row, column, sheet, keys)`;
  `keys` is a tuple of `(name, value)` pairs for open tables and `()` for
  closed ones. Absent coordinates are `None`.
- **Thread safety:** `evaluate_rule` and `evaluate_rule_columnar` may run
  concurrently on one report; `parse_cached`, `SelectionCache`, `FrameCache`
  and `MemoryProvider` may be shared ([Run rules in threads](guides/threads.md)).

## Common pitfalls

| Mistake | Consequence | Do instead |
| --- | --- | --- |
| Returning only reported cells from `select` for a closed table | `default` and `isnull` never apply; presence checks pass wrongly | Return every defined cell with `value=None` |
| `Number.of(0.1, 2)` with a float | Binary float noise in the value | `Number.of("0.1", 2)` |
| Treating `not_applicable` or null records as failures | False alarms | Only `status == "failed"` / `outcome.passed is False` are failures |
| Expecting `evaluate_rule` to raise on a bad rule | Errors go unnoticed | Check `result.status in {"error", "unsupported"}` and `result.message` |
| Calling `explain` on a `trace=False` result or a `ColumnarResult` | Wrong or no explanation | Re-run `evaluate_rule` with the default `trace=True` for failing rules |
| Not catching `ColumnarUnsupported` | Rules with scripts, `time_shift`, sets and more crash | Catch it and call `evaluate_rule` |
| `parse` on a script with `;`, `:=` or `<-` | `DpmXlSyntaxError` | `parse_program` |
| Writing `a<-1` to compare with -1 | Parsed as a persistent assignment | `a < -1` |
| A filing indicator of a table not shaped like `C_01.00`, such as `{v_T}`, in a custom provider | Reads parameter `T` | Implement `is_template(code)` on the provider |
| Keywords run together, such as `ornot` | One unknown name: a syntax error | Separate words: `or not` |
| A new `SelectionCache` per rule | Every selection is read again | One cache per report |
| Evaluating a `time_shift` rule on one report | `unsupported`, naming the reference date needed | Pass the earlier report as `previous` (`--previous`) |
| Counting a failing `warning` rule as a failed run | Runs fail that the rule file means to pass | Use `ReportCheck.failed(fail_on)` or `--fail-on` |

## Where to look next

- [Start from an EBA DPM release](guides/from-a-dpm-release.md): export a
  real module as a module file.
- [Quick reference](reference/quick-reference.md): the language and its
  grammar on one page.
- [Language](reference/language.md): every construct with its syntax,
  types, null behaviour, errors and tested examples.
- [Concepts](concepts/index.md): records and keys, null logic, intervals.
- [Python API](reference/api/index.md): every public name.
