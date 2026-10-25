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
    "with {tO, c0010} [where qKEY != [qK:a]]: {r0010} [where qKEY = [qK:a]] > 5",
    "with {tO} [where qKEY != [qK:b]]: {r0010, c0010} [sub qKEY = [qK:b]] > 5",
    "with {tO} [where qKEY != [qK:b]]: {r0010, c0010} [where qKEY != [qK:c]] > 5",
    "with {tT, c0010}: abs({r0010} - {r0020}) <= max({r0030}, 50)",
    "if {tT, r0010, c0010} > 50 then {tT, r0020, c0010} > 70 endif",
    "if {tT, r0010, c0010} > 500 then {tT, r0020, c0010} > 70 else false endif",
    "with {tT, r0010, default: 0}: if {c*} > 200 then {c*} > 1000 else {c*} < 0 endif",
    "{tT, r*, c0010} > {tONE, r*, c0010}",
    "{tT, r0010-0020, c0010} + {tT, r0020-0030, c0010} > 0",
    # A range may repeat its axis letter; it still ends at r0020.
    "sum({tT, r0010-r0020, c0010}) = 160",
    "not(isnull({tT, r0010, c0010})) and isnull({tT, r0010, c0020, default: null}) = false",
    "{tO, r0010, c0010} in {0, 10}",
    "true > false",
    "if {v_T} then {v_E} endif",
    "if {tT, r0010, c0010} > 500 then isnull({tE, r0010, c0010}) endif",
    "with {tE, default: 0, interval: true}: {r0010, c0010} = sum({r0020, c0010} group by GCC)",
    "if not isnull({tE, r0010, c0010}) then {tE, r0020, c0010} > 0 endif",
    "{tT, r0010, c0010} = time_shift({tT, r0010, c0010}, A, 1, refPeriod)",
    "{tO, r*, c0010} [rename qKEY to r] > 0",
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
    assert reference.status == expected, reference.message
    if expected == "error":
        # Type errors fail records, which the reference evaluator tracks.
        with pytest.raises(ColumnarUnsupported):
            evaluate_rule_columnar(expression, PointsFrameProvider(provider))
        return
    columnar = evaluate_rule_columnar(expression, PointsFrameProvider(provider))
    assert columnar.status == expected, columnar.message
    assert columnar.passed == reference.counts["passed"]


@pytest.mark.parametrize(
    "expression",
    [
        'not(isnull(max({tX, r0010, c0020}, "alpha")))',
        "not(isnull(min({tX, r0010, c0030}, #2025-01-01#)))",
        "not(isnull(max({tX, r0010, c0010}, [qT:a])))",
    ],
)
def test_elementwise_max_and_min_of_text_go_to_the_reference_engine(
    expression: str,
) -> None:
    provider = mixed_values()
    assert evaluate_rule(expression, provider).status == "passed"
    with pytest.raises(ColumnarUnsupported):
        evaluate_rule_columnar(expression, PointsFrameProvider(provider))


@pytest.mark.parametrize(
    ("expression", "expected"),
    [
        (
            "with {tT, c*, default: 0}: "
            "if {r0030} > 20 then {r0010} / ({r0030} - 17) > 1 endif",
            "passed",
        ),
        (
            "with {tT, c*}: filter({r0010} / ({r0030} - 17), {r0030} > 20) > 1",
            "passed",
        ),
        ('with {tT, c*}: if {r0030} > 50 then {r0010} > "a" else true endif', "passed"),
        ("with {tT, c*, default: 0}: {r0010} / ({r0030} - 17) > 1", "error"),
    ],
)
def test_record_errors_go_to_the_reference_engine(
    expression: str, expected: str
) -> None:
    # Column 0020 divides by zero; the error fails only that column's record.
    provider = data()
    with pytest.raises(ColumnarUnsupported):
        evaluate_rule_columnar(expression, PointsFrameProvider(provider))
    reference = evaluate_rule(expression, provider)
    assert reference.status == expected, reference.message


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


