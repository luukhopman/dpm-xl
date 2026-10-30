"""Command-line interface: ``dpm-xl check``, ``eval`` and ``check-report``."""

from __future__ import annotations

import argparse
import json
import sys
import xml.etree.ElementTree as ET  # ruff: ignore[suspicious-xml-etree-import] - writes XML, never parses it
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass, replace
from importlib.metadata import PackageNotFoundError, version
from importlib.util import find_spec
from pathlib import Path
from typing import Any

from .diagnostics import LayoutLookup, diagnose
from .evaluator import RuleResult
from .explain import explain
from .module import Module, load_module
from .parser import parse_program
from .provider import DataProvider, _table_layout, load_memory_provider
from .references import references
from .rules import Rule, RuleRun, evaluate_rules, load_rules

JSON_SCHEMA_VERSION = 2
"""Version of the ``--json`` output layout; it changes only with a new major."""

_DESCRIPTION = "Parse and evaluate EBA DPM-XL validation rules."
_EPILOG = """examples:
  dpm-xl check rules.json
  dpm-xl check rules.json --layouts data.json
  dpm-xl check "with {tC_01.00}: {r0010} >= 0" --references
  dpm-xl eval "{tC_01.00, r0010, c0010} >= 0" data.json
  dpm-xl eval rules.json data.json --json
  dpm-xl eval rules.json data.json --format junit --fail-on warning
  dpm-xl check-report module.json report.zip --format junit

A rule source is one expression, a text file with one expression per line
(# starts a comment), or a JSON list of objects with "code", "expression"
and optional "precondition", "severity", "active" and "modules". Data file
format: https://luukhopman.github.io/dpm-xl/reference/data-formats/

exit statuses:
  0  done; nothing failed at or above --fail-on
  1  an expression does not parse, or a rule failed or is an error
  2  usage error
  3  unreadable or invalid input"""


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI.

    Returns:
        int: Process exit code: 0 when everything parsed (with ``--strict``:
        had no errors) or no rule at or above ``--fail-on`` failed, 1 when an
        expression did not parse (with ``--strict``: had an error) or such a
        rule failed or is an error, 2 for a usage error and 3 for unreadable
        or invalid input.
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
        "check", help="report syntax errors and other problems in expressions"
    )
    check.add_argument("source", help="an expression or a rule file")
    check.add_argument(
        "--layouts",
        type=Path,
        metavar="DATA",
        help="JSON data file whose tables and parameters to check against",
    )
    check.add_argument(
        "--strict",
        action="store_true",
        help="exit with status 1 for any error, not only syntax errors",
    )
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
    _output_options(run)
    report = commands.add_parser(
        "check-report",
        help="check an XBRL report's filing rules and its module's rules",
        description="Check an xBRL-CSV or XBRL-XML report: the EBA filing rules "
        "dpm-xbrl checks and the rules of its module file, in one report. "
        'Needs the xbrl extra: pip install "dpm-xl[xbrl]".',
    )
    report.add_argument("module", type=Path, help="module file (dpm-module/1)")
    report.add_argument(
        "report", type=Path, help="xBRL-CSV package or XBRL-XML instance"
    )
    _output_options(report)
    report.add_argument(
        "--taxonomy-package",
        action="append",
        default=[],
        type=Path,
        metavar="ZIP",
        help="local taxonomy package: resolves xBRL-CSV metadata and adds the "
        "filing rules that need the taxonomy (repeatable)",
    )
    arguments = parser.parse_args(argv)
    if arguments.command == "check-report":
        if find_spec("dpmxbrl") is None:
            report.error(
                'check-report needs the xbrl extra: pip install "dpm-xl[xbrl]"'
            )
        return _check_report(
            arguments.module,
            arguments.report,
            taxonomy_packages=arguments.taxonomy_package,
            output_format=arguments.format,
            fail_on=arguments.fail_on,
        )
    if arguments.command == "check":
        return _check(
            arguments.source,
            show_references=arguments.references,
            as_json=arguments.json,
            layouts=arguments.layouts,
            strict=arguments.strict,
        )
    return _evaluate(
        arguments.source,
        arguments.data,
        arguments.precondition,
        output_format=arguments.format,
        fail_on=arguments.fail_on,
    )


