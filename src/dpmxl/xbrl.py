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

import io
import os
import re
import warnings
from collections.abc import Hashable, Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal
from typing import Any

try:
    from dpmxbrl import Fact, FilingFinding, Report, read_report, write_xbrl_csv
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
_Packages = str | os.PathLike[str] | Sequence[str | os.PathLike[str]]

_NUMBER = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?")
_INTEGER = re.compile(r"[+-]?[0-9]+")
_ZONE = r"(?:Z|[+-][0-9]{2}:[0-9]{2})?"
_DATE = re.compile(rf"([0-9]{{4}}-[0-9]{{2}}-[0-9]{{2}}){_ZONE}")
_DATE_TIME = re.compile(
    rf"([0-9]{{4}}-[0-9]{{2}}-[0-9]{{2}})"
    rf"(?:T[0-9]{{2}}:[0-9]{{2}}:[0-9]{{2}}(?:\.[0-9]+)?)?{_ZONE}"
)
_QNAME = re.compile(r"[^\s:]+:[^\s:]+")
_DOMAIN = re.compile(r"/dict/dom/([^/#]+)$")
_LETTER_PART = re.compile(r"\.[a-z](?=\.|$)", re.IGNORECASE)
_BOOLEANS = {"true": True, "1": True, "false": False, "0": False}
_EXAMPLES = 5


class _Invalid(ValueError):
    """A value that does not read as its data type."""


@dataclass(frozen=True, slots=True)
class ReportFinding:
    """A problem placing a report's facts in its module's tables.

    Attributes:
        code: ``unplacedFact`` for facts in no table of the module, or
            without a value for an open key of their table;
            ``invalidValue`` for values that do not read as their cell's
            data type; ``duplicateFact`` for facts with the cell and open
            keys of an earlier fact, the keys written otherwise (such as
            ``007`` and ``7`` for an integer key). No rule reads them.
            ``otherEntryPoint`` for a ``previous`` report of another entry
            point of the same module, such as an earlier taxonomy.
        severity: ``error`` for the report, ``warning`` for a ``previous``
            report.
        message: What is wrong, as a sentence.
        count: How many facts.
        examples: Up to five, each a fact's location and the reason.
    """

    code: str
    severity: Severity
    message: str
    count: int = 1
    examples: tuple[str, ...] = ()


