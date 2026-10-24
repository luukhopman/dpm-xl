import json
import runpy
from pathlib import Path

import pytest

from dpmxl.cli import main

EXAMPLES = Path(__file__).parent.parent / "examples"


def test_quickstart_explains_the_failing_column(capsys) -> None:
    runpy.run_path(str(EXAMPLES / "quickstart.py"), run_name="__main__")
    output = capsys.readouterr().out
    assert "failed {'passed': 1, 'failed': 1, 'null': 0}" in output
    assert "{'c': '0020'} 1,204 should equal 1,211 (1,180 + 31)" in output


def test_custom_provider_reports_each_rule(capsys) -> None:
    runpy.run_path(str(EXAMPLES / "custom_provider.py"), run_name="__main__")
    output = capsys.readouterr().out
    assert "C_02.00/0020/0010: -3 should be at least 0" in output
    assert "C_02.00/0030/0010: {tC_02.00, r0030, c0010} must be reported" in output
    assert "C_27.00/LEI-B: -5 should exceed 0" in output


def test_cli_evaluates_the_example_rule_file(capsys) -> None:
    rules, data = str(EXAMPLES / "rules.json"), str(EXAMPLES / "data.json")
    assert main(["check", rules]) == 0
    assert main(["eval", rules, data]) == 1
    output = capsys.readouterr().out
    assert "4 rules: 2 failed, 1 passed, 1 not_applicable" in output
    assert main(["eval", rules, data, "--json"]) == 1
    results = json.loads(capsys.readouterr().out)
    assert [result["status"] for result in results] == [
        "failed",
        "failed",
        "passed",
        "not_applicable",
    ]
    assert results[1]["failures"][0]["cells"] == ["{tC_27.00, c0010, qCPI=LEI-B}"]


def test_cli_check_json_reports_positions(capsys) -> None:
    assert main(["check", "{tA} >=", "--json"]) == 1
    document = json.loads(capsys.readouterr().out)
    assert document["errors"] == [
        {
            "source": "argument",
            "message": "expression ends where an operand is expected",
            "position": 7,
        }
    ]


def test_cli_rejects_a_malformed_rule_file(tmp_path, capsys) -> None:
    rules = tmp_path / "rules.json"
    rules.write_text('{"code": "x"}', encoding="utf-8")
    assert main(["check", str(rules)]) == 2
    assert "must hold a list of rules" in capsys.readouterr().err


def test_cli_version(capsys) -> None:
    with pytest.raises(SystemExit):
        main(["--version"])
    assert capsys.readouterr().out.startswith("dpm-xl ")
