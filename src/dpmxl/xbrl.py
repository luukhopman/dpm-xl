"""Evaluate a module's rules on an XBRL report read with dpm-xbrl.

Needs the ``xbrl`` extra (``pip install "dpm-xl[xbrl]"``), which installs
[dpm-xbrl](https://luukhopman.github.io/dpm-xbrl/).
[`ReportProvider`][dpmxl.xbrl.ReportProvider] places the facts of a
dpm-xbrl ``Report`` in the tables of a [`Module`][dpmxl.module.Module] by
their datapoints, so dpm-xl can evaluate the module's rules on them, and
[`check_report`][dpmxl.xbrl.check_report] does both checks a report needs:
the EBA filing rules dpm-xbrl checks and the module's validation rules.

Examples:
    >>> check = check_report("examples/xbrl-module.json", "examples/xbrl-report")
    >>> [(run.rule.code, run.status) for run in check.rules][:3]
    [('e0001', 'failed'), ('e0002', 'passed'), ('e0003', 'failed')]
    >>> check.filing, check.failed()
    ((), True)
"""

from __future__ import annotations

import os
from collections.abc import Hashable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

try:
    from dpmxbrl import Fact, FilingFinding, Report, read_report
except ModuleNotFoundError as error:  # pragma: no cover - depends on the install
    if error.name != "dpmxbrl":
        raise
    raise ModuleNotFoundError(
        'dpmxl.xbrl needs dpm-xbrl: pip install "dpm-xl[xbrl]"', name="dpmxbrl"
    ) from None

from .ast import Item
from .evaluator import _shift_date
from .module import NUMERIC_TYPES, Cell, Module, OpenKey, Table, load_module
from .provider import CellQuery, DataPoint, axis_matcher
from .recordset import EvaluationError
from .rules import RuleRun, Severity, evaluate_rules
from .values import Number, Value

DECIMALS_PARAMETERS: Mapping[str, str] = {
    "m": "decimalsMonetary",
    "p": "decimalsPercentage",
    "i": "decimalsInteger",
    "r": "decimalsDecimal",
}
"""The report parameter that gives the decimals of each numeric data type."""

_RowKey = tuple[tuple[str, Value], ...]


