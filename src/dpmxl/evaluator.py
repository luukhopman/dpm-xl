"""Evaluate DPM-XL expressions against a report's data provider.

[`evaluate_rule`][dpmxl.evaluator.evaluate_rule] evaluates a rule against a
[`DataProvider`][dpmxl.provider.DataProvider] and returns a
[`RuleResult`][dpmxl.evaluator.RuleResult]; it never raises for a bad rule or
bad data.

The evaluator implements every construct of the DPM-XL grammar; constructs
that need data beyond one report (``time_shift``, operation and table-group
references) use optional provider methods. It keeps every intermediate
record set so that a failing record can be explained operand by operand (see
[`dpmxl.explain`][dpmxl.explain]).

Semantics in brief:

* A selection yields one record per selected data point, keyed by varying
  closed axes and open key components. Missing facts take the selection's
  ``default`` (``null`` when none is written); a written default also stands
  in where another operand has a key the selection lacks.
* ``interval: true`` keeps each fact's decimals tolerance, so ``=`` holds when
  the intervals overlap; otherwise comparisons are exact.
* Null propagates through arithmetic and comparisons; ``and``/``or`` use
  three-valued (Kleene) logic. A null rule result is "not evaluated", never a
  failure.
* Aggregates over no records are null, except ``count``, which is 0.

## Threads

[`evaluate_rule`][dpmxl.evaluator.evaluate_rule] may run concurrently on one
report from several threads. [`parse_cached`][dpmxl.evaluator.parse_cached]
is thread-safe. A shared [`SelectionCache`][dpmxl.evaluator.SelectionCache] is
safe too, though two threads that miss the same selection at once may both
build it. Providers shared across threads must be safe to read concurrently;
[`MemoryProvider`][dpmxl.provider.MemoryProvider] is. An
[`Evaluator`][dpmxl.evaluator.Evaluator] instance is not meant to be shared:
create one per evaluation.

Examples:
    >>> from dpmxl import MemoryProvider, Number, TableLayout, evaluate_rule
    >>> provider = MemoryProvider(
    ...     [TableLayout("T", rows=("0010", "0020"), columns=("0010",))],
    ...     {
    ...         ("T", "0010", "0010", None, ()): Number.of(5, 0),
    ...         ("T", "0020", "0010", None, ()): Number.of(-2, 0),
    ...     },
    ... )
    >>> result = evaluate_rule("{tT, r*, c0010} >= 0", provider)
    >>> result.status, result.counts
    ('failed', {'passed': 1, 'failed': 1, 'null': 0})
    >>> [outcome.key for outcome in result.failures]
    [{'r': '0020'}]
"""

from __future__ import annotations

import calendar
import math
import re
from collections.abc import (
    Callable,
    Collection,
    Hashable,
    Iterable,
    Mapping,
    Sequence,
)
from contextlib import suppress
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta
from decimal import Decimal
from functools import lru_cache
from operator import attrgetter
from typing import Any, Literal, cast

from .ast import (
    AXIS_KEYS,
    Analytic,
    Assignment,
    Binary,
    Call,
    Get,
    If,
    In,
    Item,
    Literal_,
    Name,
    Node,
    Parameter,
    PersistentAssignment,
    Program,
    Rename,
    Selection,
    SelectionSpec,
    SetLiteral,
    Sub,
    TableReported,
    TypedParameter,
    Unary,
    Where,
    WindowBound,
    With,
    walk,
)
from .grammar import SIGNATURES
from .parser import _may_be_program, parse, parse_program
from .provider import (
    CellQuery,
    DataPoint,
    DataProvider,
    EarlierReport,
    axis_matcher,
    declared_open_keys,
    normalize_code,
)
from .recordset import (
    EvaluationError,
    Record,
    Recordset,
    UnsupportedError,
    combine,
    resolve_key,
    unique_points,
)
from .values import Number, Value, ValueSet, compare, type_name

AGGREGATES = frozenset({"sum", "count", "avg", "max", "min", "median"})
"""Canonical names of the aggregate functions (``Call.name`` values).

``rank`` and aggregates with ``over (...)`` are
[`Analytic`][dpmxl.ast.Analytic] nodes and are not listed."""
_COMPARISONS = frozenset({"=", "!=", "<", "<=", ">", ">="})
_ARITHMETIC = frozenset({"+", "-", "*", "/"})
_BOOLEAN = frozenset({"and", "or", "xor"})
_SET_FUNCTIONS = frozenset({"set_of", "union", "intersect", "setdiff", "symdiff"})
_UNSUPPORTED_FUNCTIONS = {
    "time_shift": (
        "The rule compares with the previous reporting period (time_shift), "
        "which a single report does not include"
    ),
}

# Marks records removed by filter(); never escapes the evaluator.
_FILTERED = cast(Value, object())


@dataclass(frozen=True, slots=True)
class _Failed:
    """The value of a record whose computation failed, such as ``x / 0``.

    A failure belongs to its record: it propagates through the operators
    that use the record and is dropped with it, as when an ``if`` takes the
    other branch for that record (``if {x} != 0 then {y} / {x} > 1 endif``).
    Only a failure that reaches the rule's result raises its error.
    """

    message: str


def _per_record(
    function: Callable[[list[Value]], Value],
) -> Callable[[list[Value]], Value]:
    """Apply a record function, keeping a failure to the record it occurs in.

    Returns:
        Callable[[list[Value]], Value]: The function, passing on a failed
        operand and turning an evaluation error into a failed value.
    """

    def apply(values: list[Value]) -> Value:
        for value in values:
            if type(value) is _Failed:
                return value
        try:
            return function(values)
        except UnsupportedError:
            raise
        except EvaluationError as error:
            return _failure(str(error))

    return apply


def _failure(message: str) -> Value:
    return cast(Value, _Failed(message))


def _unary_per_record(
    function: Callable[[Value], Value],
) -> Callable[[Value], Value]:
    single = _per_record(lambda values: function(values[0]))
    return lambda value: single([value])


def _checked(value: Value) -> Value:
    """Return a value that is used as a whole, raising a record's failure.

    Returns:
        Value: The value.

    Raises:
        EvaluationError: If the value's computation failed.
    """
    if type(value) is _Failed:
        raise EvaluationError(value.message)
    return value


Status = Literal["passed", "failed", "not_applicable", "error", "unsupported"]


@dataclass
class Evaluation:
    """Raw evaluation result with intermediate record sets for explanation.

    Pass it to [`explain`][dpmxl.explain.explain] (it is
    [`RuleResult.evaluation`][dpmxl.evaluator.RuleResult]).

    Attributes:
        root: The evaluated tree.
        result: The record set of the last statement.
        trace: Each node's record set by ``id(node)``; empty when evaluated
            with ``trace=False``.
        notes: Remarks gathered during evaluation.
    """

    root: Node
    result: Recordset
    trace: dict[int, Recordset] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    assignments: dict[str, Recordset] = field(default_factory=dict)
    """Results of persistent assignments (``{target} <- value``) by target,
    written as normalized DPM-XL such as ``{tT, r0010, c0010}`` or ``{vX}``."""
    shapes: dict[tuple[str, int], Any] = field(
        default_factory=dict, repr=False, compare=False
    )
    """What explanations derive from the tree alone (plain formulas, term
    counts), by kind and node id; shared by every failure explained."""

    def value_at(self, node: Node, binding: Mapping[str, Hashable]) -> list[Record]:
        """Return the records a node produced for a key binding.

        Returns:
            list[Record]: Matching records; empty when the node was not
            evaluated for that binding.
        """
        recordset = self.trace.get(id(node))
        return recordset.lookup(binding) if recordset is not None else []


class SelectionCache:
    """Selection results shared by every rule evaluated against one report.

    Rules over the same report select the same cells again and again (every
    sum rule on a table reads its columns); building each record set once
    makes large open tables affordable. Record sets are never mutated by the
    evaluator, so sharing them is safe. Use one cache per report. Rules may
    share it across threads: a selection two threads miss at once is built
    by both, and either result is kept.
    """

    def __init__(self) -> None:
        """Create an empty cache."""
        self.recordsets: dict[SelectionSpec, Recordset] = {}
        self.earlier: dict[tuple[str, int], SelectionCache] = {}
        """Caches of earlier reports for ``time_shift``, by period and count."""


