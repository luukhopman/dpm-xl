"""Vectorized DPM-XL evaluation on polars data frames.

The record-by-record evaluator (:mod:`dpmxl.evaluator`) is the reference
implementation; this module evaluates the same language with the same
semantics on columnar data, so open tables with millions of rows evaluate in
milliseconds per rule. A record set becomes a data frame:

* key columns ``k:<name>`` (``k:r``, ``k:c``, ``k:s`` for varying closed axes,
  ``k:qEBB`` and the like for open keys), as canonical strings;
* ``num`` and ``thr``: an exact ``Decimal(38, 12)`` value and its interval
  threshold (Eurofiling ``iaf`` semantics, see :mod:`dpmxl.values`);
* ``txt``: text, item (``category:code`` without ``eba_``) or ISO date values;
* ``flag``: boolean values.

A null value has all four value columns null. Operators natural-join their
operands on shared keys exactly like :func:`dpmxl.recordset.combine`.

Anything this module does not implement raises :class:`ColumnarUnsupported`;
:func:`evaluate_rule_columnar` callers then fall back to the reference
evaluator, so coverage never trades off correctness. Arithmetic that would
overflow ``Decimal(38, 12)`` raises inside polars and falls back the same way.
"""

from __future__ import annotations

import re
from collections import OrderedDict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
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
from .evaluator import _UNSUPPORTED_FUNCTIONS, AGGREGATES, _parse_cached, is_boolean
from .provider import (
    CellQuery,
    DataPoint,
    axis_matcher,
    declared_open_keys,
    normalize_code,
)
from .recordset import STANDARD_KEYS, EvaluationError, UnsupportedError, resolve_key
from .values import Number, Value

DEC = pl.Decimal(38, 12)
NUM, THR, TXT, FLAG = "num", "thr", "txt", "flag"
VALUE_COLUMNS = (NUM, THR, TXT, FLAG)
CELL = "cell"
ZERO = Decimal(0)

Status = Literal["passed", "failed", "not_applicable", "error", "unsupported"]


class ColumnarUnsupported(Exception):
    """The expression needs the reference evaluator."""


class FrameProvider(Protocol):
    """Columnar report data for :class:`ColumnarEvaluator`.

    ``select_frame`` returns one row per selected data point (closed cells
    times reported open key combinations) with columns ``cell`` (an opaque
    cell reference), ``r``, ``c``, ``s`` (raw coordinates or null),
    ``k:<code>`` for each open key, and the value columns ``num``, ``thr``,
    ``txt``, ``flag`` (all null when the cell was not reported). A cell and
    open key combination appears at most once, and a cell's coordinates are
    the same on every row. String columns may be categorical, which keeps
    large selections compact.
    """

    def select_frame(self, query: CellQuery) -> pl.DataFrame:
        """Return the selected data points as a frame."""
        ...

    def table_reported(self, table: str) -> bool | None:
        """Answer ``{v_TABLE}``."""
        ...

    def parameter(self, name: str) -> Value:
        """Return a report parameter."""
        ...