def _output_options(command: argparse.ArgumentParser) -> None:
    command.add_argument(
        "--format",
        choices=("text", "json", "junit"),
        default="text",
        help="output format (default: text)",
    )
    command.add_argument(
        "--json",
        action="store_const",
        const="json",
        dest="format",
        help="print JSON; short for --format json",
    )
    command.add_argument(
        "--fail-on",
        choices=("error", "warning"),
        default="error",
        help="exit with status 1 when a rule or finding of this severity or "
        "worse fails (default: error)",
    )


def _version() -> str:
    try:
        return version("dpm-xl")
    except PackageNotFoundError:  # pragma: no cover - running from a checkout
        return "unknown"


_RULE_FILE_SUFFIXES = frozenset({".json", ".txt"})


def _looks_like_path(source: str) -> bool:
    """Tell a mistyped rule file path from an expression.

    Returns:
        bool: Whether ``source`` reads as a path rather than an expression.
    """
    if Path(source).suffix.casefold() in _RULE_FILE_SUFFIXES:
        return True
    return ("/" in source or "\\" in source) and not any(
        char in source for char in "{}()[]=<> "
    )


def _rules(source: str) -> list[Rule]:
    """Read rules from an expression, a rule file or a module file.

    Returns:
        list[Rule]: The rules in file order.
    """
    return _source(source)[0]


def _source(source: str) -> tuple[list[Rule], Module | None]:
    """Read the rules of a rule source, and the module of a module file.

    Returns:
        tuple: The rules in file order, and the module of a module file
        (a JSON object with a ``format``), else ``None``.

    Raises:
        FileNotFoundError: If the source names a file that does not exist.
    """
    path = Path(source)
    if not path.is_file():
        if _looks_like_path(source):
            raise FileNotFoundError("no such rule file")
        return [Rule("expression", source)], None
    if path.suffix.casefold() == ".json":
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            document = None
        if isinstance(document, dict) and "format" in document:
            module = load_module(document)
            return list(module.rules), module
    return load_rules(path), None


def _problem(path: object, error: Exception) -> str:
    """Describe unreadable or invalid input as ``error: PATH: reason``.

    Returns:
        str: The message.
    """
    reason = str(error)
    if isinstance(error, OSError) and not isinstance(error, FileNotFoundError):
        reason = f"cannot read: {error.strerror or error}"
    elif isinstance(error, FileNotFoundError) and error.filename is not None:
        reason = "no such file"
    elif isinstance(error, json.JSONDecodeError):
        reason = f"not JSON: {error}"
    return f"error: {path}: {reason}"


def _expressions(rules: Iterable[Rule]) -> Iterable[tuple[str, str]]:
    for rule in rules:
        if rule.code == "expression":
            yield "expression", rule.expression
            continue
        yield f"{rule.code}:expression", rule.expression
        if rule.precondition:
            yield f"{rule.code}:precondition", rule.precondition


