"""One or more examples for every alternative of the DPM-XL grammar.

Every example must parse; every example that yields a value is evaluated
against the small report below. The rule names follow the DPM-XL grammar
(``parser rule`` or ``#labelled alternative``).
"""

from datetime import date

import pytest

from dpmxl import (
    Item,
    MemoryProvider,
    Number,
    TableLayout,
    Value,
    ValueSet,
    format_value,
    parse,
    parse_program,
)
from dpmxl.evaluator import Evaluator
from dpmxl.provider import CellKey


def tables() -> list[TableLayout]:
    return [
        TableLayout("T", rows=("0010", "0020", "0030"), columns=("0010", "0020")),
        TableLayout("U", rows=("0010", "0020", "0030"), columns=("0010", "0020")),
        TableLayout("S", rows=("0010",), columns=("0010",), sheets=("0001", "0002")),
        TableLayout("O", columns=("0010",), open_keys=("qKEY", "qDAT")),
        TableLayout("X", rows=("0010",), columns=("0010", "0020")),
    ]


def facts(shift: int = 0) -> dict[CellKey, Value]:
    values: dict[CellKey, Value] = {
        ("T", "0010", "0010", None, ()): Number.of(100 + shift, 0),
        ("T", "0020", "0010", None, ()): Number.of(60, 0),
        ("T", "0030", "0010", None, ()): Number.of(40, 0),
        ("T", "0010", "0020", None, ()): Number.of(5, 0),
        ("T", "0020", "0020", None, ()): Number.of(-5, 0),
        ("U", "0010", "0010", None, ()): Number.of(1, 0),
        ("U", "0020", "0010", None, ()): Number.of(2, 0),
        ("U", "0030", "0010", None, ()): Number.of(3, 0),
        ("S", "0010", "0010", "0001", ()): Number.of(7, 0),
        ("S", "0010", "0010", "0002", ()): Number.of(8, 0),
        ("X", "0010", "0010", None, ()): "LEI-A",
        ("X", "0010", "0020", None, ()): Item("qC", "x1"),
    }
    for index, (key, day) in enumerate(
        (("a", date(2026, 3, 31)), ("b", date(2026, 6, 30)), ("c", date(2026, 9, 30)))
    ):
        values["O", None, "0010", None, (("qKEY", key), ("qDAT", day))] = Number.of(
            10 * (index + 1), 0
        )
    return values


def report() -> MemoryProvider:
    previous = MemoryProvider(
        tables(), facts(shift=-50), parameters={"refPeriod": date(2025, 12, 31)}
    )
    return MemoryProvider(
        tables(),
        facts(),
        parameters={
            "refPeriod": date(2026, 12, 31),
            "Level": "solo",
            "Allowed": ValueSet((Item("qC", "x1"), Item("qC", "x2"))),
        },
        table_groups={"G": ("T", "U")},
        operations={"v1": "with {tT, c0010}: {r*} * 2"},
        earlier_reports={("A", 1): previous},
    )