def test_rules_evaluated_concurrently_build_each_selection_once() -> None:
    import threading
    from concurrent.futures import ThreadPoolExecutor

    from dpmxl.columnar import FrameCache

    points = PointsFrameProvider(data())
    started = threading.Barrier(4)
    calls: list[object] = []

    class Slow:
        def select_frame(self, query):
            calls.append(query)
            return points.select_frame(query)

        def table_reported(self, table):
            return points.table_reported(table)

        def parameter(self, name):
            return points.parameter(name)

    cache = FrameCache()
    expression = (
        "with {tT, c*, default: 0, interval: true}: {r0010} = {r0020} + {r0030}"
    )

    def evaluate(_: int):
        started.wait()
        return evaluate_rule_columnar(expression, Slow(), cache=cache)

    with ThreadPoolExecutor(4) as pool:
        results = list(pool.map(evaluate, range(4)))

    assert {(result.status, result.failed) for result in results} == {("failed", 1)}
    # One provider query per distinct selection, however many rules ask.
    assert len(calls) == len(set(calls)) == 3


def test_polars_failures_go_to_the_reference_engine() -> None:
    import polars as pl

    class Panicking(PointsFrameProvider):
        def select_frame(self, query):
            raise pl.exceptions.PanicException("unwrap on an Err value")

    with pytest.raises(ColumnarUnsupported):
        evaluate_rule_columnar("{tT, r0010, c0010} > 0", Panicking(data()))
    with pytest.raises(ColumnarUnsupported):
        evaluate_rule_columnar(
            "{tT, r0010, c0010} * 1e24 > 0", PointsFrameProvider(data())
        )


def ambiguous_values() -> MemoryProvider:
    row, keys = ("0010",), ("qK",)
    tables = [
        TableLayout("X", rows=row, columns=("0010", "0020"), open_keys=keys),
        TableLayout("N", rows=row, columns=("0010",), open_keys=keys),
        TableLayout("Y", rows=row, columns=("0010",)),
    ]
    values: dict[CellKey, Value] = {
        ("X", "0010", "0010", None, (("qK", "a"),)): "12:30",
        ("X", "0010", "0010", None, (("qK", "b"),)): "x:abc",
        ("X", "0010", "0020", None, (("qK", "a"),)): Item("T", "b"),
        ("X", "0010", "0020", None, (("qK", "b"),)): Item("T", "c"),
        ("N", "0010", "0010", None, (("qK", Number.of(10, 0)),)): Number.of(1, 0),
        ("N", "0010", "0010", None, (("qK", Number.of(9, 0)),)): Number.of(2, 0),
        ("Y", "0010", "0010", None, ()): Number.of("0.0000000000004", 13),
    }
    return MemoryProvider(tables, values)


@pytest.mark.parametrize(
    ("expression", "expected"),
    [
        # Text with a colon is not an item; items are not ordered.
        ('{tX, r0010, c0010} = "30"', "failed"),
        ('{tX, r0010, c0010} in {"30"}', "failed"),
        ("{tX, r0010, c0020} < [T:z]", "error"),
        ("{tX, r0010, c0020} = [b]", "failed"),
        # Numeric keys compare as numbers.
        ("{tN, r0010, c0010} [where qK = 10.0] = 1", "passed"),
        ("{tN, r0010, c0010} [get qK] > 5", "passed"),
        ('{tN, r0010, c0010} [sub qK = "10"] = 1', "error"),
        ("{tX, r0010, c0010} [where qK = 1] > 0", "error"),
        # Values Decimal(38, 12) does not hold exactly.
        ("{tY, r0010, c0010} > 0", "passed"),
        ("{tY, r0010, c0010, interval: false} < 1e30", "passed"),
    ],
)
def test_text_numeric_keys_and_wide_numbers_go_to_the_reference_engine(
    expression: str, expected: str
) -> None:
    provider = ambiguous_values()
    assert evaluate_rule(expression, provider).status == expected
    with pytest.raises(ColumnarUnsupported):
        evaluate_rule_columnar(expression, PointsFrameProvider(provider))


