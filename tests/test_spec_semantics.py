"""Behaviour required by the EBA DPM-XL operators specification v0.9."""

from datetime import date
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


@pytest.mark.parametrize(
    ("rule", "expected"),
    [
        ("count({1, 2, 3, 3, 2}) = 3", "passed"),
        ("count({}) = 0", "passed"),
        ("count(union({1, 2}, {2, 3})) = 3", "passed"),
        ("count(set_of({tT, r*, c0010})) = 2", "passed"),
        ("count({1, 2} group by r) = 2", "error"),
    ],
)
def test_count_of_a_set_is_its_number_of_members(rule: str, expected: str) -> None:
    # 7.3.4: count of a scalar_set returns its cardinality.
    data = provider({("0010", "0010"): 4, ("0020", "0010"): 4, ("0030", "0010"): 5})
    assert status(rule, data) == expected


@pytest.mark.parametrize(
    ("rule", "expected"),
    [
        ("{1, 2, 3} = {3, 2, 1}", "passed"),
        ("{1, 2} = {1, 2, 3}", "failed"),
        ("symdiff({1, 2}, {1, 2}) = {}", "passed"),
        ("{1, 2} != {2, 3}", "passed"),
        ("set_of({tT, r*, c0010}) = {4, 5}", "passed"),
        ("{1} = 1", "error"),
        ("{1} < {2}", "error"),
    ],
)
def test_sets_compare_as_sets(rule: str, expected: str) -> None:
    # 13.7: = and != on two sets test whether they hold the same members.
    data = provider({("0010", "0010"): 4, ("0020", "0010"): 4, ("0030", "0010"): 5})
    assert status(rule, data) == expected


def test_division_by_zero_is_a_runtime_error() -> None:
    # 4.3.4.6: a zero denominator generates a run-time error.
    data = provider({("0010", "0010"): 4, ("0020", "0010"): 0})
    rule = "with {tT, c0010}: {r0010} / {r0020} = 1"
    assert status(rule, data) == "error"


@pytest.mark.parametrize(
    "rule",
    ["ln(0) = 0", "ln(-1) = 0", "sqrt(-1) = 0", "log(8, 1) = 3", "log(0, 2) = 0"],
)
def test_math_outside_its_domain_is_a_runtime_error(rule: str) -> None:
    # 4.2.5.6, 4.2.6.6, 4.2.7.6: generates a run-time error.
    assert status(rule) == "error"


def test_math_domain_errors_fail_only_their_records() -> None:
    data = provider({("0010", "0010"): 4, ("0020", "0010"): -4})
    rule = "with {tT, c0010}: if {r*} > 0 then sqrt({r*}) = 2 else true endif"
    assert status(rule, data) == "passed"
    assert status("sqrt({tT, r*, c0010}) = 2", data) == "error"


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


def test_if_without_else_knows_more_boolean_then_branches() -> None:
    # 8.1.6: without else, a Boolean thenExpression gives true where the
    # condition is not true.
    tables = [
        TableLayout("A", rows=("0010",), columns=("0010",)),
        TableLayout("B", rows=("0010",), columns=("0010",)),
    ]
    flags = MemoryProvider(tables, {("B", "0010", "0010", None, ()): False})
    for rule in [
        "if {v_A} then {v_B} endif",
        "if {v_A} then nvl({tB, r0010, c0010}, false) endif",
        "if {v_A} then {tB, r0010, c0010} endif",
    ]:
        result = evaluate_rule(rule, flags)
        assert result.counts == {"passed": 1, "failed": 0, "null": 0}, rule


def test_non_boolean_if_conditions_fail_only_their_records() -> None:
    data = provider({}, open_rows=[(Item("qK", "a"), 1)])
    rule = "(if {tO, r0010, c0010} then true endif) [where qKEY = [qK:zz]]"
    assert status(rule, data) == "not_applicable"
    assert status("if {tO, r0010, c0010} then true endif", data) == "error"


def parts(a_rows=(), b_rows=()) -> MemoryProvider:
    # Two parts of one open-keyed template, each filed for its own keys.
    tables = [
        TableLayout("A", columns=("0010", "0020"), open_keys=("qKEY",)),
        TableLayout("B", columns=("0010",), open_keys=("qKEY",)),
    ]
    data: dict[CellKey, Value] = {}
    for table, rows in (("A", a_rows), ("B", b_rows)):
        for key, column, value in rows:
            data[table, None, column, None, (("qKEY", key),)] = Number.of(value, 0)
    return MemoryProvider(tables, data)


def keyed(result) -> list[tuple[str, bool | None]]:
    return sorted((str(o.key["qKEY"]), o.passed) for o in result.outcomes)


