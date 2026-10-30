import random
from collections.abc import Sequence
from datetime import date
from pathlib import Path

import pytest

from dpmxl import (
    DpmXlSyntaxError,
    Item,
    MemoryProvider,
    Number,
    TableLayout,
    Value,
    diagnose,
    evaluate_rule,
    parse,
)
from dpmxl.diagnostics import DIAGNOSTIC_CODES, Diagnostic
from dpmxl.parser import _parse_recovering, tokenize
from dpmxl.provider import CellKey

CORPUS = [
    line
    for line in Path(__file__)
    .with_name("data")
    .joinpath("eba_expressions.txt")
    .read_text(encoding="utf-8")
    .splitlines()
    if line.strip() and not line.startswith("#")
]

LAYOUTS = {
    "C_01.00": TableLayout(
        "C_01.00",
        rows=("0010", "0020", "0030"),
        columns=("0010", "0020"),
        data_types={
            (row, column, None): "number" if column == "0010" else "string"
            for row in ("0010", "0020", "0030")
            for column in ("0010", "0020")
        },
    ),
    "C_05.01": TableLayout(
        "C_05.01", rows=("0010",), columns=("0010",), sheets=("x01", "x02")
    ),
    "C_08.01": TableLayout(
        "C_08.01",
        rows=("0010",),
        columns=("0010",),
        open_keys=("qEEA",),
        open_axes=("sheets",),
    ),
    "C_27.00": TableLayout(
        "C_27.00",
        columns=("0010", "0020"),
        open_keys=("qNCO", "qINC"),
        open_axes=("rows",),
        data_types={(None, "0010", None): "item", (None, "0020", None): "date"},
    ),
    # Open keys without open_axes: the axis without codes is not checked.
    "C_28.00": TableLayout("C_28.00", columns=("0010",), open_keys=("qINC",)),
}
TABLES = tuple(LAYOUTS)


def found(
    expression: str,
    *,
    tables: tuple[str, ...] | None = TABLES,
    parameters: Sequence[str] | None = None,
    program: bool = False,
) -> list[tuple[str, str, str, str, str | None]]:
    return [
        (d.severity, d.code, expression[d.start : d.end], d.message, d.suggestion)
        for d in diagnose(
            expression,
            LAYOUTS.get,
            tables=tables,
            parameters=parameters,
            program=program,
        )
    ]


def codes(
    expression: str,
    *,
    parameters: Sequence[str] | None = None,
    program: bool = False,
) -> list[str]:
    return [
        code
        for _, code, _, _, _ in found(
            expression, parameters=parameters, program=program
        )
    ]


# Valid expressions -------------------------------------------------------


def test_eba_rules_have_no_diagnostics() -> None:
    assert [line for line in CORPUS if diagnose(line)] == []


@pytest.mark.parametrize(
    "expression",
    [
        "{tC_01.00, r0010, c0010} >= 0",
        "with {tC_01.00, c0010}: {r0010} = sum({r0020-0030})",
        "{tC_01.00, r0010-r0030, c*} > 0",
        "{tC_05.01, r0010, c0010, (sx01, sx02)} > 0",
        "{tC_27.00, c0020} > #2026-01-01# and {tC_27.00, r*, c0010} = [qCO:x1]",
        "count({tC_27.00, c0020} group by qNCO, INC) > 0",
        "{tC_27.00, c0010} [where qNCO = [qCO:x1] and r = r] [get qINC] = 'A'",
        "{tC_28.00, r0010, c0010} > 0",
        "max({tC_01.00, r0010, c0010}, 0) = max_aggr({tC_01.00, c0010} group by r)",
        "{g_G1, r9999} = 1 and {o_v1} and {v_C_99.00}",
        "if isnull({tC_01.00, r0010, c0010}) then 1 else 2 endif = 1",
        "{tC_01.00, r0010, c0020} & 'x' = 'yx'",
        "time_shift({tC_01.00, r0010, c0010}, Q, 1, qDATE) > 0",
    ],
)
def test_valid_expressions_have_no_diagnostics(expression: str) -> None:
    assert found(expression, parameters=()) == []


