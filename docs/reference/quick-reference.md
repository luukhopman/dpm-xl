---
description: DPM-XL on one page - statements, selections, references, literals, operators by precedence, clauses, every function and the complete grammar, each linked to its language reference entry.
---

# Quick reference

DPM-XL at a glance. Each entry links to the
[language reference](language.md), which gives the exact types, null
behaviour, errors and examples.

```dpm-xl
with {tC_01.00, c*, default: 0, interval: true}: {r0010} = {r0020} + {r0030}
if {v_C_27.00} then sum({tC_27.00, c0010} group by qCPI) >= 0 endif
{tC_27.00, c0020}[where qCPI <> "LEI-A"] in {p_Allowed, set-item}
total := sum({tC_27.00, c0010}); total <= {tC_01.00, r0010, c0010}
```

## Statements

| Syntax | Meaning |
| --- | --- |
| `expression` | A rule: one expression, evaluated per record ([Programs and statements](language.md#statements)) |
| `s1; s2; s3` | A script; the last statement gives the result |
| `name := e` | [Temporary assignment](language.md#temporary-assignment) for later statements |
| `{tT, r0010, c0010} <- e`, `{vX} <- e` | [Persistent assignment](language.md#persistent-assignment), returned in `RuleResult.assignments` |
| `with {tT, c*, default: 0}: e` | [Context](language.md#with) for the selections of `e` |
| `with {tO}[where qEBB = "A"]: e` | Context with a `where` on every selection of `e` |

## Selections and references

| Syntax | Meaning |
| --- | --- |
| `{tC_01.00, r0010, c0010}` | [Cells](language.md#selections) of table `C_01.00`; `t_C_01.00` and `` t`C 01.00` `` also work |
| `r0010`, `r0010-0050`, `(r0010, r0030-0050)`, `r*` | [Rows](language.md#axes): one, a range, a list, all; likewise `c` and `s` |
| `default: 0` | [Value for missing facts](language.md#default) and for keys another operand has |
| `interval: true` | [Interval arithmetic](language.md#interval) on reported precision |
| `{v_C_01.00}` | [Filing indicator](language.md#filing-indicator): was the table reported |
| `{vrefPeriod}`, `refPeriod` | [Report parameter](language.md#report-parameter), as given |
| `{p_Limit, number, default: 5}` | [Typed parameter](language.md#typed-parameter); types `number integer string date boolean item` and `set-…` of each |
| `{o_v1234, r0010}` | [Operation](language.md#operation) result |
| `{g_G01, r0010, c0010}` | [Table group](language.md#table-group), keyed by table `t` |

## Literals

| Syntax | Type |
| --- | --- |
| `12`, `-3.5`, `.5`, `1e6`, `4.5%` | [number](language.md#numbers) (`4.5%` is 0.045) |
| `"text"`, `'text'`, `''` | [text](language.md#strings), no escapes |
| `#2026-12-31#`, `#2026-12-31T10:00:00#` | [date](language.md#dates) |
| `true`, `false`, `null` | [boolean, null](language.md#boolean-and-null) |
| `[eba_CU:EUR]`, `[qEBB]` | [item](language.md#items) |
| `{1, 2}`, `{[CU:EUR], [CU:USD]}`, `{}` | [set](language.md#set-literals) |
| `` `to` ``, `` `a b` `` | [escaped name](language.md#names) |

## Operators

Loosest first; see [Precedence and associativity](language.md#precedence).

| Operators | Meaning |
| --- | --- |
| `or`, `xor` | [Logical](language.md#logical), three-valued |
| `and` | [Logical](language.md#logical), three-valued |
| `not` | [Negation](language.md#not); `not a = b` is `not (a = b)` |
| `=`, `!=`, `<>`, `<`, `<=`, `>`, `>=` | [Comparison](language.md#comparison), not chained |
| `in`, `not in` | [Membership](language.md#in) in a set |
| `&` | [Text concatenation](language.md#concatenation) |
| `+`, `-` | [Addition, subtraction](language.md#arithmetic) |
| `*`, `/` | [Multiplication, division](language.md#arithmetic) |
| unary `-`, `+` | [Sign](language.md#unary) |
| `n%`, `[…]` | [Percentage](language.md#percent), [clauses](language.md#clauses) |
| `if c then a else b endif` | [Conditional](language.md#if); `else` optional |

## Clauses

| Syntax | Meaning |
| --- | --- |
| `x[where qEBB = "A"]` | [Keep records](language.md#where) whose keys satisfy a condition |
| `x[get qEBB]` | [Replace values](language.md#get) by a key's values |
| `x[sub qEBB = "A"]` | [Fix a key](language.md#sub) and drop it |
| `x[rename qEBB to qX, …]` | [Rename keys](language.md#rename) |

Key names ignore case and the `q` prefix ([Key names](language.md#key-names)).

## Functions

| Function | Operands | Result |
| --- | --- | --- |
| [`abs(x)`](language.md#abs) | number | number |
| [`exp(x)`, `ln(x)`, `sqrt(x)`](language.md#exp) | number | number, null if undefined |
| [`power(x, y)`](language.md#power), [`log(x, base)`](language.md#log) | numbers | number, null if undefined |
| [`max(a, b, …)`, `min(a, b, …)`](language.md#max) | numbers, or dates, text, items | the largest, smallest per record |
| [`isnull(x)`](language.md#isnull) | any | boolean |
| [`nvl(x, r)`](language.md#nvl) | any | `x`, or `r` where `x` is null |
| [`len(s)`, `length(s)`](language.md#len) | text | number |
| [`substr(s, start, length)`](language.md#substr) | text, whole numbers | text |
| [`match(s, pattern)`](language.md#match) | text, regular expression | boolean |
| [`year`, `semester`, `quarter`, `month`, `week`, `day`](language.md#date-parts) | date | number |
| [`date(y, m, d)`](language.md#date) | whole numbers | date |
| [`time_shift(x, period, n, key)`](language.md#time_shift) | any, `A` `S` `Q` `M` `W` or `D`, whole number, optional name | `x` as `n` periods earlier |
| [`annualise(x, fiscalYearEnd, key)`](language.md#annualise) | number, month, name | number |
| [`set_of(x)`](language.md#set_of) | any | set |
| [`union`, `intersect`](language.md#union) | two or more sets | set |
| [`setdiff`, `symdiff`](language.md#setdiff) | two sets | set |
| [`filter(x, condition)`](language.md#filter) | any, boolean | the records of `x` where true |

## Aggregates and analytic functions

| Syntax | Meaning |
| --- | --- |
| [`sum`](language.md#sum), [`count`](language.md#count), [`avg`](language.md#avg), [`median`](language.md#median), [`max`, `min`, `max_aggr`, `min_aggr`](language.md#aggregate-max) | [Aggregates](language.md#aggregates): `sum(x)`, `sum(x group by k1, k2)` |
| `sum(x over (partition by k order by d desc data points between 1 preceding and current data point))` | [Analytic aggregate](language.md#analytic-functions) per record |
| `range between 3 M preceding and current data point` | Window by order key value; `unbounded preceding`, `unbounded following`, `n preceding`, `n following` |
| [`rank(x over (partition by k order by d))`](language.md#rank) | Rank per partition; ties share the lowest rank |

## Grammar

The complete syntax, in the [notation](language.md#notation) of the
language reference. Keywords match in any case; `group by` and the other
two-word keywords take any whitespace between their words.

```text
program      ::= statement ( ";" statement )* ";"?
statement    ::= name ":=" assigned | assigned
assigned     ::= target "<-" context | context
target       ::= selection | "{" "v" name "}" | "{" "v_" code "}"
context      ::= "with" selection ( "[" "where" expression "]" )? ":" context
               | expression

expression   ::= disjunction
disjunction  ::= conjunction ( ( "or" | "xor" ) conjunction )*
conjunction  ::= negation ( "and" negation )*
negation     ::= "not" negation | comparison
comparison   ::= concatenation ( ( "=" | "!=" | "<>" | "<" | "<=" | ">" | ">=" ) concatenation
                               | "not"? "in" concatenation )?
concatenation ::= additive ( "&" additive )*
additive     ::= multiplicative ( ( "+" | "-" ) multiplicative )*
multiplicative ::= unary ( ( "*" | "/" ) unary )*
unary        ::= ( "+" | "-" ) unary | postfix
postfix      ::= primary ( "%" | clause )*
primary      ::= literal | set | selection | reference | name | call | analytic
               | "if" expression "then" expression ( "else" expression )? "endif"
               | "(" expression ")"

clause       ::= "[" "where" expression "]"
               | "[" "get" name "]"
               | "[" "sub" name "=" additive "]"
               | "[" "rename" name "to" name ( "," name "to" name )* "]"

selection    ::= "{" component ( "," component )* "}"
component    ::= source | axis | "default" ":" default
               | "interval" ":" ( "true" | "false" )
source       ::= ( "t" | "g" | "o" ) "_"? code
axis         ::= part | "(" part ( "," part )* ")" | ( "r" | "c" | "s" ) "*"
part         ::= ( "r" | "c" | "s" ) alnum+ ( "-" ( "r" | "c" | "s" )? alnum+ )?
default      ::= ( "+" | "-" )? number "%"? | "(" default ")" | text | "true" | "false"
               | "null" | item | date | set
reference    ::= "{" "v_" code "}" | "{" "v" name "}"
               | "{" "p" "_"? code "," type ( "," "default" ":" default )? "}"
type         ::= ( "set-" )? ( "number" | "integer" | "string" | "date" | "boolean" | "item" )

call         ::= name "(" ( expression ( "," expression )* )? ")"
               | aggregate "(" expression "group" "by" name ( "," name )* ")"
               | "time_shift" "(" expression "," period "," expression ( "," name )? ")"
analytic     ::= ( aggregate | "rank" ) "(" expression "over" "(" partition? order? window? ")" ")"
aggregate    ::= "sum" | "count" | "avg" | "median" | "max" | "min" | "max_aggr" | "min_aggr"
partition    ::= "partition" "by" name ( "," name )*
order        ::= "order" "by" name ( "asc" | "desc" )? ( "," name ( "asc" | "desc" )? )*
window       ::= ( "data" "points" | "range" ) "between" bound "and" bound
bound        ::= "unbounded" ( "preceding" | "following" ) | "current" "data" "point"
               | digit+ period? ( "preceding" | "following" )
period       ::= "A" | "S" | "Q" | "M" | "W" | "D"

set          ::= "{" "}" | "{" expression ( "," expression )* "}"
literal      ::= number "%"? | text | date | "true" | "false" | "null" | item
```

A set's first member is a literal, an item, a signed number or a
parenthesized number; braces that start otherwise are a selection or
reference. The lexical rules for `name`, `code`, `number`, `text`, `date`
and `item` are under [Lexical structure](language.md#lexical).
