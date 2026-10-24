"""Evaluation of the DPM-XL constructs beyond the EBA rule corpus."""

from datetime import date, datetime
from decimal import Decimal

import pytest

from dpmxl import (
    DpmXlSyntaxError,
    Item,
    MemoryProvider,
    Number,
    TableLayout,
    Value,
    evaluate_rule,
    explain,
    parse,
    parse_program,
    references,
    tables,
)
from dpmxl.ast import (
    Assignment,
    Binary,
    Call,
    Get,
    In,
    Literal_,
    Name,
    Parameter,
    PersistentAssignment,
    Program,
    Selection,
    SetLiteral,
    Where,
    With,
    walk,
)
from dpmxl.evaluator import Evaluator
from dpmxl.explain import TIMES
from dpmxl.provider import CellKey
from dpmxl.values import ValueSet


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


def numbers(*items: int) -> ValueSet:
    return ValueSet(tuple(Number(Decimal(item)) for item in items))


@pytest.mark.parametrize(
    ("expression", "expected"),
    [
        ("{1, 2, 2.0}", numbers(1, 2)),
        ("{}", ValueSet()),
        ("{(-5), 3}", numbers(-5, 3)),
        ("{[eba_qK:a], [qK:a], [qK:b]}", ValueSet((Item("qK", "a"), Item("qK", "b")))),
        ("union({1, 2}, {2, 3}, {4})", numbers(1, 2, 3, 4)),
        ("intersect({1, 2, 3}, {2, 3, 4}, {3})", numbers(3)),
        ("setdiff({1, 2, 3}, {2})", numbers(1, 3)),
        ("symdiff({1, 2}, {2, 3})", numbers(1, 3)),
        ("set_of({tT, r*, c0010})", numbers(100, 60, 40)),
        ("set_of(null)", ValueSet()),
        ("union(1, null)", numbers(1)),
        ("3 in union({1, 2}, {3})", True),
        ("2 in setdiff({1, 2}, {2})", False),
        ("100 in {tT, r*, c0010}", True),
        ("1 not in {}", True),
        ("null in {1}", None),
    ],
)
def test_set_literals_and_operators(expression: str, expected: Value) -> None:
    assert value(expression) == expected


def test_in_takes_any_set_operand() -> None:
    assert values("with {tT, c0010}: {r*} in set_of({tT, r0010-0020, c0010})") == {
        "0010": True,
        "0020": True,
        "0030": False,
    }
    node = parse("{tA} in union({1}, {2})")
    assert isinstance(node, In) and isinstance(node.values, Call)
    # A brace after in that starts with a reference is a selection.
    selection = parse("{tA} in {tB, r*}")
    assert isinstance(selection, In) and isinstance(selection.values, Selection)


@pytest.mark.parametrize(
    ("expression", "message"),
    [
        ("{1} = {1}", "cannot compare set with set"),
        ("{tT, r0010, c0010, default: {1}} > 0", "a set default applies only to set"),
        ("union({1}) = {1}", "union takes at least 2 operands"),
        ("setdiff({1}, {2}, {3}) = {1}", "setdiff takes 2 operands"),
        ("{{1}} = 1", "unknown selection component '{'"),
    ],
)
def test_set_errors(expression: str, message: str) -> None:
    result = evaluate_rule(expression, report())
    assert result.status == "error"
    assert result.message is not None and message in result.message


def test_set_default_parses() -> None:
    node = parse("{tT, r0010, default: {1, 2}}")
    assert isinstance(node, Selection)
    assert node.spec.default == SetLiteral(
        (Literal_(Decimal(1), "number"), Literal_(Decimal(2), "number"))
    )
    assert node.spec.text() == "{tT, r0010, default: {1, 2}}"


def provider_with_references(**parameters: Value) -> MemoryProvider:
    tables = [
        TableLayout("A", rows=("0010", "0020"), columns=("0010",)),
        TableLayout("B", rows=("0010", "0020"), columns=("0010",)),
    ]
    data: dict[CellKey, Value] = {
        ("A", "0010", "0010", None, ()): Number.of(1, 0),
        ("A", "0020", "0010", None, ()): Number.of(2, 0),
        ("B", "0010", "0010", None, ()): Number.of(3, 0),
    }
    return MemoryProvider(
        tables,
        data,
        parameters=parameters,
        table_groups={"G": ("A", "B"), "ONE": ("B",)},
        operations={
            "v1": "with {c0010}: {tA, r*} + 10",
            "v2": "{o_v1, r0010} * 2",
            "loop": "{o_loop} + 1",
        },
    )


@pytest.mark.parametrize(
    ("expression", "parameters", "expected"),
    [
        ("{p_Level, string}", {"Level": "solo"}, "solo"),
        ("{pLevel, string, default: 'x'}", {}, "x"),
        ("{p`a.b`, number}", {"a.b": 5}, Number(Decimal(5))),
        ("{p_N, integer}", {"N": Number(Decimal(3))}, Number(Decimal(3))),
        ("{p_N, number, default: (-1)}", {}, Number(Decimal(-1))),
        ("{p_N, number}", {}, None),
        ("{p_B, boolean}", {"B": True}, True),
        ("{p_I, item}", {"I": "eba_qK:a"}, Item("qK", "a")),
        ("{p_D, date}", {"D": "2026-12-31"}, date(2026, 12, 31)),
        ("{p_S, set-number}", {"S": [1, 2, 2]}, numbers(1, 2)),
        ("{p_S, set-number, default: {1}}", {}, numbers(1)),
        ("{p_S, set-item}", {"S": ["qK:a"]}, ValueSet((Item("qK", "a"),))),
        ("3 in {p_S, set-integer}", {"S": (1, 3)}, True),
    ],
)
def test_typed_parameters(expression: str, parameters: dict, expected: Value) -> None:
    assert value(expression, provider_with_references(**parameters)) == expected