def test_diagnostics_are_ordered_and_coded() -> None:
    expression = "summ(1) + {r0010} + abs(1, 2) > {tXX, r0010} and ("
    diagnostics = diagnose(expression, LAYOUTS.get)
    assert [d.start for d in diagnostics] == sorted(d.start for d in diagnostics)
    assert {d.code for d in diagnostics} <= DIAGNOSTIC_CODES
    assert len(diagnostics) == 5


# Syntax ------------------------------------------------------------------


def test_syntax_errors_are_all_reported() -> None:
    assert found("abs({tC_01.00, r0010 c0010}) + summ(1) = = 2") == [
        (
            "error",
            "syntax",
            "r0010 c0010",
            "unknown selection component 'r0010 c0010'",
            None,
        ),
        (
            "error",
            "unknown-function",
            "summ",
            "unknown function 'summ'; did you mean 'sum'?",
            "sum",
        ),
        ("error", "syntax", "=", "unexpected '=' where an operand is expected", None),
    ]


def test_a_missing_token_is_reported_where_it_is_missing() -> None:
    assert diagnose("{tC_01.00, r0010} >= ") == (
        Diagnostic(
            "error", "syntax", "expression ends where an operand is expected", 21, 21
        ),
    )
    assert codes("sum({tC_01.00, r0010, c0010} {tC_01.00, r0020}) > 0") == ["syntax"]


@pytest.mark.parametrize(
    ("expression", "text", "suggestion"),
    [
        ("if {tA, r1} > 0 ornot {tA, r2} > 0 then true endif", "ornot", "or not"),
        ("if 1 = 1 then 1 else    trueendif", "trueendif", "true endif"),
        ("if 1 = 1 thennot false endif", "thennot", "then not"),
    ],
)
def test_keywords_run_together_are_a_missing_space(
    expression: str, text: str, suggestion: str
) -> None:
    (diagnostic,) = diagnose(expression)
    assert diagnostic.code == "syntax"
    assert expression[diagnostic.start : diagnostic.end] == text
    assert diagnostic.message == f"missing space: did you mean {suggestion!r}?"
    assert (diagnostic.subject, diagnostic.suggestion) == (text, suggestion)


def test_a_name_made_of_keywords_is_no_problem_without_an_error() -> None:
    assert diagnose("{tA, r1} [where ornot = 1] > 0") == ()


def test_rule_and_program_modes() -> None:
    script = "x := {tC_01.00, r0010, c0010}; x > 0"
    assert codes(script) == ["syntax", "syntax"]
    assert codes(script, program=True) == []
    assert codes("y > 0; z := 1", program=True, parameters=()) == ["unknown-name"]


def test_lexical_errors_end_the_check() -> None:
    assert diagnose('summ("x) > 0') == (
        Diagnostic("error", "syntax", "unterminated string", 5, 6),
    )


def test_recovery_reports_the_first_error_strict_parsing_does() -> None:
    # Damage every EBA sample rule a few ways; the first error must be the
    # one parse() raises, and nothing may crash.
    generator = random.Random(7)
    for line in CORPUS:
        tokens = [token for token in tokenize(line) if token.kind != "eof"]
        for _ in range(4):
            token = generator.choice(tokens)
            choice = generator.random()
            if choice < 0.4:
                damaged = line[: token.start] + line[token.end :]
            elif choice < 0.7:
                extra = generator.choice(["(", ")", "{", "}", ",", "=", "and", "x"])
                damaged = f"{line[: token.start]}{extra} {line[token.start :]}"
            else:
                damaged = f"{line[: token.end]} {token.text}{line[token.end :]}"
            try:
                parse(damaged)
                strict = None
            except DpmXlSyntaxError as error:
                strict = (error.position, error.message)
            _, errors = _parse_recovering(damaged)
            first = (errors[0].position, errors[0].message) if errors else None
            assert first == strict, damaged
            diagnose(damaged, LAYOUTS.get)


# Calls -------------------------------------------------------------------


