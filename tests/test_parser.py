import gc
from decimal import Decimal

import pytest

from dpmxl import DpmXlSyntaxError, parse, references, reported_templates, tables
from dpmxl.ast import (
    AxisSelector,
    Binary,
    Call,
    If,
    In,
    Item,
    Literal_,
    Selection,
    SetLiteral,
    Sub,
    TableReported,
    Unary,
    Where,
    With,
)


def test_with_context_selection_and_ranges() -> None:
    node = parse(
        "with {tC_34.03, c0030-0050, s*, default: 0, interval: true}: {r0010} >= {r0020} + {r0030}"
    )
    assert isinstance(node, With)
    assert node.context.table == "C_34.03"
    assert node.context.columns == AxisSelector(parts=(("0030", "0050"),))
    assert node.context.sheets == AxisSelector(wildcard=True)
    assert node.context.interval is True
    assert isinstance(node.context.default, Literal_)
    assert node.context.default.value == Decimal(0)
    assert isinstance(node.body, Binary)
    assert node.body.op == ">="


def test_axis_lists_and_references_inherit_context() -> None:
    node = parse(
        "with {tC_07.00.a, (c0010, c0030), default: 0, interval: true}: "
        "sum({tF_31.01, r0100, c*}) <= {(r0020, r0030-0040)}"
    )
    found = references(node)
    assert [reference.spec.table for reference in found] == ["F_31.01", "C_07.00.a"]
    assert found[1].spec.rows == AxisSelector(parts=("0020", ("0030", "0040")))
    assert found[1].spec.columns == AxisSelector(parts=("0010", "0030"))
    assert tables(node) == ("F_31.01", "C_07.00.a")


def test_references_leave_no_garbage_cycles() -> None:
    node = parse("with {tC_07.00.a, c0010}: {r0010} = {r0020} + sum({r0030-0050})")
    gc.collect()
    enabled = gc.isenabled()
    gc.disable()
    try:
        found = references(node)
        assert [reference.span for reference in found] == sorted(
            reference.span for reference in found
        )
        del found
        assert gc.collect() == 0, "references are freed when no longer used"
    finally:
        if enabled:
            gc.enable()


def test_clauses_sets_and_group_by() -> None:
    node = parse(
        "sum({tC_08.01.a, r0070} group by qEEA, OGR) = "
        "{tC_07.00.a, r0130, c0220} [sub qEBB = [eba_qEC:qx0]] and "
        "{r0015} [ where qEBB in {[eba_qEC:qx01], [eba_qEC:qx1]}] <= 1"
    )
    assert isinstance(node, Binary) and node.op == "and"
    left = node.left
    assert isinstance(left, Binary)
    assert isinstance(left.left, Call)
    assert left.left.group_by == ("qEEA", "OGR")
    assert isinstance(left.right, Sub)
    assert left.right.name == "qEBB"
    assert isinstance(node.right, Binary)
    where = node.right.left
    assert isinstance(where, Where)
    assert isinstance(where.condition, In)
    assert isinstance(where.condition.values, SetLiteral)
    assert where.condition.values.items[1] == Literal_(Item("qEC", "qx1"), "item")


def test_if_else_not_and_preconditions() -> None:
    node = parse(
        "if ({c0010} < 0) then ({c0010} = - {c0090}) else (isnull({c0090})) endif"
    )
    assert isinstance(node, If)
    assert node.otherwise is not None
    precondition = parse("{v_F_18.00} and ( {v_F_04.09} or {v_F_04.10} )")
    assert reported_templates(precondition) == ("F_18.00", "F_04.09", "F_04.10")
    assert isinstance(parse("not ( isnull ({c0040}) )"), Unary)
    assert isinstance(parse("{v_C_01.00}"), TableReported)


def test_literals() -> None:
    node = parse("{tW_07.01, c0010, r*} <= #2026-12-31#")
    assert isinstance(node, Binary)
    assert isinstance(node.right, Literal_)
    assert str(node.right.value) == "2026-12-31"
    percent = parse("{c0200} * 2%")
    assert isinstance(percent, Binary) and isinstance(percent.right, Literal_)
    assert percent.right.value == Decimal("0.02")
    text = parse("{c0040} != 'Not Applicable'")
    assert isinstance(text, Binary) and isinstance(text.right, Literal_)
    assert text.right.value == "Not Applicable"


