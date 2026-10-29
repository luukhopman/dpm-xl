"""Vectorized DPM-XL evaluation on polars data frames.

Needs the ``columnar`` extra (``pip install "dpm-xl[columnar]"``). The
record-by-record evaluator ([`dpmxl.evaluator`][dpmxl.evaluator]) is the
reference implementation; this module evaluates the same language with the
same semantics on columnar data, so open tables with millions of rows evaluate
in milliseconds per rule.

Anything this module does not implement raises
[`ColumnarUnsupported`][dpmxl.columnar.ColumnarUnsupported], and callers of
[`evaluate_rule_columnar`][dpmxl.columnar.evaluate_rule_columnar] then fall
back to the reference evaluator, so coverage never trades off correctness.
That covers statements and assignments, set operators such as ``union``,
analytic functions, the ``&`` operator, functions other than the aggregates,
``filter``, ``abs``, ``isnull``, ``nvl``, ``match``, ``len`` and
``min``/``max`` (so ``time_shift``, ``annualise``, ``substr``, the
mathematical and the date functions), typed parameter, operation and
table-group references, values that do not fit
``Decimal(38, 12)``, arithmetic that would overflow it, any record error (a
zero divisor or a type error, which the reference evaluator confines to its
record), ordering items and text that may be an item, and a ``default``
standing in for a record another operand has.

Values are ``Decimal(38, 12)``: sums and differences are exact, products and
quotients round to 12 decimals (thresholds of quotients round up), where the
reference evaluator keeps 34 significant digits, so an exact comparison that
hinges on the 13th decimal can differ.

## Frame schema

A [`FrameProvider`][dpmxl.columnar.FrameProvider] returns one row per selected
data point (closed cells times reported open key combinations) with these
columns:

| Column | Type | Content |
| --- | --- | --- |
| ``cell`` (``CELL``) | any | Opaque cell reference, returned in outcomes |
| ``r``, ``c``, ``s`` | text or null | Raw closed coordinates |
| ``k:<code>`` | text, may be categorical | One per open key (see below) |
| ``num`` (``NUM``) | ``DEC`` = ``Decimal(38, 12)`` | Numeric value |
| ``thr`` (``THR``) | ``DEC`` | Threshold, ``0.5·10^-decimals`` (0 if exact) |
| ``txt`` (``TXT``) | text | Text, canonical item or ISO date value |
| ``flag`` (``FLAG``) | Boolean | Boolean value |

Open key columns hold text, canonical items (``category:code``, see
[`canonical_item`][dpmxl.columnar.canonical_item]) or ISO dates.

[`VALUE_COLUMNS`][dpmxl.columnar.VALUE_COLUMNS] is ``(num, thr, txt, flag)``;
all four are null for a cell with no fact, and
[`value_columns`][dpmxl.columnar.value_columns] maps one Python value to them.
A cell and open-key combination appears at most once, and a cell's
coordinates are the same on every row. String columns may be categorical,
which keeps large selections compact.
[`PointsFrameProvider`][dpmxl.columnar.PointsFrameProvider] builds such frames
from any [`DataProvider`][dpmxl.provider.DataProvider].

Inside the evaluator a record set is a [`Frame`][dpmxl.columnar.Frame]: key
columns ``k:<name>`` (``k:r``, ``k:c``, ``k:s`` for varying closed axes, open
keys such as ``k:qEBB``) as canonical strings, plus the same value columns.
Operators natural-join their operands on shared keys exactly like
[`combine`][dpmxl.recordset.combine]. Where an operand with a ``default``
lacks a record another operand has, or an ``if`` condition with a default
lacks a key a branch has, which the reference evaluator fills in with the
default, this module raises
[`ColumnarUnsupported`][dpmxl.columnar.ColumnarUnsupported].

## Threads

[`evaluate_rule_columnar`][dpmxl.columnar.evaluate_rule_columnar] may run
concurrently on one report from several threads (polars releases the GIL).
[`FrameCache`][dpmxl.columnar.FrameCache] is thread-safe and builds each
selection once while other threads asking for it wait for that build. A
provider shared across threads must be safe to read concurrently;
[`PointsFrameProvider`][dpmxl.columnar.PointsFrameProvider] over a
[`MemoryProvider`][dpmxl.provider.MemoryProvider] is.

Examples:
    >>> from dpmxl import MemoryProvider, Number, TableLayout
    >>> from dpmxl.columnar import PointsFrameProvider, evaluate_rule_columnar
    >>> layout = TableLayout("T", rows=("0010", "0020"), columns=("0010",))
    >>> provider = MemoryProvider([layout], {
    ...     ("T", "0010", "0010", None, ()): Number.of(5, 0),
    ...     ("T", "0020", "0010", None, ()): Number.of(-2, 0),
    ... })
    >>> result = evaluate_rule_columnar(
    ...     "{tT, r*, c0010} >= 0", PointsFrameProvider(provider)
    ... )
    >>> result.status, result.passed, result.failed, result.failing_keys
    ('failed', 1, 1, [{'r': '0020'}])
"""

from __future__ import annotations

import re
import threading
from collections import OrderedDict
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import Future
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_CEILING, Context, Decimal
from functools import cached_property
from typing import Any, Literal, Protocol, cast

import polars as pl

from .ast import (
    AXIS_KEYS,
    Binary,
    Call,
    Get,
    If,
    In,
    Item,
    Literal_,
    Name,
    Node,
    Parameter,
    Rename,
    Selection,
    SelectionSpec,
    SetLiteral,
    Sub,
    TableReported,
    Unary,
    Where,
    With,
)
from .evaluator import (
    AGGREGATES,
    _check_call,
    _check_rename,
    _context_condition,
    _contextual,
    _parse_cached,
)
from .provider import (
    CellQuery,
    DataPoint,
    axis_matcher,
    declared_open_keys,
    normalize_code,
)
from .recordset import (
    STANDARD_KEYS,
    EvaluationError,
    UnsupportedError,
    _is_fact,
    resolve_key,
)
from .values import Number, Value, type_name

DEC = pl.Decimal(38, 12)
"""The polars type of the ``num`` and ``thr`` columns: ``Decimal(38, 12)``."""
NUM = "num"
"""Name of the numeric value column."""
THR = "thr"
"""Name of the column holding the interval threshold of ``num``."""
TXT = "txt"
"""Name of the text column: text, canonical items and ISO dates."""
FLAG = "flag"
"""Name of the Boolean value column."""
VALUE_COLUMNS = (NUM, THR, TXT, FLAG)
"""The four value columns, ``("num", "thr", "txt", "flag")``; all null for a
cell with no fact."""
CELL = "cell"
"""Name of the opaque cell-reference column."""
ZERO = Decimal(0)
_SCALE = Decimal("1e-12")

Status = Literal["passed", "failed", "not_applicable", "error", "unsupported"]


class ColumnarUnsupported(Exception):
    """The expression needs the reference evaluator.

    Raised by [`evaluate_rule_columnar`][dpmxl.columnar.evaluate_rule_columnar]
    and the frame helpers for anything this module does not evaluate exactly;
    catch it and call [`evaluate_rule`][dpmxl.evaluator.evaluate_rule]
    instead.
    """


class _RecordError(ColumnarUnsupported):
    """A type or pattern error in some records.

    The reference evaluator fails only those records, which a join, filter,
    where or ``if`` may still drop (see ``dpmxl.evaluator._Failed``), so it
    decides whether the rule is an error.
    """


class FrameProvider(Protocol):
    """Columnar report data for the columnar evaluator.

    The columnar counterpart of [`DataProvider`][dpmxl.provider.DataProvider].
    ``select_frame`` returns one row per selected data point (closed cells
    times reported open key combinations) with columns ``cell`` (an opaque
    cell reference), ``r``, ``c``, ``s`` (raw coordinates or null),
    ``k:<code>`` for each open key (text, items or ISO dates), and the value
    columns ``num``, ``thr``, ``txt``, ``flag`` (all null when the cell was
    not reported). A cell and open key combination appears at most once, and
    a cell's coordinates are the same on every row. String columns may be
    categorical, which keeps large selections compact. See the frame schema
    in the [`dpmxl.columnar`][dpmxl.columnar] module documentation.
    """

    def select_frame(self, query: CellQuery) -> pl.DataFrame:
        """Return the selected data points as a frame.

        Raises:
            LookupError: If the table does not exist in the release.
        """
        ...

    def table_reported(self, table: str) -> bool | None:
        """Answer ``{v_TABLE}``: whether the report's filing indicators include it.

        Returns ``None`` when the provider cannot tell.
        """
        ...

    def parameter(self, name: str) -> Value:
        """Return a report parameter such as ``refPeriod``, or ``None``."""
        ...


@dataclass(frozen=True)
class Frame:
    """A record set: key names plus a frame of key and value columns.

    Attributes:
        keys: Key names, such as ``("c",)`` or ``("qCPI",)``.
        df: One row per record: a ``k:<name>`` column per key and the value
            columns ``num``, ``thr``, ``txt`` and ``flag``.
        has_default: Whether the records come from a selection with a
            ``default`` through per-record operations, so that the reference
            evaluator fills in a default for keys they lack (see
            [`Recordset`][dpmxl.recordset.Recordset]).
    """

    keys: tuple[str, ...]
    df: pl.DataFrame
    has_default: bool = False

    @cached_property
    def kinds(self) -> frozenset[str]:
        """Value columns holding at least one non-null value (one scan)."""
        if not self.df.height:
            return frozenset()
        present = self.df.select(
            [pl.col(column).is_not_null().any() for column in (NUM, TXT, FLAG)]
        ).row(0)
        return frozenset(
            column
            for column, found in zip((NUM, TXT, FLAG), present, strict=True)
            if found
        )

    @property
    def key_columns(self) -> list[str]:
        """Frame column names of the keys."""
        return [_key(name) for name in self.keys]


