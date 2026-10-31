import importlib
import sys
from dataclasses import replace
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from dpmxl import CellQuery, Item, Number, evaluate_rule
from dpmxl.module import Module, load_module
from dpmxl.provider import EarlierRef

dpmxbrl = pytest.importorskip("dpmxbrl")

from dpmxbrl import Fact, FilingFinding, Report, write_xbrl_csv  # ruff: ignore[module-import-not-at-top-of-file]

from dpmxl.xbrl import ReportProvider, check_report  # ruff: ignore[module-import-not-at-top-of-file]

EXAMPLES = Path(__file__).parent.parent / "examples"


def cell(id_, datapoint, data_type, row="0010", column="0010", **extra):
    return {
        "id": id_,
        "row": row,
        "column": column,
        "datapoint": datapoint,
        "data_type": data_type,
        **extra,
    }


MODULE = load_module(
    {
        "format": "dpm-module/1",
        "release": "4.2",
        "module": "TEST",
        "decimals": {"r": 2},
        "tables": [
            {
                "code": "C_01.00",
                "cells": [
                    cell("m", "dpm", "m", "0010"),
                    cell("p", "dpp", "p", "0020"),
                    cell("i", "dpi", "i", "0030"),
                    cell("r", "dpr", "r", "0040"),
                    cell("e", "dpe", "e", "0050", items=["eba_CU:EUR"]),
                    cell("es", "dpes", "es", "0060"),
                    cell("b", "dpb", "b", "0070"),
                    cell("d", "dpd", "d", "0080"),
                    cell("s", "dps", "s", "0090"),
                    cell("x", "dpx", "m", "0100"),
                    cell("n", "dpn", "m", "0110"),
                    cell("t", "dpt", "t", "0120"),
                    cell("dt", "dpdt", "dt", "0130"),
                    cell("dt2", "dpdt2", "dt", "0140"),
                    cell("u", "dpu", "u", "0150"),
                    cell("ord", "dpord", "o", "0160"),
                    cell("es2", "dpes2", "es", "0170"),
                ],
            },
            {
                "code": "C_07.00.a",
                "filing_indicator": "C_07.00",
                "open_keys": [
                    {"code": "qCC", "column": "CC", "items": ["eba_CU:EUR"]},
                    {"code": "qNUM", "data_type": "i"},
                    {"code": "qDAT", "data_type": "d"},
                    {"code": "qTXT"},
                ],
                "cells": [cell("o", "dpo", "m", "*", "0010")],
            },
            {"code": "C_09.00", "cells": [cell("c9", "dp9", "m")]},
            {"code": "C_10.00", "cells": [cell("c10", "dp10", "m")]},
        ],
        "rules": [
            {"code": "v1", "expression": "{tC_01.00, r0010, c0010} > 0"},
            {
                "code": "v2",
                "expression": "{tC_01.00, r0010, c0010} > 2000",
                "severity": "warning",
            },
            {
                "code": "v3",
                "expression": "{tC_01.00, r0010, c0010} > 0",
                "modules": ["OTHER"],
            },
            {
                "code": "v4",
                "expression": "{tC_01.00, r0010, c0010} > 0",
                "active": False,
            },
        ],
    }
)


def report(facts, **changes) -> Report:
    fields: dict[str, Any] = {
        "format": "xbrl-csv",
        "entry_point": None,
        "entity_scheme": "https://eurofiling.info/eu/rs",
        "entity_id": "LEI00000000000000000.CON",
        "reference_date": date(2026, 12, 31),
        "base_currency": "iso4217:EUR",
        "parameters": {"refPeriod": "2026-12-31", "Custom": "x"},
        "decimals_parameters": {
            "decimalsMonetary": -3,
            "decimalsPercentage": 4,
            "decimalsInteger": "INF",
        },
        "filing_indicators": {"C_01.00": True, "C_07.00": True, "C_09.00": False},
        "facts": tuple(facts),
        "namespaces": {},
    }
    fields.update(changes)
    return Report(**fields)


def fact(datapoint, value, template="c_01.00", **extra):
    return Fact(value=value, datapoint=datapoint, template=template, **extra)


def values(provider, table="C_01.00"):
    return {point.row: point.value for point in provider.select(CellQuery(table))}


def test_values_are_typed_by_the_cells_data_type() -> None:
    provider = ReportProvider(
        MODULE,
        report(
            [
                fact("dpm", "1204000"),
                fact("dpp", "0.0498"),
                fact("dpi", "12"),
                fact("dpr", "1.5"),
                fact("dpe", "eba_CU:EUR"),
                fact("dpes", "eba_CU:EUR eba_CU:USD"),
                fact("dpt", "true"),
                fact("dpdt", "2026-06-30"),
                fact("dpdt2", "2026-06-30T12:00:00"),
                fact("dpu", "https://example.com/a"),
                fact("dpord", "3"),
                fact("dpes2", ""),
                fact("dpb", "true"),
                fact("dpd", "2026-06-30"),
                fact("dps", "text"),
                fact("dpn", None),
            ]
        ),
    )
    found = values(provider)
    assert found["0010"] == Number.of(1204000, -3)
    assert found["0020"] == Number.of(Decimal("0.0498"), 4)
    assert found["0030"] == Number(Decimal(12))  # decimalsInteger INF: exact
    assert found["0040"] == Number.of(Decimal("1.5"), 2)  # the module's decimals
    assert found["0050"] == Item("CU", "EUR")
    assert found["0060"] == "eba_CU:EUR eba_CU:USD"  # es is text
    assert found["0070"] is True
    assert found["0080"] == date(2026, 6, 30)
    assert found["0090"] == "text"
    assert found["0110"] is None
    assert found["0120"] is True
    assert found["0130"] == date(2026, 6, 30)
    assert found["0140"] == date(2026, 6, 30)  # a date and time: its date
    assert found["0150"] == "https://example.com/a"
    assert found["0160"] == Number(Decimal(3))
    assert found["0170"] == ""  # an empty string is a value, not null


