---
description: Build syntax highlighting, error squiggles and completion for DPM-XL with the tokenizer, the grammar module and the TextMate grammar.
---

# Build editor support

dpm-xl exposes what an editor needs: typed tokens with source offsets, the
language's keywords and function names, a TextMate grammar and syntax errors
with a start and end offset.

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
holds all of those names.

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
