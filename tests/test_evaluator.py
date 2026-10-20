from datetime import date
from decimal import Decimal

import pytest

from dpmxl import (
    Item,
    MemoryProvider,
    Number,
    TableLayout,
    Value,
    evaluate_rule,
    explain,
)
from dpmxl.provider import CellKey

ROWS = ("0010", "0020", "0030")
COLUMNS = ("0010", "0020")


def closed(values, *, decimals=0, reported=None, parameters=None, extra=()):
    tables = [TableLayout("C_01.00", rows=ROWS, columns=COLUMNS), *extra]
    data = {
        ("C_01.00", row, column, None, ()): Number.of(value, decimals)
        for (row, column), value in values.items()
    }
    return MemoryProvider(tables, data, reported=reported, parameters=parameters)


def test_sum_rule_passes_and_fails_per_column() -> None:
    provider = closed(
        {
            ("0010", "0010"): 100,
            ("0020", "0010"): 60,
            ("0030", "0010"): 40,
            ("0010", "0020"): 1204,
            ("0020", "0020"): 1180,
            ("0030", "0020"): 31,
        }
    )
    expression = (
        "with {tC_01.00, c*, default: 0, interval: true}: {r0010} = {r0020} + {r0030}"
    )
    result = evaluate_rule(expression, provider)
    assert result.status == "failed"
    assert result.counts == {"passed": 1, "failed": 1, "null": 0}
    failure = result.failures[0]
    assert failure.key == {"c": "0020"}
    assert {point.row for point in failure.points} == {"0010", "0020", "0030"}
    explanation = explain(_traced(result), expression, failure.key)
    assert explanation.filled == "1,204 = 1,180 + 31"
    assert explanation.summary == (
        "expected 1,204 = 1,180 + 31, off by 7 (tolerance ±1.5)"
    )
    assert [(point.row, point.column) for point in explanation.primary] == [
        ("0010", "0020")
    ]
    assert [operand.source for operand in explanation.operands] == [
        "{r0010}",
        "{r0020}",
        "{r0030}",
    ]


def test_interval_tolerance_accepts_rounding_differences() -> None:
    provider = closed(
        {("0010", "0010"): 100, ("0020", "0010"): 60, ("0030", "0010"): 41}
    )
    tolerant = "with {tC_01.00, c0010, default: 0, interval: true}: {r0010} = {r0020} + {r0030}"
    exact = tolerant.replace("interval: true", "interval: false")
    assert evaluate_rule(tolerant, provider).status == "passed"
    assert evaluate_rule(exact, provider).status == "failed"


def test_missing_values_use_default_or_stay_null() -> None:
    provider = closed({("0010", "0010"): 5})
    assert (
        evaluate_rule(
            "{tC_01.00, r0010, c0010, default: 0} = {tC_01.00, r0020, c0010, default: 0}",
            provider,
        ).status
        == "failed"
    )
    # With a null default the comparison is not evaluated.
    assert (
        evaluate_rule(
            "{tC_01.00, r0010, c0010} = {tC_01.00, r0020, c0010}", provider
        ).status
        == "not_applicable"
    )
    result = evaluate_rule(
        "with {tC_01.00, c0010, default: null}: not(isnull({r0020}))", provider
    )
    assert result.status == "failed"


def test_precondition_controls_applicability() -> None:
    provider = closed({("0010", "0010"): 1}, reported={"C_01.00"})
    rule = "{tC_01.00, r0010, c0010, default: 0} = 2"
    assert evaluate_rule(rule, provider, precondition="{v_C_01.00}").status == "failed"
    assert (
        evaluate_rule(rule, provider, precondition="{v_C_02.00}").status
        == "not_applicable"
    )


def test_if_then_else_and_items() -> None:
    tables = [
        TableLayout("F_00.01", rows=("0010",), columns=("0010",)),
        TableLayout("F_02.00", rows=("0010", "0020"), columns=("0010",)),
    ]
    values: dict[CellKey, Value] = {
        ("F_00.01", "0010", "0010", None, ()): Item.parse("eba_AS:x2"),
        ("F_02.00", "0010", "0010", None, ()): Number.of(10),
        ("F_02.00", "0020", "0010", None, ()): Number.of(9),
    }
    provider = MemoryProvider(tables, values)
    rule = (
        'with {c0010, interval: true}: if ( {tF_00.01, r0010, default: ""} = [eba_AS:x2] ) '
        "then ( {tF_02.00, r0010, default: 0} = sum ({tF_02.00, r0020-0085, default: 0}) ) endif"
    )
    result = evaluate_rule(rule, provider)
    assert result.status == "failed"
    explanation = explain(_traced(result), rule, result.failures[0].key)
    assert explanation.summary == "expected 10 = 9, off by 1"
    other = rule.replace("[eba_AS:x2]", "[eba_AS:x1]")
    assert evaluate_rule(other, provider).status == "not_applicable"


