# Changelog

All notable changes to this project are documented here. The project follows
[semantic versioning](https://semver.org).

## Unreleased

### Added

- `dpm-xl eval` takes a rule file as well as one expression and summarizes
  every rule; `check` and `eval` accept `--json`; `--version` and examples in
  `--help`.
- Runnable examples in `examples/`, run by the tests.

### Changed

- Syntax errors read in plain words, such as "expression ends where an
  operand is expected" and "expected a name, found ')'".
- A `where` or `sub` on a selection inside a `with` body overrides only the
  context's `where` terms on the same key; the other terms still apply.
- Expressions nested more than 50 deep, and numbers outside the decimal128
  range, are syntax errors; `4.5%%` is no longer read as 0.00045.
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

### Performance

- `if` conditions whose branches add keys look records up by key instead of
  scanning every branch record; repeated `where` verdicts are reused.

## 0.1.1 - 2026-10-23

### Performance

- Faster explanations and selections when many rules run against large
  reports.

## 0.1.0 - 2026-10-23

First release on PyPI.
