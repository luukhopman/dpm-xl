import importlib.util
import json
import logging
import os
import shutil
import sqlite3
from pathlib import Path

import pytest

from dpmxl import parse_program
from dpmxl.cli import main
from dpmxl.dpm import (
    DpmError,
    DpmRelease,
    Release,
    entry_point,
    export_module,
    open_release,
)
from dpmxl.module import load_module

EXAMPLES = Path(__file__).parent.parent / "examples"
_spec = importlib.util.spec_from_file_location("dpm_demo", EXAMPLES / "dpm_demo.py")
assert _spec is not None and _spec.loader is not None
dpm_demo = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(dpm_demo)


@pytest.fixture
def database(tmp_path: Path) -> Path:
    return dpm_demo.build(tmp_path / "dpm.sqlite")


@pytest.fixture
def db(database: Path):
    with open_release(database) as opened:
        yield opened


def _table(document: dict, code: str) -> dict:
    return next(table for table in document["tables"] if table["code"] == code)


def _rule(document: dict, code: str) -> dict:
    return next(rule for rule in document["rules"] if rule["code"] == code)


def test_the_committed_demo_database_is_up_to_date(tmp_path: Path) -> None:
    built = sqlite3.connect(dpm_demo.build(tmp_path / "demo.sqlite"))
    committed = sqlite3.connect(EXAMPLES / "dpm-demo.sqlite")
    assert list(committed.iterdump()) == list(built.iterdump())


def test_releases_modules_and_the_latest_release(db: DpmRelease) -> None:
    assert [release.code for release in db.releases()] == ["1.0", "2.0", "2.0.1"]
    assert db.release() == Release(3, "2.0.1", "2026-04-15", "deactivation")
    assert db.release("1.0").id == 1
    modules = {module.code: module for module in db.modules("2.0")}
    assert sorted(modules) == ["DEMO", "DOCS", "OTHER"]
    assert modules["DEMO"].version == "2.0.0"
    assert modules["DEMO"].release == "2.0"
    assert modules["DEMO"].framework == "DEMO"
    assert modules["DEMO"].from_date == "2026-03-31"
    assert db.modules("1.0")[0].version == "1.0.0"


def test_unknown_releases_and_modules_are_errors(db: DpmRelease) -> None:
    with pytest.raises(DpmError, match=r"no release '9\.9'.*1\.0, 2\.0, 2\.0\.1"):
        export_module(db, "DEMO", "9.9")
    with pytest.raises(DpmError, match=r"no module 'NOPE' in release 2\.0\.1"):
        export_module(db, "NOPE")
    with pytest.raises(DpmError, match="DOCS has no tables"):
        export_module(db, "DOCS")
    with pytest.raises(DpmError, match="format: expected one of"):
        export_module(db, "DEMO", format="csv")


def test_the_export_is_a_module_file(db: DpmRelease) -> None:
    document = export_module(db, "demo")
    module = load_module(document)
    assert (module.format, module.release, module.module) == (
        "dpm-module/1",
        "2.0.1",
        "DEMO",
    )
    assert document["entry_point"] == entry_point("DEMO", "2.0", "DEMO")
    assert document["entry_point"].endswith("/fws/demo/2.0/mod/demo.json")
    assert document["reference_date"] == "2026-03-31"
    assert document["decimals"] == {"m": 0, "p": 4, "i": 0, "r": 2}
    assert document["filing_indicators"] == ["T_01.00", "T_02.00"]
    assert [table["code"] for table in document["tables"]] == ["T_01.00.a", "T_02.00"]
    synth = export_module(db, "DEMO", format="dpm-synth-template/1")
    assert synth["format"] == "dpm-synth-template/1"
    assert load_module(synth).module == "DEMO"


def test_abstract_tables_give_filing_indicators(db: DpmRelease) -> None:
    document = export_module(db, "DEMO")
    assert _table(document, "T_01.00.a")["filing_indicator"] == "T_01.00"
    assert "filing_indicator" not in _table(document, "T_02.00")


def test_cells_leave_out_excluded_and_void_ones(db: DpmRelease, caplog) -> None:
    with caplog.at_level(logging.WARNING, "dpmxl.dpm"):
        cells = _table(export_module(db, "DEMO"), "T_01.00.a")["cells"]
    assert [cell["id"] for cell in cells] == [
        "T_01.00.a/r0010/c0010",
        "T_01.00.a/r0020/c0010",
        "T_01.00.a/r0050/c0010",
        "T_01.00.a/r0060/c0010",
        "T_01.00.a/r0070/c0010",
    ]
    assert cells[0] == {
        "id": "T_01.00.a/r0010/c0010",
        "row": "0010",
        "column": "0010",
        "sheet": None,
        "datapoint": "dp501",
        "data_type": "m",
    }
    # es, text that may be empty, is written as it is, without items
    assert cells[2]["data_type"] == "es"
    assert "items" not in cells[2]
    assert not any("written as" in message for message in caplog.messages)
    # an explicitly empty subcategory allows no item; a missing one, any
    assert cells[3]["items"] == []
    assert load_module(export_module(db, "DEMO")).tables[0].cells[3].items == ()