class Evaluator:
    """Evaluates one expression tree against one provider.

    The engine behind [`evaluate_rule`][dpmxl.evaluator.evaluate_rule], which
    most callers want instead: ``Evaluator.run`` raises
    [`EvaluationError`][dpmxl.recordset.EvaluationError] where
    ``evaluate_rule`` returns status ``error``. Create one per evaluation;
    share a [`SelectionCache`][dpmxl.evaluator.SelectionCache] between them.
    """

    def __init__(
        self,
        provider: DataProvider,
        *,
        trace: bool = True,
        cache: SelectionCache | None = None,
        only_keys: Mapping[str, Collection[str]] | None = None,
    ) -> None:
        """Bind the provider.

        Args:
            provider: Report data access.
            trace: Keep intermediate record sets for explanations.
            cache: Selection results shared across rules of one report.
            only_keys: Closed-axis key (``r``, ``c``, ``s``) to the normalized
                codes whose records selections keep, applied once a
                selection's keys are decided; used to explain a few known
                failing records of a large selection.
        """
        self.provider = provider
        self.cache = cache
        self.only_keys = only_keys
        self.trace_enabled = trace
        self._trace: dict[int, Recordset] = {}
        self._notes: list[str] = []
        self._selection_cache: dict[tuple[object, ...], list[DataPoint]] = {}
        self._context_conditions: list[Node] = []
        # Whether the selection being evaluated has a where or sub clause of
        # its own, which overrides the context's where.
        self._overridden = False
        self._members: dict[int, list[Value]] = {}
        self._operations: list[str] = []
        self._temporaries: dict[str, Recordset] = {}
        self._assignments: dict[str, Recordset] = {}

    def run(self, node: Node) -> Evaluation:
        """Evaluate a complete expression or program.

        Returns:
            Evaluation: The result and its trace.

        Raises:
            EvaluationError: For a type error, an unknown table and the like;
                [`UnsupportedError`][dpmxl.recordset.UnsupportedError] when the
                provider cannot resolve a reference.
        """
        self._trace = {}
        self._notes = []
        self._temporaries = {}
        self._assignments = {}
        result = self.evaluate(node, SelectionSpec(), None)
        return Evaluation(
            node, result, self._trace, self._notes, assignments=self._assignments
        )

    def evaluate(
        self,
        node: Node,
        context: SelectionSpec,
        bindings: Mapping[str, Value] | None,
    ) -> Recordset:
        """Evaluate a node under a ``with`` context and optional key bindings.

        Returns:
            Recordset: The node's records.
        """
        result = self._evaluate(node, context, bindings)
        if self.trace_enabled and bindings is None:
            self._trace[id(node)] = result
        return result

    def _evaluate(
        self,
        node: Node,
        context: SelectionSpec,
        bindings: Mapping[str, Value] | None,
    ) -> Recordset:
        match node:
            case With(context=inner, body=body, condition=condition):
                if condition is not None:
                    self._context_conditions.append(condition)
                try:
                    return self.evaluate(body, inner.merged_into(context), bindings)
                finally:
                    if condition is not None:
                        self._context_conditions.pop()
            case Literal_():
                return Recordset.scalar(_literal_value(node))
            case Selection(spec=spec):
                merged = spec.merged_into(context)
                if merged.table_group is None and merged.operation is None:
                    selected = self._selection(merged)
                else:
                    selected = self._indirect(merged)
                if self._overridden:
                    return selected
                for condition in self._context_conditions:
                    kept = _context_condition(condition, selected.keys, self._known)
                    if kept is not None:
                        selected = self._where(selected, kept, context)
                return selected
            case TableReported(table=table):
                return Recordset.scalar(self.provider.table_reported(table))
            case TypedParameter():
                return Recordset.scalar(self._typed_parameter(node))
            case Parameter(name=name):
                value = self.provider.parameter(name)
                if value is None:
                    self._notes.append(f"report parameter {name!r} is not available")
                return Recordset.scalar(value)
            case Name(name=name):
                if bindings is not None:
                    key = resolve_key(name, bindings)
                    if key is not None:
                        return Recordset.scalar(bindings[key])
                temporary = self._temporaries.get(name.casefold())
                if temporary is not None:
                    return temporary
                value = self.provider.parameter(name)
                if value is not None:
                    return Recordset.scalar(value)
                raise EvaluationError(f"unknown key component or parameter {name!r}")
            case Unary(op=op, operand=operand):
                return self.evaluate(operand, context, bindings).map(
                    _unary_per_record(_unary(op))
                )
            case Binary():
                return self._chain(node, context, bindings)
            case In(operand=operand, values=values) if not isinstance(
                values, SetLiteral
            ):
                found = self._as_set(self.evaluate(values, context, bindings), "in")
                return self.evaluate(operand, context, bindings).map(
                    _unary_per_record(
                        lambda value: (
                            None if found is None else _membership(value, found.members)
                        )
                    )
                )
            case In(operand=operand, values=SetLiteral() as values):
                members = self._members.get(id(values))
                if members is None:
                    members = [
                        self._set_member(item, context, bindings)
                        for item in values.items
                    ]
                    if not _key_names(values):
                        # Constant members, as nearly always: once, not once
                        # per record of a where clause.
                        self._members[id(values)] = members
                return self.evaluate(operand, context, bindings).map(
                    _unary_per_record(lambda value: _membership(value, members))
                )
            case SetLiteral(items=items):
                return Recordset.scalar(
                    _value_set(
                        self._set_member(item, context, bindings) for item in items
                    )
                )
            case If(condition=condition, then=then, otherwise=otherwise):
                verdicts = self.evaluate(condition, context, bindings)
                outcome = self.evaluate(then, context, bindings)
                return conditional(
                    verdicts,
                    outcome,
                    self.evaluate(otherwise, context, bindings)
                    if otherwise is not None
                    else None,
                )
            case Call():
                return self._call(node, context, bindings)
            case Analytic(operand=operand):
                return _analytic(node, self.evaluate(operand, context, bindings))
            case Where(operand=operand, condition=condition):
                return self._where(
                    self._clause_operand(operand, context, bindings),
                    condition,
                    context,
                )
            case Get(operand=operand, name=name):
                return self._get(self.evaluate(operand, context, bindings), name)
            case Sub(operand=operand, name=name, value=value):
                fixed = self.evaluate(value, context, bindings).single()
                return self._sub(
                    self._clause_operand(operand, context, bindings),
                    name,
                    _checked(fixed.value) if fixed else None,
                )
            case Rename(operand=operand, pairs=pairs):
                return self._rename(self.evaluate(operand, context, bindings), pairs)
            case Program(statements=statements):
                result = Recordset(())
                for statement in statements:
                    result = self.evaluate(statement, context, bindings)
                return result
            case Assignment(name=name, value=value):
                result = self.evaluate(value, context, bindings)
                # Names ignore case (DPM-XL 2.4.1).
                self._temporaries[name.casefold()] = result
                return result
            case PersistentAssignment(target=target, value=value):
                result = self.evaluate(value, context, bindings)
                self._assignments[_target_text(target)] = result
                return result
        raise UnsupportedError(f"unsupported expression node {type(node).__name__}")

    def _chain(
        self,
        node: Binary,
        context: SelectionSpec,
        bindings: Mapping[str, Value] | None,
    ) -> Recordset:
        # Sums of hundreds of cells and long or-chains parse as left-deep
        # trees: evaluate the left spine in a loop, not one recursion per
        # operator.
        spine = [node]
        while isinstance(spine[-1].left, Binary):
            spine.append(spine[-1].left)
        result = self.evaluate(spine[-1].left, context, bindings)
        for current in reversed(spine):
            right = self.evaluate(current.right, context, bindings)
            result = combine([result, right], _binary(current.op))
            if current is not node and self.trace_enabled and bindings is None:
                self._trace[id(current)] = result
        return result

    def _known(self, name: str) -> bool:
        """Tell whether a name resolves without a key.

        Returns:
            bool: True for a temporary or a report parameter.
        """
        return (
            name.casefold() in self._temporaries
            or self.provider.parameter(name) is not None
        )

    def _clause_operand(
        self,
        operand: Node,
        context: SelectionSpec,
        bindings: Mapping[str, Value] | None,
    ) -> Recordset:
        # DPM-XL 3.2.6: a where or sub clause on a selection fully overrides
        # the with-level where, whichever keys either names.
        saved = self._overridden
        self._overridden = isinstance(operand, Selection | Where | Sub)
        try:
            return self.evaluate(operand, context, bindings)
        finally:
            self._overridden = saved

    # Selections ---------------------------------------------------------

    def _selection(self, spec: SelectionSpec) -> Recordset:
        if not spec.table:
            raise EvaluationError(f"selection {spec.text()} has no table")
        # Restricted selections are partial and must not be shared.
        if self.cache is not None and not self.only_keys:
            cached = self.cache.recordsets.get(spec)
            if cached is None:
                cached = self._build_selection(spec)
                self.cache.recordsets[spec] = cached
            return cached
        return self._build_selection(spec)

    def _build_selection(self, spec: SelectionSpec) -> Recordset:
        assert spec.table is not None
        cache_key = (spec.table, spec.rows, spec.columns, spec.sheets)
        points = self._selection_cache.get(cache_key)
        if points is None:
            try:
                points = list(
                    self.provider.select(
                        CellQuery(spec.table, spec.rows, spec.columns, spec.sheets)
                    )
                )
            except LookupError as error:
                raise EvaluationError(str(error)) from error
            self._selection_cache[cache_key] = points
        axis_keys: list[str] = []
        for key in AXIS_KEYS.values():
            # DPM-XL 3.1.6: r, c and s are keys only when more than one row,
            # column or sheet is present in the selection.
            codes = set(map(_COORDINATES[key], points))
            codes.discard("*")
            codes.discard(None)
            if len(codes) > 1:
                axis_keys.append(key)
        coordinates = [_COORDINATES[key] for key in axis_keys]
        # An open table with no reported rows still has its key structure.
        open_keys = list(declared_open_keys(self.provider, spec.table))
        for point in points:
            if point.keys:
                for name in point.keys:
                    if name not in open_keys:
                        open_keys.append(name)
        keys = (*axis_keys, *open_keys)
        if isinstance(spec.default, SetLiteral):
            raise EvaluationError("a set default applies only to set parameters")
        default = (
            _literal_value(spec.default) if isinstance(spec.default, Literal_) else None
        )
        interval = bool(spec.interval)
        # A default also stands for the records of keys another operand has
        # (see recordset.combine).
        result = Recordset(
            keys,
            default=Record(default) if isinstance(spec.default, Literal_) else None,
        )
        kept = [
            (position, self.only_keys[name])
            for position, name in enumerate(axis_keys)
            if self.only_keys and name in self.only_keys
        ]
        for point in points:
            if kept and any(
                normalize_code(coordinates[position](point) or "") not in allowed
                for position, allowed in kept
            ):
                continue
            value = point.value
            if value is None:
                value = default
            elif isinstance(value, Number) and not interval:
                value = value.exact()
            parts: list[Hashable] = [
                normalize_code(coordinate(point) or "") for coordinate in coordinates
            ]
            if open_keys:
                values = point.keys
                parts += [_key_value(values.get(name)) for name in open_keys]
            key = tuple(parts)
            existing = result.records.get(key)
            if existing is not None and existing.value is not None and value is None:
                continue
            result.records[key] = Record(value, (point,))
        return result

    def _indirect(self, spec: SelectionSpec) -> Recordset:
        """Select from a table group or another operation's result.

        Returns:
            Recordset: The records.

        Raises:
            UnsupportedError: If the provider cannot resolve the reference.
            EvaluationError: For tables of a group with different keys.
        """
        if spec.operation is not None:
            # DPM-XL 3.1.6: an operation of the same script, from a := assignment,
            # comes first.
            temporary = self._temporaries.get(spec.operation.casefold())
            if temporary is not None:
                return _restrict(temporary, spec)
            return _restrict(self._operation(spec.operation), spec)
        code = cast(str, spec.table_group)
        method = getattr(self.provider, "table_group", None)
        tables = method(code) if callable(method) else None
        if not tables:
            raise UnsupportedError(
                f"table group {code} needs a provider that resolves table groups"
            )
        parts = [
            (table, self._selection(replace(spec, table=table, table_group=None)))
            for table in tables
        ]
        if len(parts) == 1:
            return parts[0][1]
        keys = parts[0][1].keys
        if any(part.keys != keys for _, part in parts):
            raise EvaluationError(f"the tables of group {code} have different keys")
        result = Recordset(("t", *keys))
        for table, part in parts:
            for key, record in part.records.items():
                result.records[table, *key] = record
        return result

    def _operation(self, code: str) -> Recordset:
        method = getattr(self.provider, "operation", None)
        expression = method(code) if callable(method) else None
        if expression is None:
            raise UnsupportedError(
                f"operation {code} needs a provider that resolves operations"
            )
        if code in self._operations:
            raise EvaluationError(f"operation {code} refers to itself")
        node = _parse_cached(expression) if isinstance(expression, str) else expression
        # An operation is evaluated on its own: the caller's context,
        # temporaries and assignments neither reach it nor receive its own.
        saved = (
            self._context_conditions,
            self._overridden,
            self._temporaries,
            self._assignments,
        )
        self._operations.append(code)
        self._context_conditions, self._overridden = [], False
        self._temporaries, self._assignments = {}, {}
        try:
            return self.evaluate(node, SelectionSpec(), None)
        finally:
            self._operations.pop()
            (
                self._context_conditions,
                self._overridden,
                self._temporaries,
                self._assignments,
            ) = saved

    def _typed_parameter(self, node: TypedParameter) -> Value:
        value = self.provider.parameter(node.name)
        if value is None:
            default = node.default
            if isinstance(default, Literal_):
                value = _literal_value(default)
            elif isinstance(default, SetLiteral):
                value = self.evaluate(default, SelectionSpec(), None).records[()].value
            else:
                self._notes.append(f"report parameter {node.name!r} is not available")
                return None
        return _parameter_value(node.name, node.type, value)

    # Calls ---------------------------------------------------------------

    def _call(
        self,
        node: Call,
        context: SelectionSpec,
        bindings: Mapping[str, Value] | None,
    ) -> Recordset:
        name = node.name
        _check_call(node)
        if name == "time_shift":
            return self._time_shift(node, context, bindings)
        if name == "annualise":
            return self._annualise(node, context, bindings)
        if name in _SET_FUNCTIONS:
            return self._set_function(node, context, bindings)
        if name in AGGREGATES and len(node.args) == 1:
            operand = self.evaluate(node.args[0], context, bindings)
            return _aggregate(name, operand, node.group_by)
        if node.group_by is not None:
            raise EvaluationError(f"group by is not allowed in {name}")
        if name == "filter":
            data = self.evaluate(node.args[0], context, bindings)
            condition = self.evaluate(node.args[1], context, bindings)
            joined = combine(
                [condition, data],
                lambda values: (
                    values[1]
                    if values[0] is True
                    else values[0]
                    if type(values[0]) is _Failed
                    else _FILTERED
                ),
            )
            return Recordset(
                joined.keys,
                {
                    key: record
                    for key, record in joined.records.items()
                    if record.value is not _FILTERED
                },
                data.default,
            )
        args = [self.evaluate(arg, context, bindings) for arg in node.args]
        implementation = _SCALAR_FUNCTIONS.get(name)
        if implementation is None:
            raise UnsupportedError(f"unknown function {name!r}")
        return combine(args, _per_record(implementation))

    def _time_shift(
        self,
        node: Call,
        context: SelectionSpec,
        bindings: Mapping[str, Value] | None,
    ) -> Recordset:
        operand, period_node, count_node = node.args[:3]
        period = _period(period_node)
        count = self._integer_operand(count_node, "time_shift", context, bindings)
        key = cast(Name, node.args[3]) if len(node.args) == 4 else None
        if key is not None:
            # A trial on this report: its trace is kept only if the key turns
            # out to be one of the operand's, so that explanations of the
            # other case show the earlier report's values.
            saved, self._trace = self._trace, {}
            try:
                current = self.evaluate(operand, context, bindings)
            except EvaluationError:
                current = None
            trial, self._trace = self._trace, saved
            found = resolve_key(key.name, current.keys) if current else None
            if current is not None and found is not None:
                self._trace.update(trial)
                return _shift_key(current, found, period, count)
        method = getattr(self.provider, "earlier_report", None)
        if not callable(method):
            raise UnsupportedError(_UNSUPPORTED_FUNCTIONS["time_shift"])
        earlier = method(period, count)
        if earlier is None:
            raise UnsupportedError(
                f"time_shift needs the report {count} {_PERIOD_NAMES[period]} "
                "earlier, which the provider does not have"
            )
        cache = None
        if self.cache is not None:
            cache = self.cache.earlier.setdefault((period, count), SelectionCache())
        inner = Evaluator(
            EarlierReport(earlier, period, count),
            trace=self.trace_enabled,
            cache=cache,
            only_keys=self.only_keys,
        )
        inner._context_conditions = list(self._context_conditions)
        inner._overridden = self._overridden
        inner._temporaries = dict(self._temporaries)
        inner._operations = list(self._operations)
        result = inner.evaluate(operand, context, bindings)
        self._trace.update(inner._trace)
        self._notes.extend(inner._notes)
        return result

    def _annualise(
        self,
        node: Call,
        context: SelectionSpec,
        bindings: Mapping[str, Value] | None,
    ) -> Recordset:
        operand, end_node, key = node.args
        assert isinstance(key, Name)
        fiscal_end = self._integer_operand(end_node, "annualise", context, bindings)
        if not 1 <= fiscal_end <= 12:
            raise EvaluationError("annualise needs a fiscal year end month of 1 to 12")
        data = self.evaluate(operand, context, bindings)
        found = resolve_key(key.name, data.keys)
        if found is None:
            reference = self.provider.parameter(key.name)
            if not isinstance(reference, date):
                raise EvaluationError(
                    f"annualise needs a date key or report parameter {key.name!r}"
                )
            return data.map(
                _unary_per_record(
                    lambda value: _annualised(value, reference, fiscal_end)
                )
            )
        position = data.keys.index(found)
        per_record = _per_record(
            lambda values: _annualised(values[0], values[1], fiscal_end)
        )
        return Recordset(
            data.keys,
            {
                record_key: Record(
                    per_record([record.value, _value_of_key(record_key[position])]),
                    record.points,
                )
                for record_key, record in data.records.items()
            },
        )

    def _integer_operand(
        self,
        node: Node,
        name: str,
        context: SelectionSpec,
        bindings: Mapping[str, Value] | None,
    ) -> int:
        record = self.evaluate(node, context, bindings).single()
        if record is None or record.value is None:
            raise EvaluationError(f"{name} needs a whole number, found null")
        return _integer(_checked(record.value), name)

    def _set_function(
        self,
        node: Call,
        context: SelectionSpec,
        bindings: Mapping[str, Value] | None,
    ) -> Recordset:
        name = node.name
        operands = [self.evaluate(arg, context, bindings) for arg in node.args]
        found = [self._as_set(operand, name) for operand in operands]
        points = unique_points(
            record.points for operand in operands for record in operand.records.values()
        )
        if name == "set_of":
            return Recordset.scalar(found[0] or ValueSet(), points)
        sets = [item for item in found if item is not None]
        if len(sets) != len(found):
            # A null set, such as a missing set parameter, makes the result null.
            return Recordset.scalar(None, points)
        first = sets[0]
        if name == "union":
            result = _value_set(member for found in sets for member in found.members)
        elif name == "intersect":
            result = ValueSet(
                tuple(
                    member
                    for member in first.members
                    if all(member in other for other in sets[1:])
                )
            )
        elif name == "setdiff":
            result = ValueSet(
                tuple(member for member in first.members if member not in sets[1])
            )
        else:
            result = ValueSet(
                tuple(member for member in first.members if member not in sets[1])
                + tuple(member for member in sets[1].members if member not in first)
            )
        return Recordset.scalar(result, points)

    @staticmethod
    def _as_set(data: Recordset, name: str) -> ValueSet | None:
        """Read an operand as a set: a set value, or the set of its values.

        Returns:
            ValueSet | None: The set, with null values left out; ``None`` for
            a single null value, such as a set parameter that is missing.

        Raises:
            EvaluationError: If a value failed or is itself a set.
        """
        values = [_checked(record.value) for record in data.records.values()]
        if not data.keys and len(values) == 1:
            if isinstance(values[0], ValueSet):
                return values[0]
            if values[0] is None:
                return None
        try:
            return ValueSet.of(values)
        except TypeError as error:
            raise EvaluationError(f"{name}: {error}") from error

    # Clauses ------------------------------------------------------------

    def _where(
        self, data: Recordset, condition: Node, context: SelectionSpec
    ) -> Recordset:
        # The default still stands in for the keys other operands have.
        result = Recordset(data.keys, default=data.default)
        # The verdict depends only on the keys the condition names, and many
        # records share them (qEBB has a few values over thousands of rows),
        # and on the fact f (DPM-XL 11.1.5) when the condition names it.
        names = _key_names(condition)
        named = {resolve_key(name, data.keys) for name in names}
        positions = [index for index, name in enumerate(data.keys) if name in named]
        fact = any(_is_fact(name, data.keys) for name in names)
        verdicts: dict[tuple[Hashable, ...], bool] = {}
        for key, record in data.records.items():
            if fact and type(record.value) is _Failed:
                result.records[key] = record
                continue
            part = tuple([key[position] for position in positions])
            if fact:
                part += (record.value,)
            kept = verdicts.get(part)
            if kept is None:
                bindings = {
                    name: _value_of_key(value)
                    for name, value in zip(data.keys, key, strict=True)
                }
                if fact:
                    bindings[FACT] = record.value
                verdict = self.evaluate(condition, context, bindings).single()
                kept = verdicts[part] = (
                    verdict is not None and _checked(verdict.value) is True
                )
            if kept:
                result.records[key] = record
        return result

    def _get(self, data: Recordset, name: str) -> Recordset:
        key = resolve_key(name, data.keys)
        if key is None:
            value = self.provider.parameter(name)
            if value is None:
                raise EvaluationError(f"unknown key component or parameter {name!r}")
            mapped = data.map(lambda _value: value)
            return Recordset(mapped.keys, mapped.records)
        position = data.keys.index(key)
        # DPM-XL 11.3.6: records with a null fact value are omitted.
        return Recordset(
            data.keys,
            {
                record_key: Record(
                    record.value
                    if type(record.value) is _Failed
                    else _value_of_key(record_key[position]),
                    record.points,
                )
                for record_key, record in data.records.items()
                if record.value is not None
            },
        )

    def _sub(self, data: Recordset, name: str, value: Value) -> Recordset:
        key = resolve_key(name, data.keys)
        if key is None:
            raise EvaluationError(f"unknown key component {name!r}")
        position = data.keys.index(key)
        keys = data.keys[:position] + data.keys[position + 1 :]
        result = Recordset(keys, default=data.default)
        for record_key, record in data.records.items():
            try:
                equal = compare("=", _value_of_key(record_key[position]), value)
            except TypeError as error:
                raise EvaluationError(str(error)) from error
            if equal is True:
                result.records[record_key[:position] + record_key[position + 1 :]] = (
                    record
                )
        return result

    def _rename(self, data: Recordset, pairs: tuple[tuple[str, str], ...]) -> Recordset:
        keys = list(data.keys)
        for old, new in pairs:
            key = resolve_key(old, keys)
            if key is None:
                raise EvaluationError(f"unknown key component {old!r}")
            _check_rename(new, [name for name in keys if name != key])
            keys[keys.index(key)] = new
        return Recordset(tuple(keys), dict(data.records), data.default)

    def _set_member(
        self,
        node: Node,
        context: SelectionSpec,
        bindings: Mapping[str, Value] | None,
    ) -> Value:
        record = self.evaluate(node, context, bindings).single()
        return _checked(record.value) if record else None