def _key(name: str) -> str:
    return f"k:{name}"


def canonical_item(item: Item) -> str:
    """Return the canonical text of an item: ``category:code`` or ``code``.

    Returns:
        str: The canonical form used in ``txt`` and open key columns.

    Examples:
        >>> from dpmxl import Item
        >>> canonical_item(Item.parse("eba_qEC:qx01"))
        'qEC:qx01'
    """
    return f"{item.category}:{item.code}" if item.category else item.code


def value_columns(value: Value) -> dict[str, Any]:
    """Split a scalar value into the four value columns.

    Numbers fill ``num`` and ``thr``; Booleans ``flag``; text, items
    (canonical, see [`canonical_item`][dpmxl.columnar.canonical_item]) and
    dates (ISO) ``txt``. ``None`` leaves all four null.

    Returns:
        dict[str, Any]: ``num``, ``thr``, ``txt`` and ``flag`` entries.

    Examples:
        >>> from dpmxl import Number
        >>> value_columns(Number.of("1.5", 1))
        {'num': Decimal('1.5'), 'thr': Decimal('0.05'), 'txt': None, 'flag': None}
        >>> value_columns(True)
        {'num': None, 'thr': None, 'txt': None, 'flag': True}

    Raises:
        ColumnarUnsupported: For a number or threshold that ``Decimal(38, 12)``
            does not hold exactly.
    """
    row: dict[str, Any] = {NUM: None, THR: None, TXT: None, FLAG: None}
    match value:
        case None:
            pass
        case bool():
            row[FLAG] = value
        case Number():
            row[NUM] = _exact(value.value)
            row[THR] = _exact(value.tolerance)
        case Item():
            row[TXT] = canonical_item(value)
        case date():
            row[TXT] = value.isoformat()
        case _:
            row[TXT] = str(value)
    return row


# Decimal(38, 12) holds 26 integer digits and 12 decimals.
_LIMIT = Decimal("1e26")
_WIDE = Context(prec=60)


def _exact(value: Decimal) -> Decimal:
    """Return a decimal that ``Decimal(38, 12)`` holds without rounding.

    Returns:
        Decimal: The value.

    Raises:
        ColumnarUnsupported: When the value is out of range or has more than
            12 decimals; polars would make it null or round it.
    """
    exponent = value.normalize(_WIDE).as_tuple().exponent if value.is_finite() else 0
    if not (
        isinstance(exponent, int)
        and value.is_finite()
        and value.copy_abs() < _LIMIT
        and exponent >= -12
    ):
        raise ColumnarUnsupported(f"{value} does not fit Decimal(38, 12)")
    return value


def scalar_frame(value: Value) -> Frame:
    """Build a key-less one-row frame holding one value.

    Returns:
        Frame: The scalar, with the columns of
        [`value_columns`][dpmxl.columnar.value_columns].
    """
    return Frame((), pl.DataFrame([value_columns(value)], schema=_VALUE_SCHEMA))


_VALUE_SCHEMA = {NUM: DEC, THR: DEC, TXT: pl.String, FLAG: pl.Boolean}


def frame_from_points(
    points: Sequence[DataPoint], open_keys: Sequence[str] = ()
) -> pl.DataFrame:
    """Adapt data points to the frame layout of a ``FrameProvider``.

    Builds the columns described by
    [`FrameProvider`][dpmxl.columnar.FrameProvider] from
    [`DataPoint`][dpmxl.provider.DataPoint] objects; ``cell`` holds
    ``repr(point.ref)``.

    Args:
        points: Selected data points.
        open_keys: The table's open key names, kept even without points.

    Returns:
        pl.DataFrame: One row per point.

    Raises:
        ColumnarUnsupported: For numeric or Boolean key values, items
            without a category, or numbers ``Decimal(38, 12)`` does not hold.
    """
    key_names: list[str] = list(open_keys)
    for point in points:
        key_names.extend(name for name in point.keys if name not in key_names)
    rows = []
    nums: list[Decimal | None] = []
    thrs: list[Decimal | None] = []
    for point in points:
        row: dict[str, Any] = {
            CELL: repr(point.ref),
            "r": point.row,
            "c": point.column,
            "s": point.sheet,
        }
        for name in key_names:
            value = point.keys.get(name)
            if isinstance(value, Number | bool):
                # Key columns are text, which would compare "10" with 10.
                raise ColumnarUnsupported(f"{type_name(value)} key {name}")
            row[_key(name)] = _key_text(value)
        if isinstance(point.value, Item) and point.value.category is None:
            # Its text has no category separator, so nothing would stop the
            # txt column from ordering it as text.
            raise ColumnarUnsupported("item without a category")
        value = point.value
        if isinstance(value, Number):
            # Checked in bulk below, not number by number.
            nums.append(value.value)
            thrs.append(value.tolerance)
            row[TXT] = row[FLAG] = None
        else:
            nums.append(None)
            thrs.append(None)
            columns = value_columns(value)
            row[TXT], row[FLAG] = columns[TXT], columns[FLAG]
        rows.append(row)
    schema: dict[str, Any] = {
        CELL: pl.String,
        "r": pl.String,
        "c": pl.String,
        "s": pl.String,
    }
    schema.update({_key(name): pl.String for name in key_names})
    schema.update({TXT: pl.String, FLAG: pl.Boolean})
    return (
        pl.DataFrame(rows, schema=schema)
        .with_columns(_decimals(NUM, nums), _decimals(THR, thrs))
        .select(*[name for name in schema if name not in VALUE_COLUMNS], *VALUE_COLUMNS)
    )


def _decimals(name: str, values: list[Decimal | None]) -> pl.Series:
    """Build a ``Decimal(38, 12)`` column, checking every value fits exactly.

    Returns:
        pl.Series: The column.

    Raises:
        ColumnarUnsupported: For a value out of range or with more than 12
            decimals, which polars would reject or round.
    """
    try:
        # Inferring the type finds the largest scale in one pass.
        series = pl.Series(name, values)
        if isinstance(series.dtype, pl.Decimal) and (series.dtype.scale or 0) > 12:
            # Trailing zeros (1.0000000000000) fit; anything else does not.
            for value in values:
                if value is not None:
                    _exact(value)
        return series.cast(DEC, strict=True)
    except (
        RuntimeError,
        pl.exceptions.PolarsError,
        pl.exceptions.PanicException,
    ) as error:
        raise ColumnarUnsupported(f"{name} does not fit Decimal(38, 12)") from error


def _key_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, Item):
        return canonical_item(value)
    if isinstance(value, Number):
        return format(value.value, "f")
    return str(value)


class PointsFrameProvider:
    """Adapt any ``DataProvider`` to ``FrameProvider``.

    Each ``select_frame`` call converts the wrapped
    [`DataProvider`][dpmxl.provider.DataProvider]'s points with
    [`frame_from_points`][dpmxl.columnar.frame_from_points]; the other methods
    delegate. It is as thread-safe as the wrapped provider.

    Examples:
        >>> from dpmxl import CellQuery, MemoryProvider, Number, TableLayout
        >>> layout = TableLayout("T", columns=("0010",), open_keys=("qCPI",))
        >>> provider = MemoryProvider(
        ...     [layout], {("T", None, "0010", None, (("qCPI", "A"),)): Number.of(7, 0)}
        ... )
        >>> frame = PointsFrameProvider(provider).select_frame(CellQuery("T"))
        >>> frame.columns
        ['cell', 'r', 'c', 's', 'k:qCPI', 'num', 'thr', 'txt', 'flag']
        >>> frame.select("k:qCPI", "num", "thr").row(0)
        ('A', Decimal('7.000000000000'), Decimal('0.500000000000'))
    """

    def __init__(self, provider: Any) -> None:
        """Wrap a record provider.

        Args:
            provider: A [`DataProvider`][dpmxl.provider.DataProvider].
        """
        self.provider = provider

    def select_frame(self, query: CellQuery) -> pl.DataFrame:
        """Return the provider's points as a frame.

        Returns:
            pl.DataFrame: The selection.
        """
        return frame_from_points(
            list(self.provider.select(query)),
            declared_open_keys(self.provider, query.table),
        )

    def table_reported(self, table: str) -> bool | None:
        """Delegate to the wrapped provider.

        Returns:
            bool | None: Filing-indicator state.
        """
        return self.provider.table_reported(table)

    def parameter(self, name: str) -> Value:
        """Delegate to the wrapped provider.

        Returns:
            Value: The parameter.
        """
        return self.provider.parameter(name)


