"""Keyed record sets, the value domain of DPM-XL operators.

A selection evaluates to records keyed by its varying components: closed axes
that select more than one coordinate (``r``, ``c``, ``s``) and open key
components such as ``qEBB``. Operators combine operands with a natural join on
shared keys, so ``{r0010} = {r0020}`` under ``with {c*}`` compares column by
column, and a scalar broadcasts to every record. An operand with a
[`default`][dpmxl.recordset.Recordset] stands for that default where it lacks a
record another operand has.
"""

from __future__ import annotations

from collections.abc import (
    Callable,
    Hashable,
    Iterable,
    Iterator,
    Mapping,
    Sequence,
)
from collections.abc import Set as AbstractSet
from dataclasses import dataclass, field
from typing import Any

from .provider import DataPoint
from .values import Value

MAX_JOIN_RECORDS = 2_000_000
"""Largest number of records a join may produce before it is an error."""


class EvaluationError(Exception):
    """Raised when an expression cannot be evaluated against the data.

    For example a type mismatch, an unknown table or incompatible keys.
    [`evaluate_rule`][dpmxl.evaluator.evaluate_rule] catches it and returns
    status ``error`` with the message.
    """


class UnsupportedError(EvaluationError):
    """Raised for valid DPM-XL that this evaluator cannot resolve.

    Raised when a rule needs an optional provider method (``time_shift``,
    ``{o_...}``, ``{g_...}``) that the provider lacks or that returns
    ``None``, and for a function name the evaluator does not know.
    [`evaluate_rule`][dpmxl.evaluator.evaluate_rule] catches it and returns
    status ``unsupported``.
    """


@dataclass(frozen=True, slots=True)
class Record:
    """One keyed value and the data points it was computed from.

    ``points`` may nest the operands' point tuples instead of copying them: joins over
    large open tables would otherwise copy every record's growing point list at each
    operator. Use [`unique_points`][dpmxl.recordset.unique_points] to flatten.

    Attributes:
        value: The record's value.
        points: The data points it was computed from, possibly nested.
    """

    value: Value
    points: tuple[Any, ...] = ()


@dataclass(slots=True)
class Recordset:
    """Records indexed by a tuple of key values aligned with ``keys``.

    A selection with a ``default`` keeps it as ``default``: the record of every
    key the set lacks. [`combine`][dpmxl.recordset.combine] then fills in the
    default where another operand has a record, and
    [`lookup`][dpmxl.recordset.Recordset.lookup] returns it for a missing key.
    Per-record operations carry it along (see
    [`map`][dpmxl.recordset.Recordset.map]), as do ``where``, ``sub``,
    ``filter``, ``rename``, a ``time_shift`` of a date key and an ``if``
    whose condition has one; ``get``, aggregates and analytic functions drop
    it, except that an aggregate of an operand with no record aggregates its
    default.

    Attributes:
        keys: Key names, such as ``("r", "qCPI")``; empty for a scalar.
        records: Records by key values, aligned with ``keys``.
        default: The record of a key the set lacks, or ``None`` when a
            missing key has no record.
    """

    keys: tuple[str, ...]
    records: dict[tuple[Hashable, ...], Record] = field(default_factory=dict)
    default: Record | None = None

    @classmethod
    def scalar(cls, value: Value, points: tuple[DataPoint, ...] = ()) -> Recordset:
        """Build a key-less record set holding one value.

        Returns:
            Recordset: A scalar.
        """
        return cls((), {(): Record(value, points)})

    @property
    def is_scalar(self) -> bool:
        """Whether the set has no key components."""
        return not self.keys

    def single(self) -> Record | None:
        """Return the only record of a scalar.

        Returns:
            Record | None: The record, or ``None`` for an empty set.

        Raises:
            EvaluationError: If the set is keyed.
        """
        if self.keys:
            keys = ", ".join(self.keys)
            raise EvaluationError(
                f"expected a single value, found records keyed by {keys}"
            )
        return self.records.get(())

    def lookup(self, binding: Mapping[str, Hashable]) -> list[Record]:
        """Return records consistent with a partial key binding.

        Returns:
            list[Record]: Matching records (one when all keys are bound; the
            ``default`` when the set lacks that key and has one).
        """
        if all(key in binding for key in self.keys):
            # Every key bound (the usual lookup): one record at most.
            record = self.records.get(tuple([binding[key] for key in self.keys]))
            if record is None:
                record = self.default
            return [record] if record is not None else []
        bound = [
            (index, binding[key])
            for index, key in enumerate(self.keys)
            if key in binding
        ]
        return [
            record
            for key, record in self.records.items()
            if all(key[index] == value for index, value in bound)
        ]

    def map(self, function: Callable[[Value], Value]) -> Recordset:
        """Apply a function to every value, the ``default`` included.

        Returns:
            Recordset: Same keys, transformed values.
        """
        default = self.default
        return Recordset(
            self.keys,
            {
                key: Record(function(record.value), record.points)
                for key, record in self.records.items()
            },
            None if default is None else Record(function(default.value)),
        )


