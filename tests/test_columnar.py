"""The columnar engine must agree with the reference evaluator."""

from datetime import date

import pytest

pytest.importorskip("polars")

from dpmxl import (
    Item,
    MemoryProvider,
    Number,
    TableLayout,
    Value,
    evaluate_rule,
)
from dpmxl.columnar import (
    ColumnarUnsupported,
    PointsFrameProvider,
    canonical_key,
    evaluate_rule_columnar,
)
from dpmxl.provider import CellKey


def data() -> MemoryProvider:
    tables = [
        TableLayout("T", rows=("0010", "0020", "0030"), columns=("0010", "0020")),
        TableLayout("ONE", rows=("0010",), columns=("0010",)),
        TableLayout("O", rows=("0010", "0020"), columns=("0010",), open_keys=("qKEY",)),
        # An open table filed without rows.
        TableLayout("E", rows=("0010", "0020"), columns=("0010",), open_keys=("qGCC",)),
    ]
    values: dict[CellKey, Value] = {
        ("T", "0010", "0010", None, ()): Number.of(100, 0),
        ("T", "0020", "0010", None, ()): Number.of(60, 0),
        ("T", "0030", "0010", None, ()): Number.of(41, 0),
        ("T", "0010", "0020", None, ()): Number.of(1204, 0),
        ("T", "0020", "0020", None, ()): Number.of(1180, 0),
        ("T", "0030", "0020", None, ()): Number.of(17, 0),
        ("ONE", "0010", "0010", None, ()): Number.of(5, 0),
    }
    for index, key in enumerate((Item("qK", "a"), Item("qK", "b"), Item("qK", "c"))):
        values["O", "0010", "0010", None, (("qKEY", key),)] = Number.of(10 * index, 0)
        values["O", "0020", "0010", None, (("qKEY", key),)] = Number.of(15, 0)
    return MemoryProvider(tables, values, parameters={"refPeriod": None})


EXPRESSIONS = [
    "with {tT, c*, default: 0, interval: true}: {r0010} = {r0020} + {r0030}",
    "with {tT, c*, default: 0, interval: false}: {r0010} = {r0020} + {r0030}",
    "with {tT, c0010, interval: true}: {r0010} >= {r0020} * 1.5",
    "with {tT, c0010, interval: true}: {r0010} / {r0020} > 1.6",
    "with {tO, c0010, default: 0, interval: true}: {r0020} <= {r0010}",
    "with {tO, c0010, default: 0}: {r0020} [where qKEY in {[qK:a], [qK:b]}] <= {r0010} [where qKEY in {[qK:a], [qK:b]}]",
    "sum({tO, r0010, c0010, default: 0}) = {tT, r0010, c0010}",
    "sum({tO, c0010} group by qKEY) > 20",
    "with {tT, default: 0}: {r0010} >= max_aggr({(r0020, r0030)} group by c)",
    "{tT, r0020, c0010} <= min_aggr({tT, r*, c0010})",
    "with {tT, default: 0}: if {r0010, c0010} > 0 then {r0010-0020, (c0010, c0020)} >= 0 endif",
    "count({tO, r0010, c0010}) = 3",
    "{tO, r0010, c0010} [sub qKEY = [qK:c]] = 20",
    "with {tT, c0010}: abs({r0010} - {r0020}) <= max({r0030}, 50)",
    "if {tT, r0010, c0010} > 50 then {tT, r0020, c0010} > 70 endif",
    "if {tT, r0010, c0010} > 500 then {tT, r0020, c0010} > 70 else false endif",
    "with {tT, r0010, default: 0}: if {c*} > 200 then {c*} > 1000 else {c*} < 0 endif",
    "{tT, r*, c0010} > {tONE, r*, c0010}",
    "{tT, r0010-0020, c0010} + {tT, r0020-0030, c0010} > 0",
    "not(isnull({tT, r0010, c0010})) and isnull({tT, r0010, c0020, default: null}) = false",
    "{tO, r0010, c0010} in {0, 10}",
    "true > false",
    "with {tE, default: 0, interval: true}: {r0010, c0010} = sum({r0020, c0010} group by GCC)",
    "if not isnull({tE, r0010, c0010}) then {tE, r0020, c0010} > 0 endif",
    "{tT, r0010, c0010} = time_shift({tT, r0010, c0010}, A, 1, refPeriod)",
]


