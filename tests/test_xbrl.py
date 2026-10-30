import importlib
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from dpmxl import CellQuery, Item, Number, ValueSet, evaluate_rule
from dpmxl.module import Module, load_module

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
                    cell("es", "dpes", "es", "0060", items=["eba_CU:EUR"]),
                    cell("b", "dpb", "b", "0070"),
                    cell("d", "dpd", "d", "0080"),
                    cell("s", "dps", "s", "0090"),
                    cell("x", "dpx", "m", "0100"),
                    cell("n", "dpn", "m", "0110"),
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
                fact("dpb", "true"),
                fact("dpd", "2026-06-30"),
                fact("dps", "text"),
                fact("dpx", "not a number"),
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
    assert found["0060"] == ValueSet((Item("CU", "EUR"), Item("CU", "USD")))
    assert found["0070"] is True
    assert found["0080"] == date(2026, 6, 30)
    assert found["0090"] == "text"
    assert found["0100"] == "not a number"
    assert found["0110"] is None


def test_a_facts_own_decimals_come_first() -> None:
    provider = ReportProvider(
        MODULE, report([fact("dpm", "5", decimals=2), fact("dpp", "1", decimals="INF")])
    )
    found = values(provider)
    assert found["0010"] == Number.of(5, 2)
    assert found["0020"] == Number(Decimal(1))


def test_a_closed_table_gives_every_cell() -> None:
    provider = ReportProvider(MODULE, report([]))
    assert set(values(provider)) == {f"{row:04}" for row in range(10, 120, 10)}
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
    placed = fact("dp10", "1", template=None)  # XML: placed by its datapoint
    others = [
        fact("dp404", "1"),
        fact("dpm", "1", template="C_99.00"),
        fact("dp404", "1", template=None),
    ]
    provider = ReportProvider(MODULE, report([placed, *others]))
    assert provider.unplaced == tuple(others)
    assert values(provider, "C_10.00") == {"0010": Number.of(1, -3)}


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
    assert provider.table_reported("C_10.00") is True  # no indicator, but facts
    assert provider.table_reported("C_11.00") is False
    assert provider.is_template("c_07.00.A") and provider.is_template("c_07.00")
    assert not provider.is_template("ReportingLevel")
    for expression in (
        "{v_C_07.00}",
        "{vC_07.00.a}",
        "not {v_C_09.00}",
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
        "{tC_01.00, r0010, c0010} [where baseCurrency = [iso4217:EUR]] > 0",
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
    ]
    assert check.failed()


def test_check_report_reads_bytes_with_a_name(tmp_path) -> None:
    path = tmp_path / "report.zip"
    write_xbrl_csv(report([fact("dpm", "1000")]), path)
    check = check_report(MODULE, path.read_bytes(), name="report.zip")
    assert [run.status for run in check.rules][:2] == ["passed", "failed"]


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
    assert output.endswith("6 rules: 3 failed, 2 passed, 1 not_applicable\n")


def test_check_report_json(capsys) -> None:
    import json

    from dpmxl.cli import main

    main(["check-report", MODULE_FILE, REPORT_DIR, "--json"])
    document = json.loads(capsys.readouterr().out)
    assert list(document)[:4] == ["schema_version", "tool", "version", "summary"]
    assert document["summary"] == {
        "filing_errors": 0,
        "filing_warnings": 0,
        "rules": 6,
        "passed": 2,
        "failed": 3,
        "not_applicable": 1,
        "error": 0,
        "unsupported": 0,
        "skipped": 0,
        "unplaced_facts": 0,
    }
    assert document["module"] == {"module": "COREP_LR", "release": "4.2"}
    assert document["report"]["reference_date"] == "2026-03-31"
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


def test_check_report_lists_facts_outside_the_module(monkeypatch, capsys) -> None:
    from dpmxl.cli import main

    stray = fact("dp404", "1", location="reports/c_01.00.csv:2")
    monkeypatch.setattr(dpmxbrl, "read_report", lambda path, **_: report([stray]))
    main(["check-report", MODULE_FILE, REPORT_DIR])
    assert (
        "1 fact in no table of module COREP_LR, such as reports/c_01.00.csv:2"
        in capsys.readouterr().out
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