def test_a_facts_own_decimals_come_first() -> None:
    provider = ReportProvider(
        MODULE, report([fact("dpm", "5", decimals=2), fact("dpp", "1", decimals="INF")])
    )
    found = values(provider)
    assert found["0010"] == Number.of(5, 2)
    assert found["0020"] == Number(Decimal(1))


def test_a_closed_table_gives_every_cell() -> None:
    provider = ReportProvider(MODULE, report([]))
    assert set(values(provider)) == {f"{row:04}" for row in range(10, 180, 10)}
    assert set(values(provider).values()) == {None}
    selected = provider.select(CellQuery("c_01.00", rows=None))
    assert selected[0].table == "C_01.00"
    with pytest.raises(LookupError):
        provider.select(CellQuery("C_99.00"))


def test_open_keys_are_typed_and_open_axes_ignore_selectors() -> None:
    keys = {
        "CC": "eba_CU:EUR",
        "qNUM": "3",
        "qDAT": "2026-01-31",
        "qTXT": "LEI",
        "unit": "iso4217:EUR",
    }
    provider = ReportProvider(
        MODULE, report([fact("dpo", "7", template="C_07.00.a", keys=keys)])
    )
    (point,) = provider.select(CellQuery("C_07.00.a"))
    assert point.row is None
    assert point.keys == {
        "qCC": Item("CU", "EUR"),
        "qNUM": Number(Decimal(3)),
        "qDAT": date(2026, 1, 31),
        "qTXT": "LEI",
    }
    assert provider.open_keys("c_07.00.a") == ("qCC", "qNUM", "qDAT", "qTXT")
    assert provider.open_keys("C_99.00") == ()
    result = evaluate_rule("sum({tC_07.00.a, c0010} group by qCC) = 7", provider)
    assert result.status == "passed"


def test_is_template_reads_the_module_templates_once(monkeypatch) -> None:
    calls = []
    templates = Module.templates

    def counted(module: Module) -> frozenset[str]:
        calls.append(module)
        return templates(module)

    monkeypatch.setattr(Module, "templates", counted)
    provider = ReportProvider(MODULE, report([]))
    for _ in range(3):
        assert provider.is_template("c_07.00.A")
        assert not provider.is_template("ReportingLevel")
    assert len(calls) <= 1


def test_facts_outside_the_module_are_unplaced() -> None:
    placed = fact("dp10", "1", template="C_10.00")
    others = [
        fact("dp404", "1", location="reports/c_01.00.csv:2"),
        fact("dpm", "1", template="C_99.00"),
        fact("dp10", "1", template=None),
    ]
    provider = ReportProvider(MODULE, report([placed, *others]))
    assert provider.unplaced == tuple(others)
    assert values(provider, "C_10.00") == {"0010": Number.of(1, -3)}
    (finding,) = provider.findings
    assert (finding.code, finding.severity, finding.count) == (
        "unplacedFact",
        "error",
        3,
    )
    assert finding.message == (
        "3 facts of the report are in no table of module TEST, or lack an open "
        "key of their table, so no rule reads them."
    )
    assert finding.examples == (
        "reports/c_01.00.csv:2: table c_01.00 has no datapoint dp404",
        "dpm: module TEST has no table C_99.00",
        "dp10: it has no template and datapoint",
    )


@pytest.mark.parametrize(
    ("datapoint", "value", "reason"),
    [
        ("dpm", "NaN", "'NaN' is not a number"),
        ("dpm", "not a number", "'not a number' is not a number"),
        ("dpi", "Infinity", "'Infinity' is not a number"),
        ("dpord", "1.5", "'1.5' is not a whole number"),
        ("dpt", "false", "'false' is not true"),
        ("dpb", "yes", "'yes' is not a Boolean"),
        ("dpe", "", "'' is not one item"),
        ("dpe", "eba_CU:EUR eba_CU:USD", "'eba_CU:EUR eba_CU:USD' is not one item"),
        ("dpe", "EUR", "'EUR' is not one item"),
        ("dpd", "2026-02-30", "'2026-02-30' is not a date"),
        ("dpd", "2026-06-30T12:00:00", "'2026-06-30T12:00:00' is not a date"),
        ("dpdt", "30/06/2026", "'30/06/2026' is not a date"),
    ],
)
def test_invalid_values_are_findings_not_values(datapoint, value, reason) -> None:
    bad = fact(datapoint, value, location="reports/c_01.00.csv:2")
    provider = ReportProvider(MODULE, report([bad]))
    assert set(values(provider).values()) == {None}
    assert provider.invalid == (bad,)
    assert provider.unplaced == ()
    (finding,) = provider.findings
    assert (finding.code, finding.severity) == ("invalidValue", "error")
    assert finding.message == (
        "1 fact of the report has a value that does not read as its cell's "
        "data type, so no rule reads it."
    )
    assert finding.examples == (f"reports/c_01.00.csv:2: {reason}",)
    rule = "{tC_01.00, r0010, c0010} > 0"
    assert check_report(MODULE, report([bad])).failed()
    assert evaluate_rule(rule, provider).status == "not_applicable"


def test_dates_drop_their_time_and_time_zone() -> None:
    provider = ReportProvider(
        MODULE,
        report(
            [
                fact("dpd", "2026-06-30Z"),
                fact("dpdt", "2026-06-30+02:00"),
                fact("dpdt2", "2026-06-30T23:30:00.5-01:00"),
            ]
        ),
    )
    found = values(provider)
    assert found["0080"] == found["0130"] == found["0140"] == date(2026, 6, 30)
    assert provider.invalid == ()