_PERIOD_MONTHS = {"A": 12, "S": 6, "Q": 3, "M": 1}
_PERIOD_DAYS = {"W": 7, "D": 1}
_PERIOD_NAMES = {
    "A": "year(s)",
    "S": "semester(s)",
    "Q": "quarter(s)",
    "M": "month(s)",
    "W": "week(s)",
    "D": "day(s)",
}


def _period(node: Node) -> str:
    if isinstance(node, Name) and node.name in _PERIOD_NAMES:
        return node.name
    raise EvaluationError("time_shift needs a period of A, S, Q, M, W or D")


def _shift_date(value: date, period: str, count: int) -> date:
    """Move a date ``count`` periods later (earlier when negative).

    Years, semesters, quarters and months move by calendar months: the day
    is kept, limited to the target month's length, and a month's last day
    stays the last day (``2026-02-28`` plus one quarter is ``2026-05-31``).
    Weeks and days move by 7 and 1 days.

    Returns:
        date: The shifted date (a ``datetime`` stays one).

    Raises:
        EvaluationError: If the result falls outside the years 1 to 9999.
    """
    try:
        if period in _PERIOD_DAYS:
            return value + timedelta(days=_PERIOD_DAYS[period] * count)
        months = value.year * 12 + value.month - 1 + _PERIOD_MONTHS[period] * count
        year, month = divmod(months, 12)
        last = calendar.monthrange(year, month + 1)[1]
        month_end = value.day == calendar.monthrange(value.year, value.month)[1]
        return value.replace(
            year=year,
            month=month + 1,
            day=last if month_end else min(value.day, last),
        )
    except (ValueError, OverflowError) as error:
        raise EvaluationError(
            f"shifting {value.isoformat()} by {count} {_PERIOD_NAMES[period]} "
            "leaves the years 1 to 9999"
        ) from error