@dataclass(frozen=True)
class Frame:
    """A record set: key names plus a frame of key and value columns."""

    keys: tuple[str, ...]
    df: pl.DataFrame

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
    """
    return f"{item.category}:{item.code}" if item.category else item.code


def value_columns(value: Value) -> dict[str, Any]:
    """Split a scalar value into the four value columns.

    Returns:
        dict[str, Any]: ``num``, ``thr``, ``txt`` and ``flag`` entries.
    """
    row: dict[str, Any] = {NUM: None, THR: None, TXT: None, FLAG: None}
    match value:
        case None:
            pass
        case bool():
            row[FLAG] = value
        case Number():
            row[NUM] = value.value
            row[THR] = value.tolerance
        case Item():
            row[TXT] = canonical_item(value)
        case date():
            row[TXT] = value.isoformat()
        case _:
            row[TXT] = str(value)
    return row


def scalar_frame(value: Value) -> Frame:
    """Build a key-less one-row frame.

    Returns:
        Frame: The scalar.
    """
    return Frame((), pl.DataFrame([value_columns(value)], schema=_VALUE_SCHEMA))


_VALUE_SCHEMA = {NUM: DEC, THR: DEC, TXT: pl.String, FLAG: pl.Boolean}


def frame_from_points(
    points: Sequence[DataPoint], open_keys: Sequence[str] = ()
) -> pl.DataFrame:
    """Adapt :class:`DataPoint` objects to the :class:`FrameProvider` layout.

    Args:
        points: Selected data points.
        open_keys: The table's open key names, kept even without points.

    Returns:
        pl.DataFrame: One row per point.
    """
    key_names: list[str] = list(open_keys)
    for point in points:
        key_names.extend(name for name in point.keys if name not in key_names)
    rows = []
    for point in points:
        row: dict[str, Any] = {
            CELL: repr(point.ref),
            "r": point.row,
            "c": point.column,
            "s": point.sheet,
        }
        for name in key_names:
            value = point.keys.get(name)
            row[_key(name)] = _key_text(value)
        row.update(value_columns(point.value))
        rows.append(row)
    schema: dict[str, Any] = {
        CELL: pl.String,
        "r": pl.String,
        "c": pl.String,
        "s": pl.String,
    }
    schema.update({_key(name): pl.String for name in key_names})
    schema.update(_VALUE_SCHEMA)
    return pl.DataFrame(rows, schema=schema)


def _key_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, Item):
        return canonical_item(value)
    if isinstance(value, Number):
        return format(value.value, "f")
    return str(value)


class PointsFrameProvider:
    """Adapt any :class:`dpmxl.DataProvider` to :class:`FrameProvider`."""

    def __init__(self, provider: Any) -> None:
        """Wrap a record provider.

        Args:
            provider: A :class:`dpmxl.DataProvider`.
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

    def get_raw(self, query: CellQuery) -> pl.DataFrame | None:
        """Return a cached provider frame.

        Returns:
            pl.DataFrame | None: The frame, or ``None``.
        """
        frame = self.raw.get(query)
        if frame is not None:
            self.raw.move_to_end(query)
        return frame

    def get_frame(self, spec: SelectionSpec) -> Frame | None:
        """Return a cached selection record set.

        Returns:
            Frame | None: The frame, or ``None``.
        """
        frame = self.frames.get(spec)
        if frame is not None:
            self.frames.move_to_end(spec)
        return frame

    def put_raw(self, query: CellQuery, frame: pl.DataFrame) -> None:
        """Cache a provider frame within the row budget."""
        self.raw[query] = frame
        self._rows += frame.height
        self._evict()

    def put_frame(self, spec: SelectionSpec, frame: Frame) -> None:
        """Cache a selection record set within the row budget."""
        self.frames[spec] = frame
        self._rows += frame.df.height
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
    """Evaluate one expression tree on frames."""

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
                for condition in self._conditions:
                    frame = self._where(frame, condition)
                return frame
            case TableReported(table=table):
                return scalar_frame(self.provider.table_reported(table))
            case Parameter(name=name):
                return scalar_frame(self.provider.parameter(name))
            case Name():
                raise ColumnarUnsupported("bare names outside where clauses")
            case Unary(op=op, operand=operand):
                return _unary(op, self.evaluate(operand, context))
            case Binary(op=op, left=left, right=right):
                return _binary(
                    op, self.evaluate(left, context), self.evaluate(right, context)
                )
            case In(operand=operand, values=values):
                return _membership(
                    self.evaluate(operand, context), values, self, context
                )
            case If(condition=condition, then=then, otherwise=otherwise):
                return _conditional(
                    self.evaluate(condition, context),
                    self.evaluate(then, context),
                    self.evaluate(otherwise, context)
                    if otherwise is not None
                    else None,
                    boolean_then=is_boolean(then),
                )
            case Call():
                return self._call(node, context)
            case Where(operand=operand, condition=condition):
                return self._where(self._clause_operand(operand, context), condition)
            case Get(operand=operand, name=name):
                return self._get(self.evaluate(operand, context), name)
            case Sub(operand=operand, name=name, value=value):
                return self._sub(self._clause_operand(operand, context), name, value)
            case Rename(operand=operand, pairs=pairs):
                return self._rename(self.evaluate(operand, context), pairs)
            case SetLiteral():
                raise EvaluationError("a set can only follow 'in'")
        raise ColumnarUnsupported(type(node).__name__)

    def _clause_operand(self, operand: Node, context: SelectionSpec) -> Frame:
        # DPM-XL 3.2: a where or sub on a selection overrides the with-where.
        if not isinstance(operand, Selection) or not self._conditions:
            return self.evaluate(operand, context)
        saved, self._conditions = self._conditions, []
        try:
            return self.evaluate(operand, context)
        finally:
            self._conditions = saved

    # Selections -------------------------------------------------------------

    def _selection(self, spec: SelectionSpec) -> Frame:
        if not spec.table:
            raise EvaluationError(f"selection {spec.text()} has no table")
        cached = self.cache.get_frame(spec)
        if cached is not None:
            return cached
        query = CellQuery(spec.table, spec.rows, spec.columns, spec.sheets)
        raw = self.cache.get_raw(query)
        if raw is None:
            try:
                raw = self.provider.select_frame(query)
            except LookupError as error:
                raise EvaluationError(str(error)) from error
            self.cache.put_raw(query, raw)
        frame = _build_selection(raw, spec)
        self.cache.put_frame(spec, frame)
        return frame

    # Calls ------------------------------------------------------------------

    def _call(self, node: Call, context: SelectionSpec) -> Frame:
        name = node.name
        if name == "time_shift":
            raise UnsupportedError(_UNSUPPORTED_FUNCTIONS["time_shift"])
        if name in AGGREGATES and (len(node.args) == 1 or node.group_by is not None):
            if len(node.args) != 1:
                raise EvaluationError(f"{name} with group by takes one operand")
            return _aggregate(name, self.evaluate(node.args[0], context), node.group_by)
        if node.group_by is not None:
            raise EvaluationError(f"group by is not allowed in {name}")
        args = [self.evaluate(arg, context) for arg in node.args]
        if name == "filter":
            _arity(name, args, 2)
            return _filter(args[0], args[1])
        if name == "abs":
            _arity(name, args, 1)
            return _map_numeric(args[0], lambda num, thr: (num.abs(), thr))
        if name == "isnull":
            _arity(name, args, 1)
            frame = args[0]
            return _with_values(frame, flag=_is_null())
        if name == "nvl":
            _arity(name, args, 2)
            return _nvl(args[0], args[1])
        if name == "match":
            _arity(name, args, 2)
            return _match(args[0], args[1])
        if name in {"max", "min"}:
            return _extreme(name, args)
        if name in {"len", "length"}:
            _arity(name, args, 1)
            return _length(args[0])
        raise ColumnarUnsupported(f"function {name}")

    # Clauses ----------------------------------------------------------------

    def _where(self, frame: Frame, condition: Node) -> Frame:
        if not frame.keys:
            if frame.df.height:
                raise EvaluationError("where needs a keyed operand")
            return frame
        predicate = _key_predicate(condition, frame.keys, self.provider)
        return Frame(frame.keys, frame.df.filter(predicate.fill_null(False)))

    def _get(self, frame: Frame, name: str) -> Frame:
        key = resolve_key(name, frame.keys)
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
        df = frame.df.filter(_key_equals(_key_text_column(key), fixed)).drop(_key(key))
        return Frame(tuple(item for item in frame.keys if item != key), df)

    def _rename(self, frame: Frame, pairs: tuple[tuple[str, str], ...]) -> Frame:
        keys = list(frame.keys)
        mapping: dict[str, str] = {}
        for old, new in pairs:
            key = resolve_key(old, keys)
            if key is None:
                raise EvaluationError(f"unknown key component {old!r}")
            keys[keys.index(key)] = new
            mapping[_key(key)] = _key(new)
        return Frame(tuple(keys), frame.df.rename(mapping))