def test_a_header_restricts_the_items_of_a_cell(db: DpmRelease) -> None:
    cell = _table(export_module(db, "DEMO"), "T_01.00.a")["cells"][1]
    # header 60 names subcategory version 701 (x1), not its later 702 (x2)
    assert cell["data_type"] == "e"
    assert cell["items"] == ["eba_CA:x1"]


def test_items_outside_the_property_category_are_left_out(
    db: DpmRelease, caplog
) -> None:
    with caplog.at_level(logging.WARNING, "dpmxl.dpm"):
        cell = _table(export_module(db, "DEMO"), "T_01.00.a")["cells"][4]
    # subcategory 704 is of CC, the property's category is CA: y1 is not in it
    assert cell["items"] == ["eba_CA:x1"]
    assert (
        "DEMO: cell {T_01.00.a, r0070, c0010}: 1 item is not in category CA of "
        "the property and left out: eba_CC:y1"
    ) in caplog.messages


def test_composed_categories_give_items_of_each(db: DpmRelease) -> None:
    open_cell = _table(export_module(db, "DEMO"), "T_02.00")["cells"][1]
    # y2 moves from CC to CD in release 2.0, which lists both
    assert open_cell["row"] == "*"
    assert open_cell["items"] == ["eba_CC:y1", "eba_CC:y2", "eba_CD:z2"]
    older = _table(export_module(db, "DEMO", "1.0"), "T_02.00")["cells"][1]
    assert older["items"] == ["eba_CC:y1", "eba_CC:y2"]


def test_open_keys_are_enumerated_or_typed(db: DpmRelease, caplog) -> None:
    with caplog.at_level(logging.WARNING, "dpmxl.dpm"):
        keys = _table(export_module(db, "DEMO"), "T_02.00")["open_keys"]
    assert keys == [
        # subcategory order; x4's binding ended in 1.0 and is carried
        {
            "code": "qKEY",
            "column": "qKEY",
            "items": ["eba_CA:x2", "eba_CA:x1", "eba_CA:x4"],
        },
        {"code": "qTXT", "column": "qTXT", "data_type": "s"},
    ]
    assert any("1 item keeps a binding that ended" in note for note in caplog.messages)


def test_rules_carry_precondition_severity_activity_and_modules(
    db: DpmRelease, caplog
) -> None:
    with caplog.at_level(logging.WARNING, "dpmxl.dpm"):
        document = export_module(db, "DEMO")
    assert [rule["code"] for rule in document["rules"]] == ["v1", "v6", "v7551_m"]
    assert _rule(document, "v1") == {
        "code": "v1",
        "expression": "{tT_01.00.a, r0010, c0010} >= 0",
        "precondition": "{v_T_01.00}",
        "severity": "error",
        "active": True,
        "modules": ["DEMO"],
    }
    assert _rule(document, "v6")["active"] is False
    assert _rule(document, "v6")["severity"] == "warning"
    shared = _rule(document, "v7551_m")
    assert shared["modules"] == ["DEMO", "OTHER"]
    # a known EBA typo is corrected, and reported
    assert shared["expression"].endswith("else true endif")
    parse_program(shared["expression"])
    assert any("corrected 'trueendif'" in note for note in caplog.messages)
    # v3's one scope spans DEMO and OTHER: no single report can satisfy it
    assert "DEMO: left out 1 rule whose scope spans several modules: v3" in (
        caplog.messages
    )


def test_the_release_selects_the_module_version_and_rules(db: DpmRelease) -> None:
    old = export_module(db, "DEMO", "1.0")
    assert old["entry_point"].endswith("/fws/demo/1.0/mod/demo.json")
    assert old["reference_date"] == "2025-03-31"
    assert [cell["id"] for cell in _table(old, "T_01.00.a")["cells"]] == [
        "T_01.00.a/r0010/c0010"
    ]
    # v1's first version ends in 1.0 and is valid in it; v4 is only in 1.0.0
    assert [rule["code"] for rule in old["rules"]] == ["v1", "v4"]
    assert _rule(old, "v1")["expression"] == "{tT_01.00.a, r0010, c0010} > 0"
    assert "precondition" not in _rule(old, "v1")
    new = export_module(db, "DEMO", "2.0")
    assert new["release"] == "2.0"
    assert _rule(new, "v1")["expression"].endswith(">= 0")


def test_open_release_rejects_what_it_cannot_read(tmp_path: Path) -> None:
    with pytest.raises(DpmError, match="no such file"):
        open_release(tmp_path / "missing.sqlite")
    text = tmp_path / "notes.txt"
    text.write_text("not a database", encoding="utf-8")
    with pytest.raises(DpmError, match="not a SQLite or Access database"):
        open_release(text)
    empty = tmp_path / "empty.sqlite"
    sqlite3.connect(empty).execute(
        "CREATE TABLE Release (ReleaseID)"
    ).connection.close()
    with pytest.raises(DpmError, match="table Release has no column Code"):
        open_release(empty)


