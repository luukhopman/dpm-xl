"""Evaluation of the DPM-XL constructs beyond the EBA rule corpus."""

from datetime import date, datetime
from decimal import Decimal

import pytest

from dpmxl import MemoryProvider, Number, TableLayout, Value, evaluate_rule, parse
from dpmxl.ast import Binary, Get, Literal_, Name, Where
from dpmxl.evaluator import Evaluator
from dpmxl.provider import CellKey


def report(**parameters: Value) -> MemoryProvider:
    tables = [
        TableLayout("T", rows=("0010", "0020", "0030"), columns=("0010", "0020")),
        TableLayout("O", columns=("0010",), open_keys=("qKEY", "qDAT")),
    ]
    values: dict[CellKey, Value] = {
        ("T", "0010", "0010", None, ()): Number.of(100, 0),
        ("T", "0020", "0010", None, ()): Number.of(60, 0),
        ("T", "0030", "0010", None, ()): Number.of(40, 0),
        ("T", "0010", "0020", None, ()): "LEI-A",
        ("T", "0020", "0020", None, ()): "LEI-B",
    }
    for index, (key, day) in enumerate(
        (("a", date(2026, 3, 31)), ("b", date(2026, 6, 30)), ("c", date(2026, 9, 30)))
    ):
        values["O", None, "0010", None, (("qKEY", key), ("qDAT", day))] = Number.of(
            10 * (index + 1), 0
        )
    return MemoryProvider(tables, values, parameters=parameters)


def value(expression: str, provider: MemoryProvider | None = None) -> Value:
    result = Evaluator(provider or report()).run(parse(expression)).result
    record = result.single()
    return record.value if record else None


def values(expression: str, provider: MemoryProvider | None = None) -> dict:
    result = Evaluator(provider or report()).run(parse(expression)).result
    return {
        key if len(key) != 1 else key[0]: record.value
        for key, record in result.records.items()
    }


@pytest.mark.parametrize(
    ("expression", "expected"),
    [
        ('"ab" & "cd"', "abcd"),
        ("'' & \"x\"", "x"),
        ('null & "x"', None),
        ('substr("abcdef", 2)', "bcdef"),
        ('substr("abcdef", 2, 3)', "bcd"),
        ('substr("abc")', "abc"),
        ('substr("abc", 5)', ""),
        ("substr(null, 1)", None),
        ("log(8, 2)", Number(Decimal(3))),
        ("log(-1, 2)", None),
        ("year(#2026-05-31#)", Number(Decimal(2026))),
        ("semester(#2026-07-01#)", Number(Decimal(2))),
        ("quarter(#2026-05-31#)", Number(Decimal(2))),
        ("month(#2026-05-31#)", Number(Decimal(5))),
        ("week(#2026-12-31#)", Number(Decimal(53))),
        ("day(#2026-05-31#)", Number(Decimal(31))),
        ("year(null)", None),
        ("date(2026, 2, 28)", date(2026, 2, 28)),
        ("#2026-12-31T10:00:00#", datetime(2026, 12, 31, 10)),
        ("#2026-12-31T10:00:00# > #2026-12-31#", True),
        ("#2026-12-31T00:00:00# = #2026-12-31#", True),
    ],
)
def test_text_number_and_date_functions(expression: str, expected: Value) -> None:
    assert value(expression) == expected


def test_concatenation_binds_between_comparison_and_sum() -> None:
    node = parse('"a" & "b" = "a" & "b"')
    assert isinstance(node, Binary) and node.op == "="
    assert isinstance(node.left, Binary) and node.left.op == "&"
    concat = parse("1 + 2 & 3")
    assert isinstance(concat, Binary) and concat.op == "&"


def test_concatenation_and_substr_work_per_record() -> None:
    assert values('with {tT, c0020}: {r0010-0020} & "/x"') == {
        "0010": "LEI-A/x",
        "0020": "LEI-B/x",
    }
    assert values("with {tT, c0020}: substr({r0010-0020}, 5, 1)") == {
        "0010": "A",
        "0020": "B",
    }
    assert values("with {tO, c0010}: month({tO, c0010} [get qDAT])") == {
        ("a", date(2026, 3, 31)): Number(Decimal(3)),
        ("b", date(2026, 6, 30)): Number(Decimal(6)),
        ("c", date(2026, 9, 30)): Number(Decimal(9)),
    }


@pytest.mark.parametrize(
    ("expression", "message"),
    [
        ('1 & "x" = "x"', "& needs text, found number"),
        ('substr("abc", 0) = "a"', "substr start must be at least 1"),
        ('substr("abc", 1, -1) = "a"', "substr length must not be negative"),
        ('substr("abc", 1.5) = "a"', "substr needs whole numbers"),
        ("substr(1, 1) = 1", "substr needs text, found number"),
        ("year(1) = 1", "year needs a date, found number"),
        ("date(2026, 2, 30) = #2026-02-28#", "invalid date"),
    ],
)
def test_text_and_date_function_errors(expression: str, message: str) -> None:
    result = evaluate_rule(expression, report())
    assert result.status == "error"
    assert result.message is not None and message in result.message


def test_escaped_names_and_empty_strings_parse() -> None:
    node = parse("{tO, c0010} [where `qKEY` = ''] [get `qDAT`]")
    assert isinstance(node, Get) and node.name == "qDAT"
    assert isinstance(node.operand, Where)
    assert node.operand.condition == Binary("=", Name("qKEY"), Literal_("", "string"))
    assert values("{tO, c0010} [where `qKEY` = 'a']") == {
        ("a", date(2026, 3, 31)): Number(Decimal(10))
    }