def _arity(name: str, args: Sequence[Frame], count: int) -> None:
    if len(args) != count:
        raise EvaluationError(f"{name} takes {count} operands")


def _literal_value(node: Literal_) -> Value:
    if node.kind == "number" and isinstance(node.value, Decimal):
        return Number(node.value)
    return cast(Value, node.value)


# Selection building ------------------------------------------------------------


def normalize_code_expr(column: pl.Expr) -> pl.Expr:
    """Vectorized :func:`dpmxl.provider.normalize_code`.

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
    return Frame(keys, df)


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
    """
    _check_structure(frames)
    aligned = _aligned(frames)
    if aligned is not None:
        return aligned
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


def _combine(frames: Sequence[Frame], outputs: Mapping[str, pl.Expr]) -> Frame:
    keys, df = _joined(frames)
    selected = [pl.col(_key(key)) for key in keys]
    selected.extend(
        outputs.get(column, pl.lit(None, _VALUE_SCHEMA[column]))
        .cast(_VALUE_SCHEMA[column])
        .alias(column)
        for column in VALUE_COLUMNS
    )
    return Frame(keys, df.select(selected))


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
    return Frame(frame.keys, frame.df.with_columns(exprs))


def _require_numeric(frames: Sequence[Frame], operation: str) -> None:
    for frame in frames:
        if frame.kinds & {TXT, FLAG}:
            raise EvaluationError(f"{operation} needs numbers")


