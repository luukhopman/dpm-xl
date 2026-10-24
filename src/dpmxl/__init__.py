"""Parse and evaluate EBA DPM-XL validation expressions.

Typical use::

    from dpmxl import evaluate_rule, explain, parse

    result = evaluate_rule(expression, provider, precondition=precondition)
    for outcome in result.failures:
        print(explain(result.evaluation, expression, outcome.key).summary)
"""

from ._version import __version__
from .ast import AxisSelector, Item, Node, SelectionSpec
from .evaluator import (
    Evaluation,
    Evaluator,
    Outcome,
    RuleResult,
    SelectionCache,
    evaluate_rule,
    parse_cached,
)
from .explain import Explanation, Operand, explain
from .parser import DpmXlSyntaxError, parse, parse_program, parse_selection
from .provider import (
    CellQuery,
    DataPoint,
    DataProvider,
    MemoryProvider,
    TableLayout,
    axis_matcher,
    axis_matches,
    normalize_code,
)
from .recordset import (
    EvaluationError,
    Recordset,
    UnsupportedError,
    iter_points,
    unique_points,
)
from .references import Reference, references, reported_templates, tables
from .values import Number, Value, ValueSet, compare, format_value

__all__ = [
    "AxisSelector",
    "CellQuery",
    "DataPoint",
    "DataProvider",
    "DpmXlSyntaxError",
    "Evaluation",
    "EvaluationError",
    "Evaluator",
    "Explanation",
    "Item",
    "MemoryProvider",
    "Node",
    "Number",
    "Operand",
    "Outcome",
    "Recordset",
    "Reference",
    "RuleResult",
    "SelectionCache",
    "SelectionSpec",
    "TableLayout",
    "UnsupportedError",
    "Value",
    "ValueSet",
    "__version__",
    "axis_matcher",
    "axis_matches",
    "compare",
    "evaluate_rule",
    "explain",
    "format_value",
    "iter_points",
    "normalize_code",
    "parse",
    "parse_cached",
    "parse_program",
    "parse_selection",
    "references",
    "reported_templates",
    "tables",
    "unique_points",
]
