"""Command-line entry point: ``dpm-xl check`` and ``dpm-xl eval``."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from collections.abc import Iterable, Sequence
from datetime import date
from decimal import InvalidOperation
from pathlib import Path
from typing import Any

from .ast import Item
from .evaluator import evaluate_rule
from .explain import explain
from .parser import DpmXlSyntaxError, parse
from .provider import CellKey, MemoryProvider, TableLayout
from .references import references
from .values import Number, Value


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI.

    Returns:
        int: Process exit code.
    """
    parser = argparse.ArgumentParser(prog="dpm-xl", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    check = commands.add_parser("check", help="parse expressions and report errors")
    check.add_argument(
        "source",
        help="an expression, a text file with one expression per line, or a JSON "
        "list of objects with an 'expression' field",
    )
    check.add_argument("--references", action="store_true", help="print selections")
    run = commands.add_parser("eval", help="evaluate one expression against JSON data")
    run.add_argument("expression")
    run.add_argument("data", type=Path, help="JSON data file (see README)")
    run.add_argument("--precondition")
    arguments = parser.parse_args(argv)
    if arguments.command == "check":
        return _check(arguments.source, show_references=arguments.references)
    return _evaluate(arguments.expression, arguments.data, arguments.precondition)


def _expressions(source: str) -> Iterable[tuple[str, str]]:
    path = Path(source)
    if not path.is_file():
        yield "argument", source
        return
    text = path.read_text(encoding="utf-8")
    if path.suffix.casefold() == ".json":
        for index, entry in enumerate(json.loads(text), start=1):
            for field in ("expression", "precondition"):
                value = entry.get(field)
                if isinstance(value, dict):
                    value = value.get("expression")
                if value:
                    yield f"{entry.get('code', index)}:{field}", value
        return
    for number, line in enumerate(text.splitlines(), start=1):
        if line.strip() and not line.lstrip().startswith("#"):
            yield f"line {number}", line


def _check(source: str, *, show_references: bool) -> int:
    total = 0
    errors: Counter[str] = Counter()
    for label, expression in _expressions(source):
        total += 1
        try:
            node = parse(expression)
        except DpmXlSyntaxError as error:
            errors[error.message] += 1
            print(f"{label}: {error.message}\n{error.pointer()}", file=sys.stderr)
            continue
        if show_references:
            for reference in references(node):
                print(f"{label}: {reference.spec.text()}")
    print(f"{total - sum(errors.values())}/{total} expressions parsed")
    return 1 if errors else 0


def _evaluate(expression: str, data_path: Path, precondition: str | None) -> int:
    try:
        document = json.loads(data_path.read_text(encoding="utf-8"))
        provider = load_memory_provider(document)
    except (OSError, ValueError) as error:
        print(f"error: {data_path}: {error}", file=sys.stderr)
        return 2
    result = evaluate_rule(expression, provider, precondition=precondition)
    print(f"status: {result.status}")
    if result.message:
        print(f"message: {result.message}")
    counts = result.counts
    print(
        f"records: {counts['passed']} passed, {counts['failed']} failed, "
        f"{counts['null']} not evaluated"
    )
    if result.evaluation is not None:
        for outcome in result.failures:
            explanation = explain(result.evaluation, expression, outcome.key)
            key = ", ".join(f"{name}={value}" for name, value in outcome.key.items())
            print(f"- {key or 'scalar'}: {explanation.summary}")
    return {"passed": 0, "not_applicable": 0, "failed": 1}.get(result.status, 2)


def load_memory_provider(document: dict[str, Any]) -> MemoryProvider:
    """Build a :class:`MemoryProvider` from a JSON document.

    The document has ``tables`` (code, rows, columns, sheets, open_keys),
    ``facts`` (table, row, column, sheet, keys, value, decimals, type),
    ``reported`` template codes and ``parameters``.

    Returns:
        MemoryProvider: The in-memory report.

    Raises:
        ValueError: For a malformed table, fact or parameter.
    """
    try:
        return _memory_provider(document)
    except (KeyError, TypeError, AttributeError) as error:
        raise ValueError(f"malformed data document ({error!r})") from error


def _memory_provider(document: dict[str, Any]) -> MemoryProvider:
    tables = [
        TableLayout(
            code=table["code"],
            rows=tuple(table.get("rows", ())),
            columns=tuple(table.get("columns", ())),
            sheets=tuple(table.get("sheets", ())),
            open_keys=tuple(table.get("open_keys", ())),
            template=table.get("template"),
        )
        for table in document.get("tables", ())
    ]
    values: dict[CellKey, Value] = {}
    for index, fact in enumerate(document.get("facts", ()), start=1):
        try:
            keys = tuple(
                (name, _typed(value)) for name, value in fact.get("keys", {}).items()
            )
            value = _typed(fact.get("value"), fact.get("type"), fact.get("decimals"))
        except ValueError as error:
            raise ValueError(f"fact {index}: {error}") from error
        values[
            fact["table"],
            fact.get("row"),
            fact.get("column"),
            fact.get("sheet"),
            keys,
        ] = value
    parameters = {
        name: _typed(value) for name, value in document.get("parameters", {}).items()
    }
    return MemoryProvider(
        tables, values, reported=document.get("reported"), parameters=parameters
    )


def _typed(
    value: Any, kind: str | None = None, decimals: int | str | None = None
) -> Value:
    if value is None:
        return None
    if kind == "number" or (
        isinstance(value, int | float) and not isinstance(value, bool)
    ):
        try:
            number = Number.of(str(value), decimals)
        except InvalidOperation:
            raise ValueError(f"invalid number {value!r}") from None
        except ValueError:
            raise ValueError(f"invalid decimals {decimals!r}") from None
        if not number.value.is_finite():
            raise ValueError(f"invalid number {value!r}")
        return number
    if kind == "item" or (isinstance(value, str) and value.startswith("[")):
        return Item.parse(str(value).strip("[]"))
    if kind == "date":
        return date.fromisoformat(str(value))
    return value


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
