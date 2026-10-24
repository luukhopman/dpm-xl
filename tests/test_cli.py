import json

import pytest

from dpmxl.cli import main


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