def test_items_take_the_eba_prefix_of_their_namespace() -> None:
    namespaces = {
        "cu": "http://www.eba.europa.eu/xbrl/crr/dict/dom/CU",
        "eba_CU": "http://www.eba.europa.eu/xbrl/crr/dict/dom/CU",
    }
    keys = {"CC": "cu:EUR", "qNUM": "1", "qDAT": "2026-01-31", "qTXT": "a"}
    provider = ReportProvider(
        MODULE,
        report(
            [fact("dpe", "cu:EUR"), fact("dpo", "7", template="c_07.00.a", keys=keys)],
            namespaces=namespaces,
        ),
    )
    assert values(provider)["0050"] == Item.parse("eba_CU:EUR")
    for expression in (
        "{tC_01.00, r0050, c0010} = [eba_CU:EUR]",
        "{tC_07.00.a, c0010} [where qCC = [eba_CU:EUR]] = 7",
    ):
        assert evaluate_rule(expression, provider).status == "passed", expression


@pytest.mark.parametrize(
    ("keys", "reason"),
    [
        (
            {"qNUM": "1", "qDAT": "2026-01-31", "qTXT": "a"},
            "it has no column CC for open key qCC",
        ),
        (
            {"CC": "", "qNUM": "1", "qDAT": "2026-01-31", "qTXT": "a"},
            "open key qCC is empty",
        ),
        (
            {"CC": "eba_CU:EUR", "qNUM": "1", "qDAT": "2026-01-31", "qTXT": "  "},
            "open key qTXT is empty",
        ),
        (
            {"CC": "eba_CU:EUR", "qNUM": "x", "qDAT": "2026-01-31", "qTXT": "a"},
            "open key qNUM: 'x' is not a whole number",
        ),
    ],
)
def test_facts_without_their_open_keys_are_unplaced(keys, reason) -> None:
    stray = fact("dpo", "7", template="C_07.00.a", keys=keys)
    provider = ReportProvider(MODULE, report([stray]))
    assert provider.unplaced == (stray,)
    assert provider.select(CellQuery("C_07.00.a")) == []
    assert provider.findings[0].examples == (f"dpo: {reason}",)


def test_a_key_with_no_allowed_items_is_still_enumerated() -> None:
    table = MODULE.tables[1]
    keys = (replace(table.open_keys[0], items=()), *table.open_keys[1:])
    tables = (MODULE.tables[0], replace(table, open_keys=keys), *MODULE.tables[2:])
    module = replace(MODULE, tables=tables)
    values = {"CC": "eba_CU:EUR", "qNUM": "1", "qDAT": "2026-01-31", "qTXT": "a"}
    provider = ReportProvider(
        module, report([fact("dpo", "7", template="C_07.00.a", keys=values)])
    )
    (point,) = provider.select(CellQuery("C_07.00.a"))
    assert point.keys["qCC"] == Item("CU", "EUR")


def test_text_keys_are_stripped() -> None:
    def row(text, value):
        keys = {"CC": " eba_CU:EUR ", "qNUM": " 1", "qDAT": "2026-01-31 ", "qTXT": text}
        return fact("dpo", value, template="C_07.00.a", keys=keys)

    provider = ReportProvider(MODULE, report([row(" LEI ", "7"), row("LEI", "8")]))
    (point,) = provider.select(CellQuery("C_07.00.a"))
    assert point.keys["qTXT"] == "LEI"
    assert point.value == Number.of(7, -3)  # the duplicate: the first counts
    (finding,) = provider.findings
    assert finding.code == "duplicateFact"


def test_a_fact_whose_keys_differ_only_in_spelling_is_a_finding() -> None:
    def row(number, value, location):
        keys = {"CC": "eba_CU:EUR", "qNUM": number, "qDAT": "2026-01-31", "qTXT": "a"}
        return fact("dpo", value, template="C_07.00.a", keys=keys, location=location)

    first, second = row("007", "7", "c_07.00.a.csv:2"), row("7", "8", "c_07.00.a.csv:3")
    provider = ReportProvider(MODULE, report([first, second]))
    (point,) = provider.select(CellQuery("C_07.00.a"))
    assert point.value == Number.of(7, -3)
    (finding,) = provider.findings
    assert (finding.code, finding.severity, finding.count) == (
        "duplicateFact",
        "error",
        1,
    )
    assert finding.message == (
        "1 fact of the report has the cell and open keys of an earlier fact, "
        "with the keys written otherwise, so no rule reads it."
    )
    assert finding.examples == (
        "c_07.00.a.csv:3: the cell and keys of c_07.00.a.csv:2",
    )
    assert check_report(MODULE, report([first, second])).failed()


def test_a_duplicate_fact_keeps_the_first_value() -> None:
    first = fact("dpm", "1000", location="reports/c_01.00.csv:2")
    provider = ReportProvider(MODULE, report([first, fact("dpm", "2000")]))
    point = provider.select(CellQuery("C_01.00"))[0]
    assert point.value == Number.of(1000, -3)
    assert provider.fact(point) is first
    assert provider.findings == ()


FILED = load_module(
    {
        "format": "dpm-module/1",
        "release": "4.2",
        "module": "FILED",
        "tables": [
            {
                "code": "F_19.00.a.dp",
                "filing_indicator": "F_19.00.dp",
                "cells": [cell("a", "dpa", "m"), cell("s", "dpshared", "m", "0020")],
            },
            {
                "code": "F_19.00.d.dp",
                "filing_indicator": "F_19.00.dp",
                "cells": [cell("d", "dpd", "m"), cell("s2", "dpshared", "m", "0020")],
            },
        ],
    }
)


