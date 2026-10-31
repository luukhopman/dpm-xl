import copy
import json
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from dpmxl.cli import main
from dpmxl.module import Cell, ModuleError, OpenKey, Table, cell_type, load_module
from dpmxl.rules import Rule

EXAMPLES = Path(__file__).parent.parent / "examples"
MODULE = json.loads((EXAMPLES / "module.json").read_text(encoding="utf-8"))


def test_the_example_module_loads() -> None:
    module = load_module(EXAMPLES / "module.json")
    assert (module.format, module.release, module.module) == (
        "dpm-module/1",
        "4.2",
        "DEMO",
    )
    assert module.reference_date == date(2026, 12, 31)
    assert module.currency == "EUR"
    assert module.decimals == {"m": 0}
    assert module.filing_indicators == ("C_01.00", "C_27.00")
    assert module.entry_point is None
    assert [table.code for table in module.tables] == ["C_01.00", "C_27.00"]
    assert module.table("c_27.00") == Table(
        "C_27.00",
        "C_27.00",
        (OpenKey("qCPI", "qCPI", "s"),),
        (Cell("C_27.00/c0010", "dp7", "*", "0010", None, "m"),),
    )
    assert module.table("C_99.00") is None
    assert module.rules[1] == Rule(
        "v0002", "{tC_27.00, c0010} > 0", severity="warning", source="eba"
    )
    assert not module.rules[3].active


def test_dpm_synth_templates_load_and_extra_fields_are_ignored() -> None:
    document = copy.deepcopy(MODULE)
    document["format"] = "dpm-synth-template/1"
    document["open_rows"] = 3
    document["tables"][0]["cells"][0]["range"] = [1, 2]
    document["rules"][0]["source"] = "own"
    module = load_module(document)
    assert module.format == "dpm-synth-template/1"
    assert module.rules[0].source == "own"
    tour = load_module(EXAMPLES / "toolkit-tour" / "module.json")
    assert tour.module == "TOUR"


def test_an_empty_items_array_differs_from_none() -> None:
    document = copy.deepcopy(MODULE)
    document["tables"][0]["cells"][0]["items"] = []
    module = load_module(document)
    assert module.tables[0].cells[0].items == ()
    assert module.tables[0].cells[1].items is None


def test_layouts_give_coordinates_open_axes_templates_and_types() -> None:
    module = load_module(
        {
            "format": "dpm-module/1",
            "release": "1",
            "module": "M",
            "tables": [
                {
                    "code": "C_07.00.a",
                    "filing_indicator": "C_07.00",
                    "cells": [
                        {
                            "id": "1",
                            "row": "0010",
                            "column": "0010",
                            "sheet": "*",
                            "datapoint": "a",
                            "data_type": "m",
                        },
                        {
                            "id": "2",
                            "row": "0020",
                            "column": "0020",
                            "sheet": "*",
                            "datapoint": "b",
                            "data_type": "es",
                        },
                        {
                            "id": "3",
                            "row": "0020",
                            "column": "0030",
                            "sheet": "*",
                            "datapoint": "c",
                        },
                        {
                            "id": "4",
                            "row": "0030",
                            "column": "0010",
                            "sheet": "*",
                            "datapoint": "d",
                            "data_type": "x",
                        },
                    ],
                }
            ],
        }
    )
    (layout,) = module.layouts()
    assert layout.rows == ("0010", "0020", "0030")
    assert layout.columns == ("0010", "0020", "0030")
    assert layout.sheets == ()
    assert layout.open_axes == ("sheets",)
    assert layout.template == "C_07.00"
    assert dict(layout.data_types) == {
        ("0010", "0010", None): "number",
        ("0020", "0020", None): "string",
        ("0030", "0010", None): "string",
    }
    assert module.templates() == {"c_07.00.a", "c_07.00"}


@pytest.mark.parametrize(
    ("data_type", "expected"),
    [
        ("m", "number"),
        ("p", "number"),
        ("r", "number"),
        ("i", "integer"),
        ("e", "item"),
        ("o", "integer"),
        ("es", "string"),
        ("b", "boolean"),
        ("t", "boolean"),
        ("d", "date"),
        ("dt", None),
        ("s", "string"),
        ("u", "string"),
        (None, None),
    ],
)
def test_cell_types(data_type, expected) -> None:
    assert cell_type(data_type) == expected