def test_unknown_functions_suggest_a_close_name() -> None:
    assert found("summ(1) > nonsense(1) and ISNUL(1)") == [
        (
            "error",
            "unknown-function",
            "summ",
            "unknown function 'summ'; did you mean 'sum'?",
            "sum",
        ),
        ("error", "unknown-function", "nonsense", "unknown function 'nonsense'", None),
        (
            "error",
            "unknown-function",
            "ISNUL",
            "unknown function 'isnul'; did you mean 'isnull'?",
            "isnull",
        ),
    ]


def test_operand_counts_match_the_signatures() -> None:
    assert found(
        "abs(1, 2) + sum(1, 2) + filter(1) + len(substr('a', 1, 2, 3)) = 1"
    ) == [
        ("error", "operand-count", "abs", "abs takes 1 operand, not 2", None),
        ("error", "operand-count", "sum", "sum takes 1 operand, not 2", None),
        ("error", "operand-count", "filter", "filter takes 2 operands, not 1", None),
        (
            "error",
            "operand-count",
            "substr",
            "substr takes 1 to 3 operands, not 4",
            None,
        ),
    ]
    assert codes("abs({tC_01.00, r*, c0010} group by r) > 0") == ["group-by"]


NON_PORTABLE = "; other DPM-XL engines may reject it"


@pytest.mark.parametrize(
    ("expression", "text", "suggestion"),
    [
        (".5 > 0", ".5", "0.5"),
        ("1e5 > 0", "1e5", "100000"),
        ("{tC_01.00, r0010, c0010, default: 1E-2} > 0", "1E-2", "0.01"),
        ("max({tC_01.00, r*, c0010}) > 0", "max", "max_aggr"),
        ("min({tC_01.00, r*, c0010}) > 0", "min", "min_aggr"),
        ("{tC_01.00, r0010, c0010} <> 1", "<>", "!="),
        ("{tC_01.00, r0010, c0010} > 0 AND true", "AND", "and"),
        ("{tC_01.00, r0010, c0010, default: 0} = Null", "Null", "null"),
        ("Abs({tC_01.00, r0010, c0010}) > 0", "Abs", "abs"),
        ("length('a') = 1", "length", "len"),
        ("with {tC_01.00}: with {r0010}: {c0010} > 0", "with", None),
        ("substr('abc', 1 + 1) = 'bc'", "1 + 1", None),
        (
            "substr('abc', 1, {tC_01.00, r0010, c0010}) = 'a'",
            "{tC_01.00, r0010, c0010}",
            None,
        ),
        ("{tC_01.00, r0010, c0010, default: -1} > 0", "-1", "(-1)"),
        ("with {default: +2}: {tC_01.00, r0010, c0010} > 0", "+2", "2"),
        ("{p_X, number, default: -1.5} > 0", "-1.5", None),
        ("{tC_01.00, r0010, c0010} in {1.5, -3}", "-3", "(-3)"),
    ],
)
def test_syntax_beyond_the_official_grammar_is_non_portable(
    expression: str, text: str, suggestion: str | None
) -> None:
    ((severity, code, written, message, suggested),) = found(expression)
    assert (severity, code, written, suggested) == (
        "warning",
        "non-portable",
        text,
        suggestion,
    )
    assert message.endswith(NON_PORTABLE)


@pytest.mark.parametrize(
    "expression",
    [
        "0.5 + 100000 > {tC_01.00, r0010, c0010, default: (-1)}",
        "max({tC_01.00, r0010, c0010}, 0) = max_aggr({tC_01.00, r*, c0010})",
        "substr('abc', 2, (-1)) = 'bc' and {tC_01.00, r0010, c0010} in {(-3), 1.5}",
        "abs(-1) = 1 and 3 != null and -{tC_01.00, r0010, c0010} < 0",
    ],
)
def test_portable_spellings_are_not_flagged(expression: str) -> None:
    assert found(expression) == []


def test_key_operands_must_be_names() -> None:
    assert found("annualise({tC_01.00, r0010, c0010}, 12, 3) > 0") == [
        (
            "error",
            "key-operand",
            "3",
            "annualise needs a key name as its third operand",
            None,
        )
    ]


# Selections --------------------------------------------------------------


def test_a_selection_needs_a_table() -> None:
    assert codes("{r0010} = 1") == ["missing-table"]
    assert codes("with {c0010}: {r0010} = 1") == ["missing-table"]


