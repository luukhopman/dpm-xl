---
description: Build syntax highlighting, error squiggles, quick fixes and completion for DPM-XL with the tokenizer, diagnose, the grammar module and the TextMate grammar.
---

# Build editor support

dpm-xl exposes what an editor needs: typed tokens with source offsets, the
language's keywords, function names and signatures, a TextMate grammar, and
positioned diagnostics with suggested fixes, from every syntax error to
unknown tables, coordinates, keys and operands of the wrong type.

## Highlight with tokens

[`tokenize`][dpmxl.parser.tokenize] splits an expression into
[`Token(kind, text, start, end)`][dpmxl.parser.Token] tuples. The parser
works from the same tokens, so highlighting and parsing never disagree.

```python
from dpmxl.parser import tokenize

for token in tokenize(
    "with {tC_01.00, c0010}: sum({r0010-0050} group by qEBB) >= 0.5%"
):
    print(f"{token.kind:12} {token.text!r:14} {token.start}-{token.end}")
```

```text
keyword      'with'         0-4
brace        '{'            5-6
table        'tC_01.00'     6-14
punctuation  ','            14-15
axis         'c0010'        16-21
brace        '}'            21-22
punctuation  ':'            22-23
function     'sum'          24-27
punctuation  '('            27-28
brace        '{'            28-29
axis         'r0010-0050'   29-39
brace        '}'            39-40
keyword      'group by'     41-49
identifier   'qEBB'         50-54
punctuation  ')'            54-55
operator     '>='           56-58
number       '0.5'          59-62
operator     '%'            62-63
eof          ''             63-63
```

`text` is exactly `expression[start:end]`, quotes, brackets and backticks
included. The kinds are:

| Kind | Tokens |
| --- | --- |
| `keyword` | `if`, `and`, `with`, `where`, `group by`, window keywords inside `over (…)`, and `default` / `interval` in a selection |
| `type` | A parameter type such as `number` or `set-item` |
| `function` | A known function name followed by `(` |
| `operator` | `+ - * / & % = != <> < <= > >= := <-` |
| `punctuation` | `( ) , : ; [ ]` |
| `brace` | `{` or `}` around a selection or set |
| `table`, `table_group`, `variable`, `operation`, `parameter` | A reference with its prefix: `tC_01.00`, `gG_01`, `vX` or `v_X`, `o_v1234`, `pName` |
| `axis` | A row, column or sheet coordinate, range or wildcard: `r0010`, `c0010-0050`, `s*` |
| `number`, `string`, `date`, `boolean`, `null` | Literals |
| `item` | An item such as `[eba_qEC:qx01]` |
| `period` | A `time_shift` or window period code (`A`, `Q`, …) |
| `identifier` | A key, temporary or other name, including escaped names such as `` `x.y` `` |
| `eof` | The empty token that ends every token list |

`tokenize` raises `DpmXlSyntaxError` on an unterminated literal, brace or item,
or an unknown character; an editor can fall back to the TextMate grammar for
such lines.

## Mark syntax errors

[`DpmXlSyntaxError`][dpmxl.parser.DpmXlSyntaxError] has a plain `message`,
the zero-based `position` where the problem starts and `end`, just past the
offending text: the range to underline.

```python
from dpmxl import DpmXlSyntaxError, parse_program

source = "sum({tC_01.00, r0010} group by qEBB qX) > 0"
try:
    parse_program(source)
except DpmXlSyntaxError as error:
    print(
        error.message,
        (error.position, error.end),
        repr(source[error.position : error.end]),
    )
    print(error.pointer())
```

```text
expected ')', found 'qX' (36, 38) 'qX'
sum({tC_01.00, r0010} group by qEBB qX) > 0
                                    ^~
```

Parse with [`parse_program`][dpmxl.parser.parse_program] in an editor: it
accepts everything a rule may hold, including `;`-separated statements and
assignments.

## Find every problem