def _broken(change):
    document = copy.deepcopy(MODULE)
    change(document)
    return document


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (
            lambda d: d.pop("format"),
            "format: required, 'dpm-module/1' or 'dpm-synth-template/1'",
        ),
        (
            lambda d: d.update(format="x/1"),
            "format: expected 'dpm-module/1' or 'dpm-synth-template/1', got 'x/1'",
        ),
        (lambda d: d.pop("release"), "release: required"),
        (
            lambda d: d.update(module=3),
            "module: expected a non-empty string, got the number 3",
        ),
        (lambda d: d.update(tables=[]), "tables: at least one table is required"),
        (lambda d: d.update(tables={}), "tables: expected an array, got an object"),
        (
            lambda d: d["tables"][1].update(code="c_01.00"),
            "tables[1].code: 'c_01.00' repeats tables[0].code, ignoring case",
        ),
        (
            lambda d: d["tables"][0]["cells"][1].update(datapoint=1002),
            "tables[0].cells[1].datapoint: expected a non-empty string, got the number 1002",
        ),
        (
            lambda d: d["tables"][0]["cells"][1].pop("id"),
            "tables[0].cells[1].id: required",
        ),
        (
            lambda d: d["tables"][1]["cells"][0].update(id="C_01.00/r0010/c0010"),
            "tables[1].cells[0].id: 'C_01.00/r0010/c0010' repeats tables[0].cells[0].id",
        ),
        (
            lambda d: d["tables"][0]["cells"][0].update(unit="yes"),
            "tables[0].cells[0].unit: expected true, false or null, got 'yes'",
        ),
        (
            lambda d: d["tables"][0]["cells"][0].update(items=[1]),
            "tables[0].cells[0].items[0]: expected an item qname such as 'eba_qEC:qx16', got the number 1",
        ),
        (
            lambda d: d["tables"][1]["open_keys"].append({"code": "qCPI"}),
            "tables[1].open_keys[1].column: 'qCPI' repeats tables[1].open_keys[0].column",
        ),
        (
            lambda d: d["tables"][0].update(cells=[]),
            "tables[0].cells: at least one cell is required",
        ),
        (
            lambda d: d.update(reference_date="31-12-2026"),
            "reference_date: expected a date such as '2026-12-31', got '31-12-2026'",
        ),
        (
            lambda d: d.update(decimals={"m": 1.5}),
            "decimals.m: expected a whole number from -20 to 20, got the number 1.5",
        ),
        (
            lambda d: d.update(filing_indicators=["C_01.00"]),
            "tables[1].filing_indicator: 'C_27.00' is not in filing_indicators",
        ),
        (
            lambda d: d.update(filing_indicators=["C_01.00", "C_01.00"]),
            "filing_indicators[1]: 'C_01.00' repeats filing_indicators[0]",
        ),
        (lambda d: d["rules"][1].pop("code"), "rules[1].code: required"),
        (
            lambda d: d["rules"][1].update(code="v0001"),
            "rules[1].code: 'v0001' repeats rules[0].code",
        ),
        (
            lambda d: d["rules"][1].update(severity="fatal"),
            'rules[1].severity: expected "error" or "warning", got "fatal"',
        ),
    ],
)
def test_invalid_modules_name_the_field(change, message) -> None:
    with pytest.raises(ModuleError) as caught:
        load_module(_broken(change))
    assert str(caught.value) == message


def test_unreadable_module_files(tmp_path) -> None:
    with pytest.raises(ModuleError, match=r"^no such file$"):
        load_module(tmp_path / "missing.json")
    path = tmp_path / "module.json"
    path.write_text("{", encoding="utf-8")
    with pytest.raises(ModuleError, match=r"^not JSON: "):
        load_module(path)
    path.write_text("[]", encoding="utf-8")
    with pytest.raises(ModuleError, match=r"^expected an object, got an array$"):
        load_module(path)


def test_the_cli_reads_the_rules_of_a_module(capsys) -> None:
    module, data = str(EXAMPLES / "module.json"), str(EXAMPLES / "data.json")
    assert main(["check", module]) == 0
    assert (
        capsys.readouterr().out == "4/4 expressions parsed; 1 inactive rule skipped\n"
    )
    assert main(["eval", module, data, "--json"]) == 1
    results = json.loads(capsys.readouterr().out)["results"]
    assert [result["status"] for result in results] == [
        "failed",
        "failed",
        "passed",
        "skipped",
    ]


def test_check_uses_the_layouts_of_a_module(tmp_path, capsys) -> None:
    document = copy.deepcopy(MODULE)
    document["rules"] = [{"code": "x", "expression": "{tC_01.00, r0040, c0010} > 0"}]
    path = tmp_path / "module.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    assert main(["check", str(path), "--strict"]) == 1
    assert "row 0040 is not in table C_01.00" in capsys.readouterr().err