class ReportProvider:
    """A dpm-xl provider over a report read with dpm-xbrl.

    Each fact is placed in the module's table named by its template (any
    case, such as ``c_01.00`` for ``C_01.00``) at the cell its datapoint
    names, with the table's open keys from the fact's key columns. A file
    named by a filing indicator, such as ``f_19.00.dp.csv`` for tables
    ``F_19.00.a.dp`` and ``F_19.00.d.dp``, places each fact in the tables
    of that filing indicator that have its datapoint.

    XBRL-XML facts have no template or datapoint: with
    ``taxonomy_packages``, dpm-xbrl converts the report to xBRL-CSV
    through the taxonomy (``write_xbrl_csv``), which gives each fact its
    tables, datapoints and keys; the value, decimals and location stay
    the XML fact's. Nil facts are not reported values.

    Facts that cannot be placed are kept in
    [`unplaced`][dpmxl.xbrl.ReportProvider.unplaced]: no such table or
    datapoint, or an open key's column that is missing or empty. A
    duplicate of a placed fact is ignored: the first one counts (dpm-xbrl
    reports duplicates with different values under filing rule 2.16).

    Values are typed by the cell's data type: numbers (``m``, ``p``, ``i``,
    ``r``) carry the fact's decimals, else the report's ``decimals…``
    parameter for the type, else the module's ``decimals``, where ``INF``
    is exact; ``o`` (an ordinal) is an exact whole number, ``e`` an item,
    ``b`` and ``t`` Booleans (``t`` only ``true``), and ``d`` and ``dt``
    dates: a time or time zone is dropped, so ``2026-06-30T12:00:00`` and
    ``2026-06-30Z`` read as 2026-06-30. Anything else, ``es`` included, is
    text, where an empty string is a value and not null. A value that does
    not read as its type, such as ``NaN`` for a number, ``false`` for
    ``t`` or an empty or multiple item for ``e``, is kept in
    [`invalid`][dpmxl.xbrl.ReportProvider.invalid] and not placed. Open
    keys are typed the same way: items for an enumerated key, whole
    numbers for ``i`` and ``o``, dates for ``d`` and ``dt``, and stripped
    text otherwise. An item's prefix is the module's ``eba_`` name for its
    domain's namespace, whatever prefix the report declares for it.

    ``{vX}`` reads the report's filing indicator of template ``X``: a
    template without a positive one is not reported, even with facts
    (EBA filing rule 1.6). Only in a report without filing indicators is
    a template reported when one of its tables has facts. Report
    parameters answer the other variables, by name and ignoring case:
    ``refPeriod`` (the reference date), ``entityID``, ``baseCurrency``
    (an item of the DPM's currency domain, such as ``eba_CU:EUR``; the
    report's ``iso4217:EUR`` reads as one), the ``decimals…`` parameters
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
        invalid: The facts whose value does not read as their cell's type.
        findings: The unplaced and invalid facts as findings, the previous
            reports' as warnings.
    """

    def __init__(
        self,
        module: Module,
        report: Report,
        *,
        previous: Iterable[Report] = (),
        taxonomy_packages: _Packages = (),
    ) -> None:
        """Place the report's facts in the module's tables.

        Args:
            module: The module, such as [`load_module`][dpmxl.module.load_module]
                returns.
            report: The report, such as ``dpmxbrl.read_report`` returns.
            previous: Reports of the same entity and module for other
                periods, which ``time_shift`` picks from by reference date.
            taxonomy_packages: The taxonomy package ZIPs of an XBRL-XML
                report (and XBRL-XML ``previous`` reports).

        Raises:
            ValueError: If the report is of another entry point than the
                module, an XBRL-XML report comes without taxonomy packages,
                or a previous report has no reference date, the same one as
                another report, another entity or another module. A previous
                report of another entry point of the module, such as an
                earlier taxonomy, is an ``otherEntryPoint`` warning.
            dpmxbrl.ReportError: If dpm-xbrl cannot convert an XBRL-XML
                report with the taxonomy packages.
        """
        self.module = module
        self.report = report
        if (
            module.entry_point
            and report.entry_point
            and _entry(module.entry_point) != _entry(report.entry_point)
        ):
            raise ValueError(
                f"the report is of entry point {report.entry_point}, but module "
                f"{module.module} of {module.entry_point}"
            )
        self.previous: Mapping[date, ReportProvider] = {}
        self._periods: Mapping[date, ReportProvider] = {}
        self._tables = {table.code.casefold(): table for table in module.tables}
        self._indicators = {
            code.casefold(): filed for code, filed in report.filing_indicators.items()
        }
        self._templates = module.templates() | self._indicators.keys()
        self._parameters = {
            name.casefold(): value for name, value in report.parameters.items()
        }
        self._cells: dict[tuple[str, str], list[Cell]] = {}
        self._filed: dict[str, list[Table]] = {}
        for table in module.tables:
            self._filed.setdefault(table.filing_indicator.casefold(), []).append(table)
            for cell in table.cells:
                self._cells.setdefault((table.code, cell.datapoint), []).append(cell)
        pairs, skipped, namespaces = _converted(report, taxonomy_packages)
        key_prefixes = _item_prefixes(namespaces)
        value_prefixes = _item_prefixes(report.namespaces)
        self._rows: dict[str, dict[_RowKey, dict[str, Value]]] = {}
        self._facts: dict[Hashable, Fact] = {}
        unplaced: list[tuple[Fact, str]] = []
        invalid: list[tuple[Fact, str]] = []
        duplicates: list[tuple[Fact, str]] = []
        firsts: dict[tuple[str, str, _RowKey], tuple[Fact, Fact]] = {}
        for fact, source in pairs:
            placements = self._place(fact, key_prefixes)
            if isinstance(placements, str):
                unplaced.append((source, placements))
                continue
            try:
                value = self._value(placements[0][1][0], source, value_prefixes)
            except _Invalid as error:
                invalid.append((source, str(error)))
                continue
            respelled = None
            for table, cells, keys in placements:
                row = self._rows.setdefault(table.code, {}).setdefault(keys, {})
                slot = (table.code, cells[0].datapoint, keys)
                if cells[0].datapoint in row:
                    # A duplicate: the first fact counts. One with the same
                    # keys written otherwise is no duplicate to dpm-xbrl.
                    first, first_source = firsts[slot]
                    if first.keys != fact.keys:
                        respelled = first_source
                    continue
                firsts[slot] = (fact, source)
                row[cells[0].datapoint] = value
                for cell in cells:
                    self._facts[table.code, cell.id, keys] = source
            if respelled is not None:
                where = respelled.location or respelled.datapoint or respelled.concept
                duplicates.append((source, f"the cell and keys of {where}"))
        unplaced.extend(skipped)
        self.unplaced: tuple[Fact, ...] = tuple(fact for fact, _ in unplaced)
        self.invalid: tuple[Fact, ...] = tuple(fact for fact, _ in invalid)
        self.findings: tuple[ReportFinding, ...] = _findings(
            module, unplaced, invalid, "the report", "error", duplicates
        )
        previous = tuple(previous)
        if previous:
            self._link(previous, taxonomy_packages)

    def _link(self, previous: Sequence[Report], packages: _Packages) -> None:
        current = self.report.reference_date
        # A report without an entry point is of the module's, if it has one.
        entry_point = self.report.entry_point or self.module.entry_point
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
            name = f"the previous report for {moment.isoformat()}"
            if report.entity_id != self.report.entity_id:
                raise ValueError(
                    f"{name} is of entity {report.entity_id}, "
                    f"not {self.report.entity_id}"
                )
            other = (
                report.entry_point
                and entry_point
                and _entry(report.entry_point) != _entry(entry_point)
            )
            if other and _module_code(report.entry_point) != _module_code(entry_point):
                raise ValueError(
                    f"{name} is of module {_module_code(report.entry_point)}, "
                    f"not {_module_code(entry_point)}"
                )
            # Placed in this module's tables, whatever its taxonomy version.
            module = replace(self.module, entry_point=None) if other else self.module
            provider = ReportProvider(module, report, taxonomy_packages=packages)
            found[moment] = provider
            if other:
                self.findings += (
                    ReportFinding(
                        code="otherEntryPoint",
                        severity="warning",
                        message=f"{name[0].upper()}{name[1:]} is of entry point "
                        f"{report.entry_point}, not {entry_point}; its "
                        "facts are placed in this module's tables.",
                    ),
                )
            self.findings += tuple(
                replace(
                    finding,
                    severity="warning",
                    message=finding.message.replace("the report", name, 1),
                )
                for finding in provider.findings
            )
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

    def _place(
        self, fact: Fact, prefixes: Mapping[str, str]
    ) -> list[tuple[Table, list[Cell], _RowKey]] | str:
        """Return the tables, cells and keys of a fact, or why it has none."""
        datapoint = fact.datapoint
        if fact.template is None or not datapoint:
            return "it has no template and datapoint"
        # dpm-xbrl spells a template id of the EBA metadata, such as c_00-01.
        folded = fact.template.replace("-", ".").casefold()
        table = self._tables.get(folded)
        if table is not None and (table.code, datapoint) in self._cells:
            tables = [table]
        else:
            filed = self._filed.get(_LETTER_PART.sub("", folded), [])
            tables = [
                found for found in filed if (found.code, datapoint) in self._cells
            ]
            if not tables:
                if table is None and not filed:
                    return f"module {self.module.module} has no table {fact.template}"
                return f"table {fact.template} has no datapoint {datapoint}"
        placements = []
        for found in tables:
            keys = _keys(found, fact, prefixes)
            if isinstance(keys, str):
                return keys
            placements.append((found, self._cells[found.code, datapoint], keys))
        return placements

    def _value(self, cell: Cell, fact: Fact, prefixes: Mapping[str, str]) -> Value:
        text = fact.value
        if text is None:
            return None
        kind = cell.data_type
        stripped = text.strip()
        if kind in NUMERIC_TYPES:
            if not _NUMBER.fullmatch(stripped):
                raise _Invalid(f"{stripped!r} is not a number")
            return Number.of(Decimal(stripped), self._decimals(kind, fact))
        if kind == "o":
            if not _INTEGER.fullmatch(stripped):
                raise _Invalid(f"{stripped!r} is not a whole number")
            return Number(Decimal(stripped))
        if kind == "e":
            if not _QNAME.fullmatch(stripped):
                raise _Invalid(f"{stripped!r} is not one item")
            return Item.parse(_canonical(stripped, prefixes))
        if kind in {"b", "t"}:
            found = _BOOLEANS.get(stripped)
            if found is None or (kind == "t" and not found):
                kind_name = "true" if kind == "t" else "a Boolean"
                raise _Invalid(f"{stripped!r} is not {kind_name}")
            return found
        if kind in {"d", "dt"}:
            return _date(stripped, kind)
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
        nothing was reported. A code that is no table of the module but the
        filing indicator of some, such as abstract table ``C_02.00`` of
        ``C_02.00.a`` and ``C_02.00.b``, selects the cells of those tables
        together. A selector on an axis the cell lacks, or on an
        open axis (``*``), is ignored, as by a
        [`MemoryProvider`][dpmxl.provider.MemoryProvider].

        Returns:
            Sequence[DataPoint]: The data points.

        Raises:
            LookupError: If the module has no such table.
        """
        tables = self._parts(query.table)
        if not tables:
            raise LookupError(f"unknown table {query.table}")
        return [point for table in tables for point in self._select(table, query)]

    def _parts(self, code: str) -> Sequence[Table]:
        """Return the table of a code, or the tables it is the filing indicator of."""
        folded = code.casefold()
        table = self._tables.get(folded)
        return [table] if table is not None else self._filed.get(folded, [])

    def _select(self, table: Table, query: CellQuery) -> list[DataPoint]:
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

        Its ``location``, such as ``reports/c_47.00.csv:5`` or
        ``report.xbrl#f12``, leads back to the report's file.

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
            tuple[str, ...]: Key codes, of every table a filing indicator
            selects; empty for a closed or unknown table.
        """
        codes: list[str] = []
        for found in self._parts(table):
            codes.extend(key.code for key in found.open_keys if key.code not in codes)
        return tuple(codes)

    def is_template(self, code: str) -> bool:
        """Return whether a code is a table or template of the module or report.

        Returns:
            bool: Whether ``{vCode}`` reads a filing indicator.
        """
        return code.casefold() in self._templates

    def table_reported(self, table: str) -> bool | None:
        """Return the filing indicator of a template or table, ignoring case.

        A table without its own filing indicator answers with its
        ``filing_indicator``'s; a template without a positive filing
        indicator is not reported. Only when the report has no filing
        indicators is a template reported when one of its tables has facts.

        Returns:
            bool | None: Whether it was reported.
        """
        folded = table.casefold()
        if folded in self._indicators:
            return self._indicators[folded]
        found = self._tables.get(folded)
        if found is not None and found.filing_indicator.casefold() in self._indicators:
            return self._indicators[found.filing_indicator.casefold()]
        if self._indicators:
            return self._indicators.get(_LETTER_PART.sub("", folded), False)
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


