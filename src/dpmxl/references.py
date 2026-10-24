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
    ``None`` and :attr:`kind` and :attr:`code` say what is referenced.
    Typed parameters (``{p_Name, ...}``) are not selections and are not
    listed.
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
    """Return every cell selection with its inherited context applied.

    Returns:
        tuple[Reference, ...]: Selections in source order.
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


def tables(node: Node) -> tuple[str, ...]:
    """Return the distinct table codes referenced by cell selections.

    Returns:
        tuple[str, ...]: Table codes in first-seen order.
    """
    return tuple(
        dict.fromkeys(
            reference.spec.table
            for reference in references(node)
            if reference.spec.table
        )
    )


def reported_templates(node: Node) -> tuple[str, ...]:
    """Return templates tested with ``{v_...}`` filing-indicator checks.

    Returns:
        tuple[str, ...]: Template codes in first-seen order.
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
