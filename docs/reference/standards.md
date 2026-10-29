---
description: The standards dpm-xl implements (DPM-XL 0.11, rule 2.18 of the EBA Filing Rules 5.9, and VTL 2.1 where DPM-XL builds on it), with links to the primary sources, what is implemented and not, the deviations, and how conformance is tested.
icon: lucide/badge-check
---

# Standards and conformance

This page lists the published standards dpm-xl implements, the version of
each, how far it goes, and how that is tested. Other pages link here rather
than repeat the versions. The details are in the
[language reference](language.md), including
[where dpm-xl differs](language.md#where-dpm-xl-differs) from the
specification and its [known limitations](language.md#limitations).

| Standard | Version | Publisher | dpm-xl |
| --- | --- | --- | --- |
| [DPM-XL][dpm-xl-spec] | 0.11, 18 September 2026 | EBA and EIOPA | Parses the language and evaluates it, with a listed set of deviations. |
| [EBA Filing Rules][eba-filing-rules], rule 2.18 | 5.9, 26 June 2026 | EBA | Reads reported precision as intervals, for rules with `interval: true`. |
| [VTL][vtl-21] | 2.1, July 2024 | SDMX | Only where DPM-XL builds on it: operator precedence, `if`, `match`. VTL itself is not parsed. |

The report formats, xBRL-CSV and XBRL-XML, and the other EBA filing rules
are read and checked by [dpm-xbrl], which `dpm-xl check-report` uses; see
[report formats](#report-formats) below.

dpm-xl is an independent implementation. It has not been certified by any
standards body, and the EBA does not endorse it.

## DPM-XL

The [DPM-XL specification][dpm-xl-spec], version 0.11
([release][dpm-xl-spec-release]), defines the language in three parts: the
information model (cited as IM §), the operators (cited as §), and an ANTLR
grammar. dpm-xl follows it as the reference for syntax and semantics.

Implemented
:   Every construct of the grammar: statements and scripts, selections,
    references, operators, clauses, functions, sets, aggregates and
    analytic functions, each in the [language reference](language.md)
    with its syntax, types, null and interval behaviour and errors. The
    semantics are explained in the [concepts](../concepts/index.md).

Deviations
:   Each reading that differs from the specification, with the section
    concerned, is listed once, in
    [where dpm-xl differs](language.md#where-dpm-xl-differs). Most keep the
    meaning of EBA rules where the specification reads them otherwise;
    the same section lists what dpm-xl accepts beyond the grammar.

Not implemented
:   DPM-ML, the representation of operations in the DPM database (IM §5):
    dpm-xl takes expressions as text, and a
    [module file](module-file.md) or a [provider](../guides/provider.md)
    supplies the tables, rules and data. Other limits are under
    [known limitations](language.md#limitations).

Exact behaviour
:   [Language reference](language.md), [quick reference](quick-reference.md).

## EBA Filing Rules

Rule 2.18 of the [EBA Filing Rules][eba-filing-rules], version 5.9
(EBA/XBRL/2026/06, 26 June 2026), says what the `decimals` of a reported
number mean: the value is accurate to within half a unit of the last
decimal place given, and EBA validation rules compare such values with
interval arithmetic.

Implemented
:   A reported number becomes a [`Number`][dpmxl.values.Number] with the
    tolerance `0.5 · 10^-decimals`; selections with `interval: true` carry
    it through arithmetic, comparisons and functions, with the formulas of
    DPM-XL §4 and §7. See [interval arithmetic](../concepts/intervals.md).

Decimals
:   Each fact's own `decimals`. Through the `xbrl` extra, an xBRL-CSV
    fact without them takes the report's `decimals…` parameter for its data
    type, as the filing rules set out for xBRL-CSV; see
    [`ReportProvider`][dpmxl.xbrl.ReportProvider].

Deviations
:   The DPM-XL information model sets the precision per instance (IM
    §2.2.3.3.1); dpm-xl takes it per fact, which gives the same result
    when every fact of a type has the same decimals. The tolerance of a
    quotient is the largest deviation of the four endpoint quotients, not
    the formula of §4.3.4.4, which fails for a negative divisor; see
    [quotients with a negative divisor](../concepts/intervals.md#quotients-with-a-negative-divisor).

The other filing rules are about how a report file is written; dpm-xbrl
checks them.

## VTL

DPM-XL is based on the [VTL 2.1][vtl-21] reference manual of SDMX: its
operator precedence mirrors VTL's (§1.1). dpm-xl does not parse VTL. Where
DPM-XL 0.11 points to VTL or leaves a question open, dpm-xl reads it as
follows:

Precedence
:   `in` and `not in` share the level of the comparisons, as in VTL's
    evaluation order (level VII); DPM-XL §1.1 binds `in` more loosely.
    `not` binds more loosely than comparisons, where both bind it more
    tightly than arithmetic; see [precedence](language.md#precedence).

`if`
:   A null condition takes the `else` branch, as in DPM-XL §8.1.4 and in
    VTL, whose `if` returns the `else` operand unless the condition is
    true; see [`if`](language.md#if).

`match`
:   VTL's `match_characters` takes a POSIX extended regular expression and
    lets implementations differ. DPM-XL §5.9 follows Python, and dpm-xl
    uses Python's `re`, anchored at both ends; see [`match`](language.md#match).

## Report formats

dpm-xl reads no report files. With the `xbrl` extra,
[`dpmxl.xbrl`](api/xbrl.md) and `dpm-xl check-report` read reports with
dpm-xbrl, whose
[standards page](https://luukhopman.github.io/dpm-xbrl/reference/standards/)
covers xBRL-CSV 1.0, XBRL 2.1, Report Packages 1.0 and the EBA filing
rules it checks.

## How conformance is tested

- **Specification.** [`tests/test_spec_semantics.py`](https://github.com/luukhopman/dpm-xl/blob/main/tests/test_spec_semantics.py)
  asserts the behaviour DPM-XL 0.11 requires, by section, and
  [`tests/test_grammar_coverage.py`](https://github.com/luukhopman/dpm-xl/blob/main/tests/test_grammar_coverage.py)
  parses, and where it yields a value evaluates, examples of every
  alternative of the grammar.
- **EBA expressions.** [`tests/test_corpus.py`](https://github.com/luukhopman/dpm-xl/blob/main/tests/test_corpus.py)
  parses all 14,174 distinct rule and precondition expressions of the EBA's
  DPM releases 3.4 to 4.4
  ([source](https://github.com/luukhopman/dpm-xl/blob/main/tests/data/eba_corpus.md)).
  All parse but two with typos in the EBA source, which must fail with
  the suggested fix. The corpus is parsed, not evaluated: it holds no
  report data.
- **Language reference.** Every row of an `Expression | Result` table in
  the [language reference](language.md) is evaluated against
  [`examples/language_report.py`](https://github.com/luukhopman/dpm-xl/blob/main/examples/language_report.py)
  and must show the actual result, and its [index](language.md#index)
  must list exactly the names in [`dpmxl.grammar`](api/grammar.md).
- **Documentation examples.** Every Python and command-line example on
  these pages runs in the test suite and must print what the page shows.
- **Two evaluators.** The columnar evaluator must agree with the reference
  evaluator on hand-written and on seeded random rules
  ([`tests/test_columnar.py`](https://github.com/luukhopman/dpm-xl/blob/main/tests/test_columnar.py)).
- **Not run.** The specification's repository holds no conformance tests,
  and results are not compared with another implementation's.
