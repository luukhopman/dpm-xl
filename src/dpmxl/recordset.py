"""Keyed record sets, the value domain of DPM-XL operators.

A selection evaluates to records keyed by its varying components: closed axes
that select more than one coordinate (``r``, ``c``, ``s``) and open key
components such as ``qEBB``. Operators combine operands with a natural join on
shared keys, so ``{r0010} = {r0020}`` under ``with {c*}`` compares column by
column, and a scalar broadcasts to every record.
"""

from __future__ import annotations

from collections.abc import Callable, Hashable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field

from .provider import DataPoint
from .values import Value

MAX_JOIN_RECORDS = 2_000_000


class EvaluationError(Exception):
    """Raised when an expression cannot be evaluated against the data."""


class UnsupportedError(EvaluationError):
    """Raised for valid DPM-XL that this evaluator does not implement."""


@dataclass(frozen=True, slots=True)
class Record:
    """One keyed value and the data points it was computed from."""

    value: Value
    points: tuple[DataPoint, ...] = ()


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
        bound = [
            (index, binding[key])
            for index, key in enumerate(self.keys)
            if key in binding
        ]
        if len(bound) == len(self.keys):
            record = self.records.get(tuple(value for _, value in bound))
            return [record] if record is not None else []
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
    keyed = [operand for operand in operands if operand.keys]
    for index, left in enumerate(keyed):
        for right in keyed[index + 1 :]:
            if not set(left.keys) & set(right.keys):
                raise EvaluationError(
                    "operands have unrelated keys "
                    f"({', '.join(left.keys)}) and ({', '.join(right.keys)})"
                )
    keys: list[str] = []
    for operand in operands:
        keys.extend(key for key in operand.keys if key not in keys)
    rows: list[tuple[dict[str, Hashable], list[Value], tuple[DataPoint, ...]]] = [
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
        next_rows: list[
            tuple[dict[str, Hashable], list[Value], tuple[DataPoint, ...]]
        ] = []
        for binding, values, points in rows:
            for key, record in index.get(tuple(binding[name] for name in common), ()):
                merged = dict(binding)
                merged.update(zip(operand.keys, key, strict=True))
                next_rows.append(
                    (merged, [*values, record.value], points + record.points)
                )
                if len(next_rows) > MAX_JOIN_RECORDS:
                    raise EvaluationError("join produces too many records")
        rows = next_rows
        bound.extend(key for key in operand.keys if key not in bound)
    result = Recordset(tuple(keys))
    for binding, values, points in rows:
        result.records[tuple(binding[key] for key in keys)] = Record(
            function(values), unique_points(points)
        )
    return result


def unique_points(points: Iterable[DataPoint]) -> tuple[DataPoint, ...]:
    """Deduplicate data points by provider reference, keeping order.

    Returns:
        tuple[DataPoint, ...]: Distinct points.
    """
    seen: set[Hashable] = set()
    result: list[DataPoint] = []
    for point in points:
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
    "EvaluationError",
    "Record",
    "Recordset",
    "UnsupportedError",
    "combine",
    "resolve_key",
    "unique_points",
]
