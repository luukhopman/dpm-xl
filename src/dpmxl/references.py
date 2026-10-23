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