[`diagnose`][dpmxl.diagnostics.diagnose] returns everything that can be
found wrong without report data, as
[`Diagnostic`][dpmxl.diagnostics.Diagnostic]s: a `severity` (`error` or
`warning`), a stable `code`, a `message`, the `start` and `end` offsets to
underline and, where it applies, the `subject` (the name, code or type
concerned) and a `suggestion` to replace the underlined text with, for a quick
fix. [`pointer`][dpmxl.diagnostics.Diagnostic.pointer] renders one like a
syntax error.

Unlike [`parse`][dpmxl.parser.parse], `diagnose` reports every syntax error:
after one, it resumes where the enclosing construct can carry on, and leaves
out errors that follow from an earlier one. Keywords run together, such as
`ornot` or `trueendif`, are pointed out as a missing space. A construct that
holds a syntax error is not checked further, but the rest is:

```python
from dpmxl import diagnose

source = "if {tC_01.00, r0010} > 0 ornot {tC_01.00, r0020} then summ(1) = = 2 endif"
for diagnostic in diagnose(source):
    print(diagnostic.code, diagnostic.message)
    print(diagnostic.pointer(source))
```

```text
syntax missing space: did you mean 'or not'?
if {tC_01.00, r0010} > 0 ornot {tC_01.00, r0020} then summ(1) = = 2 endif
                         ^~~~~
unknown-function unknown function 'summ'; did you mean 'sum'?
if {tC_01.00, r0010} > 0 ornot {tC_01.00, r0020} then summ(1) = = 2 endif
                                                      ^~~~
syntax unexpected '=' where an operand is expected
if {tC_01.00, r0010} > 0 ornot {tC_01.00, r0020} then summ(1) = = 2 endif
                                                                ^
```

Calls are checked against [`SIGNATURES`][dpmxl.grammar.SIGNATURES], which
the evaluators use too, so `diagnose` reports exactly the operand counts
evaluation would reject. Pass `program=True` to accept scripts with `;`,
`:=` and `<-`, as [`parse_program`][dpmxl.parser.parse_program] does.

### Tables and coordinates

Pass a lookup from table code to [`TableLayout`][dpmxl.provider.TableLayout]
(or `None` for a table that does not exist) to check tables, rows, columns and
sheets, and `tables` to suggest a table for an unknown one. A problem in a
`with` context is reported once, at the context. Severities follow
evaluation: a selection that selects nothing is an error, while a code
missing from an axis list whose other codes match is a warning. A layout's
`open_axes` say which axes have keys instead of codes. What a code on such an
axis, or on an axis the table does not have, selects is up to the provider (a
`MemoryProvider` ignores it, another may select nothing), so it is a warning
when written for that table and not reported when a shared `with` context
applies it:

```python
from dpmxl import TableLayout

layouts = {
    "C_01.00": TableLayout("C_01.00", rows=("0010", "0020"), columns=("0010", "0020")),
    "C_27.00": TableLayout(
        "C_27.00", columns=("0010",), open_keys=("qCPI",), open_axes=("rows",)
    ),
}
source = (
    "with {tC_01.00, c0010}: {r0030} = {r0011} + {tC_27.0, c0010}"
    " + sum({tC_27.00, r0010-0050, c0010})"
)
for diagnostic in diagnose(source, layouts.get, tables=layouts):
    print(
        f"{diagnostic.severity:7} {source[diagnostic.start : diagnostic.end]!r:12} "
        f"{diagnostic.suggestion!s:8} {diagnostic.message}"
    )
```

```text
error   'r0030'      None     row 0030 is not in table C_01.00
error   'r0011'      r0010    row 0011 is not in table C_01.00; did you mean r0010?
error   'tC_27.0'    tC_27.00 unknown table C_27.0; did you mean C_27.00?
warning 'r0010-0050' r*       the rows of C_27.00 are open (key qCPI), so they have no codes such as r0010-0050; select them with r* or leave them out
```

A range that covers no coordinate of its table is `empty-range`, an error
when it is all the selection selects. Table groups and operations are not
checked.

### Data types

When the layouts give their cells' `data_types`, operands of the wrong type
are errors, wherever evaluation would reject them whatever the values. A
selection covering a cell without a type, or with a `default` of another
type, has no known type and is not checked:

