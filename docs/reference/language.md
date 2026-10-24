---
description: Every DPM-XL construct dpm-xl parses, with an example and the expression-tree node it becomes, plus where parsing differs from the grammar.
---

# Language

Every construct of the DPM-XL grammar, with an example and the
[`dpmxl.ast`](api/ast.md) node it parses to. Every example on this page
parses (the test suite checks them). The semantics are explained under
[Concepts](../concepts/index.md).

Keywords match in any case (`IF`, `If`, `if`). Whitespace and line breaks
are insignificant outside literals.

## Rules and statements

| Construct | Example | Node |
| --- | --- | --- |
| Expression | `{tC_01.00, r0010, c0010} >= 0` | any |
| Statements separated by `;` (the last needs no `;`) | `x := 1; x > 0` | `Program` |
| Temporary assignment | `total := sum({tC_27.00, c0010})` | `Assignment` |
| Persistent assignment | `{tC_01.00, r0010, c0010} <- {tC_01.00, r0020, c0010} * 2` | `PersistentAssignment` |
| `with` context, optionally with a `where` clause | `with {tC_01.00, c*}[where qEBB = "A"]: {r0010} > 0` | `With` |

```dpm-xl
{tC_01.00, r0010, c0010} >= 0
total := sum({tC_27.00, c0010}); total <= {tC_01.00, r0010, c0010}
{tC_01.00, r0010, c0010} <- {tC_01.00, r0020, c0010} * 2; {vX} <- 5; true
with {tC_01.00, c*, default: 0, interval: true}: {r0010} = {r0020} + {r0030}
with {tC_01.00, c*}[where qEBB = "A"]: {r0010} > 0
```

A `with` context sets a table, axes and options for every selection in its
body; a selection's own components win, and a nested `with` replaces the
parts it names. `parse` reads one expression (a trailing `;` is allowed);
`parse_program` reads statements and assignments
([Statements and assignments](../concepts/statements.md)).

## Selections

`{…}` selects cells. Components are separated by commas, in any order, each
at most once.

| Component | Example | Meaning |
| --- | --- | --- |
| Table | `tC_01.00`, `t_C_01.00`, `` t`C 01.00` `` | The table code; `_` after `t` is cosmetic, backticks escape a code |
| Rows, columns, sheets | `r0010`, `c0010`, `s0001` | One coordinate |
| Range | `r0010-0050` | Inclusive; numeric when both ends are numbers |
| List | `(c0010, c0030-0050)` | Several codes and ranges |
| Wildcard | `r*`, `c*`, `s*` | Every coordinate on the axis |
| `default: v` | `default: 0`, `default: ""`, `default: null` | Value for cells with no fact |
| `interval: b` | `interval: true` | Use [interval arithmetic](../concepts/intervals.md) |

```dpm-xl
{tC_01.00, r0010, c0010}
{tC_01.00, r0010-0050, (c0010, c0030), s*, default: 0, interval: true}
{t_C_01.00, r0010, c0010}
{tC_01.00, r310, c0010}
```

Selections parse to `Selection` nodes holding a
[`SelectionSpec`][dpmxl.ast.SelectionSpec]. Numeric codes match as numbers
padded to four digits (`r310` is row `0310`).

## References

| Construct | Example | Node |
| --- | --- | --- |
| Filing indicator | `{v_C_01.00}` | `TableReported` |
| Report parameter | `{vrefPeriod}` | `Parameter` |
| Typed parameter | `{p_Limit, number, default: 5}` | `TypedParameter` |
| Operation reference | `{o_v1234, r0010, default: 0}` | `Selection` (`spec.operation`) |
| Table group | `{g_G_01, r0010, c0010}` | `Selection` (`spec.table_group`) |

```dpm-xl
{v_C_01.00} and {v_C_02.00}
{vrefPeriod} = #2026-12-31#
{tC_01.00, r0010, c0010} > {p_Limit, number, default: 5}
{p_Currencies, set-item} = {p_Currencies, set-item}
{o_v1234, r0010, default: 0, interval: false} > 0
{g_G_01, r0010, c0010} >= 0
```

Parameter types are `number`, `integer`, `string`, `date`, `boolean`, `item`
and `set-` followed by one of those. A `_` after `t`, `g`, `o` and `p` is
cosmetic; after `v` it is not (`{v_X}` tests a filing indicator, `{vX}` reads
a parameter). See [Parameters, operations and table groups](../concepts/references.md).

## Literals

