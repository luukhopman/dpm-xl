"""Command-line interface: ``dpm-xl check`` and ``dpm-xl eval``."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import InvalidOperation
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

from .ast import Item
from .evaluator import RuleResult, evaluate_rule
from .explain import explain
from .parser import DpmXlSyntaxError, parse_program
from .provider import CellKey, MemoryProvider, TableLayout
from .references import references
from .values import Number, Value, ValueSet

JSON_SCHEMA_VERSION = 1
"""Version of the ``--json`` output layout; it changes only with a new major."""

_DESCRIPTION = "Parse and evaluate EBA DPM-XL validation rules."
_EPILOG = """examples:
  dpm-xl check rules.json
  dpm-xl check "with {tC_01.00}: {r0010} >= 0" --references
  dpm-xl eval "{tC_01.00, r0010, c0010} >= 0" data.json
  dpm-xl eval rules.json data.json --json

A rule source is one expression, a text file with one expression per line
(# starts a comment), or a JSON list of objects with "code", "expression"
and an optional "precondition". Data file format:
https://luukhopman.github.io/dpm-xl/reference/data-formats/"""


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI.

    Returns:
        int: Process exit code: 0 when everything parsed or held, 1 when an
        expression did not parse or a rule failed, 3 for an evaluation error
        or unreadable input (argparse uses 2 for usage errors).
    """
    parser = argparse.ArgumentParser(
        prog="dpm-xl",
        description=_DESCRIPTION,
        epilog=_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {_version()}")
    commands = parser.add_subparsers(dest="command", required=True)
    check = commands.add_parser(
        "check", help="parse expressions and report syntax errors"
    )
    check.add_argument("source", help="an expression or a rule file")
    check.add_argument("--references", action="store_true", help="print selections")
    check.add_argument("--json", action="store_true", help="print JSON")
    run = commands.add_parser(
        "eval", help="evaluate rules against a JSON data file and explain failures"
    )
    run.add_argument("source", metavar="rules", help="an expression or a rule file")
    run.add_argument("data", type=Path, help="JSON data file (see --help)")
    run.add_argument(
        "--precondition",
        help="precondition for a single expression, such as {v_C_01.00}",
    )
    run.add_argument("--json", action="store_true", help="print JSON")
    arguments = parser.parse_args(argv)
    if arguments.command == "check":
        return _check(
            arguments.source,
            show_references=arguments.references,
            as_json=arguments.json,
        )
    return _evaluate(
        arguments.source,
        arguments.data,
        arguments.precondition,
        as_json=arguments.json,
    )


def _version() -> str:
    try:
        return version("dpm-xl")
    except PackageNotFoundError:  # pragma: no cover - running from a checkout
        return "unknown"


@dataclass(frozen=True, slots=True)
class _Rule:
    label: str
    expression: str
    precondition: str | None = None


def _rules(source: str) -> list[_Rule]:
    """Read rules from an expression or a rule file.

    Returns:
        list[_Rule]: The rules in file order.

    Raises:
        ValueError: If a JSON rule file is malformed.
    """
    path = Path(source)
    if not path.is_file():
        return [_Rule("expression", source)]
    text = path.read_text(encoding="utf-8")
    if path.suffix.casefold() != ".json":
        return [
            _Rule(f"line {number}", line)
            for number, line in enumerate(text.splitlines(), start=1)
            if line.strip() and not line.lstrip().startswith("#")
        ]
    entries = json.loads(text)
    if not isinstance(entries, list):
        raise ValueError("a JSON rule file must hold a list of rules")
    rules = []
    for index, entry in enumerate(entries, start=1):
        if not isinstance(entry, dict):
            raise ValueError(f"rule {index} is not a JSON object")
        expression, precondition = (
            value.get("expression") if isinstance(value, dict) else value
            for value in (entry.get("expression"), entry.get("precondition"))
        )
        if expression:
            rules.append(
                _Rule(str(entry.get("code", index)), expression, precondition or None)
            )
    return rules


def _expressions(rules: Iterable[_Rule]) -> Iterable[tuple[str, str]]:
    for rule in rules:
        if rule.label == "expression":
            yield "argument", rule.expression
            continue
        yield f"{rule.label}:expression", rule.expression
        if rule.precondition:
            yield f"{rule.label}:precondition", rule.precondition


def _check(source: str, *, show_references: bool, as_json: bool = False) -> int:
    try:
        rules = _rules(source)
    except (OSError, ValueError) as error:
        print(f"error: {source}: {error}", file=sys.stderr)
        return INVALID_INPUT
    total = 0
    errors: list[dict[str, Any]] = []
    selections: list[dict[str, str]] = []
    for label, expression in _expressions(rules):
        total += 1
        try:
            node = parse_program(expression)
        except DpmXlSyntaxError as error:
            errors.append(
                {"source": label, "message": error.message, "position": error.position}
            )
            if not as_json:
                print(f"{label}: {error.message}\n{error.pointer()}", file=sys.stderr)
            continue
        if show_references:
            for reference in references(node):
                selections.append({"source": label, "selection": reference.spec.text()})
                if not as_json:
                    print(f"{label}: {reference.spec.text()}")
    if as_json:
        document: dict[str, Any] = {
            "schema_version": JSON_SCHEMA_VERSION,
            "parsed": total - len(errors),
            "total": total,
        }
        document["errors"] = errors
        if show_references:
            document["selections"] = selections
        print(json.dumps(document, indent=2))
    else:
        print(f"{total - len(errors)}/{total} expressions parsed")
    return 1 if errors else 0


INVALID_INPUT = 3
"""Exit status for an evaluation error or unreadable input."""

_EXIT_CODES = {"passed": 0, "not_applicable": 0, "failed": 1}


def _evaluate(
    source: str,
    data_path: Path,
    precondition: str | None,
    *,
    as_json: bool = False,
) -> int:
    try:
        rules = _rules(source)
        document = json.loads(data_path.read_text(encoding="utf-8"))
        provider = load_memory_provider(document)
    except (OSError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return INVALID_INPUT
    if precondition and len(rules) == 1:
        rules = [_Rule(rules[0].label, rules[0].expression, precondition)]
    results = []
    for rule in rules:
        result = evaluate_rule(
            rule.expression, provider, precondition=rule.precondition
        )
        failures = []
        if result.evaluation is not None:
            for outcome in result.failures:
                explanation = explain(result.evaluation, rule.expression, outcome.key)
                failures.append(
                    {
                        "key": {
                            name: str(value) for name, value in outcome.key.items()
                        },
                        "summary": explanation.summary,
                        "cells": [point.label() for point in outcome.points],
                    }
                )
        results.append((rule, result, failures))
    if as_json:
        print(
            json.dumps(
                {
                    "schema_version": JSON_SCHEMA_VERSION,
                    "results": [
                        {
                            "rule": rule.label,
                            "expression": rule.expression,
                            "status": result.status,
                            "message": result.message,
                            "counts": result.counts,
                            "failures": failures,
                        }
                        for rule, result, failures in results
                    ],
                },
                indent=2,
            )
        )
    else:
        for rule, result, failures in results:
            _print_result(rule, result, failures, single=len(rules) == 1)
        if len(rules) > 1:
            statuses = Counter(result.status for _, result, _ in results)
            print(
                f"{len(rules)} rules: "
                + ", ".join(f"{count} {status}" for status, count in statuses.items())
            )
    return max(
        (_EXIT_CODES.get(result.status, INVALID_INPUT) for _, result, _ in results),
        default=0,
    )


def _print_result(
    rule: _Rule,
    result: RuleResult,
    failures: list[dict[str, Any]],
    *,
    single: bool,
) -> None:
    indent = "" if single else "  "
    if single:
        print(f"status: {result.status}")
    else:
        print(f"{rule.label}: {result.status}")
    if result.message:
        print(f"{indent}message: {result.message}")
    counts = result.counts
    print(
        f"{indent}records: {counts['passed']} passed, {counts['failed']} failed, "
        f"{counts['null']} not evaluated"
    )
    for failure in failures:
        key = ", ".join(f"{name}={value}" for name, value in failure["key"].items())
        print(f"{indent}- {key or 'scalar'}: {failure['summary']}")


def load_memory_provider(document: dict[str, Any]) -> MemoryProvider:
    """Build a [`MemoryProvider`][dpmxl.provider.MemoryProvider] from a JSON document.

    The document has ``tables`` (code, rows, columns, sheets, open_keys),
    ``facts`` (table, row, column, sheet, keys, value, decimals, type),
    ``reported`` template codes, ``parameters`` (a list is a set),
    ``table_groups`` (group code to table codes), ``operations``
    (operation code to expression) and ``earlier`` reports for
    ``time_shift`` (``period``, ``count`` and a nested ``data`` document).

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
        tables,
        values,
        reported=document.get("reported"),
        parameters=parameters,
        table_groups={
            code: tuple(group)
            for code, group in document.get("table_groups", {}).items()
        },
        operations=dict(document.get("operations", {})),
        earlier_reports={
            (entry["period"], int(entry["count"])): _memory_provider(entry["data"])
            for entry in document.get("earlier", ())
        },
    )


def _typed(
    value: Any, kind: str | None = None, decimals: int | str | None = None
) -> Value:
    if value is None:
        return None
    if isinstance(value, list):
        return ValueSet.of(_typed(member, kind) for member in value)
    if kind == "number" or (
        isinstance(value, int | float) and not isinstance(value, bool)
    ):
        try:
            number = Number.of(str(value), decimals)
        except InvalidOperation:
            raise ValueError(f"invalid number {value!r}") from None
        except ValueError as error:
            raise ValueError(f"invalid decimals {decimals!r}: {error}") from None
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
