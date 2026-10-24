"""Abstract syntax tree for DPM-XL expressions.

Every node keeps the half-open source ``span`` it was parsed from, so callers
can show the original operand text next to an evaluated value without
re-printing the expression.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Literal, TypeAlias

Span: TypeAlias = tuple[int, int]
AxisName: TypeAlias = Literal["rows", "columns", "sheets"]
AXIS_PREFIXES: dict[str, AxisName] = {"r": "rows", "c": "columns", "s": "sheets"}
AXIS_KEYS: dict[AxisName, str] = {"rows": "r", "columns": "c", "sheets": "s"}


@dataclass(frozen=True, slots=True)
class AxisSelector:
    """Selected coordinates on one table axis.

    ``parts`` holds single codes (``"0010"``) and inclusive ranges
    (``("0010", "0050")``) exactly as written, without the axis prefix.
    """

    wildcard: bool = False
    parts: tuple[str | tuple[str, str], ...] = ()

    @property
    def is_single(self) -> bool:
        """Whether the selector names exactly one coordinate."""
        return (
            not self.wildcard
            and len(self.parts) == 1
            and isinstance(self.parts[0], str)
        )

    def text(self, prefix: str) -> str:
        """Render the selector in DPM-XL syntax.

        Returns:
            str: For example ``r*``, ``r0010`` or ``(r0010, r0020-0050)``.
        """
        if self.wildcard:
            return f"{prefix}*"
        values = [
            f"{prefix}{part}"
            if isinstance(part, str)
            else f"{prefix}{part[0]}-{part[1]}"
            for part in self.parts
        ]
        return values[0] if len(values) == 1 else f"({', '.join(values)})"


class _Missing:
    """Marker for a selection option that was not written."""

    _instance: _Missing | None = None

    def __new__(cls) -> _Missing:
        """Return the shared marker instance.

        Returns:
            _Missing: The singleton.
        """
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __repr__(self) -> str:
        return "MISSING"

    def __bool__(self) -> bool:
        return False


MISSING = _Missing()


@dataclass(frozen=True, slots=True)
class SelectionSpec:
    """Source, axis and option components of a ``{...}`` selection.

    The source is one of ``table`` (``tC_01.00``), ``table_group``
    (``gG_01``) or ``operation`` (``o_v1234``, another operation's result);
    the others are ``None``.
    """

    table: str | None = None
    rows: AxisSelector | None = None
    columns: AxisSelector | None = None
    sheets: AxisSelector | None = None
    default: Literal_ | SetLiteral | _Missing = MISSING
    interval: bool | None = None
    table_group: str | None = None
    operation: str | None = None

    def merged_into(self, context: SelectionSpec) -> SelectionSpec:
        """Return this selection completed by an inherited ``with`` context.

        Returns:
            SelectionSpec: Components written here win over the context; a
            source written here replaces the context's source.
        """
        if self.table is None and self.table_group is None and self.operation is None:
            table, group, operation = (
                context.table,
                context.table_group,
                context.operation,
            )
        else:
            table, group, operation = self.table, self.table_group, self.operation
        return SelectionSpec(
            table=table,
            rows=self.rows if self.rows is not None else context.rows,
            columns=self.columns if self.columns is not None else context.columns,
            sheets=self.sheets if self.sheets is not None else context.sheets,
            default=self.default if self.default is not MISSING else context.default,
            interval=self.interval if self.interval is not None else context.interval,
            table_group=group,
            operation=operation,
        )

    def axis(self, name: AxisName) -> AxisSelector | None:
        """Return the selector for one axis.

        Returns:
            AxisSelector | None: ``None`` when the axis was not written.
        """
        return getattr(self, name)

    def text(self) -> str:
        """Render the selection in DPM-XL syntax.

        Returns:
            str: A normalized ``{...}`` selection.
        """
        parts: list[str] = []
        if self.table:
            parts.append(f"t{self.table}")
        if self.table_group:
            parts.append(f"g{self.table_group}")
        if self.operation:
            parts.append(f"o{self.operation}")
        for name, prefix in (("rows", "r"), ("columns", "c"), ("sheets", "s")):
            selector = getattr(self, name)
            if selector is not None:
                parts.append(selector.text(prefix))
        if self.default is not MISSING:
            parts.append(f"default: {_literal_text(self.default)}")
        if self.interval is not None:
            parts.append(f"interval: {str(self.interval).lower()}")
        return "{" + ", ".join(parts) + "}"


@dataclass(frozen=True, slots=True)
class Node:
    """Base class for expression nodes.

    Every node has a public ``span``: the half-open ``(start, end)`` character
    offsets of its source in the parsed expression, so ``expression[start:end]``
    is the node's text. A parenthesized operand's span includes the
    parentheses; a clause's span runs from its operand to the closing ``]``.
    Spans take no part in equality or hashing. Nodes built directly default to
    ``(0, 0)``.
    """

    span: Span = field(default=(0, 0), compare=False, kw_only=True)


@dataclass(frozen=True, slots=True)
class Literal_(Node):
    """A constant: number, string, boolean, date, item or null."""

    value: Decimal | str | bool | date | Item | None
    kind: Literal["number", "string", "boolean", "date", "item", "null"]


@dataclass(frozen=True, slots=True)
class Item:
    """An enumerated item literal such as ``[eba_qEC:qx01]``.

    ``category`` is the namespace part without the ``eba_`` prefix; it is
    ``None`` for a bare legacy element reference such as ``[ei86]``.
    """

    category: str | None
    code: str

    def __post_init__(self) -> None:
        """Drop the ``eba_`` prefix from a category given directly."""
        category = self.category
        if category is not None and category[:4].casefold() == "eba_":
            object.__setattr__(self, "category", category[4:] or None)

    @classmethod
    def parse(cls, text: str) -> Item:
        """Parse ``prefix:code`` or a bare code.

        Returns:
            Item: Normalized item identity.
        """
        value = text.strip()
        if ":" not in value:
            return cls(None, value)
        prefix, code = value.split(":", 1)
        return cls(prefix.strip() or None, code.strip())

    def matches(self, other: Item) -> bool:
        """Compare two items, ignoring a category missing on either side.

        Returns:
            bool: Whether both name the same item.
        """
        if self.code != other.code:
            return False
        return (
            self.category is None
            or other.category is None
            or self.category == other.category
        )

    def __str__(self) -> str:
        """Render ``category:code`` or the bare code.

        Returns:
            str: The item text.
        """
        return f"{self.category}:{self.code}" if self.category else self.code


@dataclass(frozen=True, slots=True)
class Selection(Node):
    """A ``{...}`` cell selection."""

    spec: SelectionSpec


@dataclass(frozen=True, slots=True)
class TableReported(Node):
    """``{v_TABLE}``: true when the report declares the template."""

    table: str


@dataclass(frozen=True, slots=True)
class Parameter(Node):
    """``{vName}``: a report-level parameter such as ``ReportingLevel``."""

    name: str


@dataclass(frozen=True, slots=True)
class TypedParameter(Node):
    """``{p_Name, type[, default: value]}``: a typed report parameter.

    ``type`` is one of :data:`dpmxl.grammar.PARAMETER_TYPES` in lower case.
    """

    name: str
    type: str
    default: Literal_ | SetLiteral | _Missing = MISSING


@dataclass(frozen=True, slots=True)
class Name(Node):
    """A bare identifier: a key component, period unit or parameter name."""

    name: str


@dataclass(frozen=True, slots=True)
class SetLiteral(Node):
    """A set literal ``{a, b, ...}`` or the empty set ``{}``."""

    items: tuple[Node, ...]


@dataclass(frozen=True, slots=True)
class Unary(Node):
    """Prefix ``+``, ``-`` or ``not``."""

    op: Literal["+", "-", "not"]
    operand: Node


@dataclass(frozen=True, slots=True)
class Binary(Node):
    """Arithmetic, comparison or boolean operator."""

    op: str
    left: Node
    right: Node


@dataclass(frozen=True, slots=True)
class In(Node):
    """``operand in set``.

    ``values`` is a :class:`SetLiteral` for ``in {...}``, otherwise any
    set-valued expression such as a ``set-*`` parameter or ``union(...)``.
    """

    operand: Node
    values: Node


@dataclass(frozen=True, slots=True)
class If(Node):
    """``if c then a [else b] endif``."""

    condition: Node
    then: Node
    otherwise: Node | None


@dataclass(frozen=True, slots=True)
class Call(Node):
    """Function or aggregate call, optionally with ``group by`` keys."""

    name: str
    args: tuple[Node, ...]
    group_by: tuple[str, ...] | None = None


@dataclass(frozen=True, slots=True)
class Where(Node):
    """``operand [where condition]`` filters records by key components."""

    operand: Node
    condition: Node


@dataclass(frozen=True, slots=True)
class Get(Node):
    """``operand [get name]`` replaces values by a key component."""

    operand: Node
    name: str


@dataclass(frozen=True, slots=True)
class Sub(Node):
    """``operand [sub name = value]`` fixes and removes a key component."""

    operand: Node
    name: str
    value: Node


@dataclass(frozen=True, slots=True)
class Rename(Node):
    """``operand [rename a to b, ...]`` renames key components."""

    operand: Node
    pairs: tuple[tuple[str, str], ...]


@dataclass(frozen=True, slots=True)
class With(Node):
    """``with {context} [where condition]: body``.

    The optional condition filters every selection evaluated in the body.
    """

    context: SelectionSpec
    body: Node
    condition: Node | None = None


def children(node: Node) -> tuple[Node, ...]:
    """Return a node's direct child expressions in source order.

    Returns:
        tuple[Node, ...]: Child nodes; literal and leaf nodes have none.
    """
    match node:
        case With(body=body, condition=condition):
            return ((condition,) if condition else ()) + (body,)
        case SetLiteral(items=items):
            return items
        case Unary(operand=operand) | Get(operand=operand) | Rename(operand=operand):
            return (operand,)
        case Binary(left=left, right=right):
            return (left, right)
        case In(operand=operand, values=values):
            return (operand, values)
        case If(condition=condition, then=then, otherwise=otherwise):
            return (condition, then) + ((otherwise,) if otherwise else ())
        case Call(args=args):
            return args
        case Where(operand=operand, condition=condition):
            return (operand, condition)
        case Sub(operand=operand, value=value):
            return (operand, value)
    return ()


def walk(node: Node) -> list[Node]:
    """Return the node and all descendants in pre-order.

    Returns:
        list[Node]: Every node of the tree.
    """
    result: list[Node] = []
    pending = [node]
    while pending:
        current = pending.pop()
        result.append(current)
        pending.extend(reversed(children(current)))
    return result


def _literal_text(value: Literal_ | SetLiteral | _Missing) -> str:
    if isinstance(value, SetLiteral):
        return (
            "{"
            + ", ".join(
                _literal_text(item) if isinstance(item, Literal_) else "…"
                for item in value.items
            )
            + "}"
        )
    if not isinstance(value, Literal_):
        return ""
    match value.kind:
        case "null":
            return "null"
        case "string":
            return f'"{value.value}"'
        case "boolean":
            return str(value.value).lower()
        case "date":
            return f"#{value.value}#"
        case "item":
            return f"[{value.value}]"
    return str(value.value)


__all__ = [
    "AXIS_KEYS",
    "AXIS_PREFIXES",
    "MISSING",
    "AxisName",
    "AxisSelector",
    "Binary",
    "Call",
    "Get",
    "If",
    "In",
    "Item",
    "Literal_",
    "Name",
    "Node",
    "Parameter",
    "Rename",
    "Selection",
    "SelectionSpec",
    "SetLiteral",
    "Span",
    "Sub",
    "TableReported",
    "TypedParameter",
    "Unary",
    "Where",
    "With",
    "children",
    "walk",
]
