from datetime import date
from decimal import Decimal, localcontext
from typing import Any, cast

import pytest

from dpmxl import (
    DataPoint,
    Item,
    MemoryProvider,
    Number,
    TableLayout,
    Value,
    evaluate_rule,
    explain,
)
from dpmxl.explain import MINUS, TIMES
from dpmxl.provider import CellKey
from dpmxl.recordset import unique_points
from dpmxl.values import format_decimal

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
    assert (
        explanation.summary
        == "1,204 should equal 1,211 (1,180 + 31): difference 7, at least 5.5 given the reported precision"
    )
    assert explanation.direction == "too_low"
    assert explanation.tolerance == "1.5"
    assert explanation.left is not None and explanation.left.single_cell
    assert explanation.right is not None and explanation.right.terms == 2
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
    assert explanation.summary == "10 should equal 9: difference 1"
    other = rule.replace("[eba_AS:x2]", "[eba_AS:x1]")
    # DPM-XL 8.1.4: without else, the records whose condition is not true are
    # left out.
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


def test_runtime_failures_are_reported_not_raised() -> None:
    provider = closed({("0010", "0010"): 1})
    for rule, message in [
        ("{tC_01.00, r*, c0010} [sub r = 0010] > 0", "cannot compare"),
        ("power(10, 300) * 1e6000 > 0", "arithmetic error"),
    ]:
        result = evaluate_rule(rule, provider)
        assert result.status == "error"
        assert result.message is not None
        assert message in result.message
    assert evaluate_rule("power(power(10, 300), 2) > 0", provider).status == (
        "not_applicable"
    )


def test_long_sums_evaluate_and_explain() -> None:
    provider = closed({("0010", "0010"): 1, ("0020", "0010"): 1})
    rule = "with {tC_01.00, c0010}: {r0010} = " + " + ".join(["{r0020}"] * 3000)
    result = evaluate_rule(rule, provider)
    assert result.status == "failed"
    explanation = explain(_traced(result), rule, result.failures[0].key)
    assert explanation.summary.startswith("1 should equal 3,000 (1 + 1 + ")
    rule = "with {tC_01.00, c0010}: " + " or ".join(["{r0020} > 1"] * 3000)
    assert evaluate_rule(rule, provider).status == "failed"


@pytest.mark.parametrize(
    ("expression", "expected"),
    [
        # A reported item reads as its qualified name, eba_NC:C.
        ("len({tB, r0010, c0010}) = 8", "passed"),
        ('match({tB, r0010, c0010}, "eba_NC:[A-U]")', "passed"),
        ("len([NC:C10]) = 10", "passed"),
        # An item without a category reads as its code.
        ("len({tB, r0020, c0010}) = 4", "passed"),
        ('substr({tB, r0010, c0010}, 8) = "C"', "passed"),
        ('{tB, r0010, c0010} & "10" = "eba_NC:C10"', "passed"),
        # Booleans read in XML Schema spelling.
        ('match({tB, r0030, c0010}, "true")', "passed"),
        ("len({tB, r0030, c0010}) = 4", "passed"),
    ],
)
def test_text_functions_read_items_and_booleans_as_reported(
    expression: str, expected: str
) -> None:
    table = TableLayout("B", rows=("0010", "0020", "0030"), columns=("0010",))
    provider = MemoryProvider(
        [table],
        {
            ("B", "0010", "0010", None, ()): Item.parse("eba_NC:C"),
            ("B", "0020", "0010", None, ()): Item(None, "ei86"),
            ("B", "0030", "0010", None, ()): True,
        },
    )
    assert evaluate_rule(expression, provider).status == expected


