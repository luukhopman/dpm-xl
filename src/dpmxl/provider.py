"""Data access contract between the evaluator and a report.

The evaluator never reads report files. It asks a :class:`DataProvider` for
the data points a selection covers and for report-level facts such as filing
indicators. A provider is responsible for:

* resolving table codes and axis selectors against the table definitions;
* returning **every defined cell** of a closed selection, with ``value=None``
  when the report has no fact for it, so ``default`` and ``isnull`` work;
* returning one data point per reported key combination for open axes, with
  the open key components in :attr:`DataPoint.keys`.

:class:`MemoryProvider` is a complete in-memory implementation used by the
tests and by tools that build reports programmatically.
"""

from __future__ import annotations

from collections.abc import Hashable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any, Protocol, TypeAlias, runtime_checkable

from .ast import AxisSelector
from .values import Value


@dataclass(frozen=True, slots=True)
class CellQuery:
    """A fully resolved selection: table plus optional axis selectors."""

    table: str
    rows: AxisSelector | None = None
    columns: AxisSelector | None = None
    sheets: AxisSelector | None = None


@dataclass(frozen=True, slots=True)
class DataPoint:
    """One selected cell, and for open tables one reported key combination.

    ``ref`` is an opaque provider identity (for example a cell ID) that is
    passed back in evaluation results so callers can highlight the cell.
    """

    table: str
    row: str | None = None
    column: str | None = None
    sheet: str | None = None
    keys: Mapping[str, Value] = field(default_factory=dict)
    value: Value = None
    ref: Hashable | None = None

    def coordinate(self, axis: str) -> str | None:
        """Return the closed coordinate for ``r``, ``c`` or ``s``.

        Returns:
            str | None: The coordinate code, or ``None`` when absent.

        Raises:
            KeyError: For another axis.
        """
        if axis == "r":
            return self.row
        if axis == "c":
            return self.column
        if axis == "s":
            return self.sheet
        raise KeyError(axis)

    def label(self) -> str:
        """Render a compact DPM-XL style location.

        Returns:
            str: For example ``{tC_01.00, r0010, c0010}``.
        """
        parts = [f"t{self.table}"]
        for prefix, value in (("r", self.row), ("c", self.column), ("s", self.sheet)):
            if value and value != "*":
                parts.append(f"{prefix}{value}")
        parts.extend(f"{name}={value}" for name, value in self.keys.items())
        return "{" + ", ".join(parts) + "}"


@runtime_checkable
class DataProvider(Protocol):
    """Source of report data for one evaluation.

    A provider may also define ``open_keys(table) -> Sequence[str]``, the
    open key names of a table. Without it, an open table with no reported
    rows yields a selection without keys; with it, the selection keeps the
    table's key structure and is empty, as the specification requires.
    """

    def select(self, query: CellQuery) -> Sequence[DataPoint]:
        """Return the data points covered by a selection.

        Raises:
            LookupError: If the table does not exist in the release.
        """
        ...

    def table_reported(self, table: str) -> bool | None:
        """Return whether the report's filing indicators include ``table``.

        Returns ``None`` when the provider cannot tell.
        """
        ...

    def parameter(self, name: str) -> Value:
        """Return a report-level parameter such as ``refPeriod``.

        Returns ``None`` when the parameter is unknown.
        """
        ...


def declared_open_keys(provider: object, table: str) -> tuple[str, ...]:
    """Return the open key names a provider declares for a table.

    Returns:
        tuple[str, ...]: Key names, or ``()`` when the provider has no
        ``open_keys`` method.
    """
    method = getattr(provider, "open_keys", None)
    return tuple(method(table)) if callable(method) else ()


@lru_cache(maxsize=65_536)
def normalize_code(code: str) -> str:
    """Normalize an axis code for comparison.

    Numeric codes are compared as numbers padded to four digits, so ``r310``
    in an older rule matches row ``0310``. Results are memoized: a report's
    rules normalize the same few thousand codes millions of times.

    Returns:
        str: A canonical code.
    """
    text = code.strip()
    if text.isdigit():
        return text.zfill(4) if len(text) < 4 else text
    return text.upper()


@dataclass(frozen=True, slots=True)
class AxisMatcher:
    """A compiled axis selector: exact codes plus inclusive ranges."""

    codes: frozenset[str]
    numeric_ranges: tuple[tuple[int, int], ...]
    text_ranges: tuple[tuple[str, str], ...]
    wildcard: bool = False

    def __call__(self, code: str | None) -> bool:
        """Return whether a coordinate is selected.

        Returns:
            bool: Whether ``code`` is covered.
        """
        if self.wildcard:
            return True
        if code is None:
            return False
        value = normalize_code(code)
        if value in self.codes:
            return True
        if self.numeric_ranges and value.isdigit():
            number = int(value)
            if any(low <= number <= high for low, high in self.numeric_ranges):
                return True
        return any(low <= value <= high for low, high in self.text_ranges)

    @property
    def single(self) -> str | None:
        """The only selected code, when the selector names exactly one."""
        if self.wildcard or self.numeric_ranges or self.text_ranges:
            return None
        return next(iter(self.codes)) if len(self.codes) == 1 else None


_ALL = AxisMatcher(frozenset(), (), (), wildcard=True)