def test_a_file_named_by_its_filing_indicator_places_facts_by_datapoint() -> None:
    facts = [
        fact("dpa", "1", template="f_19.00.dp"),
        fact("dpd", "2", template="f_19.00.dp"),
        fact("dpshared", "3", template="f_19.00.dp"),
        fact("dp404", "4", template="f_19.00.dp"),
    ]
    provider = ReportProvider(
        FILED, report(facts, filing_indicators={"F_19.00.dp": True})
    )
    assert values(provider, "F_19.00.a.dp") == {
        "0010": Number.of(1, -3),
        "0020": Number.of(3, -3),
    }
    assert values(provider, "F_19.00.d.dp") == {
        "0010": Number.of(2, -3),
        "0020": Number.of(3, -3),
    }
    assert provider.unplaced == (facts[3],)
    assert provider.findings[0].examples == (
        "dp404: table f_19.00.dp has no datapoint dp404",
    )


def test_a_filing_indicator_that_is_no_table_selects_its_tables() -> None:
    facts = [
        fact("dpa", "1", template="f_19.00.a.dp"),
        fact("dpd", "2", template="f_19.00.d.dp"),
    ]
    provider = ReportProvider(
        FILED, report(facts, filing_indicators={"F_19.00.dp": True})
    )
    points = provider.select(CellQuery("f_19.00.dp"))
    assert [(p.table, p.row, p.value) for p in points] == [
        ("F_19.00.a.dp", "0010", Number.of(1, -3)),
        ("F_19.00.a.dp", "0020", None),
        ("F_19.00.d.dp", "0010", Number.of(2, -3)),
        ("F_19.00.d.dp", "0020", None),
    ]
    assert provider.open_keys("F_19.00.dp") == ()
    # Both tables have r0010, c0010: one record cannot hold both cells.
    result = evaluate_rule("sum({tF_19.00.dp, r0010, c0010}) = 3", provider)
    assert result.status == "error"
    assert result.message == (
        "tables F_19.00.a.dp and F_19.00.d.dp of F_19.00.dp have the same cell "
        "{tF_19.00.d.dp, r0010, c0010}"
    )
    split = load_module(
        {
            "format": "dpm-module/1",
            "release": "4.0",
            "module": "SPLIT",
            "tables": [
                {
                    "code": "C_02.00.a",
                    "filing_indicator": "C_02.00",
                    "cells": [cell("a", "dpa", "m"), cell("b", "dpb", "m", "0020")],
                },
                {
                    "code": "C_02.00.b",
                    "filing_indicator": "C_02.00",
                    "cells": [cell("c", "dpc", "m", "0035")],
                },
            ],
        }
    )
    facts = [
        fact("dpa", "10", template="c_02.00.a"),
        fact("dpb", "4", template="c_02.00.a"),
        fact("dpc", "6", template="c_02.00.b"),
    ]
    provider = ReportProvider(split, report(facts, filing_indicators={"C_02.00": True}))
    rule = "with {tC_02.00, c0010}: {r0010} = {r0020} + {r0035}"
    result = evaluate_rule(rule, provider)
    assert result.status == "passed", result.message


def test_template_ids_of_the_eba_metadata_name_their_table() -> None:
    provider = ReportProvider(MODULE, report([fact("dp9", "1", template="C_09-00")]))
    assert values(provider, "C_09.00") == {"0010": Number.of(1, -3)}


def test_the_report_must_be_of_the_modules_entry_point() -> None:
    import dataclasses

    entry = "http://www.eba.europa.eu/eu/fr/xbrl/crr/fws/corep/4.2/mod/corep_of.json"
    module = dataclasses.replace(MODULE, entry_point=entry)
    for same in (entry, entry.replace(".json", ".xsd")):
        ReportProvider(module, report([], entry_point=same))
    ReportProvider(module, report([]))  # a report without one is not checked
    other = entry.replace("corep_of", "corep_lr")
    with pytest.raises(
        ValueError,
        match=r"entry point .*corep_lr\.json, but module TEST of .*corep_of\.json",
    ):
        ReportProvider(module, report([], entry_point=other))
    with pytest.raises(ValueError, match="corep_lr"):
        check_report(module, report([], entry_point=other))


def test_filing_indicators_and_variables() -> None:
    provider = ReportProvider(
        MODULE,
        report(
            [fact("dp10", "1", template="C_10.00")],
            filing_indicators={"c_01.00": True, "C_07.00": True, "C_09.00": False},
        ),
    )
    assert provider.table_reported("C_01.00") is True
    assert provider.table_reported("C_07.00.a") is True  # by its filing indicator
    assert provider.table_reported("C_09.00") is False
    assert provider.table_reported("C_10.00") is False  # facts, but no indicator
    assert provider.table_reported("C_11.00") is False
    unfiled = ReportProvider(
        MODULE,
        report([fact("dp10", "1", template="C_10.00")], filing_indicators={}),
    )
    assert unfiled.table_reported("C_10.00") is True  # no indicators: by facts
    assert unfiled.table_reported("C_09.00") is False
    assert provider.is_template("c_07.00.A") and provider.is_template("c_07.00")
    assert not provider.is_template("ReportingLevel")
    for expression in (
        "{v_C_07.00}",
        "{vC_07.00.a}",
        "not {v_C_09.00}",
        "not {vC_10.00}",
        '{vReportingLevel} = "con"',
    ):
        assert evaluate_rule(expression, provider).status == "passed", expression


def test_parameters_and_contextual_components() -> None:
    provider = ReportProvider(MODULE, report([fact("dpm", "1")]))
    assert provider.parameter("refperiod") == date(2026, 12, 31)
    assert provider.parameter("entityID") == "LEI00000000000000000.CON"
    assert provider.parameter("baseCurrency") == Item("iso4217", "EUR")
    assert provider.parameter("decimalsMonetary") == Number(Decimal(-3))
    assert provider.parameter("decimalsInteger") is None  # INF
    assert provider.parameter("decimalsDecimal") is None
    assert provider.parameter("custom") == "x"
    assert provider.parameter("Missing") is None
    for expression in (
        "{tC_01.00, r0010, c0010} [where refPeriod = #2026-12-31#] > 0",
        "{tC_01.00, r0010, c0010} [where decimalsMonetary = -3] > 0",
        "{tC_01.00, r0010, c0010} [where baseCurrency = [eba_CU:EUR]] > 0",
    ):
        assert evaluate_rule(expression, provider).status == "passed", expression
    individual = ReportProvider(
        MODULE, report([], entity_id="LEI.IND", base_currency=None)
    )
    assert individual.parameter("ReportingLevel") == "ind"
    assert individual.parameter("baseCurrency") is None
    assert (
        ReportProvider(MODULE, report([], entity_id="LEI")).parameter("ReportingLevel")
        is None
    )


