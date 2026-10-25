"""Static diagnostics: positioned problems in an expression, for editors.

[`diagnose`][dpmxl.diagnostics.diagnose] reports what can be found without
report data. On its own it finds every syntax error, unknown functions,
calls with the wrong operands and selections without a table. Given table
layouts it also checks tables, rows, columns and sheets, open-table keys
and, when the layouts carry cell data types, operands of the wrong type.
Given the report parameters, it also reports names that resolve to nothing.
"""

from __future__ import annotations

import difflib
import re
from collections.abc import Callable, Iterable, Iterator, Sequence
from dataclasses import dataclass, field, replace
from typing import Literal

from .ast import (
    Analytic,
    Assignment,
    AxisSelector,
    Binary,
    Call,
    Get,
    If,
    In,
    Literal_,
    Name,
    Node,
    Program,
    Rename,
    Selection,
    SelectionSpec,
    SetLiteral,
    Sub,
    TableReported,
    TypedParameter,
    Unary,
    Where,
    With,
    children,
)
from .grammar import CALL_NAMES, KEYWORDS, LITERAL_WORDS, SIGNATURES
from .parser import DpmXlSyntaxError, Token, _parse_recovering, _pointer, tokenize
from .provider import TableLayout, axis_matcher
from .recordset import STANDARD_KEYS, resolve_key

Severity = Literal["error", "warning"]
"""``error`` or ``warning``; see [`Diagnostic`][dpmxl.diagnostics.Diagnostic]."""

LayoutLookup = Callable[[str], TableLayout | None]
"""Returns a table's [`TableLayout`][dpmxl.provider.TableLayout], or ``None``
for a table that does not exist, such as ``layouts.get`` for a dict."""

DIAGNOSTIC_CODES = frozenset(
    {
        "syntax",
        "unknown-function",
        "operand-count",
        "group-by",
        "key-operand",
        "missing-table",
        "unknown-table",
        "unknown-row",
        "unknown-column",
        "unknown-sheet",
        "missing-row",
        "missing-column",
        "missing-sheet",
        "open-row",
        "open-column",
        "open-sheet",
        "empty-range",
        "type-mismatch",
        "unknown-key",
        "unknown-name",
    }
)
"""Every [`Diagnostic.code`][dpmxl.diagnostics.Diagnostic]. Codes are stable;
messages may be reworded in minor releases."""


@dataclass(frozen=True, slots=True)
class Diagnostic:
    """One problem in an expression, with the source text it concerns.

    Attributes:
        severity: ``error`` when evaluation would fail or select nothing as
            written; ``warning`` when the expression evaluates but probably
            does not mean what it says.
        code: A stable identifier from
            [`DIAGNOSTIC_CODES`][dpmxl.diagnostics.DIAGNOSTIC_CODES]:

            * ``syntax``: the text does not parse;
            * ``unknown-function``; ``operand-count`` and ``group-by``: a
              call with the wrong number of operands or a ``group by`` the
              function does not take; ``key-operand``: no key name where
              ``time_shift`` or ``annualise`` needs one;
            * ``missing-table``: a selection without a table;
            * ``unknown-table``: a table that does not exist;
            * ``unknown-row``, ``unknown-column`` and ``unknown-sheet``: a
              coordinate the table does not have, an
              error when no part of the selector matches and a warning when
              another part does; ``empty-range``: the same for a range;
            * ``missing-row``, ``missing-column`` and ``missing-sheet``: a
              code on an axis the table does not have; ``open-row``,
              ``open-column`` and ``open-sheet``: a code on an open axis,
              whose rows, columns or sheets have keys instead of codes. What
              a provider selects for such a code is up to it (a
              [`MemoryProvider`][dpmxl.provider.MemoryProvider] ignores the
              selector), so these are warnings, and they are not reported
              for a selector a shared ``with`` context applies;
            * ``type-mismatch``: an operand of the wrong data type;
            * ``unknown-key``: a name in a clause that is not a key of what
              the clause applies to (a warning where a report parameter may
              stand in and the parameters are not known); ``unknown-name``: a
              name that is no report parameter or earlier assignment.
        message: What is wrong, in plain words.
        start: Zero-based offset of the first character concerned.
        end: Offset just past the last character; equals ``start`` for a
            problem at a position, such as the end of the expression.
        subject: What the problem is about, when it names something: the
            function, table, coordinate, key or name as written, or the data
            type found; ``None`` otherwise.
        suggestion: A replacement for ``expression[start:end]`` that likely
            fixes the problem, such as ``sum`` for ``summ``; ``None`` when
            there is no likely fix.
    """

    severity: Severity
    code: str
    message: str
    start: int
    end: int
    subject: str | None = None
    suggestion: str | None = None

    def pointer(self, expression: str) -> str:
        """Render the source line and mark the text concerned.

        Args:
            expression: The expression the diagnostic was found in.

        Returns:
            str: Two lines for terminal output, as
            [`DpmXlSyntaxError.pointer`][dpmxl.parser.DpmXlSyntaxError.pointer].

        Examples:
            >>> source = "summ({tC_01.00, r0010}) > 0"
            >>> print(diagnose(source)[0].pointer(source))
            summ({tC_01.00, r0010}) > 0
            ^~~~
        """
        return _pointer(expression, self.start, self.end)


