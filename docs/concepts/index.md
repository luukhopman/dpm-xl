---
description: The semantics of DPM-XL as dpm-xl implements them, and where the specification leaves a choice.
---

# Concepts

How DPM-XL rules are evaluated. These pages explain the semantics; the
[language reference](../reference/language.md) lists every construct.

- [Records and keys](records-and-keys.md): selections yield keyed records;
  operators join them.
- [Null logic](null.md): defaults, null propagation, three-valued logic and
  errors confined to their record.
- [Interval arithmetic](intervals.md): reported precision as intervals, and
  the gap in explanations.
- [Preconditions and results](results.md): the five statuses and what a
  result holds.
- [Statements and assignments](statements.md): scripts with `:=` and `<-`.
- [Sets](sets.md): set literals, parameters, operators and `in`.
- [Aggregates and analytic functions](analytics.md): `group by`, `rank` and
  windows.
- [Time](time.md): dates, `time_shift` and `annualise`.
- [Parameters, operations and table groups](references.md): everything a
  rule reads besides cells.

## Sources and choices

These semantics follow the EBA *DPM-XL language specification v0.9*
(operators and data model documents) and the Eurofiling interval arithmetic
functions. Where the specification is ambiguous or contradicts itself (sum
of no records, `count` over nulls, key-name aliases, the radius formulas for
products and quotients), dpm-xl makes the choice that avoids false failures,
and says so on the page concerned.
