"""Behaviour required by the EBA DPM-XL operators specification v0.9."""

from decimal import Decimal

import pytest

from dpmxl import Item, MemoryProvider, Number, TableLayout, Value, evaluate_rule
from dpmxl.provider import CellKey

ROWS = ("0010", "0020", "0030")


def provider(values: dict[tuple[str, str], int | None], *, open_rows=()):
    tables = [
        TableLayout("T", rows=ROWS, columns=("0010", "0020")),
        TableLayout("ONE", rows=("0010",), columns=("0010",)),
        TableLayout("O", rows=("0010",), columns=("0010",), open_keys=("qKEY",)),
    ]
    data: dict[CellKey, Value] = {
        ("T", row, column, None, ()): Number.of(value, 0)
        for (row, column), value in values.items()
        if value is not None
    }
    data["ONE", "0010", "0010", None, ()] = Number.of(5, 0)
    for key, value in open_rows:
        data["O", "0010", "0010", None, (("qKEY", key),)] = Number.of(value, 0)
    return MemoryProvider(tables, data)


def status(expression: str, data=None, **kwargs) -> str:
    return evaluate_rule(expression, data or provider({}), **kwargs).status


def test_if_null_condition_takes_else_branch() -> None:
    # 8.1.6: "If the condition evaluates to null, the elseExpression is returned."
    rule = "if {tT, r0010, c0010} > 0 then true else false endif"
    assert status(rule) == "failed"


def test_if_without_else_and_boolean_then_yields_true() -> None:
    # 8.1.6: without else, a Boolean thenExpression gives true.
    assert status("if {tT, r0010, c0010, default: 0} > 0 then false endif") == "passed"
    assert status("if {tT, r0010, c0010} > 0 then false endif") == "passed"


def test_if_result_follows_the_condition_records() -> None:
    data = provider({("0010", "0010"): 1, ("0010", "0020"): -1})
    rule = (
        "with {tT, r0010, default: 0}: if {c*} > 0 then {c*} = 1 else {c*} = -1 endif"
    )
    result = evaluate_rule(rule, data)
    assert result.status == "passed"
    assert len(result.outcomes) == 2


def test_if_branch_keys_widen_the_condition_records() -> None:
    # As in an EBA RESOL2 rule on Z_09.01: a per-row condition on c0040 constrains
    # several columns of its row, one record per column.
    data = provider({("0010", "0010"): 1, ("0020", "0010"): 0, ("0010", "0020"): 5})
    rule = (
        "with {tT, default: 0}: if {r0010, c0010} > 0 then "
        "{r0010-0020, (c0010, c0020)} >= 0 endif"
    )
    result = evaluate_rule(rule, data)
    assert result.status == "passed"
    assert sorted(str(outcome.key["r"]) for outcome in result.outcomes) == [
        "0010",
        "0010",
        "0020",
        "0020",
    ]
    failing = evaluate_rule(rule.replace(">= 0 endif", "> 0 endif"), data)
    assert [(o.key["r"], o.key["c"]) for o in failing.failures] == [
        ("0020", "0010"),
        ("0020", "0020"),
    ]


def test_max_aggr_and_min_aggr_are_the_aggregate_forms() -> None:
    # EBA writes the aggregate max and min as max_aggr and min_aggr.
    data = provider({("0010", "0010"): 9, ("0020", "0010"): 4, ("0030", "0010"): 7})
    assert status("{tT, r0010, c0010} >= max_aggr({tT, r*, c0010})", data) == "passed"
    assert status("{tT, r0020, c0010} <= min_aggr({tT, r*, c0010})", data) == "passed"
    grouped = "with {tT, default: 0}: {r0010} >= max_aggr({(r0020, r0030)} group by c)"
    assert status(grouped, data) == "passed"
    assert status("max_aggr({tT, r0010, c0010}, 1) > 0", data) == "error"


def test_count_of_no_records_is_zero() -> None:
    # 7.3.4: count returns the number of records.
    data = provider({})
    assert status("count({tO, r0010, c0010}) = 0", data) == "passed"


def test_division_by_zero_is_a_runtime_error() -> None:
    # 4.3.4.6: a zero denominator generates a run-time error.
    data = provider({("0010", "0010"): 4, ("0020", "0010"): 0})
    rule = "with {tT, c0010}: {r0010} / {r0020} = 1"
    assert status(rule, data) == "error"