def test_fact_leads_back_to_the_report() -> None:
    reported = fact("dpm", "1", location="reports/c_01.00.csv:2")
    provider = ReportProvider(MODULE, report([reported]))
    first, second = provider.select(CellQuery("C_01.00"))[:2]
    assert provider.fact(first) is reported
    assert provider.fact(second) is None


def test_check_report_combines_filing_findings_and_rules(tmp_path) -> None:
    finding = FilingFinding(
        rule="1.6", code="missingFilingIndicator", severity="warning", message="m"
    )
    check = check_report(MODULE, report([fact("dpm", "1000")], filing=(finding,)))
    assert check.filing == (finding,)
    assert [(run.rule.code, run.status, run.message) for run in check.rules] == [
        ("v1", "passed", None),
        ("v2", "failed", None),
        ("v3", "skipped", "not a rule of module TEST"),
        ("v4", "skipped", "inactive rule"),
    ]
    assert not check.failed()
    assert check.failed("warning")


def test_check_report_reads_files() -> None:
    check = check_report(EXAMPLES / "xbrl-module.json", EXAMPLES / "xbrl-report")
    assert check.module.module == "COREP_LR"
    assert check.unplaced == ()
    assert [run.status for run in check.rules] == [
        "failed",
        "passed",
        "failed",
        "failed",
        "not_applicable",
        "passed",
        "unsupported",
    ]
    assert check.failed()


def test_check_report_reads_bytes_with_a_name(tmp_path) -> None:
    path = tmp_path / "report.zip"
    write_xbrl_csv(report([fact("dpm", "1000")]), path)
    check = check_report(MODULE, path.read_bytes(), name="report.zip")
    assert [run.status for run in check.rules][:2] == ["passed", "failed"]


# XBRL-XML through the taxonomy ----------------------------------------------

DATA = Path(__file__).parent / "data" / "xbrl"
PACKAGE = DATA / "taxonomy.zip"
OF_DOCUMENT: dict[str, Any] = {
    "format": "dpm-module/1",
    "release": "4.0",
    "module": "COREP_OF",
    "entry_point": (
        "http://www.eba.europa.eu/eu/fr/xbrl/crr/fws/corep/4.0/mod/corep_of.json"
    ),
    "tables": [
        {
            "code": "C_01.00",
            "cells": [
                cell("a", "dp84817", "m", "0010"),
                cell("b", "dp84818", "p", "0020"),
                cell("c", "dp84820", "s", "0030"),
            ],
        },
        {
            "code": "C_27.00",
            "open_keys": [
                {"code": "qINC", "column": "c0010"},
                {
                    "code": "qCO",
                    "column": "c0020",
                    "items": ["eba_qCO:qx2000", "eba_qCO:qx2001"],
                },
            ],
            "cells": [
                cell("n", "dp100", "s", "*", "0030"),
                cell("m", "dp101", "m", "*", "0040"),
            ],
        },
    ],
    "rules": [
        {"code": "r1", "expression": "{tC_01.00, r0010, c0010} = 1000"},
        {"code": "r2", "expression": "{tC_01.00, r0020, c0010} < 0.1"},
        {
            "code": "r3",
            "expression": "{tC_27.00, c0040} [where qCO = [eba_qCO:qx2000]] > 0",
        },
        {"code": "r4", "expression": "count({tC_27.00, c0030}) = 2"},
        {"code": "r5", "expression": "{vC_27.00} and not {vC_00.01}"},
    ],
}
OF_MODULE = load_module(OF_DOCUMENT)


def test_xml_facts_are_placed_through_the_taxonomy() -> None:
    xml = dpmxbrl.read_report(DATA / "report.xbrl", taxonomy_packages=[PACKAGE])
    assert xml.format == "xbrl-xml"
    provider = ReportProvider(OF_MODULE, xml, taxonomy_packages=[PACKAGE])
    stray = next(fact for fact in xml.facts if fact.concept == "eba_met:mi999")
    assert provider.unplaced == (stray,)
    assert provider.findings[0].examples[0].startswith("report.xbrl#fact7: no data")
    point = provider.select(CellQuery("C_01.00"))[0]
    assert point.value == Number.of(1000, -3)
    source = provider.fact(point)
    assert source is not None
    assert source.location == "report.xbrl#fact1"
    keyed = provider.select(CellQuery("C_27.00"))
    assert [point.keys for point in keyed if point.column == "0040"] == [
        {"qINC": "cp1", "qCO": Item.parse("eba_qCO:qx2000")},  # declared as co:
        {"qINC": "cp2", "qCO": Item.parse("eba_qCO:qx2001")},
    ]

    check = check_report(OF_MODULE, DATA / "report.xbrl", taxonomy_packages=PACKAGE)
    csv = check_report(OF_MODULE, DATA / "report.zip", taxonomy_packages=PACKAGE)
    statuses = [run.status for run in check.rules]
    assert statuses == ["passed", "failed", "passed", "passed", "passed"]
    assert statuses == [run.status for run in csv.rules]
    assert len(check.unplaced) == 1
    assert csv.unplaced == csv.findings == ()


def test_xml_reports_need_their_taxonomy_packages() -> None:
    xml = dpmxbrl.read_report(DATA / "report.xbrl")
    with pytest.raises(ValueError, match="--taxonomy-package"):
        ReportProvider(OF_MODULE, xml)
    with pytest.raises(ValueError, match="taxonomy packages"):
        check_report(OF_MODULE, DATA / "report.xbrl")