def combine(
    operands: Sequence[Recordset], function: Callable[[list[Value]], Value]
) -> Recordset:
    """Natural-join operands on shared keys and combine their values.

    Records without a partner on a shared key are dropped, unless the operand
    lacking the partner has a ``default``: it then takes part with its default,
    as a fact variable with a fallback value does; a keyed operand with no
    record at all takes its default at every record the others have, whatever
    their keys. When every keyed operand has a default, the result has a
    record for each key any operand with all the keys has, and its own
    default combines theirs. Operands without any
    shared key form a cross product, which is only allowed when at most one
    of them is keyed (scalar broadcast) to avoid accidental explosions.

    Returns:
        Recordset: Keys in first-seen order across operands.

    Raises:
        EvaluationError: On incompatible key structures or oversized joins.

    Examples:
        >>> def numbers(values, default=None):
        ...     records = {(key,): Record(value) for key, value in values}
        ...     return Recordset(("qKEY",), records, default)
        >>> def total(values):
        ...     return sum(values)
        >>> left = numbers([("a", 1), ("b", 2)])
        >>> right = numbers([("b", 3), ("c", 4)], Record(0))
        >>> def values(result):
        ...     return {key: record.value for key, record in result.records.items()}
        >>> values(combine([left, right], total))
        {('a',): 1, ('b',): 5}
        >>> left.default = Record(0)
        >>> values(combine([left, right], total))
        {('a',): 1, ('b',): 5, ('c',): 4}
    """
    if any(
        operand.keys and not operand.records and operand.default is not None
        for operand in operands
    ) and any(_has_data(operand) for operand in operands):
        # A keyed operand with no record at all (such as a selection a where
        # filters to nothing, or of a template filed without rows) stands for
        # its default at every record the other operands have, whatever
        # their keys, as a fact variable falls back when it binds to no fact.
        operands = [
            Recordset((), default=operand.default)
            if operand.keys and not operand.records and operand.default is not None
            else operand
            for operand in operands
        ]
    check_structure(operands)
    keyed = [operand for operand in operands if operand.keys]
    if any(
        not operand.keys and not operand.records and operand.default is not None
        for operand in operands
    ):
        # A key-less operand without its record (such as a [sub] that fixes
        # a missing key) stands for its default too.
        from_data = any(record.points for record in _scalar_records(operands))
        operands = [
            Recordset((), {(): operand.default}, operand.default)
            if not operand.keys and not operand.records and operand.default
            else operand
            for operand in operands
        ]
        if not keyed and not from_data:
            # Nothing but defaults and constants: no record of its own.
            return Recordset((), default=_combined_default(operands, function))
    if any(operand.default is not None for operand in keyed):
        first = keyed[0]
        if any(
            operand.keys != first.keys or operand.records.keys() != first.records.keys()
            for operand in keyed[1:]
        ):
            return _combine_defaults(operands, function)
        # The same keys everywhere (as in one table): no record is missing.
        aligned = _combine_aligned(operands, function)
        assert aligned is not None
        aligned.default = _combined_default(operands, function)
        return aligned
    fast = _combine_aligned(operands, function)
    if fast is not None:
        return fast
    keys: list[str] = []
    for operand in operands:
        keys.extend(key for key in operand.keys if key not in keys)
    rows: list[tuple[dict[str, Hashable], list[Value], tuple[Any, ...]]] = [
        ({}, [], ())
    ]
    bound: list[str] = []
    for operand in operands:
        common = [key for key in operand.keys if key in bound]
        positions = [operand.keys.index(key) for key in common]
        index: dict[
            tuple[Hashable, ...], list[tuple[tuple[Hashable, ...], Record]]
        ] = {}
        for key, record in operand.records.items():
            index.setdefault(tuple(key[position] for position in positions), []).append(
                (key, record)
            )
        next_rows: list[tuple[dict[str, Hashable], list[Value], tuple[Any, ...]]] = []
        for binding, values, points in rows:
            for key, record in index.get(tuple(binding[name] for name in common), ()):
                merged = dict(binding)
                merged.update(zip(operand.keys, key, strict=True))
                next_rows.append(
                    (merged, [*values, record.value], (points, record.points))
                )
                if len(next_rows) > MAX_JOIN_RECORDS:
                    raise EvaluationError("join produces too many records")
        rows = next_rows
        bound.extend(key for key in operand.keys if key not in bound)
    result = Recordset(tuple(keys))
    for binding, values, points in rows:
        result.records[tuple(binding[key] for key in keys)] = Record(
            function(values), points
        )
    return result


