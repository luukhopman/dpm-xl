# dpm-xl

A Python parser and evaluator for **DPM-XL**, the expression language of EBA
validation rules and similar checks. The core has no dependencies; the
optional `columnar` extra adds a polars evaluator for reports with millions of
open-table rows.

```python
from dpmxl import evaluate_rule, explain

expression = (
    "with {tC_01.00, c*, default: 0, interval: true}: {r0010} = {r0020} + {r0030}"
)
result = evaluate_rule(expression, provider, precondition="{v_C_01.00}")
for outcome in result.failures:
    print(explain(result.evaluation, expression, outcome.key).summary)
# 1,204 should equal 1,211 (1,180 + 31): difference 7, at least 5.5 given the
# reported precision
```

The package does not read report files and knows nothing about a particular
DPM release. Data comes through a small provider protocol (see below), so the
same evaluator works against an xBRL-CSV upload, a database, or test fixtures.

dpm-xl is an independent project, not affiliated with or endorsed by the
European Banking Authority.

## Modules

| Module | Purpose |
| --- | --- |
| `dpmxl.parser` | Tokenizer and recursive-descent parser. Nodes keep source spans. |
| `dpmxl.ast` | Expression tree, selections, axis selectors and item literals. |
| `dpmxl.values` | `Number` with interval tolerance, comparison and formatting. |
| `dpmxl.recordset` | Keyed record sets and the natural join used by every operator. |
| `dpmxl.evaluator` | Evaluation, preconditions and per-record outcomes. |
| `dpmxl.explain` | Fills a failing record's formula with operand values. |
| `dpmxl.references` | Static selections (with `with` context applied) and `{v_…}` templates. |
| `dpmxl.provider` | `DataProvider` protocol and the in-memory `MemoryProvider`. |
| `dpmxl.columnar` | The same semantics on polars frames (optional `columnar` extra). |
| `dpmxl.cli` | `dpm-xl check` and `dpm-xl eval`. |

## Supported language

- `with {context} [where …]: body`, nested contexts replacing inherited parts.
- Selections `{tTABLE, r…, c…, s…, default: v, interval: b}` with single codes,
  inclusive ranges (`r0010-0050`), lists (`(c0010, c0030)`) and wildcards.
- `{v_TABLE}` filing-indicator tests and `{vName}` report parameters.
- Literals: numbers, `4.5%`, `"text"`/`'text'`, `#2026-12-31#`, `true`/`false`,
  `null`, items `[eba_qEC:qx01]`.
- Operators `+ - * /`, `= != <> < <= > >=`, `in {…}`, `not`, `and`, `or`, `xor`,
  `if … then … [else …] endif`.
- Aggregates `sum`, `count`, `avg`, `min`, `max`, `median` (and the
  specification's `min_aggr`/`max_aggr` spellings) with `group by`;
  scalar `abs`, `isnull`, `nvl`, `len`, `match`, `min`/`max` with several
  operands, `exp`, `ln`, `sqrt`, `power`; `filter(data, condition)`.
- Clauses `[where …]`, `[get key]`, `[sub key = value]`, `[rename a to b]`.

`time_shift` needs the previous reporting period and is reported as
`unsupported`. Every distinct EBA rule and precondition expression in releases
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
  a type error, it fails only its record, so the rule is an error only if
  that record reaches the result (`if {x} != 0 then {y} / {x} > 1 endif` is
  not).
- **Conditionals.** `if` takes the `else` branch when the condition is null;
  without `else`, a Boolean `then` yields true where the condition is false or
  null. The result has the condition's record structure; branch keys the
  condition lacks widen it, so each condition record applies to every branch
  record sharing its keys (the columnar evaluator hands that case to the
  reference evaluator).
- **Aggregates** over no records are null, except `count`, which is 0;
  `count` counts non-null values. `max` and `min` also order dates, text and
  items by their text (ISO dates in date order, items by category and code),
  as presence checks expect; Booleans, and numbers mixed with other
  values in one group, are an error.
- **Clauses.** `[get key]` omits records whose fact is null; a `where` or
  `sub` on a selection inside a `with` body overrides the terms of the
  context's `where` (split at `and`) that name the same key; the other terms
  still apply. Booleans order `false < true`.
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
`Decimal(38, 12)`, arithmetic that would overflow, record errors (such as a
zero divisor) and text that may be an item, raises `ColumnarUnsupported` so
the caller falls back to the reference evaluator. `tests/test_columnar.py` checks both evaluators agree
case by case. `PointsFrameProvider` adapts any `DataProvider`.

## Provider contract

```python
class DataProvider(Protocol):
    def select(self, query: CellQuery) -> Sequence[DataPoint]: ...
    def table_reported(self, table: str) -> bool | None: ...
    def parameter(self, name: str) -> Value: ...
```

`select` resolves the table and axis selectors (`axis_matches` and
`normalize_code` implement range and code matching) and returns all defined
cells of the closed axes with `value=None` where nothing was reported. For an
open table it returns one point per reported key combination, with the key
components in `DataPoint.keys`. `DataPoint.ref` is an opaque identity that
comes back in outcomes, so a caller can highlight cells.

## CLI

```bash
dpm-xl check rules.json            # parse every expression/precondition in a rule list
dpm-xl check "with {tC_01.00}: {r0010} >= 0" --references
dpm-xl eval "with {tC_01.00, c0010, default: 0, interval: true}: {r0010} = {r0020} + {r0030}" data.json
```

`data.json` holds `tables` (`code`, `rows`, `columns`, `sheets`, `open_keys`),
`facts` (`table`, `row`, `column`, `sheet`, `keys`, `value`, `decimals` as an
integer or `INF`, `type`), `reported` and `parameters`.

## Development

```bash
uv sync
uv run pytest
uv run ruff check . && uv run ruff format --check . && uv run ty check
```

`tests/data/eba_expressions.txt` is a sample of about 300 EBA rule
expressions covering every construct above. Every line must parse.