class FrameCache:
    """Selection frames shared by every rule evaluated against one report.

    Rules reuse the same selections, but on massive open tables a selection
    can hold millions of rows, so the cache keeps at most ``max_rows`` rows
    and evicts the least recently used selections beyond that.

    Rules may be evaluated concurrently from several threads (polars
    releases the GIL): the cache is thread-safe, and
    [`raw_frame`][dpmxl.columnar.FrameCache.raw_frame] and
    [`selection`][dpmxl.columnar.FrameCache.selection] build each missing
    entry once while other threads asking for it wait for that build.
    """

    def __init__(self, max_rows: int = 20_000_000) -> None:
        """Create an empty cache.

        Args:
            max_rows: Total rows kept across cached selection frames.
        """
        self.max_rows = max_rows
        self.raw: OrderedDict[CellQuery, pl.DataFrame] = OrderedDict()
        self.frames: OrderedDict[SelectionSpec, Frame] = OrderedDict()
        self._rows = 0
        self._lock = threading.Lock()
        self._building: dict[CellQuery | SelectionSpec, Future[Any]] = {}

    def get_raw(self, query: CellQuery) -> pl.DataFrame | None:
        """Return a cached provider frame.

        Returns:
            pl.DataFrame | None: The frame, or ``None``.
        """
        with self._lock:
            frame = self.raw.get(query)
            if frame is not None:
                self.raw.move_to_end(query)
            return frame

    def get_frame(self, spec: SelectionSpec) -> Frame | None:
        """Return a cached selection record set.

        Returns:
            Frame | None: The frame, or ``None``.
        """
        with self._lock:
            frame = self.frames.get(spec)
            if frame is not None:
                self.frames.move_to_end(spec)
            return frame

    def put_raw(self, query: CellQuery, frame: pl.DataFrame) -> None:
        """Cache a provider frame within the row budget."""
        with self._lock:
            self._put(self.raw, query, frame.height, frame)

    def put_frame(self, spec: SelectionSpec, frame: Frame) -> None:
        """Cache a selection record set within the row budget."""
        with self._lock:
            self._put(self.frames, spec, frame.df.height, frame)

    def raw_frame(
        self, query: CellQuery, build: Callable[[], pl.DataFrame]
    ) -> pl.DataFrame:
        """Return a provider frame, building and caching it once.

        Returns:
            pl.DataFrame: The cached or newly built frame.
        """
        return self._once(self.raw, query, build, lambda frame: frame.height)

    def selection(self, spec: SelectionSpec, build: Callable[[], Frame]) -> Frame:
        """Return a selection record set, building and caching it once.

        Returns:
            Frame: The cached or newly built record set.
        """
        return self._once(self.frames, spec, build, lambda frame: frame.df.height)

    def _once(
        self,
        store: OrderedDict[Any, Any],
        key: CellQuery | SelectionSpec,
        build: Callable[[], Any],
        height: Callable[[Any], int],
    ) -> Any:
        with self._lock:
            cached = store.get(key)
            if cached is not None:
                store.move_to_end(key)
                return cached
            pending = self._building.get(key)
            owner = pending is None
            if pending is None:
                pending = self._building[key] = Future()
        if not owner:
            # Another rule is building it; its error is this rule's too.
            return pending.result()
        try:
            value = build()
        except BaseException as error:
            with self._lock:
                del self._building[key]
            pending.set_exception(error)
            raise
        with self._lock:
            self._put(store, key, height(value), value)
            del self._building[key]
        pending.set_result(value)
        return value

    def _put(
        self, store: OrderedDict[Any, Any], key: Any, height: int, value: Any
    ) -> None:
        previous = store.pop(key, None)
        if previous is not None:
            self._rows -= (
                previous.height
                if isinstance(previous, pl.DataFrame)
                else previous.df.height
            )
        store[key] = value
        self._rows += height
        self._evict()

    def _evict(self) -> None:
        while self._rows > self.max_rows and (self.raw or self.frames):
            store: OrderedDict[Any, Any] = (
                self.raw if len(self.raw) >= len(self.frames) else self.frames
            )
            if not store:
                store = self.frames if self.frames else self.raw
            _key, evicted = store.popitem(last=False)
            height = (
                evicted.height
                if isinstance(evicted, pl.DataFrame)
                else evicted.df.height
            )
            self._rows -= height


# Evaluation ------------------------------------------------------------------


class ColumnarEvaluator:
    """Evaluate one expression tree on frames.

    Most callers want
    [`evaluate_rule_columnar`][dpmxl.columnar.evaluate_rule_columnar], which
    also applies the precondition and turns the result into counts.
    ``evaluate`` raises [`ColumnarUnsupported`][dpmxl.columnar.ColumnarUnsupported]
    for anything it does not implement. Use one evaluator per expression; the
    [`FrameCache`][dpmxl.columnar.FrameCache] is what rules share.
    """

    def __init__(
        self, provider: FrameProvider, cache: FrameCache | None = None
    ) -> None:
        """Bind the provider.

        Args:
            provider: Columnar report data.
            cache: Selections shared across rules of one report.
        """
        self.provider = provider
        self.cache = cache or FrameCache()
        self._conditions: list[Node] = []
        self._overridden = False

    def evaluate(self, node: Node, context: SelectionSpec | None = None) -> Frame:
        """Evaluate a node under an inherited ``with`` context.

        Returns:
            Frame: The node's records.

        Raises:
            ColumnarUnsupported: For constructs the reference engine must run.
            UnsupportedError: For constructs no engine supports.
            EvaluationError: For invalid expressions or data.
        """
        context = context or SelectionSpec()
        match node:
            case With(context=inner, body=body, condition=condition):
                if condition is not None:
                    self._conditions.append(condition)
                try:
                    return self.evaluate(body, inner.merged_into(context))
                finally:
                    if condition is not None:
                        self._conditions.pop()
            case Literal_():
                return scalar_frame(_literal_value(node))
            case Selection(spec=spec):
                frame = self._selection(spec.merged_into(context))
                if self._overridden:
                    return frame
                for condition in self._conditions:
                    kept = _context_condition(
                        condition,
                        frame.keys,
                        lambda name: self.provider.parameter(name) is not None,
                    )
                    if kept is not None:
                        frame = self._where(frame, kept)
                return frame
            case TableReported(table=table):
                return scalar_frame(self.provider.table_reported(table))
            case Parameter(name=name):
                return scalar_frame(self.provider.parameter(name))
            case Name():
                raise ColumnarUnsupported("bare names outside where clauses")
            case Unary(op=op, operand=operand):
                return _unary(op, self.evaluate(operand, context))
            case Binary():
                # A left-deep chain (a long sum) in a loop, as in the
                # reference evaluator.
                spine = [node]
                while isinstance(spine[-1].left, Binary):
                    spine.append(spine[-1].left)
                frame = self.evaluate(spine[-1].left, context)
                for current in reversed(spine):
                    _binary_nodes(current)
                    frame = _binary(
                        current.op, frame, self.evaluate(current.right, context)
                    )
                return frame
            case In(operand=operand, values=SetLiteral() as values):
                return _membership(
                    self.evaluate(operand, context), values, self, context
                )
            case If(condition=condition, then=then, otherwise=otherwise):
                verdicts = self.evaluate(condition, context)
                outcome = self._branch(then, context)
                return _conditional(
                    verdicts,
                    outcome,
                    self._branch(otherwise, context) if otherwise is not None else None,
                )
            case Call():
                return self._call(node, context)
            case Where(operand=operand, condition=condition):
                return self._where(
                    self._clause_operand(operand, context),
                    condition,
                )
            case Get(operand=operand, name=name):
                return self._get(self.evaluate(operand, context), name)
            case Sub(operand=operand, name=name, value=value):
                return self._sub(self._clause_operand(operand, context), name, value)
            case Rename(operand=operand, pairs=pairs):
                return self._rename(self.evaluate(operand, context), pairs)
            case SetLiteral():
                raise ColumnarUnsupported("set values")
        raise ColumnarUnsupported(type(node).__name__)

    def _branch(self, node: Node, context: SelectionSpec) -> Frame:
        # An error in a branch fails only the records that take the branch
        # (see dpmxl.evaluator._Failed); the reference evaluator tracks that.
        try:
            return self.evaluate(node, context)
        except UnsupportedError:
            raise
        except EvaluationError as error:
            raise ColumnarUnsupported(f"error in a branch: {error}") from error

    def _clause_operand(self, operand: Node, context: SelectionSpec) -> Frame:
        # DPM-XL 3.2.6: a where or sub on a selection fully overrides the
        # with-where.
        saved = self._overridden
        self._overridden = isinstance(operand, Selection | Where | Sub)
        try:
            return self.evaluate(operand, context)
        finally:
            self._overridden = saved

    # Selections -------------------------------------------------------------

    def _selection(self, spec: SelectionSpec) -> Frame:
        if isinstance(spec.default, SetLiteral):
            raise ColumnarUnsupported("a set default")
        if spec.table_group is not None or spec.operation is not None:
            raise ColumnarUnsupported("table group and operation references")
        if not spec.table:
            raise EvaluationError(f"selection {spec.text()} has no table")
        return self.cache.selection(spec, lambda: self._build_selection(spec))

    def _build_selection(self, spec: SelectionSpec) -> Frame:
        assert spec.table is not None
        query = CellQuery(spec.table, spec.rows, spec.columns, spec.sheets)
        raw = self.cache.raw_frame(query, lambda: self._select_frame(query))
        return _build_selection(raw, spec)

    def _select_frame(self, query: CellQuery) -> pl.DataFrame:
        try:
            return self.provider.select_frame(query)
        except LookupError as error:
            raise EvaluationError(str(error)) from error

    # Calls ------------------------------------------------------------------

    def _call(self, node: Call, context: SelectionSpec) -> Frame:
        name = node.name
        _check_call(node)
        if name == "time_shift":
            # Even without another report, a date key can be shifted.
            raise ColumnarUnsupported("time_shift")
        if name == "annualise":
            raise ColumnarUnsupported("annualise")
        if name in AGGREGATES and len(node.args) == 1:
            return _aggregate(name, self.evaluate(node.args[0], context), node.group_by)
        if node.group_by is not None:
            raise EvaluationError(f"group by is not allowed in {name}")
        if name == "filter":
            # Like a branch, the data's records the condition drops may fail.
            return _filter(
                self._branch(node.args[0], context),
                self.evaluate(node.args[1], context),
            )
        args = [self.evaluate(arg, context) for arg in node.args]
        if name == "abs":
            return _map_numeric(args[0], lambda num, thr: (num.abs(), thr))
        if name == "isnull":
            frame = args[0]
            return _with_values(frame, flag=_is_null())
        if name == "nvl":
            return _nvl(args[0], args[1])
        if name == "match":
            return _match(args[0], args[1])
        if name in {"max", "min"}:
            return _extreme(name, args)
        if name in {"len", "length"}:
            return _length(args[0])
        raise ColumnarUnsupported(f"function {name}")

    # Clauses ----------------------------------------------------------------

    def _where(self, frame: Frame, condition: Node) -> Frame:
        if not frame.keys:
            if frame.df.height:
                raise ColumnarUnsupported("where on a key-less operand")
            return frame
        checks: list[pl.Expr] = []
        predicate = _key_predicate(condition, frame.keys, self.provider, checks)
        _require_text_or_items(frame.df, checks)
        return Frame(
            frame.keys, frame.df.filter(predicate.fill_null(False)), frame.has_default
        )

    def _get(self, frame: Frame, name: str) -> Frame:
        key = resolve_key(name, frame.keys)
        if key is None and _contextual(name) is not None:
            raise ColumnarUnsupported("contextual components")
        if key is None:
            value = self.provider.parameter(name)
            if value is None:
                raise EvaluationError(f"unknown key component or parameter {name!r}")
            columns = value_columns(value)
            return Frame(
                frame.keys,
                frame.df.with_columns(
                    pl.lit(columns[NUM], DEC).alias(NUM),
                    pl.lit(columns[THR], DEC).alias(THR),
                    pl.lit(columns[TXT], pl.String).alias(TXT),
                    pl.lit(columns[FLAG], pl.Boolean).alias(FLAG),
                ),
            )
        # DPM-XL 11.3.6: records with a null fact value are omitted.
        return Frame(
            frame.keys,
            frame.df.filter(~_is_null()).with_columns(
                pl.lit(None, DEC).alias(NUM),
                pl.lit(None, DEC).alias(THR),
                _key_text_column(key).alias(TXT),
                pl.lit(None, pl.Boolean).alias(FLAG),
            ),
        )

    def _sub(self, frame: Frame, name: str, value: Node) -> Frame:
        key = resolve_key(name, frame.keys)
        if key is None:
            raise EvaluationError(f"unknown key component {name!r}")
        fixed = _literal_key(value, self.provider)
        checks: list[pl.Expr] = []
        test = _key_equals(_key_text_column(key), fixed, checks)
        _require_text_or_items(frame.df, checks)
        df = frame.df.filter(test).drop(_key(key))
        keys = tuple(item for item in frame.keys if item != key)
        return Frame(keys, df, frame.has_default)

    def _rename(self, frame: Frame, pairs: tuple[tuple[str, str], ...]) -> Frame:
        keys = list(frame.keys)
        mapping: dict[str, str] = {}
        for old, new in pairs:
            key = resolve_key(old, keys)
            if key is None:
                raise EvaluationError(f"unknown key component {old!r}")
            _check_rename(new, [name for name in keys if name != key])
            keys[keys.index(key)] = new
            mapping[_key(key)] = _key(new)
        return Frame(tuple(keys), frame.df.rename(mapping), frame.has_default)