def test_default_fills_records_an_operand_lacks() -> None:
    # A selection with a default stands for its default where another operand
    # has a record it lacks, as the fallback value of a fact variable does.
    data = parts(a_rows=[("y", "0010", 1)], b_rows=[("x", "0010", 2)])
    rule = (
        "with {default: null}: if not isnull({tB, c0010}) then "
        "not isnull({tA, c0010}) and not isnull({tB, c0010}) endif"
    )
    result = evaluate_rule(rule, data)
    assert result.status == "failed"
    # y, only in A, does not meet the condition (its default) and passes.
    assert keyed(result) == [("x", False), ("y", True)]
    both = parts(a_rows=[("x", "0010", 1)], b_rows=[("x", "0010", 2)])
    assert evaluate_rule(rule, both).status == "passed"
    # A branch lacking the condition's key takes its default too.
    rule = "with {default: null}: if not isnull({tB, c0010}) then not isnull({tA, c0010}) endif"
    assert keyed(evaluate_rule(rule, data)) == [("x", False), ("y", True)]


def test_operands_with_defaults_join_on_every_key() -> None:
    data = parts(
        a_rows=[("x", "0010", 1), ("y", "0010", 5)],
        b_rows=[("x", "0010", 1), ("z", "0010", 3)],
    )
    result = evaluate_rule("with {default: 0}: {tA, c0010} = {tB, c0010}", data)
    assert keyed(result) == [("x", True), ("y", False), ("z", False)]
    # Only the operand with a default is filled in.
    result = evaluate_rule("{tA, c0010} >= {tB, c0010, default: 0}", data)
    assert keyed(result) == [("x", True), ("y", True)]
    result = evaluate_rule("{tA, c0010, default: 0} < {tB, c0010}", data)
    assert keyed(result) == [("x", False), ("z", True)]


def test_operands_without_defaults_join_on_shared_keys() -> None:
    data = parts(a_rows=[("y", "0010", 1)], b_rows=[("x", "0010", 2)])
    assert status("{tA, c0010} = {tB, c0010}", data) == "not_applicable"
    rule = (
        "if not isnull({tB, c0010}) then "
        "not isnull({tA, c0010}) and not isnull({tB, c0010}) endif"
    )
    assert status(rule, data) == "not_applicable"


def test_if_with_defaults_covers_the_keys_of_its_branches() -> None:
    # A key only a branch has is evaluated with the condition's default, as
    # when every variable of the assertion has a fallback value.
    data = parts(a_rows=[("y", "0010", 1)], b_rows=[("x", "0010", 5)])
    rule = (
        "with {default: 0}: if {tA, c0010} > 0 then {tA, c0010} <= 10 "
        "else {tB, c0010} = 0 endif"
    )
    assert keyed(evaluate_rule(rule, data)) == [("x", False), ("y", True)]
    # Without a default on the condition, its records decide the keys.
    rule = "if {tA, c0010} > 0 then {tA, c0010} <= 10 else {tB, c0010} = 0 endif"
    assert keyed(evaluate_rule(rule, data)) == [("y", True)]
    # A branch without a default must have the key.
    rule = (
        "if {tA, c0010, default: 0} > 0 then {tA, c0010} <= 10 "
        "else {tB, c0010, default: 0} = 0 endif"
    )
    assert keyed(evaluate_rule(rule, data)) == [("y", True)]


def test_if_results_keep_a_default() -> None:
    data = parts(a_rows=[("y", "0010", 1)], b_rows=[("x", "0010", 5)])
    nested = (
        "with {default: 0}: "
        "(if {tA, c0010} > 0 then {tA, c0010} else 0 endif) = {tB, c0010}"
    )
    assert keyed(evaluate_rule(nested, data)) == [("x", False), ("y", False)]
    guarded = (
        "with {default: 0}: (if false then {tA, c0010} > 0 endif) and {tB, c0010} > 0"
    )
    assert keyed(evaluate_rule(guarded, data)) == [("x", True), ("y", False)]


def test_rename_and_time_shift_keep_a_default() -> None:
    # Neither selects records or depends on their values: the default holds.
    data = parts(a_rows=[("y", "0010", 1)], b_rows=[("x", "0010", 5)])
    rule = (
        "with {default: 0}: {tA, c0010} [rename qKEY to qK] "
        "<= {tB, c0010} [rename qKEY to qK]"
    )
    assert sorted(
        (str(o.key["qK"]), o.passed) for o in evaluate_rule(rule, data).outcomes
    ) == [
        ("x", True),
        ("y", False),
    ]
    dated = MemoryProvider(
        [
            TableLayout("D", columns=("0010",), open_keys=("qDAT",)),
            TableLayout("E", columns=("0010",), open_keys=("qDAT",)),
        ],
        {
            ("D", None, "0010", None, (("qDAT", date(2026, 3, 31)),)): Number.of(5, 0),
            ("E", None, "0010", None, (("qDAT", date(2026, 3, 31)),)): Number.of(7, 0),
        },
    )
    rule = "with {default: 0}: time_shift({tD, c0010}, Q, 1, qDAT) <= {tE, c0010}"
    result = evaluate_rule(rule, dated)
    assert sorted((str(o.key["qDAT"]), o.passed) for o in result.outcomes) == [
        ("2026-03-31", True),
        ("2026-06-30", False),
    ]


