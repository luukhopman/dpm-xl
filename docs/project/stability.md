---
description: What the public API is, what semantic versioning promises for it, and what may change in minor releases.
---

# Stability and versioning

dpm-xl follows [semantic versioning](https://semver.org). From 1.0.0, a
change that breaks the public API needs a new major version.

## The public API

- Every name in the `__all__` of the modules in the
  [Python API](../reference/api/index.md), including the expression tree in
  `dpmxl.ast` (frozen node classes with source `span`s, `walk` and
  `children`) for callers that analyse rules.
- The [columnar frame schema](../reference/api/columnar.md#dpmxl.columnar--frame-schema)
  that a `FrameProvider` returns.
- The thread-safety guarantees in [Run rules in threads](../guides/threads.md).
- The CLI: its commands, options, [exit statuses](../reference/cli.md#exit-statuses)
  and the `--json` layout, versioned by `schema_version` (1), and the
  [data formats](../reference/data-formats.md) it reads.

Names starting with an underscore are internal, as are modules whose names
start with one. `dpmxl.__version__` gives the installed version.

## What may change in a minor release

- The wording of explanations (`summary`, `filled` and the other text
  fields), of syntax error messages and of `RuleResult.message`.
- New constructs, functions, token kinds and optional provider methods.
- Constructs the columnar evaluator handles itself instead of raising
  `ColumnarUnsupported`.
- Bug fixes that change a result to what the specification and these
  docs say it should be. They are listed under "Fixed" in the
  [changelog](changelog.md).

Statuses, record keys, field names, `Explanation.kind` values and the JSON
field names do not change outside a major release.

## Supported Python versions

dpm-xl supports the Python versions listed in its package metadata,
currently 3.11 to 3.15.