def _literal_value(node: Literal_) -> Value:
    if node.kind == "number" and isinstance(node.value, Decimal):
        return Number(node.value)
    return cast(Value, node.value)


# Selection building ------------------------------------------------------------


def normalize_code_expr(column: pl.Expr) -> pl.Expr:
    """Vectorized [`normalize_code`][dpmxl.provider.normalize_code].

    Returns:
        pl.Expr: Numeric codes zero-padded to four digits, others upper-case.
    """
    text = column.str.strip_chars()
    return (
        pl.when(text.str.contains(r"^\d+$"))
        .then(text.str.zfill(4))
        .otherwise(text.str.to_uppercase())
    )


def _build_selection(raw: pl.DataFrame, spec: SelectionSpec) -> Frame:
    axes = list(AXIS_KEYS.values())
    # Coordinates belong to cells, and a selection repeats each cell once per
    # open key combination; decide axis keys, normalize codes and look for
    # repeated keys on the distinct cells, not on every data point.
    cells = (
        raw.select(CELL, *axes).unique(subset=[CELL])
        if CELL in raw.columns
        else raw.select(*axes).unique()
    )
    axis_keys: list[str] = []
    for key in axes:
        # DPM-XL 3.1.6: a key only when more than one coordinate is present.
        codes = cells.get_column(key).drop_nulls().cast(pl.String).unique().to_list()
        if len([code for code in codes if code != "*"]) > 1:
            axis_keys.append(key)
    open_keys = [column[2:] for column in raw.columns if column.startswith("k:")]
    keys = (*axis_keys, *open_keys)
    missing = pl.all_horizontal(pl.col(column).is_null() for column in VALUE_COLUMNS)
    df = raw
    for key in axis_keys:
        codes = cells.select(pl.col(key).unique()).with_columns(
            normalize_code_expr(pl.col(key).cast(pl.String)).alias(_key(key))
        )
        df = df.join(codes, on=key, how="left", maintain_order="left")
        cells = cells.join(codes, on=key, how="left", maintain_order="left")
    df = df.select(
        *[_key(key) for key in axis_keys],
        *[_key(key) for key in open_keys],
        *VALUE_COLUMNS,
    )
    # Records are unique per cell and open key combination, so keys repeat
    # only when two cells share their key coordinates.
    repeats = (
        cells.height > 1
        and cells.select([_key(key) for key in axis_keys]).is_duplicated().any()
        if axis_keys
        else cells.height > 1
    )
    if df.height > 1 and repeats:
        # Keep one record per key, preferring a reported value (as the
        # reference evaluator does when a key repeats).
        subset = [_key(key) for key in keys]
        df = df.sort(missing.cast(pl.Int8), maintain_order=True)
        df = (
            df.unique(subset=subset, keep="first", maintain_order=True)
            if subset
            else df.head(1)
        )
    default = spec.default
    if isinstance(default, Literal_):
        filler = value_columns(_literal_value(default))
        value_exprs = [
            pl.when(missing)
            .then(pl.lit(filler[column], _VALUE_SCHEMA[column]))
            .otherwise(pl.col(column))
            .alias(column)
            for column in VALUE_COLUMNS
        ]
        df = df.with_columns(value_exprs)
    if spec.interval:
        threshold = pl.when(pl.col(NUM).is_not_null()).then(
            pl.col(THR).fill_null(pl.lit(ZERO, DEC))
        )
    else:
        threshold = pl.when(pl.col(NUM).is_not_null()).then(pl.lit(ZERO, DEC))
    df = df.with_columns(threshold.cast(DEC).alias(THR))
    return Frame(keys, df, isinstance(default, Literal_))


# Joining -----------------------------------------------------------------------


def _check_structure(frames: Sequence[Frame]) -> None:
    """Columnar :func:`dpmxl.recordset.check_structure` (DPM-XL 2.2.3.1).

    Raises:
        EvaluationError: When the structures are incompatible.
    """
    keyed = [frame for frame in frames if frame.keys]
    if len(keyed) < 2:
        return
    reference = max(keyed, key=lambda frame: len(frame.keys))
    for frame in keyed:
        if frame is reference:
            continue
        if not set(frame.keys) <= set(reference.keys):
            raise EvaluationError(
                "operands have incompatible keys "
                f"({', '.join(frame.keys)}) and ({', '.join(reference.keys)})"
            )
        common = [_key(key) for key in frame.keys if key in STANDARD_KEYS]
        if not common or not frame.df.height or not reference.df.height:
            continue
        left = frame.df.select(common).unique()
        right = reference.df.select(common).unique()
        if (
            left.height != right.height
            or left.join(right, on=common, how="anti").height
        ):
            names = ", ".join(column[2:] for column in common)
            raise EvaluationError(
                f"standard keys {names} do not contain the same values"
            )


