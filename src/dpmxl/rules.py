"""Rule files: the rules a validation run evaluates, with their metadata.

A rule file is a JSON list of rule objects or a text file with one
expression per line, as the data formats reference describes.
[`load_rules`][dpmxl.rules.load_rules] reads either into
[`Rule`][dpmxl.rules.Rule] objects.

Examples:
    >>> rules = load_rules(
    ...     [
    ...         {"code": "v1", "expression": "{tT, r0010} > 0"},
    ...         {"code": "v2", "expression": "{tT, r0020} > 0",
    ...          "severity": "warning", "active": False},
    ...     ]
    ... )
    >>> [(rule.code, rule.severity, rule.active) for rule in rules]
    [('v1', 'error', True), ('v2', 'warning', False)]
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, TypeAlias

Severity: TypeAlias = Literal["error", "warning"]
"""How serious a rule's failure is: ``error`` blocks a report, ``warning`` not."""

SEVERITIES: tuple[Severity, ...] = ("error", "warning")
"""The rule severities, most serious first."""


class RuleFileError(ValueError):
    """A rule file or rule list that cannot be read.

    The message names the problem by its JSON path, such as
    ``[2].severity: expected "error" or "warning", got "fatal"``.
    """


@dataclass(frozen=True, slots=True)
class Rule:
    """One validation rule and its metadata.

    Attributes:
        code: The rule's label in results, such as ``v0001_m``.
        expression: The DPM-XL expression.
        precondition: An expression that must yield a true record for the
            rule to apply, or ``None``.
        severity: ``error`` (the default) or ``warning``; a failing warning
            does not fail a run unless asked to.
        active: Whether to evaluate the rule. Inactive rules, such as the
            ones the EBA has deactivated, are skipped.
        modules: The module codes the rule applies to, such as
            ``("COREP_OF",)``; empty for every module.
        source: Who defines the rule, such as ``eba``, or ``None``.
    """

    code: str
    expression: str
    precondition: str | None = None
    severity: Severity = "error"
    active: bool = True
    modules: tuple[str, ...] = ()
    source: str | None = None

    def applies_to(self, module: str | None) -> bool:
        """Return whether the rule applies to a module.

        Returns:
            bool: ``True`` when the rule names no modules, when ``module``
            is ``None``, or when it is one of them, ignoring case.

        Examples:
            >>> rule = Rule("v1", "true", modules=("COREP_OF",))
            >>> rule.applies_to("corep_of"), rule.applies_to("FINREP9")
            (True, False)
        """
        if not self.modules or module is None:
            return True
        folded = module.casefold()
        return any(code.casefold() == folded for code in self.modules)


def load_rules(source: str | os.PathLike[str] | Sequence[Any]) -> list[Rule]:
    """Read rules from a rule file or a list of rule objects.

    A ``.json`` file holds a list of rule objects; any other file holds one
    expression per line, where ``#`` starts a comment line and blank lines
    are ignored, each labelled ``line <n>``. A rule object has ``code``
    (default: its 1-based position), ``expression``, and optionally
    ``precondition``, ``severity`` (``error`` or ``warning``, default
    ``error``), ``active`` (default ``true``), ``modules`` (a list of module
    codes) and ``source``. ``expression`` and ``precondition`` may be
    objects with an ``expression`` field, as some exports nest them. An
    object without an expression is left out; other fields are ignored.

    Args:
        source: The path of a rule file, or the rule objects themselves.

    Returns:
        list[Rule]: The rules in source order.

    Raises:
        RuleFileError: For a malformed rule, naming it by its JSON path.
        OSError: If the file cannot be read.
    """
    if isinstance(source, str | os.PathLike):
        path = Path(source)
        text = path.read_text(encoding="utf-8")
        if path.suffix.casefold() != ".json":
            return [
                Rule(f"line {number}", line)
                for number, line in enumerate(text.splitlines(), start=1)
                if line.strip() and not line.lstrip().startswith("#")
            ]
        try:
            entries = json.loads(text)
        except json.JSONDecodeError as error:
            raise RuleFileError(f"not JSON: {error}") from None
        if not isinstance(entries, list):
            raise RuleFileError(
                "a JSON rule file must hold a list of rules, got " + _describe(entries)
            )
        return rules_from(entries)
    return rules_from(source)


def rules_from(entries: Sequence[Any], path: str = "") -> list[Rule]:
    """Read rule objects, such as the ``rules`` of a JSON document.

    Args:
        entries: The rule objects, as [`load_rules`][dpmxl.rules.load_rules]
            describes them.
        path: The JSON path of ``entries`` for error messages, such as
            ``rules``.

    Returns:
        list[Rule]: The rules in order; objects without an expression are
        left out.

    Raises:
        RuleFileError: For a malformed rule, naming it by its JSON path.
    """
    rules = []
    for index, entry in enumerate(entries):
        where = f"{path}[{index}]"
        if not isinstance(entry, Mapping):
            raise RuleFileError(f"{where}: expected an object, got {_describe(entry)}")
        expression = _expression(entry, "expression", where)
        if not expression:
            continue
        code = entry.get("code", index + 1)
        if isinstance(code, bool) or not isinstance(code, str | int):
            raise RuleFileError(
                f"{where}.code: expected a string, got {_describe(code)}"
            )
        severity = entry.get("severity", "error")
        if severity is None:
            severity = "error"
        if severity not in SEVERITIES:
            raise RuleFileError(
                f'{where}.severity: expected "error" or "warning", got '
                + _describe(severity)
            )
        active = entry.get("active", True)
        if active is None:
            active = True
        if not isinstance(active, bool):
            raise RuleFileError(
                f"{where}.active: expected true or false, got {_describe(active)}"
            )
        modules = entry.get("modules") or ()
        if not isinstance(modules, list | tuple) or not all(
            isinstance(module, str) and module for module in modules
        ):
            raise RuleFileError(
                f"{where}.modules: expected a list of module codes, got "
                + _describe(modules)
            )
        source = entry.get("source")
        if source is not None and not isinstance(source, str):
            raise RuleFileError(
                f"{where}.source: expected a string, got {_describe(source)}"
            )
        rules.append(
            Rule(
                str(code),
                expression,
                _expression(entry, "precondition", where) or None,
                severity,
                active,
                tuple(modules),
                source,
            )
        )
    return rules


def _expression(entry: Mapping[str, Any], field: str, where: str) -> str | None:
    value = entry.get(field)
    if isinstance(value, Mapping):
        value = value.get("expression")
        field = f"{field}.expression"
    if value is not None and not isinstance(value, str):
        raise RuleFileError(
            f"{where}.{field}: expected a string, got {_describe(value)}"
        )
    return value


def _describe(value: Any) -> str:
    """Describe a JSON value for an error message.

    Returns:
        str: Such as ``the number 3`` or ``"fatal"``.
    """
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return json.dumps(value)
    if isinstance(value, int | float):
        return f"the number {value}"
    if isinstance(value, Mapping):
        return "an object"
    if isinstance(value, list | tuple):
        return "a list"
    return type(value).__name__


__all__ = [
    "SEVERITIES",
    "Rule",
    "RuleFileError",
    "Severity",
    "load_rules",
    "rules_from",
]