def test_clauses_that_select_records_keep_a_default() -> None:
    # Filtering one operand restricts its records, not the keys the other
    # operands bring: there it falls back to its default.
    data = parts(
        a_rows=[("y", "0010", 1), ("x", "0010", 2)],
        b_rows=[("x", "0010", 5), ("z", "0010", 3)],
    )
    where = '{tA, c0010, default: 10} [where qKEY = "y"] <= {tB, c0010}'
    assert keyed(evaluate_rule(where, data)) == [("x", False), ("z", False)]
    sub = '{tB, c0010} >= {tA, c0010, default: 0} [sub qKEY = "q"]'
    assert keyed(evaluate_rule(sub, data)) == [("x", True), ("z", True)]
    kept = "filter({tA, c0010, default: 10}, {tA, c0010, default: 10} > 1)"
    assert keyed(evaluate_rule(f"{{tB, c0010}} >= {kept}", data)) == [
        ("x", True),
        ("z", False),
    ]
    context = '{c0010, default: 10} [where qKEY != "y"]'
    rule = f"with {context}: {{tA}} <= {{tB}}"
    assert keyed(evaluate_rule(rule, data)) == [("x", True), ("z", False)]
    # A record set made only of a default has no record of its own.
    assert status('{tA, c0010, default: 0} [sub qKEY = "q"] = 0', data) == (
        "not_applicable"
    )
    # A reported key-less operand brings a record, as a fact would.
    mixed = provider({("0010", "0010"): 4})
    rule = '{tT, r0010, c0010} > {tO, r0010, c0010, default: 5} [sub qKEY = "q"]'
    assert evaluate_rule(rule, mixed).counts == {"passed": 0, "failed": 1, "null": 0}


def test_get_has_no_default() -> None:
    # A fallback has no key components to take a value from.
    data = parts(a_rows=[("y", "0010", 1)], b_rows=[("x", "0010", 5)])
    rule = "{tA, c0010, default: 0} [get qKEY] = {tB, c0010, default: 0} [get qKEY]"
    assert keyed(evaluate_rule(rule, data)) == []


def test_rename_to_an_existing_key_is_an_error() -> None:
    table = TableLayout("O2", rows=("0010",), columns=("0010",), open_keys=("qA", "qB"))
    data = MemoryProvider(
        [table],
        {("O2", "0010", "0010", None, (("qA", "a"), ("qB", "b"))): Number.of(1, 0)},
    )
    for rule in [
        "{tO2} [rename qA to qB] = 1",
        "{tO2} [rename qA to qC, qB to qC] = 1",
    ]:
        result = evaluate_rule(rule, data)
        assert result.status == "error", rule
        assert "already" in (result.message or ""), rule


def test_context_where_applies_to_selections_with_its_keys() -> None:
    # A with-level where filters the selections that have the keys it
    # names; the others, key-less ones included, are not concerned.
    tables = [
        TableLayout("A", columns=("0010",), open_keys=("qKEY",)),
        TableLayout("C", rows=("0010", "0020"), columns=("0010",)),
    ]
    data = MemoryProvider(
        tables,
        {
            ("A", None, "0010", None, (("qKEY", "x"),)): Number.of(2, 0),
            ("A", None, "0010", None, (("qKEY", "y"),)): Number.of(50, 0),
            ("C", "0010", "0010", None, ()): Number.of(3, 0),
            ("C", "0020", "0010", None, ()): Number.of(4, 0),
        },
    )
    context = 'with {c0010} [where qKEY = "x"]: '
    for body, expected in [
        ("{tA} <= {tC, r0010}", "passed"),
        ("sum({tA}) <= sum({tC, r*})", "passed"),
        ("{tA} > {tC, r0010}", "failed"),
    ]:
        result = evaluate_rule(context + body, data)
        assert result.status == expected, (body, result.message)
    # A name that is neither a key nor a parameter is still an error where
    # the selection has none of the condition's keys but names it itself.
    result = evaluate_rule('{tC, r*, c0010} [where qKEY = "x"] > 0', data)
    assert result.status == "error"
