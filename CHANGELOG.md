# Changelog

All notable changes to this project are documented here. The project follows
[semantic versioning](https://semver.org).

## Unreleased

### Added

- Documentation site at https://luukhopman.github.io/dpm-xl/, with
  `llms.txt` and `llms-full.txt`; every example in it is tested.
- `examples/rules.txt` and `examples/xbrl-report/`, a small xBRL-CSV report
  for the end-to-end guide.

### Changed

- `dpm-xl --help` points to the documentation for the data file format.

## 1.0.0 - 2026-10-24

### Added

- `dpm-xl eval` takes a rule file as well as one expression and summarizes
  every rule; `check` and `eval` accept `--json`; `--version` and examples in
  `--help`.
- Runnable examples in `examples/`, run by the tests.
- `dpmxl.__version__`; `--json` output carries `schema_version`.
- The public API is documented: every name in a module's `__all__`
  (including the `dpmxl.ast` tree and `VALUE_COLUMNS`), the columnar frame
  schema and which caches are thread-safe.
- `tokenize()` and `Token(kind, text, start, end)` are public, with kinds
  for syntax highlighting (keyword, function, operator, brace, table and axis
  references, literal kinds, item, identifier, punctuation and more); every
  AST node's source `span` is documented.
- `DpmXlSyntaxError.end`, and `pointer()` underlines the offending text.
- Text concatenation `&`, `substr`, `log`, the date functions `year`,
  `semester`, `quarter`, `month`, `week`, `day` and `date(y, m, d)`, and date
  literals with a time part (`#2026-12-31T10:00:00#`).
- Sets: literals such as `{1, 2}` and `{}`, `set_of`, `union`, `intersect`,
  `setdiff` and `symdiff`, `in` with any set operand and `default: {…}`;
  the `ValueSet` value type.
- Typed parameters `{p_Name, type[, default: v]}`, operation references
  `{o_Code, …}` and table groups `{g_Group, …}`, resolved through optional
  `operation(code)` and `table_group(code)` provider methods (and
  `MemoryProvider`'s `operations` and `table_groups`, also in the CLI data
  file); `Reference.kind` and `Reference.code`, and `tables(node, provider)`
  expands table groups.
- Statements separated by `;` with temporary (`name := e`) and persistent
  (`{target} <- e`) assignments: `parse_program`, the `Program`,
  `Assignment` and `PersistentAssignment` nodes, and
  `RuleResult.assignments`. `evaluate_rule`, the columnar fallback and
  `dpm-xl check` accept programs; `parse` still returns one expression and
  allows a trailing `;`.
- `time_shift` evaluates its operand on another period's report from the
  optional `earlier_report(period, count)` provider method (or
  `MemoryProvider(earlier_reports=...)`, or `earlier` in the CLI data file),
  or moves a date key; its points carry `provider.EarlierRef` refs, and
  explanations show the earlier report's values;
  `annualise(x, fiscalYearEnd, key)`.
- Analytic functions: `rank` and aggregates with `over (partition by …
  order by … window)`, parsed to the `Analytic` node with `Window` and
  `WindowBound`.
- `tests/test_grammar_coverage.py`: an example for every alternative of the
  DPM-XL grammar, each parsed and, where it yields a value, evaluated.
- `dpmxl.grammar`: keywords, operators, function names and parameter types as
  frozensets (`AXIS_LETTERS` for `r`, `c`, `s`), `canonical_function` and
  `CALL_NAMES` for the `Call.name` of each spelling, and a TextMate grammar in
  `editors/dpm-xl.tmLanguage.json`.

### Changed

- **Breaking:** `dpm-xl` exits with status 3, not 2, for an evaluation error
  or unreadable input, so 2 means a usage error only.
- The tokenizer splits selections into tokens; `Token.text` is the exact
  source text (quotes, brackets and backticks included) and `Token` is a
  named tuple. Error positions inside selections point at the component.
- `{}` is the empty set rather than an empty selection, and `In.values` may
  be any set-valued node, not only a `SetLiteral`; `Value` includes
  `ValueSet`.
- `time_shift` is no longer always `unsupported`: with a provider that has
  `earlier_report` it is evaluated, and `MemoryProvider` without the
  requested report reports it with a new message. The columnar evaluator
  hands every `time_shift` rule to the reference evaluator (raising
  `ColumnarUnsupported`) instead of reporting `unsupported` itself.
- A `_` after the `t`, `g`, `o` and `p` prefixes is cosmetic, as the
  DPM-XL grammar says: `{t_T1}` selects table `T1`, not `_T1`. `{v_X}`
  stays a filing-indicator test. `SelectionSpec` has
  `table_group` and `operation` fields.
- `children()` and `walk()` reach the `default` of a selection, a `with`
  context and a typed parameter.
- `with`, `to`, `where`, `get`, `sub`, `rename` and `over` are reserved
  words; escape a key of that name as `` `to` ``. `a<-1` is now a persistent
  assignment; write `a < -1` for the comparison.
- `Number.of` raises `ValueError` for `decimals` beyond the decimal128 range
  (about -6,100 to 6,100, such as -7000), which 0.1.1 accepted; callers that
  pass report-level decimals should catch it. The CLI reports it.
- Syntax errors read in plain words, such as "expression ends where an
  operand is expected" and "expected a name, found ')'".
- A `where` or `sub` on a selection inside a `with` body overrides only the
  context's `where` terms on the same key; the other terms still apply.
- Expressions nested more than 50 deep (chained clauses included), and
  numbers outside the decimal128 range, are syntax errors; `4.5%%` is no
  longer read as 0.00045.
- Explanations round the remaining gap down, so "at least" never overstates
  it, and keep only the parentheses the rule writes.

### Fixed

- A division by zero or type error fails only its own record: a rule is an
  error only if that record reaches the result, so guards such as
  `if {x} != 0 then {y} / {x} > 1 endif` work.
- `evaluate_rule` reports deep recursion, decimal overflow and type errors in
  `[sub]` as status `error` instead of raising.
- Arithmetic no longer depends on the caller's decimal context.
- Explanations show the right values after `[rename]`.
- Explanations of values around 1e33 and larger with `interval: true` no
  longer raise.
- `if` without `else` treats filing indicators (`{v_…}`) and Boolean facts as
  Boolean, as for other conditions.
- Items built with an `eba_` category match parsed items.
- The columnar evaluator hands every case it cannot match exactly to the
  reference evaluator: any polars failure, values outside `Decimal(38, 12)`,
  numeric open keys, ordering items and text that may be an item.
- The CLI accepts `"decimals": "INF"` and reports malformed data without a
  traceback.
- The columnar evaluator hands record-level type errors (comparing text with
  numbers, `and`/`not`/`abs` on the wrong type, mixed `max`/`min` groups) to
  the reference evaluator, which fails only the records concerned.
- A non-Boolean condition of a keyed `if` fails only its records.
- The columnar evaluator no longer orders items without a category as text;
  item literals in `<`, `<=`, `>`, `>=` and such items in the data go to the
  reference evaluator, which reports the error.

### Performance

- `if` conditions whose branches add keys look records up by key instead of
  scanning every branch record; repeated `where` verdicts are reused.

## 0.1.1 - 2026-10-23

### Performance

- Faster explanations and selections when many rules run against large
  reports.

## 0.1.0 - 2026-10-23

First release on PyPI.