# (grammar alternative, example, evaluated value). The value is rendered with
# format_value, a keyed result as "key=value; ..." in key order; None marks
# an example that is not evaluable on its own (a key name outside a clause).
EXAMPLES: list[tuple[str, str, str | None]] = [
    # start, statements, statement
    ("start: statement", "1 = 1", "true"),
    ("start: statement ;", "1 = 1;", "true"),
    ("start: statement ; statements", "x := 1; y := x + 1; y = 2;", "true"),
    ("#exprWithoutAssignment", "{tT, r0010, c0010}", "100"),
    ("#assignmentExpr: temporaryIdentifier := expression", "a := 2 * 3", "6"),
    ("temporaryIdentifier: ESCAPED_IDENTIFIER", "`a.b` := 4; `a.b` + 1", "5"),
    ("#persistentAssignExpr: {cellRef} <-", "{tT, r0030, c0020} <- 1 + 1", "2"),
    ("#persistentAssignExpr: {varRef} <-", "{vTotal} <- sum({tU, c0010, r*})", "6"),
    ("persistentExpression: persistentAssignment", "t := {vY} <- 5; t", "5"),
    (
        "#persistentAssignExpr with a with context",
        "{tT, r0030, c0020} <- with {tU, c0010}: {r0010} + {r0020}",
        "3",
    ),
    # expressionWithoutAssignment
    ("#exprWithoutPartialSelection", "{tU, r0010, c0010} + 1", "2"),
    ("#exprWithSelection", "with {tU, c0010}: {r0030}", "3"),
    (
        "#exprWithSelection with where",
        "with {tO, c0010} [where qKEY = 'b']: {tO}",
        "qKEY=b, qDAT=2026-06-30: 20",
    ),
    ("partialSelection: operation", "with {o_v1}: {r0020}", "120"),
    ("partialSelection: table group", "with {g_G, c0010}: {r0030}", "t=T: 40; t=U: 3"),
    # expression
    ("#parExpr", "(1 + 2) * 3", "9"),
    ("#funcExpr", "abs(-2)", "2"),
    ("#clauseExpr", "{tT, c0010, r*} [where r = '0020']", "r=0020: 60"),
    ("#unaryExpr +", "+{tU, r0010, c0010}", "1"),
    ("#unaryExpr -", "-{tU, r0010, c0010}", "-1"),
    ("#notExpr", "not true", "false"),
    ("#numericExpr *", "2 * 3", "6"),
    ("#numericExpr /", "6 / 4", "1.5"),
    ("#numericExpr +", "2 + 3", "5"),
    ("#numericExpr -", "2 - 3", "-1"),
    ("#concatExpr", '"ab" & "cd"', '"abcd"'),
    ("#compExpr =", "1 = 1", "true"),
    ("#compExpr !=", "1 != 1", "false"),
    ("#compExpr >", "2 > 1", "true"),
    ("#compExpr <", "2 < 1", "false"),
    ("#compExpr >=", "1 >= 1", "true"),
    ("#compExpr <=", "2 <= 1", "false"),
    ("#inExpr with a set literal", "2 in {1, 2}", "true"),
    ("#inExpr with a set expression", "3 in union({1}, {3})", "true"),
    ("#inExpr with a selection", "60 in {tT, c0010, r*}", "true"),
    ("#inExpr with a set parameter", "[qC:x2] in {p_Allowed, set-item}", "true"),
    ("#boolExpr and", "true and false", "false"),
    ("#boolExpr or", "true or false", "true"),
    ("#boolExpr xor", "true xor true", "false"),
    ("#ifExpr", "if 1 > 0 then 'yes' else 'no' endif", '"yes"'),
    ("#ifExpr without else", "if 1 < 0 then true endif", "true"),
    ("#itemReferenceExpr", "[eba_qC:x1]", "[qC:x1]"),
    ("#propertyReferenceExpr", "[qEBB]", "[qEBB]"),
    ("#keyNamesExpr", "qKEY", None),
    ("#literalExpr", "'text'", '"text"'),
    ("#selectExpr", "{tU, r0020, c0010}", "2"),
    ("#setExpr", "{1, 2}", "{1, 2}"),
    # setOperand, setElements
    ("setOperand: {}", "{}", "{}"),
    ("setElements: itemReference", "{[qC:x1], [qC:x2]}", "{[qC:x1], [qC:x2]}"),
    ("setElements: literal", "{'a', 'b', 'a'}", '{"a", "b"}'),
    ("setElements: negative integer literal", "{(-5), 3}", "{-5, 3}"),
    # setExpression
    ("#setLiteralExpr", "{#2026-01-01#}", "{2026-01-01}"),
    ("#setOfExpr", "set_of({tU, c0010, r*})", "{1, 2, 3}"),
    ("#unionSetExpr", "union({1}, {2}, {1})", "{1, 2}"),
    ("#intersectSetExpr", "intersect({1, 2}, {2, 3})", "{2}"),
    ("#setdiffSetExpr", "setdiff({1, 2}, {2, 3})", "{1}"),
    ("#symdiffSetExpr", "symdiff({1, 2}, {2, 3})", "{1, 3}"),
    # numericOperators
    ("#unaryNumericFunctions abs", "abs(-3)", "3"),
    ("#unaryNumericFunctions exp", "exp(0)", "1"),
    ("#unaryNumericFunctions ln", "ln(1)", "0"),
    ("#unaryNumericFunctions sqrt", "sqrt(16)", "4"),
    ("#binaryNumericFunctions power", "power(2, 10)", "1,024"),
    ("#binaryNumericFunctions log", "log(100, 10)", "2"),
    ("#complexNumericFunctions max", "max(1, 5, 3)", "5"),
    ("#complexNumericFunctions min", "min(1, 5, 3)", "1"),
    # comparisonFunctionOperators, filterOperators, conditionalOperators
    ("#matchExpr", "match({tX, r0010, c0010}, '^LEI-[A-Z]$')", "true"),
    ("#isnullExpr", "isnull({tT, r0030, c0020})", "true"),
    (
        "filterOperators",
        "filter({tT, c0010, r*}, {tT, c0010, r*} > 50)",
        "r=0010: 100; r=0020: 60",
    ),
    ("#nvlFunction", "nvl({tT, r0030, c0020}, 0)", "0"),
    # timeOperators
    (
        "#timeShiftFunction with the reference period",
        "time_shift({tT, r0010, c0010}, A, 1, refPeriod)",
        "50",
    ),
    ("#timeShiftFunction without a key", "time_shift({tT, r0010, c0010}, A, 1)", "50"),
    (
        "#timeShiftFunction with a date key",
        "time_shift({tO, c0010} [where qKEY = 'a'], Q, 1, qDAT)",
        "qKEY=a, qDAT=2026-06-30: 10",
    ),
    ("#annualiseFunction", "annualise(30, 6, refPeriod)", "60"),
    ("#dateExtractFunction year", "year(#2026-05-31#)", "2,026"),
    ("#dateExtractFunction semester", "semester(#2026-05-31#)", "1"),
    ("#dateExtractFunction quarter", "quarter(#2026-05-31#)", "2"),
    ("#dateExtractFunction month", "month(#2026-05-31#)", "5"),
    ("#dateExtractFunction week", "week(#2026-05-31#)", "22"),
    ("#dateExtractFunction day", "day(#2026-05-31#)", "31"),
    ("#dateConstructorFunction", "date(2026, 2, 28)", "2026-02-28"),
    # stringOperators
    ("#unaryStringFunction", "len('abc')", "3"),
    ("#substrFunction", "substr('abcdef')", '"abcdef"'),
    ("#substrFunction start", "substr('abcdef', 3)", '"cdef"'),
    ("#substrFunction start, length", "substr('abcdef', 3, 2)", '"cd"'),
    # aggregateOperators
    ("#commonAggrOp max_aggr", "max_aggr({tU, c0010, r*})", "3"),
    ("#commonAggrOp min_aggr", "min_aggr({tU, c0010, r*})", "1"),
    ("#commonAggrOp sum", "sum({tU, c0010, r*})", "6"),
    ("#commonAggrOp count", "count({tU, c0010, r*})", "3"),
    ("#commonAggrOp avg", "avg({tU, c0010, r*})", "2"),
    ("#commonAggrOp median", "median({tU, c0010, r*})", "2"),
    (
        "groupingClause",
        "sum({tT, (c0010, c0020), r*} group by c)",
        "c=0010: 200; c=0020: 0",
    ),
    (
        "groupingClause with several keys",
        "count({tT, c*, r*} group by r, c)",
        "r=0010, c=0010: 1; r=0010, c=0020: 1; r=0020, c=0010: 1; "
        "r=0020, c=0020: 1; r=0030, c=0010: 1; r=0030, c=0020: 0",
    ),
    (
        "#commonAggrOp with analyticClause",
        "sum({tU, c0010, r*} over (order by r))",
        "r=0010: 6; r=0020: 6; r=0030: 6",
    ),
    (
        "#rankOp",
        "rank({tU, c0010, r*} over (order by r desc))",
        "r=0030: 1; r=0020: 2; r=0010: 3",
    ),
    # analyticClause, partitionClause, orderClause, orderItem, windowClause
    (
        "analyticClause: empty",
        "count({tU, c0010, r*} over ())",
        "r=0010: 3; r=0020: 3; r=0030: 3",
    ),
    (
        "partitionClause",
        "sum({tT, c*, r*} over (partition by c))",
        "r=0010, c=0010: 200; r=0020, c=0010: 200; r=0030, c=0010: 200; "
        "r=0010, c=0020: 0; r=0020, c=0020: 0; r=0030, c=0020: 0",
    ),
    (
        "orderItem asc",
        "rank({tU, c0010, r*} over (order by r asc))",
        "r=0010: 1; r=0020: 2; r=0030: 3",
    ),
    (
        "windowClause: data points, preceding and following",
        "sum({tU, c0010, r*} over (order by r data points between 1 preceding "
        "and 1 following))",
        "r=0010: 3; r=0020: 6; r=0030: 5",
    ),
    (
        "windowBoundary: unbounded preceding, current data point",
        "sum({tU, c0010, r*} over (order by r data points between unbounded "
        "preceding and current data point))",
        "r=0010: 1; r=0020: 3; r=0030: 6",
    ),
    (
        "windowBoundary: unbounded following",
        "sum({tU, c0010, r*} over (order by r data points between current data "
        "point and unbounded following))",
        "r=0010: 6; r=0020: 5; r=0030: 3",
    ),
    (
        "windowClause: range with a time period",
        "sum({tO, c0010} over (order by qDAT range between 3 M preceding and "
        "current data point))",
        "qKEY=a, qDAT=2026-03-31: 10; qKEY=b, qDAT=2026-06-30: 30; "
        "qKEY=c, qDAT=2026-09-30: 50",
    ),
    (
        "windowBoundary: n period following",
        "count({tO, c0010} over (order by qDAT range between current data point "
        "and 1 Q following))",
        "qKEY=a, qDAT=2026-03-31: 2; qKEY=b, qDAT=2026-06-30: 2; "
        "qKEY=c, qDAT=2026-09-30: 1",
    ),
    (
        "rank in a condition",
        "filter({tU, c0010, r*}, rank({tU, c0010, r*} over (order by r)) <= 2)",
        "r=0010: 1; r=0020: 2",
    ),
    # rowHandler, colHandler, sheetHandler
    ("rowElem: ROW", "{tU, r0010, c0010}", "1"),
    ("rowElem: ROW_RANGE", "sum({tU, r0010-0020, c0010})", "3"),
    ("rowElem: ROW_ALL", "sum({tU, r*, c0010})", "6"),
    ("rowHandler: list", "sum({tU, (r0010, r0030), c0010})", "4"),
    ("colElem: COL_RANGE", "sum({tT, r0010, c0010-0020})", "105"),
    ("colHandler: list", "sum({tT, r0010, (c0010, c0020)})", "105"),
    ("sheetElem: SHEET", "{tS, r0010, c0010, s0002}", "8"),
    ("sheetElem: SHEET_RANGE", "sum({tS, r0010, c0010, s0001-0002})", "15"),
    ("sheetElem: SHEET_ALL", "sum({tS, r0010, c0010, s*})", "15"),
    ("sheetHandler: list", "sum({tS, r0010, c0010, (s0001, s0002)})", "15"),
    # argument: interval, default
    ("interval", "{tT, r0010, c0010, interval: true} = 100.4", "true"),
    ("default: literal", "{tT, r0030, c0020, default: 0}", "0"),
    ("default: null", "isnull({tT, r0030, c0020, default: null})", "true"),
    ("default: itemReference", "{tT, r0030, c0020, default: [qC:x0]}", "[qC:x0]"),
    ("default: setOperand", "{p_None, set-integer, default: {1, 2}}", "{1, 2}"),
    # select, selectOperand
    ("selectOperand: cellRef", "{tU, r0030, c0010}", "3"),
    ("selectOperand: varRef (filing indicator)", "{v_T}", "true"),
    ("selectOperand: varRef (report parameter)", "{vLevel}", '"solo"'),
    ("selectOperand: operationRef", "{o_v1}", "r=0010: 200; r=0020: 120; r=0030: 80"),
    ("selectOperand: parameterRef", "{p_Level, string}", '"solo"'),
    # parameterType
    ("parameterType: number", "{p_N, number, default: 1.5}", "1.5"),
    ("parameterType: integer", "{p_N, integer, default: (-2)}", "-2"),
    ("parameterType: string", "{p_Level, string}", '"solo"'),
    ("parameterType: date", "{p_refPeriod, date}", "2026-12-31"),
    ("parameterType: boolean", "{p_B, boolean, default: true}", "true"),
    ("parameterType: item", "{p_I, item, default: [qC:x1]}", "[qC:x1]"),
    ("parameterType: set-number", "{p_S, set-number, default: {1.5}}", "{1.5}"),
    ("parameterType: set-integer", "{p_S, set-integer, default: {1}}", "{1}"),
    ("parameterType: set-string", "{p_S, set-string, default: {'a'}}", '{"a"}'),
    (
        "parameterType: set-date",
        "{p_S, set-date, default: {#2026-01-01#}}",
        "{2026-01-01}",
    ),
    ("parameterType: set-boolean", "{p_S, set-boolean, default: {true}}", "{true}"),
    ("parameterType: set-item", "{p_Allowed, set-item}", "{[qC:x1], [qC:x2]}"),
    # cellAddress, tableReference
    ("#tableRef", "{tU, r0020, c0010}", "2"),
    ("#opRef", "{o_v1, r0010}", "200"),
    ("#compRef", "with {tU}: {r0010, c0010}", "1"),
    (
        "tableReference: TABLE_GROUP_REFERENCE",
        "{g_G, r0010, c0010}",
        "t=T: 100; t=U: 1",
    ),
    ("tableReference: escaped code", "{t`U`, r0010, c0010}", "1"),
    # clauseOperators
    (
        "#whereExpr",
        "{tO, c0010} [where qKEY in {'a', 'c'}]",
        "qKEY=a, qDAT=2026-03-31: 10; qKEY=c, qDAT=2026-09-30: 30",
    ),
    (
        "#getExpr",
        "{tO, c0010} [where qKEY = 'b'] [get qDAT]",
        "qKEY=b, qDAT=2026-06-30: 2026-06-30",
    ),
    (
        "#renameExpr",
        "{tO, c0010} [where qKEY = 'b'] [rename qKEY to K, qDAT to `D.x`]",
        "K=b, D.x=2026-06-30: 20",
    ),
    (
        "#subExpr with a literal",
        "{tO, c0010} [sub qKEY = 'b'] [sub qDAT = #2026-06-30#]",
        "20",
    ),
    (
        "#subExpr with a select",
        "{tO, c0010} [sub qKEY = {p_K, string, default: 'c'}] [sub qDAT = #2026-09-30#]",
        "30",
    ),
    (
        "#subExpr with an item",
        "{tO, c0010} [sub qKEY = [qC:a]] [sub qDAT = #2026-03-31#]",
        "10",
    ),
    # literal
    ("literal: INTEGER_LITERAL", "42", "42"),
    ("literal: negative INTEGER_LITERAL", "(-42)", "-42"),
    ("literal: DECIMAL_LITERAL", "4.25", "4.25"),
    ("literal: PERCENT_LITERAL", "4.5%", "0.045"),
    ("literal: STRING_LITERAL", '"x"', '"x"'),
    ("literal: BOOLEAN_LITERAL", "false", "false"),
    ("literal: DATE_LITERAL", "#2026-12-31#", "2026-12-31"),
    ("literal: DATE_LITERAL with time", "#2026-12-31T10:30:00#", "2026-12-31T10:30:00"),
    ("literal: EMPTY_LITERAL", "''", '""'),
    ("literal: null", "null", "null"),
    # keyNames, propertyCode in clauses
    ("keyNames: ROW_COMPONENT", "{tT, c0010, r*} [where r = '0010']", "r=0010: 100"),
    (
        "keyNames: COL_COMPONENT",
        "sum({tT, r0010, c*} group by c)",
        "c=0010: 100; c=0020: 5",
    ),
    (
        "keyNames: SHEET_COMPONENT",
        "{tS, r0010, c0010, s*} [where s = '0002']",
        "s=0002: 8",
    ),
    (
        "keyNames: ESCAPED_IDENTIFIER",
        "{tO, c0010} [where `qKEY` = 'c']",
        "qKEY=c, qDAT=2026-09-30: 30",
    ),
]


