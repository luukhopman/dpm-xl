from pathlib import Path

import pytest

from dpmxl import parse, references

CORPUS = Path(__file__).parent / "data" / "eba_expressions.txt"
EXPRESSIONS = [
    line
    for line in CORPUS.read_text(encoding="utf-8").splitlines()
    if line.strip() and not line.startswith("#")
]


@pytest.mark.parametrize("expression", EXPRESSIONS)
def test_eba_expression_parses(expression: str) -> None:
    node = parse(expression)
    for reference in references(node):
        assert reference.spec.table, reference.spec.text()