def _check(
    source: str,
    *,
    show_references: bool,
    as_json: bool = False,
    layouts: Path | None = None,
    strict: bool = False,
) -> int:
    try:
        rules, module = _source(source)
    except (OSError, ValueError) as error:
        print(_problem(source, error), file=sys.stderr)
        return EXIT_INPUT
    skipped = [rule.code for rule in rules if not rule.active]
    rules = [rule for rule in rules if rule.active]
    try:
        lookup, tables, parameters = _layouts(layouts)
    except (OSError, ValueError) as error:
        print(_problem(layouts, error), file=sys.stderr)
        return EXIT_INPUT
    if module is not None and layouts is None:
        by_code = {layout.code: layout for layout in module.layouts()}
        lookup, tables = by_code.get, tuple(by_code)
    total = 0
    unparsed = 0
    errors: list[dict[str, Any]] = []
    found: list[dict[str, Any]] = []
    selections: list[dict[str, str]] = []
    counts: Counter[str] = Counter()
    for label, expression in _expressions(rules):
        total += 1
        diagnostics = diagnose(
            expression, lookup, tables=tables, parameters=parameters, program=True
        )
        syntax = [item for item in diagnostics if item.code == "syntax"]
        unparsed += bool(syntax)
        errors.extend(
            {
                "source": label,
                "message": item.message,
                "position": item.start,
                "end": item.end,
            }
            for item in syntax
        )
        for item in diagnostics:
            counts[item.severity] += 1
            found.append({"source": label, **asdict(item)})
            if not as_json:
                print(
                    f"{label}: {item.severity}: {item.message}\n"
                    f"{item.pointer(expression)}",
                    file=sys.stderr,
                )
        if show_references and not syntax:
            for reference in references(parse_program(expression)):
                selections.append({"source": label, "selection": reference.spec.text()})
                if not as_json:
                    print(f"{label}: {reference.spec.text()}")
    if as_json:
        document: dict[str, Any] = _header() | {
            "summary": {
                "total": total,
                "parsed": total - unparsed,
                "errors": counts["error"],
                "warnings": counts["warning"],
                "skipped": len(skipped),
            },
            "skipped": skipped,
        }
        document["errors"] = errors
        document["diagnostics"] = found
        if show_references:
            document["selections"] = selections
        print(json.dumps(document, indent=2))
    else:
        problems = [
            f"{counts[severity]} {severity}{'' if counts[severity] == 1 else 's'}"
            for severity in ("error", "warning")
            if counts[severity]
        ]
        notes = [" and ".join(problems)] if problems else []
        if skipped:
            notes.append(f"{_plural(len(skipped), 'inactive rule')} skipped")
        print(
            f"{total - unparsed}/{total} expressions parsed"
            + "".join(f"; {note}" for note in notes)
        )
    if strict:
        return EXIT_FAILED if counts["error"] else EXIT_OK
    return EXIT_FAILED if unparsed else EXIT_OK


def _plural(count: int, noun: str) -> str:
    return f"{count} {noun}{'' if count == 1 else 's'}"


def _layouts(
    path: Path | None,
) -> tuple[LayoutLookup | None, tuple[str, ...] | None, tuple[str, ...] | None]:
    """Read the tables and parameter names ``check --layouts`` checks against.

    Returns:
        tuple: A layout lookup, the table codes and the parameter names;
        ``None`` each without a data file.

    Raises:
        ValueError: For a malformed data file.
    """
    if path is None:
        return None, None, None
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise ValueError("a data file must hold a JSON object")
    try:
        tables = map(_table_layout, document.get("tables", ()))
        layouts = {table.code: table for table in tables}
        parameters = tuple(document.get("parameters", {}))
    except (KeyError, TypeError, AttributeError) as error:
        raise ValueError(f"malformed data document ({error!r})") from error
    return layouts.get, tuple(layouts), parameters


EXIT_OK = 0
"""Exit status when nothing fails at or above the ``--fail-on`` severity."""
EXIT_FAILED = 1
"""Exit status when an expression does not parse or a rule fails."""
EXIT_USAGE = 2
"""Exit status of a usage error, such as an unknown option."""
EXIT_INPUT = 3
"""Exit status for unreadable or invalid input, or a rule that is an error."""


@dataclass(frozen=True, slots=True)
class _Run:
    """One rule's run and the explanation of each failing record."""

    run: RuleRun
    failures: list[dict[str, Any]]

    @property
    def rule(self) -> Rule:
        return self.run.rule

    @property
    def result(self) -> RuleResult | None:
        return self.run.result

    @property
    def status(self) -> str:
        return self.run.status

    @property
    def message(self) -> str | None:
        return self.run.message