def _combine_defaults(
    operands: Sequence[Recordset], function: Callable[[list[Value]], Value]
) -> Recordset:
    """Combine operands of which at least one keyed operand has a default.

    The result's keys come from the operands with every key (the reference
    structure of [`check_structure`][dpmxl.recordset.check_structure]): from
    those without a default, joined, or from all of them when each has one.
    An operand lacking a key then contributes its default, or drops the key
    when it has none.

    Returns:
        Recordset: The result.
    """
    keys: list[str] = []
    for operand in operands:
        keys.extend(key for key in operand.keys if key not in keys)
    names = tuple(keys)
    scalars = [
        operand.records.get(()) if not operand.keys else None for operand in operands
    ]
    if any(
        not operand.keys and record is None
        for operand, record in zip(operands, scalars, strict=True)
    ):
        # An empty scalar operand: nothing to combine.
        return Recordset(names)
    full = [
        operand
        for operand in operands
        if operand.keys and len(operand.keys) == len(names)
    ]
    required = [operand for operand in full if operand.default is None]
    candidates: dict[tuple[Hashable, ...], None] = {}
    for operand in required[:1] or full:
        if operand.keys == names:
            candidates.update(dict.fromkeys(operand.records))
        else:
            positions = [operand.keys.index(name) for name in names]
            candidates.update(
                dict.fromkeys(
                    tuple([key[position] for position in positions])
                    for key in operand.records
                )
            )
    projections = [
        None
        if not operand.keys or operand.keys == names
        else [names.index(name) for name in operand.keys]
        for operand in operands
    ]
    result = Recordset(names)
    for key in candidates:
        values: list[Value] = []
        parts: list[tuple[Any, ...]] = []
        for operand, scalar, projection in zip(
            operands, scalars, projections, strict=True
        ):
            if scalar is not None:
                record: Record | None = scalar
            else:
                record = operand.records.get(
                    key
                    if projection is None
                    else tuple([key[position] for position in projection])
                )
                if record is None:
                    record = operand.default
            if record is None:
                break
            values.append(record.value)
            parts.append(record.points)
        else:
            result.records[key] = Record(function(values), tuple(parts))
    result.default = _combined_default(operands, function)
    return result