@pytest.mark.parametrize(
    ("expression", "expected"),
    [
        ('{tX, r0010, c0010} = "x:abc"', "failed"),
        ("{tX, r0010, c0020} = [T:b]", "failed"),
        ('{tX, r0010, c0010} != "zz"', "passed"),
    ],
)
def test_unambiguous_text_and_items_stay_columnar(
    expression: str, expected: str
) -> None:
    provider = ambiguous_values()
    assert evaluate_rule(expression, provider).status == expected
    columnar = evaluate_rule_columnar(expression, PointsFrameProvider(provider))
    assert columnar.status == expected


@pytest.mark.parametrize(
    "expression",
    [
        '({tO, r0010, c0010} > "x") [where qKEY = [qK:zz]]',
        "with {tO, c0010}: ({r0010} and true) [where qKEY = [qK:zz]]",
        "with {tO, c0010}: (not {r0010}) [where qKEY = [qK:zz]]",
        "with {tO, c0010}: abs({r0010} > 1) [where qKEY = [qK:zz]]",
        "with {tO, c0010}: (if {r0010} then true endif) [where qKEY = [qK:zz]]",
    ],
)
def test_record_type_errors_dropped_by_where_go_to_the_reference(
    expression: str,
) -> None:
    provider = data()
    assert evaluate_rule(expression, provider).status == "not_applicable"
    with pytest.raises(ColumnarUnsupported):
        evaluate_rule_columnar(expression, PointsFrameProvider(provider))


@pytest.mark.parametrize(
    ("expression", "expected"),
    [
        ("{tB, r0010, c0010} < {tB, r0020, c0010}", "error"),
        ("{tB, r0010, c0010} < [b]", "error"),
        ("{tB, r0030, c0010} >= [qT:a]", "error"),
        ("{tB, r0010, c0010} = [b]", "failed"),
    ],
)
def test_items_without_a_category_go_to_the_reference(
    expression: str, expected: str
) -> None:
    table = TableLayout("B", rows=("0010", "0020", "0030"), columns=("0010",))
    provider = MemoryProvider(
        [table],
        {
            ("B", "0010", "0010", None, ()): Item(None, "a"),
            ("B", "0020", "0010", None, ()): Item(None, "b"),
            ("B", "0030", "0010", None, ()): "a",
        },
    )
    assert evaluate_rule(expression, provider).status == expected
    with pytest.raises(ColumnarUnsupported):
        evaluate_rule_columnar(expression, PointsFrameProvider(provider))


def test_frame_from_points_checks_numbers_in_bulk() -> None:
    from decimal import Decimal

    from dpmxl import DataPoint
    from dpmxl.columnar import frame_from_points

    points = [
        DataPoint("T", "0010", value=Number(Decimal("1.0000000000000"))),
        DataPoint("T", "0020", value=Number.of("2.5", 1)),
        DataPoint("T", "0030", value="text"),
        DataPoint("T", "0040"),
    ]
    frame = frame_from_points(points)
    assert frame.get_column("num").to_list() == [1, Decimal("2.5"), None, None]
    assert frame.get_column("thr").to_list()[1] == Decimal("0.05")
    assert frame.columns[-4:] == ["num", "thr", "txt", "flag"]
    for wide in ("1e30", "0.0000000000004", "NaN"):
        with pytest.raises(ColumnarUnsupported):
            frame_from_points([DataPoint("T", "0010", value=Number(Decimal(wide)))])