def test_open_table_where_group_by_and_sub() -> None:
    tables = [
        TableLayout(
            "C_07.00.a", rows=("0010", "0020"), columns=("0010",), open_keys=("qEBB",)
        ),
        TableLayout("C_02.00", rows=("0010",), columns=("0010",)),
    ]
    a, b = Item("qEC", "qx1"), Item("qEC", "qx2")
    values: dict[CellKey, Value] = {
        ("C_07.00.a", "0010", "0010", None, (("qEBB", a),)): Number.of(10),
        ("C_07.00.a", "0020", "0010", None, (("qEBB", a),)): Number.of(4),
        ("C_07.00.a", "0010", "0010", None, (("qEBB", b),)): Number.of(20),
        ("C_07.00.a", "0020", "0010", None, (("qEBB", b),)): Number.of(25),
        ("C_02.00", "0010", "0010", None, ()): Number.of(30),
    }
    provider = MemoryProvider(tables, values)
    per_key = "with {tC_07.00.a, c0010, default: 0, interval: true}: {r0020} <= {r0010}"
    result = evaluate_rule(per_key, provider)
    assert result.status == "failed"
    assert [outcome.key for outcome in result.failures] == [{"qEBB": b}]

    filtered = (
        "with {tC_07.00.a, c0010, default: 0, interval: true}: "
        "{r0020} [where EBB in {[eba_qEC:qx1]}] <= {r0010} [where EBB in {[eba_qEC:qx1]}]"
    )
    assert evaluate_rule(filtered, provider).status == "passed"

    total = "{tC_02.00, r0010, c0010, default: 0} = sum({tC_07.00.a, r0010, c0010, default: 0})"
    assert evaluate_rule(total, provider).status == "passed"

    grouped = (
        "sum({tC_07.00.a, c0010, default: 0} group by qEBB) >= "
        "{tC_07.00.a, r0010, c0010, default: 0}"
    )
    assert evaluate_rule(grouped, provider).status == "passed"

    fixed = (
        "{tC_07.00.a, r0010, c0010, default: 0} [sub qEBB = [eba_qEC:qx2]] = "
        "{tC_02.00, r0010, c0010} - 10"
    )
    assert evaluate_rule(fixed, provider).status == "passed"


def test_unsupported_and_errors_are_reported_not_raised() -> None:
    provider = closed({})
    assert (
        evaluate_rule(
            "{tC_01.00, r0010, c0010} = time_shift({tC_01.00, r0020, c0010}, A, 1, refPeriod)",
            provider,
        ).status
        == "unsupported"
    )
    assert evaluate_rule("{tX_99.99, r0010} = 1", provider).status == "error"
    assert evaluate_rule("{r0010", provider).status == "error"
    assert (
        evaluate_rule("{tC_01.00, r0010, c0010, default: 0} + 1", provider).status
        == "error"
    )


def test_match_len_dates_and_parameters() -> None:
    tables = [TableLayout("B_01.01", rows=("0010",), columns=("0010", "0020"))]
    values: dict[CellKey, Value] = {
        ("B_01.01", "0010", "0010", None, ()): "529900T8BM49AURSDO55",
        ("B_01.01", "0010", "0020", None, ()): date(2027, 1, 1),
    }
    provider = MemoryProvider(
        tables,
        values,
        parameters={"refPeriod": date(2026, 12, 31), "ReportingLevel": "con"},
    )
    assert (
        evaluate_rule(
            'match({tB_01.01, r0010, c0010}, "^[A-Z0-9]{18}[0-9]{2}$")', provider
        ).status
        == "passed"
    )
    assert (
        evaluate_rule("len({tB_01.01, r0010, c0010}) <= 10", provider).status
        == "failed"
    )
    assert (
        evaluate_rule("{tB_01.01, r0010, c0020} <= #2026-12-31#", provider).status
        == "failed"
    )
    assert (
        evaluate_rule(
            "{tB_01.01, r0010, c0020} <= {tB_01.01, r0010, c0020} [get refPeriod]",
            provider,
        ).status
        == "failed"
    )
    assert evaluate_rule("{vReportingLevel} = 'con'", provider).status == "passed"


def test_percent_literals_and_scalar_functions() -> None:
    provider = closed(
        {("0010", "0010"): 45, ("0020", "0010"): 1000, ("0030", "0010"): -7}
    )
    assert (
        evaluate_rule(
            "with {tC_01.00, c0010, interval: false}: {r0010} = {r0020} * 4.5%",
            provider,
        ).status
        == "passed"
    )
    assert (
        evaluate_rule(
            "with {tC_01.00, c0010}: abs({r0030}) = max({r0010}, 7, -1) - 38", provider
        ).status
        == "passed"
    )


@pytest.mark.parametrize(
    ("left", "op", "right", "expected"),
    [
        (Number.of(100, 0), "=", Number.of("100.4"), True),
        (Number.of(100, 0), "=", Number.of("100.6"), False),
        (Number.of(100, 0), "<", Number.of("99.6"), True),
        (Number.of(100, 0), ">", Number.of("100.4"), True),
        (Number.of(100, 0), ">=", Number.of("100.6"), False),
    ],
)
def test_interval_comparisons(left, op, right, expected) -> None:
    from dpmxl import compare

    assert compare(op, left, right) is expected


def test_number_tolerance_from_decimals() -> None:
    assert Number.of(5, 2).tolerance == Decimal("0.005")
    assert Number.of(5, -3).tolerance == Decimal(500)
    assert (Number.of(1, 0) * Number.of(3)).tolerance == Decimal("1.5")


def _traced(result):
    assert result.evaluation is not None
    return result.evaluation