def _aligned(frames: Sequence[Frame]) -> tuple[tuple[str, ...], pl.DataFrame] | None:
    """Combine operands column-wise when their rows already line up.

    Selections from one open table come back in the same key order, so an
    operator over them needs no join. Operands qualify when every keyed
    operand has the same keys, the same height and equal key columns
    (checked, not assumed); scalars broadcast. Otherwise ``None``.

    Returns:
        tuple[tuple[str, ...], pl.DataFrame] | None: Keys and the frame.
    """
    keyed = [frame for frame in frames if frame.keys]
    if len(keyed) < 2:
        return None
    first = keyed[0]
    columns = first.key_columns
    for frame in keyed[1:]:
        if frame.keys != first.keys or frame.df.height != first.df.height:
            return None
    reference = first.df.select(columns)
    for frame in keyed[1:]:
        if frame.df is first.df:
            continue
        if not frame.df.select(columns).equals(reference):
            return None
    parts: list[pl.Series | pl.Expr] = list(reference.get_columns())
    for index, frame in enumerate(frames):
        if frame.keys:
            parts.extend(
                frame.df.get_column(column).alias(f"{column}_{index}")
                for column in VALUE_COLUMNS
            )
        else:
            row = (
                frame.df.row(0, named=True)
                if frame.df.height
                else dict.fromkeys(VALUE_COLUMNS)
            )
            parts.extend(
                pl.repeat(
                    row[column],
                    first.df.height,
                    dtype=_VALUE_SCHEMA[column],
                    eager=True,
                ).alias(f"{column}_{index}")
                for column in VALUE_COLUMNS
            )
    for frame in frames:
        if not frame.keys and not frame.df.height:
            # An empty scalar operand: nothing to combine.
            return first.keys, pl.DataFrame(parts).head(0)
    return first.keys, pl.DataFrame(parts)


def _joined(frames: Sequence[Frame]) -> tuple[tuple[str, ...], pl.DataFrame]:
    """Natural-join frames; value columns are suffixed with ``_<index>``.

    Returns:
        tuple[tuple[str, ...], pl.DataFrame]: Result keys and the joined frame.

    Raises:
        EvaluationError: On operands with unrelated keys.
        ColumnarUnsupported: Where a default would stand in for a record.
    """
    _check_structure(frames)
    if any(
        not frame.keys and not frame.df.height and frame.has_default for frame in frames
    ):
        # The reference evaluator takes the default of an empty key-less operand.
        raise ColumnarUnsupported("a default for a missing key-less record")
    aligned = _aligned(frames)
    if aligned is not None:
        return aligned
    _require_partners(frames)
    keys: list[str] = []
    result: pl.DataFrame | None = None
    for index, frame in enumerate(frames):
        renamed = frame.df.rename(
            {column: f"{column}_{index}" for column in VALUE_COLUMNS}
        )
        if result is None:
            result = renamed
        else:
            common = [_key(key) for key in frame.keys if key in keys]
            if common:
                result = result.join(renamed, on=common, how="inner")
            else:
                result = result.join(renamed, how="cross")
        keys.extend(key for key in frame.keys if key not in keys)
    assert result is not None
    return tuple(keys), result


def _require_partners(frames: Sequence[Frame]) -> None:
    """Leave defaults standing in for missing records to the reference evaluator.

    [`combine`][dpmxl.recordset.combine] fills in an operand's default where
    another operand with its keys has a record it lacks; an inner join would
    drop that record instead.

    Raises:
        ColumnarUnsupported: When an operand with a default lacks a partner.
    """
    for frame in frames:
        if not frame.has_default or not frame.keys:
            continue
        columns = frame.key_columns
        mine = frame.df.select(columns).unique()
        for other in frames:
            if other is frame or not set(frame.keys) <= set(other.keys):
                continue
            theirs = other.df.select(columns).unique()
            if theirs.join(mine, on=columns, how="anti", nulls_equal=True).height:
                raise ColumnarUnsupported("a default for records an operand lacks")


def _all_defaults(frames: Sequence[Frame]) -> bool:
    """Whether the result of combining frames has a default, as in ``combine``.

    Returns:
        bool: True when every keyed frame has a default.
    """
    keyed = [frame for frame in frames if frame.keys]
    return bool(keyed) and all(frame.has_default for frame in keyed)


def _combine(frames: Sequence[Frame], outputs: Mapping[str, pl.Expr]) -> Frame:
    keys, df = _joined(frames)
    selected = [pl.col(_key(key)) for key in keys]
    selected.extend(
        outputs.get(column, pl.lit(None, _VALUE_SCHEMA[column]))
        .cast(_VALUE_SCHEMA[column])
        .alias(column)
        for column in VALUE_COLUMNS
    )
    return Frame(keys, df.select(selected), _all_defaults(frames))


def _c(column: str, index: int) -> pl.Expr:
    return pl.col(f"{column}_{index}")


def _is_null(index: int | None = None) -> pl.Expr:
    if index is None:
        return pl.all_horizontal(pl.col(column).is_null() for column in VALUE_COLUMNS)
    return pl.all_horizontal(_c(column, index).is_null() for column in VALUE_COLUMNS)


def _with_values(frame: Frame, **values: pl.Expr) -> Frame:
    exprs = [
        values.get(column, pl.lit(None, _VALUE_SCHEMA[column]))
        .cast(_VALUE_SCHEMA[column])
        .alias(column)
        for column in VALUE_COLUMNS
    ]
    return Frame(frame.keys, frame.df.with_columns(exprs), frame.has_default)


def _require_numeric(frames: Sequence[Frame], operation: str) -> None:
    for frame in frames:
        if frame.kinds & {TXT, FLAG}:
            raise _RecordError(f"{operation} needs numbers")


# Operators ---------------------------------------------------------------------


def _unary(op: str, frame: Frame) -> Frame:
    if op == "not":
        if frame.kinds & {NUM, TXT}:
            raise _RecordError("not needs a boolean")
        return _with_values(frame, flag=~pl.col(FLAG))
    _require_numeric([frame], f"unary {op}")
    if op == "-":
        return _with_values(frame, num=-pl.col(NUM), thr=pl.col(THR))
    return frame


def _binary(op: str, left: Frame, right: Frame) -> Frame:
    frames = (left, right)
    if op in {"+", "-", "*", "/"}:
        _require_numeric(frames, op)
        a, b = _c(NUM, 0), _c(NUM, 1)
        ta, tb = _c(THR, 0), _c(THR, 1)
        if op == "+":
            return _combine(frames, {NUM: a + b, THR: ta + tb})
        if op == "-":
            return _combine(frames, {NUM: a - b, THR: ta + tb})
        if op == "*":
            return _combine(
                frames, {NUM: a * b, THR: (a * tb).abs() + (b * ta).abs() + ta * tb}
            )
        return _divide(frames)
    if op in {"and", "or", "xor"}:
        for frame in frames:
            if frame.kinds & {NUM, TXT}:
                raise _RecordError(f"{op} needs booleans")
        a, b = _c(FLAG, 0), _c(FLAG, 1)
        if op == "and":
            return _combine(frames, {FLAG: a & b})
        if op == "or":
            return _combine(frames, {FLAG: a | b})
        return _combine(frames, {FLAG: a != b})
    if op in {"=", "!=", "<", "<=", ">", ">="}:
        return _compare(op, frames)
    raise ColumnarUnsupported(f"operator {op}")


def _binary_nodes(node: Binary) -> None:
    """Leave ordering an item literal to the reference evaluator.

    Raises:
        _RecordError: For ``<``, ``<=``, ``>`` or ``>=`` with an item
            literal, which the ``txt`` column would order as text.
    """
    if node.op in {"<", "<=", ">", ">="} and any(
        isinstance(side, Literal_) and side.kind == "item"
        for side in (node.left, node.right)
    ):
        raise _RecordError(f"items do not support {node.op!r}")


def _divide(frames: Sequence[Frame]) -> Frame:
    keys, df = _joined(frames)
    if df.height == 0:
        return Frame(
            keys,
            df.select([pl.col(_key(k)) for k in keys]).with_columns(
                [pl.lit(None, _VALUE_SCHEMA[c]).alias(c) for c in VALUE_COLUMNS]
            ),
            _all_defaults(frames),
        )
    # Interval division needs the four endpoint quotients; do it exactly in
    # Python decimals, row by row, only for rows that have thresholds.
    rows = df.select(
        _c(NUM, 0).alias("a"),
        _c(THR, 0).alias("ta"),
        _c(NUM, 1).alias("b"),
        _c(THR, 1).alias("tb"),
    ).rows()
    nums: list[Decimal | None] = []
    thrs: list[Decimal | None] = []
    for a, ta, b, tb in rows:
        if a is not None and b is not None and b == 0:
            # The reference evaluator fails only this record, which a join,
            # filter or if may still drop.
            raise ColumnarUnsupported("division by zero")
        if a is None or b is None:
            nums.append(None)
            thrs.append(None)
            continue
        # Quotients are rounded to the frame's 12 decimals, their thresholds
        # up, so that rounding never narrows an interval.
        try:
            quotient = Number(a, ta or ZERO) / Number(b, tb or ZERO)
        except ZeroDivisionError as error:
            # A divisor interval containing zero fails only this record.
            raise ColumnarUnsupported(str(error)) from error
        if quotient.value.copy_abs() >= _LIMIT or quotient.tolerance >= _LIMIT:
            raise ColumnarUnsupported("quotient beyond Decimal(38, 12)")
        nums.append(quotient.value.quantize(_SCALE, context=_WIDE))
        thrs.append(quotient.tolerance.quantize(_SCALE, ROUND_CEILING, context=_WIDE))
    columns: dict[str, pl.Series] = {
        _key(key): df.get_column(_key(key)) for key in keys
    }
    columns[NUM] = pl.Series(NUM, nums, dtype=DEC)
    columns[THR] = pl.Series(THR, thrs, dtype=DEC)
    columns[TXT] = pl.Series(TXT, [None] * len(nums), dtype=pl.String)
    columns[FLAG] = pl.Series(FLAG, [None] * len(nums), dtype=pl.Boolean)
    out = pl.DataFrame(columns)
    return Frame(keys, out, _all_defaults(frames))