def _shift_key(data: Recordset, key: str, period: str, count: int) -> Recordset:
    position = data.keys.index(key)
    result = Recordset(data.keys, default=data.default)
    for record_key, record in data.records.items():
        moment = record_key[position]
        if not isinstance(moment, date):
            found = type_name(_value_of_key(moment))
            raise EvaluationError(f"time_shift needs dates in key {key}, found {found}")
        shifted = _shift_date(moment, period, count)
        moved = (*record_key[:position], shifted, *record_key[position + 1 :])
        if moved in result.records:
            raise EvaluationError(
                f"time_shift moves several {key} dates to {shifted.isoformat()}"
            )
        result.records[moved] = record
    return result


def _annualised(value: Value, reference: Value, fiscal_end: int) -> Value:
    if value is None or reference is None:
        return None
    number = _require_number(value, "annualise")
    if not isinstance(reference, date):
        raise EvaluationError(f"annualise needs a date, found {type_name(reference)}")
    months = (reference.month - fiscal_end - 1) % 12 + 1
    return number * Number(Decimal(12)) / Number(Decimal(months))


def _analytic(node: Analytic, data: Recordset) -> Recordset:
    """Evaluate ``rank`` or an aggregate over an analytic window.

    Returns:
        Recordset: One record per operand record, with the same keys.

    Raises:
        EvaluationError: For a key the operand lacks or an invalid window.
    """
    width = len(data.keys)

    def position(name: str) -> int:
        # The fact f (DPM-XL 7.8.7) follows the keys in each member's key.
        if _is_fact(name, data.keys):
            return width
        key = resolve_key(name, data.keys)
        if key is None:
            raise EvaluationError(
                f"{node.name} over {name!r}, which is not a key of the operand "
                f"({', '.join(data.keys) or 'no keys'})"
            )
        return data.keys.index(key)

    partition = [position(name) for name in node.partition_by]
    order = [(position(name), descending) for name, descending in node.order_by]
    groups: dict[tuple[Hashable, ...], list[tuple[tuple[Hashable, ...], Record]]] = {}
    for key, record in data.records.items():
        extended = (*key, _key_value(record.value))
        groups.setdefault(tuple([extended[index] for index in partition]), []).append(
            (extended, record)
        )
    result = Recordset(data.keys)
    reduce = _per_record(lambda values: _reduce(node.name, values, len(values)))
    for members in groups.values():
        for index, descending in reversed(order):
            members.sort(
                key=lambda item: _sort_value(item[0][index]), reverse=descending
            )
            # Null order values sort last either way (DPM-XL 7.8.4).
            members.sort(key=lambda item: item[0][index] is None)
        ranks = _order_values(members, order)
        if node.name == "rank":
            first: dict[tuple[Any, ...], int] = {}
            for number, rank_key in enumerate(ranks, start=1):
                first.setdefault(rank_key, number)
            for (key, record), rank_key in zip(members, ranks, strict=True):
                result.records[key[:width]] = Record(
                    Number(Decimal(first[rank_key])), record.points
                )
            continue
        for current, (key, _record) in enumerate(members):
            low, high = _window_span(node, members, ranks, order, current)
            window = members[low:high]
            values: list[Value] = [
                item.value for _, item in window if item.value is not None
            ]
            result.records[key[:width]] = Record(
                reduce(values), tuple(item.points for _, item in window)
            )
    return result


