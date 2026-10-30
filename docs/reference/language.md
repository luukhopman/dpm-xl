---
description: The complete DPM-XL language as dpm-xl implements it - lexical rules, precedence, and every statement, selection, reference, operator, clause and function with its syntax, types, null and interval behaviour, errors and verified examples.
---

# Language reference

Every construct dpm-xl accepts, with its syntax, meaning, operand and result
types, null and interval behaviour, how it treats keyed records, the errors
it raises, and examples whose results the test suite computes. The
[quick reference](quick-reference.md) lists the same constructs on one
page; the [concept pages](../concepts/index.md) explain the semantics in
depth.

<div class="grid cards" markdown>

-   :lucide-book-open-check:{ .lg .middle } [**How to read this page**](#reading)

    ---

    The syntax notation, the example report, data types, records and errors.

-   :lucide-type:{ .lg .middle } [**Lexical structure**](#lexical)

    ---

    Whitespace, case, names, literals and limits.

-   :lucide-list-ordered:{ .lg .middle } [**Programs and statements**](#statements)

    ---

    Scripts, `:=`, `<-` and `with`.

-   :lucide-table:{ .lg .middle } [**Selections**](#selections)

    ---

    Tables, rows, columns, sheets, `default` and `interval`.

-   :lucide-link:{ .lg .middle } [**References**](#references)

    ---

    Variables, parameters, operations and table groups.

-   :lucide-plus:{ .lg .middle } [**Operators**](#operators)

    ---

    Precedence, arithmetic, comparison, `in`, logic and `if`.

-   :lucide-filter:{ .lg .middle } [**Clauses**](#clauses)

    ---

    `where`, `get`, `sub` and `rename`.

-   :lucide-function-square:{ .lg .middle } [**Functions**](#functions)

    ---

    Numeric, null, text, date, time and set functions, and `filter`.

-   :lucide-braces:{ .lg .middle } [**Sets**](#sets)

    ---

    Set literals.

-   :lucide-sigma:{ .lg .middle } [**Aggregates**](#aggregates)

    ---

    `sum`, `count`, `avg`, `median`, `max` and `min`, with `group by`.

-   :lucide-chart-no-axes-column:{ .lg .middle } [**Analytic functions**](#analytic-functions)

    ---

    Windows with `over`, and `rank`.

-   :lucide-git-compare:{ .lg .middle } [**Where dpm-xl differs**](#where-dpm-xl-differs)

    ---

    Every reading that differs from DPM-XL 0.11, with its section.

-   :lucide-triangle-alert:{ .lg .middle } [**Known limitations**](#limitations)

    ---

    What dpm-xl does not do.

-   :lucide-list:{ .lg .middle } [**Index**](#index)

    ---

    Every keyword, function and symbol, with its entry.

</div>

!!! tip "Look a name up"

    The [index](#index) at the end lists every keyword, function and symbol
    with its entry. To evaluate an expression of your own against the
    example report, run `python examples/language_report.py "…"` in a
    checkout of the repository; see [examples and results](#examples).

## How to read this page {#reading}

### Syntax notation {#notation}

Syntax is written in an EBNF in the style of the XML specification:

- `"with"` is the text itself; keywords match in any case.
- `expression` is another construct, defined on this page.
- `a b` is `a` followed by `b`; `a | b` is `a` or `b`.
- `a?` is an optional `a`; `a*` and `a+` repeat `a` zero or more, and one or
  more times.
- `( … )` groups.

`name` is a [name](#names), `number` a [number literal](#numbers), `code` a
table code, `alnum` a letter or digit, `digit` a digit, and `literal` any
[literal](#literals).

### Examples and results {#examples}

The examples run against a small report, built by
[`examples/language_report.py`](https://github.com/luukhopman/dpm-xl/blob/main/examples/language_report.py):

| Table | Layout | Values |
| --- | --- | --- |
| `T` | rows `0010`–`0030`, columns `0010`, `0020` | c0010: 100, 60, 40; c0020: 5, -5 and nothing in r0030. Reported with `decimals` 0, so ±0.5 with `interval: true`. |
| `U` | rows `0010`–`0030`, column `0010` | 1, 2, 3, exact |
| `S` | row `0010`, column `0010`, sheets `0001`, `0002` | 7, 8 |
| `X` | row `0010`, columns `0010`–`0040` | `"LEI-A"`, `[eba_CU:EUR]`, `#2026-06-30#`, `true` |
| `O` | open, keys `qKEY`, `qDAT`; columns `0010`, `0020` | a, 2026-03-31: 10, EUR; b, 2026-06-30: 20, USD; c, 2026-09-30: 30, JPY |
| `P` | open, key `qKEY`; column `0010` | b: 2; d: 4 |

Report parameters: `refPeriod` = 2026-12-31, `Level` = `"solo"`, `Limit` =
5 and the set `Allowed` = `{[CU:EUR], [CU:USD]}`. Table group `G` holds `T`
and `U`; operation `v1` is `with {tT, c0010}: {r*} * 2`. In the report one
year earlier (`time_shift(…, A, 1)`), T r0010 c0010 is 50.

A result without keys is one value; a keyed result lists its records as
`key=value, …: value`, separated by `;`. Numbers are shown in full, with
`± tolerance` when they carry an [interval](../concepts/intervals.md)
tolerance; text is quoted and items are in brackets. `error: …` is an
[evaluation error](#errors) (in a keyed result, of that record only),
`unsupported: …` a reference the provider cannot resolve, `syntax error: …`
a [syntax error](#errors), and `no records` an empty result. To try an
expression of your own:

```bash
python examples/language_report.py "sum({tT, c0010, r*})"
```

### Data types {#data-types}

| Type | Values | Literal |
| --- | --- | --- |
| number | Decimals with 34 significant digits, and a tolerance from reported precision | [`12`, `4.5%`](#numbers) |
| text | Character strings | [`"text"`](#strings) |
| boolean | `true`, `false` | [`true`](#boolean-and-null) |
| date | Dates and date-times | [`#2026-12-31#`](#dates) |
| item | A member of a category, `category:code` | [`[eba_CU:EUR]`](#items) |
| set | Distinct non-null values | [`{1, 2}`](#set-literals) |
| null | No value | [`null`](#boolean-and-null) |

`integer` exists only as a [parameter type](#typed-parameter): a number
without a fraction. Each entry below states the types it takes; another
type is an evaluation error.

### Records, keys and nulls {#records}

An operand is a set of records: one value, or one value per key such as
`r=0010` or `qKEY=a`. Unless an entry says otherwise:

- Operators and functions of several operands **join** their operands on
  the keys they share, and a key-less operand applies to every record
  ([Operators join on shared keys](../concepts/records-and-keys.md#operators-join-on-shared-keys)).
  Keyed operands must have the same keys, or one operand's keys must
  include every other's; anything else is the error `operands have
  incompatible keys`.
- An operand with a `default` stands in for the records it lacks
  ([Defaults across keys](../concepts/defaults.md)).
- A **null** operand makes the result null
  ([Null logic](../concepts/null.md)). A record whose result is null is not
  evaluated, never a failure.
- An **evaluation error** in one record, such as a division by zero, fails
  only that record; it is the rule's error only if the record reaches the
  result ([Errors stay in their record](../concepts/null.md#errors-stay-in-their-record)).
- A value passed on unchanged, such as an `if` branch, the value `nvl` or
  `filter` keeps, or a record that `where`, `sub` or `rename` keeps, keeps
  its interval tolerance.
- `where`, `sub`, `filter`, `rename`, a `with` context's `where` and a
  `time_shift` of a date key keep their operand's `default`; the results of
  `get`, aggregates and analytic functions have none and join on shared
  keys only
  ([Defaults across keys](../concepts/defaults.md)).

### Errors {#errors}

| Kind | When | Rule status |
| --- | --- | --- |
| Syntax error | The text does not parse: [`DpmXlSyntaxError`][dpmxl.parser.DpmXlSyntaxError], with its position | `error` |
| Evaluation error | A wrong type, an unknown table, key or parameter, incompatible keys, a division by zero | `error` |
| Unsupported | The rule needs a provider method the provider lacks, or calls an unknown function | `unsupported` |

[`diagnose`][dpmxl.diagnostics.diagnose] finds syntax errors, unknown
functions and wrong operand counts without data, and with table layouts
also unknown tables, coordinates and keys and operands of the wrong type.
Messages may be reworded in minor releases; statuses do not change
([Stability](../project/stability.md)).

## Lexical structure {#lexical}

### Whitespace and comments {#whitespace}

Spaces, tabs and line breaks separate tokens and are otherwise ignored
outside text literals. The words of `group by`, `partition by`, `order by`,
`data points` and `current data point` may be separated by any whitespace.

Expressions have no comments. Text [rule files](data-formats.md#rule-files) skip
lines that start with `#`, but that belongs to the file format.

### Case {#case}

Keywords, function names, `true`, `false`, `null` and parameter types match
in any case. The reference prefixes `t g v o p` and the axis letters
`r c s` are lower case, the period codes `A S Q M W D` upper case.
Identifiers ignore case, as DPM-XL 2.4.1 requires: names of temporaries,
[key names](#key-names) in clauses, and the table, table group, operation
and parameter codes that [`MemoryProvider`][dpmxl.provider.MemoryProvider]
looks up, when they match one code only.

| Expression | Result |
| --- | --- |
| `IF TRUE THEN Abs(-1) ENDIF` | `1` |
| `{tt, r0010, c0010}` | `100` |
| `{TT, r0010, c0010}` | `syntax error: unknown selection component 'TT'` |

### Keywords and word boundaries {#word-boundaries}

A word is a letter or `_` followed by letters, digits, `_` and `.`, not
ending in `.`. A word is read whole, so a keyword needs whitespace or
punctuation between it and a neighbouring word: `ornot` is one name, not
`or not`, and `trueendif` is not `true endif`. A word may directly follow a
number (`2endif` reads `2 endif`), and symbols need no spaces
(`1<2and(true)`).

| Expression | Result |
| --- | --- |
| `true ornot false` | `syntax error: expected end of expression, found 'ornot'` |
| `true or(not false)` | `true` |
| `1<2and 2>1` | `true` |

[`diagnose`][dpmxl.diagnostics.diagnose] suggests the missing space:
`did you mean 'or not'?`.

### Names {#names}

```text
name ::= word | "`" character* "`"
```

A name is a [word](#word-boundaries) that is not a reserved word, or any
text without backticks between backticks. Names stand for
[temporaries](#temporary-assignment), [report parameters](#bare-names) and,
inside [clauses](#clauses), [key components](#key-names), and parse to
[`Name`][dpmxl.ast.Name]. Backticks make a reserved word or text with
spaces a name: `` `to` ``, `` `a b` ``.

The keywords `and else endif get group by if in not or over rename sub then
to where with xor` are reserved everywhere. The
[window keywords](#analytic-functions) are reserved only inside `over (…)`,
`default` and `interval` only inside selections, function names only before
`(`, and period codes only where a period is expected; elsewhere they are
ordinary names.

| Expression | Result |
| --- | --- |
| `Level` | `"solo"` |
| `` `Level` `` | `"solo"` |
| `` `a.b` := 4; `a.b` + 1 `` | `5` |
| `range := 2; sum := 3; range * sum` | `6` |
| `to` | `syntax error: unexpected keyword 'to'` |

### Literals {#literals}

```text
literal ::= number | percentage | text | date | "true" | "false" | "null" | item
```

Literals are exact values. They parse to
[`Literal_`][dpmxl.ast.Literal_] with `kind` `number`, `string`, `date`,
`boolean`, `null` or `item` (whose value is an
[`Item`][dpmxl.ast.Item]). [Set literals](#set-literals) are described
with sets.

#### Numbers {#numbers}

```text
number   ::= digit+ ( "." digit+ )? exponent? | "." digit+ exponent?
exponent ::= ( "e" | "E" ) ( "+" | "-" )? digit+
```

A decimal, read exactly: `0.1` is one tenth. A number literal has no sign;
`-3` is [unary minus](#unary) applied to `3`. A point needs a digit after
it, so `1.` is a syntax error. A number whose exponent is outside the
decimal128 range (about ±6144) is the syntax error `number out of range`.

#### Percentages {#percent}

```text
percentage ::= ( number | "(" number ")" ) "%"
```

`%` after a number literal, possibly in parentheses, divides it by 100.
After anything else, such as a name or `(1 + 1)`, it is the syntax error
`'%' must follow a number`, and so is `5%%`.

| Expression | Result |
| --- | --- |
| `12` | `12` |
| `-3.5` | `-3.5` |
| `.5` | `0.5` |
| `1.5e3` | `1500` |
| `0.1 + 0.2 = 0.3` | `true` |
| `4.5%` | `0.045` |
| `2 * 3 %` | `0.06` |
| `1.` | `syntax error: unexpected character '.'` |
| `(1)%` | `0.01` |
| `Limit%` | `syntax error: '%' must follow a number` |

#### Text {#strings}

```text
text ::= '"' character* '"' | "'" character* "'"
```

Text between double or single quotes, possibly empty, possibly spanning
lines. There are no escape sequences: a text cannot contain its own quote,
so write `"it's"` or `'say "yes"'`.

| Expression | Result |
| --- | --- |
| `"text"` | `"text"` |
| `"it's"` | `"it's"` |
| `''` | `""` |

#### Dates {#dates}

```text
date ::= "#" YYYY "-" MM "-" DD ( "T" hh ":" mm ":" ss )? "#"
```

A calendar date, or a date-time with a time part, with every digit written.
`#2026-1-1#` and impossible dates such as `#2026-02-30#` are the syntax
error `invalid date`. A date equals the date-time at its midnight.

| Expression | Result |
| --- | --- |
| `#2026-12-31#` | `2026-12-31` |
| `#2026-12-31T10:30:00#` | `2026-12-31T10:30:00` |
| `#2026-12-31# = #2026-12-31T00:00:00#` | `true` |
| `#2026-02-30#` | `syntax error: invalid date '2026-02-30'` |

#### Booleans and null {#boolean-and-null}

`true` and `false` are the Boolean values and `null` the absent value, in
any case. Null propagates through most operations
([Null logic](../concepts/null.md)).

| Expression | Result |
| --- | --- |
| `TRUE` | `true` |
| `null` | `null` |
| `isnull(null)` | `true` |

#### Items {#items}

```text
item ::= "[" category ":" code "]" | "[" code "]" | "[" "`" code "`" "]"
```

A member of a DPM category, such as a currency or a country. The category
starts with a letter and holds letters, digits, `_` and `-`; the code holds
letters, digits, `_`, `.` and `-` and ends in a letter or digit. Spaces may
pad the inside of the brackets, but not the `:`. The second form, a code
alone such as `[qEBB]` or `[ei86]`, is a property or legacy item code.

Items support only `=` and `!=`. Two items are equal when their codes match
and their categories match, ignoring an `eba_` prefix and a category
missing on either side: `[eba_CU:EUR]`, `[CU:EUR]` and `[EUR]` are equal.
Text compared with an item is read as an item.

A `[` followed by `where`, `get`, `sub` or `rename` opens a
[clause](#clauses) instead.

| Expression | Result |
| --- | --- |
| `[eba_CU:EUR]` | `[CU:EUR]` |
| `[eba_CU:EUR] = [EUR]` | `true` |
| `[CU:EUR] = "eba_CU:EUR"` | `true` |
| `[qEBB]` | `[qEBB]` |
| `[CU:EUR] < [CU:USD]` | `error: items do not support '<'` |
| `[eba_CU : EUR]` | `syntax error: invalid item '[eba_CU : EUR]'` |

### Limits {#limits}

An expression nests at most 50 levels deep (parentheses, signs, `not`,
`if`, calls, `with` bodies and chained clauses count); deeper is the
syntax error `expression too deeply nested`. Arithmetic keeps 34
significant digits.

## Programs and statements {#statements}

```text
program    ::= statement ( ";" statement )* ";"?
statement  ::= name ":=" assigned | assigned
assigned   ::= target "<-" context | context
context    ::= "with" selection ( "[" "where" expression "]" )? ":" context | expression
```

A rule is one expression. A script is statements separated by `;`, run in
order; the last statement gives the result and needs no `;`.
[`parse`][dpmxl.parser.parse] reads one expression (a trailing `;` is
allowed) and [`parse_program`][dpmxl.parser.parse_program] a script, which
[`evaluate_rule`][dpmxl.evaluator.evaluate_rule] also accepts
([Statements and assignments](../concepts/statements.md)). Parses to
[`Program`][dpmxl.ast.Program].

| Expression | Result |
| --- | --- |
| `x := 1; y := x + 1; y * 10;` | `20` |
| `1;;` | `syntax error: unexpected ';' where an operand is expected` |

### Temporary assignment `:=` {#temporary-assignment}

```text
name ":=" assigned
```

Evaluates the right side and binds its records, keys included, to `name`
for the statements that follow; the statement's result is that value. A
temporary hides a report parameter of the same name, and inside a clause a
key component of the same name hides it. Parses to
[`Assignment`][dpmxl.ast.Assignment].

| Expression | Result |
| --- | --- |
| `d := {tT, c0010} - {tT, c0020}; d` | `r=0010: 95; r=0020: 65; r=0030: null` |
| `Level := 1; Level` | `1` |
| `x := 1; X` | `1` |

### Persistent assignment `<-` {#persistent-assignment}

```text
target ::= selection | "{" "v" "_"? code "}"
```

`target <- value` evaluates the value and returns it in
[`RuleResult.assignments`][dpmxl.evaluator.RuleResult] under the target's
normalized text, such as `{tT, r0010, c0010}`. Nothing is written to the
report: later statements still read the reported values. The statement's
result is the value. Outside clauses `<-` is always this assignment, so
write a comparison with a negative operand as `a < -1`. A target that is
not a selection or `{v…}` reference is a syntax error. Parses to
[`PersistentAssignment`][dpmxl.ast.PersistentAssignment].

| Expression | Result |
| --- | --- |
| `{tT, r0010, c0010} <- {tU, r0010, c0010} * 2` | `2` |
| `{tT, r0010, c0010} <- 5; {tT, r0010, c0010}` | `100` |
| `{vTotal} <- sum({tU})` | `6` |

### `with` {#with}

```text
"with" selection ( "[" "where" expression "]" )? ":" context
```

Sets a context for the [selections](#selections) of its body: each takes
the context's table, axes, `default` and `interval` where it does not write
its own. A nested `with` replaces the components it names. `with` may start
a statement, an assignment's value or another `with` body; elsewhere, such
as in parentheses, it is a syntax error.

The optional `where` applies, as a [`where` clause](#where), to each
selection of the body that has the keys it names. Its `and` terms that name
a key the selection lacks (neither one of its keys, the value `f`, nor a
temporary or report parameter) leave that selection alone, so a term on `f`
alone applies to every selection. A `where` or `sub` written on a selection replaces the
context's `where` entirely, whichever keys either names
([Clauses change keys and records](../concepts/records-and-keys.md#clauses-change-keys-and-records)).
Parses to [`With`][dpmxl.ast.With].

| Expression | Result |
| --- | --- |
| `with {tT, c0010}: {r0010} + {r0020}` | `160` |
| `with {tT, c0020, default: 0}: {r0030}` | `0` |
| `with {tT, c0020, default: 0}: {r0030, default: 1}` | `1` |
| `with {tT, interval: true}: {r0010, c0010}` | `100 ± 0.5` |
| `with {tT}: with {c0010}: {r0010}` | `100` |
| `with {tO, c0010}[where qKEY = "a"]: {tO}` | `qKEY=a, qDAT=2026-03-31: 10` |
| `with {tO, c0010}[where qKEY = "a"]: {c0010}[sub qKEY = "b"]` | `qDAT=2026-06-30: 20` |
| `with {tO, c0010}[where qKEY = "a"]: {c0010}[where qDAT > #2026-05-01#]` | `qKEY=b, qDAT=2026-06-30: 20; qKEY=c, qDAT=2026-09-30: 30` |
| `with {tO}[where qKEY = "a"]: {c0010} + {tT, r0010, c0010}` | `qKEY=a, qDAT=2026-03-31: 110` |
| `with {tO}[where qDAT > #2026-05-01#]: {c0010} + {tP, c0010}` | `qKEY=b, qDAT=2026-06-30: 22` |
| `with {tO}[where qKEY = "a" and r = "0010"]: {c0010}` | `qKEY=a, qDAT=2026-03-31: 10` |
| `with {c0010}[where f > 15]: {tO} + {tT, r0010}` | `qKEY=b, qDAT=2026-06-30: 120; qKEY=c, qDAT=2026-09-30: 130` |
| `(with {tT}: {r0010, c0010})` | `syntax error: unexpected keyword 'with'` |

## Selections {#selections}

```text
selection ::= "{" component ( "," component )* "}"
component ::= source | axis | "default" ":" default | "interval" ":" ( "true" | "false" )
source    ::= ( "t" | "g" | "o" ) "_"? code
code      ::= ( letter | digit | "_" | "." | "-" )+ | "`" character* "`"
```

A selection reads cells. Its components are separated by commas, come in
any order and appear at most once each (one source, one selector per axis,
one `default`, one `interval`); a repeated one is a syntax error. The
source is written or comes from an enclosing [`with`](#with); without one
the selection is the evaluation error `selection … has no table`. Braces
that start with a literal, an item or a signed number are a
[set literal](#set-literals) instead, and `{v…}` and `{p…}` braces are
[references](#references). Parses to [`Selection`][dpmxl.ast.Selection]
holding a [`SelectionSpec`][dpmxl.ast.SelectionSpec].

### Table `t` {#table}

`tCode` names a table, such as `tC_01.00`. A `_` after `t` is cosmetic
(`t_C_01.00` is `tC_01.00`), and backticks escape other codes:
`` t`C 01.00` ``. An unknown table is the evaluation error `unknown table
…`. The sources `g` and `o` select from a [table group](#table-group) or
an [operation](#operation).

### Rows, columns and sheets `r c s` {#axes}

```text
axis ::= part | "(" part ( "," part )* ")" | ( "r" | "c" | "s" ) "*"
part ::= ( "r" | "c" | "s" ) alnum+ ( "-" ( "r" | "c" | "s" )? alnum+ )?
```

`r`, `c` and `s` select rows, columns and sheets: one code (`r0010`), an
inclusive range (`r0010-0050`), a list of codes and ranges on one axis in
parentheses (`(c0010, c0030-0050)`), or every coordinate (`r*`). Codes hold
letters and digits; a range may repeat its axis letter (`r0010-r0050`). An
axis that is not written selects every coordinate on it.

Codes match as DPM numbers them: numeric codes as numbers padded to four
digits (`r10` is row `0010`), others ignoring case. A range is numeric when
both ends are numeric and compares text otherwise. A list cannot mix axes
or hold `*`. A coordinate the table lacks selects nothing.

**Keys.** Each axis that selects more than one coordinate is a key, `r`,
`c` or `s`, with the coordinate codes as text; open tables add their key
components, such as `qKEY`
([Selections yield records](../concepts/records-and-keys.md#selections-yield-records)).

| Expression | Result |
| --- | --- |
| `{tT, r0010, c0010}` | `100` |
| `{t_T, r10, c10}` | `100` |
| `{tT, c0010}` | `r=0010: 100; r=0020: 60; r=0030: 40` |
| `{tT, r0010-0020, c0020}` | `r=0010: 5; r=0020: -5` |
| `{tT, (r0010, r0030), c0010}` | `r=0010: 100; r=0030: 40` |
| `{tT, r0010, c*}` | `c=0010: 100; c=0020: 5` |
| `{tS}` | `s=0001: 7; s=0002: 8` |
| `{tS, s0002}` | `8` |
| `sum({tS, r0010, c0010, s*})` | `15` |
| `{tO, c0010}` | `qKEY=a, qDAT=2026-03-31: 10; qKEY=b, qDAT=2026-06-30: 20; qKEY=c, qDAT=2026-09-30: 30` |
| `{tT, r0010, r0020}` | `syntax error: duplicate rows selector` |
| `{tT, (r0010, c0010)}` | `syntax error: axis list mixes axes` |
| `{tZ, r0010}` | `error: unknown table Z` |

### `default` {#default}

```text
default ::= ( "+" | "-" )? number "%"? | "(" default ")" | text | "true" | "false" | "null" | item | date | set
```

The value of a selected cell without a fact; without `default` it is null.
A written `default`, `default: null` included, also stands in for records
that another operand has and the selection lacks
([Defaults across keys](../concepts/defaults.md)).
The value is a literal, not an expression: `default: 1 + 1` is a syntax
error. A set is a default only of a [set parameter](#typed-parameter); on a
selection it is an evaluation error.

| Expression | Result |
| --- | --- |
| `{tT, r*, c0020}` | `r=0010: 5; r=0020: -5; r=0030: null` |
| `{tT, r*, c0020, default: 0}` | `r=0010: 5; r=0020: -5; r=0030: 0` |
| `{tT, r0030, c0020, default: (-1)}` | `-1` |
| `{tO, c0010} + {tP, c0010}` | `qKEY=b, qDAT=2026-06-30: 22` |
| `{tO, c0010} + {tP, c0010, default: 0}` | `qKEY=a, qDAT=2026-03-31: 10; qKEY=b, qDAT=2026-06-30: 22; qKEY=c, qDAT=2026-09-30: 30` |
| `{tO, c0010, default: 0} [where qKEY = "z"] + {tT, r0010, c0010}` | `100` |
| `sum({tO, c0010, default: 0} [where qKEY = "z"]) + {tT, r0010, c0010}` | `100` |
| `{tT, c0010, default: {1}}` | `error: a set default applies only to set parameters` |

### `interval` {#interval}

`interval: true` keeps each reported number's tolerance (from its XBRL
`decimals`), so that arithmetic and comparisons use
[interval arithmetic](../concepts/intervals.md); `interval: false`, or no
`interval`, makes the numbers exact. The value is `true` or `false`.

| Expression | Result |
| --- | --- |
| `{tT, r0010, c0010, interval: true}` | `100 ± 0.5` |
| `{tT, r0010, c0010, interval: true} = 100.4` | `true` |
| `{tT, r0010, c0010} = 100.4` | `false` |
| `{tT, r0010, c0010, interval: 1}` | `syntax error: interval must be true or false` |

## References {#references}

```text
reference ::= "{" "v" "_"? code "}"
            | "{" "p" "_"? code "," type ( "," "default" ":" default )? "}"
```

Braces also read report-level data and other rules' results; each kind of
reference goes to a provider method
([Parameters, operations and table groups](../concepts/references.md)).

### Variable `{v…}` {#variable}

`{vX}`, also written `{v_X}` (the `_` is cosmetic, §3.1.1), is variable
`X` of the report. When `X` is a table or template code, by its shape
(such as `C_01.00`) or because the provider knows it, the variable is that
template's filing indicator: `true` when it was reported, else `false` (the
provider's `table_reported`), usually in a
[precondition](../concepts/results.md#preconditions). Otherwise it is
report parameter `X` as the provider gives it, of any type, and null when
it is missing. Backticks escape other names: ``{v`a b`}``. Parses to
[`Variable`][dpmxl.ast.Variable]; [`read_variable`][dpmxl.provider.read_variable]
decides.

<a id="filing-indicator"></a><a id="report-parameter"></a>

| Expression | Result |
| --- | --- |
| `{v_T}` | `true` |
| `{vT}` | `true` |
| `{v_C_01.00}` | `false` |
| `{v_T} and not {v_C_01.00}` | `true` |
| `{vrefPeriod}` | `2026-12-31` |
| `{v_Level}` | `"solo"` |
| `{vMissing}` | `null` |

#### Bare names {#bare-names}

A [name](#names) reads a [temporary](#temporary-assignment) or, failing
that, the report parameter of that name; inside a clause a key component
comes first ([Key names](#key-names)). An unknown name is the evaluation
error `unknown key component or parameter`.

The contextual components of DPM-XL 2.2.3.1.4 and 2.2.3.3.1, listed in
[`CONTEXTUAL_COMPONENTS`][dpmxl.grammar.CONTEXTUAL_COMPONENTS] (`refPeriod`,
`entityID`, `baseCurrency`, `decimalsInteger`, `decimalsMonetary`,
`decimalsPercentage`, `decimalsDecimal`), are the report parameters of
those names, of the component's type, in any case; a missing one is null.
`baseCurrency` is an item of the DPM's currency domain, as in `[eba_CU:EUR]`
(DPM-XL §2.2.3.3.1); an ISO 4217 code such as `iso4217:EUR` or `EUR` reads
as `eba_CU:EUR`.

| Expression | Result |
| --- | --- |
| `refPeriod` | `2026-12-31` |
| `baseCurrency` | `null` |
| `{tT, c0010}[where entityID = "LEI"]` | `no records` |
| `missing` | `error: unknown key component or parameter 'missing'` |

### Typed parameter `{p_…}` {#typed-parameter}

```text
type ::= "number" | "integer" | "string" | "date" | "boolean" | "item"
       | "set-number" | "set-integer" | "set-string" | "set-date" | "set-boolean" | "set-item"
```

`{p_Name, type}` reads report parameter `Name` and checks its type; a value
of another type is the evaluation error `parameter … is not …`. Text is
read as a date or an item for those types, and `integer` takes whole
numbers. A missing parameter takes the `default`, or is null. A `set-…`
type takes a set of that member type, and its default may be a
[set literal](#set-literals). The `_` after `p` is cosmetic; the type comes
before the default. Parses to [`TypedParameter`][dpmxl.ast.TypedParameter].

| Expression | Result |
| --- | --- |
| `{p_refPeriod, date}` | `2026-12-31` |
| `{p_Limit, number} + 1` | `6` |
| `{pLimit, integer}` | `5` |
| `{p_Level, string}` | `"solo"` |
| `{p_Allowed, set-item}` | `{[CU:EUR], [CU:USD]}` |
| `{p_Missing, boolean, default: true}` | `true` |
| `{p_Missing, item, default: [CU:EUR]}` | `[CU:EUR]` |
| `{p_Missing, set-number, default: {1, 2}}` | `{1, 2}` |
| `{p_Missing, set-integer}` | `null` |
| `{p_Missing, set-string, default: {"a"}}` | `{"a"}` |
| `{p_Missing, set-date, default: {#2026-01-01#}}` | `{2026-01-01}` |
| `{p_Missing, set-boolean, default: {true}}` | `{true}` |
| `{p_Limit, date}` | `error: parameter Limit is not a date` |
| `{p_Limit}` | `syntax error: expected ',', found '}'` |

### Operation `{o_…}` {#operation}

```text
"{" "o" "_"? code ( "," ( axis | "default" ":" default | "interval" ":" ( "true" | "false" ) ) )* "}"
```

Reads the result of temporary `Code` of the same script, assigned with
[`:=`](#temporary-assignment) and matched ignoring case, or else evaluates operation
`Code`, the expression the provider's optional `operation(code)` method
returns, on its own: the referring rule's `with` context, temporaries and
assignments do not reach it. On its result, axes
keep the matching `r`, `c` and `s` records, `default` fills nulls and
`interval: false` makes numbers exact. An operation that refers to itself
is an evaluation error; without the provider method the rule is
unsupported. Parses to a `Selection` with `spec.operation`.

| Expression | Result |
| --- | --- |
| `{o_v1}` | `r=0010: 200; r=0020: 120; r=0030: 80` |
| `{o_v1, r0010}` | `200` |
| `op1 := {tT, c0010} * 10; {oOp1, r0010}` | `1000` |
| `{o_X}` | `unsupported: operation X needs a provider that resolves operations` |

### Table group `{g_…}` {#table-group}

`{g_Group, …}` selects from every table of a group, which the provider's
optional `table_group(code)` method lists. With several tables the records
gain the key `t`, the table code, and the tables must have the same keys
for the selection. Without the provider method the rule is unsupported.
Parses to a `Selection` with `spec.table_group`.

| Expression | Result |
| --- | --- |
| `{g_G, r0010, c0010}` | `t=T: 100; t=U: 1` |
| `{g_G, r0010}` | `error: the tables of group G have different keys` |
| `{g_X, r0010}` | `unsupported: table group X needs a provider that resolves table groups` |

## Operators {#operators}

### Precedence and associativity {#precedence}

From loosest to tightest binding:

| Level | Operators | Associativity | Entry |
| --- | --- | --- | --- |
| 1 | `;`, `:=`, `<-`, `with … :` | statements only | [Statements](#statements) |
| 2 | `or`, `xor` | left | [Logical operators](#logical) |
| 3 | `and` | left | [Logical operators](#logical) |
| 4 | `not` | prefix; nests (`not not x`) | [`not`](#not) |
| 5 | `=`, `!=`, `<>`, `<`, `<=`, `>`, `>=`, `in`, `not in` | none: one per operand | [Comparison](#comparison), [`in`](#in) |
| 6 | `&` | left | [Concatenation](#concatenation) |
| 7 | `+`, `-` | left | [Arithmetic](#arithmetic) |
| 8 | `*`, `/` | left | [Arithmetic](#arithmetic) |
| 9 | unary `+`, `-` | prefix; nests (`- -x`) | [Unary plus and minus](#unary) |
| 10 | `%` after a number literal, clauses `[…]` | postfix; chain left to right | [Percentages](#percent), [Clauses](#clauses) |
| 11 | literals, selections, references, names, calls, `if … endif`, `( … )` | | |

Without parentheses `not` cannot be an operand of a comparison, arithmetic
or a sign: `1 = not true` and `- not x` are syntax errors. Comparisons do
not chain: `a < b < c` is a syntax error.

| Expression | Result |
| --- | --- |
| `1 + 2 * 3` | `7` |
| `(1 + 2) * 3` | `9` |
| `10 - 4 - 3` | `3` |
| `12 / 4 / 3` | `1` |
| `-2 * -3` | `6` |
| `"a" & "b" = "ab"` | `true` |
| `1 + 1 in {2}` | `true` |
| `not 1 = 2` | `true` |
| `not true and false` | `false` |
| `true or false and false` | `true` |
| `true xor true or true` | `true` |
| `1 < 2 < 3` | `syntax error: expected end of expression, found '<'` |
| `1 = not true` | `syntax error: unexpected keyword 'not'` |

### Arithmetic `+ - * /` {#arithmetic}

```text
additive       ::= multiplicative ( ( "+" | "-" ) multiplicative )*
multiplicative ::= unary ( ( "*" | "/" ) unary )*
```

Addition, subtraction, multiplication and division of numbers.

- **Types:** numbers in, a number out; exact decimal arithmetic with 34
  significant digits.
- **Null:** null if either operand is null.
- **Intervals:** tolerances propagate
  ([Arithmetic](../concepts/intervals.md#arithmetic)).
- **Keys:** the operands [join](#records).
- **Errors:** `+ needs numbers, found …`; `division by zero` when the
  divisor's value is zero, `division by an interval that contains zero`
  when its tolerance reaches zero.
- **Node:** [`Binary`][dpmxl.ast.Binary].

| Expression | Result |
| --- | --- |
| `{tT, r0020, c0010} + {tT, r0030, c0010}` | `100` |
| `{tT, c0010} - {tT, c0020}` | `r=0010: 95; r=0020: 65; r=0030: null` |
| `{tT, c0010, interval: true} * 2` | `r=0010: 200 ± 1; r=0020: 120 ± 1; r=0030: 80 ± 1` |
| `1 / 3` | `0.3333333333333333333333333333` |
| `1 + null` | `null` |
| `1 / 0` | `error: division by zero` |
| `1 / ({tT, r0010, c0020, interval: true} - 4.8)` | `error: division by an interval that contains zero` |
| `{tT, c0010} / {tT, c0020}` | `r=0010: 20; r=0020: -12; r=0030: null` |
| `1 + "a"` | `error: + needs numbers, found string` |
| `{tT, r0010} + {tT, c0010}` | `error: operands have incompatible keys (r) and (c)` |

### Unary plus and minus {#unary}

```text
unary ::= ( "+" | "-" ) unary | postfix
```

`-x` negates a number and `+x` returns it, for each record, keeping its
tolerance. Null stays null; another type is the error `unary - needs
numbers`. Parses to [`Unary`][dpmxl.ast.Unary].

| Expression | Result |
| --- | --- |
| `-{tT, r0010, c*}` | `c=0010: -100; c=0020: -5` |
| `- -1` | `1` |
| `-"a"` | `error: unary - needs numbers, found string` |

### Concatenation `&` {#concatenation}

```text
concatenation ::= additive ( "&" additive )*
```

Joins two texts; null if either is null. An item joins as its text, as
under [`len`](#len); another type is the error `& needs text, found …`. Binds looser than arithmetic and tighter than
comparisons. Parses to [`Binary`][dpmxl.ast.Binary].

| Expression | Result |
| --- | --- |
| `"LEI" & "-" & "A"` | `"LEI-A"` |
| `{tX, c0010} & "/2026"` | `"LEI-A/2026"` |
| `"a" & null` | `null` |
| `{tX, c0020} & "/2026"` | `"eba_CU:EUR/2026"` |
| `"a" & 1` | `error: & needs text, found number` |

### Comparison `= != <> < <= > >=` {#comparison}

```text
comparison ::= concatenation ( ( "=" | "!=" | "<>" | "<" | "<=" | ">" | ">=" ) concatenation )?
```

Compares two values and yields a Boolean. `<>` is `!=`; the node's `op` is
`!=`.

| Operands | Comparison |
| --- | --- |
| number, number | By value; with tolerances as intervals ([Comparisons](../concepts/intervals.md#comparisons)) |
| text, text | By character code |
| date, date | In date order; a date is the date-time at its midnight |
| boolean, boolean | `false` before `true`; the text `"true"`, `"false"`, `"1"` or `"0"` counts as a Boolean |
| item, item | `=` and `!=` only, as under [Items](#items); text counts as an item |
| date, text | As text |

- **Null:** null if either operand is null.
- **Keys:** the operands [join](#records).
Two sets are equal under `=` when each member of one is in the other.

- **Errors:** `cannot compare number with string using '='` and the like
  for other pairs, a set with anything but a set included; `items do not
  support '<'`.
- **Node:** [`Binary`][dpmxl.ast.Binary].

| Expression | Result |
| --- | --- |
| `{tT, r0010, c0010} > {tT, r0020, c0010}` | `true` |
| `{tT, c0010} >= 50` | `r=0010: true; r=0020: true; r=0030: false` |
| `"a" < "b"` | `true` |
| `#2026-01-01# < #2026-01-02#` | `true` |
| `true > false` | `true` |
| `{tX, c0040} = "true"` | `true` |
| `{tX, c0020} = [CU:EUR]` | `true` |
| `1 != 2` | `true` |
| `1 <> 2` | `true` |
| `null = null` | `null` |
| `1 = "1"` | `error: cannot compare number with string using '='` |
| `{1, 2} = {2, 1}` | `true` |
| `symdiff({1, 2}, {1, 2}) = {}` | `true` |
| `{1} = 1` | `error: cannot compare set with number using '='` |
| `{1} < {2}` | `error: cannot compare set with set using '<'` |

### `in`, `not in` {#in}

```text
membership ::= concatenation "not"? "in" concatenation
```

`x in s` is `true` when `x` equals (`=`) a member of the set `s`, so `x`'s
interval tolerance applies; `x not in s` is `not (x in s)`. `s` is a
[set literal](#set-literals), a set parameter, a
[set function](#set-functions), or any other operand, which stands for the
set of its non-null values ([Sets](../concepts/sets.md)).

- **Null:** null when `x` is null, or when `s` is a single null, such as a
  missing set parameter.
- **Keys:** applies to each record of `x`; the set is not joined.
- **Errors:** incompatible types, as for `=`.
- **Node:** [`In`][dpmxl.ast.In]; `not in` is `Unary("not", In(…))`.

| Expression | Result |
| --- | --- |
| `{tU, c0010} in {1, 3}` | `r=0010: true; r=0020: false; r=0030: true` |
| `{tO, c0020} in {p_Allowed, set-item}` | `qKEY=a, qDAT=2026-03-31: true; qKEY=b, qDAT=2026-06-30: true; qKEY=c, qDAT=2026-09-30: false` |
| `{tO, c0020} not in {[CU:JPY]}` | `qKEY=a, qDAT=2026-03-31: true; qKEY=b, qDAT=2026-06-30: true; qKEY=c, qDAT=2026-09-30: false` |
| `60 in {tT, c0010}` | `true` |
| `{tT, r0010, c0010, interval: true} in {100.4}` | `true` |
| `null in {1}` | `null` |
| `1 in {p_Missing, set-number}` | `null` |
| `1 in {}` | `false` |

### `not` {#not}

```text
negation ::= "not" negation | comparison
```

Negates a Boolean, for each record; null stays null. Another type is the
error `not needs a boolean`. `not` binds looser than comparisons: `not a =
b` is `not (a = b)`. Parses to [`Unary`][dpmxl.ast.Unary].

| Expression | Result |
| --- | --- |
| `not {tT, c0010} > 50` | `r=0010: false; r=0020: false; r=0030: true` |
| `not null` | `null` |
| `not 1` | `error: not needs a boolean, found number` |

### Logical operators `and or xor` {#logical}

```text
disjunction ::= conjunction ( ( "or" | "xor" ) conjunction )*
conjunction ::= negation ( "and" negation )*
```

Conjunction, disjunction and exclusive or with three-valued (Kleene) logic:
`false and null` is `false` and `true or null` is `true`; otherwise a null
operand makes the result null, and `xor` with a null is always null. Both
operands are always evaluated.

- **Keys:** the operands [join](#records).
- **Errors:** `and needs booleans, found …`.
- **Node:** [`Binary`][dpmxl.ast.Binary].

| Expression | Result |
| --- | --- |
| `{tT, c0010} > 50 and {tT, c0020} > 0` | `r=0010: true; r=0020: false; r=0030: false` |
| `{v_T} or {v_C_01.00}` | `true` |
| `true xor false` | `true` |
| `null and false` | `false` |
| `null or false` | `null` |
| `true xor null` | `null` |
| `1 and true` | `error: and needs booleans, found number` |

### `if` {#if}

```text
"if" expression "then" expression ( "else" expression )? "endif"
```

Chooses a branch by a Boolean condition; a null condition takes the `else`
branch. Without `else`, the records whose condition is false or null are
left out, so a guarded check is not evaluated where its guard does not hold
([Conditionals](../concepts/null.md#conditionals)). `if … endif` is an
operand: it nests and combines with operators.

- **Keys:** a key-less condition picks a whole branch. A keyed condition
  gives one record per condition record, from the matching branch record;
  branch keys the condition lacks widen it. Defaults on the condition or a
  branch fill in missing keys
  ([Defaults across keys](../concepts/defaults.md)).
- **Errors:** `if needs a boolean condition, found …`, in the record
  concerned.
- **Node:** [`If`][dpmxl.ast.If].

| Expression | Result |
| --- | --- |
| `if {v_T} then {tT, r0010, c0010} > 0 endif` | `true` |
| `if {tT, c0010} > 50 then {tT, c0010} else 0 endif` | `r=0010: 100; r=0020: 60; r=0030: 0` |
| `if {tT, c0010} > 50 then {tT, c0020} > 0 endif` | `r=0010: true; r=0020: false` |
| `if {tT, c0010} > 50 then {tT, c0020} endif` | `r=0010: 5; r=0020: -5` |
| `if false then true endif` | `null` |
| `if null then 1 else 2 endif` | `2` |
| `if false then 1 else if false then 2 else 3 endif endif + 1` | `4` |
| `if 1 then 2 endif` | `error: if needs a boolean condition, found number` |

## Clauses {#clauses}

```text
postfix ::= primary ( "%" | clause )*
clause  ::= "[" "where" expression "]"
          | "[" "get" name "]"
          | "[" "sub" name "=" additive ( "," name "=" additive )* "]"
          | "[" "rename" name "to" name ( "," name "to" name )* "]"
```

A clause follows any operand in brackets, usually a selection or a name.
Clauses chain left to right. Inside a clause `<-` reads `< -`, so
`[where qX<-1]` compares with -1.

### Key names {#key-names}

Names in clauses, `group by` and `over` resolve against the operand's keys:
exactly, else ignoring case and the DPM 2.0 `q` prefix, so `KEY`, `key` and
`qkey` all find `qKEY`. In `where`, `f` is the record's value. A name that
matches no key, or several, is read as a temporary or report parameter in
`where` and `get`, and is an error in
`sub`, `rename`, `group by` and `over`. The keys `r`, `c` and `s` hold
coordinate codes as text (`r = "0010"`, not `r = 10`); open keys hold the
values the provider reports, such as text, dates and items.

### `where` {#where}

Keeps the records that satisfy a condition. The condition is evaluated for
each record, with the record's key components as names and its value as
`f`, and must yield one Boolean; records where it is false or null are
dropped. The result keeps the operand's `default`, which stands in for the
keys other operands bring ([Defaults across keys](../concepts/defaults.md)).
Parses to [`Where`][dpmxl.ast.Where].

| Expression | Result |
| --- | --- |
| `{tT, c0010}[where r = "0010"]` | `r=0010: 100` |
| `{tT, c0010}[where r in {"0010", "0020"}]` | `r=0010: 100; r=0020: 60` |
| `{tO, c0010}[where qDAT > #2026-05-01#]` | `qKEY=b, qDAT=2026-06-30: 20; qKEY=c, qDAT=2026-09-30: 30` |
| `{tO, c0010}[where KEY <> "a" and qDAT < #2026-09-01#]` | `qKEY=b, qDAT=2026-06-30: 20` |
| `{tO, c0010}[where qDAT<-1]` | `error: cannot compare date with number using '<'` |
| `{tT, c0010}[where r = 10]` | `error: cannot compare string with number using '='` |
| `{tT, c0020}[where f != 0]` | `r=0010: 5; r=0020: -5` |
| `{tT, c0020}[where not isnull(f)]` | `r=0010: 5; r=0020: -5` |
| `{tT, r0010, c0010}[where f > 500]` | `null` |
| `{tO, c0010}[where {tO, c0010} > 10]` | `error: expected a single value, found records keyed by qKEY, qDAT` |

### `get` {#get}

Replaces each record's value by the value of one of its key components,
keeping the keys; records whose value is null are dropped, and the result
has no `default`. A name that is not a key reads the report parameter of
that name for every record. Parses to [`Get`][dpmxl.ast.Get].

| Expression | Result |
| --- | --- |
| `{tO, c0010}[get qDAT]` | `qKEY=a, qDAT=2026-03-31: 2026-03-31; qKEY=b, qDAT=2026-06-30: 2026-06-30; qKEY=c, qDAT=2026-09-30: 2026-09-30` |
| `{tT, c0020}[get r]` | `r=0010: "0010"; r=0020: "0020"` |
| `{tT, c0010}[get foo]` | `error: unknown key component or parameter 'foo'` |

### `sub` {#sub}

Keeps the records whose key component equals a value, compared as with
`=`, and removes that key. The value is an additive expression (a literal,
a parameter, an item or arithmetic; parenthesize anything else) with one
value. The result keeps the operand's `default`, as for [`where`](#where).
Several pairs, separated by commas, fix one key after another, as a chain of
`sub` clauses does (§11.4.1). Parses to [`Sub`][dpmxl.ast.Sub], one node per
pair, the last pair outermost.

| Expression | Result |
| --- | --- |
| `{tO, c0010}[sub qKEY = "a"]` | `qDAT=2026-03-31: 10` |
| `{tO, c0010}[sub qKEY = "a"][sub qDAT = #2026-03-31#]` | `10` |
| `{tO, c0010}[sub qKEY = "a", qDAT = #2026-03-31#]` | `10` |
| `{tT, c0010}[sub r = "0010"]` | `100` |
| `{tO, c0010}[sub qKEY = "z"]` | `no records` |
| `{tO, c0010, default: 0}[sub qDAT = #2026-09-30#] + {tP, c0010}` | `qKEY=b: 2; qKEY=d: 4` |
| `{tO, c0010}[sub foo = 1]` | `error: unknown key component 'foo'` |

### `rename` {#rename}

Renames key components, so that operands with different key names join.
The old names resolve as [key names](#key-names); the new ones are taken as
written. Records, values and the `default` are unchanged. A new name that
is already a key component (also ignoring case and the `q` prefix), or two
pairs with the same new name, is the error `rename: key component …
already exists`; pairs apply in order, so keys cannot be swapped in one
clause. Parses to [`Rename`][dpmxl.ast.Rename].

| Expression | Result |
| --- | --- |
| `{tO, c0010}[rename qKEY to K, qDAT to D]` | `K=a, D=2026-03-31: 10; K=b, D=2026-06-30: 20; K=c, D=2026-09-30: 30` |
| `{tP, c0010}[rename qKEY to K] + {tO, c0010}[sub qDAT = #2026-06-30#][rename qKEY to K]` | `K=b: 22` |
| `{tO, c0010}[rename foo to K]` | `error: unknown key component 'foo'` |
| `{tO, c0010}[rename qKEY to DAT]` | `error: rename: key component qDAT already exists` |
| `{tO, c0010}[rename qKEY to X, qDAT to X]` | `error: rename: key component X already exists` |

## Functions {#functions}

```text
call ::= name "(" ( expression ( "," expression )* )? ")"
```

A word followed by `(` is a call; function names match in any case. Calls
parse to [`Call`][dpmxl.ast.Call] with the canonical name
([`canonical_function`][dpmxl.grammar.canonical_function]), except
[analytic calls](#analytic-functions). Unless an entry says otherwise, a
function applies to each record, [joins](#records) keyed operands, and is
null when an operand is null.

- **Operand counts** are checked against
  [`SIGNATURES`][dpmxl.grammar.SIGNATURES]: a wrong count is the error
  `abs takes 1 operand, not 2`, and `group by` in a function that does not
  aggregate is `group by is not allowed in abs`.
- **Unknown functions** parse, so that rules with newer functions can be
  read, and evaluate as unsupported: `unknown function 'foo'`.

| Expression | Result |
| --- | --- |
| `ABS(-1)` | `1` |
| `abs(1, 2)` | `error: abs takes 1 operand, not 2` |
| `abs(1 group by r)` | `error: group by is not allowed in abs` |
| `foo(1)` | `unsupported: unknown function 'foo'` |

### Numeric functions {#numeric-functions}

#### `abs` {#abs}

`abs(x)`: the absolute value of a number, keeping its tolerance. Errors:
`abs needs numbers, found …`.

| Expression | Result |
| --- | --- |
| `abs(-3)` | `3` |
| `abs({tT, r*, c0020})` | `r=0010: 5; r=0020: 5; r=0030: null` |
| `abs({tT, r0020, c0020, interval: true})` | `5 ± 0.5` |
| `abs("x")` | `error: abs needs numbers, found string` |

#### `exp`, `ln`, `sqrt` {#exp}

`exp(x)`, `ln(x)` and `sqrt(x)`: the exponential, natural logarithm and
square root of a number. They are computed in binary floating point, to
about 16 significant digits, and the result is exact, without tolerance. A
result out of range, such as `exp(1000)`, is null. Errors: `exp needs
numbers, found …`; `ln needs a number greater than 0, found 0` and `sqrt
needs a number at least 0, found -1`, which fail only their record.

| Expression | Result |
| --- | --- |
| `exp(0)` | `1` |
| `exp(1)` | `2.718281828459045` |
| `ln(1)` | `0` |
| `sqrt(16)` | `4` |
| `sqrt(2)` | `1.4142135623730951` |
| `exp(1000)` | `null` |
| `ln(0)` | `error: ln needs a number greater than 0, found 0` |
| `sqrt(-1)` | `error: sqrt needs a number at least 0, found -1` |
| `sqrt("a")` | `error: sqrt needs numbers, found string` |

#### `power` {#power}

`power(base, exponent)`: `base` raised to `exponent`, in binary floating
point like [`exp`](#exp); null when undefined or out of range.

| Expression | Result |
| --- | --- |
| `power(2, 10)` | `1024` |
| `power(2, 0.5)` | `1.4142135623730951` |
| `power(0, -1)` | `null` |
| `power(-8, 1 / 3)` | `null` |

#### `log` {#log}

`log(x, base)`: the logarithm of `x` to `base`, in binary floating point
like [`ln`](#exp). Errors: `log needs a number greater than 0, found …`
and `log needs a base greater than 1, found …`, which fail only their
record.

| Expression | Result |
| --- | --- |
| `log(8, 2)` | `3` |
| `log(100, 10)` | `2` |
| `log(8, 1)` | `error: log needs a base greater than 1, found 1` |
| `log(-8, 2)` | `error: log needs a number greater than 0, found -8` |

#### `max`, `min` {#max}

With two or more operands, `max(a, b, …)` and `min(a, b, …)` pick the
largest or smallest value per record, keeping its tolerance, the largest
among equal values; null if any operand is null. Numbers compare by value; dates, text and items, which
cannot be mixed with numbers, by their text (ISO dates in date order).
Booleans are an error. With one operand they are
[aggregates](#aggregate-max).

| Expression | Result |
| --- | --- |
| `max(1, 5, 3)` | `5` |
| `min({tT, c0010}, {tT, c0020})` | `r=0010: 5; r=0020: -5; r=0030: null` |
| `max({tT, c0010}, 50)` | `r=0010: 100; r=0020: 60; r=0030: 50` |
| `max(100, {tT, r0010, c0010, interval: true})` | `100 ± 0.5` |
| `max(#2026-01-01#, #2026-02-01#)` | `2026-02-01` |
| `max(1, null)` | `null` |
| `max(1, "a")` | `error: max cannot compare numbers with dates, text or items` |

### Null functions {#null-functions}

#### `isnull` {#isnull}

`isnull(x)`: `true` where `x` is null, else `false`; never null. It applies
to each record, so it finds the unreported cells of a selection.

| Expression | Result |
| --- | --- |
| `isnull({tT, c0020})` | `r=0010: false; r=0020: false; r=0030: true` |
| `isnull(null)` | `true` |
| `isnull(0)` | `false` |

#### `nvl` {#nvl}

`nvl(x, replacement)`: `x`, or `replacement` where `x` is null. The
operands [join](#records), so `nvl` replaces null values but adds no
records; a `default` on `x` covers the records `x` lacks.

| Expression | Result |
| --- | --- |
| `nvl({tT, c0020}, 0)` | `r=0010: 5; r=0020: -5; r=0030: 0` |
| `nvl(null, "none")` | `"none"` |
| `nvl({tO, c0010}, {tP, c0010})` | `qKEY=b, qDAT=2026-06-30: 20` |

### Text functions {#text-functions}

#### `len`, `length` {#len}

`len(x)`, also spelled `length(x)`: the number of characters of a text.
Other values count the characters of their text form; a number counts as
written, without an exponent, a Boolean as `true` or `false`, and an
item as its qualified name `eba_category:code` (`[CU:EUR]` and
`[eba_CU:EUR]` both count 10), or its code alone when it has no category.

| Expression | Result |
| --- | --- |
| `len("abc")` | `3` |
| `length({tX, c0010})` | `5` |
| `len({tX, c0020})` | `10` |
| `len({tX, c0040})` | `4` |
| `len(12.50)` | `5` |
| `len(null)` | `null` |

#### `substr` {#substr}

`substr(text)`, `substr(text, start)` and `substr(text, start, length)`:
part of a text, or of an item's text as under [`len`](#len). `start`
counts from 1 (default 1) and `length`, by default the rest, is at least 0;
both are whole numbers. Past the end the result is
`""`. Errors: `substr needs text, found …`, `substr start must be at least
1`, `substr length must not be negative`, `substr needs whole numbers`.

| Expression | Result |
| --- | --- |
| `substr("abcdef", 2, 3)` | `"bcd"` |
| `substr("abcdef", 3)` | `"cdef"` |
| `substr("abcdef", 10)` | `""` |
| `substr({tX, c0020}, 8)` | `"EUR"` |
| `substr("abcdef", 0)` | `error: substr start must be at least 1` |
| `substr(123, 1)` | `error: substr needs text, found number` |

#### `match` {#match}

`match(x, pattern)`: `true` when the whole text of `x` matches the regular
expression `pattern`, in Python
[`re`](https://docs.python.org/3/library/re.html) syntax, as if anchored at
both ends. Numbers and items match their text form, as under
[`len`](#len). Errors: `match needs a text pattern`,
`invalid match pattern: …`.

| Expression | Result |
| --- | --- |
| `match({tX, c0010}, "LEI-[A-Z]")` | `true` |
| `match({tX, c0020}, "eba_CU:[A-Z]{3}")` | `true` |
| `match("xLEI-A", "LEI-[A-Z]")` | `false` |
| `match(2026, "[0-9]{4}")` | `true` |
| `match("a", "(")` | `error: invalid match pattern: missing ), unterminated subpattern at position 0` |

### Date functions {#date-functions}

#### `year`, `semester`, `quarter`, `month`, `week`, `day` {#date-parts}

The part of a date or date-time, as a number: `year`, `semester` (1–2),
`quarter` (1–4), `month` (1–12), `week` (the ISO 8601 week, 1–53) and
`day` of the month. Errors: `year needs a date, found …`; text is not read
as a date.

| Expression | Result |
| --- | --- |
| `year(#2026-05-31#)` | `2026` |
| `semester(#2026-07-01#)` | `2` |
| `quarter(#2026-05-31#)` | `2` |
| `month({tX, c0030})` | `6` |
| `week(#2026-01-01#)` | `1` |
| `day(#2026-05-31T10:00:00#)` | `31` |
| `year({tO, c0010}[get qDAT])` | `qKEY=a, qDAT=2026-03-31: 2026; qKEY=b, qDAT=2026-06-30: 2026; qKEY=c, qDAT=2026-09-30: 2026` |
| `year("2026-05-31")` | `error: year needs a date, found string` |

#### `date` {#date}

`date(year, month, day)`: the date of three whole numbers; null when they
form no date, such as a day the month lacks. Errors: `date needs whole
numbers`.

| Expression | Result |
| --- | --- |
| `date(2026, 2, 28)` | `2026-02-28` |
| `date(2026, 12, 31) = #2026-12-31#` | `true` |
| `date(2026, 2, 30)` | `null` |
| `date(2026, 13, 1)` | `null` |

### Time functions {#time-functions}

#### `time_shift` {#time_shift}

```text
"time_shift" "(" expression "," period "," expression ( "," name )? ")"
period ::= "A" | "S" | "Q" | "M" | "W" | "D"
```

`time_shift(x, period, count, key)` presents `x` as it was `count` periods
earlier (later when negative): years, semesters, quarters, months, weeks or
days. `period` is an upper-case code and `count` a whole number.

- When `key` is a date key component of `x`, its values move `count`
  periods later within the report, so that each record joins with those of
  the later date. Months move by calendar months, and a month's last day
  stays the last day.
- Otherwise, without `key` or with a name such as `refPeriod` that is not a
  key of `x`, `x` is evaluated on the report `count` periods earlier, from
  the provider's optional `earlier_report(period, count)` method; without
  that report the rule is unsupported.

Errors: `time_shift needs a period of A, S, Q, M, W or D`, `time_shift
needs a key name as its fourth operand`, `time_shift needs dates in key …`,
and `time_shift moves several … dates to …` when two records would merge.
See [Time](../concepts/time.md#time_shift) and
[Compare with earlier reports](../guides/time-shift.md).

| Expression | Result |
| --- | --- |
| `time_shift({tT, r0010, c0010}, A, 1)` | `50` |
| `{tT, r0010, c0010} - time_shift({tT, r0010, c0010}, A, 1, refPeriod)` | `50` |
| `time_shift({tO, c0010}, Q, 1, qDAT)` | `qKEY=a, qDAT=2026-06-30: 10; qKEY=b, qDAT=2026-09-30: 20; qKEY=c, qDAT=2026-12-31: 30` |
| `time_shift({tO, c0010}, S, 1, qDAT)` | `qKEY=a, qDAT=2026-09-30: 10; qKEY=b, qDAT=2026-12-31: 20; qKEY=c, qDAT=2027-03-31: 30` |
| `time_shift({tO, c0010}, W, 1, qDAT)` | `qKEY=a, qDAT=2026-04-07: 10; qKEY=b, qDAT=2026-07-07: 20; qKEY=c, qDAT=2026-10-07: 30` |
| `time_shift({tO, c0010}, D, -1, qDAT)` | `qKEY=a, qDAT=2026-03-30: 10; qKEY=b, qDAT=2026-06-29: 20; qKEY=c, qDAT=2026-09-29: 30` |
| `time_shift({tO, c0010}, M, -1, qDAT)` | `qKEY=a, qDAT=2026-02-28: 10; qKEY=b, qDAT=2026-05-31: 20; qKEY=c, qDAT=2026-08-31: 30` |
| `time_shift({tT, r0010, c0010}, Q, 1)` | `unsupported: time_shift needs the report 1 quarter(s) earlier (reference date 2026-09-30), which the provider does not have` |
| `time_shift({tT, r0010, c0010}, a, 1)` | `error: time_shift needs a period of A, S, Q, M, W or D` |
| `time_shift({tO, c0010}, A, 1, qKEY)` | `error: time_shift needs dates in key qKEY, found string` |

#### `annualise` {#annualise}

`annualise(x, fiscalYearEnd, key)` scales a year-to-date amount to a year:
`x · 12 / months`, where `months` counts the months after the fiscal year's
last month (`fiscalYearEnd`, 1–12) up to and including the month of the
date in `key`. `key` is a date key component of `x`, else a date report
parameter. The tolerance scales with the amount. Errors: `annualise needs
a fiscal year end month of 1 to 12`, `annualise needs a date key or report
parameter …`, `annualise needs a key name as its third operand`.

| Expression | Result |
| --- | --- |
| `annualise({tO, c0010}, 12, qDAT)` | `qKEY=a, qDAT=2026-03-31: 40; qKEY=b, qDAT=2026-06-30: 40; qKEY=c, qDAT=2026-09-30: 40` |
| `annualise(30, 6, refPeriod)` | `60` |
| `annualise(30, 12, Level)` | `error: annualise needs a date key or report parameter 'Level'` |

### Set functions {#set-functions}

Each operand of a set function is a set, or any other operand, which stands
for the set of its non-null values. A single null operand, such as a
missing set parameter, makes the result null; `set_of` gives `{}` instead.
The result has no keys, and its members keep their first-seen order.

#### `set_of` {#set_of}

`set_of(x)`: the set of the non-null values of `x`.

| Expression | Result |
| --- | --- |
| `set_of({tU})` | `{1, 2, 3}` |
| `set_of({tT, c0020})` | `{5, -5}` |
| `set_of(null)` | `{}` |

#### `union`, `intersect` {#union}

`union(a, b, …)` has the members of any operand; `intersect(a, b, …)` the
members of the first operand that every other operand has. Both take two or
more operands.

| Expression | Result |
| --- | --- |
| `union({1}, {2}, {1, 3})` | `{1, 2, 3}` |
| `intersect({1, 2}, {2, 3}, {2})` | `{2}` |
| `union({tU}, {tP})` | `{1, 2, 3, 4}` |
| `union({1}, {p_Missing, set-number})` | `null` |

#### `setdiff`, `symdiff` {#setdiff}

`setdiff(a, b)` has the members of `a` that `b` lacks; `symdiff(a, b)` the
members of exactly one of the two.

| Expression | Result |
| --- | --- |
| `setdiff({1, 2}, {2, 3})` | `{1}` |
| `symdiff({1, 2}, {2, 3})` | `{1, 3}` |
| `setdiff({1, 2, 3, 4}, {tU})` | `{4}` |

### `filter` {#filter}

`filter(data, condition)` keeps the records of `data` whose `condition`
record is `true`; a false, null or non-Boolean condition drops the record.
The two operands [join](#records), so the condition is usually a comparison
on the same selection. Unlike [`where`](#where) it tests values, not keys.
The result keeps `data`'s `default`, which stands in for the keys other
operands bring.

| Expression | Result |
| --- | --- |
| `filter({tT, c0010}, {tT, c0010} > 50)` | `r=0010: 100; r=0020: 60` |
| `filter({tO, c0010}, {tO, c0020} = [CU:USD])` | `qKEY=b, qDAT=2026-06-30: 20` |
| `count(filter({tT, c0020}, {tT, c0020} > 0))` | `1` |

## Sets {#sets}

### Set literals {#set-literals}

```text
set ::= "{" "}" | "{" expression ( "," expression )* "}"
```

Braces whose first member is a literal, an item, a signed number or a
parenthesized number are a set; other braces are a
[selection](#selections). Each member is an expression with one value;
nulls and duplicates are dropped, and a set cannot contain a set. Sets
cannot be compared with `=` or the other comparisons and cannot be a rule's
result ([Sets](../concepts/sets.md)). Parses to
[`SetLiteral`][dpmxl.ast.SetLiteral].

| Expression | Result |
| --- | --- |
| `{1, 2, 2}` | `{1, 2}` |
| `{(-5), 3}` | `{-5, 3}` |
| `{-5, 1 + 1}` | `{-5, 2}` |
| `{[eba_CU:EUR], [eba_CU:USD]}` | `{[CU:EUR], [CU:USD]}` |
| `{"a", #2026-01-01#, true, null}` | `{"a", 2026-01-01, true}` |
| `{}` | `{}` |

Sets are tested with [`in`](#in), built with the
[set functions](#set-functions) and read from
[set parameters](#typed-parameter).

## Aggregates {#aggregates}

```text
aggregate ::= ( "sum" | "count" | "avg" | "median" | "max" | "min" | "max_aggr" | "min_aggr" )
              "(" expression ( "group" "by" name ( "," name )* )? ")"
```

An aggregate reduces an operand's records to one value, or to one value per
combination of the `group by` keys ([Key names](#key-names)), skipping null
values. Over no records an aggregate is null, except `count`, which is 0;
so is a group whose values are all null. The result has the `group by`
keys, or none, and no `default`: a key without records is no group
([Aggregates](../concepts/analytics.md#aggregates)).

- **Errors:** `group by 'qX' is not a key of the operand (r, c)`; `sum
  needs numbers, found …`; `max with group by takes 1 operand, not 2`.
- **Node:** [`Call`][dpmxl.ast.Call] with `group_by`; with `over`, an
  [analytic function](#analytic-functions).

| Expression | Result |
| --- | --- |
| `sum({tT} group by c)` | `c=0010: 200; c=0020: 0` |
| `count({tT} group by r, c)` | `r=0010, c=0010: 1; r=0010, c=0020: 1; r=0020, c=0010: 1; r=0020, c=0020: 1; r=0030, c=0010: 1; r=0030, c=0020: 0` |
| `sum({tO, c0010} group by KEY)` | `qKEY=a: 10; qKEY=b: 20; qKEY=c: 30` |
| `sum({tT} group by qX)` | `error: group by 'qX' is not a key of the operand (r, c)` |

### `sum` {#sum}

The sum of the numbers; their tolerances add up.

| Expression | Result |
| --- | --- |
| `sum({tT, c0010})` | `200` |
| `sum({tT, c0010, interval: true})` | `200 ± 1.5` |
| `sum({tT, r0030, c0020})` | `null` |
| `sum({tX, c0010})` | `error: sum needs numbers, found string` |

### `count` {#count}

The number of non-null values, of any type. Of a set, the number of its
members; a set takes no `group by`.

| Expression | Result |
| --- | --- |
| `count({tT})` | `5` |
| `count({tT, r0030, c0020})` | `0` |
| `count({tO} group by c)` | `c=0010: 3; c=0020: 3` |
| `count({1, 2, 3, 3, 2})` | `3` |
| `count({})` | `0` |
| `count(union({1, 2}, {2, 3}))` | `3` |

### `avg` {#avg}

The mean of the numbers, with the sum's tolerance divided by the count.

| Expression | Result |
| --- | --- |
| `avg({tU})` | `2` |
| `avg({tT, c0010, interval: true})` | `66.66666666666666666666666667 ± 0.5` |

### `median` {#median}

The middle number with its tolerance, the largest among equal values, or
the mean of the two middle numbers and of their tolerances.

| Expression | Result |
| --- | --- |
| `median({tU})` | `2` |
| `median({tT, c0020})` | `0` |
| `median({tT, c0010, interval: true})` | `60 ± 0.5` |
| `median({tT, c0020, interval: true})` | `0 ± 0.5` |

### `max`, `min`, `max_aggr`, `min_aggr` {#aggregate-max}

With one operand, `max` and `min` are aggregates, also spelled `max_aggr`
and `min_aggr`, which take exactly one operand. They pick the largest or
smallest value, keeping its tolerance, the largest among equal values.
Besides numbers they order dates,
text and items by their text (ISO dates in date order, items by category
and code), as presence checks expect; Booleans, and numbers mixed with
other values, are errors. With several operands `max` and `min` are the
[scalar functions](#max).

| Expression | Result |
| --- | --- |
| `max({tU})` | `3` |
| `min_aggr({tT, c0020})` | `-5` |
| `max_aggr({tO, c0020})` | `[CU:USD]` |
| `max({tO, c0010} group by qKEY)` | `qKEY=a: 10; qKEY=b: 20; qKEY=c: 30` |
| `max({tX})` | `error: max needs numbers, dates, text or items` |
| `max_aggr(1, 2)` | `syntax error: max_aggr takes one operand` |

## Analytic functions {#analytic-functions}

```text
analytic  ::= function "(" expression "over" "(" partition? order? window? ")" ")"
function  ::= "rank" | "sum" | "count" | "avg" | "median" | "max" | "min" | "max_aggr" | "min_aggr"
partition ::= "partition" "by" name ( "," name )*
order     ::= "order" "by" name ( "asc" | "desc" )? ( "," name ( "asc" | "desc" )? )*
window    ::= ( "data" "points" | "range" ) "between" bound "and" bound
bound     ::= "unbounded" ( "preceding" | "following" )
            | "current" "data" "point"
            | digit+ period? ( "preceding" | "following" )
```

An analytic function keeps its operand's records: each gets the aggregate
of the records in its window, or its rank, within its partition.
`partition by` and `order by` name keys of the operand
([Key names](#key-names)) or `f`, its value; without `partition by` the
whole operand is one partition. Null order values come last. Without a window the window is the whole partition, even with
`order by`. `data points`
windows count records; `range` windows with an offset need a single number
or date order key, and `3 M preceding` is three calendar months earlier.
The result has no `default`. The window keywords are reserved only inside
`over (…)`
([Partitions, order and windows](../concepts/analytics.md#partitions-order-and-windows)).

- **Errors:** the syntax errors `rank needs an order by clause`, `abs takes
  no over clause` and `a window offset is a whole number`; `sum over 'qX',
  which is not a key of the operand (r, c)`; `a range window offset needs a
  number or date order key`; `a range window with offsets needs one order
  key`.
- **Node:** [`Analytic`][dpmxl.ast.Analytic] with a
  [`Window`][dpmxl.ast.Window].

| Expression | Result |
| --- | --- |
| `sum({tU} over ())` | `r=0010: 6; r=0020: 6; r=0030: 6` |
| `sum({tU} over (order by r))` | `r=0010: 6; r=0020: 6; r=0030: 6` |
| `sum({tU} over (order by r data points between unbounded preceding and current data point))` | `r=0010: 1; r=0020: 3; r=0030: 6` |
| `sum({tT} over (partition by c))` | `r=0010, c=0010: 200; r=0020, c=0010: 200; r=0030, c=0010: 200; r=0010, c=0020: 0; r=0020, c=0020: 0; r=0030, c=0020: 0` |
| `avg({tU} over (order by r data points between 1 preceding and current data point))` | `r=0010: 1; r=0020: 1.5; r=0030: 2.5` |
| `sum({tU} over (order by r data points between current data point and unbounded following))` | `r=0010: 6; r=0020: 5; r=0030: 3` |
| `min_aggr({tU} over (order by r desc data points between unbounded preceding and 1 following))` | `r=0030: 2; r=0020: 1; r=0010: 1` |
| `sum({tO, c0010} over (order by qDAT range between 3 M preceding and current data point))` | `qKEY=a, qDAT=2026-03-31: 10; qKEY=b, qDAT=2026-06-30: 30; qKEY=c, qDAT=2026-09-30: 50` |
| `count({tO, c0010} over (order by qDAT asc range between current data point and 1 Q following))` | `qKEY=a, qDAT=2026-03-31: 2; qKEY=b, qDAT=2026-06-30: 2; qKEY=c, qDAT=2026-09-30: 1` |
| `sum({tU} over (order by r range between 1 preceding and current data point))` | `error: a range window offset needs a number or date order key` |
| `abs({tU} over ())` | `syntax error: abs takes no over clause` |

### `rank` {#rank}

`rank(x over (partition by … order by …))`: the position of each record in
its partition by the order keys, from 1; ties share the lowest rank and
leave gaps (1, 1, 3). `order by f` ranks by value. `rank` needs `over`
with `order by`; a window is ignored.

| Expression | Result |
| --- | --- |
| `rank({tU} over (order by r desc))` | `r=0030: 1; r=0020: 2; r=0010: 3` |
| `rank({tT} over (partition by c order by r desc))` | `r=0030, c=0010: 1; r=0020, c=0010: 2; r=0010, c=0010: 3; r=0030, c=0020: 1; r=0020, c=0020: 2; r=0010, c=0020: 3` |
| `filter({tU}, rank({tU} over (order by r)) <= 2)` | `r=0010: 1; r=0020: 2` |
| `rank({tT, c0020} over (order by f desc))` | `r=0010: 1; r=0020: 2; r=0030: 3` |
| `rank({tU})` | `syntax error: rank needs an over clause` |
| `rank({tU} over (partition by r))` | `syntax error: rank needs an order by clause` |

## Where dpm-xl differs {#where-dpm-xl-differs}

The [DPM-XL specification][dpm-xl-spec], version 0.11, is the reference
([standards and conformance](standards.md#dpm-xl)); its operators part is
cited as §, its information model part as IM §. Some readings differ from
it on purpose, so that EBA rules keep their meaning:

- `not` binds looser than comparisons and `in`: `not a = b` is
  `not (a = b)` (§1.1 puts `not` above `*`). `in` shares the level of the
  comparisons (§1.1 puts it below them).
- Chained comparisons such as `a < b < c` or `a in b in c`, `- not x`, and a
  selection that repeats an axis, `default` or `interval` are syntax errors.
- Outside clauses `<-` is the persistent assignment, so compare with a
  negated operand as `a < -b`.
- A variable `{vX}` is a template's filing indicator when `X` is a table
  or template code, by its shape or because the provider knows it, and
  otherwise a report parameter; the specification leaves the variables of a
  report to the information model (§3.1.1).
- A [`default`](#default) stands for the records an operand lacks
  where another operand has them, as an XBRL fallback value does; the
  specification joins inner and generates implicit nulls only for keys the
  operand's own table reports (§2.2.3.3, IM §4.2.1)
  ([Defaults across keys](../concepts/defaults.md)).
  An operand a `where` filters to nothing likewise takes its default at the
  other operands' records, and an aggregate of it aggregates the default,
  where a strict reading of IM §4.2.1 gives no record.
- A `with` context's `where` leaves alone a selection that lacks a key it
  names; the specification makes that a semantic error (§3.2.5, example
  10).
- Ranges of codes with only digits are numeric and pad to four digits
  (`r10` is `0010`); the specification orders them as text (§3.1.6). A
  selection without an axis selects every code on it, where the
  specification needs `*` for an axis that is not open (§3.1.6).
- Clauses accept the keys `r`, `c` and `s` (§11 and §11.1.5 forbid them),
  and there are no attribute components other than the
  [contextual ones](#bare-names), which `rename` does not reject as a new
  name (§2.2.3.3, §11.2.5).
- Text compared with an item is read as an item, ignoring an `eba_` prefix
  or a missing category, and other values are not cast to text, so `1 =
  "1"` is an error (IM §2.3.2, §5.1.3).
- `exp`, `ln`, `sqrt`, `power` and `log` drop an operand's tolerance
  instead of rejecting it (§4.2.4.5 to §4.3.7.5); `exp` and `power` out of
  range are null, which the specification leaves open.
- An interval's tolerance comes from each fact's `decimals`, not from the
  instance's `decimals…` parameters (IM §2.2.3.3.1).
- A set may mix types (§13.1.5), a window clause of `rank` is ignored
  (§7.8.5), and the bounds of a window are not checked (§7.1.8.6): `0
  preceding` is the current record and bounds in the wrong order give
  null.
- The structure constraints of `if` (§8.1.5) are not enforced: a key-less
  condition may choose between branches with different keys.
- `time_shift` of a date value, rather than of a record set, is not
  supported (§10.1.2).
- `match` tests the whole text (`re.fullmatch`); the specification follows
  Python without saying whether the pattern is anchored (§5.9).

<!-- docs: invalid -->
```dpm-xl
{tT, r0010} < {tT, r0020} < {tT, r0030}
1 in {1} in {true}
- not true
{tT, r0010, r0020}
```

### Syntax beyond the official grammar {#beyond-the-grammar}

In the other direction dpm-xl accepts syntax that the ANTLR grammar
published with v0.11 rejects. Where the grammar contradicts the
specification's own text or the EBA's rules, dpm-xl follows them and
[`diagnose`][dpmxl.diagnostics.diagnose] reports nothing:

| Accepted | Evidence |
| --- | --- |
| `default:null`, `interval:false` without a space after the colon | 185 of the 14,174 EBA expressions write them so; the grammar's lexer reads `default:null` as an item code, although it otherwise ignores whitespace (§3.1.1 defines `default` and `interval` as arguments) |
| `null` as an operand, as in `max(1, 3, null)` | Examples such as `3 = null` (§5.2), `max(1, 3, null)` (§4.3.5) and `len(null)` (§9.1); the grammar takes `null` only after `default:` |
| `abs(-1)` | The example of §4.2.3; the grammar reads `(-1)` as one literal, so the call lacks its parentheses |
| A last statement without `;` | The example of §3.1.6.1; the grammar needs `;` after every statement of a script |

The others have no such basis: no EBA expression uses them, and other
engines may reject a rule that does. dpm-xl evaluates them, and `diagnose`
reports each as a `non-portable` warning with the portable spelling where
there is one, so that `dpm-xl check --strict` fails on them:

| Accepted | Portable spelling |
| --- | --- |
| `.5`, `1e5` | `0.5`, `100000` |
| `max(x)`, `min(x)`, also with `group by` | `max_aggr(x)`, `min_aggr(x)` |
| `substr(x, 1 + 1)`: positions that are not integer literals (the grammar's reading of §9.3, whose text allows any integer) | `substr(x, 2)` |
| `default: -1`, `{1.5, -3}` | `default: (-1)`, `{1.5, (-3)}`; a negative decimal cannot be written |
| Keywords, functions and literals not in lower case, such as `AND`, `TRUE` | `and`, `true` |
| `<>` | `!=` |
| `length` | `len` |
| `with` inside a `with` body | One `with` |

`union` and `intersect` of one operand parse, but are an error, as in the
specification. Not flagged: codes without leading zeros (`r310` is row
`0310`), ranges that repeat the axis letter (`r0440-r0480`), key names
without the `q` prefix or in another case and item codes without a category
(`[ei86]`), which the grammar accepts; and [bare names](#bare-names), sets
that mix types and `max` and `min` over dates, text and items, which
concern meaning rather than spelling.

Every distinct EBA rule and precondition expression of DPM releases 3.4–4.4
parses, except two source expressions with typos (`trueendif`, `ornot`),
which are reported as syntax errors.

## Known limitations {#limitations}

- No comments, and no escape sequences in [text](#strings).
- `with` only starts a statement, an assignment's value or another `with`
  body ([`with`](#with)).
- `exp`, `ln`, `sqrt`, `power` and `log` compute in binary floating point
  and drop the tolerance ([`exp`](#exp)).
- A coordinate a table lacks selects nothing rather than raising an error;
  [`diagnose`][dpmxl.diagnostics.diagnose] with table layouts warns about
  it.
- `time_shift` across reports, `{o_…}` and `{g_…}` need optional provider
  methods; without them a rule is unsupported
  ([Connect your data](../guides/provider.md)).
- The [columnar evaluator](../guides/columnar.md) implements a subset and
  raises `ColumnarUnsupported` for the rest, such as scripts, `time_shift`,
  analytic functions and most sets.
- Expressions nest at most 50 deep, and numbers stay within the decimal128
  range ([Limits](#limits)).

## Index {#index}

Every word and symbol of [`dpmxl.grammar`][dpmxl.grammar], with its entry.
The test suite checks that this index and the grammar module agree.

| Name | Kind | Entry |
| --- | --- | --- |
| `and` | keyword | [Logical operators](#logical) |
| `else` | keyword | [`if`](#if) |
| `endif` | keyword | [`if`](#if) |
| `get` | keyword | [`get`](#get) |
| `group by` | keyword | [Aggregates](#aggregates) |
| `if` | keyword | [`if`](#if) |
| `in` | keyword | [`in`, `not in`](#in) |
| `not` | keyword | [`not`](#not) |
| `or` | keyword | [Logical operators](#logical) |
| `over` | keyword | [Analytic functions](#analytic-functions) |
| `rename` | keyword | [`rename`](#rename) |
| `sub` | keyword | [`sub`](#sub) |
| `then` | keyword | [`if`](#if) |
| `to` | keyword | [`rename`](#rename) |
| `where` | keyword | [`where`](#where) |
| `with` | keyword | [`with`](#with) |
| `xor` | keyword | [Logical operators](#logical) |
| `asc` | window keyword | [Analytic functions](#analytic-functions) |
| `between` | window keyword | [Analytic functions](#analytic-functions) |
| `current data point` | window keyword | [Analytic functions](#analytic-functions) |
| `data points` | window keyword | [Analytic functions](#analytic-functions) |
| `desc` | window keyword | [Analytic functions](#analytic-functions) |
| `following` | window keyword | [Analytic functions](#analytic-functions) |
| `order by` | window keyword | [Analytic functions](#analytic-functions) |
| `partition by` | window keyword | [Analytic functions](#analytic-functions) |
| `preceding` | window keyword | [Analytic functions](#analytic-functions) |
| `range` | window keyword | [Analytic functions](#analytic-functions) |
| `unbounded` | window keyword | [Analytic functions](#analytic-functions) |
| `default` | selection option | [`default`](#default) |
| `interval` | selection option | [`interval`](#interval) |
| `false` | literal | [Booleans and null](#boolean-and-null) |
| `null` | literal | [Booleans and null](#boolean-and-null) |
| `true` | literal | [Booleans and null](#boolean-and-null) |
| `boolean` | parameter type | [Typed parameter](#typed-parameter) |
| `date` | parameter type | [Typed parameter](#typed-parameter) |
| `integer` | parameter type | [Typed parameter](#typed-parameter) |
| `item` | parameter type | [Typed parameter](#typed-parameter) |
| `number` | parameter type | [Typed parameter](#typed-parameter) |
| `set-boolean` | parameter type | [Typed parameter](#typed-parameter) |
| `set-date` | parameter type | [Typed parameter](#typed-parameter) |
| `set-integer` | parameter type | [Typed parameter](#typed-parameter) |
| `set-item` | parameter type | [Typed parameter](#typed-parameter) |
| `set-number` | parameter type | [Typed parameter](#typed-parameter) |
| `set-string` | parameter type | [Typed parameter](#typed-parameter) |
| `string` | parameter type | [Typed parameter](#typed-parameter) |
| `A` | period | [`time_shift`](#time_shift) |
| `S` | period | [`time_shift`](#time_shift) |
| `Q` | period | [`time_shift`](#time_shift) |
| `M` | period | [`time_shift`](#time_shift) |
| `W` | period | [`time_shift`](#time_shift) |
| `D` | period | [`time_shift`](#time_shift) |
| `abs` | function | [`abs`](#abs) |
| `annualise` | function | [`annualise`](#annualise) |
| `avg` | function | [`avg`](#avg) |
| `count` | function | [`count`](#count) |
| `date` | function | [`date`](#date) |
| `day` | function | [Date parts](#date-parts) |
| `exp` | function | [`exp`, `ln`, `sqrt`](#exp) |
| `filter` | function | [`filter`](#filter) |
| `intersect` | function | [`union`, `intersect`](#union) |
| `isnull` | function | [`isnull`](#isnull) |
| `len` | function | [`len`, `length`](#len) |
| `length` | function | [`len`, `length`](#len) |
| `ln` | function | [`exp`, `ln`, `sqrt`](#exp) |
| `log` | function | [`log`](#log) |
| `match` | function | [`match`](#match) |
| `max` | function | [`max`, `min`](#max) |
| `max_aggr` | function | [`max_aggr`, `min_aggr`](#aggregate-max) |
| `median` | function | [`median`](#median) |
| `min` | function | [`max`, `min`](#max) |
| `min_aggr` | function | [`max_aggr`, `min_aggr`](#aggregate-max) |
| `month` | function | [Date parts](#date-parts) |
| `nvl` | function | [`nvl`](#nvl) |
| `power` | function | [`power`](#power) |
| `quarter` | function | [Date parts](#date-parts) |
| `rank` | function | [`rank`](#rank) |
| `semester` | function | [Date parts](#date-parts) |
| `set_of` | function | [`set_of`](#set_of) |
| `setdiff` | function | [`setdiff`, `symdiff`](#setdiff) |
| `sqrt` | function | [`exp`, `ln`, `sqrt`](#exp) |
| `substr` | function | [`substr`](#substr) |
| `sum` | function | [`sum`](#sum) |
| `symdiff` | function | [`setdiff`, `symdiff`](#setdiff) |
| `time_shift` | function | [`time_shift`](#time_shift) |
| `union` | function | [`union`, `intersect`](#union) |
| `week` | function | [Date parts](#date-parts) |
| `year` | function | [Date parts](#date-parts) |
| `+` | operator | [Arithmetic, unary plus](#arithmetic) |
| `-` | operator | [Arithmetic, unary minus](#arithmetic) |
| `*` | operator | [Arithmetic](#arithmetic) |
| `/` | operator | [Arithmetic](#arithmetic) |
| `&` | operator | [Concatenation](#concatenation) |
| `=` | operator | [Comparison](#comparison) |
| `!=` | operator | [Comparison](#comparison) |
| `<>` | operator | [Comparison](#comparison) |
| `<` | operator | [Comparison](#comparison) |
| `<=` | operator | [Comparison](#comparison) |
| `>` | operator | [Comparison](#comparison) |
| `>=` | operator | [Comparison](#comparison) |
| `%` | operator | [Percentages](#percent) |
| `:=` | operator | [Temporary assignment](#temporary-assignment) |
| `<-` | operator | [Persistent assignment](#persistent-assignment) |
| `(` | punctuation | [Precedence (grouping), calls, axis lists](#precedence) |
| `)` | punctuation | [Precedence (grouping), calls, axis lists](#precedence) |
| `[` | punctuation | [Clauses, items](#clauses) |
| `]` | punctuation | [Clauses, items](#clauses) |
| `{` | punctuation | [Selections, references, sets](#selections) |
| `}` | punctuation | [Selections, references, sets](#selections) |
| `,` | punctuation | [Selections, calls, sets](#selections) |
| `:` | punctuation | [`with`, selection options](#with) |
| `;` | punctuation | [Programs and statements](#statements) |
| `t` | reference prefix | [Table](#table) |
| `g` | reference prefix | [Table group](#table-group) |
| `v` | reference prefix | [Variable](#variable) |
| `o` | reference prefix | [Operation](#operation) |
| `p` | reference prefix | [Typed parameter](#typed-parameter) |
| `r` | axis | [Rows, columns and sheets](#axes) |
| `c` | axis | [Rows, columns and sheets](#axes) |
| `s` | axis | [Rows, columns and sheets](#axes) |