def diagnose(
    expression: str,
    layout: LayoutLookup | None = None,
    *,
    tables: Iterable[str] | None = None,
    parameters: Iterable[str] | None = None,
    program: bool = False,
) -> tuple[Diagnostic, ...]:
    """Return the problems found in an expression without evaluating it.

    Every syntax error is reported: after one, parsing resumes where the
    enclosing construct can carry on, and an error caused by an earlier one
    is left out. A construct that contains a syntax error is not checked
    further. Selections inside ``with`` are checked with their context, and
    a problem in the context is reported once, at the context.

    Args:
        expression: A DPM-XL rule expression, or a script with
            ``program=True``.
        layout: Looks up a table's [`TableLayout`][dpmxl.provider.TableLayout],
            or returns ``None`` for a table that does not exist. Without it,
            tables, coordinates, keys and data types are not checked. Table
            groups and operations are never checked.
        tables: Every table code, to suggest one for an unknown table.
        parameters: Every report parameter name. With them, a name that is
            neither a parameter, nor assigned by an earlier statement, nor a
            key in a clause is an error; without them names are not checked
            outside clauses.
        program: Accept a script (``;``, ``:=`` and ``<-``), as
            [`parse_program`][dpmxl.parser.parse_program] does; otherwise the
            text must be one expression, as for
            [`parse`][dpmxl.parser.parse].

    Returns:
        tuple[Diagnostic, ...]: Problems in source order; empty when none
        were found.

    Examples:
        >>> for d in diagnose("summ({tC_01.00, r0010}) > 0 and"):
        ...     print(d.start, d.end, d.code, d.message)
        0 4 unknown-function unknown function 'summ'; did you mean 'sum'?
        31 31 syntax expression ends where an operand is expected
        >>> from dpmxl import TableLayout
        >>> layouts = {"C_01.00": TableLayout("C_01.00", rows=("0010", "0020"))}
        >>> for d in diagnose("{tC_01.00, r0011} = {tC_02.00, r0010}", layouts.get):
        ...     print(d.start, d.end, d.message, d.suggestion)
        11 16 row 0011 is not in table C_01.00; did you mean r0010? r0010
        21 29 unknown table C_02.00 None
    """
    tree, errors = _parse_recovering(expression, program=program)
    checker = _Checker(
        expression,
        errors,
        layout,
        None if tables is None else tuple(tables),
        None if parameters is None else frozenset(parameters),
    )
    return checker.run(tree)


_AXES = (("rows", "r", "row"), ("columns", "c", "column"), ("sheets", "s", "sheet"))
_TYPE_OF_LITERAL = {
    "number": "number",
    "string": "string",
    "date": "date",
    "boolean": "boolean",
    "item": "item",
}
_SCALAR_TYPES = frozenset({"boolean", "date", "integer", "item", "number", "string"})
_ARITHMETIC = frozenset({"+", "-", "*", "/"})
_COMPARISONS = frozenset({"=", "!=", "<", "<=", ">", ">="})
_LOGICAL = frozenset({"and", "or", "xor"})
_DATE_PARTS = ("year", "semester", "quarter", "month", "week", "day")
# Operands a function needs of one type, by position, as the evaluator
# checks them.
_OPERAND_TYPES: dict[str, dict[int, str]] = {
    **{name: {0: "number"} for name in ("abs", "exp", "ln", "sqrt")},
    **{name: {0: "number", 1: "number"} for name in ("power", "log")},
    "date": {0: "number", 1: "number", 2: "number"},
    "substr": {0: "string"},
    "match": {1: "string"},
    **{name: {0: "date"} for name in _DATE_PARTS},
}
_NUMBER_RESULTS = frozenset(
    {
        "abs",
        "exp",
        "ln",
        "sqrt",
        "power",
        "log",
        "len",
        "length",
        "count",
        "sum",
        "avg",
        "median",
        "annualise",
        *_DATE_PARTS,
    }
)
# Single words that run together when a space is left out, as in ornot.
_JOINABLE = frozenset(word for word in KEYWORDS if " " not in word) | LITERAL_WORDS
# Operands longer than this are not quoted in a type-mismatch message.
_LONG_TEXT = 40


