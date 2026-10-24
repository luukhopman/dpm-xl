"""Data access contract between the evaluator and a report.

The evaluator never reads report files. It asks a
[`DataProvider`][dpmxl.provider.DataProvider] for the data points a selection covers and
for report-level facts such as filing indicators. A provider is responsible for:

* resolving table codes and axis selectors against the table definitions;
* returning **every defined cell** of a closed selection, with ``value=None``
  when the report has no fact for it, so ``default`` and ``isnull`` work;
* returning one data point per reported key combination for open axes, with
  the open key components in [`DataPoint.keys`][dpmxl.provider.DataPoint.keys].

[`MemoryProvider`][dpmxl.provider.MemoryProvider] is a complete in-memory implementation
used by the tests and by tools that build reports programmatically.
"""

from __future__ import annotations

from collections.abc import Hashable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from functools import lru_cache
from typing import Any, Protocol, TypeAlias, runtime_checkable

from .ast import AxisSelector
from .values import Value


@dataclass(frozen=True, slots=True)
class CellQuery:
    """A fully resolved selection: table plus optional axis selectors.

    The evaluator passes one to
    [`DataProvider.select`][dpmxl.provider.DataProvider.select] after applying
    the ``with`` context. Match coordinates with
    [`axis_matcher`][dpmxl.provider.axis_matcher].

    Attributes:
        table: The table code, such as ``C_01.00``.
        rows: The row selector; ``None`` when the selection names no rows,
            which selects every row.
        columns: The column selector, likewise.
        sheets: The sheet selector, likewise.
    """

    table: str
    rows: AxisSelector | None = None
    columns: AxisSelector | None = None
    sheets: AxisSelector | None = None


@dataclass(frozen=True, slots=True)
class DataPoint:
    """One selected cell, and for open tables one reported key combination.

    ``ref`` is an opaque provider identity (for example a cell ID) that is
    passed back in evaluation results so callers can highlight the cell.

    Attributes:
        table: The table code.
        row: The row code, or ``None`` for a table without rows.
        column: The column code, or ``None``.
        sheet: The sheet code, or ``None``.
        keys: Open key components by name (such as ``{"qCPI": "LEI-A"}``);
            empty for closed tables.
        value: The reported value, or ``None`` when nothing was reported.
        ref: Any hashable identity of the cell; points read by ``time_shift``
            from another report carry an
            [`EarlierRef`][dpmxl.provider.EarlierRef].
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

        Examples:
            >>> DataPoint("C_01.00", row="0010", column="0010").label()
            '{tC_01.00, r0010, c0010}'
            >>> DataPoint("C_27.00", column="0010", keys={"qCPI": "LEI-B"}).label()
            '{tC_27.00, c0010, qCPI=LEI-B}'
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

    Three methods are required. ``select`` resolves a
    [`CellQuery`][dpmxl.provider.CellQuery] against the table definitions
    ([`axis_matcher`][dpmxl.provider.axis_matcher] and
    [`normalize_code`][dpmxl.provider.normalize_code] implement range and
    code matching) and returns:

    * for a closed table, **every defined cell** the selection covers, with
      ``value=None`` where the report has no fact, so ``default`` and
      ``isnull`` work;
    * for an open table, one point per reported key combination (times the
      selected closed coordinates), with the key components in
      [`DataPoint.keys`][dpmxl.provider.DataPoint];

    and raises ``LookupError`` for a table the release does not define (the
    rule's status is then ``error``). ``table_reported`` answers ``{v_TABLE}``
    and ``parameter`` answers ``{vName}`` and ``{p_Name, type}``.

    A provider may also define these optional methods:

    * ``open_keys(table: str) -> Sequence[str]``: the open key names of a
      table. Without it, an open table with no reported rows yields a
      selection without keys; with it, the selection keeps the table's key
      structure and is empty, as the specification requires.
    * ``table_group(code: str) -> Sequence[str] | None``: the table codes of a
      table group, for ``{g_Group, ...}`` selections.
    * ``operation(code: str) -> str | None``: the expression of another
      operation, for ``{o_Code, ...}`` references.
    * ``earlier_report(period: str, count: int) -> DataProvider | None``: the
      report ``count`` periods earlier (later when negative), where
      ``period`` is ``A``, ``S``, ``Q``, ``M``, ``W`` or ``D``, for
      ``time_shift``.

    Without the optional method, or when it returns ``None``, rules that need
    it are ``unsupported``. ``DataProvider`` is ``runtime_checkable``:
    ``isinstance`` checks the three required methods only.

    A provider shared by several threads must be safe to read concurrently.
    """

    def select(self, query: CellQuery) -> Sequence[DataPoint]:
        """Return the data points covered by a selection.

        Raises:
            LookupError: If the table does not exist in the release.
        """
        ...

    def table_reported(self, table: str) -> bool | None:
        """Return whether the report's filing indicators include ``table``.

        ``table`` is the code written in ``{v_...}``, usually a template code
        such as ``C_01.00``. Returns ``None`` when the provider cannot tell,
        which makes ``{v_...}`` null.
        """
        ...

    def parameter(self, name: str) -> Value:
        """Return a report-level parameter such as ``refPeriod``.

        Returns ``None`` when the parameter is unknown. Typed parameters
        (``{p_Name, type}``) convert the value: Python numbers become
        [`Number`][dpmxl.values.Number], text becomes an item or date for
        those types, and a list or set becomes a set.
        """
        ...