def test_an_invalid_module_is_invalid_input(tmp_path, capsys) -> None:
    path = tmp_path / "module.json"
    path.write_text(json.dumps(_broken(lambda d: d.pop("tables"))), encoding="utf-8")
    assert main(["check", str(path)]) == 3
    assert capsys.readouterr().err == f"error: {path}: tables: required\n"


SPLIT: dict[str, Any] = {
    "format": "dpm-module/1",
    "release": "4.0",
    "module": "SPLIT",
    "tables": [
        {
            "code": "C_02.00.a",
            "filing_indicator": "C_02.00",
            "cells": [
                {
                    "id": "a1",
                    "row": "0010",
                    "column": "0010",
                    "datapoint": "a1",
                    "data_type": "m",
                },
                {
                    "id": "a2",
                    "row": "0020",
                    "column": "0010",
                    "datapoint": "a2",
                    "data_type": "m",
                },
            ],
        },
        {
            "code": "C_02.00.b",
            "filing_indicator": "C_02.00",
            "open_keys": [{"code": "qKEY"}],
            "cells": [
                {
                    "id": "b1",
                    "row": "0035",
                    "column": "0010",
                    "sheet": "*",
                    "datapoint": "b1",
                    "data_type": "m",
                },
            ],
        },
        {
            "code": "C_03.00",
            "cells": [
                {"id": "c1", "row": "0010", "column": "0010", "datapoint": "c1"},
            ],
        },
    ],
    "rules": [
        {"code": "v1", "expression": "with {tC_02.00, c0010}: {r0010} >= {r0020}"},
    ],
}


def test_a_filing_indicator_that_is_no_table_stands_for_its_tables() -> None:
    module = load_module(SPLIT)
    assert module.abstract_tables() == {"C_02.00": ("C_02.00.a", "C_02.00.b")}
    assert module.parts("c_02.00") == ("C_02.00.a", "C_02.00.b")
    assert module.parts("C_02.00.a") == ("C_02.00.a",)
    assert module.parts("C_03.00") == ("C_03.00",)
    assert module.parts("C_04.00") == ()
    layout = module.layout("C_02.00")
    assert layout is not None
    assert (layout.code, layout.rows, layout.columns) == (
        "C_02.00",
        ("0010", "0020", "0035"),
        ("0010",),
    )
    assert layout.open_keys == ("qKEY",)
    assert layout.data_types["0035", "0010", None] == "number"
    part = module.table("C_02.00.b")
    assert part is not None
    assert module.layout("C_02.00.b") == part.layout()
    assert module.layout("C_04.00") is None


def test_a_table_code_is_not_also_a_group_of_tables() -> None:
    document = copy.deepcopy(SPLIT)
    document["tables"][2]["filing_indicator"] = "C_02.00.a"
    module = load_module(document)
    assert module.parts("C_02.00.a") == ("C_02.00.a",)
    assert module.abstract_tables() == {"C_02.00": ("C_02.00.a", "C_02.00.b")}


def test_check_reads_a_group_of_tables_as_one(tmp_path, capsys) -> None:
    document = copy.deepcopy(SPLIT)
    document["rules"].append(
        {"code": "v2", "expression": "{tC_02.00, r0040, c0010} > 0"}
    )
    path = tmp_path / "module.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    assert main(["check", str(path)]) == 1
    captured = capsys.readouterr()
    assert "v1:" not in captured.err
    assert "row 0040 is not in table C_02.00" in captured.err


def test_providers_select_the_tables_of_a_filing_indicator_together() -> None:
    from dpmxl import CellQuery, MemoryProvider, Number, evaluate_rule

    module = load_module(SPLIT)
    provider = MemoryProvider(
        module.layouts(),
        {
            ("C_02.00.a", "0010", "0010", None, ()): Number.of(5, 0),
            ("C_02.00.a", "0020", "0010", None, ()): Number.of(3, 0),
            ("C_02.00.b", "0035", "0010", None, (("qKEY", "k"),)): Number.of(1, 0),
        },
    )
    points = provider.select(CellQuery("C_02.00", columns=None))
    assert [(p.table, p.row, dict(p.keys)) for p in points] == [
        ("C_02.00.a", "0010", {}),
        ("C_02.00.a", "0020", {}),
        ("C_02.00.b", "0035", {"qKEY": "k"}),
    ]
    assert provider.open_keys("C_02.00") == ("qKEY",)
    assert evaluate_rule(module.rules[0].expression, provider).status == "passed"
    result = evaluate_rule("sum({tC_02.00, c0010}) = 9", provider)
    assert result.status == "passed"
    with pytest.raises(LookupError, match=r"unknown table C_04\.00"):
        provider.select(CellQuery("C_04.00"))