| Literal | Examples | Node |
| --- | --- | --- |
| Number | `12`, `-3.5`, `1e6`, `4.5%` (0.045) | `Literal_` (`kind="number"`) |
| Text | `"text"`, `'text'`, `''` | `Literal_` (`string`) |
| Date | `#2026-12-31#`, `#2026-12-31T10:00:00#` | `Literal_` (`date`) |
| Boolean | `true`, `false` | `Literal_` (`boolean`) |
| Null | `null` | `Literal_` (`null`) |
| Item | `[eba_qEC:qx01]`, `[qx01]` | `Literal_` (`item`), value [`Item`][dpmxl.ast.Item] |
| Set | `{1, 2}`, `{[eba_CU:EUR], [eba_CU:USD]}`, `{}` | `SetLiteral` |
| Escaped name | `` `x.y` ``, `` `to` `` | `Name` |

```dpm-xl
{tC_01.00, r0010, c0010} > 4.5%
{tC_01.00, r0010, c0010} = "text" or {tC_01.00, r0010, c0010} = ''
{tC_01.00, r0010, c0010} <= #2026-12-31T10:00:00#
{tC_01.00, r0010, c0010} in {[eba_qEC:qx01], [eba_qEC:qx02]}
{tC_01.00, r0010, c0010} in {}
isnull(null)
```

## Operators

From loosest to tightest binding:

| Level | Operators | Node |
| --- | --- | --- |
| 1 | `or`, `xor` | `Binary` |
| 2 | `and` | `Binary` |
| 3 | `not` | `Unary` |
| 4 | `=`, `!=`, `<>`, `<`, `<=`, `>`, `>=`, `in`, `not in` (one per operand, not chained) | `Binary`, `In` |
| 5 | `&` (text concatenation) | `Binary` |
| 6 | `+`, `-` | `Binary` |
| 7 | `*`, `/` | `Binary` |
| 8 | unary `-`, `+` | `Unary` |
| 9 | `%` after a number, clauses `[…]` | `Literal_`, clause nodes |

