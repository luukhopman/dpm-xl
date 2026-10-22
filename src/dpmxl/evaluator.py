"""Evaluate DPM-XL expressions against a :class:`~dpmxl.provider.DataProvider`.

The evaluator implements the subset of DPM-XL 1.0 used by EBA validation
rules and similar checks. It keeps every intermediate record set so that a
failing record can be explained operand by operand (see :mod:`dpmxl.explain`).

Semantics in brief:

* A selection yields one record per selected data point, keyed by varying
  closed axes and open key components. Missing facts take the selection's
  ``default`` (``null`` when none is written).
* ``interval: true`` keeps each fact's decimals tolerance, so ``=`` holds when
  the intervals overlap; otherwise comparisons are exact.
* Null propagates through arithmetic and comparisons; ``and``/``or`` use
  three-valued (Kleene) logic. A null rule result is "not evaluated", never a
  failure.
* Aggregates over no records are null.
"""

from __future__ import annotations

import math
import re
import statistics
from collections.abc import Callable, Collection, Hashable, Iterator, Mapping
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation
from functools import lru_cache
from typing import Any, Literal, cast

from .ast import (
    AXIS_KEYS,
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
    Rename,
    Selection,
    SelectionSpec,
    SetLiteral,
    Sub,
    TableReported,
    Unary,
    Where,
    With,
)
from .parser import parse
from .provider import (
    CellQuery,
    DataPoint,
    DataProvider,
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
from .values import Number, Value, compare, type_name

AGGREGATES = frozenset({"sum", "count", "avg", "max", "min", "median"})
_COMPARISONS = frozenset({"=", "!=", "<", "<=", ">", ">="})
_ARITHMETIC = frozenset({"+", "-", "*", "/"})
_BOOLEAN = frozenset({"and", "or", "xor"})
_UNSUPPORTED_FUNCTIONS = {
    "time_shift": (
        "The rule compares with the previous reporting period (time_shift), "
        "which a single report does not include"
    ),
}

# Marks records removed by filter(); never escapes the evaluator.
_FILTERED = cast(Value, object())

Status = Literal["passed", "failed", "not_applicable", "error", "unsupported"]


@dataclass
class Evaluation:
    """Raw evaluation result with intermediate record sets for explanation."""

    root: Node
    result: Recordset
    trace: dict[int, Recordset] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

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
    evaluator, so sharing them is safe. Use one cache per report.
    """

    def __init__(self) -> None:
        """Create an empty cache."""
        self.recordsets: dict[SelectionSpec, Recordset] = {}


class Evaluator:
    """Evaluates one expression tree against one provider."""

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

    def run(self, node: Node) -> Evaluation:
        """Evaluate a complete expression.

        Returns:
            Evaluation: The result and its trace.
        """
        self._trace = {}
        self._notes = []
        result = self.evaluate(node, SelectionSpec(), None)
        return Evaluation(node, result, self._trace, self._notes)

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
                selected = self._selection(spec.merged_into(context))
                for condition in self._context_conditions:
                    selected = self._where(selected, condition, context)
                return selected
            case TableReported(table=table):
                return Recordset.scalar(self.provider.table_reported(table))
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
                value = self.provider.parameter(name)
                if value is not None:
                    return Recordset.scalar(value)
                raise EvaluationError(f"unknown key component or parameter {name!r}")
            case Unary(op=op, operand=operand):
                return self.evaluate(operand, context, bindings).map(_unary(op))
            case Binary(op=op, left=left, right=right):
                operands = [
                    self.evaluate(left, context, bindings),
                    self.evaluate(right, context, bindings),
                ]
                return combine(operands, _binary(op))
            case In(operand=operand, values=values):
                members = [
                    self._set_member(item, context, bindings) for item in values.items
                ]
                return self.evaluate(operand, context, bindings).map(
                    lambda value: _membership(value, members)
                )
            case SetLiteral():
                raise EvaluationError("a set can only follow 'in'")
            case If(condition=condition, then=then, otherwise=otherwise):
                return conditional(
                    self.evaluate(condition, context, bindings),
                    self.evaluate(then, context, bindings),
                    self.evaluate(otherwise, context, bindings)
                    if otherwise is not None
                    else None,
                    boolean_then=is_boolean(then),
                )
            case Call():
                return self._call(node, context, bindings)
            case Where(operand=operand, condition=condition):
                return self._where(
                    self._clause_operand(operand, context, bindings), condition, context
                )
            case Get(operand=operand, name=name):
                return self._get(self.evaluate(operand, context, bindings), name)
            case Sub(operand=operand, name=name, value=value):
                fixed = self.evaluate(value, context, bindings).single()
                return self._sub(
                    self._clause_operand(operand, context, bindings),
                    name,
                    fixed.value if fixed else None,
                )
            case Rename(operand=operand, pairs=pairs):
                return self._rename(self.evaluate(operand, context, bindings), pairs)
        raise UnsupportedError(f"unsupported expression node {type(node).__name__}")

    def _clause_operand(
        self,
        operand: Node,
        context: SelectionSpec,
        bindings: Mapping[str, Value] | None,
    ) -> Recordset:
        # DPM-XL 3.2: a where or sub clause on a selection overrides the
        # with-level where instead of adding to it.
        if not isinstance(operand, Selection) or not self._context_conditions:
            return self.evaluate(operand, context, bindings)
        saved, self._context_conditions = self._context_conditions, []
        try:
            return self.evaluate(operand, context, bindings)
        finally:
            self._context_conditions = saved

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
            codes = {point.coordinate(key) for point in points}
            codes.discard("*")
            codes.discard(None)
            if len(codes) > 1:
                axis_keys.append(key)
        # An open table with no reported rows still has its key structure.
        open_keys = list(declared_open_keys(self.provider, spec.table))
        for point in points:
            open_keys.extend(name for name in point.keys if name not in open_keys)
        keys = (*axis_keys, *open_keys)
        default = (
            _literal_value(spec.default) if isinstance(spec.default, Literal_) else None
        )
        interval = bool(spec.interval)
        result = Recordset(keys)
        kept = [
            (position, self.only_keys[name])
            for position, name in enumerate(axis_keys)
            if self.only_keys and name in self.only_keys
        ]
        for point in points:
            if kept and any(
                normalize_code(point.coordinate(axis_keys[position]) or "")
                not in allowed
                for position, allowed in kept
            ):
                continue
            value = point.value
            if value is None:
                value = default
            elif isinstance(value, Number) and not interval:
                value = value.exact()
            key = tuple(
                normalize_code(point.coordinate(name) or "") for name in axis_keys
            ) + tuple(_key_value(point.keys.get(name)) for name in open_keys)
            existing = result.records.get(key)
            if existing is not None and existing.value is not None and value is None:
                continue
            result.records[key] = Record(value, (point,))
        return result

    # Calls ---------------------------------------------------------------

    def _call(
        self,
        node: Call,
        context: SelectionSpec,
        bindings: Mapping[str, Value] | None,
    ) -> Recordset:
        name = node.name
        if name in _UNSUPPORTED_FUNCTIONS:
            raise UnsupportedError(_UNSUPPORTED_FUNCTIONS[name])
        if name in AGGREGATES and (len(node.args) == 1 or node.group_by is not None):
            if len(node.args) != 1:
                raise EvaluationError(f"{name} with group by takes one operand")
            operand = self.evaluate(node.args[0], context, bindings)
            return _aggregate(name, operand, node.group_by)
        if node.group_by is not None:
            raise EvaluationError(f"group by is not allowed in {name}")
        if name == "filter":
            _arity(node, 2)
            data = self.evaluate(node.args[0], context, bindings)
            condition = self.evaluate(node.args[1], context, bindings)
            joined = combine(
                [condition, data],
                lambda values: values[1] if values[0] is True else _FILTERED,
            )
            return Recordset(
                joined.keys,
                {
                    key: record
                    for key, record in joined.records.items()
                    if record.value is not _FILTERED
                },
            )
        args = [self.evaluate(arg, context, bindings) for arg in node.args]
        function = _SCALAR_FUNCTIONS.get(name)
        if function is None:
            raise UnsupportedError(f"unknown function {name!r}")
        arity, implementation = function
        if arity is not None and len(args) not in arity:
            raise EvaluationError(
                f"{name} takes {' or '.join(map(str, arity))} operands"
            )
        return combine(args, implementation)

    # Clauses ------------------------------------------------------------

    def _where(
        self, data: Recordset, condition: Node, context: SelectionSpec
    ) -> Recordset:
        if data.records and not data.keys:
            raise EvaluationError("where needs a keyed operand")
        result = Recordset(data.keys)
        for key, record in data.records.items():
            bindings = {
                name: _value_of_key(value)
                for name, value in zip(data.keys, key, strict=True)
            }
            verdict = self.evaluate(condition, context, bindings).single()
            if verdict is not None and verdict.value is True:
                result.records[key] = record
        return result

    def _get(self, data: Recordset, name: str) -> Recordset:
        key = resolve_key(name, data.keys)
        if key is None:
            value = self.provider.parameter(name)
            if value is None:
                raise EvaluationError(f"unknown key component or parameter {name!r}")
            return data.map(lambda _value: value)
        position = data.keys.index(key)
        # DPM-XL 11.3.6: records with a null fact value are omitted.
        return Recordset(
            data.keys,
            {
                record_key: Record(_value_of_key(record_key[position]), record.points)
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
        result = Recordset(keys)
        for record_key, record in data.records.items():
            if compare("=", _value_of_key(record_key[position]), value) is True:
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
            keys[keys.index(key)] = new
        return Recordset(tuple(keys), dict(data.records))

    def _set_member(
        self,
        node: Node,
        context: SelectionSpec,
        bindings: Mapping[str, Value] | None,
    ) -> Value:
        record = self.evaluate(node, context, bindings).single()
        return record.value if record else None


# Value helpers -------------------------------------------------------------


def _literal_value(node: Literal_) -> Value:
    if node.kind == "number":
        assert isinstance(node.value, Decimal)
        return Number(node.value)
    return cast(Value, node.value)


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
    if op in _COMPARISONS:

        def comparison(values: list[Value]) -> Value:
            try:
                return compare(op, values[0], values[1])
            except TypeError as error:
                raise EvaluationError(str(error)) from error

        return comparison
    if op in _ARITHMETIC:

        def arithmetic(values: list[Value]) -> Value:
            left, right = values
            if left is None or right is None:
                return None
            a = _require_number(left, op)
            b = _require_number(right, op)
            if op == "+":
                return a + b
            if op == "-":
                return a - b
            if op == "*":
                return a * b
            if b.value == 0:
                # DPM-XL 4.3.4.6: a zero denominator is a run-time error.
                raise EvaluationError("division by zero")
            return a / b

        return arithmetic
    if op in _BOOLEAN:

        def boolean(values: list[Value]) -> Value:
            for value in values:
                if value is not None and not isinstance(value, bool):
                    raise EvaluationError(
                        f"{op} needs booleans, found {type_name(value)}"
                    )
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


def is_boolean(node: Node) -> bool:
    """Whether an expression is statically of the Boolean data type.

    Returns:
        bool: True for comparisons, logical operators, ``in``, ``isnull``,
        ``match``, Boolean literals and conditionals of those.
    """
    match node:
        case Binary(op=op):
            return op in _COMPARISONS or op in _BOOLEAN
        case Unary(op="not") | In():
            return True
        case Call(name=name):
            return name in {"isnull", "match"}
        case Literal_(kind="boolean"):
            return True
        case If(then=then):
            return is_boolean(then)
        case With(body=body):
            return is_boolean(body)
    return False


def conditional(
    condition: Recordset,
    then: Recordset,
    otherwise: Recordset | None,
    *,
    boolean_then: bool,
) -> Recordset:
    """Evaluate ``if`` with the DPM-XL 8.1 semantics.

    A key-less condition returns the whole ``then`` or ``else`` operand. A
    keyed condition yields one record per condition record, taking the value
    of the matching ``then`` or ``else`` record; when a branch has keys the
    condition lacks, the condition record applies to each branch record that
    shares its keys, one result record each. A null condition takes the
    ``else`` branch. Without ``else``, the result is ``true`` when ``then`` is
    Boolean and null otherwise.

    Returns:
        Recordset: The result.

    Raises:
        EvaluationError: For a non-Boolean condition.
    """
    fallback: Value = True if boolean_then else None

    def verdict(value: Value) -> Value:
        if value is not None and not isinstance(value, bool):
            raise EvaluationError(
                f"if needs a boolean condition, found {type_name(value)}"
            )
        return value

    if not condition.keys:
        record = condition.single()
        value = verdict(record.value if record else None)
        if value is True:
            return then
        if otherwise is not None:
            return otherwise
        if then.keys:
            return Recordset(
                then.keys,
                {
                    key: Record(fallback, item.points)
                    for key, item in then.records.items()
                },
            )
        return Recordset.scalar(fallback, record.points if record else ())
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
    result = Recordset(condition.keys + extra)
    for key, record in condition.records.items():
        value = verdict(record.value)
        branch = then if value is True else otherwise
        binding = dict(zip(condition.keys, key, strict=True))
        widenings: Collection[tuple[Hashable, ...]] = [()]
        if extra:
            widenings = dict.fromkeys(
                tuple(keys.get(name) for name in extra)
                for candidate in (then, otherwise)
                if candidate is not None
                for keys in _matching_keys(candidate, binding)
            ).keys()
        for widening in widenings:
            if branch is None:
                result.records[key + widening] = Record(fallback, record.points)
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


def _matching_keys(
    records: Recordset, binding: Mapping[str, Hashable]
) -> Iterator[dict[str, Hashable]]:
    """Yield the keys of records consistent with a partial binding."""
    bound = [
        (position, binding[name])
        for position, name in enumerate(records.keys)
        if name in binding
    ]
    for key in records.records:
        if all(key[position] == part for position, part in bound):
            yield dict(zip(records.keys, key, strict=True))


def _membership(value: Value, members: list[Value]) -> Value:
    if value is None:
        return None
    try:
        return any(compare("=", value, member) is True for member in members)
    except TypeError as error:
        raise EvaluationError(str(error)) from error


def _aggregate(
    name: str, data: Recordset, group_by: tuple[str, ...] | None
) -> Recordset:
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
    for key, records in groups.items():
        values: list[Value] = [
            record.value for record in records if record.value is not None
        ]
        points = unique_points(point for record in records for point in record.points)
        result.records[key] = Record(_reduce(name, values, len(records)), points)
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
        comparable: list[Any] = [
            value for value in values if not isinstance(value, Number | Item | bool)
        ]
        if len(comparable) != len(values):
            raise EvaluationError(f"{name} needs numbers, dates or text")
        return max(comparable) if name == "max" else min(comparable)
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
        return Number(statistics.median(number.value for number in numbers))
    if name == "max":
        return max(numbers, key=lambda number: number.value)
    return min(numbers, key=lambda number: number.value)


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


def _length(value: Value) -> Value:
    text = str(value) if not isinstance(value, Number) else format(value.value, "f")
    return Number(Decimal(len(text)))


def _match(value: Value, pattern: Value) -> Value:
    if not isinstance(pattern, str):
        raise EvaluationError("match needs a text pattern")
    text = str(value) if not isinstance(value, Number) else format(value.value, "f")
    try:
        return re.fullmatch(pattern, text) is not None
    except re.error as error:
        raise EvaluationError(f"invalid match pattern: {error}") from error


def _math(function: Callable[[float], float], name: str) -> Callable[[Value], Value]:
    def apply(value: Value) -> Value:
        number = _require_number(value, name)
        try:
            return Number(Decimal(repr(function(float(number.value)))))
        except (ValueError, OverflowError, InvalidOperation):
            return None

    return apply


def _power(base: Value, exponent: Value) -> Value:
    left = _require_number(base, "power")
    right = _require_number(exponent, "power")
    try:
        return Number(Decimal(repr(float(left.value) ** float(right.value))))
    except (ValueError, OverflowError, InvalidOperation, ZeroDivisionError):
        return None


_SCALAR_FUNCTIONS: dict[
    str, tuple[tuple[int, ...] | None, Callable[[list[Value]], Value]]
] = {
    "abs": ((1,), _null_safe(_abs)),
    "isnull": ((1,), _isnull),
    "nvl": ((2,), _nvl),
    "len": ((1,), _null_safe(_length)),
    "length": ((1,), _null_safe(_length)),
    "match": ((2,), _null_safe(_match)),
    "max": (None, _elementwise_extreme("max")),
    "min": (None, _elementwise_extreme("min")),
    "exp": ((1,), _null_safe(_math(math.exp, "exp"))),
    "ln": ((1,), _null_safe(_math(math.log, "ln"))),
    "sqrt": ((1,), _null_safe(_math(math.sqrt, "sqrt"))),
    "power": ((2,), _null_safe(_power)),
}


def _arity(node: Call, count: int) -> None:
    if len(node.args) != count:
        raise EvaluationError(f"{node.name} takes {count} operands")


# Rule evaluation -------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Outcome:
    """One evaluated record of a rule.

    ``points`` are flattened from the evaluation on first access: most
    outcomes pass, and nobody reads their points.
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
    """The outcome of evaluating a rule and its optional precondition."""

    status: Status
    outcomes: list[Outcome] = field(default_factory=list)
    message: str | None = None
    evaluation: Evaluation | None = None
    notes: list[str] = field(default_factory=list)

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
    tree can serve every report a rule is evaluated against.

    Returns:
        Node: The expression tree.
    """
    return parse(expression)


_parse_cached = parse_cached


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
        trace: Keep intermediate values for :func:`dpmxl.explain.explain`.
        cache: Selections shared by the rules of one report.
        only_keys: Keep only records with these closed-axis key codes in
            every selection (see :class:`Evaluator`); the precondition is
            evaluated on all records. Not meaningful with aggregates, whose
            totals would cover only the kept records.

    Returns:
        RuleResult: Status, per-record outcomes and the evaluation trace.
        Syntax errors are reported as status ``error``, not raised.
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
            if not any(record.value is True for record in pre.result.records.values()):
                return RuleResult("not_applicable", message="precondition not met")
        node = _parse_cached(expression) if isinstance(expression, str) else expression
        evaluation = Evaluator(
            provider, trace=trace, cache=cache, only_keys=only_keys
        ).run(node)
    except UnsupportedError as error:
        return RuleResult("unsupported", message=str(error))
    except (EvaluationError, DpmXlSyntaxError) as error:
        return RuleResult("error", message=str(error))

    outcomes: list[Outcome] = []
    for key, record in evaluation.result.records.items():
        if record.value is not None and not isinstance(record.value, bool):
            return RuleResult(
                "error",
                message=f"rule yields {type_name(record.value)} values, not booleans",
                evaluation=evaluation,
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
        status, outcomes, evaluation=evaluation, notes=list(evaluation.notes)
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