def _module_code(url: str | None) -> str:
    """Return the module code of an entry point, its file name, case-folded."""
    return _entry(url or "").rsplit("/", 1)[-1]


def _entry(url: str) -> str:
    """Return an entry point without ``.json`` or ``.xsd``, for comparing."""
    folded = url.casefold()
    for suffix in (".json", ".xsd"):
        folded = folded.removesuffix(suffix)
    return folded


def _converted(
    report: Report, packages: _Packages
) -> tuple[list[tuple[Fact, Fact]], list[tuple[Fact, str]], Mapping[str, str]]:
    """Return the facts to place, each with the fact as reported.

    An xBRL-CSV report's facts are placed as they are. An XBRL-XML report
    is converted to xBRL-CSV with dpm-xbrl and its taxonomy packages; each
    converted fact is paired with the XML fact it came from.

    Returns:
        tuple: The pairs, the facts the conversion left out with the
        reason, and the namespaces of the facts to place.

    Raises:
        ValueError: If an XBRL-XML report comes without taxonomy packages.
    """
    if report.format != "xbrl-xml":
        return [(fact, fact) for fact in report.facts], [], report.namespaces
    if not packages:
        raise ValueError(
            "the facts of an XBRL-XML report are placed through its taxonomy: "
            "give its taxonomy packages (taxonomy_packages, or "
            "--taxonomy-package on the command line)"
        )
    buffer = io.BytesIO()
    with warnings.catch_warnings():
        # The XML facts keep their own decimals; the converted ones are unused.
        warnings.simplefilter("ignore")
        skipped = write_xbrl_csv(
            report, buffer, taxonomy_packages=packages, strict=False
        )
    converted = read_report(
        buffer.getvalue(), name="report.zip", taxonomy_packages=packages
    )
    sources: dict[Hashable, Fact] = {}
    for fact in report.facts:
        if fact.concept:
            sources.setdefault(_identity(fact, report.namespaces), fact)
    pairs = [
        (fact, sources.get(_identity(fact, converted.namespaces), fact))
        if fact.concept
        else (fact, fact)
        for fact in converted.facts
    ]
    return (
        pairs,
        [(found.fact, found.reason) for found in skipped],
        converted.namespaces,
    )