NEW_CONSTRUCTS = [
    'with {tT, c0010}: "a" & "b" = "ab"',
    'substr("abc", 2) = "bc"',
    "log({tONE, r0010, c0010}, 5) = 1",
    "year(#2026-12-31#) = 2026",
    "date(2026, 12, 31) = #2026-12-31T00:00:00#",
    "{tONE, r0010, c0010} in union({5}, {6})",
    "with {tT, c0010}: {r0010} in set_of({tT, r*, c0010})",
    "5 in {tONE, r0010, c0010}",
    "{p_X, number, default: 5} = {tONE, r0010, c0010}",
    "x := {tONE, r0010, c0010}; x = 5",
    "rank({tT, c0010, r*} over (order by r)) > 0",
    "sum({tT, c0010, r*} over (partition by r)) > 0",
]


@pytest.mark.parametrize("expression", NEW_CONSTRUCTS)
def test_newer_constructs_go_to_the_reference_engine(expression: str) -> None:
    provider = data()
    with pytest.raises(ColumnarUnsupported):
        evaluate_rule_columnar(expression, PointsFrameProvider(provider))
    assert evaluate_rule(expression, provider).status == "passed"


def test_set_defaults_go_to_the_reference_engine() -> None:
    expression = "{tONE, r0010, c0010, default: {1}} > 1"
    with pytest.raises(ColumnarUnsupported):
        evaluate_rule_columnar(expression, PointsFrameProvider(data()))
    assert evaluate_rule(expression, data()).status == "error"


def parts(a_keys: tuple[str, ...], b_keys: tuple[str, ...]) -> MemoryProvider:
    # Two parts of one open-keyed template.
    tables = [
        TableLayout("A", columns=("0010",), open_keys=("qKEY",)),
        TableLayout("B", columns=("0010",), open_keys=("qKEY",)),
    ]
    values: dict[CellKey, Value] = {}
    for table, keys in (("A", a_keys), ("B", b_keys)):
        for index, key in enumerate(keys):
            values[table, None, "0010", None, (("qKEY", key),)] = Number.of(index, 0)
    return MemoryProvider(tables, values)


DEFAULTED = [
    "with {default: null}: if not isnull({tB, c0010}) then "
    "not isnull({tA, c0010}) and not isnull({tB, c0010}) endif",
    "with {default: null}: if isnull({tA, c0010}) then false "
    "else isnull({tB, c0010}) endif",
    "with {default: 0}: {tA, c0010} = {tB, c0010}",
    "{tA, c0010} >= {tB, c0010, default: 0}",
    "with {default: 0}: max({tA, c0010}, {tB, c0010}) >= 0",
    "with {default: 0}: if {tA, c0010} > 0 then {tA, c0010} <= 10 "
    "else {tB, c0010} = 0 endif",
    "with {default: 0}: (if {tA, c0010} > 0 then {tA, c0010} else 0 endif) "
    "= {tB, c0010}",
    "with {default: 0}: (if false then {tA, c0010} > 0 endif) and {tB, c0010} > 0",
    "with {default: 0}: nvl({tA, c0010}, {tB, c0010}) >= 0",
    "with {default: 0}: {tA, c0010} [rename qKEY to qK] "
    "<= {tB, c0010} [rename qKEY to qK]",
    "with {default: 0}: sum(filter({tA, c0010}, {tB, c0010} >= 0)) >= 0",
]


@pytest.mark.parametrize("expression", DEFAULTED)
def test_defaults_for_missing_records_go_to_the_reference_engine(
    expression: str,
) -> None:
    # The reference evaluator fills in the default where a part lacks a key.
    provider = parts(("x", "y"), ("y", "z"))
    with pytest.raises(ColumnarUnsupported):
        evaluate_rule_columnar(expression, PointsFrameProvider(provider))
    assert evaluate_rule(expression, provider).status in {"passed", "failed"}


FILTERED = [
    '{tA, c0010, default: 10} [where qKEY = "y"] <= {tB, c0010}',
    '{tB, c0010} >= {tA, c0010, default: 0} [sub qKEY = "q"]',
    "{tB, c0010} >= filter({tA, c0010, default: 10}, {tA, c0010, default: 10} > 0)",
    'with {c0010, default: 10} [where qKEY != "x"]: {tA} <= {tB}',
    'if {tA, c0010, default: 0} [sub qKEY = "q"] > 0 then true else false endif',
]