@lru_cache(maxsize=16_384)
def axis_matcher(selector: AxisSelector | None) -> AxisMatcher:
    """Compile a selector once for repeated matching.

    Returns:
        AxisMatcher: A callable matcher; ``None`` and wildcards select all.
    """
    if selector is None or selector.wildcard:
        return _ALL
    codes: set[str] = set()
    numeric: list[tuple[int, int]] = []
    text: list[tuple[str, str]] = []
    for part in selector.parts:
        if isinstance(part, str):
            codes.add(normalize_code(part))
            continue
        low, high = normalize_code(part[0]), normalize_code(part[1])
        if low.isdigit() and high.isdigit():
            numeric.append((int(low), int(high)))
        else:
            text.append((low, high))
    return AxisMatcher(frozenset(codes), tuple(numeric), tuple(text))


def axis_matches(code: str | None, selector: AxisSelector | None) -> bool:
    """Return whether a coordinate is selected.

    ``None`` selectors and wildcards select every coordinate. Ranges are
    inclusive and compare numerically when both bounds are numeric.

    Returns:
        bool: Whether ``code`` is covered by ``selector``.
    """
    return axis_matcher(selector)(code)


CellKey: TypeAlias = tuple[str, str | None, str | None, str | None, tuple[Any, ...]]


@dataclass(frozen=True, slots=True)
class TableLayout:
    """Closed coordinates and open key names of one table for MemoryProvider."""

    code: str
    rows: tuple[str, ...] = ()
    columns: tuple[str, ...] = ()
    sheets: tuple[str, ...] = ()
    open_keys: tuple[str, ...] = ()
    template: str | None = None

    def coordinates(self) -> Iterable[tuple[str | None, str | None, str | None]]:
        """Yield every closed (row, column, sheet) combination.

        Yields:
            tuple[str | None, str | None, str | None]: One cell position.
        """
        for sheet in self.sheets or (None,):
            for row in self.rows or (None,):
                for column in self.columns or (None,):
                    yield row, column, sheet


class MemoryProvider:
    """Provider over in-memory table layouts and values.

    Values are keyed by ``(table, row, column, sheet, keys)`` where ``keys`` is
    a tuple of ``(name, value)`` pairs for open tables (empty for closed ones).
    Absent tables in ``reported`` are treated as not reported.
    """

    def __init__(
        self,
        tables: Iterable[TableLayout],
        values: Mapping[CellKey, Value],
        *,
        reported: Iterable[str] | None = None,
        parameters: Mapping[str, Value] | None = None,
    ) -> None:
        """Index tables and values.

        Args:
            tables: Table layouts.
            values: Cell values; see the class docstring for the key shape.
            reported: Template or table codes with a positive filing
                indicator; defaults to every table that has a value.
            parameters: Report parameters such as ``refPeriod``.
        """
        self.tables = {table.code: table for table in tables}
        self.values = dict(values)
        self.parameters = dict(parameters or {})
        self.open_rows: dict[str, set[tuple[Any, ...]]] = {}
        for table, _row, _column, _sheet, keys in self.values:
            if keys:
                self.open_rows.setdefault(table, set()).add(keys)
        self.reported = (
            set(reported) if reported is not None else {key[0] for key in self.values}
        )

    def select(self, query: CellQuery) -> Sequence[DataPoint]:
        """Return closed cells, and one point per reported open key set.

        Returns:
            Sequence[DataPoint]: Selected data points.

        Raises:
            LookupError: If the table is unknown.
        """
        layout = self.tables.get(query.table)
        if layout is None:
            raise LookupError(f"unknown table {query.table}")
        positions = [
            position
            for position in layout.coordinates()
            if axis_matches(position[0], query.rows if layout.rows else None)
            and axis_matches(position[1], query.columns if layout.columns else None)
            and axis_matches(position[2], query.sheets if layout.sheets else None)
        ]
        key_sets: list[tuple[Any, ...]] = (
            sorted(self.open_rows.get(layout.code, ()), key=repr)
            if layout.open_keys
            else [()]
        )
        return [
            DataPoint(
                table=layout.code,
                row=row,
                column=column,
                sheet=sheet,
                keys=dict(keys),
                value=self.values.get((layout.code, row, column, sheet, keys)),
                ref=(layout.code, row, column, sheet, keys),
            )
            for keys in key_sets
            for row, column, sheet in positions
        ]

    def open_keys(self, table: str) -> tuple[str, ...]:
        """Return a table's open key names.

        Returns:
            tuple[str, ...]: Key names; empty for closed or unknown tables.
        """
        layout = self.tables.get(table)
        return layout.open_keys if layout is not None else ()

    def table_reported(self, table: str) -> bool | None:
        """Return whether a table or its template was reported.

        Returns:
            bool | None: Filing-indicator state.
        """
        if table in self.reported:
            return True
        return any(
            layout.template == table and layout.code in self.reported
            for layout in self.tables.values()
        )

    def parameter(self, name: str) -> Value:
        """Return a report parameter.

        Returns:
            Value: The parameter or ``None``.
        """
        return self.parameters.get(name)


__all__ = [
    "AxisMatcher",
    "CellQuery",
    "DataPoint",
    "DataProvider",
    "MemoryProvider",
    "TableLayout",
    "axis_matcher",
    "axis_matches",
    "normalize_code",
]