# Operators ---------------------------------------------------------------------


def _unary(op: str, frame: Frame) -> Frame:
    if op == "not":
        if frame.kinds & {NUM, TXT}:
            raise EvaluationError("not needs a boolean")
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
                raise EvaluationError(f"{op} needs booleans")
        a, b = _c(FLAG, 0), _c(FLAG, 1)
        if op == "and":
            return _combine(frames, {FLAG: a & b})
        if op == "or":
            return _combine(frames, {FLAG: a | b})
        return _combine(frames, {FLAG: a != b})
    if op in {"=", "!=", "<", "<=", ">", ">="}:
        return _compare(op, frames)
    raise ColumnarUnsupported(f"operator {op}")


def _divide(frames: Sequence[Frame]) -> Frame:
    keys, df = _joined(frames)
    if df.height == 0:
        return Frame(
            keys,
            df.select([pl.col(_key(k)) for k in keys]).with_columns(
                [pl.lit(None, _VALUE_SCHEMA[c]).alias(c) for c in VALUE_COLUMNS]
            ),
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
            raise EvaluationError("division by zero")
        if a is None or b is None:
            nums.append(None)
            thrs.append(None)
            continue
        quotient = Number(a, ta or ZERO) / Number(b, tb or ZERO)
        nums.append(quotient.value.quantize(Decimal("1e-12")))
        thrs.append(quotient.tolerance.quantize(Decimal("1e-12")))
    columns: dict[str, pl.Series] = {
        _key(key): df.get_column(_key(key)) for key in keys
    }
    columns[NUM] = pl.Series(NUM, nums, dtype=DEC)
    columns[THR] = pl.Series(THR, thrs, dtype=DEC)
    columns[TXT] = pl.Series(TXT, [None] * len(nums), dtype=pl.String)
    columns[FLAG] = pl.Series(FLAG, [None] * len(nums), dtype=pl.Boolean)
    out = pl.DataFrame(columns)
    return Frame(keys, out)


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
    text_equal = _text_equal(ta, tb)
    text = {
        "=": text_equal,
        "!=": ~text_equal,
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
        raise EvaluationError(f"cannot compare values of different types using {op!r}")
    if flags is None and df.height and df.select((flag_a & flag_b).any()).item():
        raise EvaluationError(f"booleans do not support {op!r}")
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
    return Frame(keys, df.select(selected))


def _text_equal(left: pl.Expr, right: pl.Expr) -> pl.Expr:
    """Items compare by category and code, ignoring a missing category.

    Returns:
        pl.Expr: Equality of the two text columns.
    """
    both = left.str.contains(":", literal=True) & right.str.contains(":", literal=True)
    return (
        pl.when(both)
        .then(left == right)
        .otherwise(left.str.split(":").list.last() == right.str.split(":").list.last())
    )


def _conditional(
    condition: Frame, then: Frame, otherwise: Frame | None, *, boolean_then: bool
) -> Frame:
    """Columnar :func:`dpmxl.evaluator.conditional` (DPM-XL 8.1).

    Returns:
        Frame: One record per condition record (or the chosen branch).

    Raises:
        EvaluationError: For non-Boolean conditions.
        ColumnarUnsupported: When a branch has keys the condition lacks.
    """
    df = condition.df
    if condition.kinds & {NUM, TXT}:
        raise EvaluationError("if needs a boolean condition")
    fallback = {NUM: None, THR: None, TXT: None, FLAG: True if boolean_then else None}
    if not condition.keys:
        verdict = df.get_column(FLAG)[0] if df.height else None
        if verdict is True:
            return then
        if otherwise is not None:
            return otherwise
        if then.keys:
            return _with_values(then, flag=pl.lit(fallback[FLAG], pl.Boolean))
        return scalar_frame(fallback[FLAG])
    for branch in (then, otherwise):
        if branch is not None and not set(branch.keys) <= set(condition.keys):
            # Rare in EBA rules; the reference evaluator widens the result.
            raise ColumnarUnsupported("if branches with keys the condition lacks")
    result = condition.df.select([*condition.key_columns, pl.col(FLAG).alias("_cond")])
    for index, branch in ((1, then), (2, otherwise)):
        if branch is None:
            continue
        renamed = branch.df.rename(
            {column: f"{column}_{index}" for column in VALUE_COLUMNS}
        )
        if branch.keys:
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
    outputs = []
    for column in VALUE_COLUMNS:
        then_value = _c(column, 1)
        if otherwise is not None:
            other_value = _c(column, 2)
        else:
            other_value = pl.lit(fallback[column], _VALUE_SCHEMA[column])
        outputs.append(
            pl.when(cond.fill_null(False))
            .then(then_value)
            .otherwise(other_value)
            .cast(_VALUE_SCHEMA[column])
            .alias(column)
        )
    return Frame(condition.keys, result.select([*condition.key_columns, *outputs]))


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
    for member in members:
        if member[NUM] is not None:
            width = thr + pl.lit(member[THR] or ZERO, DEC)
            tests.append(
                num.is_not_null() & ((num - pl.lit(member[NUM], DEC)).abs() <= width)
            )
        elif member[TXT] is not None:
            tests.append(txt.is_not_null() & _text_equal(txt, pl.lit(member[TXT])))
        elif member[FLAG] is not None:
            tests.append(pl.col(FLAG) == pl.lit(member[FLAG]))
    if (
        frame.df.height
        and members
        and any(m[NUM] is not None for m in members)
        and TXT in frame.kinds
    ):
        raise EvaluationError("cannot compare values of different types")
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
        raise EvaluationError("match needs a text pattern")
    try:
        re.compile(text)
    except re.error as error:
        raise EvaluationError(f"invalid match pattern: {error}") from error
    if NUM in frame.kinds:
        raise ColumnarUnsupported("match on numbers")
    try:
        anchored = f"^(?:{text})$"
        result = pl.col(TXT).str.contains(anchored)
        out = _with_values(frame, flag=result)
        out.df.head(1)
    except pl.exceptions.ComputeError as error:  # pragma: no cover - regex flavour
        raise ColumnarUnsupported(f"regex {text!r}") from error
    return out


def _length(frame: Frame) -> Frame:
    if NUM in frame.kinds:
        raise ColumnarUnsupported("len of numbers")
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
    values = pl.concat_list([_c(NUM, index) for index in range(count)])
    thresholds = pl.concat_list([_c(THR, index) for index in range(count)])
    position = values.list.arg_max() if name == "max" else values.list.arg_min()
    selected = [pl.col(_key(key)) for key in keys]
    selected += [
        pl.when(any_null)
        .then(None)
        .otherwise(values.list.get(position))
        .cast(DEC)
        .alias(NUM),
        pl.when(any_null)
        .then(None)
        .otherwise(thresholds.list.get(position))
        .cast(DEC)
        .alias(THR),
        pl.lit(None, pl.String).alias(TXT),
        pl.lit(None, pl.Boolean).alias(FLAG),
    ]
    return Frame(keys, df.select(selected))


def _filter(data: Frame, condition: Frame) -> Frame:
    keys, df = _joined((condition, data))
    kept = df.filter(_c(FLAG, 0).fill_null(False))
    selected = [pl.col(_key(key)) for key in keys]
    selected += [_c(column, 1).alias(column) for column in VALUE_COLUMNS]
    return Frame(keys, kept.select(selected))


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
            raise EvaluationError(f"{name} needs numbers")
        if FLAG in frame.kinds:
            raise EvaluationError(f"{name} needs numbers, dates, text or items")
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
                raise EvaluationError(
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
        index = pl.col(NUM).arg_max() if name == "max" else pl.col(NUM).arg_min()
        num = pl.when(num_count > 0).then(pl.col(NUM).get(index))
        thr = pl.when(num_count > 0).then(pl.col(THR).get(index))
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
        case Literal_(value=value):
            return _key_text(
                _literal_value(node) if isinstance(value, Decimal) else value
            )
        case Parameter(name=name):
            return _key_text(provider.parameter(name))
    raise ColumnarUnsupported("non-literal key value")


def _key_equals(column: pl.Expr, value: str | None) -> pl.Expr:
    if value is None:
        return column.is_null()
    return _text_equal(column, pl.lit(value))


def _key_predicate(node: Node, keys: Sequence[str], provider: FrameProvider) -> pl.Expr:
    match node:
        case Binary(op="and", left=left, right=right):
            return _key_predicate(left, keys, provider) & _key_predicate(
                right, keys, provider
            )
        case Binary(op="or", left=left, right=right):
            return _key_predicate(left, keys, provider) | _key_predicate(
                right, keys, provider
            )
        case Unary(op="not", operand=operand):
            return ~_key_predicate(operand, keys, provider)
        case Binary(op="=" | "!=", left=Name(name=name), right=right):
            column = _key_column(name, keys)
            test = _key_equals(column, _literal_key(right, provider))
            return test if node.op == "=" else ~test
        case Binary(op="=" | "!=", left=left, right=Name(name=name)):
            column = _key_column(name, keys)
            test = _key_equals(column, _literal_key(left, provider))
            return test if node.op == "=" else ~test
        case In(operand=Name(name=name), values=values):
            column = _key_column(name, keys)
            tests = [
                _key_equals(column, _literal_key(item, provider))
                for item in values.items
            ]
            return pl.any_horizontal(tests) if tests else pl.lit(False)
    raise ColumnarUnsupported("where condition beyond key comparisons")


def _key_column(name: str, keys: Sequence[str]) -> pl.Expr:
    key = resolve_key(name, keys)
    if key is None:
        raise EvaluationError(f"unknown key component or parameter {name!r}")
    return _key_text_column(key)


def _key_text_column(key: str) -> pl.Expr:
    # Providers may store key columns as categoricals; string matching needs text.
    return pl.col(_key(key)).cast(pl.String)


# Rule evaluation -----------------------------------------------------------------


@dataclass
class ColumnarResult:
    """Outcome of one rule evaluated on frames."""

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

    Returns:
        ColumnarResult: Status, record counts and the keys of failing records.

    Raises:
        ColumnarUnsupported: When the reference evaluator must run instead.
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
    except pl.exceptions.ComputeError as error:
        raise ColumnarUnsupported(f"polars: {error}") from error
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

    Returns:
        dict[str, str | None]: Key name to canonical string.
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