def _has_data(operand: Recordset) -> bool:
    """Whether an operand has a record of its own: keyed, or from data points.

    Returns:
        bool: False for an empty operand and for a constant.
    """
    if operand.keys:
        return bool(operand.records)
    record = operand.records.get(())
    return record is not None and bool(record.points)


def _scalar_records(operands: Sequence[Recordset]) -> list[Record]:
    return [
        record
        for operand in operands
        if not operand.keys
        for record in operand.records.values()
    ]


def _combined_default(
    operands: Sequence[Recordset], function: Callable[[list[Value]], Value]
) -> Record | None:
    """Combine the operands' defaults, scalars included.

    Returns:
        Record | None: The result's default, or ``None`` unless every keyed
        operand has one and every scalar operand a record.
    """
    values: list[Value] = []
    for operand in operands:
        record = operand.default if operand.keys else operand.records.get(())
        if record is None:
            return None
        values.append(record.value)
    return Record(function(values))


STANDARD_KEYS = frozenset({"r", "c", "s"})
"""Keys of the closed axes: rows, columns and sheets."""


def check_structure(operands: Sequence[Recordset]) -> None:
    """Enforce DPM-XL 2.2.3.1 for operators over several record sets.

    Keyed operands must have exactly the same keys, or one operand's keys
    (the reference) must be a superset of every other's. Standard keys
    (``r``, ``c``, ``s``) shared with the reference must contain the same
    values: ``{tT1, r010-020} + {tT1, r030-040}`` is an error, not empty.

    Raises:
        EvaluationError: When the structures are incompatible.
    """
    keyed = [operand for operand in operands if operand.keys]
    if len(keyed) < 2:
        return
    reference = max(keyed, key=lambda operand: len(operand.keys))
    reference_keys = set(reference.keys)
    for operand in keyed:
        if operand is reference:
            continue
        if not set(operand.keys) <= reference_keys:
            raise EvaluationError(
                "operands have incompatible keys "
                f"({', '.join(operand.keys)}) and ({', '.join(reference.keys)})"
            )
        common = [key for key in operand.keys if key in STANDARD_KEYS]
        if not common or not operand.records or not reference.records:
            continue
        if _projection(operand, common) != _projection(reference, common):
            raise EvaluationError(
                f"standard keys {', '.join(common)} do not contain the same values"
            )


def _projection(data: Recordset, keys: Sequence[str]) -> AbstractSet[Any]:
    positions = [data.keys.index(key) for key in keys]
    if positions == list(range(len(data.keys))):
        # Every key, in order: the record keys themselves.
        return data.records.keys()
    return {tuple(key[position] for position in positions) for key in data.records}


def _combine_aligned(
    operands: Sequence[Recordset], function: Callable[[list[Value]], Value]
) -> Recordset | None:
    """Combine operands that share one key structure, or are scalars.

    This covers nearly every rule operation (``{r0010} = {r0020} + {r0030}``
    under a ``with`` context) without the general join's per-row merging.

    Returns:
        Recordset | None: The result, or ``None`` when the general join is needed.
    """
    keyed = [operand for operand in operands if operand.keys]
    keys = keyed[0].keys if keyed else ()
    if any(operand.keys != keys for operand in keyed):
        return None
    scalars = [
        operand.records.get(()) if not operand.keys else None for operand in operands
    ]
    if any(
        not operand.keys and record is None
        for operand, record in zip(operands, scalars, strict=True)
    ):
        # An empty scalar operand: nothing to combine.
        return Recordset(keys)
    if not keyed:
        records = [record for record in scalars if record is not None]
        return Recordset.scalar(
            function([record.value for record in records]),
            unique_points(point for record in records for point in record.points),
        )
    driver = keyed[0]
    result = Recordset(keys)
    if len(operands) == 2:
        # Most operators are binary; avoid the generic per-record loop.
        left, right = operands
        left_scalar, right_scalar = scalars
        if left_scalar is not None:
            for key, record in right.records.items():
                result.records[key] = Record(
                    function([left_scalar.value, record.value]),
                    (left_scalar.points, record.points),
                )
        elif right_scalar is not None:
            for key, record in left.records.items():
                result.records[key] = Record(
                    function([record.value, right_scalar.value]),
                    (record.points, right_scalar.points),
                )
        else:
            other = right.records
            for key, record in left.records.items():
                partner = other.get(key)
                if partner is not None:
                    result.records[key] = Record(
                        function([record.value, partner.value]),
                        (record.points, partner.points),
                    )
        return result
    for key in driver.records:
        values: list[Value] = []
        parts: list[tuple[Any, ...]] = []
        for operand, scalar in zip(operands, scalars, strict=True):
            record = scalar if scalar is not None else operand.records.get(key)
            if record is None:
                break
            values.append(record.value)
            parts.append(record.points)
        else:
            # Link the operands' points; flattened and deduplicated on use.
            result.records[key] = Record(function(values), tuple(parts))
    return result


