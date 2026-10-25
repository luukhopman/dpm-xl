"""Machine-readable vocabulary of DPM-XL for editors and other tooling.

The sets below are the words and symbols the tokenizer recognizes; the tests
check that [`tokenize`][dpmxl.parser.tokenize] agrees with them. Words are lower
case; the tokenizer matches keywords in any case.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
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

FUNCTION_ALIASES = {"max_aggr": "max", "min_aggr": "min"}
"""Source spellings whose ``Call.name`` differs: the aggregate forms of
``max`` and ``min``, which evaluators recognize by their single operand."""


def canonical_function(name: str) -> str:
    """Map a function's source spelling to the ``Call.name`` the parser gives it.

    Args:
        name: A function name as written, in any case.

    Returns:
        str: The lower-case name, with ``max_aggr`` and ``min_aggr`` read as
        ``max`` and ``min``.

    Examples:
        >>> canonical_function("max_aggr"), canonical_function("SUM")
        ('max', 'sum')
    """
    folded = name.casefold()
    return FUNCTION_ALIASES.get(folded, folded)


CALL_NAMES = frozenset(
    canonical_function(name) for name in FUNCTIONS - ANALYTIC_FUNCTIONS
)
"""Every ``Call.name`` a known function parses to. Aggregates among them are
``{canonical_function(name) for name in AGGREGATE_FUNCTIONS}``, which equals
``dpmxl.evaluator.AGGREGATES``. Analytic functions (``rank``, and aggregates
with ``over``) parse to [`Analytic`][dpmxl.ast.Analytic] instead of a call."""

_ORDINALS = ("first", "second", "third", "fourth")


@dataclass(frozen=True, slots=True)
class Signature:
    """How many operands a function takes, and where it takes a key name.

    Both evaluators check calls against these signatures, and
    [`diagnose`][dpmxl.diagnostics.diagnose] reports the same problems before
    evaluation, so the three never disagree.

    Attributes:
        minimum: The fewest operands.
        maximum: The most operands, or ``None`` for no limit.
        group_by: Whether ``group by`` may follow the (single) operand.
        key_operand: Zero-based position of an operand that must be a key
            name, such as ``qDATE`` in ``annualise(x, 12, qDATE)``; ``None``
            when there is none.
        period_operand: Zero-based position of an operand that is a period
            code from `TIME_PERIODS`, such as ``Q`` in ``time_shift(x, Q, 1)``;
            ``None`` when there is none.

    Examples:
        >>> SIGNATURES["substr"].problem("substr", 4)
        'substr takes 1 to 3 operands, not 4'
        >>> SIGNATURES["sum"].problem("sum", 1, group_by=True) is None
        True
        >>> SIGNATURES["abs"].problem("abs", 1, group_by=True)
        'group by is not allowed in abs'
    """

    minimum: int
    maximum: int | None
    group_by: bool = False
    key_operand: int | None = None
    period_operand: int | None = None

    def operands(self) -> str:
        """Describe the accepted operand count.

        Returns:
            str: For example ``1 operand``, ``3 or 4 operands``, ``1 to 3
            operands`` or ``2 or more operands``.
        """
        low, high = self.minimum, self.maximum
        noun = "operand" if low == high == 1 else "operands"
        if high is None:
            return f"{low} or more {noun}"
        if low == high:
            return f"{low} {noun}"
        if high == low + 1:
            return f"{low} or {high} {noun}"
        return f"{low} to {high} {noun}"

    def problem(self, name: str, count: int, *, group_by: bool = False) -> str | None:
        """Return what is wrong with a call's operand count, if anything.

        Args:
            name: The function's ``Call.name``, for the message.
            count: The number of operands written.
            group_by: Whether the call has a ``group by`` clause.

        Returns:
            str | None: A message such as ``abs takes 1 operand, not 2``, or
            ``None`` when the call is well formed.
        """
        if group_by:
            if not self.group_by:
                return f"group by is not allowed in {name}"
            if count != 1:
                return f"{name} with group by takes 1 operand, not {count}"
            return None
        if count < self.minimum or (self.maximum is not None and count > self.maximum):
            return f"{name} takes {self.operands()}, not {count}"
        return None

    def key_problem(self, name: str) -> str:
        """Describe a call whose key operand is not a key name.

        Returns:
            str: For example ``annualise needs a key name as its third
            operand``.
        """
        position = self.key_operand if self.key_operand is not None else 0
        return f"{name} needs a key name as its {_ORDINALS[position]} operand"


def _signatures() -> dict[str, Signature]:
    one = Signature(1, 1)
    two = Signature(2, 2)
    signatures = {
        # Aggregates; max and min with several operands compare them instead.
        **{
            name: Signature(1, 1, group_by=True)
            for name in ("avg", "count", "median", "sum")
        },
        **{name: Signature(1, None, group_by=True) for name in ("max", "min")},
        "filter": two,
        "time_shift": Signature(3, 4, key_operand=3, period_operand=1),
        "annualise": Signature(3, 3, key_operand=2),
        "set_of": one,
        "setdiff": two,
        "symdiff": two,
        "union": Signature(2, None),
        "intersect": Signature(2, None),
        **dict.fromkeys(
            (
                "abs",
                "isnull",
                "len",
                "length",
                "exp",
                "ln",
                "sqrt",
                "year",
                "semester",
                "quarter",
                "month",
                "week",
                "day",
            ),
            one,
        ),
        **dict.fromkeys(("nvl", "match", "power", "log"), two),
        "substr": Signature(1, 3),
        "date": Signature(3, 3),
    }
    return dict(sorted(signatures.items()))


SIGNATURES: Mapping[str, Signature] = MappingProxyType(_signatures())
"""The [`Signature`][dpmxl.grammar.Signature] of every name in `CALL_NAMES`."""

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

AXIS_LETTERS = frozenset({"r", "c", "s"})
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
"""Every ``Token.kind`` that [`tokenize`][dpmxl.parser.tokenize] produces."""


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

    Examples:
        >>> textmate_grammar()["scopeName"]
        'source.dpm-xl'
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
    "AXIS_LETTERS",
    "CALL_NAMES",
    "FUNCTIONS",
    "FUNCTION_ALIASES",
    "KEYWORDS",
    "LITERAL_WORDS",
    "OPERATORS",
    "PARAMETER_TYPES",
    "PUNCTUATION",
    "REFERENCE_PREFIXES",
    "SELECTION_KEYWORDS",
    "SIGNATURES",
    "TIME_PERIODS",
    "TOKEN_KINDS",
    "WINDOW_KEYWORDS",
    "Signature",
    "canonical_function",
    "textmate_grammar",
]