@dataclass(frozen=True, slots=True)
class EarlierRef:
    """The ``ref`` of a data point that ``time_shift`` read from another report.

    It wraps the earlier report's own ``ref`` with the shift, so the point
    stays distinct from the current report's cell with the same ``ref``.

    Attributes:
        period: The ``time_shift`` period, such as ``Q``.
        count: The number of periods.
        ref: The earlier report's own ``ref`` for the cell.
    """

    period: str
    count: int
    ref: Hashable


class EarlierReport:
    """The report ``time_shift`` reads, marking its points' refs.

    Every data point it selects carries an [`EarlierRef`][dpmxl.provider.EarlierRef]
    instead of the provider's ``ref`` (points without a ``ref`` keep ``None``); every
    other method, optional ones included, is the wrapped provider's.
    """

    def __init__(self, provider: DataProvider, period: str, count: int) -> None:
        """Wrap a provider.

        Args:
            provider: The earlier report.
            period: The ``time_shift`` period, such as ``Q``.
            count: The number of periods.
        """
        self.provider = provider
        self.period = period
        self.count = count

    def select(self, query: CellQuery) -> Sequence[DataPoint]:
        """Return the earlier report's points with marked refs.

        Returns:
            Sequence[DataPoint]: The points.
        """
        return [
            point
            if point.ref is None
            else replace(point, ref=EarlierRef(self.period, self.count, point.ref))
            for point in self.provider.select(query)
        ]

    def table_reported(self, table: str) -> bool | None:
        """Return the earlier report's filing indicator.

        Returns:
            bool | None: Filing-indicator state.
        """
        return self.provider.table_reported(table)

    def parameter(self, name: str) -> Value:
        """Return an earlier report parameter.

        Returns:
            Value: The parameter or ``None``.
        """
        return self.provider.parameter(name)

    def __getattr__(self, name: str) -> Any:
        """Delegate optional provider methods.

        Returns:
            Any: The wrapped provider's attribute.
        """
        return getattr(self.provider, name)


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

    Examples:
        >>> normalize_code("310"), normalize_code("0310"), normalize_code("x01")
        ('0310', '0310', 'X01')
    """
    text = code.strip()
    if text.isdigit():
        return text.zfill(4) if len(text) < 4 else text
    return text.upper()


@dataclass(frozen=True, slots=True)
class AxisMatcher:
    """A compiled axis selector: exact codes plus inclusive ranges.

    Build one with [`axis_matcher`][dpmxl.provider.axis_matcher] and call it
    with a coordinate code.

    Attributes:
        codes: Normalized single codes.
        numeric_ranges: Inclusive ranges with numeric bounds.
        text_ranges: Inclusive ranges with text bounds, compared as text.
        wildcard: Whether every coordinate is selected.
    """

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

    Examples:
        >>> from dpmxl import AxisSelector
        >>> rows = axis_matcher(AxisSelector(parts=(("0010", "0050"), "0100")))
        >>> rows("0030"), rows("100"), rows("0060"), rows(None)
        (True, True, False, False)
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

    Examples:
        >>> from dpmxl import AxisSelector
        >>> axis_matches("0020", AxisSelector(parts=("0010", "0020")))
        True
        >>> axis_matches("0020", None)
        True
    """
    return axis_matcher(selector)(code)