```python
layouts["C_01.00"] = TableLayout(
    "C_01.00",
    rows=("0010", "0020"),
    columns=("0010", "0020"),
    data_types={
        (row, column, None): "number" if column == "0010" else "string"
        for row in ("0010", "0020")
        for column in ("0010", "0020")
    },
)
source = 'with {tC_01.00}: {r0010, c0010} + {r0010, c0020} > 0 and {r0020, c0010} = "x"'
for diagnostic in diagnose(source, layouts.get):
    print(diagnostic.message)
```

```text
'+' needs numbers, but {r0010, c0020} is a string
'=' cannot compare a number with a string
```

### Keys and names

A name in a clause, such as `qCPI` in `[where qCPI = "A"]`, a `group by` or an
`over (partition by …)`, must be a key of what it applies to. Pass the report
`parameters` to check names too: a name that is neither a key there, nor a
parameter, nor assigned by an earlier statement of a script is an error.
Without them, a name in a `where` or `get` clause that is not a key is a
warning, since a parameter may stand in for it:

```python
source = "{tC_27.00, c0010} [where qCPX = refDate] > 0 and refPeriod > #2026-01-01#"
for diagnostic in diagnose(source, layouts.get, parameters=["refPeriod"]):
    print(diagnostic.severity, diagnostic.message, diagnostic.suggestion)
```

```text
error qCPX is not a key of table C_27.00 (keys qCPI), nor a report parameter qCPI
error refDate is not a key of table C_27.00 (keys qCPI), nor a report parameter None
```

`dpm-xl check` runs the same checks over a rule file, against the tables and
parameters of a data file with `--layouts`
([CLI reference](../reference/cli.md#dpm-xl-check)).

## Complete keywords and functions

[`dpmxl.grammar`](../reference/api/grammar.md) lists the vocabulary as
frozensets: `KEYWORDS`, `WINDOW_KEYWORDS`, `SELECTION_KEYWORDS`,
`OPERATORS`, `PUNCTUATION`, `FUNCTIONS`, `AGGREGATE_FUNCTIONS`,
`ANALYTIC_FUNCTIONS`, `PARAMETER_TYPES`, `LITERAL_WORDS`, `TIME_PERIODS`,
`AXIS_LETTERS` (`r`, `c`, `s`), `REFERENCE_PREFIXES` and `TOKEN_KINDS`.

```python
from dpmxl import grammar

print(sorted(grammar.AGGREGATE_FUNCTIONS))
print(sorted(grammar.TIME_PERIODS))
print(grammar.canonical_function("max_aggr"), grammar.canonical_function("MAX"))
```

```text
['avg', 'count', 'max_aggr', 'median', 'min_aggr', 'sum']
['A', 'D', 'M', 'Q', 'S', 'W']
max max
```

[`canonical_function`][dpmxl.grammar.canonical_function] gives the
`Call.name` that a spelling parses to (`max_aggr` is `max`), and `CALL_NAMES`
holds all of those names. Each has a [`Signature`][dpmxl.grammar.Signature]
in `SIGNATURES`, for signature help:

```python
signature = grammar.SIGNATURES["time_shift"]
print(signature.operands(), signature.key_operand, signature.period_operand)
print(signature.problem("time_shift", 2))
```

```text
3 or 4 operands 3 1
time_shift takes 3 or 4 operands, not 2
```

## TextMate grammar

[`textmate_grammar()`][dpmxl.grammar.textmate_grammar] builds a TextMate
grammar (scope `source.dpm-xl`) from the same vocabulary, for VS Code,
Sublime Text, GitHub Linguist or any highlighter that reads TextMate
grammars. The repository ships it as
[`editors/dpm-xl.tmLanguage.json`](https://github.com/luukhopman/dpm-xl/blob/main/editors/dpm-xl.tmLanguage.json);
regenerate it after changing `dpmxl.grammar`:

```bash
uv run python -c "import json; from dpmxl.grammar import textmate_grammar; print(json.dumps(textmate_grammar(), indent=2))" > editors/dpm-xl.tmLanguage.json
```

## Show what a rule reads

For hover information or a "go to table" action,
[`references`][dpmxl.references.references] returns every selection with
its inherited `with` context and its source span; see
[Analyse rules statically](analyse.md).