class ReportProvider:
    """A dpm-xl provider over a report read with dpm-xbrl.

    Each fact is placed in the module's table named by its template (any
    case, such as ``c_01.00`` for ``C_01.00``) at the cell its datapoint
    names; a fact without a template, as in XBRL-XML read without a
    taxonomy, is placed by its datapoint when only one table has it. Facts
    that cannot be placed are kept in
    [`unplaced`][dpmxl.xbrl.ReportProvider.unplaced].

    Values are typed by the cell's data type: numbers (``m``, ``p``, ``i``,
    ``r``) carry the fact's decimals, else the report's ``decimals…``
    parameter for the type, else the module's ``decimals``, where ``INF``
    is exact; ``o`` (an ordinal) is an exact whole number, ``e`` an item,
    ``b`` and ``t`` Booleans, and ``d`` a date, as is a ``dt`` value
    without a time; anything else, ``es`` included, is text, where an empty
    string is a value and not null. Text that does not read as its type
    stays text, so a rule using it is an error. Open keys are typed the
    same way: items for an enumerated key, numbers for ``i`` and ``o``,
    dates for ``d`` and ``dt``, text otherwise.

    ``{vX}`` reads the report's filing indicator of template ``X``;
    without one, a template is reported when it has facts. Report
    parameters answer the other variables, by name and ignoring case:
    ``refPeriod`` (the reference date), ``entityID``, ``baseCurrency``
    (an item such as ``iso4217:EUR``), the ``decimals…`` parameters
    (``INF`` is null), ``ReportingLevel`` (``con`` or ``ind``, from the
    entity identifier's suffix) and every other parameter of the report.

    ``time_shift`` on another period reads the ``previous`` report whose
    reference date is ``count`` periods before this report's (``refPeriod``
    2026-12-31 and ``time_shift(x, Q, 1)`` read the report for 2026-09-30),
    placed and typed by the same module. Without such a report the rule is
    ``unsupported``, and its message names the reference date it needs.

    Every optional method of a [`DataProvider`][dpmxl.provider.DataProvider]
    but ``table_group`` and ``operation`` is implemented. A
    ``ReportProvider`` is safe to read from several threads.

    Attributes:
        module: The module.
        report: The report.
        previous: Providers over the earlier reports, by reference date.
        unplaced: The facts that are in no table of the module.
    """

    def __init__(
        self, module: Module, report: Report, *, previous: Iterable[Report] = ()
    ) -> None:
        """Place the report's facts in the module's tables.

        Args:
            module: The module, such as [`load_module`][dpmxl.module.load_module]
                returns.
            report: The report, such as ``dpmxbrl.read_report`` returns.
            previous: Reports of the same module for other periods, which
                ``time_shift`` picks from by reference date.

        Raises:
            ValueError: If a previous report has no reference date, or the
                same one as this report or another previous report.
        """
        self.module = module
        self.report = report
        self.previous: Mapping[date, ReportProvider] = {}
        self._periods: Mapping[date, ReportProvider] = {}
        previous = tuple(previous)
        if previous:
            self._link(previous)
        self._tables = {table.code.casefold(): table for table in module.tables}
        self._indicators = {
            code.casefold(): filed for code, filed in report.filing_indicators.items()
        }
        self._templates = module.templates() | self._indicators.keys()
        self._parameters = {
            name.casefold(): value for name, value in report.parameters.items()
        }
        cells: dict[tuple[str, str], list[Cell]] = {}
        owners: dict[str, set[str]] = {}
        for table in module.tables:
            for cell in table.cells:
                cells.setdefault((table.code, cell.datapoint), []).append(cell)
                owners.setdefault(cell.datapoint, set()).add(table.code)
        self._rows: dict[str, dict[_RowKey, dict[str, Value]]] = {}
        self._facts: dict[Hashable, Fact] = {}
        unplaced: list[Fact] = []
        for fact in report.facts:
            table = self._place(fact, owners)
            found = cells.get((table.code, fact.datapoint or "")) if table else None
            if table is None or not found:
                unplaced.append(fact)
                continue
            columns = {key.column.casefold(): key for key in table.open_keys}
            keys = tuple(
                (key.code, _key(key, text))
                for column, text in fact.keys.items()
                if (key := columns.get(column.casefold())) is not None
            )
            row = self._rows.setdefault(table.code, {}).setdefault(keys, {})
            row[found[0].datapoint] = self._value(found[0], fact)
            for cell in found:
                self._facts[table.code, cell.id, keys] = fact
        self.unplaced: tuple[Fact, ...] = tuple(unplaced)

    def _link(self, previous: Sequence[Report]) -> None:
        current = self.report.reference_date
        if current is None:
            raise ValueError("the report has no reference date to shift from")
        found: dict[date, ReportProvider] = {}
        for report in previous:
            moment = report.reference_date
            if moment is None:
                raise ValueError("a previous report has no reference date")
            if moment == current or moment in found:
                raise ValueError(
                    f"two reports have the reference date {moment.isoformat()}"
                )
            found[moment] = ReportProvider(self.module, report)
        self.previous = dict(sorted(found.items()))
        periods = {current: self, **found}
        for provider in (self, *found.values()):
            provider._periods = periods

    def earlier_report(self, period: str, count: int) -> ReportProvider | None:
        """Return the report ``count`` periods earlier (later when negative).

        It is the report among ``previous`` (or this one) whose reference
        date is this report's moved by ``count`` periods back, the way
        ``time_shift`` moves dates.

        Returns:
            ReportProvider | None: That report, or ``None`` when there is
            none or this report has no reference date.
        """
        current = self.report.reference_date
        if current is None:
            return None
        try:
            return self._periods.get(_shift_date(current, period, -count))
        except EvaluationError:
            return None

    def _place(self, fact: Fact, owners: Mapping[str, set[str]]) -> Table | None:
        if fact.template is not None:
            return self._tables.get(fact.template.casefold())
        tables = owners.get(fact.datapoint or "", set())
        return self.module.table(next(iter(tables))) if len(tables) == 1 else None

    def _value(self, cell: Cell, fact: Fact) -> Value:
        text = fact.value
        if text is None:
            return None
        kind = cell.data_type
        try:
            if kind in NUMERIC_TYPES:
                return Number.of(Decimal(text.strip()), self._decimals(kind, fact))
            if kind == "o":
                return Number(Decimal(int(text.strip())))
            if kind == "e":
                return Item.parse(text)
            if kind in {"b", "t"}:
                return {"true": True, "1": True, "false": False, "0": False}[
                    text.strip()
                ]
            if kind in {"d", "dt"}:
                return date.fromisoformat(text.strip())
        except (InvalidOperation, ValueError, KeyError):
            return text
        return text

    def _decimals(self, kind: str, fact: Fact) -> int | str | None:
        if fact.decimals is not None:
            return fact.decimals
        found = self.report.decimals_parameters.get(DECIMALS_PARAMETERS[kind])
        if found is not None:
            return found
        return self.module.decimals.get(kind)

    def select(self, query: CellQuery) -> Sequence[DataPoint]:
        """Return the selected cells, one per reported key combination.

        A closed table gives every selected cell, with ``value=None`` where
        nothing was reported. A selector on an axis the cell lacks, or on an
        open axis (``*``), is ignored, as by a
        [`MemoryProvider`][dpmxl.provider.MemoryProvider].

        Returns:
            Sequence[DataPoint]: The data points.

        Raises:
            LookupError: If the module has no such table.
        """
        table = self._tables.get(query.table.casefold())
        if table is None:
            raise LookupError(f"unknown table {query.table}")
        matchers = [axis_matcher(query.rows), axis_matcher(query.columns)]
        matchers.append(axis_matcher(query.sheets))
        selected = [
            cell
            for cell in table.cells
            if all(
                code in (None, "*") or matcher(code)
                for code, matcher in zip(
                    (cell.row, cell.column, cell.sheet), matchers, strict=True
                )
            )
        ]
        rows = self._rows.get(table.code, {})
        keyed: Sequence[_RowKey] = list(rows) if table.open_keys else [()]
        return [
            DataPoint(
                table=table.code,
                row=_closed(cell.row),
                column=_closed(cell.column),
                sheet=_closed(cell.sheet),
                keys=dict(keys),
                value=rows.get(keys, {}).get(cell.datapoint),
                ref=(table.code, cell.id, keys),
            )
            for keys in keyed
            for cell in selected
        ]

    def fact(self, point: DataPoint) -> Fact | None:
        """Return the reported fact behind a data point.

        Its ``location``, such as ``reports/c_47.00.csv:5``, leads back to
        the report's file.

        Returns:
            Fact | None: The fact, or ``None`` for a cell nothing was
            reported for or a point of another provider.

        Examples:
            >>> from dpmxl import CellQuery
            >>> from dpmxbrl import read_report
            >>> from dpmxl.module import load_module
            >>> provider = ReportProvider(
            ...     load_module("examples/xbrl-module.json"),
            ...     read_report("examples/xbrl-report"),
            ... )
            >>> point = provider.select(CellQuery("C_47.00"))[3]
            >>> point.label(), point.value.value, point.value.tolerance
            ('{tC_47.00, r0040, c0010}', Decimal('1045000'), Decimal('5E+2'))
            >>> provider.fact(point).location
            'reports/c_47.00.csv:5'
        """
        return self._facts.get(point.ref) if point.ref is not None else None

    def open_keys(self, table: str) -> tuple[str, ...]:
        """Return the open key codes of a table.

        Returns:
            tuple[str, ...]: Key codes; empty for a closed or unknown table.
        """
        found = self._tables.get(table.casefold())
        return tuple(key.code for key in found.open_keys) if found else ()

    def is_template(self, code: str) -> bool:
        """Return whether a code is a table or template of the module or report.

        Returns:
            bool: Whether ``{vCode}`` reads a filing indicator.
        """
        return code.casefold() in self._templates

    def table_reported(self, table: str) -> bool | None:
        """Return the filing indicator of a template or table, ignoring case.

        A table without its own filing indicator answers with its
        ``filing_indicator``'s; a template the report gives no filing
        indicator for is reported when one of its tables has facts.

        Returns:
            bool | None: Whether it was reported.
        """
        folded = table.casefold()
        if folded in self._indicators:
            return self._indicators[folded]
        found = self._tables.get(folded)
        if found is not None and found.filing_indicator.casefold() in self._indicators:
            return self._indicators[found.filing_indicator.casefold()]
        return any(
            rows and folded in (code.casefold(), self._filed_as(code))
            for code, rows in self._rows.items()
        )

    def _filed_as(self, code: str) -> str:
        return self._tables[code.casefold()].filing_indicator.casefold()

    def parameter(self, name: str) -> Value:
        """Return a report parameter, ignoring case.

        Returns:
            Value: The parameter, or ``None`` when the report lacks it.
        """
        folded = name.casefold()
        report = self.report
        if folded == "refperiod":
            return report.reference_date
        if folded == "entityid":
            return report.entity_id
        if folded == "basecurrency":
            return Item.parse(report.base_currency) if report.base_currency else None
        if folded == "reportinglevel":
            suffix = (report.entity_id or "").rpartition(".")[2].casefold()
            return suffix if suffix in {"con", "ind"} else None
        for parameter, found in report.decimals_parameters.items():
            if parameter.casefold() == folded:
                if found is None or found == "INF":
                    return None
                return Number(Decimal(found))
        return self._parameters.get(folded)


