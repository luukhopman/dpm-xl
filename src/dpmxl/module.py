"""Module files: one module's tables, cells and rules, in one JSON document.

A module file describes one module of a DPM release, such as ``COREP_OF``:
its tables with their cells and open keys, the datapoint each cell carries,
and the rules a report of the module must satisfy. It is the
``dpm-module/1`` format, which shares its fields with dpm-synth's
``dpm-synth-template/1``, so one file serves both tools.
[`load_module`][dpmxl.module.load_module] reads either.

A [`Module`][dpmxl.module.Module] gives dpm-xl's
[`TableLayout`][dpmxl.provider.TableLayout]s with
[`layouts`][dpmxl.module.Module.layouts] and its
[`Rule`][dpmxl.rules.Rule]s as [`rules`][dpmxl.module.Module.rules];
``dpmxl.xbrl.ReportProvider`` (the ``xbrl`` extra) evaluates them on a
report read with dpm-xbrl.

Examples:
    >>> module = load_module(
    ...     {
    ...         "format": "dpm-module/1",
    ...         "release": "4.2",
    ...         "module": "DEMO",
    ...         "tables": [
    ...             {
    ...                 "code": "T_01.00",
    ...                 "cells": [
    ...                     {"id": "c1", "row": "0010", "column": "0010",
    ...                      "datapoint": "dp1", "data_type": "m"},
    ...                 ],
    ...             }
    ...         ],
    ...         "rules": [{"code": "v1", "expression": "{tT_01.00, r0010} > 0"}],
    ...     }
    ... )
    >>> module.layouts()[0].rows, module.rules[0].code
    (('0010',), 'v1')
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import date
from pathlib import Path
from typing import Any

from .provider import TableLayout
from .rules import Rule, RuleFileError, rules_from

MODULE_FORMAT = "dpm-module/1"
"""The ``format`` of a module file."""

FORMATS = (MODULE_FORMAT, "dpm-synth-template/1")
"""The ``format`` values [`load_module`][dpmxl.module.load_module] reads."""

NUMERIC_TYPES = frozenset({"m", "p", "i", "r"})
"""DPM data type codes of numbers: monetary, percentage, integer, decimal."""

_CELL_TYPES = {
    "m": "number",
    "p": "number",
    "r": "number",
    "i": "integer",
    "o": "integer",
    "e": "item",
    "b": "boolean",
    "t": "boolean",
    "d": "date",
}
_MAX_DECIMALS = 20


class ModuleError(ValueError):
    """A module file that cannot be read or is not valid.

    The message names the offending field by its JSON path, such as
    ``tables[2].cells[0].datapoint: required``.
    """


@dataclass(frozen=True, slots=True)
class OpenKey:
    """A key of an open table, such as one counterparty per row.

    Attributes:
        code: The key's property code, as rules name it, such as ``qEBB``.
        column: The key's column in the table's xBRL-CSV file.
        data_type: The DPM data type code of a typed key, such as ``i`` or
            ``d``; ``None`` for text.
        items: The allowed item qnames of an enumerated key, such as
            ``eba_qEC:qx16``; empty when none is allowed, ``None`` for a
            typed key.
    """

    code: str
    column: str
    data_type: str | None = None
    items: tuple[str, ...] | None = None


@dataclass(frozen=True, slots=True)
class Cell:
    """One reportable cell and the datapoint that carries its value.

    Attributes:
        id: An identifier of the cell, unique within the module.
        datapoint: The datapoint code, such as ``dp12345``.
        row: The row code, such as ``0010``; ``None`` for a table without
            rows, ``*`` for every row of an open table.
        column: The column code, likewise.
        sheet: The sheet code, likewise.
        data_type: The DPM data type code: ``m`` monetary, ``p``
            percentage, ``i`` integer, ``r`` decimal, ``o`` ordinal (an
            integer), ``e`` item, ``b`` Boolean, ``t`` a Boolean that can
            only be true, ``d`` date, ``dt`` date or date and time; ``s``
            text, ``es`` text that may be empty, ``u`` URI, and anything
            else, or ``None``, is text.
        items: The allowed item qnames of an ``e`` cell; empty when none is
            allowed, ``None`` when they are not known.
        unit: Whether a monetary value is reported in its currency of
            denomination, in the table's ``unit`` column.
    """

    id: str
    datapoint: str
    row: str | None = None
    column: str | None = None
    sheet: str | None = None
    data_type: str | None = None
    items: tuple[str, ...] | None = None
    unit: bool = False


@dataclass(frozen=True, slots=True)
class Table:
    """A table of the module, its filing indicator, open keys and cells.

    Attributes:
        code: The table code, such as ``C_07.00.a``, as rules name it.
        filing_indicator: The filing indicator it is reported under, such
            as ``C_07.00``; the code when the file gives none.
        open_keys: The open keys; empty for a closed table.
        cells: The reportable cells.
    """

    code: str
    filing_indicator: str
    open_keys: tuple[OpenKey, ...] = ()
    cells: tuple[Cell, ...] = ()

    def layout(self) -> TableLayout:
        """Return the table's layout for dpm-xl.

        Row, column and sheet codes are those of the cells; ``*`` stands for
        an open axis. An axis whose every cell has ``*`` is open. Data types
        map to the layout's as [`cell_type`][dpmxl.module.cell_type] does.

        Returns:
            TableLayout: The layout.
        """
        axes: dict[str, list[str]] = {"rows": [], "columns": [], "sheets": []}
        stars: dict[str, int] = {"rows": 0, "columns": 0, "sheets": 0}
        data_types: dict[tuple[str | None, str | None, str | None], str] = {}
        for cell in self.cells:
            for axis, code in zip(
                axes, (cell.row, cell.column, cell.sheet), strict=True
            ):
                if code == "*":
                    stars[axis] += 1
                elif code is not None and code not in axes[axis]:
                    axes[axis].append(code)
            kind = cell_type(cell.data_type)
            if kind is not None:
                data_types[_open(cell.row), _open(cell.column), _open(cell.sheet)] = (
                    kind
                )
        open_axes = tuple(
            axis
            for axis in ("rows", "columns", "sheets")
            if stars[axis] == len(self.cells) and self.cells
        )
        return TableLayout(
            code=self.code,
            rows=tuple(axes["rows"]),
            columns=tuple(axes["columns"]),
            sheets=tuple(axes["sheets"]),
            open_keys=tuple(key.code for key in self.open_keys),
            template=self.filing_indicator
            if self.filing_indicator != self.code
            else None,
            open_axes=open_axes,
            data_types=data_types,
        )


def _open(code: str | None) -> str | None:
    return None if code == "*" else code


def cell_type(data_type: str | None) -> str | None:
    """Return the [`TableLayout`][dpmxl.provider.TableLayout] type of a DPM data type.

    ``m``, ``p`` and ``r`` are ``number``; ``i`` and ``o`` ``integer``;
    ``e`` ``item``; ``b`` and ``t`` ``boolean``; ``d`` ``date``; ``s``,
    ``es``, ``u`` and other codes ``string``.

    Returns:
        str | None: ``number``, ``integer``, ``item``, ``boolean``, ``date``
        or ``string``; ``None`` for ``dt``, whose value is a date or a date
        and time, or no data type.

    Examples:
        >>> cell_type("m"), cell_type("o"), cell_type("es"), cell_type("dt")
        ('number', 'integer', 'string', None)
    """
    if data_type is None or data_type == "dt":
        return None
    return _CELL_TYPES.get(data_type, "string")


@dataclass(frozen=True, slots=True)
class Module:
    """One module of a DPM release: its tables, cells and rules.

    Build one with [`load_module`][dpmxl.module.load_module].

    Attributes:
        format: The file's format, ``dpm-module/1`` or
            ``dpm-synth-template/1``.
        release: The DPM release, such as ``4.2``.
        module: The module code, such as ``COREP_OF``.
        tables: The tables.
        rules: The rules, with their severity and whether they are active.
        entry_point: The module's xBRL-CSV entry point, or ``None``.
        reference_date: The reference date, or ``None``.
        filing_indicators: The filing indicators of every template of the
            module; empty when the file lists none.
        currency: The reporting currency, an ISO 4217 code such as ``EUR``,
            or ``None``.
        decimals: Reporting decimals by data type code, such as
            ``{"m": -3}``.
    """

    format: str
    release: str
    module: str
    tables: tuple[Table, ...]
    rules: tuple[Rule, ...] = ()
    entry_point: str | None = None
    reference_date: date | None = None
    filing_indicators: tuple[str, ...] = ()
    currency: str | None = None
    decimals: Mapping[str, int] = field(default_factory=dict)

    def table(self, code: str) -> Table | None:
        """Return a table by its code, ignoring case.

        Returns:
            Table | None: The table, or ``None``.
        """
        folded = code.casefold()
        return next(
            (table for table in self.tables if table.code.casefold() == folded), None
        )

    def layouts(self) -> tuple[TableLayout, ...]:
        """Return the layouts of the tables, for dpm-xl.

        Returns:
            tuple[TableLayout, ...]: One per table; see
            [`Table.layout`][dpmxl.module.Table.layout].
        """
        return tuple(table.layout() for table in self.tables)

    def templates(self) -> frozenset[str]:
        """Return the table and template codes of the module, case-folded.

        These are the codes a ``{vX}`` variable reads the filing indicator
        of: the table codes, their filing indicators and the module's
        ``filing_indicators``.

        Returns:
            frozenset[str]: The codes, case-folded.
        """
        codes = {table.code for table in self.tables}
        codes.update(table.filing_indicator for table in self.tables)
        codes.update(self.filing_indicators)
        return frozenset(code.casefold() for code in codes)


def load_module(source: str | os.PathLike[str] | Mapping[str, Any]) -> Module:
    """Read and check a module file.

    The ``format`` is ``dpm-module/1`` or ``dpm-synth-template/1``; the two
    share their fields. Fields a version does not know, such as dpm-synth's
    generation settings, are ignored.

    Args:
        source: The path of a JSON module file, or the parsed document.

    Returns:
        Module: The module.

    Raises:
        ModuleError: If the file cannot be read or is not JSON, or a field
            is missing or invalid; the message names it by its JSON path.
    """
    if isinstance(source, Mapping):
        return _module(source)
    path = Path(source)
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError as error:
        raise ModuleError("no such file") from error
    except (OSError, ValueError) as error:
        reason = error.strerror if isinstance(error, OSError) else None
        raise ModuleError(f"cannot read: {reason or error}") from error
    try:
        document = json.loads(text)
    except ValueError as error:
        raise ModuleError(f"not JSON: {error}") from error
    return _module(document)


def _module(document: object) -> Module:
    root = _mapping(document, "")
    found = root.get("format")
    if found not in FORMATS:
        expected = " or ".join(repr(name) for name in FORMATS)
        raise ModuleError(
            f"format: expected {expected}, got {_describe(found)}"
            if found is not None
            else f"format: required, {expected}"
        )
    tables = tuple(
        _table(item, f"tables[{index}]")
        for index, item in enumerate(_array(root, "tables", "", required=True))
    )
    if not tables:
        raise ModuleError("tables: at least one table is required")
    _unique(
        [table.code.casefold() for table in tables],
        "tables[{}].code".format,
        ", ignoring case",
    )
    places = [
        (f"tables[{index}].cells[{number}].id", cell.id)
        for index, table in enumerate(tables)
        for number, cell in enumerate(table.cells)
    ]
    _unique([cell for _, cell in places], lambda index: places[index][0])
    entries = _array(root, "rules", "")
    for index, entry in enumerate(entries):
        rule = _mapping(entry, f"rules[{index}]")
        _text(rule, "code", f"rules[{index}]")
        _text(rule, "expression", f"rules[{index}]")
    try:
        rules = tuple(rules_from(entries, "rules"))
    except RuleFileError as error:
        raise ModuleError(str(error)) from None
    rules = tuple(
        rule if rule.source is not None else replace(rule, source="eba")
        for rule in rules
    )
    _unique([rule.code for rule in rules], "rules[{}].code".format)
    filing_indicators = tuple(
        _filing_indicator(code, f"filing_indicators[{index}]")
        for index, code in enumerate(_array(root, "filing_indicators", ""))
    )
    _unique(filing_indicators, "filing_indicators[{}]".format)
    if filing_indicators:
        for index, table in enumerate(tables):
            if table.filing_indicator not in filing_indicators:
                raise ModuleError(
                    f"tables[{index}].filing_indicator: "
                    f"{table.filing_indicator!r} is not in filing_indicators"
                )
    return Module(
        format=found,
        release=_text(root, "release", ""),
        module=_text(root, "module", ""),
        tables=tables,
        rules=rules,
        entry_point=_optional_text(root, "entry_point", ""),
        reference_date=_date(root, "reference_date"),
        filing_indicators=filing_indicators,
        currency=_optional_text(root, "currency", ""),
        decimals=_decimals(root),
    )


def _table(value: object, path: str) -> Table:
    table = _mapping(value, path)
    code = _text(table, "code", path)
    keys = tuple(
        _open_key(item, f"{path}.open_keys[{index}]")
        for index, item in enumerate(_array(table, "open_keys", path))
    )
    _unique([key.column for key in keys], (path + ".open_keys[{}].column").format)
    cells = tuple(
        _cell(item, f"{path}.cells[{index}]")
        for index, item in enumerate(_array(table, "cells", path, required=True))
    )
    if not cells:
        raise ModuleError(f"{path}.cells: at least one cell is required")
    return Table(
        code=code,
        filing_indicator=_optional_text(table, "filing_indicator", path) or code,
        open_keys=keys,
        cells=cells,
    )


def _open_key(value: object, path: str) -> OpenKey:
    key = _mapping(value, path)
    code = _text(key, "code", path)
    return OpenKey(
        code=code,
        column=_optional_text(key, "column", path) or code,
        data_type=_optional_text(key, "data_type", path),
        items=_items(key, path),
    )


def _cell(value: object, path: str) -> Cell:
    cell = _mapping(value, path)
    unit = cell.get("unit")
    if unit is not None and not isinstance(unit, bool):
        raise ModuleError(
            f"{path}.unit: expected true, false or null, got {_describe(unit)}"
        )
    return Cell(
        id=_text(cell, "id", path),
        datapoint=_text(cell, "datapoint", path),
        row=_optional_text(cell, "row", path),
        column=_optional_text(cell, "column", path),
        sheet=_optional_text(cell, "sheet", path),
        data_type=_optional_text(cell, "data_type", path),
        items=_items(cell, path),
        unit=bool(unit),
    )


def _items(parent: Mapping[str, Any], path: str) -> tuple[str, ...] | None:
    values = parent.get("items")
    if values is None:
        return None
    if not isinstance(values, list):
        raise ModuleError(
            f"{path}.items: expected an array of item qnames, got {_describe(values)}"
        )
    for index, item in enumerate(values):
        if not isinstance(item, str) or not item.strip():
            raise ModuleError(
                f"{path}.items[{index}]: expected an item qname such as "
                f"'eba_qEC:qx16', got {_describe(item)}"
            )
    return tuple(values)


def _filing_indicator(value: object, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ModuleError(
            f"{path}: expected a filing indicator such as 'C_07.00', got "
            + _describe(value)
        )
    return value


def _decimals(root: Mapping[str, Any]) -> dict[str, int]:
    value = root.get("decimals")
    if value is None:
        return {}
    decimals = _mapping(value, "decimals")
    for code, number in decimals.items():
        if (
            isinstance(number, bool)
            or not isinstance(number, int)
            or abs(number) > _MAX_DECIMALS
        ):
            raise ModuleError(
                f"decimals.{code}: expected a whole number from -{_MAX_DECIMALS} "
                f"to {_MAX_DECIMALS}, got {_describe(number)}"
            )
    return dict(decimals)


def _date(root: Mapping[str, Any], name: str) -> date | None:
    text = _optional_text(root, name, "")
    if text is None:
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        raise ModuleError(
            f"{name}: expected a date such as '2026-12-31', got {text!r}"
        ) from None


def _unique(values: Sequence[str], where: Callable[[int], str], note: str = "") -> None:
    """Raise for a value that repeats an earlier one.

    Raises:
        ModuleError: Naming both places.
    """
    seen: dict[str, int] = {}
    for index, value in enumerate(values):
        if value in seen:
            raise ModuleError(
                f"{where(index)}: {value!r} repeats {where(seen[value])}{note}"
            )
        seen[value] = index


def _mapping(value: object, path: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        where = f"{path}: " if path else ""
        raise ModuleError(f"{where}expected an object, got {_describe(value)}")
    return value


def _array(
    parent: Mapping[str, Any], name: str, path: str, *, required: bool = False
) -> Sequence[Any]:
    where = f"{path}.{name}" if path else name
    value = parent.get(name)
    if value is None:
        if required:
            raise ModuleError(f"{where}: required")
        return []
    if not isinstance(value, list):
        raise ModuleError(f"{where}: expected an array, got {_describe(value)}")
    return value


def _text(parent: Mapping[str, Any], name: str, path: str) -> str:
    where = f"{path}.{name}" if path else name
    value = parent.get(name)
    if value is None:
        raise ModuleError(f"{where}: required")
    if not isinstance(value, str) or not value.strip():
        raise ModuleError(
            f"{where}: expected a non-empty string, got {_describe(value)}"
        )
    return value


def _optional_text(parent: Mapping[str, Any], name: str, path: str) -> str | None:
    where = f"{path}.{name}" if path else name
    value = parent.get(name)
    if value is None or value == "":
        return None
    if not isinstance(value, str):
        raise ModuleError(f"{where}: expected a string or null, got {_describe(value)}")
    return value


def _describe(value: object) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return repr(value)
    if isinstance(value, int | float):
        return f"the number {value}"
    if isinstance(value, Mapping):
        return "an object"
    if isinstance(value, list):
        return "an array"
    return type(value).__name__


__all__ = [
    "FORMATS",
    "MODULE_FORMAT",
    "NUMERIC_TYPES",
    "Cell",
    "Module",
    "ModuleError",
    "OpenKey",
    "Table",
    "cell_type",
    "load_module",
]