def _identity(fact: Fact, namespaces: Mapping[str, str]) -> Hashable:
    """Return a fact's concept and dimensions by namespace, not prefix."""

    def name(qname: str) -> str:
        prefix, colon, local = qname.partition(":")
        return f"{{{namespaces.get(prefix, prefix)}}}{local}" if colon else qname

    return (
        name(fact.concept or ""),
        frozenset(
            (name(axis), name(member)) for axis, member in fact.dimensions.items()
        ),
        frozenset(
            (name(axis), value.strip()) for axis, value in fact.typed_dimensions.items()
        ),
    )


def _item_prefixes(namespaces: Mapping[str, str]) -> dict[str, str]:
    """Map each prefix of an EBA domain namespace to its ``eba_`` name.

    ``.../dict/dom/CU`` is ``eba_CU``, whatever prefix a report declares.

    Returns:
        dict[str, str]: Each prefix that differs from its ``eba_`` name.
    """
    prefixes = {}
    for prefix, namespace in namespaces.items():
        match = _DOMAIN.search(namespace)
        if match is not None and prefix != f"eba_{match[1]}":
            prefixes[prefix] = f"eba_{match[1]}"
    return prefixes


def _canonical(qname: str, prefixes: Mapping[str, str]) -> str:
    prefix, _, local = qname.partition(":")
    found = prefixes.get(prefix)
    return f"{found}:{local}" if found else qname