@pytest.mark.parametrize("expression", EXPRESSIONS)
def test_columnar_agrees_with_reference(expression: str) -> None:
    provider = data()
    reference = evaluate_rule(expression, provider)
    try:
        columnar = evaluate_rule_columnar(
            expression, PointsFrameProvider(provider), max_failing_keys=10_000
        )
    except ColumnarUnsupported:
        pytest.skip("evaluated by the reference engine")
    assert columnar.status == reference.status, (reference.message, columnar.message)
    if reference.status in {"error", "unsupported"}:
        return
    assert columnar.passed == reference.counts["passed"]
    assert columnar.failed == reference.counts["failed"]
    expected = sorted(
        str(sorted(canonical_key(o.key).items())) for o in reference.failures
    )
    actual = sorted(str(sorted(key.items())) for key in columnar.failing_keys or [])
    assert actual == expected
    if columnar.failing_frame is not None:
        assert columnar.failing_frame.height == columnar.failed
        every = sorted(
            str(sorted(key.items()))
            for key in columnar.failing_frame.iter_rows(named=True)
        )
        assert every == expected


# One open row per group: Item, text, date, Boolean and mixed columns.
def mixed_values() -> MemoryProvider:
    table = TableLayout(
        "X",
        rows=("0010",),
        columns=("0010", "0020", "0030", "0040", "0050"),
        open_keys=("qGCC",),
    )
    rows = {
        Item("qG", "g1"): (
            Item("qT", "b"),
            "beta",
            date(2024, 12, 31),
            True,
            Number.of(5, 0),
        ),
        Item("qG", "g2"): (Item("qT", "a"), "alpha", date(2025, 3, 31), False, "x"),
    }
    values: dict[CellKey, Value] = {}
    for key, row in rows.items():
        for column, value in zip(table.columns, row, strict=True):
            values["X", "0010", column, None, (("qGCC", key),)] = value
    return MemoryProvider([table], values)


@pytest.mark.parametrize(
    ("expression", "expected"),
    [
        # Some checks test for presence with max_aggr over item columns.
        ("not(isnull(max_aggr({tX, r0010, c0010} group by qGCC)))", "passed"),
        ("max_aggr({tX, r0010, c0010}) = [qT:b]", "passed"),
        ("min_aggr({tX, r0010, c0010}) = [qT:a]", "passed"),
        ("not(isnull(min_aggr({tX, r0010, c0020})))", "passed"),
        ("not(isnull(max_aggr({tX, r0010, c0030} group by qGCC)))", "passed"),
        ("not(isnull(max_aggr({tX, r0010, c0040})))", "error"),
        # Numbers and text may not meet in one group.
        ("not(isnull(max_aggr({tX, r0010, c0050} group by qGCC)))", "passed"),
        ("not(isnull(max_aggr({tX, r0010, c0050})))", "error"),
    ],
)
def test_max_and_min_order_dates_text_and_items(expression: str, expected: str) -> None:
    provider = mixed_values()
    reference = evaluate_rule(expression, provider)
    columnar = evaluate_rule_columnar(expression, PointsFrameProvider(provider))
    assert reference.status == expected, reference.message
    assert columnar.status == expected, columnar.message
    if expected == "passed":
        assert columnar.passed == reference.counts["passed"]


@pytest.mark.parametrize(
    "expression",
    [
        "with {tT, c*, default: 0, interval: true}: {r0010} = {r0020} + {r0030}",
        "with {tT, c*}: {r0020} < {r0030}",
        "{tT, r*, c0010} < {tONE, r*, c0010} * 10",
        "{tT, r*, c0010} + {tT, r*, c0020} > 200",
        "with {tT, r0010, default: 0}: if {c*} > 200 then {c*} > 1000 else {c*} < 0 endif",
    ],
)
def test_only_keys_keeps_the_failing_records_unchanged(expression: str) -> None:
    provider = data()
    full = evaluate_rule(expression, provider)
    assert full.failures, "the case must fail to be meaningful"
    only = {
        axis: {
            code
            for o in full.failures
            if (code := canonical_key(o.key)[axis]) is not None
        }
        for axis in ("r", "c", "s")
        if all(axis in o.key for o in full.failures)
    }
    restricted = evaluate_rule(expression, provider, only_keys=only)
    assert [(o.key, o.points) for o in restricted.failures] == [
        (o.key, o.points) for o in full.failures
    ]
    assert len(restricted.outcomes) <= len(full.outcomes)