@pytest.mark.parametrize(
    ("expression", "parameters", "message"),
    [
        ("{p_N, integer} = 1", {"N": Number(Decimal("1.5"))}, "is not an integer"),
        ("{p_N, number} = 1", {"N": "x"}, "is not a number"),
        ("{p_S, set-string} = 1", {"S": "x"}, "is not a set"),
        ("{p_B, boolean}", {"B": 1}, "is not a Boolean"),
    ],
)
def test_typed_parameter_errors(
    expression: str, parameters: dict, message: str
) -> None:
    result = evaluate_rule(expression, provider_with_references(**parameters))
    assert result.status == "error"
    assert result.message is not None and message in result.message


def test_table_groups_key_records_by_table() -> None:
    provider = provider_with_references()
    assert values("{g_G, r0010, c0010}", provider) == {
        "A": Number(Decimal(1)),
        "B": Number(Decimal(3)),
    }
    assert value("{g_ONE, r0010, c0010}", provider) == Number(Decimal(3))
    assert values("with {gG, c0010, default: 0}: {r*} > 0", provider) == {
        ("A", "0010"): True,
        ("A", "0020"): True,
        ("B", "0010"): True,
        ("B", "0020"): False,
    }


def test_operation_references_evaluate_the_operation() -> None:
    provider = provider_with_references()
    assert values("{o_v1}", provider) == {
        "0010": Number(Decimal(11)),
        "0020": Number(Decimal(12)),
    }
    assert value("{o_v1, r0020}", provider) == Number(Decimal(12))
    assert value("{o_v2}", provider) == Number(Decimal(22))
    assert evaluate_rule("{o_v1, r0010} = 11", provider).status == "passed"


@pytest.mark.parametrize(
    ("expression", "status", "message"),
    [
        ("{o_loop} > 0", "error", "operation loop refers to itself"),
        ("{o_v1, c0010} > 0", "error", "has no c key"),
        ("{o_missing} > 0", "unsupported", "needs a provider that resolves"),
        ("{g_missing, r0010} > 0", "unsupported", "needs a provider that resolves"),
    ],
)
def test_reference_errors(expression: str, status: str, message: str) -> None:
    result = evaluate_rule(expression, provider_with_references())
    assert result.status == status
    assert result.message is not None and message in result.message


def test_references_describe_groups_and_operations() -> None:
    node = parse("{tA, r0010} + {g_G, r0010} + {o_v1, r0010} + {p_X, number}")
    found = references(node)
    assert [(item.kind, item.code, item.spec.table) for item in found] == [
        ("table", "A", "A"),
        ("table_group", "G", None),
        ("operation", "v1", None),
    ]
    assert tables(node) == ("A",)
    assert tables(node, provider_with_references()) == ("A", "B")
    assert parse("{t_A}") == parse("{tA}") == parse("{t`A`}")


def test_parse_program_reads_statements_and_assignments() -> None:
    source = (
        "total := sum({tT, r*, c0010}); {tT, r0010, c0020} <- total * 2; "
        "{v_X} <- 1; with {tT, c0010}: total > {r0010} * 3;"
    )
    program = parse_program(source)
    assert isinstance(program, Program)
    first, second, third, fourth = program.statements
    assert isinstance(first, Assignment) and first.name == "total"
    assert isinstance(second, PersistentAssignment)
    assert isinstance(second.target, Selection)
    assert isinstance(third, PersistentAssignment)
    assert third.target == Parameter("X")
    assert isinstance(fourth, With)
    assert source[slice(*second.span)] == "{tT, r0010, c0020} <- total * 2"
    assert [type(node).__name__ for node in walk(program)].count("Selection") == 3


def test_parse_keeps_returning_single_expressions() -> None:
    assert parse("{tT, r0010} > 0;") == parse("{tT, r0010} > 0")
    assert parse_program("1 = 1").statements == (parse("1 = 1"),)
    with pytest.raises(DpmXlSyntaxError, match="several statements need parse_program"):
        parse("a := 1; a > 0")
    with pytest.raises(DpmXlSyntaxError, match="assignments need parse_program"):
        parse("{tT, r0010} <- 1")
    with pytest.raises(DpmXlSyntaxError, match="assignment target"):
        parse_program("{p_X, number} <- 1")


def test_programs_evaluate_statement_by_statement() -> None:
    source = (
        "total := sum({tT, r*, c0010}); {tT, r0010, c0020} <- total * 2; "
        "with {tT, c0010}: total > {r0010} * 3"
    )
    result = evaluate_rule(source, report())
    assert result.status == "failed"
    assert list(result.assignments) == ["{tT, r0010, c0020}"]
    assigned = result.assignments["{tT, r0010, c0020}"].single()
    assert assigned is not None and assigned.value == Number(Decimal(400))
    assert result.evaluation is not None
    explanation = explain(result.evaluation, source, result.failures[0].key)
    assert (
        explanation.summary == f"200 should exceed 300 (100 {TIMES} 3): difference 100"
    )


def test_temporaries_shadow_parameters_and_keep_records() -> None:
    provider = report(x=Number(Decimal(1)))
    assert evaluate_rule("x := {tT, c0010, r*}; x > 50", provider).counts == {
        "passed": 2,
        "failed": 1,
        "null": 0,
    }
    assert evaluate_rule("x > 0", provider).status == "passed"
    # A program whose result is not Boolean still returns its assignments.
    result = evaluate_rule("{vY} <- 1 + 1", provider)
    assert result.status == "error" and "number values" in (result.message or "")
    assigned = result.assignments["{vY}"].single()
    assert assigned is not None and assigned.value == Number(Decimal(2))
