import itertools
import json
from pathlib import Path

import pytest

from dpmxl import DpmXlSyntaxError, parse
from dpmxl.grammar import (
    FUNCTIONS,
    KEYWORDS,
    LITERAL_WORDS,
    OPERATORS,
    PARAMETER_TYPES,
    REFERENCE_PREFIXES,
    SELECTION_KEYWORDS,
    TIME_PERIODS,
    TOKEN_KINDS,
    WINDOW_KEYWORDS,
    textmate_grammar,
)
from dpmxl.parser import Token, tokenize

ROOT = Path(__file__).parent.parent
CORPUS = Path(__file__).parent / "data" / "eba_expressions.txt"


def kinds(expression: str) -> list[tuple[str, str]]:
    return [(token.kind, token.text) for token in tokenize(expression)[:-1]]


def test_selection_tokens_suit_highlighting() -> None:
    assert kinds("with {tC_01.00, c*, default: 0, interval: true}: {r0010-0050}") == [
        ("keyword", "with"),
        ("brace", "{"),
        ("table", "tC_01.00"),
        ("punctuation", ","),
        ("axis", "c*"),
        ("punctuation", ","),
        ("keyword", "default"),
        ("punctuation", ":"),
        ("number", "0"),
        ("punctuation", ","),
        ("keyword", "interval"),
        ("punctuation", ":"),
        ("boolean", "true"),
        ("brace", "}"),
        ("punctuation", ":"),
        ("brace", "{"),
        ("axis", "r0010-0050"),
        ("brace", "}"),
    ]


def test_expression_tokens_suit_highlighting() -> None:
    assert kinds(
        "sum({r0010} group by qEBB) [where qX = [eba_qEC:qx1]] & 'a' != `x.y`"
    ) == [
        ("function", "sum"),
        ("punctuation", "("),
        ("brace", "{"),
        ("axis", "r0010"),
        ("brace", "}"),
        ("keyword", "group by"),
        ("identifier", "qEBB"),
        ("punctuation", ")"),
        ("punctuation", "["),
        ("keyword", "where"),
        ("identifier", "qX"),
        ("operator", "="),
        ("item", "[eba_qEC:qx1]"),
        ("punctuation", "]"),
        ("operator", "&"),
        ("string", "'a'"),
        ("operator", "!="),
        ("identifier", "`x.y`"),
    ]


def test_context_dependent_kinds() -> None:
    assert kinds("time_shift({tA}, Q, 1, refPeriod)")[6] == ("period", "Q")
    window = kinds(
        "rank({tA} over (partition by r order by c desc "
        "range between 11 M preceding and current data point))"
    )
    assert ("keyword", "partition by") in window
    assert ("keyword", "desc") in window
    assert ("period", "M") in window
    assert ("keyword", "current data point") in window
    # Window words and period codes are names elsewhere.
    assert kinds("{tA} [where range = M]")[5:8] == [
        ("identifier", "range"),
        ("operator", "="),
        ("identifier", "M"),
    ]
    assert kinds("{p_X, set-number, default: {1}}")[1:4] == [
        ("parameter", "p_X"),
        ("punctuation", ","),
        ("type", "set-number"),
    ]
    assert [kind for kind, _ in kinds("{gG, oO, v_T, vP}")][1:-1:2] == [
        "table_group",
        "operation",
        "variable",
        "variable",
    ]
    assert kinds("null = false")[0] == ("null", "null")
    assert kinds("abs (1)")[0] == ("function", "abs")
    assert kinds("unknown(1)")[0] == ("identifier", "unknown")


def test_token_texts_are_source_slices() -> None:
    for expression in CORPUS.read_text(encoding="utf-8").splitlines():
        if not expression.strip() or expression.startswith("#"):
            continue
        tokens = tokenize(expression)
        assert tokens[-1] == Token("eof", "", len(expression), len(expression))
        for token in tokens:
            assert token.kind in TOKEN_KINDS
            assert expression[token.start : token.end] == token.text
        between = "".join(
            expression[previous.end : token.start]
            for previous, token in itertools.pairwise(tokens)
        )
        assert not between.strip(), "only whitespace lies between tokens"


@pytest.mark.parametrize("word", sorted(KEYWORDS))
def test_tokenizer_knows_every_keyword(word: str) -> None:
    token = tokenize(f"x {word.upper()} y")[1]
    assert token.kind == "keyword"
    assert " ".join(token.text.casefold().split()) == word


@pytest.mark.parametrize("word", sorted(WINDOW_KEYWORDS))
def test_tokenizer_knows_every_window_keyword(word: str) -> None:
    token = tokenize(f"sum(x over ({word}))")[5]
    assert (token.kind, token.text) == ("keyword", word)


@pytest.mark.parametrize("name", sorted(FUNCTIONS))
def test_tokenizer_knows_every_function(name: str) -> None:
    assert tokenize(f"{name}(x)")[0] == Token("function", name, 0, len(name))


@pytest.mark.parametrize("operator", sorted(OPERATORS))
def test_tokenizer_knows_every_operator(operator: str) -> None:
    assert tokenize(f"x {operator} y")[1] == Token(
        "operator", operator, 2, 2 + len(operator)
    )


@pytest.mark.parametrize("name", sorted(PARAMETER_TYPES))
def test_tokenizer_knows_every_parameter_type(name: str) -> None:
    assert tokenize(f"{{p_X, {name}}}")[3] == Token("type", name, 6, 6 + len(name))


def test_tokenizer_knows_selection_words_literals_and_prefixes() -> None:
    for word in SELECTION_KEYWORDS:
        assert tokenize(f"{{{word}: 1}}")[1].kind == "keyword"
    for word in LITERAL_WORDS:
        assert tokenize(word)[0].kind == ("null" if word == "null" else "boolean")
        assert tokenize(f"{{default: {word}}}")[3].kind == tokenize(word)[0].kind
    for prefix, kind in REFERENCE_PREFIXES.items():
        assert tokenize(f"{{{prefix}_X}}")[1].kind == kind
    for period in TIME_PERIODS:
        assert tokenize(f"time_shift(x, {period}, 1)")[4].kind == "period"


def test_textmate_grammar_is_in_step() -> None:
    path = ROOT / "editors" / "dpm-xl.tmLanguage.json"
    assert json.loads(path.read_text(encoding="utf-8")) == textmate_grammar(), (
        "regenerate editors/dpm-xl.tmLanguage.json (see README)"
    )


def test_syntax_errors_carry_a_range() -> None:
    with pytest.raises(DpmXlSyntaxError) as caught:
        parse("{tA, r0010} + then")
    error = caught.value
    assert (error.position, error.end) == (14, 18)
    assert error.pointer() == "{tA, r0010} + then\n              ^~~~"
    with pytest.raises(DpmXlSyntaxError) as caught:
        parse("{tA, x0010}")
    assert caught.value.expression[caught.value.position : caught.value.end] == "x0010"
    with pytest.raises(DpmXlSyntaxError) as caught:
        parse("{tA} >=")
    assert caught.value.pointer() == "{tA} >=\n       ^"


def test_pointer_marks_the_failing_line_only() -> None:
    error = DpmXlSyntaxError("bad", "a +\nbcd efg", 4, 20)
    assert error.pointer() == "bcd efg\n^~~~~~~"
    assert DpmXlSyntaxError("bad", "abc", 1).end == 2