CellKey: TypeAlias = tuple[str, str | None, str | None, str | None, tuple[Any, ...]]


@dataclass(frozen=True, slots=True)
class TableLayout:
    """Closed coordinates and open key names of one table for MemoryProvider.

    Attributes:
        code: The table code, such as ``C_01.00``.
        rows: Row codes; empty for a table without rows.
        columns: Column codes; empty for a table without columns.
        sheets: Sheet codes; empty for a table without sheets.
        open_keys: Open key names, such as ``("qCPI",)``; empty for a closed
            table.
        template: The template code when it differs from ``code``, so
            ``{v_TEMPLATE}`` holds when any of its tables was reported.
    """

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
    Absent tables in ``reported`` are treated as not reported. Every optional
    [`DataProvider`][dpmxl.provider.DataProvider] method is implemented. Each
    point's ``ref`` is its value key.

    A ``MemoryProvider`` is safe to read from several threads at once.

    Examples:
        >>> from dpmxl import CellQuery, Number
        >>> closed = TableLayout("C_01.00", rows=("0010", "0020"), columns=("0010",))
        >>> open_ = TableLayout("C_27.00", columns=("0010",), open_keys=("qCPI",))
        >>> provider = MemoryProvider(
        ...     [closed, open_],
        ...     {
        ...         ("C_01.00", "0010", "0010", None, ()): Number.of(100, 0),
        ...         ("C_27.00", None, "0010", None, (("qCPI", "A"),)): Number.of(1, 0),
        ...     },
        ...     parameters={"refPeriod": "2026-12-31"},
        ... )
        >>> [(p.row, p.value) for p in provider.select(CellQuery("C_01.00"))][1]
        ('0020', None)
        >>> [p.keys for p in provider.select(CellQuery("C_27.00"))]
        [{'qCPI': 'A'}]
        >>> provider.table_reported("C_27.00"), provider.parameter("refPeriod")
        (True, '2026-12-31')
    """

    def __init__(
        self,
        tables: Iterable[TableLayout],
        values: Mapping[CellKey, Value],
        *,
        reported: Iterable[str] | None = None,
        parameters: Mapping[str, Value] | None = None,
        table_groups: Mapping[str, Sequence[str]] | None = None,
        operations: Mapping[str, str] | None = None,
        earlier_reports: Mapping[tuple[str, int], DataProvider] | None = None,
    ) -> None:
        """Index tables and values.

        Args:
            tables: Table layouts.
            values: Cell values; see the class docstring for the key shape.
            reported: Template or table codes with a positive filing
                indicator; defaults to every table that has a value.
            parameters: Report parameters such as ``refPeriod``.
            table_groups: Table codes by table group code.
            operations: Operation expressions by operation code.
            earlier_reports: Reports of other periods by ``(period, count)``,
                such as ``("A", 1)`` for the previous year.
        """
        self.earlier_reports = dict(earlier_reports or {})
        self.table_groups = dict(table_groups or {})
        self.operations = dict(operations or {})
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

    def table_group(self, code: str) -> Sequence[str] | None:
        """Return the table codes of a table group.

        Returns:
            Sequence[str] | None: The tables, or ``None`` for an unknown group.
        """
        return self.table_groups.get(code)

    def earlier_report(self, period: str, count: int) -> DataProvider | None:
        """Return the report ``count`` periods earlier.

        Returns:
            DataProvider | None: The report, or ``None`` when not given.
        """
        return self.earlier_reports.get((period, count))

    def operation(self, code: str) -> str | None:
        """Return the expression of an operation.

        Returns:
            str | None: The expression, or ``None`` for an unknown operation.
        """
        return self.operations.get(code)


__all__ = [
    "AxisMatcher",
    "CellQuery",
    "DataPoint",
    "DataProvider",
    "EarlierRef",
    "EarlierReport",
    "MemoryProvider",
    "TableLayout",
    "axis_matcher",
    "axis_matches",
    "normalize_code",
]
