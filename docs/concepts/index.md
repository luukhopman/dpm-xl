---
description: The semantics of DPM-XL as dpm-xl implements them, and the specification they follow.
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

## Sources

These semantics follow the
[DPM-XL specification v0.11](https://dpm-alliance.github.io/dpm-xl-docs/)
(2026-09-18; its operators and information model parts and its ANTLR
grammar) and the interval arithmetic rule of the EBA XBRL Filing Rules
(v5.9, rule 2.18). Where dpm-xl reads a rule differently, so that EBA rules
keep their meaning, the
[language reference](../reference/language.md#where-dpm-xl-differs) lists
it with the section concerned.