@pytest.mark.parametrize(("rule", "expression", "expected"), EXAMPLES)
def test_every_grammar_alternative_parses(
    rule: str, expression: str, expected: str | None
) -> None:
    program = parse_program(expression)
    assert program.statements
    if len(program.statements) == 1 and not rule.startswith(
        ("#assignmentExpr", "#persistentAssignExpr", "persistentExpression")
    ):
        assert parse(expression) == program.statements[0]


EVALUABLE = [example for example in EXAMPLES if example[2] is not None]


@pytest.mark.parametrize(("rule", "expression", "expected"), EVALUABLE)
def test_every_evaluable_alternative_evaluates(
    rule: str, expression: str, expected: str
) -> None:
    result = Evaluator(report()).run(parse_program(expression)).result
    if not result.keys:
        record = result.single()
        assert format_value(record.value if record else None) == expected
        return
    shown = "; ".join(
        ", ".join(
            f"{name}={_key_text(part)}"
            for name, part in zip(result.keys, key, strict=True)
        )
        + f": {_plain(record.value)}"
        for key, record in result.records.items()
    )
    assert shown == expected


def _key_text(value: object) -> str:
    return value.isoformat() if isinstance(value, date) else str(value)


def _plain(value: Value) -> str:
    text = format_value(value)
    return text[1:-1] if isinstance(value, str) else text


