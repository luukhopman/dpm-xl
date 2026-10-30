import json
from pathlib import Path
from typing import Any

import pytest

from dpmxl.cli import _source, main


def test_check_reports_parse_errors(tmp_path, capsys) -> None:
    source = tmp_path / "rules.txt"
    source.write_text("{tA, r0010} = 1\n# comment\n{tA, r0010\n", encoding="utf-8")
    assert main(["check", str(source)]) == 1
    output = capsys.readouterr()
    assert "1/2 expressions parsed" in output.out
    assert "unterminated" in output.err


def test_eval_explains_failures(tmp_path, capsys) -> None:
    data = tmp_path / "data.json"
    data.write_text(
        json.dumps(
            {
                "tables": [
                    {
                        "code": "C_01.00",
                        "rows": ["0010", "0020", "0030"],
                        "columns": ["0010"],
                    }
                ],
                "facts": [
                    {
                        "table": "C_01.00",
                        "row": "0010",
                        "column": "0010",
                        "value": 1204,
                        "decimals": 0,
                    },
                    {
                        "table": "C_01.00",
                        "row": "0020",
                        "column": "0010",
                        "value": 1180,
                        "decimals": 0,
                    },
                    {
                        "table": "C_01.00",
                        "row": "0030",
                        "column": "0010",
                        "value": 17,
                        "decimals": 0,
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    code = main(
        [
            "eval",
            "with {tC_01.00, c0010, default: 0, interval: true}: {r0010} = {r0020} + {r0030}",
            str(data),
        ]
    )
    output = capsys.readouterr().out
    assert code == 1
    assert "status: failed" in output
    assert "1,204 should equal 1,197 (1,180 + 17): difference 7" in output


def _write(tmp_path, facts):
    data = tmp_path / "data.json"
    table = {"code": "A", "rows": ["0010", "0020"], "columns": ["0010"]}
    data.write_text(json.dumps({"tables": [table], "facts": facts}), encoding="utf-8")
    return str(data)


def _fact(row, value, **extra):
    return {"table": "A", "row": row, "column": "0010", "value": value, **extra}


def test_eval_accepts_inf_decimals(tmp_path, capsys) -> None:
    data = _write(
        tmp_path, [_fact("0010", 5, decimals="INF"), _fact("0020", 5, decimals="inf")]
    )
    rule = "with {tA, c0010, interval: true}: {r0010} = {r0020}"
    assert main(["eval", rule, data]) == 0
    assert "status: passed" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("fact", "message"),
    [
        (_fact("0010", "2026/12/31", type="date"), "Invalid isoformat string"),
        (_fact("0010", "1,000", type="number"), "invalid number '1,000'"),
        (_fact("0010", 5, decimals="two"), "invalid decimals 'two'"),
        (_fact("0010", 1, decimals=-7000), "invalid decimals -7000: out of range"),
        (_fact("0010", 1, decimals=10**20), "out of range"),
        ({"row": "0010"}, "malformed data document"),
    ],
)
def test_eval_reports_bad_data_cleanly(tmp_path, capsys, fact, message) -> None:
    data = _write(tmp_path, [fact])
    assert main(["eval", "{tA, r0010, c0010} = 1", data]) == 3
    error = capsys.readouterr().err
    assert error.startswith("error: ")
    assert message in error


def test_eval_reads_groups_operations_and_set_parameters(tmp_path, capsys) -> None:
    data = tmp_path / "data.json"
    data.write_text(
        json.dumps(
            {
                "tables": [{"code": "A", "rows": ["0010"], "columns": ["0010"]}],
                "facts": [{"table": "A", "row": "0010", "column": "0010", "value": 2}],
                "parameters": {"Allowed": [1, 2]},
                "table_groups": {"G": ["A"]},
                "operations": {"v1": "{tA, r0010, c0010} * 2"},
            }
        ),
        encoding="utf-8",
    )
    rules = "{g_G, r0010, c0010} in {p_Allowed, set-number} and {o_v1} = 4"
    assert main(["eval", rules, str(data)]) == 0
    assert "status: passed" in capsys.readouterr().out


@pytest.mark.parametrize("source", ["rules/v4.2.json", "missing.txt", "rules/v4"])
def test_a_missing_rule_file_is_not_read_as_an_expression(source, capsys) -> None:
    assert main(["check", source]) == 3
    assert capsys.readouterr().err == f"error: {source}: no such rule file\n"


def test_expressions_with_a_slash_are_still_expressions(capsys) -> None:
    assert main(["check", "1/2 = 0.5"]) == 0
    assert main(["check", "{tA, r0010} / 2 > 0"]) == 0


def test_check_json_errors_carry_the_end_offset(capsys) -> None:
    assert main(["check", "{tA} >=", "--json"]) == 1
    error = json.loads(capsys.readouterr().out)["errors"][0]
    assert error["position"] <= error["end"]


def layouts_file(tmp_path) -> str:
    data = tmp_path / "layouts.json"
    data.write_text(
        json.dumps(
            {
                "tables": [
                    {
                        "code": "C_01.00",
                        "rows": ["0010", "0020"],
                        "columns": ["0010"],
                        "data_types": [
                            {"row": "0010", "column": "0010", "type": "number"},
                            {"row": "0020", "column": "0010", "type": "number"},
                        ],
                    },
                    {
                        "code": "C_27.00",
                        "columns": ["0010"],
                        "open_keys": ["qCPI"],
                        "open_axes": ["rows"],
                    },
                ],
                "parameters": {"refPeriod": "2026-12-31"},
            }
        ),
        encoding="utf-8",
    )
    return str(data)


def test_check_reports_problems_beyond_syntax(capsys) -> None:
    # Without --strict only syntax errors fail, as before.
    assert main(["check", "summ({tC_01.00, r0010}) > 0"]) == 0
    output = capsys.readouterr()
    assert (
        "expression: error: unknown function 'summ'; did you mean 'sum'?" in output.err
    )
    assert output.out.strip() == "1/1 expressions parsed; 1 error"
    assert main(["check", "summ({tC_01.00, r0010}) > 0", "--strict"]) == 1


def test_check_against_layouts(tmp_path, capsys) -> None:
    layouts = layouts_file(tmp_path)
    source = "{tC_01.00, r0011, c0010} + 'x' > 0 or {tC_27.00, r0010, c0010} > 0"
    assert main(["check", source, "--layouts", layouts, "--strict"]) == 1
    output = capsys.readouterr()
    assert "row 0011 is not in table C_01.00; did you mean r0010?" in output.err
    assert "the rows of C_27.00 are open (key qCPI)" in output.err
    assert "'+' needs numbers, but 'x' is a string" in output.err
    assert (
        "warning: the rows of C_27.00 are open (key qCPI), so they have no codes "
        "such as r0010" in output.err
    )
    assert output.out.strip() == "1/1 expressions parsed; 2 errors and 1 warning"
    strict = ["--layouts", layouts, "--strict"]
    assert main(["check", "refPeriod > #2026-01-01#", *strict]) == 0
    assert main(["check", "refDate > #2026-01-01#", *strict]) == 1


def test_check_warnings_do_not_fail(tmp_path, capsys) -> None:
    layouts = layouts_file(tmp_path)
    assert (
        main(
            [
                "check",
                "{tC_01.00, (r0010, r0030-0050), c0010} > 0",
                "--layouts",
                layouts,
                "--strict",
            ]
        )
        == 0
    )
    output = capsys.readouterr()
    assert "warning: rows 0030-0050 select no row of table C_01.00" in output.err
    assert output.out.strip() == "1/1 expressions parsed; 1 warning"


def test_check_strict_fails_on_non_portable_syntax(capsys) -> None:
    assert main(["check", "{tC_01.00, r0010, c0010} > .5"]) == 0
    assert main(["check", "{tC_01.00, r0010, c0010} > .5", "--strict"]) == 1
    output = capsys.readouterr()
    assert "expression: warning: DPM-XL 0.11 numbers have digits" in output.err
    assert main(["check", "{tC_01.00, r0010, c0010} > 0.5", "--strict"]) == 0


def test_check_json_lists_diagnostics(tmp_path, capsys) -> None:
    assert main(["check", "abs(1, 2) > (", "--json"]) == 1
    document = json.loads(capsys.readouterr().out)
    assert document["summary"]["parsed"] == 0
    assert [error["message"] for error in document["errors"]] == [
        "expression ends where an operand is expected"
    ]
    assert [
        (item["code"], item["start"], item["end"]) for item in document["diagnostics"]
    ] == [("operand-count", 0, 3), ("syntax", 13, 13)]
    assert set(document["diagnostics"][0]) == {
        "source",
        "severity",
        "code",
        "message",
        "start",
        "end",
        "subject",
        "suggestion",
    }


def test_check_rejects_an_unreadable_layouts_file(tmp_path, capsys) -> None:
    data = tmp_path / "bad.json"
    data.write_text('{"tables": [{"rows": []}]}', encoding="utf-8")
    assert main(["check", "1 = 1", "--layouts", str(data)]) == 3
    assert f"error: {data}: malformed data document" in capsys.readouterr().err


def test_check_names_the_file_it_cannot_read(tmp_path, capsys) -> None:
    rules = tmp_path / "bad.json"
    rules.write_text("[1]", encoding="utf-8")
    assert main(["check", str(rules)]) == 3
    assert (
        capsys.readouterr().err
        == f"error: {rules}: [0]: expected an object, got the number 1\n"
    )
    broken = tmp_path / "broken.json"
    broken.write_text("{nope", encoding="utf-8")
    assert main(["check", "1 = 1", "--layouts", str(broken)]) == 3
    assert capsys.readouterr().err.startswith(f"error: {broken}: not JSON: Expecting")


def test_unreadable_data_names_the_file(tmp_path, capsys) -> None:
    assert main(["eval", "1 = 1", str(tmp_path / "missing.json")]) == 3
    assert (
        capsys.readouterr().err == f"error: {tmp_path / 'missing.json'}: no such file\n"
    )
    assert main(["eval", "1 = 1", str(tmp_path)]) == 3
    assert capsys.readouterr().err.startswith(f"error: {tmp_path}: cannot read: ")
    listed = tmp_path / "list.json"
    listed.write_text("[]", encoding="utf-8")
    assert main(["eval", "1 = 1", str(listed)]) == 3
    assert capsys.readouterr().err == (
        f"error: {listed}: a data file must hold a JSON object\n"
    )


def _rule_file(tmp_path, rules):
    path = tmp_path / "rules.json"
    path.write_text(json.dumps(rules), encoding="utf-8")
    return str(path)


SEVERITIES = [
    {"code": "e", "expression": "{tA, r0010, c0010} > 5"},
    {"code": "w", "expression": "{tA, r0020, c0010} > 5", "severity": "warning"},
    {"code": "ok", "expression": "{tA, r0010, c0010} > 0"},
    {"code": "na", "expression": "1 = 1", "precondition": "{v_C_09.00}"},
    {"code": "off", "expression": "1 = 2", "active": False},
]


@pytest.mark.parametrize(
    ("rules", "fail_on", "status"),
    [
        (SEVERITIES, "error", 1),
        (SEVERITIES[1:], "error", 0),
        (SEVERITIES[1:], "warning", 1),
        (SEVERITIES[2:], "warning", 0),
        (
            [
                *SEVERITIES[1:],
                {"code": "x", "expression": "1 / 0 > 1", "severity": "warning"},
            ],
            "error",
            0,
        ),
        (
            [*SEVERITIES[1:], {"code": "x", "expression": "1 / 0 > 1"}],
            "error",
            1,
        ),
    ],
)
def test_eval_fails_on_the_chosen_severity(tmp_path, rules, fail_on, status) -> None:
    data = _write(tmp_path, [_fact("0010", 1), _fact("0020", 2)])
    assert (
        main(["eval", _rule_file(tmp_path, rules), data, "--fail-on", fail_on])
        == status
    )


def test_eval_json_opens_with_tool_version_and_summary(tmp_path, capsys) -> None:
    data = _write(tmp_path, [_fact("0010", 1), _fact("0020", 2)])
    main(["eval", _rule_file(tmp_path, SEVERITIES), data, "--format", "json"])
    document = json.loads(capsys.readouterr().out)
    assert list(document)[:5] == [
        "schema_version",
        "tool",
        "version",
        "summary",
        "results",
    ]
    assert document["schema_version"] == 2
    assert document["tool"] == "dpm-xl"
    assert document["summary"] == {
        "rules": 5,
        "passed": 1,
        "failed": 2,
        "not_applicable": 1,
        "error": 0,
        "unsupported": 0,
        "skipped": 1,
    }


def test_check_json_opens_with_tool_version_and_summary(capsys) -> None:
    main(["check", "1 > 0 and", "--json"])
    document = json.loads(capsys.readouterr().out)
    assert [document[key] for key in ("schema_version", "tool")] == [2, "dpm-xl"]
    assert document["summary"] == {
        "total": 1,
        "parsed": 0,
        "errors": 1,
        "warnings": 0,
        "skipped": 0,
    }


def test_eval_writes_junit(tmp_path, capsys) -> None:
    import xml.etree.ElementTree as ET

    data = _write(tmp_path, [_fact("0010", 1), _fact("0020", 2)])
    shifted = "{tA, r0010, c0010} = time_shift({tA, r0020, c0010}, A, 1, refPeriod)"
    rules = [
        *SEVERITIES,
        {"code": "x", "expression": "1 / 0 > 1"},
        {"code": "u", "expression": shifted},
    ]
    assert main(["eval", _rule_file(tmp_path, rules), data, "--format", "junit"]) == 1
    suite = ET.fromstring(capsys.readouterr().out)
    assert suite.attrib == {
        "name": "rules.json",
        "tests": "7",
        "failures": "1",
        "errors": "1",
        "skipped": "3",
    }
    cases = {case.get("name"): case for case in suite.iter("testcase")}

    def child(name: str, tag: str) -> ET.Element:
        found = cases[name].find(tag)
        assert found is not None
        return found

    assert child("e", "failure").get("type") == "error"
    assert "1 should exceed 5" in (child("e", "failure").text or "")
    assert cases["w"].find("failure") is None
    assert (child("w", "system-out").text or "").startswith(
        "1 failing record [warning]"
    )
    assert cases["ok"].find("*") is None
    assert child("na", "skipped").get("message") == "precondition not met"
    assert child("off", "skipped").get("message") == "inactive rule"
    assert child("x", "error").get("message") == "division by zero"
    # An unsupported rule was not checked, as for the exit status.
    assert cases["u"].find("error") is None
    assert "time_shift" in (child("u", "skipped").get("message") or "")
    assert (
        main(
            [
                "eval",
                _rule_file(tmp_path, SEVERITIES[1:]),
                data,
                "--format",
                "junit",
                "--fail-on",
                "warning",
            ]
        )
        == 1
    )
    suite = ET.fromstring(capsys.readouterr().out)
    assert suite.get("failures") == "1"


def test_inline_expressions_are_labelled_expression(capsys) -> None:
    assert main(["check", "sun(1) > 0"]) == 0
    assert capsys.readouterr().err.startswith(
        "expression: error: unknown function 'sun'; did you mean 'sum'?"
    )


def test_check_report_names_the_missing_extra(monkeypatch, capsys) -> None:
    monkeypatch.setattr("dpmxl.cli.find_spec", lambda name: None)
    with pytest.raises(SystemExit) as exit_:
        main(["check-report", "module.json", "report.zip"])
    assert exit_.value.code == 2
    assert 'needs the xbrl extra: pip install "dpm-xl[xbrl]"' in capsys.readouterr().err


def test_a_json_rule_file_is_read_once(tmp_path, monkeypatch) -> None:
    path = _rule_file(tmp_path, SEVERITIES)
    reads = []
    read_text = Path.read_text

    def counted(self: Path, *args: Any, **kwargs: Any) -> str:
        reads.append(self)
        return read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", counted)
    rules, module = _source(path)
    assert [rule.code for rule in rules] == [rule["code"] for rule in SEVERITIES]
    assert module is None
    assert len(reads) == 1
