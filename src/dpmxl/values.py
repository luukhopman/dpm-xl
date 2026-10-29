"""Runtime values: numbers with interval thresholds, items, text, dates.

Numbers follow the Eurofiling interval arithmetic functions (``iaf:*``) that
EBA validation rules are based on: a number is a value with a symmetric
threshold, so it stands for the interval ``[value - t, value + t]``. Facts
reported with XBRL ``decimals`` get ``t = 0.5 * 10**-decimals`` (``INF`` is
exact); constants and defaults are exact. Sums and differences add
thresholds, products use ``|A*dB| + |B*dA| + dA*dB``, quotients take the
largest deviation of the endpoint quotients, ``abs`` and negation keep the
threshold, and ``min``/``max`` keep the chosen value's threshold. Two numbers
are equal when ``|a - b| <= ta + tb``, i.e. when their intervals overlap.
Selections evaluated with ``interval: false`` drop the threshold, so their
comparisons are exact.

Arithmetic uses [`DECIMAL_CONTEXT`][dpmxl.values.DECIMAL_CONTEXT] (34 significant
digits, as IEEE decimal128), whatever the caller's thread decimal context.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime
from decimal import (
    ROUND_HALF_EVEN,
    Context,
    Decimal,
    DivisionByZero,
    InvalidOperation,
    Overflow,
)
from typing import Any, TypeAlias, cast

from .ast import Item

ZERO = Decimal(0)

DECIMAL_CONTEXT = Context(
    prec=34,
    rounding=ROUND_HALF_EVEN,
    Emax=6144,
    Emin=-6143,
    traps=[DivisionByZero, InvalidOperation, Overflow],
)
"""The decimal context of every operation on numbers (IEEE decimal128)."""

_add = DECIMAL_CONTEXT.add
_subtract = DECIMAL_CONTEXT.subtract
_multiply = DECIMAL_CONTEXT.multiply
_divide = DECIMAL_CONTEXT.divide


@dataclass(frozen=True, slots=True)
class Number:
    """A decimal value with a symmetric tolerance for interval arithmetic.

    A number stands for the interval
    ``[value - tolerance, value + tolerance]``. Build reported facts with
    [`Number.of`][dpmxl.values.Number.of], which derives the tolerance from
    XBRL ``decimals``. Arithmetic operators
    (``+``, ``-``, ``*``, ``/``, unary ``-`` and ``abs``) follow the interval
    rules in the module documentation.

    Attributes:
        value: The amount.
        tolerance: Half-width of the interval; 0 for an exact number.

    Examples:
        >>> Number.of(2, 0) + Number.of(3, 1)
        Number(value=Decimal('5'), tolerance=Decimal('0.55'))
    """

    value: Decimal
    tolerance: Decimal = ZERO

    @classmethod
    def of(
        cls, value: int | str | Decimal, decimals: int | str | None = None
    ) -> Number:
        """Build a number, deriving tolerance from XBRL ``decimals``.

        Args:
            value: The amount.
            decimals: XBRL ``decimals``: an integer, ``"INF"`` (in any case)
                or ``None``, which both mean exact.

        Returns:
            Number: The value with ``0.5 * 10**-decimals`` tolerance, or an
            exact value.

        Raises:
            ValueError: If ``decimals`` is text other than ``INF`` or an
                integer, or puts the tolerance outside the range of
                [`DECIMAL_CONTEXT`][dpmxl.values.DECIMAL_CONTEXT] (beyond about ±6,100).

        Examples:
            >>> Number.of(1204, 0)
            Number(value=Decimal('1204'), tolerance=Decimal('0.5'))
            >>> Number.of("250.4", 1).tolerance, Number.of(1000, -3).tolerance
            (Decimal('0.05'), Decimal('5E+2'))
            >>> Number.of(5, "INF").tolerance
            Decimal('0')
        """
        amount = value if isinstance(value, Decimal) else Decimal(value)
        if decimals is None:
            return cls(amount)
        if isinstance(decimals, str):
            if decimals.strip().casefold() == "inf":
                return cls(amount)
            try:
                decimals = int(decimals)
            except ValueError:
                raise ValueError("not an integer or INF") from None
        exponent = -decimals - 1
        if not DECIMAL_CONTEXT.Etiny() <= exponent <= DECIMAL_CONTEXT.Emax:
            raise ValueError("out of range")
        return cls(amount, Decimal(5).scaleb(exponent, DECIMAL_CONTEXT))

    def exact(self) -> Number:
        """Return the same value without tolerance.

        Returns:
            Number: An exact copy.
        """
        return self if not self.tolerance else Number(self.value)

    @property
    def low(self) -> Decimal:
        """Lower interval bound, ``value - tolerance``.

        Examples:
            >>> Number.of(1204, 0).low, Number.of(1204, 0).high
            (Decimal('1203.5'), Decimal('1204.5'))
        """
        return _subtract(self.value, self.tolerance)

    @property
    def high(self) -> Decimal:
        """Upper interval bound, ``value + tolerance``."""
        return _add(self.value, self.tolerance)

    def __add__(self, other: Number) -> Number:
        """Add values and tolerances.

        Returns:
            Number: The result.
        """
        return Number(
            _add(self.value, other.value), _add(self.tolerance, other.tolerance)
        )

    def __sub__(self, other: Number) -> Number:
        """Subtract values; tolerances add up.

        Returns:
            Number: The result.
        """
        return Number(
            _subtract(self.value, other.value), _add(self.tolerance, other.tolerance)
        )

    def __mul__(self, other: Number) -> Number:
        """Multiply as Eurofiling's ``iaf:numeric-multiply`` does.

        The threshold is ``|A * dB| + |B * dA| + dA * dB``.

        Returns:
            Number: The result.
        """
        value = _multiply(self.value, other.value)
        if not self.tolerance and not other.tolerance:
            return Number(value)
        threshold = _add(
            _add(
                _multiply(self.value, other.tolerance).copy_abs(),
                _multiply(other.value, self.tolerance).copy_abs(),
            ),
            _multiply(self.tolerance, other.tolerance),
        )
        return Number(value, threshold)

    def __truediv__(self, other: Number) -> Number:
        """Divide as Eurofiling's ``iaf:numeric-divide`` does.

        The threshold is the largest deviation of the four endpoint quotients
        ``(A ± dA) / (B ± dB)`` from ``A / B``.

        Returns:
            Number: The quotient.

        Raises:
            ZeroDivisionError: If ``other`` is zero or, as DPM-XL 4.3.4.5
                forbids, an interval that contains zero.
        """
        if other.value == 0:
            raise ZeroDivisionError("division by zero")
        if other.low <= 0 <= other.high:
            raise ZeroDivisionError("division by an interval that contains zero")
        value = _divide(self.value, other.value)
        if not self.tolerance and not other.tolerance:
            return Number(value)
        deviations = [
            _subtract(value, _divide(numerator, denominator)).copy_abs()
            for numerator in (self.high, self.low)
            for denominator in (other.high, other.low)
        ]
        return Number(value, max(deviations))

    def __neg__(self) -> Number:
        """Negate the value.

        Returns:
            Number: The result.
        """
        return Number(self.value.copy_negate(), self.tolerance)

    def __abs__(self) -> Number:
        """Return the absolute value.

        Returns:
            Number: The result.
        """
        return Number(self.value.copy_abs(), self.tolerance)


@dataclass(frozen=True, slots=True)
class ValueSet:
    """A set of distinct scalar values.

    Set literals, ``set-*`` parameters and set operators yield sets. Members are kept in
    first-seen order; numbers are exact, so ``1`` and ``1.0`` are one member. Build sets
    with [`ValueSet.of`][dpmxl.values.ValueSet.of], which removes duplicates by DPM-XL
    equality.
    """

    members: tuple[Value, ...] = ()
    """The members in first-seen order."""

    @classmethod
    def of(cls, values: Iterable[Value]) -> ValueSet:
        """Collect distinct non-null values.

        Returns:
            ValueSet: The set, in first-seen order.

        Raises:
            TypeError: If a value is itself a set.

        Examples:
            >>> values = ValueSet.of([Number.of(1), Number.of("1.0"), None, "a"])
            >>> len(values), Number.of(1) in values, "b" in values
            (2, True, False)
        """
        members: list[Value] = []
        for value in values:
            if value is None:
                continue
            if isinstance(value, ValueSet):
                raise TypeError("a set cannot contain a set")
            if isinstance(value, Number):
                value = value.exact()
            if not any(_same(value, member) for member in members):
                members.append(value)
        return cls(tuple(members))

    def __contains__(self, value: object) -> bool:
        """Whether a member equals ``value`` (numbers by interval overlap).

        Returns:
            bool: Membership.
        """
        return any(_same(cast(Value, value), member) for member in self.members)

    def __len__(self) -> int:
        """Return the number of members.

        Returns:
            int: The size.
        """
        return len(self.members)


def _same(left: Value, right: Value) -> bool:
    try:
        return compare("=", left, right) is True
    except TypeError:
        return False


Value: TypeAlias = Number | Item | str | bool | date | ValueSet | None
"""A runtime value: [`Number`][dpmxl.values.Number], [`Item`][dpmxl.ast.Item],
text, Boolean, date (or date-time), [`ValueSet`][dpmxl.values.ValueSet] or
``None`` (null)."""


def compare(op: str, left: Value, right: Value) -> bool | None:
    """Compare two scalar values with DPM-XL semantics.

    Numbers use interval comparison: ``a = b`` holds when the tolerance
    intervals overlap. Items compare by category and code, ignoring a missing
    category. Null on either side yields null.

    Returns:
        bool | None: The comparison result, or ``None`` for null operands.

    Raises:
        TypeError: When the operands cannot be compared.
        ValueError: When ``op`` is not a comparison operator.

    Examples:
        >>> compare("=", Number.of(1204, 0), Number.of(1205, 0))  # overlap
        True
        >>> compare("=", Number.of(1204, 0), Number.of(1206, 0))
        False
        >>> compare("<", None, Number.of(1)) is None
        True
        >>> compare("=", Item.parse("eba_qEC:qx01"), Item.parse("qx01"))
        True
    """
    if left is None or right is None:
        return None
    if isinstance(left, ValueSet) and isinstance(right, ValueSet) and op in {"=", "!="}:
        # DPM-XL 13.7: sets are equal when each member of one is in the other.
        equal = all(member in right for member in left.members) and all(
            member in left for member in right.members
        )
        return equal if op == "=" else not equal
    if isinstance(left, Number) and isinstance(right, Number):
        difference = _subtract(left.value, right.value)
        tolerance = _add(left.tolerance, right.tolerance)
        match op:
            case "=":
                return difference.copy_abs() <= tolerance
            case "!=":
                return difference.copy_abs() > tolerance
            case "<":
                return difference < tolerance
            case "<=":
                return difference <= tolerance
            case ">":
                return difference > tolerance.copy_negate()
            case ">=":
                return difference >= tolerance.copy_negate()
    if isinstance(left, Item) or isinstance(right, Item):
        if isinstance(left, ValueSet) or isinstance(right, ValueSet):
            raise TypeError(f"cannot compare {type_name(left)} with {type_name(right)}")
        if op not in {"=", "!="}:
            raise TypeError(f"items do not support {op!r}")
        equal = _item_of(left).matches(_item_of(right))
        return equal if op == "=" else not equal
    if isinstance(left, bool) or isinstance(right, bool):
        if not (isinstance(left, bool) and isinstance(right, bool)):
            left, right = _as_bool(left), _as_bool(right)
        if not (isinstance(left, bool) and isinstance(right, bool)):
            raise TypeError(f"cannot compare {type_name(left)} with {type_name(right)}")
        # DPM-XL orders Booleans with false before true.
        match op:
            case "=":
                return left == right
            case "!=":
                return left != right
            case "<":
                return left < right
            case "<=":
                return left <= right
            case ">":
                return left > right
            case ">=":
                return left >= right
        raise ValueError(f"unknown comparison {op!r}")
    if (
        isinstance(left, Number)
        or isinstance(right, Number)
        or isinstance(left, ValueSet)
        or isinstance(right, ValueSet)
    ):
        raise TypeError(
            f"cannot compare {type_name(left)} with {type_name(right)} using {op!r}"
        )
    ordered: Any = left
    other: Any = right
    if type(left) is not type(right):
        if isinstance(left, date) and isinstance(right, date):
            # A date compares with a date-time as its midnight.
            ordered = cast(Any, _moment(left))
            other = cast(Any, _moment(right))
        else:
            ordered, other = str(left), str(right)
    match op:
        case "=":
            return ordered == other
        case "!=":
            return ordered != other
        case "<":
            return ordered < other
        case "<=":
            return ordered <= other
        case ">":
            return ordered > other
        case ">=":
            return ordered >= other
    raise ValueError(f"unknown comparison {op!r}")


def _moment(value: date) -> datetime:
    if isinstance(value, datetime):
        return value
    return datetime(value.year, value.month, value.day)


def _item_of(value: Value) -> Item:
    if isinstance(value, Item):
        return value
    return Item.parse(str(value))


def _as_bool(value: Value) -> Value:
    if isinstance(value, str):
        folded = value.strip().casefold()
        if folded in {"true", "1"}:
            return True
        if folded in {"false", "0"}:
            return False
    return value


def type_name(value: Value) -> str:
    """Return a readable type name for error messages.

    Returns:
        str: For example ``number`` or ``item``.

    Examples:
        >>> type_name(Number.of(1)), type_name("x"), type_name(None)
        ('number', 'string', 'null')
    """
    match value:
        case None:
            return "null"
        case Number():
            return "number"
        case Item():
            return "item"
        case bool():
            return "boolean"
        case date():
            return "date"
        case ValueSet():
            return "set"
    return "string"


def format_value(value: Value) -> str:
    """Format a value for an explanation.

    Numbers use thousands separators and drop trailing zeros; items keep their
    ``category:code`` form in brackets.

    Returns:
        str: Human-readable text.

    Examples:
        >>> from datetime import date
        >>> format_value(Number.of("1234567.50")), format_value(Item.parse("a:b"))
        ('1,234,567.5', '[a:b]')
        >>> format_value(date(2026, 12, 31)), format_value(True), format_value(None)
        ('2026-12-31', 'true', 'null')
        >>> format_value("text")
        '"text"'
    """
    match value:
        case None:
            return "null"
        case Number():
            return format_decimal(value.value)
        case Item():
            return f"[{value}]"
        case bool():
            return "true" if value else "false"
        case date():
            return value.isoformat()
        case ValueSet(members=members):
            return "{" + ", ".join(format_value(member) for member in members) + "}"
    return f'"{value}"'


def format_decimal(value: Decimal) -> str:
    """Format a decimal with thousands separators and no exponent.

    Returns:
        str: For example ``1,204`` or ``-0.075``.

    Examples:
        >>> format_decimal(Decimal("1234567.8900"))
        '1,234,567.89'
    """
    try:
        normalized = value.normalize(DECIMAL_CONTEXT)
    except InvalidOperation:  # pragma: no cover - NaN guards
        return str(value)
    return format(normalized, ",f")


# A computed number with more decimals than any reported value shows this
# many significant digits.
_LONG_FRACTION = 10
_COMPUTED_DIGITS = 6


def format_computed(value: Decimal) -> str:
    """Format a computed decimal, rounding a long fraction for display.

    A division yields up to 34 significant digits. Beyond ten decimals, the
    number shows six significant digits, but keeps every integer digit and
    two decimals:
    ``1.852935352358765...`` reads ``1.85294`` and ``12345.67890123456``
    ``12,345.68``. Shorter fractions, such as the exact difference of two
    reported values, are shown in full, as reported values always are.

    Returns:
        str: The formatted number.

    Examples:
        >>> format_computed(Decimal("1.852935352358765123"))
        '1.85294'
        >>> format_computed(Decimal("12345.67890123456"))
        '12,345.68'
    """
    try:
        normalized = value.normalize(DECIMAL_CONTEXT)
    except InvalidOperation:  # pragma: no cover - NaN guards
        return str(value)
    exponent = normalized.as_tuple().exponent
    if isinstance(exponent, int) and exponent < -_LONG_FRACTION:
        places = max(_COMPUTED_DIGITS - 1 - normalized.adjusted(), 2)
        normalized = normalized.quantize(
            Decimal(1).scaleb(-places), context=DECIMAL_CONTEXT
        )
    return format_decimal(normalized)


__all__ = [
    "DECIMAL_CONTEXT",
    "Number",
    "Value",
    "ValueSet",
    "compare",
    "format_computed",
    "format_decimal",
    "format_value",
    "type_name",
]