def test_every_call_name_has_a_signature() -> None:
    from dpmxl.grammar import CALL_NAMES, SIGNATURES

    assert set(SIGNATURES) == CALL_NAMES


@pytest.mark.parametrize(
    ("name", "count", "group_by", "problem"),
    [
        ("abs", 1, False, None),
        ("abs", 2, False, "abs takes 1 operand, not 2"),
        ("power", 1, False, "power takes 2 operands, not 1"),
        ("substr", 0, False, "substr takes 1 to 3 operands, not 0"),
        ("time_shift", 5, False, "time_shift takes 3 or 4 operands, not 5"),
        ("union", 1, False, "union takes 2 or more operands, not 1"),
        ("max", 3, False, None),
        ("max", 2, True, "max with group by takes 1 operand, not 2"),
        ("sum", 1, True, None),
        ("abs", 1, True, "group by is not allowed in abs"),
    ],
)
def test_signatures_describe_operand_problems(
    name: str, count: int, group_by: bool, problem: str | None
) -> None:
    from dpmxl.grammar import SIGNATURES

    assert SIGNATURES[name].problem(name, count, group_by=group_by) == problem


@pytest.mark.parametrize(
    ("expression", "message"),
    [
        ("abs(1, 2) > 0", "abs takes 1 operand, not 2"),
        ("annualise({tT, r0010, c0010}, 12, 3) > 0", "annualise needs a key name"),
        ("time_shift({tT, r0010, c0010}, A, 1, 2) > 0", "time_shift needs a key"),
    ],
)
def test_the_evaluator_checks_calls_against_the_signatures(
    expression: str, message: str
) -> None:
    from dpmxl import MemoryProvider, TableLayout, evaluate_rule

    provider = MemoryProvider([TableLayout("T", rows=("0010",), columns=("0010",))], {})
    result = evaluate_rule(expression, provider)
    assert result.status == "error"
    assert result.message is not None and result.message.startswith(message)