def _compare(op: str, frames: Sequence[Frame]) -> Frame:
    a, b = _c(NUM, 0), _c(NUM, 1)
    diff = a - b
    width = _c(THR, 0).fill_null(ZERO) + _c(THR, 1).fill_null(ZERO)
    numeric = {
        "=": diff.abs() <= width,
        "!=": diff.abs() > width,
        "<": diff < width,
        "<=": diff <= width,
        ">": diff > -width,
        ">=": diff >= -width,
    }[op]
    ta, tb = _c(TXT, 0), _c(TXT, 1)
    text = {
        "=": ta == tb,
        "!=": ta != tb,
        "<": ta < tb,
        "<=": ta <= tb,
        ">": ta > tb,
        ">=": ta >= tb,
    }[op]
    fa, fb = _c(FLAG, 0), _c(FLAG, 1)
    flags = {
        "=": fa == fb,
        "!=": fa != fb,
        "<": fa < fb,
        "<=": fa <= fb,
        ">": fa > fb,
        ">=": fa >= fb,
    }[op]
    keys, df = _joined(frames)
    num_a, num_b = _c(NUM, 0).is_not_null(), _c(NUM, 1).is_not_null()
    txt_a, txt_b = _c(TXT, 0).is_not_null(), _c(TXT, 1).is_not_null()
    flag_a, flag_b = _c(FLAG, 0).is_not_null(), _c(FLAG, 1).is_not_null()
    mixed = (
        df.select(
            (
                (num_a & (txt_b | flag_b))
                | (num_b & (txt_a | flag_a))
                | (txt_a & flag_b)
                | (flag_a & txt_b)
            ).any()
        ).item()
        if df.height
        else False
    )
    if mixed:
        raise _RecordError(f"cannot compare values of different types using {op!r}")
    if flags is None and df.height and df.select((flag_a & flag_b).any()).item():
        raise _RecordError(f"booleans do not support {op!r}")
    if op in {"=", "!="}:
        _require_text_or_items(df, [_item_ambiguity(ta, tb)])
    else:
        # Items are not ordered; text and dates are. The txt column holds all
        # three: values with a category separator may be items. Items without
        # a category never get here (see _binary_nodes and frame_from_points).
        colon = (ta.str.contains(":", literal=True)) | tb.str.contains(
            ":", literal=True
        )
        if df.height and df.select((txt_a & txt_b & colon).any()).item():
            raise ColumnarUnsupported(f"ordering text that may be items with {op!r}")
    result = (
        pl.when(num_a & num_b)
        .then(numeric)
        .when(txt_a & txt_b)
        .then(text)
        .when(flag_a & flag_b)
        .then(flags if flags is not None else pl.lit(None, pl.Boolean))
        .otherwise(pl.lit(None, pl.Boolean))
    )
    selected = [pl.col(_key(key)) for key in keys]
    selected += [
        pl.lit(None, DEC).alias(NUM),
        pl.lit(None, DEC).alias(THR),
        pl.lit(None, pl.String).alias(TXT),
        result.alias(FLAG),
    ]
    return Frame(keys, df.select(selected), _all_defaults(frames))


def _item_ambiguity(left: pl.Expr, right: pl.Expr) -> pl.Expr:
    """Rows whose text equality and item equality differ.

    Items compare by code, ignoring a category missing on either side
    (``[qx1]`` matches ``[eba_qEC:qx1]``), text compares exactly (``"12:30"``
    is not ``"30"``). The ``txt`` column holds both, so it cannot tell which
    applies when one side has a category, the other has none and the codes
    match, or when only one side has the ``eba_`` prefix that an item reading
    drops. Everywhere else both readings agree with plain equality.

    Returns:
        pl.Expr: True where the readings differ.
    """
    category = left.str.contains(":", literal=True)
    return (
        (category != right.str.contains(":", literal=True))
        & (left.str.split(":").list.last() == right.str.split(":").list.last())
    ) | (_prefixed(left) != _prefixed(right))


def _literal_ambiguity(column: pl.Expr, text: str) -> pl.Expr:
    """:func:`_item_ambiguity` against a literal, without splitting the column.

    Returns:
        pl.Expr: True where the readings differ.
    """
    prefixed = _prefixed(column) != text[:4].casefold().startswith("eba_")
    if ":" in text:
        return prefixed | (column == pl.lit(text.rsplit(":", 1)[1]))
    return prefixed | column.str.ends_with(f":{text}")


def _prefixed(column: pl.Expr) -> pl.Expr:
    """Text with the ``eba_`` prefix, which an item reading drops.

    Items are held without it (see
    [`canonical_item`][dpmxl.columnar.canonical_item]), so such text equals
    an item only when read as one.

    Returns:
        pl.Expr: True where the text starts with ``eba_`` in any case.
    """
    return column.str.to_lowercase().str.starts_with("eba_")


def _require_text_or_items(df: pl.DataFrame, checks: Sequence[pl.Expr]) -> None:
    """Leave equality tests that :func:`_item_ambiguity` flags to the reference.

    Raises:
        ColumnarUnsupported: When some row's text and item readings differ.
    """
    if checks and df.height and df.select(pl.any_horizontal(checks).any()).item():
        raise ColumnarUnsupported("text that may be an item without its category")


def _conditional(condition: Frame, then: Frame, otherwise: Frame | None) -> Frame:
    """Columnar :func:`dpmxl.evaluator.conditional` (DPM-XL 8.1).

    Returns:
        Frame: One record per condition record (or the chosen branch).

    Raises:
        _RecordError: For non-Boolean conditions, which fail their records.
        ColumnarUnsupported: When a branch has keys the condition lacks, or
            key values a condition with a default lacks.
    """
    df = condition.df
    if condition.kinds & {NUM, TXT}:
        raise _RecordError("if needs a boolean condition")
    if not condition.keys:
        if not df.height and condition.has_default:
            raise ColumnarUnsupported("a default for a missing key-less condition")
        verdict = df.get_column(FLAG)[0] if df.height else None
        if verdict is True:
            return then
        if otherwise is not None:
            return otherwise
        # DPM-XL 8.1.4: without else, the records are left out.
        return Frame(then.keys, then.df.head(0))
    for branch in (then, otherwise):
        if branch is not None and not set(branch.keys) <= set(condition.keys):
            # Rare in EBA rules; the reference evaluator widens the result.
            raise ColumnarUnsupported("if branches with keys the condition lacks")
        if (
            condition.has_default
            and branch is not None
            and set(branch.keys) == set(condition.keys)
            and branch.df.select(condition.key_columns)
            .join(
                condition.df.select(condition.key_columns),
                on=condition.key_columns,
                how="anti",
                nulls_equal=True,
            )
            .height
        ):
            # The reference evaluator covers them with the condition's default.
            raise ColumnarUnsupported("a default for keys only a branch has")
    result = condition.df.select([*condition.key_columns, pl.col(FLAG).alias("_cond")])

    def cond_taken(index: int) -> pl.Expr:
        verdict = pl.col("_cond")
        return verdict.fill_null(False) if index == 1 else ~verdict.fill_null(False)

    for index, branch in ((1, then), (2, otherwise)):
        if branch is None:
            continue
        renamed = branch.df.rename(
            {column: f"{column}_{index}" for column in VALUE_COLUMNS}
        )
        if branch.keys:
            if branch.has_default:
                # The reference evaluator takes the branch's default where it
                # lacks a condition record's key.
                taken = cond_taken(index)
                lacking = result.filter(taken).join(
                    branch.df, on=branch.key_columns, how="anti", nulls_equal=True
                )
                if lacking.height:
                    raise ColumnarUnsupported("a default for records a branch lacks")
            result = result.join(renamed, on=branch.key_columns, how="left")
        else:
            result = (
                result.join(renamed.head(1), how="cross")
                if renamed.height
                else result.with_columns(
                    [
                        pl.lit(None, _VALUE_SCHEMA[column]).alias(f"{column}_{index}")
                        for column in VALUE_COLUMNS
                    ]
                )
            )
    cond = pl.col("_cond")
    if otherwise is None:
        # Without else, the records whose condition is not true are left out.
        result = result.filter(cond.fill_null(False))
    outputs = []
    for column in VALUE_COLUMNS:
        then_value = _c(column, 1)
        other_value = (
            _c(column, 2)
            if otherwise is not None
            else pl.lit(None, _VALUE_SCHEMA[column])
        )
        outputs.append(
            pl.when(cond.fill_null(False))
            .then(then_value)
            .otherwise(other_value)
            .cast(_VALUE_SCHEMA[column])
            .alias(column)
        )
    return Frame(
        condition.keys,
        result.select([*condition.key_columns, *outputs]),
        condition.has_default,
    )