# time_shift on previous reports --------------------------------------------

GROWTH = "{tC_01.00, r0010, c0010} >= time_shift({tC_01.00, r0010, c0010}, Q, 1)"


def dated(day: date, facts) -> Report:
    return report(
        facts,
        reference_date=day,
        parameters={"refPeriod": day.isoformat()},
    )


SEPTEMBER = dated(date(2026, 9, 30), [fact("dpm", "900000")])
JUNE = dated(date(2026, 6, 30), [fact("dpm", "1100000")])


def test_time_shift_reads_the_previous_report_by_reference_date() -> None:
    provider = ReportProvider(
        MODULE, report([fact("dpm", "1000000")]), previous=[JUNE, SEPTEMBER]
    )
    assert list(provider.previous) == [date(2026, 6, 30), date(2026, 9, 30)]
    assert evaluate_rule(GROWTH, provider).status == "passed"
    half_year = GROWTH.replace("Q, 1", "S, 1")
    result = evaluate_rule(half_year, provider)
    assert result.status == "failed"
    earlier = result.failures[0].points[1]
    assert earlier.ref == EarlierRef("S", 1, ("C_01.00", "m", ()))
    assert isinstance(earlier.value, Number)
    assert earlier.value == Number.of(1100000, -3)
    assert earlier.value.tolerance == Decimal(500)


def test_previous_reports_shift_among_themselves() -> None:
    current = report([fact("dpm", "1000000")])
    provider = ReportProvider(MODULE, current, previous=[SEPTEMBER, JUNE])
    september = provider.earlier_report("Q", 1)
    assert september is provider.previous[date(2026, 9, 30)]
    assert september.earlier_report("Q", 1) is provider.previous[date(2026, 6, 30)]
    assert september.earlier_report("Q", -1) is provider
    assert provider.earlier_report("M", 1) is None
    nested = "time_shift(time_shift({tC_01.00, r0010, c0010}, Q, 1), Q, 1) = 1100000"
    assert evaluate_rule(nested, provider).status == "passed"


def test_time_shift_names_the_missing_reference_date() -> None:
    for previous in ([], [JUNE]):
        provider = ReportProvider(MODULE, report([fact("dpm", "1")]), previous=previous)
        result = evaluate_rule(GROWTH, provider)
        assert result.status == "unsupported"
        assert result.message == (
            "time_shift needs the report 1 quarter(s) earlier "
            "(reference date 2026-09-30), which the provider does not have"
        )


def test_open_keys_of_previous_reports_are_typed_alike() -> None:
    def row(value):
        keys = {"CC": "eba_CU:EUR", "qNUM": "1", "qDAT": "2026-01-31", "qTXT": "a"}
        return fact("dpo", value, template="C_07.00.a", keys=keys)

    provider = ReportProvider(
        MODULE, report([row("10")]), previous=[dated(date(2025, 12, 31), [row("8")])]
    )
    rule = "{tC_07.00.a, c0010} - time_shift({tC_07.00.a, c0010}, A, 1, refPeriod) = 2"
    result = evaluate_rule(rule, provider)
    assert result.status == "passed"
    assert [outcome.key for outcome in result.outcomes] == [
        {
            "qCC": Item.parse("eba_CU:EUR"),
            "qNUM": Decimal(1),
            "qDAT": date(2026, 1, 31),
            "qTXT": "a",
        }
    ]


@pytest.mark.parametrize(
    ("current", "previous", "message"),
    [
        (report([]), [dated(date(2026, 12, 31), [])], "reference date 2026-12-31"),
        (report([]), [JUNE, JUNE], "reference date 2026-06-30"),
        (report([]), [report([], reference_date=None)], "previous report has no"),
        (report([], reference_date=None), [JUNE], "report has no reference date"),
    ],
)
def test_previous_reports_need_distinct_reference_dates(
    current, previous, message
) -> None:
    with pytest.raises(ValueError, match=message):
        ReportProvider(MODULE, current, previous=previous)


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        (
            {"entity_id": "OTHER.CON"},
            "previous report for 2026-09-30 is of entity OTHER.CON, "
            "not LEI00000000000000000.CON",
        ),
        (
            {"entry_point": "http://example.com/4.2/mod/b.json"},
            "previous report for 2026-09-30 is of module b, not a",
        ),
    ],
)
def test_previous_reports_are_of_the_same_entity_and_module(changes, message) -> None:
    import dataclasses

    current = report([], entry_point="http://example.com/4.2/mod/a.json")
    earlier = dataclasses.replace(
        dated(date(2026, 9, 30), []),
        **{"entry_point": current.entry_point, **changes},
    )
    with pytest.raises(ValueError, match=message):
        ReportProvider(MODULE, current, previous=[earlier])


def test_a_previous_report_of_another_taxonomy_is_a_warning() -> None:
    import dataclasses

    point = "http://www.eba.europa.eu/eu/fr/xbrl/crr/fws/finrep/{}/mod/finrep9.json"
    current = report([fact("dpm", "1000000")], entry_point=point.format("4.2"))
    earlier = dataclasses.replace(SEPTEMBER, entry_point=point.format("4.1"))
    provider = ReportProvider(MODULE, current, previous=[earlier])
    (finding,) = provider.findings
    assert (finding.code, finding.severity) == ("otherEntryPoint", "warning")
    assert finding.message == (
        f"The previous report for 2026-09-30 is of entry point {point.format('4.1')}, "
        f"not {point.format('4.2')}; its facts are placed in this module's tables."
    )
    assert evaluate_rule(GROWTH, provider).status == "passed"