def _run_rules(
    rules: Sequence[Rule], provider: DataProvider, module: str | None = None
) -> list[_Run]:
    """Evaluate active rules and explain every failing record.

    Returns:
        list[_Run]: One run per rule, in order; inactive rules and rules
        for other modules are skipped.
    """
    return [_explained(run) for run in evaluate_rules(rules, provider, module=module)]


def _explained(run: RuleRun) -> _Run:
    failures = []
    result = run.result
    if result is not None and result.evaluation is not None:
        for outcome in result.failures:
            explanation = explain(result.evaluation, run.rule.expression, outcome.key)
            failures.append(
                {
                    "key": {name: str(value) for name, value in outcome.key.items()},
                    "summary": explanation.summary,
                    "cells": [point.label() for point in outcome.points],
                }
            )
    return _Run(run, failures)


_NO_RECORDS = {"passed": 0, "failed": 0, "null": 0}


def _run_json(run: _Run) -> dict[str, Any]:
    rule = run.rule
    return {
        "rule": rule.code,
        "expression": rule.expression,
        "severity": rule.severity,
        "active": rule.active,
        "modules": list(rule.modules),
        "status": run.status,
        "message": run.message,
        "counts": run.result.counts if run.result else dict(_NO_RECORDS),
        "failures": run.failures,
    }


_STATUSES = ("passed", "failed", "not_applicable", "error", "unsupported", "skipped")


def _rules_summary(runs: Sequence[_Run]) -> dict[str, int]:
    statuses = Counter(run.status for run in runs)
    return {"rules": len(runs)} | {status: statuses[status] for status in _STATUSES}


def _header() -> dict[str, Any]:
    return {
        "schema_version": JSON_SCHEMA_VERSION,
        "tool": "dpm-xl",
        "version": _version(),
    }


def _failing(fail_on: str) -> frozenset[str]:
    """Return the severities that ``--fail-on`` fails on.

    Returns:
        frozenset[str]: ``error`` alone, or both severities for ``warning``.
    """
    return frozenset({"error"} if fail_on == "error" else {"error", "warning"})


def _exit_status(runs: Sequence[_Run], failing: frozenset[str]) -> int:
    """Return the exit status of a rule run.

    Returns:
        int: 1 when a rule of a ``failing`` severity failed or is an
        ``error``, else 0. An ``unsupported`` rule does not count.
    """
    if any(
        run.status in {"failed", "error"} and run.rule.severity in failing
        for run in runs
    ):
        return EXIT_FAILED
    return EXIT_OK


def _evaluate(
    source: str,
    data_path: Path,
    precondition: str | None,
    *,
    output_format: str = "text",
    fail_on: str = "error",
) -> int:
    try:
        rules = _rules(source)
    except (OSError, ValueError) as error:
        print(_problem(source, error), file=sys.stderr)
        return EXIT_INPUT
    try:
        document = json.loads(data_path.read_text(encoding="utf-8"))
        if not isinstance(document, dict):
            raise ValueError("a data file must hold a JSON object")
        provider = load_memory_provider(document)
    except (OSError, ValueError) as error:
        print(_problem(data_path, error), file=sys.stderr)
        return EXIT_INPUT
    if precondition and len(rules) == 1:
        rules = [replace(rules[0], precondition=precondition)]
    runs = _run_rules(rules, provider)
    failing = _failing(fail_on)
    if output_format == "json":
        document = _header() | {
            "summary": _rules_summary(runs),
            "results": [_run_json(run) for run in runs],
        }
        print(json.dumps(document, indent=2))
    elif output_format == "junit":
        suite = _junit_suite(_suite_name(source))
        _junit_rules(suite, runs, failing)
        print(_junit_text(suite))
    else:
        _print_runs(runs, single=len(rules) == 1)
    return _exit_status(runs, failing)


def _suite_name(source: str) -> str:
    path = Path(source)
    return path.name if path.is_file() else "expression"


def _print_runs(runs: Sequence[_Run], *, single: bool = False) -> None:
    for run in runs:
        _print_run(run, single=single)
    if not single:
        statuses = Counter(run.status for run in runs)
        print(
            f"{_plural(len(runs), 'rule')}: "
            + ", ".join(f"{count} {status}" for status, count in statuses.items())
        )


