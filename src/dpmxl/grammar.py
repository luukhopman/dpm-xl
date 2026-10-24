"""Machine-readable vocabulary of DPM-XL for editors and other tooling.

The sets below are the words and symbols the tokenizer recognizes; the tests
check that :func:`dpmxl.parser.tokenize` agrees with them. Words are lower
case; the tokenizer matches keywords in any case.
"""

from __future__ import annotations

import re
from typing import Any

KEYWORDS = frozenset(
    {
        "and",
        "else",
        "endif",
        "get",
        "group by",
        "if",
        "in",
        "not",
        "or",
        "over",
        "rename",
        "sub",
        "then",
        "to",
        "where",
        "with",
        "xor",
    }
)
"""Keywords of expressions and clauses."""

WINDOW_KEYWORDS = frozenset(
    {
        "asc",
        "between",
        "current data point",
        "data points",
        "desc",
        "following",
        "order by",
        "partition by",
        "preceding",
        "range",
        "unbounded",
    }
)
"""Keywords inside an analytic ``over (...)`` clause."""

SELECTION_KEYWORDS = frozenset({"default", "interval"})
"""Option keywords inside a ``{...}`` selection."""

PARAMETER_TYPES = frozenset(
    {
        "boolean",
        "date",
        "integer",
        "item",
        "number",
        "set-boolean",
        "set-date",
        "set-integer",
        "set-item",
        "set-number",
        "set-string",
        "string",
    }
)
"""Data types of a ``{p_Name, type}`` parameter reference."""

LITERAL_WORDS = frozenset({"false", "null", "true"})
"""Boolean and null literals."""

TIME_PERIODS = frozenset({"A", "S", "Q", "M", "W", "D"})
"""Period codes of ``time_shift`` and ``range`` window bounds (upper case)."""

AGGREGATE_FUNCTIONS = frozenset(
    {"avg", "count", "max_aggr", "median", "min_aggr", "sum"}
)
"""Aggregate operators; ``max`` and ``min`` with one operand aggregate too."""

ANALYTIC_FUNCTIONS = frozenset({"rank"})
"""Operators that take only an analytic ``over (...)`` clause."""

FUNCTIONS = (
    AGGREGATE_FUNCTIONS
    | ANALYTIC_FUNCTIONS
    | frozenset(
        {
            "abs",
            "annualise",
            "date",
            "day",
            "exp",
            "filter",
            "intersect",
            "isnull",
            "len",
            "length",
            "ln",
            "log",
            "match",
            "max",
            "min",
            "month",
            "nvl",
            "power",
            "quarter",
            "semester",
            "set_of",
            "setdiff",
            "sqrt",
            "substr",
            "symdiff",
            "time_shift",
            "union",
            "week",
            "year",
        }
    )
)
"""Function names, recognized when followed by ``(``."""

OPERATORS = frozenset(
    {
        "!=",
        "%",
        "&",
        "*",
        "+",
        "-",
        "/",
        ":=",
        "<",
        "<-",
        "<=",
        "<>",
        "=",
        ">",
        ">=",
    }
)
"""Operator symbols, including the assignments ``:=`` and ``<-``."""

PUNCTUATION = frozenset({"(", ")", ",", ":", ";", "[", "]"})
"""Punctuation; ``{`` and ``}`` are the separate ``brace`` token kind."""

REFERENCE_PREFIXES = {
    "t": "table",
    "g": "table_group",
    "v": "variable",
    "o": "operation",
    "p": "parameter",
}
"""Selection reference prefix to token kind, such as ``tC_01.00``."""

AXIS_PREFIXES = frozenset({"r", "c", "s"})
"""Prefixes of row, column and sheet coordinates inside a selection."""

TOKEN_KINDS = frozenset(
    {
        "axis",
        "boolean",
        "brace",
        "date",
        "eof",
        "function",
        "identifier",
        "item",
        "keyword",
        "null",
        "number",
        "operation",
        "operator",
        "parameter",
        "period",
        "punctuation",
        "string",
        "table",
        "table_group",
        "type",
        "variable",
    }
)
"""Every ``Token.kind`` that :func:`dpmxl.parser.tokenize` produces."""


def _words(words: frozenset[str]) -> str:
    # Longest first, so that "set-number" wins over "set"; spaces match any
    # whitespace, as in the tokenizer.
    ordered = sorted(words, key=lambda word: (-len(word), word))
    return "|".join(word.replace(" ", r"\s+").replace("-", r"\-") for word in ordered)