@dataclass(frozen=True, slots=True)
class _Scope:
    """What a node inherits: its ``with`` context, and the names in scope."""

    context: SelectionSpec = field(default_factory=SelectionSpec)
    # Inside a clause condition names are keys; keys is None when the
    # clause's keys are unknown, so its names are not checked.
    clause: bool = False
    keys: tuple[str, ...] | None = None
    table: str | None = None
    temporaries: frozenset[str] = frozenset()


class _Checker:
    """One diagnose run: the walk over the tree and the problems found."""

    def __init__(
        self,
        source: str,
        errors: Sequence[DpmXlSyntaxError],
        layout: LayoutLookup | None,
        tables: tuple[str, ...] | None,
        parameters: frozenset[str] | None,
    ) -> None:
        self.source = source
        self.errors = errors
        self.layout = layout
        self.tables = tables
        self.parameters = parameters
        # Keyed so that a context problem shared by many selections is
        # reported once.
        self.found: dict[tuple[int, int, str], Diagnostic] = {}
        self.types: dict[int, str | None] = {}
        self.layouts: dict[str, TableLayout | None] = {}
        self.selection_types: dict[tuple[object, ...], str | None] = {}
        try:
            self.tokens = tokenize(source)
        except DpmXlSyntaxError:
            self.tokens = []

    def run(self, tree: Program | None) -> tuple[Diagnostic, ...]:
        for error in self.errors:
            self.syntax(error)
        if tree is not None:
            self.walk(tree)
        return tuple(
            sorted(self.found.values(), key=lambda d: (d.start, d.end, d.code))
        )

    def add(
        self,
        severity: Severity,
        code: str,
        message: str,
        span: tuple[int, int],
        subject: str | None = None,
        suggestion: str | None = None,
    ) -> None:
        start, end = span
        self.found.setdefault(
            (start, end, message),
            Diagnostic(severity, code, message, start, end, subject, suggestion),
        )

    def damaged(self, span: tuple[int, int]) -> bool:
        """Whether a syntax error lies within ``span``.

        Returns:
            bool: True when the construct is not checked further.
        """
        return any(span[0] <= error.position <= span[1] for error in self.errors)

    # Syntax ------------------------------------------------------------

    def syntax(self, error: DpmXlSyntaxError) -> None:
        joined = self.missing_space(error)
        if joined is not None:
            token, words = joined
            self.add(
                "error",
                "syntax",
                f"missing space: did you mean {words!r}?",
                (token.start, token.end),
                token.text,
                words,
            )
            return
        self.add("error", "syntax", error.message, (error.position, error.end))

    def missing_space(self, error: DpmXlSyntaxError) -> tuple[Token, str] | None:
        """Find keywords run together at a syntax error, such as ``ornot``.

        Returns:
            tuple[Token, str] | None: The token and its words with spaces,
            when the token at the error, or the one before it, is such a run.
        """
        after = next(
            (
                index
                for index, token in enumerate(self.tokens)
                if token.start >= error.position
            ),
            None,
        )
        if after is None:
            return None
        for index in (after, after - 1):
            if index < 0:
                continue
            token = self.tokens[index]
            if token.kind != "identifier":
                continue
            words = _split_words(token.text)
            if words is not None:
                return token, " ".join(words)
        return None

    # Walk --------------------------------------------------------------

    def walk(self, tree: Node) -> None:
        # Post-order with an explicit stack, as long sums nest deeply: checks
        # that need no operand types run on the way down, type checks on the
        # way up.
        pending: list[tuple[Node, _Scope, bool]] = [(tree, _Scope(), False)]
        while pending:
            node, scope, done = pending.pop()
            if done:
                self.types[id(node)] = (
                    None if self.damaged(node.span) else self.type_of(node, scope)
                )
                continue
            if not self.damaged(node.span):
                self.check(node, scope)
            pending.append((node, scope, True))
            pending.extend(
                (child, child_scope, False)
                for child, child_scope in reversed(self.children(node, scope))
            )

    def children(self, node: Node, scope: _Scope) -> list[tuple[Node, _Scope]]:
        match node:
            case With(context=context, body=body, condition=condition):
                inner = replace(scope, context=context.merged_into(scope.context))
                found = [
                    (child, scope)
                    for child in children(node)
                    if child is not body and child is not condition
                ]
                if condition is not None:
                    found.append((condition, replace(inner, clause=True, keys=None)))
                return [*found, (body, inner)]
            case Where(operand=operand, condition=condition):
                keys = self.keys_of(operand, scope)
                clause = replace(
                    scope,
                    clause=True,
                    keys=keys[0] if keys else None,
                    table=keys[1] if keys else None,
                )
                return [(operand, scope), (condition, clause)]
            case Program(statements=statements):
                found = []
                assigned = scope.temporaries
                for statement in statements:
                    found.append((statement, replace(scope, temporaries=assigned)))
                    if isinstance(statement, Assignment):
                        assigned = assigned | {statement.name}
                return found
            case Call(name=name, args=args) if name in SIGNATURES:
                # A key name or period code is not a report parameter.
                signature = SIGNATURES[name]
                named = {signature.key_operand, signature.period_operand}
                return [
                    (arg, replace(scope, clause=True, keys=None))
                    if index in named
                    else (arg, scope)
                    for index, arg in enumerate(args)
                ]
        return [(child, scope) for child in children(node)]

    def check(self, node: Node, scope: _Scope) -> None:
        match node:
            case Selection(spec=spec):
                self.check_selection(spec, spec.merged_into(scope.context), node.span)
            case Call():
                self.check_call(node, scope)
            case Name(name=name):
                self.check_name(name, node.span, scope)
            case Get(operand=operand, name=name):
                # get falls back to a report parameter of that name.
                self.check_keys(node, operand, (name,), scope, parameter=True)
            case Sub(operand=operand, name=name):
                self.check_keys(node, operand, (name,), scope)
            case Rename(operand=operand, pairs=pairs):
                self.check_keys(node, operand, [old for old, _ in pairs], scope)
            case Analytic(operand=operand, partition=partition, order_by=order):
                names = [*partition, *(key for key, _ in order)]
                self.check_keys(node, operand, names, scope)

    # Selections ----------------------------------------------------------

    def table_layout(self, code: str) -> TableLayout | None:
        if code not in self.layouts:
            assert self.layout is not None
            self.layouts[code] = self.layout(code)
        return self.layouts[code]

    def check_selection(
        self, written: SelectionSpec, spec: SelectionSpec, span: tuple[int, int]
    ) -> None:
        """Check a selection, ``written`` as is and ``spec`` with its context.

        A selector part that matches no code is an error only when no part
        matches, as the selection is then empty. What a code on an axis
        without codes (open or absent) selects is up to the provider, so it
        is a warning, and none for a selector a shared context applies.
        """
        if spec.table_group is not None or spec.operation is not None:
            return
        if spec.table is None:
            self.add(
                "error",
                "missing-table",
                "selection names no table; add one, such as tC_01.00, "
                "or a with context",
                span,
            )
            return
        if self.layout is None:
            return
        source = spec.source_span if spec.source_span != (0, 0) else span
        layout = self.table_layout(spec.table)
        if layout is None:
            self.unknown_table(spec.table, source)
            return
        for axis, letter, noun in _AXES:
            selector: AxisSelector | None = getattr(spec, axis)
            if selector is None or selector.wildcard:
                continue
            where = selector.span if selector.span != (0, 0) else span
            codes: tuple[str, ...] = getattr(layout, axis)
            if codes:
                self.check_parts(spec.table, selector, codes, letter, noun, where)
                continue
            # The axis has no codes. Only a selector written with the table,
            # not one a shared with context applies to several tables, is
            # worth a warning.
            if not _same_braces(self.source, where, source) and (
                getattr(written, axis) is None
            ):
                continue
            if axis in layout.open_axes:
                self.open_axis(spec.table, layout, selector, axis, letter, where)
            elif not layout.open_keys or layout.open_axes:
                # Without open_axes, an axis without codes of a table with
                # open keys may be open or absent, so it is not described.
                text = selector.text(letter)
                self.add(
                    "warning",
                    f"missing-{noun}",
                    f"table {spec.table} has no {axis}, so it has no codes "
                    f"such as {_first_part(selector, letter)}",
                    where,
                    text,
                )

    def open_axis(
        self,
        table: str,
        layout: TableLayout,
        selector: AxisSelector,
        axis: str,
        letter: str,
        where: tuple[int, int],
    ) -> None:
        keys = layout.open_keys
        named = (
            f" (key{'s' if len(keys) > 1 else ''} {', '.join(keys)})" if keys else ""
        )
        text = selector.text(letter)
        written = self.source[where[0] : where[1]]
        prefix = written[:1] if written[:1].casefold() == letter else letter
        self.add(
            "warning",
            f"open-{_noun(axis)}",
            f"the {axis} of {table} are open{named}, so they have no codes "
            f"such as {_first_part(selector, letter)}; select them with "
            f"{letter}* or leave them out",
            where,
            text,
            prefix + "*",
        )

    def unknown_table(self, code: str, span: tuple[int, int]) -> None:
        match = _closest(code, self.tables or (), cutoff=0.8)
        written = self.source[span[0] : span[1]]
        suggestion = None
        if match is not None and written[1:2] != "`":
            prefix = written[:2] if written[1:2] == "_" else written[:1]
            suggestion = prefix + match
        hint = f"; did you mean {match}?" if match else ""
        self.add(
            "error",
            "unknown-table",
            f"unknown table {code}{hint}",
            span,
            code,
            suggestion,
        )

    def check_parts(
        self,
        table: str,
        selector: AxisSelector,
        codes: tuple[str, ...],
        letter: str,
        noun: str,
        where: tuple[int, int],
    ) -> None:
        spans = (
            selector.spans
            if len(selector.spans) == len(selector.parts)
            else (where,) * len(selector.parts)
        )
        unmatched = [
            (part, span)
            for part, span in zip(selector.parts, spans, strict=True)
            if not any(
                axis_matcher(AxisSelector(parts=(part,)))(code) for code in codes
            )
        ]
        # The selection is empty only when no part matches; otherwise the
        # rule still evaluates over the parts that do.
        severity: Severity = (
            "error" if len(unmatched) == len(selector.parts) else "warning"
        )
        for part, span in unmatched:
            if isinstance(part, str):
                match = _closest(part, codes, cutoff=0.75)
                written = self.source[span[0] : span[1]]
                prefix = written[:1] if written[:1].casefold() == letter else letter
                self.add(
                    severity,
                    f"unknown-{noun}",
                    f"{noun} {part} is not in table {table}"
                    + (f"; did you mean {letter}{match}?" if match else ""),
                    span,
                    part,
                    prefix + match if match else None,
                )
            else:
                self.add(
                    severity,
                    "empty-range",
                    f"{noun}s {part[0]}-{part[1]} select no {noun} of table {table}",
                    span,
                    f"{part[0]}-{part[1]}",
                )

    # Calls ---------------------------------------------------------------

    def name_span(self, node: Node) -> tuple[int, int]:
        match = re.match(r"[A-Za-z_][A-Za-z0-9_.]*", self.source[node.span[0] :])
        if match is None:
            return node.span
        return (node.span[0], node.span[0] + match.end())

    def check_call(self, node: Call, scope: _Scope) -> None:
        name = node.name
        where = self.name_span(node)
        if name not in CALL_NAMES:
            match = _closest(name, sorted(CALL_NAMES), cutoff=0.7)
            hint = f"; did you mean {match!r}?" if match else ""
            self.add(
                "error",
                "unknown-function",
                f"unknown function {name!r}{hint}",
                where,
                name,
                match,
            )
            return
        signature = SIGNATURES[name]
        problem = signature.problem(
            name, len(node.args), group_by=node.group_by is not None
        )
        if problem is not None:
            code = "group-by" if problem.startswith("group by") else "operand-count"
            self.add("error", code, problem, where, name)
            return
        position = signature.key_operand
        if position is not None and position < len(node.args):
            operand = node.args[position]
            if not isinstance(operand, Name):
                self.add(
                    "error",
                    "key-operand",
                    signature.key_problem(name),
                    operand.span,
                    name,
                )
        if node.group_by:
            self.check_keys(node, node.args[0], node.group_by, scope)

    # Names and keys ------------------------------------------------------

    def keys_of(
        self, operand: Node, scope: _Scope
    ) -> tuple[tuple[str, ...], str] | None:
        """Return the keys a clause's operand may have, with its table.

        Returns:
            tuple[tuple[str, ...], str] | None: The open keys and ``r``,
            ``c`` and ``s``, for an operand that selects from a table with a
            known layout; ``None`` when the keys are unknown.
        """
        match operand:
            case Selection(spec=spec):
                merged = spec.merged_into(scope.context)
                if self.layout is None or merged.table is None:
                    return None
                if merged.table_group is not None or merged.operation is not None:
                    return None
                layout = self.table_layout(merged.table)
                if layout is None:
                    return None
                return (*layout.open_keys, *sorted(STANDARD_KEYS)), merged.table
            case Where(operand=inner) | Sub(operand=inner):
                return self.keys_of(inner, scope)
        return None

    def check_keys(
        self,
        node: Node,
        operand: Node,
        names: Iterable[str],
        scope: _Scope,
        *,
        parameter: bool = False,
    ) -> None:
        """Check the key names a clause or grouping writes.

        Args:
            node: The clause or call, for positions.
            operand: What the names must be keys of.
            names: The names written.
            scope: The node's scope.
            parameter: Whether a report parameter may stand in for a key.
        """
        found = self.keys_of(operand, scope)
        if found is None:
            return
        keys, table = found
        severity: Severity = "error"
        for name in names:
            if resolve_key(name, keys) is not None:
                continue
            if parameter:
                if self.parameters is None:
                    severity = "warning"
                elif name in self.parameters:
                    continue
            span = self.identifier_span(name, operand.span[1], node.span[1])
            self.unknown_key(
                severity, name, span or node.span, keys, table, parameter=parameter
            )

    def check_name(self, name: str, span: tuple[int, int], scope: _Scope) -> None:
        if name in scope.temporaries:
            return
        if self.parameters is not None and name in self.parameters:
            return
        if scope.clause:
            if scope.keys is None or resolve_key(name, scope.keys) is not None:
                return
            assert scope.table is not None
            # Without the report parameters, a name in a clause that is not
            # a key may still be a parameter.
            severity: Severity = "error" if self.parameters is not None else "warning"
            self.unknown_key(
                severity, name, span, scope.keys, scope.table, parameter=True
            )
            return
        if self.parameters is None:
            return
        known = sorted(self.parameters | scope.temporaries)
        match = _closest(name, known, cutoff=0.75)
        self.add(
            "error",
            "unknown-name",
            f"unknown name {name!r}: no report parameter or earlier assignment "
            "has it" + (f"; did you mean {match!r}?" if match else ""),
            span,
            name,
            match,
        )

    def unknown_key(
        self,
        severity: Severity,
        name: str,
        span: tuple[int, int],
        keys: Sequence[str],
        table: str,
        *,
        parameter: bool = False,
    ) -> None:
        """Report a name that is not a key of a clause's operand.

        ``parameter`` tells whether a report parameter could stand in for it.
        """
        open_keys = [key for key in keys if key not in STANDARD_KEYS]
        match = _closest(name, open_keys, cutoff=0.75)
        listed = f"keys {', '.join(open_keys)}" if open_keys else "no open keys"
        message = f"{name} is not a key of table {table} ({listed})"
        if parameter and self.parameters is not None:
            message += ", nor a report parameter"
        elif parameter:
            message += "; unless it is a report parameter, evaluation fails"
        self.add(severity, "unknown-key", message, span, name, match)

    def identifier_span(
        self, name: str, start: int, end: int
    ) -> tuple[int, int] | None:
        for token in self.tokens:
            if token.start < start or token.end > end or token.kind != "identifier":
                continue
            text = token.text[1:-1] if token.text[:1] == "`" else token.text
            if text == name:
                return (token.start, token.end)
        return None

    # Types ---------------------------------------------------------------

    def type(self, node: Node | None) -> str | None:
        return None if node is None else self.types.get(id(node))

    def type_of(self, node: Node, scope: _Scope) -> str | None:
        """Infer a node's data type from its operands', reporting mismatches.

        Returns:
            str | None: ``number``, ``string``, ``date``, ``boolean`` or
            ``item``; ``None`` when unknown or mixed.
        """
        match node:
            case Literal_(kind=kind):
                return _TYPE_OF_LITERAL.get(kind)
            case Selection(spec=spec):
                return self.selection_type(spec.merged_into(scope.context))
            case TableReported() | In():
                return "boolean"
            case TypedParameter(kind=kind):
                if kind not in _SCALAR_TYPES:
                    return None
                return "number" if kind == "integer" else kind
            case Unary(op="not", operand=operand):
                self.require(operand, "boolean", "'not' needs a boolean")
                return "boolean"
            case Unary(op=op, operand=operand):
                self.require(operand, "number", f"unary '{op}' needs a number")
                return "number"
            case Binary(op=op, left=left, right=right):
                return self.binary_type(node, op, left, right)
            case If(condition=condition, then=then, otherwise=otherwise):
                self.require(condition, "boolean", "if needs a boolean condition")
                if otherwise is None:
                    return self.type(then)
                return _common(self.type(then), self.type(otherwise))
            case Call(name=name, args=args):
                return self.call_type(name, args)
            case Analytic(name=name, operand=operand):
                if name in {"max", "min"}:
                    return self.type(operand)
                return "number"
            case (
                Where(operand=operand) | Sub(operand=operand) | Rename(operand=operand)
            ):
                return self.type(operand)
            case With(body=body) | Assignment(value=body):
                return self.type(body)
            case Program(statements=statements):
                return self.type(statements[-1])
        return None

    def selection_type(self, spec: SelectionSpec) -> str | None:
        if self.layout is None or spec.table is None:
            return None
        if spec.table_group is not None or spec.operation is not None:
            return None
        key = (spec.table, spec.rows, spec.columns, spec.sheets, spec.default)
        if key in self.selection_types:
            return self.selection_types[key]
        found: str | None = None
        layout = self.table_layout(spec.table)
        if layout is not None and layout.data_types:
            # A cell without a type leaves the selection's type unknown.
            types: set[str | None] = set(_cell_types(layout, spec))
            default = spec.default
            if isinstance(default, SetLiteral):
                types.add("set")
            elif isinstance(default, Literal_) and default.kind != "null":
                types.add(_TYPE_OF_LITERAL[default.kind])
            if len(types) == 1:
                found = types.pop()  # None when the only type is unknown
        self.selection_types[key] = found
        return found

    def binary_type(self, node: Node, op: str, left: Node, right: Node) -> str | None:
        if op in _ARITHMETIC:
            for operand in (left, right):
                self.require(operand, "number", f"'{op}' needs numbers")
            return "number"
        if op == "&":
            for operand in (left, right):
                self.require(operand, "string", "'&' needs strings")
            return "string"
        if op in _LOGICAL:
            for operand in (left, right):
                self.require(operand, "boolean", f"'{op}' needs booleans")
            return "boolean"
        if op in _COMPARISONS:
            self.check_comparison(node, op, self.type(left), self.type(right))
            return "boolean"
        return None

    def check_comparison(
        self, node: Node, op: str, left: str | None, right: str | None
    ) -> None:
        # Only pairs the evaluator rejects whatever their values: a string
        # compares with a date, a boolean or an item.
        if left is None or right is None:
            return
        pair = {left, right}
        if "item" in pair and op not in {"=", "!="}:
            self.add(
                "error",
                "type-mismatch",
                f"items compare only with = or !=, not '{op}'",
                node.span,
                "item",
            )
        elif ("number" in pair and pair & {"string", "date", "boolean"}) or pair == {
            "boolean",
            "date",
        }:
            self.add(
                "error",
                "type-mismatch",
                f"'{op}' cannot compare {_article(left)} with {_article(right)}",
                node.span,
            )

    def call_type(self, name: str, args: Sequence[Node]) -> str | None:
        for position, wanted in _OPERAND_TYPES.get(name, {}).items():
            if position < len(args):
                self.require(args[position], wanted, f"{name} needs {_article(wanted)}")
        if name in {"sum", "avg", "median"} and len(args) == 1:
            self.require(args[0], "number", f"{name} needs numbers")
        if name in {"max", "min"} and len(args) == 1:
            found = self.type(args[0])
            if found == "boolean":
                self.mismatch(
                    args[0], f"{name} needs numbers, dates, strings or items", found
                )
        if name in _NUMBER_RESULTS:
            return "number"
        if name in {"isnull", "match"}:
            return "boolean"
        if name == "substr":
            return "string"
        if name == "date":
            return "date"
        if name in {"max", "min", "nvl"}:
            return _common(*(self.type(arg) for arg in args))
        if name in {"filter", "time_shift"} and args:
            return self.type(args[0])
        return None

    def require(self, operand: Node, wanted: str, needs: str) -> None:
        found = self.type(operand)
        if found is not None and found != wanted:
            self.mismatch(operand, needs, found)

    def mismatch(self, operand: Node, needs: str, found: str) -> None:
        text = " ".join(self.source[operand.span[0] : operand.span[1]].split())
        shown = text if len(text) <= _LONG_TEXT else "its operand"
        self.add(
            "error",
            "type-mismatch",
            f"{needs}, but {shown} is {_article(found)}",
            operand.span,
            found,
        )


