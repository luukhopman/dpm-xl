import gzip
import json
from pathlib import Path

import pytest

from dpmxl import (
    DpmXlSyntaxError,
    diagnose,
    is_template_code,
    parse,
    parse_program,
    references,
)
from dpmxl.ast import Variable, walk

DATA = Path(__file__).parent / "data"
SAMPLE = [
    line
    for line in (DATA / "eba_expressions.txt").read_text(encoding="utf-8").splitlines()
    if line.strip() and not line.startswith("#")
]
CORPUS: dict[str, str] = json.loads(
    gzip.decompress((DATA / "eba_corpus.json.gz").read_bytes())
)

# Two EBA expressions have typos: one lacks a space before endif, one between
# or and not.
TYPOS = {
    "v7551_m": (
        "expected 'endif', found end of expression",
        "missing space: did you mean 'true endif'?",
    ),
    "v904909_m": (
        "expected 'then', found 'ornot'",
        "missing space: did you mean 'or not'?",
    ),
}


@pytest.mark.parametrize("expression", SAMPLE)
def test_eba_expression_parses(expression: str) -> None:
    node = parse(expression)
    for reference in references(node):
        assert reference.spec.table, reference.spec.text()


def test_every_eba_expression_parses_but_two_typos() -> None:
    assert len(CORPUS) == 14_174
    failed = {}
    for expression, code in CORPUS.items():
        try:
            parse_program(expression)
        except DpmXlSyntaxError as error:
            failed[code] = (error.message, expression)
    assert sorted(failed) == sorted(TYPOS)
    for code, (message, expression) in failed.items():
        expected, suggestion = TYPOS[code]
        assert message == expected
        (diagnostic,) = diagnose(expression, program=True)
        assert diagnostic.message == suggestion


def test_no_eba_expression_is_non_portable() -> None:
    # The non-portable warnings flag only leniencies the EBA does not use.
    flagged = {
        code: diagnostic.message
        for expression, code in CORPUS.items()
        for diagnostic in diagnose(expression, program=True)
        if diagnostic.code == "non-portable"
    }
    assert flagged == {}


def test_eba_variables_keep_their_meaning() -> None:
    # {v_X} names a template and {vReportingLevel} is the only parameter, so
    # reading both spellings as one variable changes no EBA verdict.
    names = {
        node.name
        for expression in CORPUS
        if "{v" in expression and (tree := _parsed(expression)) is not None
        for node in walk(tree)
        if isinstance(node, Variable)
    }
    assert {name for name in names if not is_template_code(name)} == {"ReportingLevel"}
    assert len(names) > 600


def _parsed(expression: str):
    try:
        return parse_program(expression)
    except DpmXlSyntaxError:
        return None
