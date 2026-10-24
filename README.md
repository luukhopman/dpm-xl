# dpm-xl

A Python parser and evaluator for **DPM-XL**, the expression language of EBA
validation rules and similar checks. Give it a rule and your report data; it
tells you which records fail and explains each failure in plain numbers:

```text
1,204 should equal 1,211 (1,180 + 31): difference 7, at least 5.5 given the reported precision
```

- Parses every construct of the DPM-XL grammar, including every EBA
  validation rule and precondition of DPM releases 3.4–4.4 (14,000+ distinct
  expressions, about 0.1 ms each).
- Evaluates them with EBA's interval arithmetic, null logic and key joins, and
  points each failure at the cells involved.
- Has no dependencies. The optional `columnar` extra adds a polars evaluator
  for reports with millions of open-table rows.
- Reads no files and knows no DPM release: data comes through a three-method
  provider, so the same evaluator runs against a report upload, a database or
  test fixtures. [dpm-xbrl](https://pypi.org/project/dpm-xbrl/) reads
  xBRL-CSV and XBRL-XML reports.

dpm-xl is an independent project, not affiliated with or endorsed by the
European Banking Authority.

## Installation

```bash
pip install dpm-xl               # Python 3.11+, no dependencies
pip install "dpm-xl[columnar]"   # adds the polars evaluator
```

## Quickstart

```python
from dpmxl import MemoryProvider, Number, TableLayout, evaluate_rule, explain

layout = TableLayout("C_01.00", rows=("0010", "0020", "0030"), columns=("0010", "0020"))
values = {  # (table, row, column, sheet, open keys) -> value with XBRL decimals
    ("C_01.00", "0010", "0010", None, ()): Number.of(100, 0),
    ("C_01.00", "0020", "0010", None, ()): Number.of(60, 0),
    ("C_01.00", "0030", "0010", None, ()): Number.of(40, 0),
    ("C_01.00", "0010", "0020", None, ()): Number.of(1204, 0),
    ("C_01.00", "0020", "0020", None, ()): Number.of(1180, 0),
    ("C_01.00", "0030", "0020", None, ()): Number.of(31, 0),
}
provider = MemoryProvider([layout], values)

expression = (
    "with {tC_01.00, c*, default: 0, interval: true}: {r0010} = {r0020} + {r0030}"
)
result = evaluate_rule(expression, provider, precondition="{v_C_01.00}")

print(result.status, result.counts)
# failed {'passed': 1, 'failed': 1, 'null': 0}
for outcome in result.failures:
    print(outcome.key, explain(result.evaluation, expression, outcome.key).summary)
# {'c': '0020'} 1,204 should equal 1,211 (1,180 + 31): difference 7, at least
# 5.5 given the reported precision
```

[`examples/`](https://github.com/luukhopman/dpm-xl/tree/main/examples) holds this script, a custom provider over your own
data ([`custom_provider.py`](https://github.com/luukhopman/dpm-xl/blob/main/examples/custom_provider.py)) and a rule file
with data for the CLI. The tests run every example.

## Results

`evaluate_rule(expression, provider, *, precondition=None)` never raises for a
bad rule or bad data; it returns a `RuleResult`:

| Field | Meaning |
| --- | --- |
| `status` | `passed`, `failed`, `not_applicable` (precondition not met, or no record could be evaluated), `error` (syntax error, unknown table, type mismatch, division by zero that reaches the result) or `unsupported` (a `time_shift`, `{o_…}` or `{g_…}` the provider cannot resolve) |
| `message` | Why the status is `error`, `unsupported` or `not_applicable` |
| `outcomes` | One `Outcome` per record: `key` (such as `{'c': '0020'}`), `passed` (`True`, `False` or `None` when not evaluated) and `points`, the cells it used |
| `failures`, `counts` | The failing outcomes, and the number passed, failed and not evaluated |
| `assignments` | Results of persistent assignments (`{target} <- value`) by target text, such as `{tT, r0010, c0010}` |

`DataPoint.ref` in `outcome.points` is whatever identity your provider gave
the cell, so a user interface can highlight it. `explain(result.evaluation,
expression, key)` returns an `Explanation`: `summary` (the sentence above),
`filled` (the formula with values, `1,204 = 1,180 + 31`), `difference`, `gap`
(the distance left after allowing for reported precision), `direction`
(`too_high` or `too_low`) and the `left` and `right` sides with their
intervals.

`parse(expression)` returns the expression tree, whose nodes keep their
source `span` (`parse_program` reads several statements and assignments),
and raises `DpmXlSyntaxError` with a plain message, the
`position` and `end` of the offending text and a `pointer()` that marks it:

```text
$ dpm-xl check "with {tC_01.00, c0010}: {r0010} = {r0020} +* {r0030}"
argument: unexpected '*' where an operand is expected
with {tC_01.00, c0010}: {r0010} = {r0020} +* {r0030}
                                           ^
0/1 expressions parsed
```

## Connecting your data

```python
class DataProvider(Protocol):
    def select(self, query: CellQuery) -> Sequence[DataPoint]: ...
    def table_reported(self, table: str) -> bool | None: ...
    def parameter(self, name: str) -> Value: ...
```

`select` resolves the table and axis selectors (`axis_matcher` and
`normalize_code` implement range and code matching) and returns all defined
cells of the closed axes with `value=None` where nothing was reported, so
`default` and `isnull` work. For an open table it returns one point per
reported key combination, with the key components in `DataPoint.keys`; an
optional `open_keys(table)` method names them for tables with no rows.
`table_reported` answers `{v_TABLE}` and `parameter` answers `{vName}` and
`{p_Name, type}`. Optional `table_group(code)` and `operation(code)` methods
resolve `{g_…}` table groups and `{o_…}` operation references, and
`earlier_report(period, count)` returns another period's report for
`time_shift` (`MemoryProvider` takes them as `table_groups`, `operations` and
`earlier_reports`). In
`references(node)`, a group or operation read has `spec.table` `None`, with
`kind` (`table`, `table_group` or `operation`) and `code`;
`tables(node, provider)` counts a group read as reading every table
`table_group(code)` lists.
Values are `Number` (use `Number.of(value, decimals)` for reported facts),
`str`, `bool`, `datetime.date`, `Item`, `ValueSet` or `None`.
[`examples/custom_provider.py`](https://github.com/luukhopman/dpm-xl/blob/main/examples/custom_provider.py) is a complete
provider in 40 lines.

To evaluate many rules against one report, pass a shared `SelectionCache`
(`evaluate_rule(..., cache=cache)`) so each selection is read once;
`parse_cached` memoizes parsing.

## CLI

```bash
dpm-xl check rules.json                     # parse every expression and precondition
dpm-xl check "{tC_01.00, r0010} >=" --json  # syntax errors with positions, as JSON
dpm-xl eval rules.json data.json            # evaluate and explain every rule
dpm-xl eval "{tC_27.00, c0010} > 0" data.json --json
```

A rule source is one expression, a text file with one expression per line
(`#` starts a comment), or a JSON list of objects with `code`, `expression`
and an optional `precondition` ([`examples/rules.json`](https://github.com/luukhopman/dpm-xl/blob/main/examples/rules.json)).
`data.json` ([`examples/data.json`](https://github.com/luukhopman/dpm-xl/blob/main/examples/data.json)) holds `tables`
(`code`, `rows`, `columns`, `sheets`, `open_keys`), `facts` (`table`, `row`,
`column`, `sheet`, `keys`, `value`, `decimals` as an integer or `INF`, `type`),
`reported`, `parameters` (a list is a set), `table_groups`, `operations` and
`earlier` reports for `time_shift` (`period`, `count` and a nested `data`
document). `--json` output is an object with
`schema_version` (1), and `results` (`eval`: rule, expression, status,
message, counts and failures with key, summary and cells) or `parsed`,
`total` and `errors` with positions (`check`). The exit status is 0 when everything parsed or
held, 1 when an expression does not parse or a rule fails, and 2 for an
evaluation error or unreadable input.

```text
$ dpm-xl eval examples/rules.json examples/data.json
v0001: failed
  records: 1 passed, 1 failed, 0 not evaluated
  - c=0020: 1,204 should equal 1,211 (1,180 + 31): difference 7, at least 5.5 given the reported precision
v0002: failed
  records: 1 passed, 1 failed, 0 not evaluated
  - qCPI=LEI-B: -5 should exceed 0: difference 5
v0003: passed
  records: 1 passed, 0 failed, 0 not evaluated
v0004: not_applicable
  message: precondition not met
  records: 0 passed, 0 failed, 0 not evaluated
4 rules: 2 failed, 1 passed, 1 not_applicable
```

## Editor support

`tokenize(expression)` (in `dpmxl.parser`) returns `Token(kind, text, start,
end)` tuples for syntax highlighting: `keyword`, `function`, `operator`,
`punctuation`, `brace`, `table`, `table_group`, `operation`, `variable` and
`parameter` references, `axis` coordinates (`r0010`, `c*`), `type`, `period`,
`item`, `identifier` and the literal kinds `number`, `string`, `date`,
`boolean` and `null`; the parser works from the same tokens. `dpmxl.grammar`
lists the keywords, operators, function names and parameter types as
frozensets; `canonical_function(name)` gives the `Call.name` a spelling parses
to (`max_aggr` is `max`), `CALL_NAMES` all of them; `textmate_grammar()` builds the TextMate grammar in
[`editors/dpm-xl.tmLanguage.json`](https://github.com/luukhopman/dpm-xl/blob/main/editors/dpm-xl.tmLanguage.json).

## Supported language

- Statements separated by `;`, temporary assignments `name := expression`
  and persistent assignments `{tT, r…, c…} <- expression` or `{vX} <- …`
  (`parse_program`; `evaluate_rule` and `dpm-xl check` accept them too).
- `with {context} [where …]: body`, nested contexts replacing inherited parts.
- Selections `{tTABLE, r…, c…, s…, default: v, interval: b}` with single codes,
  inclusive ranges (`r0010-0050`), lists (`(c0010, c0030)`) and wildcards.
- `{v_TABLE}` filing-indicator tests and `{vName}` report parameters; typed
  parameters `{p_Name, number|integer|string|date|boolean|item|set-…[, default:
  v]}`; operation references `{o_Code[, r…, c…]}` and table groups
  `{g_Group, …}`. A `_` after a reference prefix is cosmetic (`t_T1` is `tT1`)
  and `` t`code` `` escapes a code.
- Literals: numbers, `4.5%`, `"text"`/`'text'` (and `''`), `#2026-12-31#`,
  `#2026-12-31T10:00:00#`, `true`/`false`, `null`, items `[eba_qEC:qx01]`;
  escaped names such as `` `x.y` `` for keys.
- Operators `+ - * /`, `&` (text), `= != <> < <= > >=`, `in`, `not`, `and`,
  `or`, `xor`, `if … then … [else …] endif`.
- Sets: literals `{1, 2}`, `{[eba_qEC:qx01], [eba_qEC:qx02]}` and `{}`;
  `set_of(x)`, `union`, `intersect`, `setdiff`, `symdiff`; `in` with any set,
  including a selection; `default: {…}` for set parameters.
- Aggregates `sum`, `count`, `avg`, `min`, `max`, `median` (and the
  specification's `min_aggr`/`max_aggr` spellings) with `group by`;
  scalar `abs`, `isnull`, `nvl`, `len`, `substr`, `match`, `min`/`max` with
  several operands, `exp`, `ln`, `sqrt`, `power`, `log`; `year`, `semester`,
  `quarter`, `month`, `week`, `day` and `date(y, m, d)`;
  `time_shift(x, A|S|Q|M|W|D, n[, key])`, `annualise(x, fiscalYearEnd, key)`;
  `filter(data, condition)`.
- Analytic `rank(x over (…))` and aggregates with `over (partition by k, …
  order by k [asc|desc], … [data points|range] between … and …)`, with bounds
  `unbounded preceding|following`, `current data point` and `n [A|S|Q|M|W|D]
  preceding|following`.
- Clauses `[where …]`, `[get key]`, `[sub key = value]`, `[rename a to b]`.

Every distinct EBA rule and precondition expression in releases
3.4–4.4 parses, except two source expressions with typos (`trueendif`,
`ornot`), which are reported as syntax errors.

## Semantics

- **Records and keys.** A selection yields one record per data point. Its key
  holds every closed axis that selects more than one coordinate (`r`, `c`, `s`;
  an axis that is not written counts when the table has several coordinates on
  it) plus open key components such as `qEBB`. Binary operators natural-join on
  shared keys; a scalar broadcasts. Operands with unrelated keys are an error.
- **Missing facts** take the selection's `default`; with no default they are
  null. Providers must therefore return every defined cell of a closed
  selection, reported or not.
- **Interval arithmetic.** With `interval: true`, numbers follow the Eurofiling
  interval arithmetic functions (`iaf:*`, version 1.1.1) that EBA validation
  rules are based on. A fact reported with `decimals = d` stands for
  `value ± 0.5·10^-d` (`INF` is exact; constants and defaults are exact). Sums
  and differences add thresholds; products use `|A·δB| + |B·δA| + δA·δB`;
  quotients take the largest deviation of the four endpoint quotients
  (skipping a zero divisor); `abs` and negation keep the threshold; `min` and
  `max` keep the chosen value's threshold. `a = b` holds when
  `|a − b| ≤ δa + δb` (the intervals overlap), `a ≤ b` when
  `a − b ≤ δa + δb`, `a ≥ b` when `a ≥ b − (δa + δb)`, and likewise for the
  strict comparisons. With `interval: false` facts are exact. Arithmetic
  keeps 34 significant digits (IEEE decimal128) in any thread decimal context.
  Explanations report each side's interval and the *gap*: how far apart the
  closest values within those intervals still are.
- **Null.** Null propagates through arithmetic, comparisons and functions
  (except `isnull` and `nvl`). `and`/`or`/`not` use three-valued (Kleene)
  logic. A record whose result is null is "not evaluated", never a failure.
  Division by zero is a run-time error, as the specification requires; like
  a type error (a non-Boolean `if` condition included), it fails only its
  record, so the rule is an error only if that record reaches the result
  (`if {x} != 0 then {y} / {x} > 1 endif` is not).
- **Conditionals.** `if` takes the `else` branch when the condition is null;
  without `else`, a Boolean `then` (`{v_…}` and Boolean facts included)
  yields true where the condition is false or null. The result has the
  condition's record structure; branch keys the condition lacks widen it, so each condition record applies to every branch
  record sharing its keys (the columnar evaluator hands that case to the
  reference evaluator).
- **Aggregates** over no records are null, except `count`, which is 0;
  `count` counts non-null values. `max` and `min` also order dates, text and
  items by their text (ISO dates in date order, items by category and code),
  as presence checks expect; Booleans, and numbers mixed with other
  values in one group, are an error.
- **Analytic functions** keep the operand's records: each gets the aggregate
  of the records in its window (or its rank) within its partition. Partition
  and order keys must be keys of the operand; `rank` needs `order by` and
  ranks by those keys, ties sharing the lowest rank and leaving gaps (1, 1,
  3). Without a window clause the window is the whole partition, or with
  `order by` every record up to the current one and its peers (`range
  between unbounded preceding and current data point`). `data points`
  windows count records; `range` windows compare the single order key's
  values (numbers, or dates with a period: `3 M preceding` is three calendar
  months back). `preceding` follows the sort direction. These analytic calls
  are `Analytic` nodes, not `Call`s, and `rank` is not in
  `evaluator.AGGREGATES`.
- **Clauses.** `[get key]` omits records whose fact is null; a `where` or
  `sub` on a selection inside a `with` body overrides the terms of the
  context's `where` (split at `and`) that name the same key; the other terms
  still apply. Booleans order `false < true`.
- **Text and dates.** `&` joins text; other operands are an error. `substr(s,
  start, length)` counts from 1 (start ≥ 1, length ≥ 0, whole numbers) and
  yields `''` past the end. `log(x, base)` follows `ln` (null outside its
  domain). `week` is the ISO 8601 week, `semester` 1 or 2; `date(y, m, d)` of
  an impossible day is an error. A date equals a date-time at midnight.
- **Sets** hold distinct non-null values (numbers exactly, items ignoring the
  `eba_` prefix) in first-seen order. An operand of `in` or of a set operator
  that is not a set stands for the set of its non-null values, so
  `{c0010} in {tT, r*, c0020}` tests against the column's values. Sets cannot
  be compared or appear in a rule's result; a set `default` on a cell
  selection is an error.
- **References.** `{p_Name, type}` reads `parameter(Name)` and checks its
  type (Python numbers become `Number`, text becomes an item or date for those
  types, a list or set becomes a set); a missing value takes the `default` or
  is null. `{g_Group, …}` selects from every table the provider's
  `table_group(code)` lists, keyed by table code `t` when there are several
  (the tables must share their keys). `{o_Code, …}` evaluates the expression
  the provider's `operation(code)` returns; its axes keep the result's
  matching `r`/`c`/`s` records (dropping a key selected by one code),
  `default` fills nulls and `interval: false` makes numbers exact. Without
  those provider methods the rule is `unsupported`; an operation that refers
  to itself is an error.
- **Statements** run in order; the last one gives the rule's records and
  verdict. `name := e` keeps `e`'s records for later statements, where `name`
  wins over a report parameter of that name and loses to a key component
  inside a clause. `{target} <- e` computes `e` and returns it in
  `RuleResult.assignments`; nothing is written to the report.
- **Time.** `time_shift(x, Q, 1, refPeriod)` presents the previous quarter's
  records as the current period's, as in the EBA introduction to DPM-XL:
  when the key is not a key component of `x` (`refPeriod`, or no key), `x` is
  evaluated on the report the provider's `earlier_report(period, count)`
  returns, `count` periods earlier (later when negative); without that
  method, or when it returns `None`, the rule is `unsupported`. When the key
  is a date key component of `x`, its values move `count` periods later
  instead. Periods move dates by calendar months (12, 6, 3, 1; a month's
  last day stays the last day) or by 7 or 1 days. `annualise(x, m, key)`
  scales a year-to-date amount to a year: `x · 12 / months`, where `months`
  counts the months from the fiscal year that ends in month `m` up to and
  including the month of the date in `key` (a date key component, else the
  report parameter of that name). It treats that month as complete, so it is
  meant for period-end dates.
- **Key names** in `where`, `group by`, `sub` and `get` match with or without
  the DPM 2.0 `q` prefix and ignore case (`EBB` finds `qEBB`).
- **Items** compare by code and category, ignoring the `eba_` prefix and a
  category missing on either side.
- **Preconditions** make a rule `not_applicable` unless they yield at least one
  true record.

A `RuleResult` has status `passed`, `failed`, `not_applicable`, `error`
(syntax, unknown table, type mismatch) or `unsupported`, plus one `Outcome`
per record with the data points it used.

These semantics follow the EBA *DPM-XL language specification v0.9*
(operators and data model documents) and the Eurofiling interval arithmetic
functions. Where the specification is ambiguous or contradicts itself (sum of
no records, `count` over nulls, key-name aliases, the radius formulas for
products and quotients), the choice above is the one that avoids false
failures.

## Columnar evaluation

`dpmxl.columnar.evaluate_rule_columnar(expression, provider)` evaluates a rule
on polars frames from a `FrameProvider` (`select_frame(query)` returns one row
per data point with `k:<key>` text columns and the `num`, `thr`, `txt`, `flag`
value columns). Values are `Decimal(38, 12)`: sums and differences are exact,
products and quotients round to 12 decimals (thresholds of quotients round
up), where the reference evaluator keeps 34 significant digits, so an exact
comparison that hinges on the 13th decimal can differ. Keys are joined like
`recordset.combine`, and a `FrameCache` shares selections across rules within
a row budget; rules evaluated on several threads build each selection once.
Anything the module does not implement, including values that do not fit
`Decimal(38, 12)`, arithmetic that would overflow, any record error (a zero
divisor or a type error, which the reference evaluator confines to its
record), ordering items and text that may be an item, raises
`ColumnarUnsupported` so the caller falls back to the reference evaluator. `tests/test_columnar.py`
checks both evaluators agree case by case. `PointsFrameProvider` adapts any `DataProvider`.

## Modules

| Module | Purpose |
| --- | --- |
| `dpmxl.parser` | Tokenizer and recursive-descent parser. Nodes keep source spans. |
| `dpmxl.grammar` | Keywords, operators and function names; the TextMate grammar. |
| `dpmxl.ast` | Expression tree, selections, axis selectors and item literals. |
| `dpmxl.values` | `Number` with interval tolerance, comparison and formatting. |
| `dpmxl.recordset` | Keyed record sets and the natural join used by every operator. |
| `dpmxl.evaluator` | Evaluation, preconditions and per-record outcomes. |
| `dpmxl.explain` | Fills a failing record's formula with operand values. |
| `dpmxl.references` | Static selections (with `with` context applied) and `{v_…}` templates. |
| `dpmxl.provider` | `DataProvider` protocol and the in-memory `MemoryProvider`. |
| `dpmxl.columnar` | The same semantics on polars frames (optional `columnar` extra). |
| `dpmxl.cli` | `dpm-xl check` and `dpm-xl eval`. |

## Stability

Releases follow [semantic versioning](https://semver.org). The public API is
every name in the `__all__` of the modules listed above, including the
expression tree in `dpmxl.ast` (frozen node classes with source `span`s,
`walk` and `children`) for callers that analyse rules, and the frame schema
below. Names starting with an underscore are internal. Explanation and error
wording may improve in minor releases; statuses, keys and field names may not.
`dpmxl.__version__` gives the installed version. See
[CHANGELOG.md](https://github.com/luukhopman/dpm-xl/blob/main/CHANGELOG.md)
for each release.

### Columnar frame schema

A `FrameProvider` (or a caller building frames for `frame_from_points`'s
consumers) returns one row per selected data point with these columns:

| Column | Type | Content |
| --- | --- | --- |
| `cell` (`CELL`) | any | Opaque cell reference, returned in outcomes |
| `r`, `c`, `s` | text or null | Raw closed coordinates |
| `k:<code>` | text (may be categorical) | One per open key: text, canonical items (`category:code`, `canonical_item`) or ISO dates |
| `num` (`NUM`) | `DEC` = `Decimal(38, 12)` | Numeric value |
| `thr` (`THR`) | `DEC` | Its interval threshold, `0.5·10^-decimals` (0 when exact) |
| `txt` (`TXT`) | text | Text, canonical item or ISO date value |
| `flag` (`FLAG`) | Boolean | Boolean value |

`VALUE_COLUMNS` is `(num, thr, txt, flag)`; all four are null for a cell
with no fact, and `value_columns(value)` maps one Python value to them.
A cell and open-key combination appears at most once.

### Threads

`evaluate_rule` and `evaluate_rule_columnar` may run concurrently on one
report. `parse_cached` and `FrameCache` are thread-safe; `FrameCache` builds
each selection once while other threads wait for it. A shared
`SelectionCache` is safe too, though two threads that miss the same selection
at once may both build it. Providers shared across threads must be safe to
read concurrently; `MemoryProvider` is.

## Development

```bash
uv sync
uv run pytest
uv run ruff check . && uv run ruff format --check . && uv run ty check
```

After changing `dpmxl.grammar`, regenerate the editor grammar:

```bash
uv run python -c "import json; from dpmxl.grammar import textmate_grammar; print(json.dumps(textmate_grammar(), indent=2))" > editors/dpm-xl.tmLanguage.json
```

`tests/test_grammar_coverage.py` has an example for every alternative of the
DPM-XL grammar; each must parse, and each that yields a value is evaluated.
`tests/data/eba_expressions.txt` is a sample of about 300 EBA rule
expressions covering every construct above. Every line must parse.