@pytest.mark.parametrize("expression", FILTERED)
def test_defaults_kept_by_clauses_go_to_the_reference_engine(expression: str) -> None:
    provider = parts(("x", "y"), ("y", "z"))
    with pytest.raises(ColumnarUnsupported):
        evaluate_rule_columnar(expression, PointsFrameProvider(provider))
    assert evaluate_rule(expression, provider).status in {"passed", "failed"}


@pytest.mark.parametrize("expression", [*DEFAULTED, "{tA, c0010} = {tB, c0010}"])
def test_defaults_with_partners_stay_columnar(expression: str) -> None:
    provider = parts(("y", "x"), ("x", "y"))
    reference = evaluate_rule(expression, provider)
    columnar = evaluate_rule_columnar(expression, PointsFrameProvider(provider))
    assert (columnar.status, columnar.passed, columnar.failed) == (
        reference.status,
        reference.counts["passed"],
        reference.counts["failed"],
    )


@pytest.mark.parametrize("expression", ["{g_G, r0010, c0010} > 0", "{o_X} > 0"])
def test_groups_and_operations_go_to_the_reference_engine(expression: str) -> None:
    provider = MemoryProvider(
        [TableLayout("T", rows=("0010",), columns=("0010",))],
        {("T", "0010", "0010", None, ()): Number.of(1, 0)},
        table_groups={"G": ("T",)},
        operations={"X": "{tT, r0010, c0010}"},
    )
    with pytest.raises(ColumnarUnsupported):
        evaluate_rule_columnar(expression, PointsFrameProvider(provider))
    assert evaluate_rule(expression, provider).status == "passed"


def test_time_functions_go_to_the_reference_engine() -> None:
    provider = data()
    earlier = MemoryProvider(
        list(provider.tables.values()),
        dict(provider.values),
        parameters={"refPeriod": date(2025, 12, 31)},
    )
    shifting = MemoryProvider(
        list(provider.tables.values()),
        dict(provider.values),
        parameters={"refPeriod": date(2026, 12, 31)},
        earlier_reports={("A", 1): earlier},
    )
    for expression in (
        "{tT, r0010, c0010} = time_shift({tT, r0010, c0010}, A, 1, refPeriod)",
        "annualise({tT, r0010, c0010}, 12, refPeriod) = 100",
    ):
        with pytest.raises(ColumnarUnsupported):
            evaluate_rule_columnar(expression, PointsFrameProvider(shifting))
        assert evaluate_rule(expression, shifting).status == "passed"


class _ThreeMethods:
    """A provider without any optional method."""

    def __init__(self, inner: MemoryProvider) -> None:
        self.inner = inner

    def select(self, query):
        return self.inner.select(query)

    def table_reported(self, table: str) -> bool | None:
        return self.inner.table_reported(table)

    def parameter(self, name: str) -> Value:
        return self.inner.parameter(name)


@pytest.mark.parametrize(
    ("expression", "status"),
    [
        (
            "time_shift({tD, c0010}, Q, 1, qDAT) [sub qDAT = #2026-06-30#] = 5",
            "passed",
        ),
        (
            "time_shift({tD, c0010}, Q, 1, refPeriod) [sub qDAT = #2026-03-31#] = 5",
            "unsupported",
        ),
    ],
)
def test_time_shift_always_goes_to_the_reference_engine(
    expression: str, status: str
) -> None:
    provider = _ThreeMethods(
        MemoryProvider(
            [TableLayout("D", columns=("0010",), open_keys=("qDAT",))],
            {
                ("D", None, "0010", None, (("qDAT", date(2026, 3, 31)),)): Number.of(
                    5, 0
                )
            },
        )
    )
    with pytest.raises(ColumnarUnsupported):
        evaluate_rule_columnar(expression, PointsFrameProvider(provider))
    assert evaluate_rule(expression, provider).status == status