def _same_braces(source: str, first: tuple[int, int], second: tuple[int, int]) -> bool:
    """Whether two spans were written inside the same ``{...}``.

    Returns:
        bool: True when no brace stands between them, or a span is unknown.
    """
    if first == (0, 0) or second == (0, 0):
        return True
    start, end = sorted((first, second))
    return not any(char in "{}" for char in source[start[1] : end[0]])


def _first_part(selector: AxisSelector, letter: str) -> str:
    """Return a selector's first code or range, such as ``r0010``.

    Returns:
        str: The part in DPM-XL syntax.
    """
    if not selector.parts:
        return selector.text(letter)
    return AxisSelector(parts=selector.parts[:1]).text(letter)


def _noun(axis: str) -> str:
    return axis[:-1]


def _cell_types(layout: TableLayout, spec: SelectionSpec) -> Iterator[str | None]:
    """Yield the data type of each cell a selection covers in a layout.

    A selector applies only to an axis with codes, as in
    [`MemoryProvider`][dpmxl.provider.MemoryProvider].

    Yields:
        str | None: Each covered cell's type, ``integer`` read as ``number``;
        ``None`` for a cell without one.
    """
    rows = axis_matcher(spec.rows if layout.rows else None)
    columns = axis_matcher(spec.columns if layout.columns else None)
    sheets = axis_matcher(spec.sheets if layout.sheets else None)
    for cell in layout.coordinates():
        row, column, sheet = cell
        if rows(row) and columns(column) and sheets(sheet):
            data_type = layout.data_types.get(cell)
            yield "number" if data_type == "integer" else data_type


