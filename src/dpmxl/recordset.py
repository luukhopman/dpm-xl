"""Keyed record sets, the value domain of DPM-XL operators.

A selection evaluates to records keyed by its varying components: closed axes
that select more than one coordinate (``r``, ``c``, ``s``) and open key
components such as ``qEBB``. Operators combine operands with a natural join on
shared keys, so ``{r0010} = {r0020}`` under ``with {c*}`` compares column by
column, and a scalar broadcasts to every record.
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


class EvaluationError(Exception):
    """Raised when an expression cannot be evaluated against the data."""


class UnsupportedError(EvaluationError):
    """Raised for valid DPM-XL that this evaluator does not implement."""


@dataclass(frozen=True, slots=True)
class Record:
    """One keyed value and the data points it was computed from.

    ``points`` may nest the operands' point tuples instead of copying them:
    joins over large open tables would otherwise copy every record's growing
    point list at each operator. Use :func:`unique_points` to flatten.
    """

    value: Value
    points: tuple[Any, ...] = ()


@dataclass(slots=True)
class Recordset:
    """Records indexed by a tuple of key values aligned with ``keys``."""

    keys: tuple[str, ...]
    records: dict[tuple[Hashable, ...], Record] = field(default_factory=dict)

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
            list[Record]: Matching records (one when all keys are bound).
        """
        if all(key in binding for key in self.keys):
            # Every key bound (the usual lookup): one record at most.
            record = self.records.get(tuple([binding[key] for key in self.keys]))
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
        """Apply a function to every value.

        Returns:
            Recordset: Same keys, transformed values.
        """
        return Recordset(
            self.keys,
            {
                key: Record(function(record.value), record.points)
                for key, record in self.records.items()
            },
        )


def combine(
    operands: Sequence[Recordset], function: Callable[[list[Value]], Value]
) -> Recordset:
    """Natural-join operands on shared keys and combine their values.

    Records without a partner on a shared key are dropped. Operands without
    any shared key form a cross product, which is only allowed when at most
    one of them is keyed (scalar broadcast) to avoid accidental explosions.

    Returns:
        Recordset: Keys in first-seen order across operands.

    Raises:
        EvaluationError: On incompatible key structures or oversized joins.
    """
    check_structure(operands)
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


STANDARD_KEYS = frozenset({"r", "c", "s"})


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
    """Flatten nested point tuples (see :class:`Record`) in order.

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


def resolve_key(name: str, keys: Iterable[str]) -> str | None:
    """Resolve a key name written in a rule against available key components.

    Rules refer to DPM 2.0 key properties with or without their ``q`` prefix
    (``qEBB`` and ``EBB``) and in any case.

    Returns:
        str | None: The matching key, or ``None`` when absent or ambiguous.
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