def _sort_value(value: Hashable) -> tuple[int, Any]:
    """Order key values of mixed types by type and value.

    Returns:
        tuple[int, Any]: A sort key.
    """
    if value is None:
        return (0, 0)
    if isinstance(value, bool):
        return (1, int(value))
    if isinstance(value, Decimal):
        return (2, value)
    if isinstance(value, date):
        return (3, _moment(value))
    return (4, str(value))


def _moment(value: date) -> datetime:
    if isinstance(value, datetime):
        return value
    return datetime(value.year, value.month, value.day)


def _order_values(
    members: list[tuple[tuple[Hashable, ...], Record]], order: list[tuple[int, bool]]
) -> list[tuple[Any, ...]]:
    return [tuple(_sort_value(key[index]) for index, _ in order) for key, _ in members]


def _window_span(
    node: Analytic,
    members: list[tuple[tuple[Hashable, ...], Record]],
    ranks: list[tuple[Any, ...]],
    order: list[tuple[int, bool]],
    current: int,
) -> tuple[int, int]:
    """Return the half-open range of sorted members in a record's window.

    Without a window clause the window is the whole partition, whatever the
    ``order by`` (DPM-XL 7.1.8.4).

    Returns:
        tuple[int, int]: Start and end positions.

    Raises:
        EvaluationError: For a ``range`` window that is not over one number
            or date key.
    """
    count = len(members)
    window = node.window
    if window is None:
        return 0, count
    if window.unit == "data points":
        low = _row_bound(window.start, current, count)
        high = _row_bound(window.end, current, count) + 1
        return max(low, 0), max(min(high, count), max(low, 0))
    if not order:
        return 0, count
    if len(order) != 1 and (
        window.start.kind in {"preceding", "following"}
        or window.end.kind in {"preceding", "following"}
    ):
        raise EvaluationError("a range window with offsets needs one order key")
    index, descending = order[0]
    value = members[current][0][index]
    bounds = []
    for bound, start in ((window.start, True), (window.end, False)):
        # A null order value has no offset: its window is its null peers.
        if bound.kind == "current data point" or (
            value is None and bound.kind in {"preceding", "following"}
        ):
            bounds.append(_peer_bound(ranks, current, start=start))
        else:
            bounds.append(
                _range_bound(bound, value, descending, members, index, start=start)
            )
    low, high = bounds
    return low, max(high, low)


def _peer_bound(ranks: list[tuple[Any, ...]], current: int, *, start: bool) -> int:
    """Return where the current member's peers start, or end (exclusive).

    Returns:
        int: A position among the sorted members.
    """
    position = current
    if start:
        while position > 0 and ranks[position - 1] == ranks[current]:
            position -= 1
        return position
    while position + 1 < len(ranks) and ranks[position + 1] == ranks[current]:
        position += 1
    return position + 1


def _row_bound(bound: WindowBound, current: int, count: int) -> int:
    match bound.kind:
        case "unbounded preceding":
            return 0
        case "unbounded following":
            return count - 1
        case "preceding":
            return current - bound.offset
        case "following":
            return current + bound.offset
    return current


def _range_bound(
    bound: WindowBound,
    value: Hashable,
    descending: bool,
    members: list[tuple[tuple[Hashable, ...], Record]],
    index: int,
    *,
    start: bool,
) -> int:
    """Find a range window bound among members sorted on one key.

    Returns:
        int: The first member inside the window (``start``) or the first
        after it.

    Raises:
        EvaluationError: For an offset over a key that is not a number or
            date.
    """
    count = len(members)
    if bound.kind == "unbounded preceding":
        return 0
    if bound.kind == "unbounded following":
        return count
    offset = bound.offset if bound.kind == "following" else -bound.offset
    if descending:
        offset = -offset
    if isinstance(value, date):
        # Without a period, an offset over dates counts days.
        target: Hashable = _shift_date(value, bound.period or "D", offset)
    elif isinstance(value, Decimal):
        if bound.period is not None:
            raise EvaluationError("a range window period needs a date order key")
        target = value + offset
    else:
        raise EvaluationError("a range window offset needs a number or date order key")
    goal = _sort_value(target)
    # Members are sorted ascending on the key, or descending, with nulls last.
    positions = range(sum(1 for member in members if member[0][index] is not None))
    if start:
        for position in positions:
            found = _sort_value(members[position][0][index])
            if (found >= goal) if not descending else (found <= goal):
                return position
        return len(positions)
    for position in reversed(positions):
        found = _sort_value(members[position][0][index])
        if (found <= goal) if not descending else (found >= goal):
            return position + 1
    return 0


def _target_text(target: Node) -> str:
    if isinstance(target, Selection):
        return target.spec.text()
    if isinstance(target, Parameter):
        return f"{{v{target.name}}}"
    raise EvaluationError("assignment target must be a selection")


def _restrict(data: Recordset, spec: SelectionSpec) -> Recordset:
    """Apply a selection's axes and options to an operation's result.

    Returns:
        Recordset: The records whose ``r``, ``c`` and ``s`` keys match the
        selected coordinates; an axis selecting one coordinate is no longer a
        key. ``default`` fills null values and missing keys (see
        [`Recordset`][dpmxl.recordset.Recordset]) and ``interval: false``
        makes numbers exact.

    Raises:
        EvaluationError: If the result lacks a selected axis key.
    """
    result = data
    for key, selector in (("r", spec.rows), ("c", spec.columns), ("s", spec.sheets)):
        if selector is None or selector.wildcard:
            continue
        if key not in result.keys:
            raise EvaluationError(
                f"operation {spec.operation} has no {key} key to select"
            )
        position = result.keys.index(key)
        matches = axis_matcher(selector)
        single = selector.is_single
        kept = Recordset(
            result.keys[:position] + result.keys[position + 1 :]
            if single
            else result.keys
        )
        for record_key, record in result.records.items():
            code = record_key[position]
            if matches(code if isinstance(code, str) else str(code)):
                if single:
                    record_key = record_key[:position] + record_key[position + 1 :]
                kept.records[record_key] = record
        result = kept
    default = (
        _literal_value(spec.default) if isinstance(spec.default, Literal_) else None
    )
    if default is not None or spec.interval is False:
        exact = spec.interval is False

        def fill(value: Value) -> Value:
            if value is None:
                return default
            if exact and isinstance(value, Number):
                return value.exact()
            return value

        result = result.map(fill)
    if isinstance(spec.default, Literal_):
        result = Recordset(result.keys, result.records, Record(default))
    return result


def _parameter_value(name: str, kind: str, value: Value) -> Value:
    """Check a parameter value against its declared type.

    Returns:
        Value: The value; integers, decimals and floats become numbers,
        text becomes an item or date for those types, and a Python
        collection becomes a set.

    Raises:
        EvaluationError: If the value does not have the type.
    """
    if kind.startswith("set-"):
        members: Any = value
        if isinstance(value, ValueSet):
            members = value.members
        elif not isinstance(value, list | tuple | set | frozenset):
            raise EvaluationError(f"parameter {name} is not a set")
        return _value_set(
            _parameter_value(name, kind[4:], member) for member in members
        )
    found: Any = value
    if kind in {"number", "integer"}:
        if isinstance(found, int | float | Decimal) and not isinstance(found, bool):
            found = Number(Decimal(str(found)))
        if (
            not isinstance(found, Number)
            or not found.value.is_finite()
            or (kind == "integer" and found.value != found.value.to_integral_value())
        ):
            raise EvaluationError(f"parameter {name} is not {_ARTICLES[kind]}")
        return found
    if kind == "item" and isinstance(found, str):
        found = Item.parse(found)
    if kind == "date" and isinstance(found, str):
        with suppress(ValueError):
            found = date.fromisoformat(found)
    expected = {"string": str, "boolean": bool, "item": Item, "date": date}[kind]
    if not isinstance(found, expected):
        raise EvaluationError(f"parameter {name} is not {_ARTICLES[kind]}")
    return found


_ARTICLES = {
    "number": "a number",
    "integer": "an integer",
    "string": "text",
    "boolean": "a Boolean",
    "item": "an item",
    "date": "a date",
}


def _context_condition(
    condition: Node,
    keys: tuple[str, ...],
    known: Callable[[str], bool] = lambda _name: False,
) -> Node | None:
    """Return the part of a ``with`` where that applies to a selection.

    The context's where concerns the selections that have the keys it names:
    the condition's ``and`` terms naming a key the selection lacks (a name
    that is neither one of its keys, the fact ``f`` nor ``known``) are left
    out. A term on the fact alone applies to every selection (DPM-XL 3.2.5).

    Args:
        condition: The ``with`` context's where condition.
        keys: The selection's keys, which the names resolve against.
        known: Whether a name other than a key resolves, such as a report
            parameter.

    Returns:
        Node | None: The condition to apply, or ``None`` for none.
    """

    def applies(term: Node) -> bool:
        return all(
            resolve_key(name, keys) is not None or _is_fact(name, keys) or known(name)
            for name in _key_names(term)
        )

    if applies(condition):
        return condition
    terms: list[Node] = []
    pending = [condition]
    while pending:
        current = pending.pop()
        if isinstance(current, Binary) and current.op == "and":
            pending += [current.right, current.left]
        elif applies(current):
            terms.append(current)
    if not terms:
        return None
    kept = terms[0]
    for term in terms[1:]:
        kept = Binary("and", kept, term, span=(kept.span[0], term.span[1]))
    return kept