def _date(text: str, kind: str | None) -> date:
    found = (_DATE if kind == "d" else _DATE_TIME).fullmatch(text)
    try:
        if found is None:
            raise ValueError
        return date.fromisoformat(found[1])
    except ValueError:
        raise _Invalid(f"{text!r} is not a date") from None


def _closed(code: str | None) -> str | None:
    return None if code == "*" else code


def _keys(table: Table, fact: Fact, prefixes: Mapping[str, str]) -> _RowKey | str:
    """Return a fact's open keys in a table, or why it lacks one."""
    columns = {column.casefold(): text for column, text in fact.keys.items()}
    keys = []
    for key in table.open_keys:
        text = columns.get(key.column.casefold())
        if text is None:
            return f"it has no column {key.column} for open key {key.code}"
        text = text.strip()
        if not text:
            return f"open key {key.code} is empty"
        try:
            keys.append((key.code, _key(key, text, prefixes)))
        except _Invalid as error:
            return f"open key {key.code}: {error}"
    return tuple(keys)


def _key(key: OpenKey, text: str, prefixes: Mapping[str, str]) -> Value:
    if key.items is not None:
        if not _QNAME.fullmatch(text):
            raise _Invalid(f"{text!r} is not one item")
        return Item.parse(_canonical(text, prefixes))
    if key.data_type in {"i", "o"}:
        if not _INTEGER.fullmatch(text):
            raise _Invalid(f"{text!r} is not a whole number")
        return Number(Decimal(text))
    if key.data_type in {"d", "dt"}:
        return _date(text, key.data_type)
    return text