`<>` is `!=` (the node's `op` is `!=`). Parentheses group as usual. `&`
joins text; other operands are an error. Comparisons order numbers, dates,
text and items; Booleans order `false < true`.

```dpm-xl
{tT, r0010} = {tT, r0020} + {tT, r0030} * 2
{tT, r0010} != 0 xor {tT, r0020} <> 0
not {tT, r0010} > 0 or {tT, r0020} not in {1, 2}
{tT, r0010, c0010} & "-" & {tT, r0010, c0020} = "A-B"
-({tT, r0010} - {tT, r0020}) < 0
```

`if condition then a [else b] endif` parses to `If`:

```dpm-xl
if {v_C_01.00} then {tC_01.00, r0010, c0010} > 0 endif
if {tT, r0010} > 0 then {tT, r0020} else {tT, r0030} endif >= 0
```

## Functions

Calls parse to [`Call`][dpmxl.ast.Call] with the canonical name
([`canonical_function`][dpmxl.grammar.canonical_function]).

| Group | Functions |
| --- | --- |
| Aggregates (with optional `group by`) | `sum`, `count`, `avg`, `min`, `max`, `median`, and the spellings `min_aggr`, `max_aggr` |
| Numeric | `abs`, `exp`, `ln`, `sqrt`, `power(x, n)`, `log(x, base)`, `min(a, b, …)`, `max(a, b, …)` |
| Null | `isnull(x)`, `nvl(x, replacement)` |
| Text | `len(s)`, `substr(s, start, length)`, `match(s, pattern)` |
| Dates | `year`, `semester`, `quarter`, `month`, `week`, `day`, `date(y, m, d)` |
| Time | `time_shift(x, A\|S\|Q\|M\|W\|D, n[, key])`, `annualise(x, fiscalYearEnd, key)` |
| Sets | `set_of(x)`, `union`, `intersect`, `setdiff`, `symdiff` |
| Filtering | `filter(data, condition)` |

```dpm-xl
sum({tC_27.00, c0010}) > 0
sum({tC_27.00, c0010} group by qCPI) > 0
max_aggr({tC_27.00, c0010}) >= min({tC_27.00, c0010})
abs({tT, r0010}) + exp(0) + ln(1) + sqrt(4) + power(2, 3) + log(8, 2) > 0
nvl({tT, r0010}, 0) = 0 or isnull({tT, r0020})
len({tT, r0010}) = 20 and substr({tT, r0010}, 1, 4) = "5299" and match({tT, r0010}, "[A-Z0-9]{18}[0-9]{2}")
year({p_refPeriod, date}) = 2026 and semester(#2026-12-31#) = 2 and quarter(#2026-12-31#) = 4
month(#2026-12-31#) + week(#2026-12-31#) + day(#2026-12-31#) > 0 and date(2026, 12, 31) = #2026-12-31#
{tT, r0010} >= time_shift({tT, r0010}, Q, 1, refPeriod)
annualise({tC_27.00, c0010}, 12, qDAT) > 0
{tT, r0010} in union(set_of({tT, r0020}), intersect({1, 2}, setdiff({2, 3}, symdiff({1}, {2}))))
count(filter({tC_27.00, c0010}, {tC_27.00, c0010} > 0)) > 0
```

`substr` counts from 1 (start ≥ 1, length ≥ 0, whole numbers) and yields `''`
past the end. `log(x, base)` follows `ln` (null outside its domain). `week`
is the ISO 8601 week and `semester` 1 or 2. `match` uses the pattern as a
regular expression that must match the whole text.

## Analytic functions

`rank(x over (…))` and the aggregates with `over (…)` parse to
[`Analytic`][dpmxl.ast.Analytic] with a [`Window`][dpmxl.ast.Window]:

```dpm-xl
with {tC_08.02}: rank({c0010} over (partition by qEEA order by qEEA desc)) > 0
with {tC_08.02}: sum({c0010} over (order by qEEA data points between unbounded preceding and current data point)) > 0
with {tO}: avg({c0010} over (partition by qEBB order by qDAT range between 3 M preceding and current data point)) > 0
with {tO}: max({c0010} over (partition by qEBB order by qDAT asc data points between 1 preceding and 1 following)) > 0
```

`over (partition by k, … order by k [asc|desc], … [data points|range]
between … and …)`, with bounds `unbounded preceding|following`, `current
data point` and `n [A|S|Q|M|W|D] preceding|following`.
[Aggregates and analytic functions](../concepts/analytics.md) explains the
windows.

## Clauses

Clauses follow an operand in brackets and can be chained:

| Clause | Example | Node |
| --- | --- | --- |
| `where` | `{tC_27.00, c0010}[where qCPI = "LEI-A"]` | `Where` |
| `get` | `{tC_27.00, c0010}[get qCPI]` | `Get` |
| `sub` | `{tC_27.00, c0010}[sub qCPI = "LEI-A"]` | `Sub` |
| `rename` | `{tC_27.00, c0010}[rename qCPI to qX, qEBB to qY]` | `Rename` |

```dpm-xl
{tC_27.00, c0010}[where qCPI = "LEI-A" and qEBB <> "x"] > 0
{tC_27.00, c0010}[get qCPI] = "LEI-A"
{tC_27.00, c0010}[sub qCPI = "LEI-A"] > 0
{tC_27.00, c0010}[rename qCPI to qX][where qX = "LEI-A"] > 0
{tC_27.00, c0010}[where qEBB <-1] > 0
```

Inside clauses, as in the grammar, `<-` reads `< -`, so the last example
compares `qEBB` with `-1`.

## Where dpm-xl differs from the grammar

Some readings differ from the DPM-XL grammar on purpose, so that EBA rules
keep their meaning:

- `not` binds looser than comparisons and `in`: `not a = b` is
  `not (a = b)`.
- Chained comparisons such as `a < b < c` or `a in b in c`, `- not x`, and a
  selection that repeats an axis, `default` or `interval` are syntax errors.
- Outside clauses `<-` is the persistent assignment, so compare with a
  negated operand as `a < -b`.

<!-- docs: invalid -->
```dpm-xl
{tT, r0010} < {tT, r0020} < {tT, r0030}
1 in {1} in {true}
- not true
{tT, r0010, r0020}
```

In the other direction, keywords match in any case, `null` and `<>` are
accepted anywhere, and the last of several statements needs no `;`.

Every distinct EBA rule and precondition expression of DPM releases 3.4–4.4
parses, except two source expressions with typos (`trueendif`, `ornot`),
which are reported as syntax errors. Expressions nested more than 50 deep
(chained clauses included) and numbers outside the decimal128 range are
syntax errors.

## Reserved words

`with`, `to`, `where`, `get`, `sub`, `rename` and `over`, and the other
keywords in [`dpmxl.grammar.KEYWORDS`][dpmxl.grammar.KEYWORDS], cannot be
key names unless escaped: `` `to` ``.