def test_unknown_tables_suggest_a_close_code() -> None:
    assert found("{tC_01.0, r0010} = {tXX_99.99, r0010}") == [
        (
            "error",
            "unknown-table",
            "tC_01.0",
            "unknown table C_01.0; did you mean C_01.00?",
            "tC_01.00",
        ),
        ("error", "unknown-table", "tXX_99.99", "unknown table XX_99.99", None),
    ]
    # Without the table codes there is nothing to suggest.
    assert found("{tC_01.0, r0010} > 0", tables=None)[0][4] is None
    # Table codes ignore case (DPM-XL 2.4.1).
    assert found("isnull({t_c_27.00, c0010})") == []


def test_unknown_coordinates_are_underlined() -> None:
    assert found("{tC_01.00, r0011, c0030} = {tC_05.01, r0010, c0010, sx03}") == [
        (
            "error",
            "unknown-row",
            "r0011",
            "row 0011 is not in table C_01.00; did you mean r0010?",
            "r0010",
        ),
        (
            "error",
            "unknown-column",
            "c0030",
            "column 0030 is not in table C_01.00",
            None,
        ),
        ("error", "unknown-sheet", "sx03", "sheet x03 is not in table C_05.01", None),
    ]


def test_each_part_of_an_axis_list_is_checked() -> None:
    # The selection still covers r0010, so the missing part is a warning.
    assert found("{tC_01.00, (r0010, r0040), c0010} > 0") == [
        ("warning", "unknown-row", "r0040", "row 0040 is not in table C_01.00", None)
    ]
    # With no part matching, the selection is empty: an error for each.
    assert codes("{tC_01.00, (r0040, r0050-0090), c0010} > 0") == [
        "unknown-row",
        "empty-range",
    ]
    assert {
        item[0] for item in found("{tC_01.00, (r0040, r0050-0090), c0010} > 0")
    } == {"error"}


def test_a_context_problem_is_reported_once_at_the_context() -> None:
    assert found("with {tC_01.00, c0030}: {r0010} = {r0020} + {r9999}") == [
        (
            "error",
            "unknown-column",
            "c0030",
            "column 0030 is not in table C_01.00",
            None,
        ),
        ("error", "unknown-row", "r9999", "row 9999 is not in table C_01.00", None),
    ]


def test_a_code_on_an_axis_the_table_lacks() -> None:
    assert found("{tC_01.00, r0010, c0010, s0010} = 1") == [
        (
            "warning",
            "missing-sheet",
            "s0010",
            "table C_01.00 has no sheets, so it has no codes such as s0010",
            None,
        )
    ]


def test_a_shared_context_is_not_checked_on_tables_without_the_axis() -> None:
    # The context's c0010 applies to C_01.00; C_05.01 has columns too, but
    # the open sheets of C_08.01 and C_28.00's rows ignore what they lack.
    assert found("with {tC_01.00, c0010}: {r0010} = {tC_28.00, r0010}") == []
    assert (
        found("with {r0010, sx01, default: 0}: {tC_05.01, c0010} = {tC_08.01, c0010}")
        == []
    )
    assert found("with {sx01}: {tC_08.01, r0010, c0010} > 0") == []


def test_codes_on_an_open_axis() -> None:
    expression = "with {tC_08.01, c0010}: {r0010, (s0005, s0017)} = {r0010, s0003-0017}"
    assert found(expression) == [
        (
            "warning",
            "open-sheet",
            "(s0005, s0017)",
            "the sheets of C_08.01 are open (key qEEA), so they have no codes "
            "such as s0005; select them with s* or leave them out",
            "s*",
        ),
        (
            "warning",
            "open-sheet",
            "s0003-0017",
            "the sheets of C_08.01 are open (key qEEA), so they have no codes "
            "such as s0003-0017; select them with s* or leave them out",
            "s*",
        ),
    ]
    # Written in the context together with the table, it is meant for it.
    assert codes("with {tC_27.00, r0010}: {c0010} = [qCO:x1]") == ["open-row"]