def _check_rename(new: str, others: Sequence[str]) -> None:
    """Refuse a rename to a key component the record set already has.

    Raises:
        EvaluationError: If ``new`` names one of ``others``.
    """
    clash = resolve_key(new, others) or next(
        (name for name in others if name.casefold() == new.casefold()), None
    )
    if clash is not None:
        raise EvaluationError(f"rename: key component {clash} already exists")


FACT = "f"
"""The name of a record's value in a ``where`` condition (DPM-XL 2.2.3)."""


def _is_fact(name: str, keys: Sequence[str]) -> bool:
    """Tell whether a name in a clause is the fact ``f`` rather than a key.

    Returns:
        bool: True for ``f`` (any case) unless the operand has a key ``f``.
    """
    return name.casefold() == FACT and FACT not in keys


def _key_names(node: Node) -> tuple[str, ...]:
    return tuple(current.name for current in walk(node) if isinstance(current, Name))


# Value helpers -------------------------------------------------------------


def _literal_value(node: Literal_) -> Value:
    if node.kind == "number":
        assert isinstance(node.value, Decimal)
        return Number(node.value)
    return cast(Value, node.value)


# A data point's closed coordinate by axis key, as DataPoint.coordinate.
_COORDINATES = {
    "r": attrgetter("row"),
    "c": attrgetter("column"),
    "s": attrgetter("sheet"),
}


def _key_value(value: Value) -> Hashable:
    if isinstance(value, Item):
        return value
    if isinstance(value, Number):
        return value.value
    return value


def _value_of_key(value: Hashable) -> Value:
    if isinstance(value, Decimal):
        return Number(value)
    if isinstance(value, Item | str | bool | date) or value is None:
        return value
    return str(value)


def _require_number(value: Value, operation: str) -> Number:
    if not isinstance(value, Number):
        raise EvaluationError(f"{operation} needs numbers, found {type_name(value)}")
    return value


def _unary(op: str) -> Callable[[Value], Value]:
    def apply(value: Value) -> Value:
        if value is None:
            return None
        if op == "not":
            if not isinstance(value, bool):
                raise EvaluationError(f"not needs a boolean, found {type_name(value)}")
            return not value
        number = _require_number(value, f"unary {op}")
        return -number if op == "-" else number

    return apply


def _binary(op: str) -> Callable[[list[Value]], Value]:
    # The hottest record functions: they pass on failed operands and fail
    # their record themselves instead of going through _per_record.
    if op in _COMPARISONS:

        def comparison(values: list[Value]) -> Value:
            left, right = values
            if type(left) is _Failed:
                return left
            if type(right) is _Failed:
                return right
            try:
                return compare(op, left, right)
            except TypeError as error:
                return _failure(str(error))

        return comparison
    if op in _ARITHMETIC:

        def arithmetic(values: list[Value]) -> Value:
            left, right = values
            if type(left) is _Failed:
                return left
            if type(right) is _Failed:
                return right
            if left is None or right is None:
                return None
            if not isinstance(left, Number) or not isinstance(right, Number):
                found = right if isinstance(left, Number) else left
                return _failure(f"{op} needs numbers, found {type_name(found)}")
            if op == "+":
                return left + right
            if op == "-":
                return left - right
            if op == "*":
                return left * right
            if right.value == 0:
                # DPM-XL 4.3.4.6: a zero denominator is a run-time error.
                return _failure("division by zero")
            return left / right

        return arithmetic
    if op == "&":

        def concatenate(values: list[Value]) -> Value:
            left, right = values
            if type(left) is _Failed:
                return left
            if type(right) is _Failed:
                return right
            if left is None or right is None:
                return None
            if isinstance(left, Item):
                left = _text_form(left)
            if isinstance(right, Item):
                right = _text_form(right)
            if not isinstance(left, str) or not isinstance(right, str):
                found = right if isinstance(left, str) else left
                return _failure(f"& needs text, found {type_name(found)}")
            return left + right

        return concatenate
    if op in _BOOLEAN:

        def boolean(values: list[Value]) -> Value:
            for value in values:
                if type(value) is _Failed:
                    return value
            for value in values:
                if value is not None and not isinstance(value, bool):
                    return _failure(f"{op} needs booleans, found {type_name(value)}")
            left, right = values
            if op == "and":
                if left is False or right is False:
                    return False
                return None if left is None or right is None else True
            if op == "or":
                if left is True or right is True:
                    return True
                return None if left is None or right is None else False
            return None if left is None or right is None else left != right

        return boolean
    raise UnsupportedError(f"unknown operator {op!r}")


def conditional(
    condition: Recordset,
    then: Recordset,
    otherwise: Recordset | None,
) -> Recordset:
    """Evaluate ``if`` with the DPM-XL 8.1 semantics.

    A key-less condition returns the whole ``then`` or ``else`` operand. A
    keyed condition yields one record per condition record, taking the value
    of the matching ``then`` or ``else`` record; when a branch has keys the
    condition lacks, the condition record applies to each branch record that
    shares its keys, one result record each. A null condition takes the
    ``else`` branch. Without ``else``, the records whose condition is not
    true are left out (DPM-XL 8.1.4).

    A condition with a [`default`][dpmxl.recordset.Recordset] also covers
    the keys a branch has and it lacks, taking its default there, as in
    [`combine`][dpmxl.recordset.combine]: each branch without a default must
    have the key. A branch lacking a key takes its default, and the result
    has a default when the condition's default picks one.

    Returns:
        Recordset: The result.

    Raises:
        EvaluationError: For a non-Boolean key-less condition; a keyed one
            fails only its records.
    """

    def verdict(value: Value) -> Value:
        # A non-Boolean condition fails its record, like other type errors.
        if value is not None and not isinstance(value, bool | _Failed):
            return _failure(f"if needs a boolean condition, found {type_name(value)}")
        return value

    if not condition.keys:
        record = condition.single() or condition.default
        value = _checked(verdict(record.value if record else None))
        if value is True:
            return then
        if otherwise is not None:
            return otherwise
        return Recordset(then.keys)
    # Branch keys the condition lacks widen the result, as in a join: each
    # condition record applies to every branch record that shares its keys.
    extra = tuple(
        dict.fromkeys(
            name
            for branch in (then, otherwise)
            if branch is not None
            for name in branch.keys
            if name not in condition.keys
        )
    )
    # Index each branch's widening parts by the keys it shares with the
    # condition, rather than scanning the branch for every condition record.
    indexes: list[tuple[list[int], dict[tuple[Hashable, ...], list]]] = []
    for candidate in (then, otherwise) if extra else ():
        if candidate is None:
            continue
        shared = [name for name in candidate.keys if name in condition.keys]
        sources = [candidate.keys.index(name) for name in shared]
        parts = [
            candidate.keys.index(name) if name in candidate.keys else None
            for name in extra
        ]
        index: dict[tuple[Hashable, ...], list] = {}
        for candidate_key in candidate.records:
            index.setdefault(
                tuple([candidate_key[position] for position in sources]), []
            ).append(
                tuple(
                    [
                        None if position is None else candidate_key[position]
                        for position in parts
                    ]
                )
            )
        indexes.append(([condition.keys.index(name) for name in shared], index))
    result = Recordset(condition.keys + extra)
    records: Iterable[tuple[tuple[Hashable, ...], Record]] = condition.records.items()
    if condition.default is not None:
        records = [
            *records,
            *_branch_keys(condition, (then, otherwise)),
        ]
        result.default = _conditional_default(
            verdict(condition.default.value), then, otherwise
        )
    for key, record in records:
        value = verdict(record.value)
        if type(value) is _Failed:
            # A failed condition fails its records whichever branch they take.
            branch = None
        else:
            branch = then if value is True else otherwise
            if branch is None:
                continue
        binding = dict(zip(condition.keys, key, strict=True))
        widenings: Collection[tuple[Hashable, ...]] = [()]
        if extra:
            widenings = dict.fromkeys(
                widening
                for positions, index in indexes
                for widening in index.get(
                    tuple([key[position] for position in positions]), ()
                )
            ).keys()
        for widening in widenings:
            if branch is None:
                result.records[key + widening] = Record(value, record.points)
                continue
            full = binding | {
                name: part
                for name, part in zip(extra, widening, strict=True)
                if part is not None
            }
            matches = branch.lookup(full)
            chosen = matches[0] if matches else None
            result.records[key + widening] = Record(
                chosen.value if chosen else None,
                (record.points, chosen.points) if chosen else record.points,
            )
    return result


def _branch_keys(
    condition: Recordset, branches: Iterable[Recordset | None]
) -> list[tuple[tuple[Hashable, ...], Record]]:
    """Return the condition's default at the keys only branches have.

    Keys come from the branches with every condition key; each branch
    without a default must have the key.

    Returns:
        list[tuple[tuple[Hashable, ...], Record]]: Keys and the default.
    """
    assert condition.default is not None
    keyed = [branch for branch in branches if branch is not None and branch.keys]
    found: dict[tuple[Hashable, ...], None] = {}
    for branch in keyed:
        if not set(condition.keys) <= set(branch.keys):
            continue
        positions = [branch.keys.index(name) for name in condition.keys]
        for key in branch.records:
            part = tuple([key[position] for position in positions])
            if part not in condition.records:
                found[part] = None
    required = [branch for branch in keyed if branch.default is None]
    return [
        (key, condition.default)
        for key in found
        if all(
            branch.lookup(dict(zip(condition.keys, key, strict=True)))
            for branch in required
        )
    ]