def iter_points(points: Iterable[Any]) -> Iterator[DataPoint]:
    """Flatten nested point tuples (see [`Record`][dpmxl.recordset.Record]) in order.

    Yields:
        DataPoint: Each point, duplicates included.
    """
    stack = [iter(points)]
    while stack:
        for item in stack[-1]:
            if isinstance(item, tuple):
                stack.append(iter(item))
                break
            yield item
        else:
            stack.pop()


def unique_points(points: Iterable[Any]) -> tuple[DataPoint, ...]:
    """Flatten and deduplicate data points by provider reference, keeping order.

    Returns:
        tuple[DataPoint, ...]: Distinct points.
    """
    if isinstance(points, tuple):
        if len(points) == 1 and not isinstance(points[0], tuple):
            return points
        if not any(isinstance(item, tuple) for item in points):
            # Already flat: skip the generator.
            flat: Iterable[Any] = points
        else:
            flat = iter_points(points)
    else:
        flat = iter_points(points)
    seen: set[Hashable] = set()
    result: list[DataPoint] = []
    for point in flat:
        identity = point.ref if point.ref is not None else id(point)
        if identity in seen:
            continue
        seen.add(identity)
        result.append(point)
    return tuple(result)


_FACT = "f"
"""The name of a record's value in a clause (DPM-XL 2.2.3.2)."""


def _is_fact(name: str, keys: Sequence[str]) -> bool:
    """Tell whether a name in a clause is the fact ``f`` rather than a key.

    Returns:
        bool: True for ``f`` (any case) unless the operand has a key ``f``.
    """
    return name.casefold() == _FACT and _FACT not in keys


def resolve_key(name: str, keys: Iterable[str]) -> str | None:
    """Resolve a key name written in a rule against available key components.

    Rules refer to DPM 2.0 key properties with or without their ``q`` prefix
    (``qEBB`` and ``EBB``) and in any case.

    Returns:
        str | None: The matching key, or ``None`` when absent or ambiguous.

    Examples:
        >>> resolve_key("EBB", ["qEBB", "r"]), resolve_key("qebb", ["qEBB"])
        ('qEBB', 'qEBB')
        >>> resolve_key("CPI", ["r"]) is None
        True
    """
    available = list(keys)
    if name in available:
        return name
    folded = name.casefold()
    variants = {folded, f"q{folded}"}
    if folded.startswith("q"):
        variants.add(folded[1:])
    matches = [key for key in available if key.casefold() in variants]
    return matches[0] if len(matches) == 1 else None


__all__ = [
    "STANDARD_KEYS",
    "EvaluationError",
    "Record",
    "Recordset",
    "UnsupportedError",
    "check_structure",
    "combine",
    "iter_points",
    "resolve_key",
    "unique_points",
]