def test_regex_with_braces_inside_strings() -> None:
    node = parse('match({tB_01.02, c0060}, "^[A-Z0-9]{18}[0-9]{2}$")')
    assert isinstance(node, Call)
    assert isinstance(node.args[1], Literal_)
    assert node.args[1].value == "^[A-Z0-9]{18}[0-9]{2}$"


def test_with_where_context() -> None:
    node = parse(
        "with {tR_04.00.a, c*, default: 0} [ where qPYB = [eba_qIA:qx2090] ]: {r0100} >= 0"
    )
    assert isinstance(node, With)
    assert node.condition is not None


def test_spans_cover_source() -> None:
    source = "with {c0010}: {tA, r0010} = ( {tA, r0020} + 1 )"
    node = parse(source)
    assert isinstance(node, With)
    body = node.body
    assert isinstance(body, Binary)
    assert source[slice(*body.right.span)] == "( {tA, r0020} + 1 )"
    assert isinstance(body.left, Selection)


@pytest.mark.parametrize(
    ("source", "message"),
    [
        ("", "empty expression"),
        ("{r0010", "unterminated '{'"),
        ("{tA, x0010}", "unknown selection component"),
        ("if {tA} then 1", "expected 'endif', found end of expression"),
        ("{tA} >=", "expression ends where an operand is expected"),
        ("sum({tA} group by) > 0", "expected a name, found ')'"),
        ("{tA, r0010 = 5", "unterminated '{': no matching '}'"),
        ("{tA} = = 1", "unexpected"),
        ("{tA, r0010, r0020}", "duplicate rows selector"),
        ("{tA, interval: maybe}", "interval must be true or false"),
        ("{tA, (r0010, )}", "empty axis list member"),
        ("{tA} in {[ [eba_BT:x1]}", "invalid item '[ [eba_BT:x1]'"),
        ("[eba_BT:x1 y] = 1", "invalid item"),
        ("[eba_BT:x1 = 1", "unterminated item"),
        ("{tA, (, r0010)}", "empty axis list member"),
        ("{tA, ()}", "empty axis list"),
        ("{tA, (r0010 c0010)}", "expected ')'"),
        ("(" * 60 + "true" + ")" * 60, "too deeply nested"),
        ("-" * 2000 + "1", "too deeply nested"),
        ("not " * 2000 + "true", "too deeply nested"),
        ("{tA}" + " [where qX = 1]" * 60, "too deeply nested"),
        ("1e99999999999 + 1 = 1", "number out of range"),
        ("4.5%% = 0.045", "'%' must follow a number"),
        ("{tA, default: 1e-99999999999}", "invalid default"),
    ],
)
def test_syntax_errors(source: str, message: str) -> None:
    with pytest.raises(DpmXlSyntaxError) as error:
        parse(source)
    assert message in error.value.message


def test_long_operator_chains_parse() -> None:
    node = parse(" + ".join(["{r0010}"] * 5000) + " = 0")
    assert isinstance(node, Binary)
    assert node.op == "="


def test_items_drop_the_eba_prefix_however_built() -> None:
    assert Item("eba_qEC", "qx1") == Item.parse("eba_qEC:qx1") == Item("qEC", "qx1")
    assert Item("EBA_qEC", "qx1").matches(Item("qEC", "qx1"))
    assert Item.parse("qx1") == Item(None, "qx1")


def test_clause_chains_within_the_nesting_limit_parse() -> None:
    node = parse("{tA}" + " [where qX = 1]" * 40 + " > 0")
    assert isinstance(node, Binary)
    assert isinstance(node.left, Where)


def test_deliberate_readings_that_keep_eba_rules_unchanged() -> None:
    # not binds looser than comparisons and in, unlike the grammar.
    negated = parse("not 1 = 2")
    assert isinstance(negated, Unary) and isinstance(negated.operand, Binary)
    member = parse("not 1 in {1}")
    assert isinstance(member, Unary) and isinstance(member.operand, In)
    for source in ("1 < 2 < 3", "- not true"):
        with pytest.raises(DpmXlSyntaxError):
            parse(source)