def test_match_len_dates_and_parameters() -> None:
    tables = [TableLayout("B_01.01", rows=("0010",), columns=("0010", "0020"))]
    values: dict[CellKey, Value] = {
        ("B_01.01", "0010", "0010", None, ()): "SYNTHETICDPMXL000002",
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
    assert Number.of(5, "INF") == Number.of(5, "inf") == Number(Decimal(5))
    for decimals in (-7000, 10**20, "two"):
        with pytest.raises(ValueError, match=r"out of range|not an integer"):
            Number.of(5, decimals)


def _traced(result):
    assert result.evaluation is not None
    return result.evaluation


def test_explanations_read_as_sentences() -> None:
    provider = closed(
        {
            ("0010", "0010"): 100,
            ("0020", "0010"): 150,
            ("0030", "0010"): -60,
        }
    )
    rule = "with {tC_01.00, c0010, default: 0, interval: true}: {r0010} = {r0020} + {r0030}"
    result = evaluate_rule(rule, provider)
    explanation = explain(_traced(result), rule, result.failures[0].key)
    assert explanation.filled == "100 = 150 \u2212 60"
    assert explanation.formula == "{r0010} = {r0020} + {r0030}"
    assert (
        explanation.summary
        == "100 should equal 90 (150 \u2212 60): difference 10, at least 8.5 given the reported precision"
    )

    ceiling = "with {tC_01.00, c0010, default: 0, interval: false}: {r0020} <= {r0010}"
    result = evaluate_rule(ceiling, provider)
    explanation = explain(_traced(result), ceiling, result.failures[0].key)
    assert explanation.verb == "should not exceed"
    assert explanation.summary == "150 should not exceed 100: difference 50"


def test_zero_runs_collapse_and_conditions_have_messages() -> None:
    tables = [
        TableLayout(
            "T", rows=tuple(f"{n:04d}" for n in range(10, 80, 10)), columns=("0010",)
        )
    ]
    values: dict[CellKey, Value] = {("T", "0010", "0010", None, ()): Number.of(17)}
    provider = MemoryProvider(tables, values)
    rule = "with {tT, c0010, default: 0}: {r0010} = {r0020} + {r0030} + {r0040} + {r0050} + {r0060}"
    result = evaluate_rule(rule, provider)
    explanation = explain(_traced(result), rule, result.failures[0].key)
    assert explanation.filled == "17 = 0 + 0 (\u00d74)"

    missing = "with {tT, c0010}: not(isnull({r0020}))"
    result = evaluate_rule(missing, provider)
    explanation = explain(_traced(result), missing, result.failures[0].key)
    assert explanation.kind == "missing"
    assert explanation.summary == "{r0020} must be reported"
    assert [(point.row, point.column) for point in explanation.primary] == [
        ("0020", "0010")
    ]

    member = "with {tT, c0010}: {r0010} in {1, 2}"
    result = evaluate_rule(member, provider)
    explanation = explain(_traced(result), member, result.failures[0].key)
    assert explanation.kind == "membership"
    assert explanation.summary == "17 is not one of 1, 2"


def test_interval_arithmetic_follows_eurofiling() -> None:
    # iaf:numeric-multiply: |A*dB| + |B*dA| + dA*dB
    product = Number.of(1_635_500, 0) * Number.of("0.4048", 4)
    assert product.value == Decimal("662050.4000")
    assert product.tolerance == Decimal("0.5") * Decimal("0.4048") + Decimal(
        "1635500"
    ) * Decimal("0.00005") + Decimal("0.5") * Decimal("0.00005")
    # iaf:numeric-divide: largest deviation of the four endpoint quotients
    quotient = Number.of(100, 0) / Number.of(4, 0)
    assert quotient.value == 25
    assert round(quotient.tolerance, 20) == round(
        abs(Decimal(25) - Decimal("100.5") / Decimal("3.5")), 20
    )
    # A divisor interval spanning zero skips the zero endpoint.
    assert (Number.of(1, 0) / Number.of("0.5", 0)).tolerance == Decimal("1.5")


def test_arithmetic_ignores_the_callers_decimal_context() -> None:
    provider = closed(
        {("0010", "0010"): 1234561, ("0020", "0010"): 1234000, ("0030", "0010"): 561}
    )
    rule = "with {tC_01.00, c0010, interval: false}: {r0010} = {r0020} + {r0030}"
    with localcontext() as context:
        context.prec = 6
        assert evaluate_rule(rule, provider).status == "passed"
        assert (Number.of(1, 0) / Number.of(3, 0)).value == Decimal("0." + "3" * 34)


def test_explanations_show_each_sides_interval() -> None:
    provider = closed(
        {
            ("0010", "0010"): 1204,
            ("0020", "0010"): 1180,
            ("0030", "0010"): 31,
        }
    )
    rule = "with {tC_01.00, c0010, default: 0, interval: true}: {r0010} = {r0020} + {r0030}"
    result = evaluate_rule(rule, provider)
    explanation = explain(_traced(result), rule, result.failures[0].key)
    assert explanation.left is not None and explanation.right is not None
    assert (explanation.left.low, explanation.left.high) == ("1,203.5", "1,204.5")
    assert explanation.left.threshold == "0.5"
    assert (explanation.right.low, explanation.right.high) == ("1,210", "1,212")
    assert explanation.right.threshold == "1"
    assert explanation.gap == "5.5"


def test_computed_numbers_are_rounded_and_reported_values_are_exact() -> None:
    provider = closed(
        {("0010", "0010"): 1, ("0020", "0010"): 3, ("0030", "0010"): 7},
        decimals=8,
    )
    rule = "with {tC_01.00, c0010, interval: false}: {r0010} = {r0020} / {r0030}"
    result = evaluate_rule(rule, provider)
    explanation = explain(_traced(result), rule, result.failures[0].key)

    assert (
        explanation.summary
        == "1 should equal 0.428571 (3 \u00f7 7): difference 0.571429"
    )
    assert explanation.right is not None and explanation.right.value == "0.428571"
    assert explanation.filled == "1 = 3 \u00f7 7"

    reported = closed({("0010", "0010"): Decimal("0.123456789")}, decimals=9)
    rule = "with {tC_01.00, c0010, interval: false}: {r0010} = 0"
    result = evaluate_rule(rule, reported)
    explanation = explain(_traced(result), rule, result.failures[0].key)
    assert explanation.summary == "0.123456789 should equal 0: difference 0.123456789"


def test_failures_of_one_rule_share_what_the_tree_alone_decides() -> None:
    provider = closed(
        {
            ("0010", "0010"): 100,
            ("0020", "0010"): 60,
            ("0030", "0010"): -50,
            ("0010", "0020"): 1204,
            ("0020", "0020"): 1180,
            ("0030", "0020"): 31,
        }
    )
    rule = "with {tC_01.00, c*, default: 0}: {r0010} = ({r0020} + {r0030})"
    result = evaluate_rule(rule, provider)
    first, second = (
        explain(_traced(result), rule, failure.key) for failure in result.failures
    )

    assert _traced(result).shapes, "plain formulas are kept for later failures"
    assert first.formula == second.formula == "{r0010} = ({r0020} + {r0030})"
    assert (first.filled, second.filled) == (
        "100 = (60 \u2212 50)",
        "1,204 = (1,180 + 31)",
    )
    alone = evaluate_rule(rule, provider)
    assert second == explain(_traced(alone), rule, result.failures[1].key)


def test_decimals_format_with_thousands_separators() -> None:
    assert format_decimal(Decimal("-1234567.8900")) == "-1,234,567.89"
    assert format_decimal(Decimal("1E+6")) == "1,000,000"
    assert format_decimal(Decimal("0.0001250")) == "0.000125"
    assert format_decimal(Decimal("999")) == "999"


def test_unique_points_flatten_nested_points_in_order() -> None:
    a, b, c = (DataPoint("T", row, ref=row) for row in ("0010", "0020", "0030"))

    assert unique_points((a,)) == (a,)
    assert unique_points((a, b, a)) == (a, b)
    assert unique_points(((a, (b,)), c, (b, a))) == (a, b, c)
    assert unique_points(point for point in (c, c)) == (c,)


def test_where_and_widening_if_scale_with_distinct_keys() -> None:
    table = TableLayout(
        "O", rows=("0010", "0020"), columns=("0010",), open_keys=("qA", "qB")
    )
    values: dict[CellKey, Value] = {
        ("O", row, "0010", None, (("qA", f"a{i % 3}"), ("qB", f"b{i}"))): Number.of(
            i, 0
        )
        for i in range(300)
        for row in ("0010", "0020")
    }
    calls: list[str] = []

    class Counting(MemoryProvider):
        def parameter(self, name):
            calls.append(name)
            return "a1"

    provider = Counting([table], values)
    rule = "with {tO, c0010}: if sum({r0010} group by qA) > 5 then {r0020} >= 0 endif"
    result = evaluate_rule(rule, provider, trace=False)
    assert result.counts == {"passed": 300, "failed": 0, "null": 0}
    rule = "count({tO, r0010, c0010} [where qA = wanted and qA in {'a1', 'a2'}]) = 100"
    assert evaluate_rule(rule, provider).status == "passed"
    assert calls == ["wanted"] * 3


def test_explanations_round_gaps_down_and_keep_source_parentheses() -> None:
    provider = closed({("0010", "0010"): "10.00", ("0020", "0010"): "4.53"}, decimals=2)
    rule = "with {tC_01.00, c0010, interval: true}: {r0010} = {r0020}"
    result = evaluate_rule(rule, provider)
    explanation = explain(_traced(result), rule, result.failures[0].key)
    # The intervals are 5.46 apart: "at least 5.5" would overstate it.
    assert explanation.gap == "5.4"

    provider = closed({("0010", "0010"): 100, ("0020", "0010"): 60})
    rule = (
        "with {tC_01.00, c0010, default: 0}: "
        "{r0010} = ({r0020} + {r0030}) * ({r0010} - {r0030})"
    )
    result = evaluate_rule(rule, provider)
    explanation = explain(_traced(result), rule, result.failures[0].key)
    assert explanation.filled == f"100 = (60 + 0) {TIMES} (100 {MINUS} 0)"


def test_explanations_follow_keys_through_rename() -> None:
    table = TableLayout("O", rows=("0010",), columns=("0010",), open_keys=("qKEY",))
    provider = MemoryProvider(
        [table],
        {
            ("O", "0010", "0010", None, (("qKEY", key),)): Number.of(value, 0)
            for key, value in (("a", 1), ("b", 200))
        },
    )
    rule = "with {tO, c0010}: {r0010} [rename KEY to qX] > 100"
    result = evaluate_rule(rule, provider)
    assert [failure.key for failure in result.failures] == [{"qX": "a"}]
    explanation = explain(_traced(result), rule, result.failures[0].key)
    assert explanation.summary == "1 should exceed 100: difference 99"
    assert len(explanation.operands[0].points) == 1


def test_explanations_of_huge_values_with_intervals() -> None:
    for value in ("1e33", "123456789012345678901234567890123", "1e40"):
        provider = closed({("0010", "0010"): value, ("0020", "0010"): 1})
        rule = "with {tC_01.00, c0010, interval: true}: {r0020} = {r0010}"
        result = evaluate_rule(rule, provider)
        explanation = explain(_traced(result), rule, result.failures[0].key)
        assert explanation.summary.startswith("1 should equal ")
        assert explanation.right is not None
        assert explanation.right.low is not None


def test_table_layouts_reject_inconsistent_axes_and_types() -> None:
    from dpmxl import TableLayout

    with pytest.raises(ValueError, match="unknown open axis 'row'"):
        TableLayout("T", open_axes=cast(Any, ("row",)))
    with pytest.raises(ValueError, match="open rows of T cannot have codes"):
        TableLayout("T", rows=("0010",), open_axes=("rows",))
    with pytest.raises(ValueError, match="unknown data type 'text'"):
        TableLayout("T", data_types={(None, None, None): "text"})


def test_open_axes_and_data_types_do_not_change_evaluation() -> None:
    from dpmxl import MemoryProvider, Number, TableLayout, evaluate_rule

    values: dict[CellKey, Value] = {
        ("C", None, "0010", None, (("qK", "a"),)): Number.of(5, 0)
    }
    plain = TableLayout("C", columns=("0010",), open_keys=("qK",))
    described = TableLayout(
        "C",
        columns=("0010",),
        open_keys=("qK",),
        open_axes=("rows",),
        data_types={(None, "0010", None): "number"},
    )
    # Data types take no part in equality; open axes do.
    assert described != plain
    assert described == TableLayout(
        "C", columns=("0010",), open_keys=("qK",), open_axes=("rows",)
    )
    for layout in (plain, described):
        result = evaluate_rule("{tC, c0010} > 0", MemoryProvider([layout], values))
        assert result.status == "passed"