def _print_run(run: _Run, *, single: bool) -> None:
    indent = "" if single else "  "
    if run.result is None:
        print(f"{run.rule.code}: skipped ({run.message})")
        return
    if single:
        print(f"status: {run.status}")
    else:
        severity = " (warning)" if run.rule.severity == "warning" else ""
        print(f"{run.rule.code}: {run.status}{severity}")
    if run.message:
        print(f"{indent}message: {run.message}")
    counts = run.result.counts
    print(
        f"{indent}records: {counts['passed']} passed, {counts['failed']} failed, "
        f"{counts['null']} null"
    )
    for failure in run.failures:
        key = ", ".join(f"{name}={value}" for name, value in failure["key"].items())
        print(f"{indent}- {key or 'scalar'}: {failure['summary']}")


def _junit_suite(name: str) -> ET.Element:
    suite = ET.Element("testsuite", name=name)
    properties = ET.SubElement(suite, "properties")
    for key, value in (("tool", "dpm-xl"), ("version", _version())):
        ET.SubElement(properties, "property", name=key, value=value)
    for counter in ("tests", "failures", "errors", "skipped"):
        suite.set(counter, "0")
    return suite


def _count(suite: ET.Element, counter: str) -> None:
    suite.set(counter, str(int(suite.get(counter, "0")) + 1))


def _junit_rules(
    suite: ET.Element, runs: Sequence[_Run], failing: frozenset[str]
) -> None:
    """Add one test case per rule to a JUnit test suite.

    A failed rule of a ``failing`` severity is a failure, a rule that is
    ``error`` an error, and a skipped, not applicable or ``unsupported``
    rule, which was not checked, is skipped; a failed rule below the
    threshold passes with its failures in ``system-out``.
    """
    for run in runs:
        case = ET.SubElement(
            suite, "testcase", classname="dpm-xl.rules", name=run.rule.code
        )
        _count(suite, "tests")
        lines = "\n".join(
            f"{', '.join(f'{k}={v}' for k, v in failure['key'].items()) or 'scalar'}: "
            f"{failure['summary']}"
            for failure in run.failures
        )
        if run.status == "error":
            _count(suite, "errors")
            ET.SubElement(
                case, "error", message=run.message or run.status, type=run.status
            )
        elif run.status == "failed" and run.rule.severity in failing:
            _count(suite, "failures")
            failure = ET.SubElement(
                case,
                "failure",
                message=f"{_plural(len(run.failures), 'failing record')}",
                type=run.rule.severity,
            )
            failure.text = lines
        elif run.status == "failed":
            ET.SubElement(case, "system-out").text = (
                f"{_plural(len(run.failures), 'failing record')} "
                f"[{run.rule.severity}]\n{lines}"
            )
        elif run.status in {"skipped", "not_applicable", "unsupported"}:
            _count(suite, "skipped")
            ET.SubElement(
                case, "skipped", message=run.message or run.status.replace("_", " ")
            )


def _junit_text(suite: ET.Element) -> str:
    ET.indent(suite)
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(
        suite, encoding="unicode"
    )