def _membership(
    frame: Frame,
    values: SetLiteral,
    evaluator: ColumnarEvaluator,
    context: SelectionSpec,
) -> Frame:
    members = []
    for item in values.items:
        member = evaluator.evaluate(item, context)
        if member.keys or member.df.height != 1:
            raise ColumnarUnsupported("non-scalar set member")
        members.append(member.df.row(0, named=True))
    num, thr, txt = pl.col(NUM), pl.col(THR).fill_null(ZERO), pl.col(TXT)
    tests: list[pl.Expr] = []
    ambiguities: list[pl.Expr] = []
    for member in members:
        if member[NUM] is not None:
            width = thr + pl.lit(member[THR] or ZERO, DEC)
            tests.append(
                num.is_not_null() & ((num - pl.lit(member[NUM], DEC)).abs() <= width)
            )
        elif member[TXT] is not None:
            tests.append(txt.is_not_null() & (txt == pl.lit(member[TXT])))
            ambiguities.append(_literal_ambiguity(txt, member[TXT]))
        elif member[FLAG] is not None:
            tests.append(pl.col(FLAG) == pl.lit(member[FLAG]))
    if (
        frame.df.height
        and members
        and any(m[NUM] is not None for m in members)
        and TXT in frame.kinds
    ):
        raise _RecordError("cannot compare values of different types")
    _require_text_or_items(frame.df, ambiguities)
    found = pl.any_horizontal(tests) if tests else pl.lit(False)
    return _with_values(
        frame, flag=pl.when(_is_null()).then(pl.lit(None, pl.Boolean)).otherwise(found)
    )


def _map_numeric(frame: Frame, function: Any) -> Frame:
    _require_numeric([frame], "function")
    num, thr = function(pl.col(NUM), pl.col(THR))
    return _with_values(frame, num=num, thr=thr)


def _nvl(left: Frame, right: Frame) -> Frame:
    first_null = _is_null(0)
    return _combine(
        (left, right),
        {
            column: pl.when(first_null).then(_c(column, 1)).otherwise(_c(column, 0))
            for column in VALUE_COLUMNS
        },
    )


def _match(frame: Frame, pattern: Frame) -> Frame:
    if pattern.keys or pattern.df.height != 1:
        raise ColumnarUnsupported("non-literal match pattern")
    text = pattern.df.row(0, named=True)[TXT]
    if not isinstance(text, str):
        raise _RecordError("match needs a text pattern")
    try:
        re.compile(text)
    except re.error as error:
        raise _RecordError(f"invalid match pattern: {error}") from error
    if NUM in frame.kinds:
        raise ColumnarUnsupported("match on numbers")
    _require_plain_text(frame, "match")
    try:
        anchored = f"^(?:{text})$"
        result = pl.col(TXT).str.contains(anchored)
        out = _with_values(frame, flag=result)
        out.df.head(1)
    except pl.exceptions.PolarsError as error:  # pragma: no cover - regex flavour
        raise ColumnarUnsupported(f"regex {text!r}") from error
    return out


def _require_plain_text(frame: Frame, name: str) -> None:
    """Leave text that may be an item, and Booleans, to the reference evaluator.

    The ``txt`` column holds an item as ``category:code``, but ``len`` and
    ``match`` read an item as its qualified name ``eba_category:code``, and
    text with a colon cannot be told apart from an item. Booleans read as
    ``true`` and ``false``.

    Raises:
        ColumnarUnsupported: When some value contains a colon or is a Boolean.
    """
    if FLAG in frame.kinds:
        raise ColumnarUnsupported(f"{name} of booleans")
    if (
        TXT in frame.kinds
        and frame.df.select(pl.col(TXT).str.contains(":", literal=True).any()).item()
    ):
        raise ColumnarUnsupported(f"{name} of text that may be an item")


def _length(frame: Frame) -> Frame:
    if NUM in frame.kinds:
        raise ColumnarUnsupported("len of numbers")
    _require_plain_text(frame, "len")
    return _with_values(
        frame,
        num=pl.col(TXT).str.len_chars().cast(DEC),
        thr=pl.when(pl.col(TXT).is_not_null()).then(pl.lit(ZERO, DEC)),
    )


def _extreme(name: str, frames: Sequence[Frame]) -> Frame:
    if any(TXT in frame.kinds for frame in frames) and not any(
        FLAG in frame.kinds for frame in frames
    ):
        # The reference evaluator orders dates, text and items.
        raise ColumnarUnsupported(f"elementwise {name} of dates, text or items")
    _require_numeric(frames, name)
    keys, df = _joined(frames)
    count = len(frames)
    any_null = pl.any_horizontal(_c(NUM, index).is_null() for index in range(count))
    numbers = [_c(NUM, index) for index in range(count)]
    extreme = (
        pl.max_horizontal(numbers) if name == "max" else pl.min_horizontal(numbers)
    )
    # DPM-XL 4.3.5.4: among equal values, the largest threshold.
    threshold = pl.max_horizontal(
        pl.when(_c(NUM, index) == extreme).then(_c(THR, index))
        for index in range(count)
    )
    selected = [pl.col(_key(key)) for key in keys]
    selected += [
        pl.when(any_null).then(None).otherwise(extreme).cast(DEC).alias(NUM),
        pl.when(any_null).then(None).otherwise(threshold).cast(DEC).alias(THR),
        pl.lit(None, pl.String).alias(TXT),
        pl.lit(None, pl.Boolean).alias(FLAG),
    ]
    return Frame(keys, df.select(selected), _all_defaults(frames))


def _filter(data: Frame, condition: Frame) -> Frame:
    keys, df = _joined((condition, data))
    kept = df.filter(_c(FLAG, 0).fill_null(False))
    selected = [pl.col(_key(key)) for key in keys]
    selected += [_c(column, 1).alias(column) for column in VALUE_COLUMNS]
    return Frame(keys, kept.select(selected), data.has_default)


def _aggregate(name: str, frame: Frame, group_by: tuple[str, ...] | None) -> Frame:
    group_keys: list[str] = []
    for key_name in group_by or ():
        key = resolve_key(key_name, frame.keys)
        if key is None:
            raise EvaluationError(
                f"group by {key_name!r} is not a key of the operand "
                f"({', '.join(frame.keys) or 'no keys'})"
            )
        group_keys.append(key)
    df = frame.df
    text = False
    if name != "count" and frame.kinds & {TXT, FLAG}:
        if name not in {"max", "min"}:
            raise _RecordError(f"{name} needs numbers")
        if FLAG in frame.kinds:
            raise _RecordError(f"{name} needs numbers, dates, text or items")
        # Dates, text and items order by their text (ISO dates in date
        # order); a group may not mix them with numbers.
        text = True
        if NUM in frame.kinds:
            both = pl.col(NUM).is_not_null().any() & pl.col(TXT).is_not_null().any()
            mixed = (
                df.group_by([_key(key) for key in group_keys]).agg(both)
                if group_keys
                else df.select(both)
            )
            if mixed.get_column(NUM).any():
                raise _RecordError(
                    f"{name} cannot compare numbers with dates, text or items"
                )
    present = pl.col(NUM).is_not_null()
    non_null = pl.any_horizontal(
        pl.col(column).is_not_null() for column in VALUE_COLUMNS
    )
    count = non_null.sum()
    num_count = present.sum()
    if name == "count":
        num = count.cast(DEC)
        thr = pl.lit(ZERO, DEC)
    elif name == "sum":
        num = pl.when(num_count > 0).then(pl.col(NUM).sum())
        thr = pl.when(num_count > 0).then(pl.col(THR).filter(present).sum())
    elif name == "avg":
        num = pl.when(num_count > 0).then(pl.col(NUM).sum() / num_count.cast(DEC))
        thr = pl.when(num_count > 0).then(
            pl.col(THR).filter(present).sum() / num_count.cast(DEC)
        )
    elif name in {"max", "min"}:
        chosen = pl.col(NUM).max() if name == "max" else pl.col(NUM).min()
        num = pl.when(num_count > 0).then(chosen)
        # DPM-XL 7.4.4 and 7.5.4: among equal values, the largest threshold.
        thr = pl.when(num_count > 0).then(
            pl.col(THR).filter(pl.col(NUM) == chosen).max()
        )
    elif name == "median":
        raise ColumnarUnsupported("median")
    else:  # pragma: no cover
        raise ColumnarUnsupported(name)
    extreme = pl.col(TXT).max() if name == "max" else pl.col(TXT).min()
    aggregations = [
        num.cast(DEC).alias(NUM),
        thr.cast(DEC).alias(THR),
        (extreme if text else pl.lit(None, pl.String)).alias(TXT),
        pl.lit(None, pl.Boolean).alias(FLAG),
    ]
    if not group_keys:
        if df.height == 0:
            return scalar_frame(Number(ZERO) if name == "count" else None)
        return Frame((), df.select(aggregations))
    out = df.group_by([_key(key) for key in group_keys], maintain_order=True).agg(
        aggregations
    )
    if name == "count":
        out = out.with_columns(
            pl.when(pl.col(NUM).is_not_null()).then(pl.col(NUM)).alias(NUM)
        )
    return Frame(tuple(group_keys), out)


# Key conditions (where/sub) ----------------------------------------------------


def _literal_key(node: Node, provider: FrameProvider) -> str | None:
    match node:
        case Literal_(kind="item", value=Item() as item):
            return canonical_item(item)
        case Literal_(kind="null"):
            return None
        case Literal_(kind="string" | "date", value=value):
            return _key_text(value)
        case Parameter(name=name):
            value = provider.parameter(name)
            if isinstance(value, str | Item | date) or value is None:
                return _key_text(value)
    # Key columns are text: "10" may have been a number or text, and a number
    # never equals text (the reference evaluator reports that).
    raise ColumnarUnsupported("key compared with a number, Boolean or expression")


