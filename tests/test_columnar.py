"""The columnar engine must agree with the reference evaluator."""

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