def _check_report(
    module_path: Path,
    report_path: Path,
    *,
    taxonomy_packages: Sequence[Path] = (),
    output_format: str = "text",
    fail_on: str = "error",
) -> int:
    # The xbrl extra: imported only for this command.
    from dpmxbrl import ReportError, read_report

    from .xbrl import ReportProvider

    try:
        module = load_module(module_path)
    except (OSError, ValueError) as error:
        print(_problem(module_path, error), file=sys.stderr)
        return EXIT_INPUT
    try:
        report = read_report(report_path, taxonomy_packages=taxonomy_packages)
    except ReportError as error:  # its message names the file
        print(f"error: {error}", file=sys.stderr)
        return EXIT_INPUT
    provider = ReportProvider(module, report)
    runs = _run_rules(module.rules, provider, module.module)
    failing = _failing(fail_on)
    findings = [_finding_json(finding) for finding in report.filing]
    unplaced = provider.unplaced
    if output_format == "json":
        errors = sum(1 for finding in report.filing if finding.severity == "error")
        document = _header() | {
            "summary": {
                "filing_errors": errors,
                "filing_warnings": len(report.filing) - errors,
                **_rules_summary(runs),
                "unplaced_facts": len(unplaced),
            },
            "report": {
                "path": str(report_path),
                "format": report.format,
                "entry_point": report.entry_point,
                "entity_id": report.entity_id,
                "reference_date": (
                    report.reference_date.isoformat() if report.reference_date else None
                ),
            },
            "module": {"module": module.module, "release": module.release},
            "warnings": list(report.warnings),
            "filing_rules": findings,
            "results": [_run_json(run) for run in runs],
            "unplaced": [
                {
                    "template": fact.template,
                    "datapoint": fact.datapoint,
                    "location": fact.location,
                }
                for fact in unplaced
            ],
        }
        print(json.dumps(document, indent=2, ensure_ascii=False))
    elif output_format == "junit":
        suite = _junit_suite(report_path.name)
        _junit_findings(suite, findings, failing)
        _junit_rules(suite, runs, failing)
        print(_junit_text(suite))
    else:
        print(
            f"report: {report_path} ({report.format}); module {module.module}, "
            f"release {module.release}"
        )
        for warning in report.warnings:
            print(f"warning: {warning}")
        errors = sum(1 for finding in findings if finding["severity"] == "error")
        print(
            f"filing rules broken: {_plural(errors, 'error')}, "
            f"{_plural(len(findings) - errors, 'warning')}"
        )
        for finding in findings:
            times = f" ({finding['count']} times)" if finding["count"] > 1 else ""
            print(
                f"  - [{finding['severity']}] {finding['rule']} "
                f"{finding['message']}{times}"
            )
        _print_runs(runs)
        if unplaced:
            example = unplaced[0].location or unplaced[0].datapoint
            print(
                f"{_plural(len(unplaced), 'fact')} in no table of module "
                f"{module.module}, such as {example}"
            )
    broken = any(finding["severity"] in failing for finding in findings)
    status = _exit_status(runs, failing)
    return EXIT_FAILED if broken and status == EXIT_OK else status


def _finding_json(finding: Any) -> dict[str, Any]:
    return {
        "rule": finding.rule,
        "title": getattr(finding, "title", finding.rule),
        "code": finding.code,
        "severity": finding.severity,
        "message": finding.message,
        "count": finding.count,
        "examples": list(finding.examples),
    }


def _junit_findings(
    suite: ET.Element, findings: Sequence[dict[str, Any]], failing: frozenset[str]
) -> None:
    """Add one test case per broken filing rule to a JUnit test suite.

    A finding at a ``failing`` severity is a failure; others are listed in
    the test case's ``system-out``.
    """
    by_rule: dict[str, list[dict[str, Any]]] = {}
    for finding in findings:
        by_rule.setdefault(finding["rule"], []).append(finding)
    for rule, found in by_rule.items():
        case = ET.SubElement(
            suite,
            "testcase",
            classname="dpm-xbrl.filing-rules",
            name=f"{rule} {found[0]['title']}",
        )
        _count(suite, "tests")
        lines = "\n".join(
            f"[{finding['severity']}] {finding['code']}: {finding['message']}"
            for finding in found
        )
        if any(finding["severity"] in failing for finding in found):
            _count(suite, "failures")
            failure = ET.SubElement(
                case,
                "failure",
                message="; ".join(finding["message"] for finding in found),
                type=", ".join(finding["code"] for finding in found),
            )
            failure.text = lines
        else:
            ET.SubElement(case, "system-out").text = lines


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


__all__ = [
    "EXIT_FAILED",
    "EXIT_INPUT",
    "EXIT_OK",
    "EXIT_USAGE",
    "JSON_SCHEMA_VERSION",
    "main",
]
