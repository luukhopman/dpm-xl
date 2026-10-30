"""Command-line interface of dpm-xl.

The commands are ``check``, ``eval``, ``check-report``, ``list-modules``
and ``export-module``.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import xml.etree.ElementTree as ET  # ruff: ignore[suspicious-xml-etree-import] - writes XML, never parses it
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass, replace
from datetime import date
from importlib.metadata import PackageNotFoundError, version
from importlib.util import find_spec
from pathlib import Path
from typing import Any

from .diagnostics import LayoutLookup, diagnose
from .evaluator import RuleResult
from .explain import explain
from .module import FORMATS, MODULE_FORMAT, Module, load_module
from .parser import parse_program
from .provider import DataProvider, _table_layout, load_memory_provider
from .references import references
from .rules import Rule, RuleRun, evaluate_rules, load_rules, rules_from

_DATABASE_HELP = (
    "EBA DPM 2.0 database: SQLite, or the Access file with mdbtools on PATH"
)

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
  dpm-xl list-modules dpm.sqlite --release 4.3
  dpm-xl export-module dpm.sqlite COREP_OF --release 4.3 -o corep_of.json

A rule source is one expression, a text file with one expression per line
(# starts a comment), or a JSON list of objects with "code", "expression"
and optional "precondition", "severity", "active" and "modules". Data file
format: https://luukhopman.github.io/dpm-xl/reference/data-formats/

exit statuses:
  0  done; nothing failed at or above --fail-on
  1  an expression has an error (with --strict, also a warning), or a rule
     failed or is an error
  2  usage error
  3  unreadable or invalid input"""


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI.

    Returns:
        int: Process exit code: 0 when no expression has an error (with
        ``--strict``: nor a warning) or no rule at or above ``--fail-on``
        failed, 1 when one has (with ``--strict``: an error or a warning) or
        such a rule failed or is an error, 2 for a usage error and 3 for
        unreadable or invalid input.
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
        help="exit with status 1 for warnings too, such as syntax other "
        "DPM-XL engines may reject",
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
        help="check an XBRL report's filing rules and validation rules",
        description="Check an xBRL-CSV or XBRL-XML report: the EBA filing rules "
        "dpm-xbrl checks and the validation rules of its module file, in one report. "
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
        help="local taxonomy package: resolves xBRL-CSV metadata, places "
        "XBRL-XML facts and adds the filing rules that need the taxonomy "
        "(repeatable)",
    )
    report.add_argument(
        "--previous",
        action="append",
        default=[],
        type=Path,
        metavar="REPORT",
        help="report of the same module for an earlier period, which time_shift "
        "rules compare with (repeatable)",
    )
    listing = commands.add_parser(
        "list-modules",
        help="list the releases and modules of an EBA DPM 2.0 database",
        description="List the releases of an EBA DPM 2.0 database, and the "
        "modules of one release.",
    )
    listing.add_argument("database", type=Path, help=_DATABASE_HELP)
    listing.add_argument(
        "--release", help="release code, such as 4.3 (default: the latest)"
    )
    listing.add_argument("--json", action="store_true", help="print JSON")
    export = commands.add_parser(
        "export-module",
        help="write a module file for one module of an EBA DPM 2.0 database",
        description="Export one module of a release of an EBA DPM 2.0 database "
        "as a module file: its tables, cells, open keys and rules. Notes on "
        "the EBA data it corrects or leaves out go to standard error.",
    )
    export.add_argument("database", type=Path, help=_DATABASE_HELP)
    export.add_argument("module", help="module code, such as COREP_OF")
    export.add_argument(
        "--release", help="release code, such as 4.3 (default: the latest)"
    )
    export.add_argument(
        "-o",
        "--output",
        type=Path,
        metavar="FILE",
        help="file to write (default: standard output)",
    )
    export.add_argument(
        "--format",
        choices=FORMATS,
        default=MODULE_FORMAT,
        help="the file's format (default: %(default)s); dpm-synth 1.0 reads "
        "only dpm-synth-template/1, which dpm-xl reads too",
    )
    arguments = parser.parse_args(argv)
    if arguments.command == "list-modules":
        return _list_modules(
            arguments.database, arguments.release, as_json=arguments.json
        )
    if arguments.command == "export-module":
        return _export_module(
            arguments.database,
            arguments.module,
            arguments.release,
            output=arguments.output,
            document_format=arguments.format,
        )
    if arguments.command == "check-report":
        if find_spec("dpmxbrl") is None:
            report.error(
                'check-report needs the xbrl extra: pip install "dpm-xl[xbrl]"'
            )
        return _check_report(
            arguments.module,
            arguments.report,
            taxonomy_packages=arguments.taxonomy_package,
            previous=arguments.previous,
            output_format=arguments.format,
            fail_on=arguments.fail_on,
            show_all=arguments.show_all,
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
        show_all=arguments.show_all,
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
    command.add_argument(
        "--all",
        action="store_true",
        dest="show_all",
        help="in text output, list every rule, not only those that failed, "
        "are an error or are unsupported",
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
        if isinstance(document, list):
            return rules_from(document), None
    # load_rules reads other files, and reports what is wrong with this one.
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
    if counts["error"] or (strict and counts["warning"]):
        return EXIT_FAILED
    return EXIT_OK


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
"""Exit status when an expression has an error, or a rule fails or is an error."""
EXIT_USAGE = 2
"""Exit status of a usage error, such as an unknown option."""
EXIT_INPUT = 3
"""Exit status for unreadable or invalid input."""


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
    show_all: bool = False,
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
        _print_runs(runs, single=len(rules) == 1, show_all=show_all)
    return _exit_status(runs, failing)


def _suite_name(source: str) -> str:
    path = Path(source)
    return path.name if path.is_file() else "expression"


_SHOWN = frozenset({"failed", "error", "unsupported"})


def _print_runs(
    runs: Sequence[_Run], *, single: bool = False, show_all: bool = False
) -> None:
    """Print rule results, then a summary line.

    Without ``show_all``, only rules that failed, are an error or are
    unsupported are listed, so a large module's problems are not buried.
    """
    shown = [run for run in runs if single or show_all or run.status in _SHOWN]
    for run in shown:
        _print_run(run, single=single)
    if not single:
        statuses = Counter(run.status for run in runs)
        hidden = len(runs) - len(shown)
        note = f" ({hidden} not listed; --all lists every rule)" if hidden else ""
        print(
            f"{_plural(len(runs), 'rule')}: "
            + ", ".join(f"{count} {status}" for status, count in statuses.items())
            + note
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
    previous: Sequence[Path] = (),
    output_format: str = "text",
    fail_on: str = "error",
    show_all: bool = False,
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
        if report.format == "xbrl-xml" and not taxonomy_packages:
            print(
                f"error: {report_path}: an XBRL-XML report needs its taxonomy "
                "packages (--taxonomy-package) to place its facts in the module",
                file=sys.stderr,
            )
            return EXIT_INPUT
        earlier = [
            read_report(path, taxonomy_packages=taxonomy_packages) for path in previous
        ]
    except ReportError as error:  # its message names the file
        print(f"error: {error}", file=sys.stderr)
        return EXIT_INPUT
    try:
        provider = ReportProvider(
            module, report, previous=earlier, taxonomy_packages=taxonomy_packages
        )
    except (ReportError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return EXIT_INPUT
    runs = _run_rules(module.rules, provider, module.module)
    failing = _failing(fail_on)
    findings = [_finding_json(finding) for finding in report.filing]
    facts = [_finding_json(finding) for finding in provider.findings]
    unplaced = provider.unplaced
    if output_format == "json":
        errors = sum(1 for finding in report.filing if finding.severity == "error")
        document = _header() | {
            "summary": {
                "filing_errors": errors,
                "filing_warnings": len(report.filing) - errors,
                **_rules_summary(runs),
                "unplaced_facts": len(unplaced),
                "invalid_facts": len(provider.invalid),
            },
            "report": {
                "path": str(report_path),
                "format": report.format,
                "entry_point": report.entry_point,
                "entity_id": report.entity_id,
                "reference_date": _iso(report.reference_date),
                "previous": [
                    {
                        "path": str(path),
                        "reference_date": _iso(found.reference_date),
                    }
                    for path, found in zip(previous, earlier, strict=True)
                ],
            },
            "module": {"module": module.module, "release": module.release},
            "warnings": list(report.warnings),
            "filing_rules": findings,
            "fact_findings": facts,
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
        _junit_findings(suite, facts, failing, classname="dpm-xl.facts")
        _junit_rules(suite, runs, failing)
        print(_junit_text(suite))
    else:
        print(
            f"report: {report_path} ({report.format}); module {module.module}, "
            f"release {module.release}"
        )
        for path, found in zip(previous, earlier, strict=True):
            print(f"previous: {path} ({_iso(found.reference_date)})")
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
        for finding in facts:
            print(f"[{finding['severity']}] {finding['code']}: {finding['message']}")
            for example in finding["examples"]:
                print(f"  - {example}")
        _print_runs(runs, show_all=show_all)
    broken = any(finding["severity"] in failing for finding in [*findings, *facts])
    status = _exit_status(runs, failing)
    return EXIT_FAILED if broken and status == EXIT_OK else status


def _list_modules(database: Path, release: str | None, *, as_json: bool) -> int:
    from .dpm import DpmError, open_release

    try:
        with open_release(database) as db:
            releases = db.releases()
            chosen = db.release(release)
            modules = db.modules(chosen.code)
    except DpmError as error:
        print(f"error: {error}", file=sys.stderr)
        return EXIT_INPUT
    if as_json:
        document = _header() | {
            "releases": [asdict(found) for found in releases],
            "release": chosen.code,
            "modules": [asdict(module) for module in modules],
        }
        print(json.dumps(document, indent=2))
        return EXIT_OK
    print("releases: " + ", ".join(found.code for found in releases))
    print(f"modules of release {chosen.code}: {len(modules)}")
    width = max((len(module.code) for module in modules), default=0)
    for module in modules:
        print(
            f"  {module.code:<{width}}  {module.version or '-':<7}  "
            f"{module.name or ''}".rstrip()
        )
    return EXIT_OK


class _NoteHandler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        print(f"note: {record.getMessage()}", file=sys.stderr)


def _export_module(
    database: Path,
    module: str,
    release: str | None,
    *,
    output: Path | None,
    document_format: str,
) -> int:
    from .dpm import DpmError, export_module, open_release

    logger = logging.getLogger("dpmxl.dpm")
    handler = _NoteHandler()
    logger.addHandler(handler)
    propagate, logger.propagate = logger.propagate, False
    try:
        with open_release(database) as db:
            document = export_module(db, module, release, format=document_format)
    except DpmError as error:
        print(f"error: {error}", file=sys.stderr)
        return EXIT_INPUT
    finally:
        logger.removeHandler(handler)
        logger.propagate = propagate
    text = json.dumps(document, indent=1, ensure_ascii=False) + "\n"
    if output is None:
        sys.stdout.write(text)
        return EXIT_OK
    try:
        output.write_text(text, encoding="utf-8")
    except OSError as error:
        print(_problem(output, error), file=sys.stderr)
        return EXIT_INPUT
    tables = document["tables"]
    print(
        f"wrote {output}: module {document['module']}, release "
        f"{document['release']}: {_plural(len(tables), 'table')}, "
        f"{_plural(sum(len(table['cells']) for table in tables), 'cell')}, "
        f"{_plural(len(document['rules']), 'rule')}",
        file=sys.stderr,
    )
    return EXIT_OK


def _iso(moment: date | None) -> str | None:
    return moment.isoformat() if moment else None


def _finding_json(finding: Any) -> dict[str, Any]:
    rule = getattr(finding, "rule", None)  # None for dpm-xl's fact findings
    return {
        **({"rule": rule, "title": getattr(finding, "title", rule)} if rule else {}),
        "code": finding.code,
        "severity": finding.severity,
        "message": finding.message,
        "count": finding.count,
        "examples": list(finding.examples),
    }


def _junit_findings(
    suite: ET.Element,
    findings: Sequence[dict[str, Any]],
    failing: frozenset[str],
    *,
    classname: str = "dpm-xbrl.filing-rules",
) -> None:
    """Add one test case per broken filing rule, or fact finding, to a suite.

    A finding at a ``failing`` severity is a failure; others are listed in
    the test case's ``system-out``.
    """
    by_rule: dict[str, list[dict[str, Any]]] = {}
    for finding in findings:
        name = f"{finding['rule']} {finding['title']}" if "rule" in finding else None
        by_rule.setdefault(name or finding["code"], []).append(finding)
    for name, found in by_rule.items():
        case = ET.SubElement(suite, "testcase", classname=classname, name=name)
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
