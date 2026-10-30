# Changelog

All notable changes to this project are documented here. The project follows
[semantic versioning](https://semver.org).

## 1.3.0 - 2026-10-30

### Added

- Text output of `eval` and `check-report` lists only rules that failed,
  are an error or are unsupported; `--all` lists every rule.
- Rules in a JSON rule file take `severity` (`error` or `warning`),
  `active` and `modules`; `dpm-xl eval` and `check` skip inactive rules.
- `dpmxl.rules.load_rules` reads a rule file, and `evaluate_rules`
  evaluates its rules on one report.
- `dpm-xl eval --format junit` writes a JUnit XML report, one test case per
  rule.
- `dpm-xl eval --fail-on error|warning` sets which failing rules fail the
  run; by default a failing `warning` rule does not.
- Module files (`dpm-module/1`, or dpm-synth's `dpm-synth-template/1`):
  `dpmxl.module.load_module` reads one, and `dpm-xl check` and `eval` take
  one as their rule source.
- Module file data types are the DPM's: `es` is text that may be empty,
  `t` a Boolean that is true, `dt` a date or date and time, `u` a URI and
  `o` an ordinal.
- `dpmxl.xbrl.ReportProvider` evaluates a module's rules on a report read
  with dpm-xbrl (`pip install "dpm-xl[xbrl]"`).
- `dpmxl.xbrl.check_report` returns a report's filing findings and its
  module's rule results together.
- `dpm-xl check-report MODULE REPORT` prints both as text, JSON or JUnit
  XML.
- `ReportProvider` and `check_report` take earlier reports as `previous`,
  for `time_shift` across periods.
- `dpm-xl check-report --previous REPORT` passes an earlier report.
- The contextual components `entityID`, `baseCurrency` and the
  `decimals…` names read the report parameters of those names, with their
  type; a missing one is null.
- The tests parse all 14,174 distinct EBA expressions of DPM releases 3.4
  to 4.4, committed as test data.
- The language reference lists every place where dpm-xl differs from the
  DPM-XL specification v0.11, with the section concerned.
- `diagnose` warns about syntax the v0.11 grammar rejects and no EBA rule
  needs, such as `.5` or `<>` (code `non-portable`); `dpm-xl check
  --strict` fails on it.
- The language reference lists the syntax dpm-xl accepts beyond the v0.11
  grammar, with the evidence for each.
- `dpmxl.dpm` exports a module of an EBA DPM 2.0 database (SQLite, or the
  Access file with mdbtools) as a module file.
- `dpm-xl export-module DATABASE MODULE` writes the module file, and
  `dpm-xl list-modules DATABASE` lists the releases and modules.
- The export writes each data type as the DPM codes it, `es` and `t`
  included.

### Changed

- **Breaking:** `dpm-xl check` exits with status 1 for any error, such as
  an unknown function, not only a syntax error; `--strict` also fails on
  warnings.
- **Breaking:** `eval` exits with status 1, not 3, for a rule that is an
  error, and an `unsupported` rule no longer affects the exit status.
- **Breaking:** `{v_X}` and `{vX}` are the same variable (DPM-XL v0.11
  §3.1.1): a template's filing indicator when `X` is a template code, else
  report parameter `X`.
- **Breaking:** both parse to `Variable`, which replaces the
  `TableReported` and `Parameter` nodes.
- **Breaking:** the `--json` output opens with `tool`, `version` and a
  `summary` of counts (`schema_version` 2).
- **Breaking:** `load_memory_provider` moved from `dpmxl.cli` to
  `dpmxl.provider`.
- **Breaking:** `dpmxl.cli.INVALID_INPUT` is now `EXIT_INPUT`.
- An expression given on the command line is labelled `expression`, not
  `argument`.
- A `time_shift` without the earlier report names its reference date.
- The text output of `dpm-xl eval` counts null records as `null`.
- A malformed rule file names the field by its JSON path, such as
  `[0].severity`.
- Unreadable input is reported as `error: PATH: reason`.
- The end-to-end guide and the toolkit tour use `ReportProvider` instead of
  a hand-written provider.

### Fixed

- `count` of a set is its number of members, as in `count({1, 2, 2}) = 2`;
  it used to be 1.
- `=` and `!=` compare two sets by their members, so `{1, 2} = {2, 1}` is
  true; they used to fail with `cannot compare set with set`.
- An analytic function with `order by` and no window clause takes the
  whole partition, as the specification says, instead of a running window.
- `ln`, `sqrt` and `log` outside their domain, such as `ln(0)`, are an error
  for their record instead of null.
- `date()` of a day, month or year that does not exist, such as
  `date(2026, 2, 30)`, is null instead of an error.
- `if` without `else` leaves out the records whose condition is not true,
  as the specification says, instead of making them true or null.
- A `where` or `sub` on a selection inside `with … [where …]` replaces the
  context's `where` entirely, as the specification says; it used to replace
  only the terms on the same key.
- An operand with a `default` that a `where` filters to nothing takes its
  default next to the other operands, also under an aggregate, as the EBA's
  formulas do; such rules were not applicable.
- `[sub]` takes several pairs, as in `[sub qX = 1, qY = 2]` (§11.4.1);
  it was a syntax error.
- `where` can test a record's value as `f`, as in `[where f != 0]`, also in
  a `with` context, where a condition on `f` alone applies to every
  selection instead of being dropped.
- `partition by` and `order by` of an analytic function can name `f`, so
  `rank(x over (order by f desc))` ranks by value; null order values come
  last.
- `{o_X}` reads temporary `X` of the same script, as in `op1 := …;
  {oOp1, r0010}`, before asking the provider for an operation.
- Names of temporaries, and the table, table group, operation and parameter
  codes `MemoryProvider` looks up, ignore case, so `{tt, r0010}` reads
  table `T`.
- Division by an interval that contains zero, such as `0.4 ± 0.5`, is an
  error for its record, as the specification says; the zero endpoint used
  to be skipped.
- `max` and `min` keep the largest tolerance among equal values, whatever
  their order; they used to keep the first one's.
- `median` keeps the tolerance of the middle value, or the mean of the two
  middle values' tolerances, instead of dropping it.
- The concepts pages cite the DPM-XL specification v0.11 instead of v0.9
  and no longer call points it settles ambiguous.
- `diagnose` checks the `partition by` and `order by` keys of analytic
  functions; it used to skip them.
- `diagnose` suggests a short name one typo away, such as `sum` for `sun`.
- The columnar engine leaves a set-valued `{vX}` to the reference engine;
  it compared the set as text.
- `group by r`, `c` or `s` of a selection with no records gives no groups
  instead of an error.
- An operand with a `default` and no records in an `if` condition takes
  its default, as it does in `and`; such rules were not applicable.
- The columnar engine leaves a `where` on a report parameter, such as
  `[where Level = "con"]`, to the reference engine instead of failing.

## 1.2.3 - 2026-10-26

### Fixed

- `len` and `match` read a Boolean as `true` or `false`, as a report
  holds it, instead of Python's `True` and `False`. The columnar evaluator
  leaves them to the reference evaluator, which it used to disagree with.
- `substr` and `&` read an item as its qualified name, as `len` does,
  instead of failing with `needs text, found item`.
- The columnar evaluator leaves equality and `in` tests between items and
  text starting with `eba_` to the reference evaluator. It compared
  `"eba_CU:EUR"` with `[CU:EUR]` as text and found them unequal.

## 1.2.2 - 2026-10-26

### Fixed

- `len` and `match` read an item as its qualified name, `eba_NC:C`, as a
  report holds it. They used to drop the prefix, so `len` of `[eba_NC:C]`
  was 4 instead of 8. The columnar evaluator leaves text with a colon to
  the reference evaluator.

## 1.2.1 - 2026-10-25

### Fixed

- `date()` with a day, month or year that does not exist raises `invalid
  date: 2026-02-30` on every supported Python version; the message used to
  repeat Python's own wording, which differs between versions.

## 1.2.0 - 2026-10-25

### Added

- The language reference documents every construct with its syntax, types,
  null and interval behaviour, errors and examples whose results the tests
  compute, and a new quick reference has the language and its grammar on
  one page. The tests check that the reference covers `dpmxl.grammar`.
- `Recordset.default`: the record of a key a record set lacks, from a
  selection's `default`. `Recordset.map` carries it and `Recordset.lookup`
  returns it for a missing key.
- `Frame.has_default`: whether a columnar frame comes from a selection with
  a `default`.

### Fixed

- An operand with a `default` stands for its default where another operand
  has a record it lacks, as a fact variable's fallback value does, instead
  of dropping that record from the join. `with {default: null}: if not
  isnull({tA, c0010}) then not isnull({tB, c0010}) endif` over two parts of
  an open table now fails for a key filed only in `A`; it was not evaluated.
  Operands without a default still decide the keys and join on the keys
  they share. An `if` condition with a default also covers keys only a
  branch has. `where`, `sub`, `filter`, a `with` context's `where`,
  `rename`, a `time_shift` of a date key and `if` results keep the default,
  so a filtered operand falls back to it for keys the other operands bring;
  `get`, aggregates and analytic functions do not. The columnar evaluator
  leaves these cases to the reference evaluator.
- `[rename a to b]` on a record set that already has a key `b` is an error;
  it produced two keys of the same name.
- A `with` context's `where` applies only to the selections that have the
  keys it names. A body selection without them, key-less ones included,
  was an error ("unknown key component" or "where needs a keyed operand").

## 1.1.0 - 2026-10-25

### Added

- `diagnose()` finds problems without report data, as positioned
  `Diagnostic`s with a stable `code`, the `subject` concerned and a
  `suggestion` to replace the text with: every syntax error (parsing
  resumes after one), keywords run together (`ornot`), unknown functions,
  wrong operand counts and selections without a table. Given table layouts
  it also reports unknown tables, rows, columns and sheets, empty ranges,
  clause names that are not keys and, with cell data types, operands of the
  wrong type; given the report parameters, names that resolve to nothing.
  An error means the rule fails, is inapplicable or cannot be evaluated as
  written; a code on an open axis or one the table lacks, whose outcome is
  up to the provider, is a warning.
  `Diagnostic.pointer()` renders one; `DIAGNOSTIC_CODES` lists the codes.
- `dpmxl.grammar.SIGNATURES`: each function's `Signature` (operand counts,
  `group by`, key and period operands), which both evaluators and
  `diagnose()` check calls against.
- `TableLayout.open_axes` and `TableLayout.data_types` describe open axes
  and cell data types (`dpmxl.provider.CELL_TYPES`; it may be partial); data
  files accept them.
- Parsed selections keep source positions: `AxisSelector.span` and `spans`,
  and `SelectionSpec.source_span`.
- `dpm-xl check` reports every problem `diagnose()` finds, also as
  `diagnostics` in `--json`. `--layouts DATA` checks against a data file's
  tables and parameters; `--strict` fails on any error, not only syntax
  errors.

### Changed

- Calls with the wrong operands fail with one wording in both evaluators,
  such as `abs takes 1 operand, not 2`, before their operands are evaluated.
- `dpm-xl check --json` lists every syntax error, so `errors` may hold
  several entries for one expression: count failing expressions with
  `total - parsed`, not `len(errors)`.
- The errors for `max_aggr` and `min_aggr` with several operands and for
  `rank` without `over` point at the function name; an unknown selection
  component's error spans the whole component.

### Fixed

- A range that repeats its axis letter, such as `r0440-r0480`, selected every
  coordinate from its lower bound up; it now selects what `r0440-0480` does.
  The letter is dropped only when the lower bound does not start with it, so
  `rr1-rr10` reads as written (see `AxisSelector`).

## 1.0.0 - 2026-10-24

### Added

- Python 3.15 support, tested in CI on 3.11 to 3.15 with and without extras.
- Documentation site at https://luukhopman.github.io/dpm-xl/, with
  `llms.txt` and `llms-full.txt`; every example in it is tested.
- `examples/rules.txt` and `examples/xbrl-report/`, a small xBRL-CSV report
  for the end-to-end guide.
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

- `dpm-xl check` and `eval` report a rule file path that does not exist
  instead of reading it as an expression; `check --json` errors carry `end`.
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