def _findings(
    module: Module,
    unplaced: Sequence[tuple[Fact, str]],
    invalid: Sequence[tuple[Fact, str]],
    name: str,
    severity: Severity,
    duplicates: Sequence[tuple[Fact, str]] = (),
) -> tuple[ReportFinding, ...]:
    found = []
    for code, facts in (
        ("unplacedFact", unplaced),
        ("invalidValue", invalid),
        ("duplicateFact", duplicates),
    ):
        if not facts:
            continue
        count = len(facts)
        one = count == 1
        if code == "duplicateFact":
            problem = (
                f"{'has' if one else 'have'} the cell and open keys of an earlier "
                "fact, with the keys written otherwise"
            )
        elif code == "unplacedFact":
            problem = (
                f"{'is' if one else 'are'} in no table of module {module.module}, "
                f"or lack{'s' if one else ''} an open key of "
                f"{'its' if one else 'their'} table"
            )
        else:
            problem = (
                f"{'has' if one else 'have'} a value that does not read as "
                f"{'its' if one else 'their'} cell's data type"
            )
        found.append(
            ReportFinding(
                code=code,
                severity=severity,
                message=f"{count} fact{'' if one else 's'} of {name} {problem}, so "
                f"no rule reads {'it' if one else 'them'}.",
                count=count,
                examples=tuple(
                    f"{fact.location or fact.datapoint or fact.concept}: {reason}"
                    for fact, reason in facts[:_EXAMPLES]
                ),
            )
        )
    return tuple(found)


@dataclass(frozen=True, slots=True)
class ReportCheck:
    """The filing findings and rule results of one report.

    Attributes:
        module: The module the report was checked against.
        report: The report.
        rules: One run per rule of the module, in order.
        unplaced: The facts in no table of the module.
        findings: The unplaced and invalid facts, as
            [`ReportProvider.findings`][dpmxl.xbrl.ReportProvider] gives them.
        invalid: The facts whose value does not read as their cell's type.
    """

    module: Module
    report: Report
    rules: tuple[RuleRun, ...]
    unplaced: tuple[Fact, ...] = ()
    findings: tuple[ReportFinding, ...] = ()
    invalid: tuple[Fact, ...] = ()

    @property
    def filing(self) -> tuple[FilingFinding, ...]:
        """The EBA filing rules the report breaks, as dpm-xbrl found them."""
        return self.report.filing

    def failed(self, fail_on: Severity = "error") -> bool:
        """Return whether a finding or rule at or above a severity failed.

        Args:
            fail_on: ``error`` counts only errors, ``warning`` warnings too.

        Returns:
            bool: Whether a filing finding, a finding of
            [`findings`][dpmxl.xbrl.ReportCheck.findings], or a rule that
            failed or is an ``error``, has a severity at or above ``fail_on``.
        """
        failing = {"error"} if fail_on == "error" else {"error", "warning"}
        return (
            any(finding.severity in failing for finding in self.filing)
            or any(finding.severity in failing for finding in self.findings)
            or any(
                run.status in {"failed", "error"} and run.rule.severity in failing
                for run in self.rules
            )
        )


def check_report(
    module: Module | str | os.PathLike[str] | Mapping[str, Any],
    report: Report | str | os.PathLike[str] | bytes,
    *,
    taxonomy_packages: _Packages = (),
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
            taxonomy; an XBRL-XML report needs them to place its facts (see
            [`ReportProvider`][dpmxl.xbrl.ReportProvider]).
        name: The report's file name, for bytes; the EBA file naming rule
            checks it.
        previous: Reports of the same entity and module for earlier
            periods, or paths to read them from with the same taxonomy
            packages, for ``time_shift``. Only the report itself is checked
            against the filing rules.

    Returns:
        ReportCheck: The filing findings, the facts that could not be placed
        and one rule run per rule; rules that are inactive or for other
        modules are skipped.

    Raises:
        dpmxbrl.ReportError: If a report cannot be read or converted.
        ModuleError: If the module file is not valid.
        ValueError: If a report is of another entry point than the module,
            an XBRL-XML report comes without taxonomy packages, or the
            previous reports' reference dates or entities do not fit.
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
    provider = ReportProvider(
        module, report, previous=earlier, taxonomy_packages=taxonomy_packages
    )
    runs = evaluate_rules(module.rules, provider, module=module.module)
    return ReportCheck(
        module,
        report,
        tuple(runs),
        provider.unplaced,
        provider.findings,
        provider.invalid,
    )


__all__ = [
    "DECIMALS_PARAMETERS",
    "ReportCheck",
    "ReportFinding",
    "ReportProvider",
    "check_report",
]