def _conditional_default(
    verdict: Value, then: Recordset, otherwise: Recordset | None
) -> Record | None:
    """Return the default of an ``if`` whose condition has one.

    Returns:
        Record | None: The default of the branch the condition's default
        takes (a key-less branch's value), or ``None`` when it has none.
    """
    if type(verdict) is _Failed:
        return Record(verdict)
    branch = then if verdict is True else otherwise
    if branch is None:
        return None
    if branch.keys:
        return branch.default
    return branch.records.get(())


def _value_set(values: Iterable[Value]) -> ValueSet:
    try:
        return ValueSet.of(values)
    except TypeError as error:
        raise EvaluationError(str(error)) from error


def _membership(value: Value, members: Sequence[Value]) -> Value:
    if value is None:
        return None
    try:
        return any(compare("=", value, member) is True for member in members)
    except TypeError as error:
        raise EvaluationError(str(error)) from error


def _aggregate(
    name: str, data: Recordset, group_by: tuple[str, ...] | None
) -> Recordset:
    single = data.single() if not data.keys else None
    if name == "count" and single is not None and isinstance(single.value, ValueSet):
        # DPM-XL 7.3.4: count of a set is its number of members.
        if group_by is not None:
            raise EvaluationError("group by is not allowed with a set")
        return Recordset.scalar(Number(Decimal(len(single.value))))
    group_keys: list[str] = []
    for key_name in group_by or ():
        key = resolve_key(key_name, data.keys)
        if key is None:
            raise EvaluationError(
                f"group by {key_name!r} is not a key of the operand "
                f"({', '.join(data.keys) or 'no keys'})"
            )
        group_keys.append(key)
    positions = [data.keys.index(key) for key in group_keys]
    groups: dict[tuple[Hashable, ...], list[Record]] = {}
    for key, record in data.records.items():
        groups.setdefault(tuple(key[position] for position in positions), []).append(
            record
        )
    result = Recordset(tuple(group_keys))
    reduce = _per_record(lambda values: _reduce(name, values, len(values)))
    for key, records in groups.items():
        values: list[Value] = [
            record.value for record in records if record.value is not None
        ]
        points = unique_points(point for record in records for point in record.points)
        result.records[key] = Record(reduce(values), points)
    if not group_keys and not groups:
        # DPM-XL 7.3: count is the number of records; other aggregates of
        # nothing are null.
        result.records[()] = Record(Number(Decimal(0)) if name == "count" else None)
    return result


def _reduce(name: str, values: list[Value], record_count: int) -> Value:
    if name == "count":
        return Number(Decimal(len(values)))
    if not values:
        return None
    if name in {"max", "min"} and not all(
        isinstance(value, Number) for value in values
    ):
        if any(isinstance(value, bool) for value in values):
            raise EvaluationError(f"{name} needs numbers, dates, text or items")
        if any(isinstance(value, Number) for value in values):
            raise EvaluationError(
                f"{name} cannot compare numbers with dates, text or items"
            )
        # Dates, text and items order by their text, as in the columnar
        # engine: ISO dates in date order, items by category and code.
        # Some checks use max_aggr over item columns to test for presence.
        pick = max if name == "max" else min
        return pick(values, key=_ordering_text)
    numbers = [_require_number(value, name) for value in values]
    if name == "sum":
        total = numbers[0]
        for number in numbers[1:]:
            total += number
        return total
    if name == "avg":
        total = numbers[0]
        for number in numbers[1:]:
            total += number
        return total / Number(Decimal(len(numbers)))
    if name == "median":
        ordered = sorted(number.value for number in numbers)
        middle = len(ordered) // 2
        if len(ordered) % 2:
            return Number(ordered[middle])
        return (Number(ordered[middle - 1]) + Number(ordered[middle])) / Number(
            Decimal(2)
        )
    if name == "max":
        return max(numbers, key=lambda number: number.value)
    return min(numbers, key=lambda number: number.value)


def _ordering_text(value: Value) -> str:
    return value.isoformat() if isinstance(value, date) else str(value)


def _elementwise_extreme(name: str) -> Callable[[list[Value]], Value]:
    def apply(values: list[Value]) -> Value:
        present: list[Value] = [value for value in values if value is not None]
        if len(present) != len(values):
            return None
        return _reduce(name, present, len(present))

    return apply


def _null_safe(function: Callable[..., Value]) -> Callable[[list[Value]], Value]:
    def apply(values: list[Value]) -> Value:
        if any(value is None for value in values):
            return None
        return function(*values)

    return apply


def _abs(value: Value) -> Value:
    return abs(_require_number(value, "abs"))


def _isnull(values: list[Value]) -> Value:
    return values[0] is None


def _nvl(values: list[Value]) -> Value:
    return values[0] if values[0] is not None else values[1]


def _text_form(value: Value) -> str:
    # The text a report holds: a number as written, an item as its qualified
    # name, which keeps the eba_ prefix that Item drops, a Boolean in XML
    # Schema spelling.
    if isinstance(value, Number):
        return format(value.value, "f")
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, Item) and value.category is not None:
        return f"eba_{value.category}:{value.code}"
    return str(value)


def _length(value: Value) -> Value:
    return Number(Decimal(len(_text_form(value))))


def _match(value: Value, pattern: Value) -> Value:
    if not isinstance(pattern, str):
        raise EvaluationError("match needs a text pattern")
    text = _text_form(value)
    try:
        return re.fullmatch(pattern, text) is not None
    except re.error as error:
        raise EvaluationError(f"invalid match pattern: {error}") from error


# DPM-XL 4.2.5-4.2.7: the smallest operand each function accepts, and
# whether it must exceed it; anything else is a run-time error.
_DOMAINS = {
    "ln": (Decimal(0), True),
    "sqrt": (Decimal(0), False),
    "log": (Decimal(0), True),
}


def _in_domain(number: Number, name: str, *, base: bool = False) -> None:
    low, strict = (Decimal(1), True) if base else _DOMAINS[name]
    if number.value < low or (strict and number.value == low):
        what = "base" if base else "number"
        bound = f"greater than {low}" if strict else f"at least {low}"
        raise EvaluationError(
            f"{name} needs a {what} {bound}, found {number.value.normalize()}"
        )


def _math(function: Callable[[float], float], name: str) -> Callable[[Value], Value]:
    def apply(value: Value) -> Value:
        number = _require_number(value, name)
        if name in _DOMAINS:
            _in_domain(number, name)
        try:
            return _float_number(function(float(number.value)))
        except (ValueError, OverflowError):
            return None

    return apply


def _power(base: Value, exponent: Value) -> Value:
    left = _require_number(base, "power")
    right = _require_number(exponent, "power")
    try:
        return _float_number(float(left.value) ** float(right.value))
    except (ValueError, OverflowError, ZeroDivisionError):
        return None


def _log(value: Value, base: Value) -> Value:
    number = _require_number(value, "log")
    radix = _require_number(base, "log")
    _in_domain(number, "log")
    _in_domain(radix, "log", base=True)
    try:
        return _float_number(math.log(float(number.value), float(radix.value)))
    except (ValueError, ZeroDivisionError, OverflowError):
        return None


def _integer(value: Value, name: str) -> int:
    number = _require_number(value, name)
    if number.value != number.value.to_integral_value():
        raise EvaluationError(f"{name} needs whole numbers, found {number.value}")
    return int(number.value)


def _substr(*values: Value) -> Value:
    text = values[0]
    if isinstance(text, Item):
        text = _text_form(text)
    if not isinstance(text, str):
        raise EvaluationError(f"substr needs text, found {type_name(text)}")
    start = _integer(values[1], "substr") if len(values) > 1 else 1
    if start < 1:
        raise EvaluationError("substr start must be at least 1")
    if len(values) < 3:
        return text[start - 1 :]
    length = _integer(values[2], "substr")
    if length < 0:
        raise EvaluationError("substr length must not be negative")
    return text[start - 1 : start - 1 + length]


def _date_part(name: str) -> Callable[[Value], Value]:
    def apply(value: Value) -> Value:
        if not isinstance(value, date):
            raise EvaluationError(f"{name} needs a date, found {type_name(value)}")
        part = {
            "year": value.year,
            "semester": (value.month - 1) // 6 + 1,
            "quarter": (value.month - 1) // 3 + 1,
            "month": value.month,
            "week": value.isocalendar().week,
            "day": value.day,
        }[name]
        return Number(Decimal(part))

    return apply


def _make_date(year: Value, month: Value, day: Value) -> Value:
    parts = [_integer(value, "date") for value in (year, month, day)]
    try:
        return date(*parts)
    except ValueError:
        # DPM-XL 10.3.6: a day, month or year that does not exist is null.
        return None


def _float_number(value: float | complex) -> Value:
    # Out of float range (inf) or undefined (nan, complex): null, as math
    # domain errors are.
    if not isinstance(value, float) or not math.isfinite(value):
        return None
    return Number(Decimal(repr(value)))