def test_an_empty_range() -> None:
    # An empty selection evaluates to nothing: an error.
    assert found("{tC_01.00, r0040-0090, c0010} = 1") == [
        (
            "error",
            "empty-range",
            "r0040-0090",
            "rows 0040-0090 select no row of table C_01.00",
            None,
        )
    ]
    assert found("{tC_01.00, (r0010, r0040-0090), c0010} = 1")[0][0] == "warning"


def test_numeric_codes_compare_as_padded_numbers() -> None:
    assert found("{tC_01.00, r10, c0010} = 1") == []


def test_tables_are_not_checked_without_layouts() -> None:
    assert diagnose("{tXX_99.99, r0010} = 1 and {tX, c0010} [where qX = 1] > 0") == ()


# Keys and names ----------------------------------------------------------


def test_clause_names_must_be_keys() -> None:
    assert found(
        "{tC_27.00, c0010} [where qNCOO = [qCO:x1]] [sub qINX = 'A'] = [qCO:x1]"
        " and count({tC_27.00, c0010} group by qINCC) > 0"
    ) == [
        (
            "warning",
            "unknown-key",
            "qNCOO",
            "qNCOO is not a key of table C_27.00 (keys qNCO, qINC); unless it is "
            "a report parameter, evaluation fails",
            "qNCO",
        ),
        (
            "error",
            "unknown-key",
            "qINX",
            "qINX is not a key of table C_27.00 (keys qNCO, qINC)",
            "qINC",
        ),
        (
            "error",
            "unknown-key",
            "qINCC",
            "qINCC is not a key of table C_27.00 (keys qNCO, qINC)",
            "qINC",
        ),
    ]


def test_report_parameters_stand_in_for_keys_in_where_and_get() -> None:
    expression = "{tC_27.00, c0010} [get Level] > 0"
    assert codes(expression) == ["unknown-key"]
    assert found(expression)[0][0] == "warning"
    assert codes(expression, parameters=["Level"]) == []
    assert found(expression, parameters=[])[0][:2] == ("error", "unknown-key")
    assert found(expression, parameters=[])[0][3].endswith(", nor a report parameter")


def test_names_are_checked_against_the_parameters() -> None:
    assert found("refPeriodd > #2026-01-01#", parameters=["refPeriod"]) == [
        (
            "error",
            "unknown-name",
            "refPeriodd",
            "unknown name 'refPeriodd': no report parameter or earlier assignment "
            "has it; did you mean 'refPeriod'?",
            "refPeriod",
        )
    ]
    assert codes("refPeriodd > #2026-01-01#") == []


def test_earlier_assignments_are_names() -> None:
    script = "x := {tC_01.00, r0010, c0010}; y := x + 1; x < y and z > 0"
    assert found(script, program=True, parameters=()) == [
        (
            "error",
            "unknown-name",
            "z",
            "unknown name 'z': no report parameter or earlier assignment has it",
            None,
        )
    ]
    # Names ignore case; a suggestion keeps the assignment's spelling.
    script = "MyTotal := 1; mytotal > 0 and BASECURRENCY = [CU:EUR] and MyTotl > 0"
    assert found(script, program=True, parameters=()) == [
        (
            "error",
            "unknown-name",
            "MyTotl",
            "unknown name 'MyTotl': no report parameter or earlier assignment "
            "has it; did you mean 'MyTotal'?",
            "MyTotal",
        )
    ]


