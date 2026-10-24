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

Statuses: `passed`, `failed`, `not_applicable`, `error`, `unsupported`.

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

## Contracts

- **Providers** implement `select(query) -> Sequence[DataPoint]`,
  `table_reported(table) -> bool | None` and `parameter(name) -> Value`;
  optionally `open_keys`, `table_group`, `operation`, `earlier_report`
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
| `{vX}` for a filing indicator | Reads parameter `X` | `{v_X}` tests the filing indicator |
| A new `SelectionCache` per rule | Every selection is read again | One cache per report |
| Passing a path that does not exist to `dpm-xl check` | It is parsed as an expression and may "pass" | Check the file exists first |

## Where to look next

- [Language](reference/language.md): every construct with an example.
- [Concepts](concepts/index.md): records and keys, null logic, intervals.
- [Python API](reference/api/index.md): every public name.