def _common(*types: str | None) -> str | None:
    """Return the one type all operands share.

    Returns:
        str | None: The shared type; ``None`` when one is unknown or they
        differ.
    """
    distinct = set(types)
    return distinct.pop() if len(distinct) == 1 else None


def _article(data_type: str) -> str:
    return f"an {data_type}" if data_type == "item" else f"a {data_type}"


def _split_words(word: str) -> list[str] | None:
    """Split a run of keywords and literal words, such as ``trueendif``.

    Returns:
        list[str] | None: The words as written, at least two and as few as
        possible; ``None`` when ``word`` is not such a run.
    """
    folded = word.casefold()
    # ends[i]: the fewest word ends that split folded[:i].
    ends: list[list[int] | None] = [None] * (len(folded) + 1)
    ends[0] = []
    for index in range(len(folded)):
        here = ends[index]
        if here is None:
            continue
        for joinable in _JOINABLE:
            if folded.startswith(joinable, index):
                end = index + len(joinable)
                candidate = [*here, end]
                best = ends[end]
                if best is None or len(candidate) < len(best):
                    ends[end] = candidate
    found = ends[-1]
    if found is None or len(found) < 2:
        return None
    starts = [0, *found[:-1]]
    return [word[start:end] for start, end in zip(starts, found, strict=True)]


def _closest(word: str, candidates: Iterable[str], *, cutoff: float) -> str | None:
    """Return the one candidate clearly closest to ``word``.

    A candidate equal to ``word`` but for case wins outright; otherwise the
    best match must reach ``cutoff`` and beat the runner-up.

    Returns:
        str | None: The candidate, or ``None`` when none or several fit.
    """
    pool = list(dict.fromkeys(candidates))
    folded = word.casefold()
    for candidate in pool:
        if candidate.casefold() == folded:
            return candidate
    by_folded = {candidate.casefold(): candidate for candidate in pool}
    close = difflib.get_close_matches(folded, list(by_folded), n=2, cutoff=cutoff)
    if not close:
        return None
    if len(close) == 2:
        first, second = (
            difflib.SequenceMatcher(None, folded, match).ratio() for match in close
        )
        if first == second:
            return None
    return by_folded[close[0]]


__all__ = ["DIAGNOSTIC_CODES", "Diagnostic", "LayoutLookup", "Severity", "diagnose"]