# Types -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("expression", "text", "message"),
    [
        (
            "{tC_01.00, r0010, c0020} + 1 > 0",
            "{tC_01.00, r0010, c0020}",
            "'+' needs numbers, but {tC_01.00, r0010, c0020} is a string",
        ),
        (
            "-{tC_01.00, r0010, c0020} > 0",
            "{tC_01.00, r0010, c0020}",
            "unary '-' needs a number, but {tC_01.00, r0010, c0020} is a string",
        ),
        (
            "{tC_01.00, r0010, c0010} = 'x'",
            "{tC_01.00, r0010, c0010} = 'x'",
            "'=' cannot compare a number with a string",
        ),
        (
            "{tC_27.00, c0010} > [qCO:x1]",
            "{tC_27.00, c0010} > [qCO:x1]",
            "items compare only with = or !=, not '>'",
        ),
        (
            "if {tC_01.00, r0010, c0010} then 1 endif = 1",
            "{tC_01.00, r0010, c0010}",
            "if needs a boolean condition, but {tC_01.00, r0010, c0010} is a number",
        ),
        (
            "{tC_01.00, r0010, c0010} and true",
            "{tC_01.00, r0010, c0010}",
            "'and' needs booleans, but {tC_01.00, r0010, c0010} is a number",
        ),
        (
            "year({tC_01.00, r0010, c0010}) > 2000",
            "{tC_01.00, r0010, c0010}",
            "year needs a date, but {tC_01.00, r0010, c0010} is a number",
        ),
        (
            "sum({tC_01.00, r*, c0020}) > 0",
            "{tC_01.00, r*, c0020}",
            "sum needs numbers, but {tC_01.00, r*, c0020} is a string",
        ),
        (
            "{vC_01.00} + 1 > 0",
            "{vC_01.00}",
            "'+' needs numbers, but {vC_01.00} is a boolean",
        ),
        (
            "len(sum({tC_01.00, r*, c0010}) & 'x') > 0",
            "sum({tC_01.00, r*, c0010})",
            "'&' needs strings, but sum({tC_01.00, r*, c0010}) is a number",
        ),
    ],
)
def test_operands_of_the_wrong_type(expression: str, text: str, message: str) -> None:
    mismatches = [item for item in found(expression) if item[1] == "type-mismatch"]
    assert [(item[2], item[3]) for item in mismatches] == [(text, message)]


@pytest.mark.parametrize(
    "expression",
    [
        # Mixed types and defaults leave the type open.
        "{tC_01.00, r0010} + 1 > 0",
        "{tC_01.00, r0010, c0020, default: 0} + 1 > 0",
        # Strings compare with dates, booleans and items whatever their text.
        "{tC_01.00, r0010, c0020} = #2026-01-01# or {tC_01.00, r0010, c0020} = true",
        "{tC_27.00, c0010} = 'qCO:x1'",
        "nvl({tC_01.00, r0010, c0010}, 0) + 1 > 0",
        # A variable that is not a template is a parameter of any type.
        "{vReportingLevel} + 1 > 0",
    ],
)
def test_undecided_types_are_not_reported(expression: str) -> None:
    assert codes(expression) == []


# Pointer -----------------------------------------------------------------


def test_pointer_marks_the_text_on_its_line() -> None:
    expression = "{tC_01.00, r0010} >\n  summ(1)"
    (diagnostic,) = diagnose(expression)
    assert diagnostic.pointer(expression) == "  summ(1)\n  ^~~~"


def test_cells_without_a_data_type_leave_the_type_unknown() -> None:
    layouts = {
        "P": TableLayout(
            "P",
            rows=("0010", "0020"),
            columns=("0010",),
            data_types={("0010", "0010", None): "number"},
        )
    }
    assert diagnose("{tP, c0010} = 'x'", layouts.get) == ()
    assert [d.code for d in diagnose("{tP, r0010, c0010} = 'x'", layouts.get)] == [
        "type-mismatch"
    ]


# Parity with evaluation ----------------------------------------------------

_SAMPLE_VALUES = {
    "number": Number.of(5, 0),
    "string": "x",
    "date": date(2026, 12, 31),
    "boolean": True,
    "item": Item("qCO", "x1"),
}


def _provider() -> MemoryProvider:
    """Build a report with a value in every cell of the layouts.

    Returns:
        MemoryProvider: Untyped cells hold numbers; open tables one key row.
    """
    values: dict[CellKey, Value] = {}
    for layout in LAYOUTS.values():
        keys = tuple((name, Item("qCO", "x1")) for name in layout.open_keys)
        for cell in layout.coordinates():
            data_type = layout.data_types.get(cell, "number")
            values[layout.code, *cell, keys] = _SAMPLE_VALUES[
                "number" if data_type == "integer" else data_type
            ]
    return MemoryProvider(LAYOUTS.values(), values, parameters={"refPeriod": None})


