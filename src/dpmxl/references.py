"""Static analysis: the selections and templates an expression refers to."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .ast import (
    Node,
    Selection,
    SelectionSpec,
    TableReported,
    With,
    children,
)


@dataclass(frozen=True, slots=True)
class Reference:
    """A selection completed by its inherited ``with`` context.

    ``spec.table`` is the table code of a cell selection; for a table group
    (``{g_Group, ...}``) or operation (``{o_Code, ...}``) reference it is
    ``None`` and [`kind`][dpmxl.references.Reference.kind] and
    [`code`][dpmxl.references.Reference.code] say what is referenced. Typed
    parameters (``{p_Name, ...}``) are not selections and are not listed.

    Attributes:
        spec: The selection with its ``with`` context applied.
        span: The selection's source span.
    """

    spec: SelectionSpec
    span: tuple[int, int]

    @property
    def kind(self) -> Literal["table", "table_group", "operation"]:
        """What the selection reads: a table, a table group or an operation."""
        if self.spec.operation is not None:
            return "operation"
        if self.spec.table_group is not None:
            return "table_group"
        return "table"

    @property
    def code(self) -> str | None:
        """The table, table group or operation code."""
        return self.spec.operation or self.spec.table_group or self.spec.table


def references(node: Node) -> tuple[Reference, ...]:
    """Return every selection with its inherited context applied.

    Table-group and operation references are included with ``spec.table`` set to
    ``None``: check [`Reference.kind`][dpmxl.references.Reference.kind] and read the
    group or operation code from [`Reference.code`][dpmxl.references.Reference.code]. A
    group read reads every table the provider's ``table_group(code)`` lists;
    [`tables`][dpmxl.references.tables] expands groups that way when given the provider.
    Targets of persistent assignments are included too.

    Returns:
        tuple[Reference, ...]: Selections in source order.

    Examples:
        >>> from dpmxl import parse
        >>> node = parse("with {tC_01.00, c0010}: {r0010} = {r0020} + {g_G1, r0010}")
        >>> [(ref.spec.text(), ref.kind, ref.code) for ref in references(node)]
        ... # doctest: +NORMALIZE_WHITESPACE
        [('{tC_01.00, r0010, c0010}', 'table', 'C_01.00'),
         ('{tC_01.00, r0020, c0010}', 'table', 'C_01.00'),
         ('{gG1, r0010, c0010}', 'table_group', 'G1')]
    """
    found: list[Reference] = []
    # An explicit stack, not a recursive closure: a closure that refers to
    # itself is a reference cycle, which would leave every Reference it
    # found for the cyclic garbage collector instead of freeing it at once.
    pending: list[tuple[Node, SelectionSpec]] = [(node, SelectionSpec())]
    while pending:
        current, context = pending.pop()
        if isinstance(current, With):
            pending.append((current.body, current.context.merged_into(context)))
        elif isinstance(current, Selection):
            found.append(Reference(current.spec.merged_into(context), current.span))
        else:
            # Reversed, so children are visited in source order.
            pending.extend((child, context) for child in reversed(children(current)))
    return tuple(sorted(found, key=lambda reference: reference.span))


def tables(node: Node, provider: object | None = None) -> tuple[str, ...]:
    """Return the distinct table codes referenced by cell selections.

    Args:
        node: The expression tree.
        provider: Optional provider whose ``table_group(code)`` method
            resolves table groups; each group read then counts as reading
            all its tables. Without it, groups are left out.

    Returns:
        tuple[str, ...]: Table codes in first-seen order.

    Examples:
        >>> from dpmxl import MemoryProvider, parse
        >>> node = parse("{tC_01.00, r0010} = {g_G1, r0010}")
        >>> tables(node)
        ('C_01.00',)
        >>> tables(node, MemoryProvider([], {}, table_groups={"G1": ("C_05.01",)}))
        ('C_01.00', 'C_05.01')
    """
    method = getattr(provider, "table_group", None)
    found: list[str] = []
    for reference in references(node):
        if reference.spec.table:
            found.append(reference.spec.table)
        elif reference.spec.table_group and callable(method):
            found.extend(method(reference.spec.table_group) or ())
    return tuple(dict.fromkeys(found))


def reported_templates(node: Node) -> tuple[str, ...]:
    """Return templates tested with ``{v_...}`` filing-indicator checks.

    Returns:
        tuple[str, ...]: Template codes in first-seen order.

    Examples:
        >>> from dpmxl import parse
        >>> reported_templates(parse("{v_C_01.00} and not {v_C_02.00}"))
        ('C_01.00', 'C_02.00')
    """
    pending = [node]
    found: list[str] = []
    while pending:
        current = pending.pop(0)
        if isinstance(current, TableReported):
            found.append(current.table)
        pending.extend(children(current))
    return tuple(dict.fromkeys(found))


__all__ = ["Reference", "references", "reported_templates", "tables"]
