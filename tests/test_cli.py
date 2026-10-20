import json

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
    assert "expected 1,204 = 1,180 + 17, off by 7" in output