PARITY = [
    "with {tC_01.00, c0010}: {r0010} = {tC_28.00, r0010}",
    "with {sx01, default: 0}: {tC_01.00, r0010, c0010} = {tC_08.01, r0010, c0010}",
    "{tC_01.00, r0010, c0010, s0010} = 5",
    "{tC_08.01, r0010, c0010, s0005} = 5",
    "{tC_01.00, (r0010, r0040), c0010} = 5",
    "{tC_01.00, r0040, c0010} = 5",
    "{tC_01.00, r0040-0090, c0010} = 5",
    "{tC_01.00, r0010, c0020} + 1 > 0",
    "{tC_01.00, r0010, c0010} = 'x'",
    "{tC_27.00, c0010} > [qCO:x1]",
    "{tC_27.00, c0010} [sub qINX = [qCO:x1]] = [qCO:x1]",
    "count({tC_27.00, c0010} group by qINCC) > 0",
    "{tC_27.00, c0010} [where qNCO = [qCO:x1]] = [qCO:x1]",
    "{tXX, r0010} = 1",
    "{r0010} = 1",
    "summ({tC_01.00, r0010, c0010}) > 0",
    "abs({tC_01.00, r0010, c0010}, 1) > 0",
    "year({tC_01.00, r0010, c0010}) > 0",
    "with {tC_01.00, c0010}: if {r0010} then {r0020} > 0 endif",
]


@pytest.mark.parametrize("expression", PARITY)
def test_an_error_means_the_rule_does_not_pass(expression: str) -> None:
    # Each case either has an error, or holds for the sample report.
    errors = [d for d in diagnose(expression, LAYOUTS.get) if d.severity == "error"]
    result = evaluate_rule(expression, _provider())
    if errors:
        assert result.status != "passed", errors
    else:
        assert result.status == "passed", result.message


@pytest.mark.parametrize("expression", PARITY)
def test_the_columnar_engine_agrees(expression: str) -> None:
    pytest.importorskip("polars")
    from dpmxl.columnar import (
        ColumnarUnsupported,
        PointsFrameProvider,
        evaluate_rule_columnar,
    )

    errors = [d for d in diagnose(expression, LAYOUTS.get) if d.severity == "error"]
    try:
        result = evaluate_rule_columnar(expression, PointsFrameProvider(_provider()))
    except ColumnarUnsupported:
        pytest.skip("evaluated by the reference engine")
    assert (result.status == "passed") == (not errors)


def test_clauses_may_name_the_fact() -> None:
    # DPM-XL 11.1.5: a where condition may use the Fact Component, f.
    assert found("{tC_28.00, c0010} [where f != 0] > 0", parameters=()) == []
    assert found("with {tC_28.00} [where F != 0]: {c0010} > 0", parameters=()) == []


def test_analytic_functions_check_their_keys() -> None:
    assert found("rank({tC_28.00, c0010} over (order by qX desc)) > 0") == [
        (
            "error",
            "unknown-key",
            "qX",
            "qX is not a key of table C_28.00 (keys qINC)",
            None,
        )
    ]
    assert found("rank({tC_28.00, c0010} over (partition by INC order by f)) > 0") == []


def test_contextual_components_are_known_names() -> None:
    # DPM-XL 2.2.3.3.1: contextual components exist in every record set.
    assert (
        found("{tC_28.00, c0010} [where baseCurrency = [CU:EUR]] > 0", parameters=())
        == []
    )
    assert found('entityID = "LEI"', parameters=()) == []


@pytest.mark.parametrize(
    ("expression", "suggestion"),
    [
        # One typo away, though too short for the similarity ratio.
        ("sun(1) > 0", "sum"),
        ("smu(1) > 0", "sum"),
        ("mx(1, 2) > 0", "max"),
        ("summ(1) > 0", "sum"),
    ],
)
def test_near_misses_get_a_suggestion(expression: str, suggestion: str) -> None:
    (diagnostic,) = diagnose(expression)
    assert diagnostic.suggestion == suggestion


def test_names_two_typos_away_or_ambiguous_get_none() -> None:
    (diagnostic,) = diagnose("xyz(1) > 0")
    assert diagnostic.suggestion is None