def _key_equals(column: pl.Expr, value: str | None, checks: list[pl.Expr]) -> pl.Expr:
    if value is None:
        return column.is_null()
    checks.append(_literal_ambiguity(column, value))
    return column == pl.lit(value)


def _key_predicate(
    node: Node, keys: Sequence[str], provider: FrameProvider, checks: list[pl.Expr]
) -> pl.Expr:
    """Translate a where condition on keys to a filter expression.

    Args:
        node: The condition.
        keys: The operand's keys.
        provider: Report parameters.
        checks: Collects the equality tests' :func:`_item_ambiguity`.

    Returns:
        pl.Expr: The filter.

    Raises:
        ColumnarUnsupported: For conditions beyond key comparisons.
    """
    match node:
        case Binary(op="and", left=left, right=right):
            return _key_predicate(left, keys, provider, checks) & _key_predicate(
                right, keys, provider, checks
            )
        case Binary(op="or", left=left, right=right):
            return _key_predicate(left, keys, provider, checks) | _key_predicate(
                right, keys, provider, checks
            )
        case Unary(op="not", operand=operand):
            return ~_key_predicate(operand, keys, provider, checks)
        case Binary(op="=" | "!=", left=Name(name=name), right=right):
            column = _key_column(name, keys)
            test = _key_equals(column, _literal_key(right, provider), checks)
            return test if node.op == "=" else ~test
        case Binary(op="=" | "!=", left=left, right=Name(name=name)):
            column = _key_column(name, keys)
            test = _key_equals(column, _literal_key(left, provider), checks)
            return test if node.op == "=" else ~test
        case In(operand=Name(name=name), values=SetLiteral() as values):
            column = _key_column(name, keys)
            tests = [
                _key_equals(column, _literal_key(item, provider), checks)
                for item in values.items
            ]
            return pl.any_horizontal(tests) if tests else pl.lit(False)
    raise ColumnarUnsupported("where condition beyond key comparisons")


def _key_column(name: str, keys: Sequence[str]) -> pl.Expr:
    key = resolve_key(name, keys)
    if _is_fact(name, keys):
        raise ColumnarUnsupported("where on the fact f")
    if key is None and _contextual(name) is not None:
        raise ColumnarUnsupported("contextual components")
    if key is None:
        raise EvaluationError(f"unknown key component or parameter {name!r}")
    return _key_text_column(key)


def _key_text_column(key: str) -> pl.Expr:
    # Providers may store key columns as categoricals; string matching needs text.
    return pl.col(_key(key)).cast(pl.String)


# Rule evaluation -----------------------------------------------------------------


@dataclass
class ColumnarResult:
    """Outcome of one rule evaluated on frames.

    Unlike [`RuleResult`][dpmxl.evaluator.RuleResult] it carries no
    evaluation trace: to explain a failure, evaluate the rule with
    [`evaluate_rule`][dpmxl.evaluator.evaluate_rule] (``only_keys`` limits it
    to the failing keys) and call [`explain`][dpmxl.explain.explain].

    Attributes:
        status: ``passed``, ``failed``, ``not_applicable``, ``error`` or
            ``unsupported``, as for [`RuleResult`][dpmxl.evaluator.RuleResult].
        message: Why the status is ``error``, ``unsupported`` or
            ``not_applicable``.
        passed: Number of records that hold.
        failed: Number of records that fail.
        null: Number of records whose result is null (not evaluated).
    """

    status: Status
    message: str | None = None
    passed: int = 0
    failed: int = 0
    null: int = 0
    failing_keys: list[dict[str, str | None]] | None = None
    """Keys of the first failing records, up to ``max_failing_keys``."""
    failing_frame: pl.DataFrame | None = None
    """Keys of every failing record, one string column per key name; ``None``
    when the result has no keys."""


def evaluate_rule_columnar(
    expression: str | Node,
    provider: FrameProvider,
    *,
    precondition: str | Node | None = None,
    cache: FrameCache | None = None,
    max_failing_keys: int = 1_000,
) -> ColumnarResult:
    """Evaluate a validation rule on frames, honouring its precondition.

    The columnar counterpart of [`evaluate_rule`][dpmxl.evaluator.evaluate_rule]:
    the same statuses and counts, and failing keys in canonical form (see
    [`canonical_key`][dpmxl.columnar.canonical_key]). Syntax and evaluation
    errors are returned as status ``error``, not raised. It may run
    concurrently from several threads with a shared ``cache``.

    Args:
        expression: Rule expression text or a parsed tree.
        provider: Columnar report data.
        precondition: Optional precondition; the rule is not applicable
            unless it yields at least one true record.
        cache: Selections shared by the rules of one report; a new cache per
            call when omitted.
        max_failing_keys: How many failing keys to list in
            ``failing_keys``; ``failing_frame`` has them all.

    Returns:
        ColumnarResult: Status, record counts and the keys of failing records.

    Raises:
        ColumnarUnsupported: When the reference evaluator must run instead.

    Examples:
        Fall back to the reference evaluator when needed:

        >>> from dpmxl import MemoryProvider, Number, TableLayout, evaluate_rule
        >>> provider = MemoryProvider(
        ...     [TableLayout("T", rows=("0010",), columns=("0010",))],
        ...     {("T", "0010", "0010", None, ()): Number.of(3, 0)},
        ... )
        >>> def run(expression):
        ...     try:
        ...         return evaluate_rule_columnar(
        ...             expression, PointsFrameProvider(provider)
        ...         ).status
        ...     except ColumnarUnsupported:
        ...         return evaluate_rule(expression, provider).status
        >>> run("{tT, r0010, c0010} > 0")
        'passed'
        >>> run("year(#2026-12-31#) = 2026")  # dates: reference evaluator
        'passed'
    """
    from .parser import DpmXlSyntaxError

    cache = cache or FrameCache()
    try:
        if precondition is not None:
            pre_node = (
                _parse_cached(precondition)
                if isinstance(precondition, str)
                else precondition
            )
            pre = ColumnarEvaluator(provider, cache).evaluate(pre_node)
            if not pre.df.height or not pre.df.get_column(FLAG).fill_null(False).any():
                return ColumnarResult("not_applicable", message="precondition not met")
        node = _parse_cached(expression) if isinstance(expression, str) else expression
        frame = ColumnarEvaluator(provider, cache).evaluate(node)
    except UnsupportedError as error:
        return ColumnarResult("unsupported", message=str(error))
    except (EvaluationError, DpmXlSyntaxError) as error:
        return ColumnarResult("error", message=str(error))
    except (
        pl.exceptions.PolarsError,
        pl.exceptions.PanicException,
        ArithmeticError,
        RecursionError,
    ) as error:
        # Overflow beyond Decimal(38, 12) and anything else polars rejects.
        raise ColumnarUnsupported(f"{type(error).__name__}: {error}") from error
    df = frame.df
    if frame.kinds & {NUM, TXT}:
        return ColumnarResult("error", message="rule yields values, not booleans")
    flags = df.get_column(FLAG) if df.height else pl.Series(FLAG, [], dtype=pl.Boolean)
    passed = int(flags.fill_null(False).sum())
    failed = int((~flags).fill_null(False).sum())
    null = int(flags.is_null().sum())
    failing = None
    failing_frame = None
    if failed and frame.keys:
        failing_frame = df.filter(~pl.col(FLAG).fill_null(True)).select(
            _key_text_column(name).alias(name) for name in frame.keys
        )
        failing = list(failing_frame.head(max_failing_keys).iter_rows(named=True))
    elif failed:
        failing = [{}]
    status: Status = "failed" if failed else "passed" if passed else "not_applicable"
    return ColumnarResult(status, None, passed, failed, null, failing, failing_frame)


def canonical_key(key: Mapping[str, Any]) -> dict[str, str | None]:
    """Canonicalize a reference outcome key for comparison with columnar keys.

    Closed coordinates are normalized with
    [`normalize_code`][dpmxl.provider.normalize_code]; other key values become
    the text the columnar evaluator uses (items as ``category:code``).

    Returns:
        dict[str, str | None]: Key name to canonical string.

    Examples:
        >>> canonical_key({"r": "10", "qCPI": "LEI-A"})
        {'r': '0010', 'qCPI': 'LEI-A'}
    """
    result: dict[str, str | None] = {}
    for name, value in key.items():
        if name in {"r", "c", "s"} and isinstance(value, str):
            result[name] = normalize_code(value)
        else:
            result[name] = _key_text(value)
    return result


def selected_axes(
    query: CellQuery, row: str | None, column: str | None, sheet: str | None
) -> bool:
    """Return whether a cell's coordinates are selected (for providers).

    Returns:
        bool: Whether every axis matches.
    """
    return (
        axis_matcher(query.rows)(row)
        and axis_matcher(query.columns)(column)
        and axis_matcher(query.sheets)(sheet)
    )


__all__ = [
    "CELL",
    "DEC",
    "FLAG",
    "NUM",
    "THR",
    "TXT",
    "VALUE_COLUMNS",
    "ColumnarEvaluator",
    "ColumnarResult",
    "ColumnarUnsupported",
    "Frame",
    "FrameCache",
    "FrameProvider",
    "PointsFrameProvider",
    "canonical_item",
    "canonical_key",
    "evaluate_rule_columnar",
    "frame_from_points",
    "normalize_code_expr",
    "scalar_frame",
    "selected_axes",
    "value_columns",
]