def _closed(code: str | None) -> str | None:
    return None if code == "*" else code


def _key(key: OpenKey, text: str) -> Value:
    if key.items:
        return Item.parse(text)
    try:
        if key.data_type in {"i", "o"}:
            return Number(Decimal(text.strip()))
        if key.data_type in {"d", "dt"}:
            return date.fromisoformat(text.strip())
    except (InvalidOperation, ValueError):
        return text
    return text


@dataclass(frozen=True, slots=True)
class ReportCheck:
    """The filing findings and rule results of one report.

    Attributes:
        module: The module the report was checked against.
        report: The report.
        rules: One run per rule of the module, in order.
        unplaced: The facts in no table of the module.
    """

    module: Module
    report: Report
    rules: tuple[RuleRun, ...]
    unplaced: tuple[Fact, ...] = ()

    @property
    def filing(self) -> tuple[FilingFinding, ...]:
        """The EBA filing rules the report breaks, as dpm-xbrl found them."""
        return self.report.filing

    def failed(self, fail_on: Severity = "error") -> bool:
        """Return whether a finding or rule at or above a severity failed.

        Args:
            fail_on: ``error`` counts only errors, ``warning`` warnings too.

        Returns:
            bool: Whether a filing finding, or a rule that failed or is an
            ``error``, has a severity at or above ``fail_on``.
        """
        failing = {"error"} if fail_on == "error" else {"error", "warning"}
        return any(finding.severity in failing for finding in self.filing) or any(
            run.status in {"failed", "error"} and run.rule.severity in failing
            for run in self.rules
        )