def test_an_access_file_needs_mdb_export(tmp_path: Path, monkeypatch) -> None:
    access = tmp_path / "dpm.accdb"
    access.write_bytes(b"\0\1\0\0Standard ACE DB\0" + bytes(64))
    monkeypatch.setattr(shutil, "which", lambda name: None)
    with pytest.raises(DpmError, match=r"needs mdb-export \(mdbtools\) on PATH"):
        open_release(access)


def test_an_access_file_is_read_with_mdb_export(
    database: Path, tmp_path: Path, monkeypatch
) -> None:
    # A stand-in for mdb-export that prints the demo database's tables as CSV,
    # as mdb-export prints an Access file's tables.
    program = tmp_path / "mdb-export"
    program.write_text(
        "#!/usr/bin/env python3\n"
        "import csv, sqlite3, sys\n"
        f"connection = sqlite3.connect({str(database)!r})\n"
        'cursor = connection.execute(f"SELECT * FROM \\"{sys.argv[-1]}\\"")\n'
        "writer = csv.writer(sys.stdout)\n"
        "writer.writerow([column[0] for column in cursor.description])\n"
        "writer.writerows(['' if v is None else v for v in row] for row in cursor)\n",
        encoding="utf-8",
    )
    program.chmod(0o755)
    access = tmp_path / "dpm.accdb"
    access.write_bytes(b"\0\1\0\0Standard ACE DB\0" + bytes(64))
    monkeypatch.setenv("PATH", f"{tmp_path}{os.pathsep}{os.environ['PATH']}")
    with open_release(access) as from_access, open_release(database) as from_sqlite:
        assert export_module(from_access, "DEMO") == export_module(from_sqlite, "DEMO")
        # the tables are committed, so the database can be copied or saved
        assert not from_access._connection.in_transaction
        from_access._connection.execute("VACUUM INTO ?", (str(tmp_path / "copy.db"),))


def test_cli_lists_modules(database: Path, capsys) -> None:
    assert main(["list-modules", str(database), "--release", "2.0"]) == 0
    assert capsys.readouterr().out == (
        "releases: 1.0, 2.0, 2.0.1\n"
        "modules of release 2.0: 3\n"
        "  DEMO   2.0.0    Demo module\n"
        "  DOCS   1.0.0    Documents\n"
        "  OTHER  1.0.0    Other module\n"
    )
    assert main(["list-modules", str(database), "--json"]) == 0
    document = json.loads(capsys.readouterr().out)
    assert document["release"] == "2.0.1"
    assert document["releases"][0] == {
        "id": 1,
        "code": "1.0",
        "date": "2025-01-15",
        "type": "module",
    }
    assert document["modules"][0]["code"] == "DEMO"


def test_cli_exports_a_module(database: Path, tmp_path: Path, capsys) -> None:
    target = tmp_path / "demo.json"
    assert main(["export-module", str(database), "DEMO", "-o", str(target)]) == 0
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "note: DEMO: left out 1 rule whose scope spans" in captured.err
    assert captured.err.endswith(
        f"wrote {target}: module DEMO, release 2.0.1: 2 tables, 7 cells, 3 rules\n"
    )
    assert load_module(target).module == "DEMO"
    assert main(["check", str(target)]) == 0
    capsys.readouterr()
    arguments = ["export-module", str(database), "DEMO", "--release", "1.0"]
    assert main([*arguments, "--format", "dpm-synth-template/1"]) == 0
    document = json.loads(capsys.readouterr().out)
    assert (document["format"], document["release"]) == ("dpm-synth-template/1", "1.0")


def test_cli_reports_bad_input_with_status_3(database: Path, capsys) -> None:
    assert main(["export-module", str(database), "NOPE"]) == 3
    assert capsys.readouterr().err.startswith("error: no module 'NOPE'")
    assert main(["list-modules", str(database), "--release", "9"]) == 3
    assert "no release '9'" in capsys.readouterr().err
    assert main(["export-module", "missing.sqlite", "DEMO"]) == 3
    assert capsys.readouterr().err == "error: missing.sqlite: no such file\n"


REAL = os.environ.get("DPMXL_DPM_DATABASE")


@pytest.mark.skipif(not REAL, reason="set DPMXL_DPM_DATABASE to an EBA DPM database")
def test_a_real_release_exports_every_module() -> None:
    assert REAL is not None
    with open_release(REAL) as real:
        release = os.environ.get("DPMXL_DPM_RELEASE") or real.release().code
        exported = 0
        for info in real.modules(release):
            try:
                document = export_module(real, info.code, release)
            except DpmError as error:
                assert "has no tables" in str(error)
                continue
            module = load_module(document)
            assert module.tables and module.filing_indicators
            for rule in module.rules:
                if rule.active:
                    parse_program(rule.expression)
            exported += 1
        assert exported