# Operand counts are checked against dpmxl.grammar.SIGNATURES first.
_SCALAR_FUNCTIONS: dict[str, Callable[[list[Value]], Value]] = {
    "abs": _null_safe(_abs),
    "isnull": _isnull,
    "nvl": _nvl,
    "len": _null_safe(_length),
    "length": _null_safe(_length),
    "match": _null_safe(_match),
    "max": _elementwise_extreme("max"),
    "min": _elementwise_extreme("min"),
    "exp": _null_safe(_math(math.exp, "exp")),
    "ln": _null_safe(_math(math.log, "ln")),
    "sqrt": _null_safe(_math(math.sqrt, "sqrt")),
    "power": _null_safe(_power),
    "log": _null_safe(_log),
    "substr": _null_safe(_substr),
    "date": _null_safe(_make_date),
    **{
        name: _null_safe(_date_part(name))
        for name in ("year", "semester", "quarter", "month", "week", "day")
    },
}


def _check_call(node: Call) -> None:
    """Check a call's operands against its [`Signature`][dpmxl.grammar.Signature].

    Both evaluators call this before evaluating a call's operands.

    Raises:
        EvaluationError: For a wrong operand count, a ``group by`` the
            function does not take, or a key operand that is not a name.
    """
    signature = SIGNATURES.get(node.name)
    if signature is None:
        return
    problem = signature.problem(
        node.name, len(node.args), group_by=node.group_by is not None
    )
    if problem is not None:
        raise EvaluationError(problem)
    position = signature.key_operand
    if (
        position is not None
        and position < len(node.args)
        and not isinstance(node.args[position], Name)
    ):
        raise EvaluationError(signature.key_problem(node.name))


# Rule evaluation -------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Outcome:
    """One evaluated record of a rule.

    ``points`` are flattened from the evaluation on first access: most
    outcomes pass, and nobody reads their points.

    Attributes:
        key: The record key, such as ``{'c': '0020'}`` or ``{'qCPI': 'LEI-B'}``;
            empty for a rule without keys. Pass it to
            [`explain`][dpmxl.explain.explain].
        passed: ``True``, ``False``, or ``None`` when the record's result is
            null (not evaluated).
        raw_points: The points as the evaluation keeps them (possibly
            nested); read ``points`` instead.
    """

    key: Mapping[str, Hashable]
    passed: bool | None
    raw_points: tuple[Any, ...] = field(default=(), repr=False)

    @property
    def points(self) -> tuple[DataPoint, ...]:
        """Distinct data points the record was computed from."""
        return unique_points(self.raw_points)


@dataclass
class RuleResult:
    """The outcome of evaluating a rule and its optional precondition.

    Attributes:
        status: ``passed``, ``failed``, ``not_applicable`` (precondition not
            met, or no record could be evaluated), ``error`` (syntax error,
            unknown table, type mismatch, division by zero that reaches the
            result) or ``unsupported`` (a ``time_shift``, ``{o_...}`` or
            ``{g_...}`` the provider cannot resolve, or an unknown function).
        outcomes: One [`Outcome`][dpmxl.evaluator.Outcome] per record.
        message: Why the status is ``error``, ``unsupported`` or
            ``not_applicable``.
        evaluation: The traced [`Evaluation`][dpmxl.evaluator.Evaluation] for
            [`explain`][dpmxl.explain.explain]; ``None`` when evaluation did not
            complete.
        notes: Remarks gathered during evaluation.
    """

    status: Status
    outcomes: list[Outcome] = field(default_factory=list)
    message: str | None = None
    evaluation: Evaluation | None = None
    notes: list[str] = field(default_factory=list)
    assignments: dict[str, Recordset] = field(default_factory=dict)
    """Results of persistent assignments by target (see
    [`Evaluation.assignments`][dpmxl.evaluator.Evaluation.assignments]); the verdict
    comes from the last statement."""

    @property
    def failures(self) -> list[Outcome]:
        """Records whose result is false."""
        return [outcome for outcome in self.outcomes if outcome.passed is False]

    @property
    def counts(self) -> dict[str, int]:
        """Counts of passed, failed and not-evaluated records."""
        return {
            "passed": sum(outcome.passed is True for outcome in self.outcomes),
            "failed": sum(outcome.passed is False for outcome in self.outcomes),
            "null": sum(outcome.passed is None for outcome in self.outcomes),
        }


@lru_cache(maxsize=32_768)
def parse_cached(expression: str) -> Node:
    """Parse an expression once and reuse the tree.

    Trees are immutable and traces key nodes per evaluation, so one parsed
    tree can serve every report a rule is evaluated against. The cache is
    thread-safe and holds up to 32,768 expressions.

    Returns:
        Node: The expression tree.

    Raises:
        DpmXlSyntaxError: If the text is not a valid expression.

    Examples:
        >>> parse_cached("{tT, r0010} > 0") is parse_cached("{tT, r0010} > 0")
        True
    """
    return parse(expression)


@lru_cache(maxsize=4_096)
def _parse_program_cached(source: str) -> Program:
    return parse_program(source)


def _parse_cached(expression: str) -> Node:
    """Parse a rule: an expression, or statements with assignments.

    Returns:
        Node: The expression as :func:`parse_cached` returns it, or a
        :class:`~dpmxl.ast.Program` for several statements or assignments.
    """
    if not _may_be_program(expression):
        return parse_cached(expression)
    program = _parse_program_cached(expression)
    first = program.statements[0]
    if len(program.statements) == 1 and not isinstance(
        first, Assignment | PersistentAssignment
    ):
        return first
    return program


def evaluate_rule(
    expression: str | Node,
    provider: DataProvider,
    *,
    precondition: str | Node | None = None,
    trace: bool = True,
    cache: SelectionCache | None = None,
    only_keys: Mapping[str, Collection[str]] | None = None,
) -> RuleResult:
    """Evaluate a validation rule, honouring its precondition.

    Args:
        expression: Rule expression text or a parsed tree.
        provider: Report data.
        precondition: Optional precondition; the rule is not applicable
            unless it yields at least one true record.
        trace: Keep intermediate values for [`explain`][dpmxl.explain.explain].
        cache: Selections shared by the rules of one report.
        only_keys: Keep only records with these closed-axis key codes in
            every selection (see [`Evaluator`][dpmxl.evaluator.Evaluator]); the
            precondition is evaluated on all records. Not meaningful with aggregates,
            whose totals would cover only the kept records.

    Returns:
        RuleResult: Status, per-record outcomes and the evaluation trace.
        Syntax errors are reported as status ``error``, not raised.

    Examples:
        >>> from dpmxl import MemoryProvider, Number, TableLayout, explain
        >>> provider = MemoryProvider(
        ...     [TableLayout("T", rows=("0010", "0020"), columns=("0010",))],
        ...     {
        ...         ("T", "0010", "0010", None, ()): Number.of(10, 0),
        ...         ("T", "0020", "0010", None, ()): Number.of(12, 0),
        ...     },
        ... )
        >>> expression = "with {tT, c0010}: {r0010} >= {r0020}"
        >>> result = evaluate_rule(expression, provider, precondition="{v_T}")
        >>> result.status
        'failed'
        >>> explain(result.evaluation, expression, result.failures[0].key).summary
        '10 should be at least 12: difference 2'
        >>> evaluate_rule("{tT, r0010} >", provider).status
        'error'
    """
    from .parser import DpmXlSyntaxError

    try:
        if precondition is not None:
            pre_node = (
                _parse_cached(precondition)
                if isinstance(precondition, str)
                else precondition
            )
            pre = Evaluator(provider, trace=False, cache=cache).run(pre_node)
            if not any(
                _checked(record.value) is True for record in pre.result.records.values()
            ):
                return RuleResult("not_applicable", message="precondition not met")
        node = _parse_cached(expression) if isinstance(expression, str) else expression
        evaluation = Evaluator(
            provider, trace=trace, cache=cache, only_keys=only_keys
        ).run(node)
    except UnsupportedError as error:
        return RuleResult("unsupported", message=str(error))
    except (EvaluationError, DpmXlSyntaxError) as error:
        return RuleResult("error", message=str(error))
    except ArithmeticError as error:
        # Decimal overflow and the like, e.g. power(10, 300) * 1e6000.
        return RuleResult("error", message=f"arithmetic error: {type(error).__name__}")
    except RecursionError:
        return RuleResult("error", message="expression too deeply nested")

    outcomes: list[Outcome] = []
    for key, record in evaluation.result.records.items():
        if type(record.value) is _Failed:
            return RuleResult(
                "error",
                message=record.value.message,
                assignments=evaluation.assignments,
            )
        if record.value is not None and not isinstance(record.value, bool):
            return RuleResult(
                "error",
                message=f"rule yields {type_name(record.value)} values, not booleans",
                evaluation=evaluation,
                assignments=evaluation.assignments,
            )
        outcomes.append(
            Outcome(
                dict(zip(evaluation.result.keys, key, strict=True)),
                record.value,
                record.points,
            )
        )
    if any(outcome.passed is False for outcome in outcomes):
        status: Status = "failed"
    elif any(outcome.passed is True for outcome in outcomes):
        status = "passed"
    else:
        status = "not_applicable"
    return RuleResult(
        status,
        outcomes,
        evaluation=evaluation,
        notes=list(evaluation.notes),
        assignments=evaluation.assignments,
    )


__all__ = [
    "AGGREGATES",
    "Evaluation",
    "Evaluator",
    "Outcome",
    "RuleResult",
    "SelectionCache",
    "evaluate_rule",
    "parse_cached",
]