def check_report(
    module: Module | str | os.PathLike[str] | Mapping[str, Any],
    report: Report | str | os.PathLike[str] | bytes,
    *,
    taxonomy_packages: str | os.PathLike[str] | Sequence[str | os.PathLike[str]] = (),
    name: str | None = None,
    previous: Sequence[Report | str | os.PathLike[str]] = (),
) -> ReportCheck:
    """Check a report's filing rules and its module's validation rules.

    Args:
        module: The module, or a module file for
            [`load_module`][dpmxl.module.load_module].
        report: The report, or what ``dpmxbrl.read_report`` reads: a path or
            the bytes of an xBRL-CSV package or XBRL-XML instance.
        taxonomy_packages: Taxonomy package ZIPs for ``read_report``, which
            resolve xBRL-CSV metadata and add the filing rules that need the
            taxonomy.
        name: The report's file name, for bytes; the EBA file naming rule
            checks it.
        previous: Reports of the same module for earlier periods, or paths
            to read them from with the same taxonomy packages, for
            ``time_shift`` (see [`ReportProvider`][dpmxl.xbrl.ReportProvider]).
            Only the report itself is checked against the filing rules.

    Returns:
        ReportCheck: The filing findings and one rule run per rule; rules
        that are inactive or for other modules are skipped.

    Raises:
        dpmxbrl.ReportError: If a report cannot be read.
        ModuleError: If the module file is not valid.
        ValueError: If the reports' reference dates are missing or repeat.
    """
    if not isinstance(module, Module):
        module = load_module(module)
    if not isinstance(report, Report):
        report = read_report(report, name=name, taxonomy_packages=taxonomy_packages)
    earlier = [
        found
        if isinstance(found, Report)
        else read_report(found, taxonomy_packages=taxonomy_packages)
        for found in previous
    ]
    provider = ReportProvider(module, report, previous=earlier)
    runs = evaluate_rules(module.rules, provider, module=module.module)
    return ReportCheck(module, report, tuple(runs), provider.unplaced)


__all__ = [
    "DECIMALS_PARAMETERS",
    "ReportCheck",
    "ReportProvider",
    "check_report",
]
