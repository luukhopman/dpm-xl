import json

import pytest

from dpmxl.cli import main
from dpmxl.rules import Rule, RuleFileError, load_rules, rules_from


def test_rules_carry_severity_active_modules_and_source() -> None:
    (rule,) = load_rules(
        [
            {
                "code": "v1",
                "expression": "{tT} > 0",
                "precondition": {"expression": "{v_T}"},
                "severity": "warning",
                "active": False,
                "modules": ["COREP_OF"],
                "source": "eba",
                "title": "ignored",
            }
        ]
    )
    assert rule == Rule(
        "v1", "{tT} > 0", "{v_T}", "warning", False, ("COREP_OF",), "eba"
    )


def test_rules_default_to_active_errors_for_every_module() -> None:
    rules = load_rules(
        [
            {"expression": "1 = 1", "severity": None, "active": None},
            {"code": "no expression"},
            {"code": 7, "expression": "2 = 2"},
        ]
    )
    assert rules == [Rule("1", "1 = 1"), Rule("7", "2 = 2")]
    assert rules[0].applies_to("ANY")


def test_text_rule_files_label_lines(tmp_path) -> None:
    path = tmp_path / "rules.txt"
    path.write_text("# comment\n\n1 = 1\n", encoding="utf-8")
    assert load_rules(path) == [Rule("line 3", "1 = 1")]


@pytest.mark.parametrize(
    ("entries", "message"),
    [
        ([1], "[0]: expected an object, got the number 1"),
        (
            [{"expression": "1", "severity": "fatal"}],
            '[0].severity: expected "error" or "warning", got "fatal"',
        ),
        (
            [{"expression": "1", "active": "no"}],
            '[0].active: expected true or false, got "no"',
        ),
        (
            [{"expression": "1", "modules": "M"}],
            '[0].modules: expected a list of module codes, got "M"',
        ),
        (
            [{"expression": "1", "modules": [""]}],
            "[0].modules: expected a list of module codes, got a list",
        ),
        ([{"expression": 1}], "[0].expression: expected a string, got the number 1"),
        (
            [{"expression": "1", "precondition": {"expression": 2}}],
            "[0].precondition.expression: expected a string, got the number 2",
        ),
        ([{"expression": "1", "code": True}], "[0].code: expected a string, got true"),
        (
            [{"expression": "1", "source": 3}],
            "[0].source: expected a string, got the number 3",
        ),
    ],
)
def test_malformed_rules_name_the_field(entries, message) -> None:
    with pytest.raises(RuleFileError) as caught:
        load_rules(entries)
    assert str(caught.value) == message


def test_rules_from_prefixes_the_path() -> None:
    with pytest.raises(RuleFileError, match=r"^rules\[1\]: expected an object"):
        rules_from([{"expression": "1"}, None], "rules")


def test_a_json_rule_file_must_be_a_list(tmp_path) -> None:
    path = tmp_path / "rules.json"
    path.write_text('{"rules": []}', encoding="utf-8")
    with pytest.raises(RuleFileError, match="must hold a list of rules, got an object"):
        load_rules(path)
    path.write_text("[", encoding="utf-8")
    with pytest.raises(RuleFileError, match=r"^not JSON"):
        load_rules(path)


def _data(tmp_path):
    data = tmp_path / "data.json"
    data.write_text(
        json.dumps(
            {
                "tables": [{"code": "T", "rows": ["0010"], "columns": ["0010"]}],
                "facts": [{"table": "T", "row": "0010", "column": "0010", "value": 5}],
            }
        ),
        encoding="utf-8",
    )
    return str(data)


def _rules(tmp_path, rules):
    path = tmp_path / "rules.json"
    path.write_text(json.dumps(rules), encoding="utf-8")
    return str(path)


def test_eval_skips_inactive_rules_and_shows_severity(tmp_path, capsys) -> None:
    rules = _rules(
        tmp_path,
        [
            {
                "code": "a",
                "expression": "{tT, r0010, c0010} > 9",
                "severity": "warning",
            },
            {"code": "b", "expression": "{tT, r0010, c0010} / 0 > 1", "active": False},
        ],
    )
    assert main(["eval", rules, _data(tmp_path)]) == 1
    output = capsys.readouterr().out
    assert "a: failed (warning)" in output
    assert "b: skipped (inactive)" in output
    assert "2 rules: 1 failed, 1 skipped" in output
    main(["eval", rules, _data(tmp_path), "--json"])
    skipped = json.loads(capsys.readouterr().out)["results"][1]
    assert skipped["status"] == "skipped"
    assert skipped["active"] is False
    assert skipped["message"] == "inactive rule"
    assert skipped["counts"] == {"passed": 0, "failed": 0, "null": 0}


def test_check_skips_inactive_rules(tmp_path, capsys) -> None:
    rules = _rules(
        tmp_path,
        [
            {"code": "a", "expression": "1 = 1"},
            {"code": "b", "expression": "1 = = 1", "active": False},
        ],
    )
    assert main(["check", rules]) == 0
    assert (
        capsys.readouterr().out == "1/1 expressions parsed; 1 inactive rule skipped\n"
    )
    main(["check", rules, "--json"])
    assert json.loads(capsys.readouterr().out)["skipped"] == ["b"]


def test_a_malformed_rule_is_invalid_input(tmp_path, capsys) -> None:
    rules = _rules(tmp_path, [{"code": "a", "expression": "1 = 1", "active": 1}])
    assert main(["eval", rules, _data(tmp_path)]) == 3
    assert (
        "[0].active: expected true or false, got the number 1"
        in capsys.readouterr().err
    )