def test_errors_fail_only_the_records_that_reach_the_result() -> None:
    # Column 0010 divides by zero, column 0020 does not.
    data = provider(
        {("0010", "0010"): 4, ("0020", "0010"): 0, ("0010", "0020"): 4}
        | {("0020", "0020"): 2}
    )
    guarded = "with {tT, c*}: if {r0020} != 0 then {r0010} / {r0020} > 1 endif"
    result = evaluate_rule(guarded, data)
    assert result.status == "passed", result.message
    assert result.counts == {"passed": 2, "failed": 0, "null": 0}
    taken = "with {tT, c*}: if {r0010} > 0 then {r0010} / {r0020} > 1 endif"
    assert evaluate_rule(taken, data).message == "division by zero"
    typed = 'with {tT, c*}: if {r0020} != 0 then {r0010} > "a" else true endif'
    assert status(typed, data) == "error"
    text = 'with {tT, c*}: if isnull({r0030}) then true else {r0010} > "a" endif'
    assert status(text, data) == "passed"


def test_get_omits_records_with_null_facts() -> None:
    # 11.3.6: "Records with null Fact value will be omitted."
    data = provider({}, open_rows=[(Item("qK", "a"), 1)])
    rule = "count({tO, r0010, c0010, default: null} [get qKEY]) = 1"
    assert status(rule, data) == "passed"


def test_axis_keys_only_for_several_present_coordinates() -> None:
    # 3.1.6: r is a key only when more than one row is present, so r* over a
    # one-row table is a scalar and broadcasts.
    data = provider({("0010", "0010"): 9, ("0020", "0010"): 9, ("0030", "0010"): 9})
    rule = "{tT, r*, c0010} > {tONE, r*, c0010}"
    result = evaluate_rule(rule, data)
    assert result.status == "passed"
    assert len(result.outcomes) == 3


def test_standard_keys_must_contain_the_same_values() -> None:
    # 2.2.3.1: summing {tT1, r010-020} and {tT1, r030-040} is not possible.
    data = provider({("0010", "0010"): 1, ("0020", "0010"): 1, ("0030", "0010"): 1})
    assert (
        status("{tT, r0010-0020, c0010} + {tT, r0020-0030, c0010} > 0", data) == "error"
    )


def test_partially_overlapping_keys_are_rejected() -> None:
    data = provider({("0010", "0010"): 1}, open_rows=[(Item("qK", "a"), 1)])
    rule = "{tT, c0010, r*} + {tO, r0010, c0010} > 0"
    assert status(rule, data) == "error"


def test_booleans_are_ordered_false_before_true() -> None:
    assert status("true > false") == "passed"


@pytest.mark.parametrize(
    ("left", "right", "expected"),
    [
        (Decimal("100"), Decimal("100.5"), "passed"),
        (Decimal("100"), Decimal("101.5"), "failed"),
    ],
)
def test_interval_equality_overlaps(left, right, expected) -> None:
    data = MemoryProvider(
        [TableLayout("T", rows=("0010", "0020"), columns=("0010",))],
        {
            ("T", "0010", "0010", None, ()): Number.of(left, 0),
            ("T", "0020", "0010", None, ()): Number.of(right, 0),
        },
    )
    assert (
        status("with {tT, c0010, interval: true}: {r0010} = {r0020}", data) == expected
    )


def test_open_table_without_rows_keeps_its_keys() -> None:
    # 3.1.6: a selection's structure comes from the table, not from its data;
    # an open table with no reported rows is an empty record set with keys.
    data = provider({})
    assert status("sum({tO, r0010, c0010} group by KEY) = 0", data) == "not_applicable"
    rule = "if not isnull({tO, r0010, c0010}) then {tO, r0010, c0010} > 0 endif"
    assert status(rule, data) == "not_applicable"


def test_clauses_on_a_selection_override_the_context_where_on_their_key() -> None:
    # 3.2: a where on a selection replaces the with-level where on its key;
    # where on other keys still applies.
    table = TableLayout("O2", rows=("0010",), columns=("0010",), open_keys=("qA", "qB"))
    data = MemoryProvider(
        [table],
        {
            ("O2", "0010", "0010", None, (("qA", a), ("qB", b))): Number.of(value, 0)
            for a, b, value in [("a1", "b1", 1), ("a2", "b1", -1), ("a1", "b2", -5)]
        },
    )
    context = 'with {tO2, r0010, c0010} [where qA = "a1" and B = "b1"]: '
    for body, expected in [
        ("{tO2} > 0", "passed"),
        ('{tO2} [where qB = "b2"] > 0', "failed"),
        ('{tO2} [where A = "a2"] > 0', "failed"),
        ('{tO2} [sub qA = "a2"] > -10', "passed"),
        ('{tO2} [sub qB = "b2"] > 0', "failed"),
        ('{tO2} [where A != "a2"] [where B != "b1"] > -10', "passed"),
    ]:
        result = evaluate_rule(context + body, data)
        assert result.status == expected, body
        assert len(result.outcomes) == 1, body