def test_unplaced_facts_of_previous_reports_are_warnings() -> None:
    earlier = dated(date(2026, 9, 30), [fact("dpm", "1"), fact("dp404", "1")])
    provider = ReportProvider(MODULE, report([fact("dpm", "1")]), previous=[earlier])
    (finding,) = provider.findings
    assert (finding.code, finding.severity) == ("unplacedFact", "warning")
    assert finding.message.startswith(
        "1 fact of the previous report for 2026-09-30 is in no table"
    )
    check = check_report(MODULE, report([fact("dpm", "1")]), previous=[earlier])
    assert check.findings == (finding,)
    assert not check.failed()
    assert check.failed("warning")


def test_check_report_reads_previous_reports() -> None:
    check = check_report(
        EXAMPLES / "xbrl-module.json",
        EXAMPLES / "xbrl-report",
        previous=[EXAMPLES / "xbrl-report-previous"],
    )
    shift = check.rules[-1]
    assert (shift.rule.code, shift.status) == ("e0007", "failed")
    with_report = check_report(
        EXAMPLES / "xbrl-module.json",
        EXAMPLES / "xbrl-report",
        previous=[dpmxbrl.read_report(EXAMPLES / "xbrl-report-previous")],
    )
    assert with_report.rules[-1].status == "failed"


def test_columnar_hands_time_shift_on_reports_to_the_reference_engine() -> None:
    columnar = pytest.importorskip("dpmxl.columnar")
    provider = ReportProvider(
        MODULE, report([fact("dpm", "1000000")]), previous=[SEPTEMBER]
    )
    with pytest.raises(columnar.ColumnarUnsupported):
        columnar.evaluate_rule_columnar(GROWTH, columnar.PointsFrameProvider(provider))
    assert evaluate_rule(GROWTH, provider).status == "passed"


def test_the_extra_is_named_when_dpm_xbrl_is_missing(monkeypatch) -> None:
    monkeypatch.setitem(sys.modules, "dpmxbrl", None)
    monkeypatch.delitem(sys.modules, "dpmxl.xbrl")
    with pytest.raises(
        ModuleNotFoundError, match=r'pip install "dpm-xl\[xbrl\]"'
    ) as caught:
        importlib.import_module("dpmxl.xbrl")
    assert caught.value.name == "dpmxbrl"


# dpm-xl check-report --------------------------------------------------------

MODULE_FILE, REPORT_DIR = (
    str(EXAMPLES / "xbrl-module.json"),
    str(EXAMPLES / "xbrl-report"),
)


def test_check_report_prints_findings_and_rules(capsys) -> None:
    from dpmxl.cli import main

    assert main(["check-report", MODULE_FILE, REPORT_DIR]) == 1
    output = capsys.readouterr().out
    assert output.startswith(
        f"report: {REPORT_DIR} (xbrl-csv); module COREP_LR, release 4.2\n"
    )
    assert "filing rules broken: 0 errors, 0 warnings\n" in output
    assert "e0004: failed (warning)\n" in output
    assert output.endswith(
        "7 rules: 3 failed, 2 passed, 1 not_applicable, 1 unsupported "
        "(3 not listed; --all lists every rule)\n"
    )
    assert ": passed" not in output

    main(["check-report", MODULE_FILE, REPORT_DIR, "--all"])
    output = capsys.readouterr().out
    assert ": passed" in output
    assert output.endswith(
        "7 rules: 3 failed, 2 passed, 1 not_applicable, 1 unsupported\n"
    )


def test_check_report_json(capsys) -> None:
    import json

    from dpmxl.cli import main

    main(["check-report", MODULE_FILE, REPORT_DIR, "--json"])
    document = json.loads(capsys.readouterr().out)
    assert list(document)[:4] == ["schema_version", "tool", "version", "summary"]
    assert document["summary"] == {
        "filing_errors": 0,
        "filing_warnings": 0,
        "rules": 7,
        "passed": 2,
        "failed": 3,
        "not_applicable": 1,
        "error": 0,
        "unsupported": 1,
        "skipped": 0,
        "unplaced_facts": 0,
        "invalid_facts": 0,
    }
    assert document["module"] == {"module": "COREP_LR", "release": "4.2"}
    assert document["report"]["reference_date"] == "2026-03-31"
    assert document["report"]["previous"] == []
    assert document["results"][3]["severity"] == "warning"


def _finding(severity):
    return FilingFinding(
        rule="2.19",
        code="nilUsed",
        severity=severity,
        message="Nil is used.",
        count=2,
        examples=("a", "b"),
    )


@pytest.mark.parametrize(
    ("severity", "fail_on", "status"),
    [("warning", "error", 0), ("warning", "warning", 1), ("error", "error", 1)],
)
def test_check_report_fails_on_findings(
    monkeypatch, tmp_path, capsys, severity, fail_on, status
) -> None:
    import json

    from dpmxl.cli import main

    module = tmp_path / "module.json"
    document = json.loads(Path(MODULE_FILE).read_text(encoding="utf-8"))
    document["rules"] = []
    module.write_text(json.dumps(document), encoding="utf-8")
    monkeypatch.setattr(
        dpmxbrl,
        "read_report",
        lambda path, **_: report([], filing=(_finding(severity),)),
    )
    assert (
        main(["check-report", str(module), REPORT_DIR, "--fail-on", fail_on]) == status
    )
    assert f"  - [{severity}] 2.19 Nil is used. (2 times)\n" in capsys.readouterr().out
    main(
        [
            "check-report",
            str(module),
            REPORT_DIR,
            "--format",
            "junit",
            "--fail-on",
            fail_on,
        ]
    )
    junit = capsys.readouterr().out
    assert 'classname="dpm-xbrl.filing-rules"' in junit
    assert ("<failure" in junit) == bool(status)