def textmate_grammar() -> dict[str, Any]:
    """Build a TextMate grammar for DPM-XL syntax highlighting.

    ``editors/dpm-xl.tmLanguage.json`` in the repository is this grammar;
    the tests keep the two in step.

    Returns:
        dict[str, Any]: The grammar, ready for ``json.dump``.
    """
    boundary = r"(?<![A-Za-z0-9_.])"
    end = r"(?![A-Za-z0-9_])"
    return {
        "$schema": (
            "https://raw.githubusercontent.com/martinring/tmlanguage/master/"
            "tmlanguage.json"
        ),
        "name": "DPM-XL",
        "scopeName": "source.dpm-xl",
        "fileTypes": ["dpmxl", "dpm-xl"],
        "patterns": [
            {"include": "#strings"},
            {"include": "#dates"},
            {"include": "#selections"},
            {"include": "#items"},
            {"include": "#expression"},
        ],
        "repository": {
            "strings": {
                "patterns": [
                    {"name": "string.quoted.double.dpm-xl", "match": r'"[^"]*"'},
                    {"name": "string.quoted.single.dpm-xl", "match": r"'[^']*'"},
                ]
            },
            "dates": {
                "name": "constant.other.date.dpm-xl",
                "match": r"#[0-9]{4}-[0-9]{2}-[0-9]{2}(T[0-9:]{8})?#",
            },
            "items": {
                "name": "constant.other.item.dpm-xl",
                "match": r"\[\s*[A-Za-z_][A-Za-z0-9_.\-]*:[A-Za-z0-9_.\-]+\s*\]",
            },
            "selections": {
                "begin": r"\{",
                "end": r"\}",
                "beginCaptures": {"0": {"name": "punctuation.section.braces.dpm-xl"}},
                "endCaptures": {"0": {"name": "punctuation.section.braces.dpm-xl"}},
                "patterns": [
                    {"include": "#strings"},
                    {"include": "#dates"},
                    {"include": "#items"},
                    {"include": "#selections"},
                    {
                        "name": "storage.type.dpm-xl",
                        "match": f"{boundary}({_words(PARAMETER_TYPES)}){end}",
                    },
                    {
                        "name": "keyword.other.option.dpm-xl",
                        "match": f"{boundary}({_words(SELECTION_KEYWORDS)}){end}",
                    },
                    {
                        "name": "constant.language.dpm-xl",
                        "match": f"{boundary}({_words(LITERAL_WORDS)}){end}",
                    },
                    {
                        "name": "variable.other.axis.dpm-xl",
                        "match": (
                            f"{boundary}[rcs](\\*|[0-9A-Za-z]+(-[0-9A-Za-z]+)?)"
                            r"(?![A-Za-z0-9_.\-])"
                        ),
                    },
                    {
                        "name": "entity.name.type.table.dpm-xl",
                        "match": (f"{boundary}[tgvop](`[^`]*`|[A-Za-z0-9_.\\-]+)"),
                    },
                    {"include": "#numbers"},
                ],
            },
            "numbers": {
                "name": "constant.numeric.dpm-xl",
                "match": r"(?<![A-Za-z_])\d+(\.\d+)?([eE][+-]?\d+)?%?",
            },
            "expression": {
                "patterns": [
                    {
                        "name": "keyword.control.dpm-xl",
                        "match": (
                            f"{boundary}(?i:{_words(KEYWORDS | WINDOW_KEYWORDS)}){end}"
                        ),
                    },
                    {
                        "name": "constant.language.dpm-xl",
                        "match": f"{boundary}(?i:{_words(LITERAL_WORDS)}){end}",
                    },
                    {
                        "name": "support.function.dpm-xl",
                        "match": f"{boundary}({_words(FUNCTIONS)})(?=\\s*\\()",
                    },
                    {"include": "#numbers"},
                    {
                        "name": "keyword.operator.dpm-xl",
                        "match": "|".join(
                            re.escape(operator)
                            for operator in sorted(
                                OPERATORS, key=lambda text: (-len(text), text)
                            )
                        ),
                    },
                    {
                        "name": "variable.other.escaped.dpm-xl",
                        "match": r"`[^`]*`",
                    },
                ]
            },
        },
    }


__all__ = [
    "AGGREGATE_FUNCTIONS",
    "ANALYTIC_FUNCTIONS",
    "AXIS_PREFIXES",
    "FUNCTIONS",
    "KEYWORDS",
    "LITERAL_WORDS",
    "OPERATORS",
    "PARAMETER_TYPES",
    "PUNCTUATION",
    "REFERENCE_PREFIXES",
    "SELECTION_KEYWORDS",
    "TIME_PERIODS",
    "TOKEN_KINDS",
    "WINDOW_KEYWORDS",
    "textmate_grammar",
]
