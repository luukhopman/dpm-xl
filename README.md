# dpm-xl

A dependency-free Python parser and evaluator for **DPM-XL**, the expression
language of EBA validation rules and similar checks.

```python
from dpmxl import evaluate_rule, explain

expression = (
    "with {tC_01.00, c*, default: 0, interval: true}: {r0010} = {r0020} + {r0030}"
)
result = evaluate_rule(expression, provider, precondition="{v_C_01.00}")
for outcome in result.failures:
    print(explain(result.evaluation, expression, outcome.key).summary)
# expected 1,204 = 1,180 + 31, off by 7 (tolerance ±1.5)
```

The package does not read report files and knows nothing about a particular
DPM release. Data comes through a small provider protocol (see below), so the
same evaluator works against an xBRL-CSV upload, a database, or test fixtures.

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
- Aggregates `sum`, `count`, `avg`, `min`, `max`, `median` with `group by`;
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
- **Interval arithmetic.** With `interval: true`, a fact reported with
  `decimals = d` is the interval `value ± 0.5·10^-d`. Sums add tolerances,
  products and quotients use interval bounds, and `a = b` holds when the
  intervals overlap (`a <= b` when `a.low <= b.high`, and so on). With
  `interval: false` facts are exact.
- **Null.** Null propagates through arithmetic, comparisons and functions
  (except `isnull` and `nvl`). `and`/`or` use three-valued logic. A record whose
  result is null is "not evaluated", never a failure. Division by zero is null.
- **Aggregates** over no records are null; `count` counts non-null values.
- **Key names** in `where`, `group by`, `sub` and `get` match with or without
  the DPM 2.0 `q` prefix and ignore case (`EBB` finds `qEBB`).
- **Items** compare by code and category, ignoring the `eba_` prefix and a
  category missing on either side.
- **Preconditions** make a rule `not_applicable` unless they yield at least one
  true record.

A `RuleResult` has status `passed`, `failed`, `not_applicable`, `error`
(syntax, unknown table, type mismatch) or `unsupported`, plus one `Outcome`
per record with the data points it used.

These semantics follow the EBA rule corpus and the published DPM-XL
conventions as far as they could be verified offline; where the language
specification is ambiguous (aggregates over empty sets, key-name aliases),
the choice above is the conservative one that avoids false failures.

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
`facts` (`table`, `row`, `column`, `sheet`, `keys`, `value`, `decimals`,
`type`), `reported` and `parameters`.

## Development

```bash
uv sync
uv run pytest
uv run ruff check . && uv run ruff format --check . && uv run ty check
```

`tests/data/eba_expressions.txt` is a sample of about 300 EBA rule
expressions covering every construct above. Every line must parse.