def test_check_report_fails_on_facts_outside_the_module(monkeypatch, capsys) -> None:
    import json

    from dpmxl.cli import main

    stray = fact("dp404", "1", location="reports/c_01.00.csv:2")
    monkeypatch.setattr(dpmxbrl, "read_report", lambda path, **_: report([stray]))
    module = EXAMPLES / "xbrl-module.json"
    document = json.loads(module.read_text(encoding="utf-8"))
    document["rules"] = []
    monkeypatch.setattr("dpmxl.cli.load_module", lambda path: load_module(document))
    assert main(["check-report", MODULE_FILE, REPORT_DIR]) == 1
    assert (
        "[error] unplacedFact: 1 fact of the report is in no table of module "
        "COREP_LR, or lacks an open key of its table, so no rule reads it.\n"
        "  - reports/c_01.00.csv:2: module COREP_LR has no table c_01.00\n"
    ) in capsys.readouterr().out
    main(["check-report", MODULE_FILE, REPORT_DIR, "--json"])
    output = json.loads(capsys.readouterr().out)
    assert output["summary"]["unplaced_facts"] == 1
    assert output["fact_findings"][0]["code"] == "unplacedFact"
    assert output["fact_findings"][0]["severity"] == "error"
    main(["check-report", MODULE_FILE, REPORT_DIR, "--format", "junit"])
    junit = capsys.readouterr().out
    assert '<testcase classname="dpm-xl.facts" name="unplacedFact">' in junit
    assert '<failure message="1 fact of the report' in junit


def test_check_report_reads_xml_with_its_taxonomy_packages(tmp_path, capsys) -> None:
    import json

    from dpmxl.cli import main

    module = tmp_path / "module.json"
    module.write_text(json.dumps(OF_DOCUMENT), encoding="utf-8")
    xml = str(DATA / "report.xbrl")
    assert main(["check-report", str(module), xml]) == 3
    assert capsys.readouterr().err == (
        f"error: {xml}: an XBRL-XML report needs its taxonomy packages "
        "(--taxonomy-package) to place its facts in the module\n"
    )
    command = ["check-report", str(module), xml, "--taxonomy-package", str(PACKAGE)]
    assert main([*command, "--json"]) == 1
    document = json.loads(capsys.readouterr().out)
    assert document["summary"]["unplaced_facts"] == 1
    assert [result["status"] for result in document["results"]] == [
        "passed",
        "failed",
        "passed",
        "passed",
        "passed",
    ]


def test_check_report_rejects_a_report_of_another_module(tmp_path, capsys) -> None:
    import json

    from dpmxl.cli import main

    module = tmp_path / "module.json"
    module.write_text(json.dumps(OF_DOCUMENT), encoding="utf-8")
    assert main(["check-report", str(module), REPORT_DIR]) == 3
    assert capsys.readouterr().err == (
        "error: the report is of entry point "
        "http://www.eba.europa.eu/eu/fr/xbrl/crr/fws/corep/4.2/mod/corep_lr.json, "
        "but module COREP_OF of "
        "http://www.eba.europa.eu/eu/fr/xbrl/crr/fws/corep/4.0/mod/corep_of.json\n"
    )


def test_check_report_rejects_unreadable_input(tmp_path, capsys) -> None:
    from dpmxl.cli import main

    assert main(["check-report", str(tmp_path / "missing.json"), REPORT_DIR]) == 3
    assert (
        capsys.readouterr().err == f"error: {tmp_path / 'missing.json'}: no such file\n"
    )
    assert main(["check-report", MODULE_FILE, str(tmp_path / "missing.zip")]) == 3
    error = capsys.readouterr().err
    assert error.startswith(f"error: {tmp_path / 'missing.zip'}: ")
    assert error.count("missing.zip") == 1


PREVIOUS_DIR = str(EXAMPLES / "xbrl-report-previous")


def test_check_report_compares_with_previous_reports(capsys) -> None:
    import json

    from dpmxl.cli import main

    assert (
        main(["check-report", MODULE_FILE, REPORT_DIR, "--previous", PREVIOUS_DIR]) == 1
    )
    output = capsys.readouterr().out
    assert f"previous: {PREVIOUS_DIR} (2025-12-31)\n" in output
    assert "e0007: failed (warning)\n" in output
    assert "time_shift(1,180,000, Q, 1, refPeriod)" in output
    main(
        ["check-report", MODULE_FILE, REPORT_DIR, "--previous", PREVIOUS_DIR, "--json"]
    )
    document = json.loads(capsys.readouterr().out)
    assert document["report"]["previous"] == [
        {"path": PREVIOUS_DIR, "reference_date": "2025-12-31"}
    ]
    assert document["results"][-1]["status"] == "failed"


def test_check_report_names_the_period_no_previous_report_covers(
    tmp_path, capsys
) -> None:
    import shutil

    from dpmxl.cli import main

    older = tmp_path / "older"
    shutil.copytree(PREVIOUS_DIR, older)
    parameters = older / "reports" / "parameters.csv"
    parameters.write_text(
        parameters.read_text(encoding="utf-8").replace("2025-12-31", "2025-09-30"),
        encoding="utf-8",
    )
    main(["check-report", MODULE_FILE, REPORT_DIR, "--previous", str(older)])
    assert (
        "e0007: unsupported (warning)\n"
        "  message: time_shift needs the report 1 quarter(s) earlier "
        "(reference date 2025-12-31), which the provider does not have\n"
    ) in capsys.readouterr().out


def test_check_report_rejects_bad_previous_reports(tmp_path, capsys) -> None:
    from dpmxl.cli import main

    missing = tmp_path / "missing.zip"
    assert (
        main(["check-report", MODULE_FILE, REPORT_DIR, "--previous", str(missing)]) == 3
    )
    assert capsys.readouterr().err.startswith(f"error: {missing}: ")
    assert (
        main(["check-report", MODULE_FILE, REPORT_DIR, "--previous", REPORT_DIR]) == 3
    )
    assert capsys.readouterr().err == (
        "error: two reports have the reference date 2026-03-31\n"
    )
