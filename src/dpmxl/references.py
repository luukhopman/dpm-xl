"""Static analysis: the selections and templates an expression refers to."""

from __future__ import annotations

from dataclasses import dataclass

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
    """A selection completed by its inherited ``with`` context."""

    spec: SelectionSpec
    span: tuple[int, int]


def references(node: Node) -> tuple[Reference, ...]:
    """Return every cell selection with its inherited context applied.

    Returns:
        tuple[Reference, ...]: Selections in source order.
    """
    found: list[Reference] = []

    def visit(current: Node, context: SelectionSpec) -> None:
        if isinstance(current, With):
            visit(current.body, current.context.merged_into(context))
            return
        if isinstance(current, Selection):
            found.append(Reference(current.spec.merged_into(context), current.span))
            return
        for child in children(current):
            visit(child, context)

    visit(node, SelectionSpec())
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
