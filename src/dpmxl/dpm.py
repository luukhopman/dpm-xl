"""Export modules of an EBA DPM 2.0 release to module files.

The EBA publishes each DPM 2.0 release as a database, a Microsoft Access
file with the tables of the DPM metamodel: tables, cells, variables,
properties, categories, items, modules and validation rules.
[`open_release`][dpmxl.dpm.open_release] opens the database, as SQLite
with the table and column names the EBA publishes (or as the Access file,
with mdbtools), and [`export_module`][dpmxl.dpm.export_module] writes one
module of one release as a ``dpm-module/1`` document, which
[`load_module`][dpmxl.module.load_module] reads.

One database holds every release up to its own: each versioned row has a
window from ``StartReleaseID`` to ``EndReleaseID``, both included, and the
row of a release is the one whose window holds it, the latest starting one
where two do. The release selects the module version and its rules; the
version's tables, cells and items are those it was published with, as in
its taxonomy. The EBA data errors that the export meets are corrected or
left out, as the guide describes, and each is reported as a warning of the
``dpmxl.dpm`` logger.

Examples:
    >>> import sqlite3
    >>> from dpmxl.dpm import DpmError, DpmRelease
    >>> try:
    ...     DpmRelease(sqlite3.connect(":memory:"))
    ... except DpmError as error:
    ...     print(error)
    not an EBA DPM 2.0 database: it has no Release table
"""

from __future__ import annotations

import contextlib
import csv
import html
import io
import json
import logging
import posixpath
import re
import shutil
import sqlite3
import subprocess  # ruff: ignore[suspicious-subprocess-import] - runs mdb-export, found on PATH, without a shell
import sys
import tempfile
import urllib.parse
import zipfile
import zlib
from collections import defaultdict
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Self

from .module import FORMATS, MODULE_FORMAT

logger = logging.getLogger(__name__)

DEFAULT_DECIMALS: Mapping[str, int] = {"m": 0, "p": 4, "i": 0, "r": 2}
"""The ``decimals`` an export writes: monetary 0, percentage 4, integer 0,
decimal 2; within the least accuracy of EBA filing rule 2.18."""

ENTRY_POINT = "http://www.eba.europa.eu/eu/fr/xbrl/crr/fws/{framework}/{release}/mod/{module}.json"
"""The EBA's xBRL-CSV entry point of a module version: the framework and
module codes in lower case and the release that introduced the version."""

TABLES: Mapping[str, tuple[str, ...]] = {
    "Release": ("ReleaseID", "Code", "Date", "Type"),
    "Organisation": ("OrgID", "Acronym"),
    "Framework": ("FrameworkID", "Code"),
    "Module": ("ModuleID", "FrameworkID"),
    "ModuleVersion": (
        "ModuleVID",
        "ModuleID",
        "Code",
        "Name",
        "VersionNumber",
        "StartReleaseID",
        "EndReleaseID",
        "FromReferenceDate",
        "ToReferenceDate",
    ),
    "ModuleVersionComposition": ("ModuleVID", "TableID", "TableVID"),
    "ModuleParameters": ("ModuleVID", "VariableVID"),
    "Table": ("TableID", "IsAbstract"),
    "TableVersion": (
        "TableVID",
        "TableID",
        "Code",
        "AbstractTableID",
        "StartReleaseID",
        "EndReleaseID",
    ),
    "TableVersionCell": (
        "TableVID",
        "CellID",
        "VariableVID",
        "CellCode",
        "IsExcluded",
        "IsVoid",
    ),
    "Cell": ("CellID", "RowID", "ColumnID", "SheetID"),
    "TableVersionHeader": ("TableVID", "HeaderID", "HeaderVID", "Order"),
    "Header": ("HeaderID", "IsKey"),
    "HeaderVersion": (
        "HeaderVID",
        "HeaderID",
        "PropertyID",
        "SubCategoryVID",
        "KeyVariableVID",
        "StartReleaseID",
        "EndReleaseID",
    ),
    "VariableVersion": (
        "VariableVID",
        "VariableID",
        "PropertyID",
        "SubCategoryVID",
        "Code",
        "StartReleaseID",
        "EndReleaseID",
        "ContextID",
    ),
    "ContextComposition": ("ContextID", "PropertyID", "ItemID"),
    "Property": ("PropertyID", "DataTypeID"),
    "DataType": ("DataTypeID", "Code", "Name"),
    "PropertyCategory": ("PropertyID", "CategoryID", "StartReleaseID", "EndReleaseID"),
    "Category": ("CategoryID", "Code", "OwnerID", "IsEnumerated"),
    "Item": ("ItemID", "IsActive"),
    "ItemCategory": ("ItemID", "CategoryID", "Code", "StartReleaseID", "EndReleaseID"),
    "SuperCategoryComposition": (
        "SuperCategoryID",
        "CategoryID",
        "StartReleaseID",
        "EndReleaseID",
    ),
    "SubCategory": ("SubCategoryID", "CategoryID"),
    "SubCategoryVersion": (
        "SubCategoryVID",
        "SubCategoryID",
        "StartReleaseID",
        "EndReleaseID",
    ),
    "SubCategoryItem": ("SubCategoryVID", "ItemID", "Order"),
    "Operation": ("OperationID", "Code"),
    "OperationVersion": (
        "OperationVID",
        "OperationID",
        "PreconditionOperationVID",
        "Expression",
        "StartReleaseID",
        "EndReleaseID",
    ),
    "OperationScope": (
        "OperationScopeID",
        "OperationVID",
        "IsActive",
        "Severity",
        "FromSubmissionDate",
    ),
    "OperationScopeComposition": ("OperationScopeID", "ModuleVID"),
}
"""The tables and columns of the DPM 2.0 database that an export reads."""


class DpmError(ValueError):
    """A database that cannot be read, or a release or module it lacks."""


@dataclass(frozen=True, slots=True)
class ExpressionFix:
    """A known error in the expression of an EBA rule, and its correction.

    Attributes:
        rule: The rule code, such as ``v7551_m``.
        wrong: The text in the expression, such as ``trueendif``.
        right: The text that replaces it, once, such as ``true endif``.
        reason: What is wrong.
    """

    rule: str
    wrong: str
    right: str
    reason: str


KNOWN_ERRORS: tuple[ExpressionFix, ...] = (
    ExpressionFix("v7551_m", "trueendif", "true endif", "no space before endif"),
    ExpressionFix("v904909_m", "ornot", "or not", "no space between or and not"),
)
"""Typos in EBA rule expressions that the export corrects, so that they
parse; an expression without the wrong text is left as it is."""


@dataclass(frozen=True, slots=True)
class Release:
    """A release of the database.

    Attributes:
        id: The ``ReleaseID``; releases are ordered by it.
        code: The release code, such as ``4.3`` or ``4.3.0.1``.
        date: The release date, ``YYYY-MM-DD``, or ``None``.
        type: ``module`` for a release of modules, ``deactivation`` for one
            that only deactivates rules; ``None`` when the database does not
            say.
    """

    id: int
    code: str
    date: str | None = None
    type: str | None = None


@dataclass(frozen=True, slots=True)
class ModuleInfo:
    """A module of a release.

    Attributes:
        code: The module code, such as ``COREP_OF``.
        name: The module name, such as ``Own Funds - COREP``.
        version: The module version, such as ``4.1.0``.
        framework: The framework code, such as ``COREP``.
        release: The code of the release that introduced this version.
        from_date: The first reference date of the version, ``YYYY-MM-DD``.
        to_date: The last reference date of the version, or ``None``.
    """

    code: str
    name: str | None
    version: str | None
    framework: str | None
    release: str | None
    from_date: str | None
    to_date: str | None


def open_release(path: str | Path) -> DpmRelease:
    """Open an EBA DPM 2.0 database.

    Args:
        path: A SQLite file with the tables and columns of the EBA's Access
            database, such as one converted with mdbtools or downloaded from
            dpm-toolkit; or the Access file (``.accdb``) itself, which needs
            ``mdb-export`` of mdbtools on ``PATH`` and is read into memory,
            which takes about ten seconds; or the ZIP file the EBA publishes
            it in, whose one Access file is unpacked to a temporary file,
            read the same way and deleted.

    Returns:
        DpmRelease: The database, open read-only; close it, or use it in a
        ``with`` block.

    Raises:
        DpmError: If the file cannot be read or is not a DPM 2.0 database.
    """
    path = Path(path)
    try:
        with path.open("rb") as file:
            header = file.read(32)
    except FileNotFoundError as error:
        raise DpmError(f"{path}: no such file") from error
    except OSError as error:
        raise DpmError(f"{path}: cannot read: {error.strerror or error}") from error
    if header[4:19] in {b"Standard ACE DB", b"Standard Jet DB"}:
        return DpmRelease(_from_access(path), path)
    if header.startswith((b"PK\x03\x04", b"PK\x05\x06")):
        return DpmRelease(_from_zip(path), path)
    if not header.startswith(b"SQLite format 3\0"):
        raise DpmError(f"{path}: not a SQLite, Access or ZIP file")
    connection = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
    try:
        return DpmRelease(connection, path)
    except BaseException:
        connection.close()
        raise


_ZIP_MAX_BYTES = 2 * 1024**3
"""The largest Access file unpacked from a ZIP file."""

_ZIP_MAX_RATIO = 100.0
"""The highest compression ratio of an Access file in a ZIP file."""

_ZIP_RATIO_FROM = 1024**2
"""The size from which the compression ratio is checked."""


def _mdb_export(path: Path) -> str:
    """Return the path of ``mdb-export``.

    Returns:
        str: The program.

    Raises:
        DpmError: If it is not on ``PATH``.
    """
    program = shutil.which("mdb-export")
    if program is not None:
        return program
    if sys.platform == "win32":
        raise DpmError(
            f"{path}: reading an Access database needs mdb-export (mdbtools), "
            "which does not run on Windows; run dpm-xl in WSL with mdbtools "
            "installed, or convert the database to SQLite first, as "
            "https://luukhopman.github.io/dpm-xl/guides/from-a-dpm-release/ "
            "describes"
        )
    raise DpmError(
        f"{path}: reading an Access database needs mdb-export (mdbtools) on "
        "PATH; install mdbtools, or convert the database to SQLite first"
    )


def _from_zip(path: Path) -> sqlite3.Connection:
    """Read the tables an export needs from the Access file in a ZIP file.

    The one ``.accdb`` or ``.mdb`` member (one with ``dpm`` in its name,
    if there are several) is checked, unpacked to a fixed name in a
    temporary directory, read with ``mdb-export`` and deleted.

    Returns:
        sqlite3.Connection: An in-memory database of those tables.

    Raises:
        DpmError: If the ZIP file has no single Access file, the member is a
            symbolic link, too large or too compressed, or cannot be read.
    """
    _mdb_export(path)
    try:
        archive = zipfile.ZipFile(path)
    except (OSError, zipfile.BadZipFile) as error:
        raise DpmError(f"{path}: not a readable ZIP file: {error}") from error
    with archive:
        members = [
            member
            for member in archive.infolist()
            if not member.is_dir()
            and member.filename.casefold().endswith((".accdb", ".mdb"))
        ]
        named = [
            member
            for member in members
            if "dpm" in _member_name(member.filename).casefold()
        ]
        if len(named) == 1:
            member = named[0]
        elif len(members) == 1:
            member = members[0]
        elif not members:
            raise DpmError(f"{path}: the ZIP file has no .accdb or .mdb database")
        else:
            names = ", ".join(sorted(member.filename for member in members))
            raise DpmError(
                f"{path}: the ZIP file has several Access databases: {names}"
            )
        where = f"{path}: {member.filename}"
        if (member.external_attr >> 16) & 0o170000 == 0o120000:
            raise DpmError(f"{where} is a symbolic link")
        if member.file_size > _ZIP_MAX_BYTES:
            raise DpmError(f"{where} is larger than {_ZIP_MAX_BYTES:,} bytes")
        if member.file_size >= _ZIP_RATIO_FROM and (
            member.file_size / max(member.compress_size, 1) > _ZIP_MAX_RATIO
        ):
            raise DpmError(f"{where} is compressed more than {_ZIP_MAX_RATIO:g} to 1")
        suffix = Path(_member_name(member.filename)).suffix.casefold()
        with tempfile.TemporaryDirectory(prefix="dpmxl-") as directory:
            target = Path(directory) / f"database{suffix}"
            try:
                with archive.open(member) as source, target.open("wb") as output:
                    size = 0
                    while chunk := source.read(1024**2):
                        size += len(chunk)
                        if size > _ZIP_MAX_BYTES:
                            raise DpmError(
                                f"{where} is larger than {_ZIP_MAX_BYTES:,} bytes"
                            )
                        output.write(chunk)
            except (OSError, zipfile.BadZipFile, zlib.error) as error:
                raise DpmError(f"{where}: cannot unpack: {error}") from error
            return _from_access(target, path)


def _member_name(filename: str) -> str:
    return filename.replace("\\", "/").rsplit("/", 1)[-1]


def _from_access(path: Path, source: Path | None = None) -> sqlite3.Connection:
    """Read the tables an export needs from an Access file into memory.

    Args:
        path: The Access file.
        source: The file to name in errors, such as the ZIP file that
            ``path`` was unpacked from; ``path`` by default.

    Returns:
        sqlite3.Connection: An in-memory database of those tables, committed,
        so that ``backup`` and ``VACUUM INTO`` can copy it.

    Raises:
        DpmError: If ``mdb-export`` is not on ``PATH`` or fails.
    """
    program = _mdb_export(source or path)
    connection = sqlite3.connect(":memory:")
    for table in TABLES:
        result = subprocess.run(  # ruff: ignore[subprocess-without-shell-equals-true] - fixed arguments, no shell
            [program, "-D", "%Y-%m-%d", "-T", "%Y-%m-%d", "-b", "strip", path, table],
            capture_output=True,
            check=False,
        )
        if result.returncode != 0:
            message = result.stderr.decode("utf-8", "replace").strip()
            connection.close()
            raise DpmError(f"{source or path}: mdb-export {table} failed: {message}")
        rows = csv.reader(io.StringIO(result.stdout.decode("utf-8"), newline=""))
        columns = next(rows, None)
        if not columns:
            continue
        integer = [_is_integer_column(column) for column in columns]
        names = ", ".join(_quote(column) for column in columns)
        connection.execute(f"CREATE TABLE {_quote(table)} ({names})")
        marks = ", ".join("?" * len(columns))
        connection.executemany(
            f"INSERT INTO {_quote(table)} VALUES ({marks})",  # ruff: ignore[hardcoded-sql-expression] - table names are constants
            (
                [
                    _access_value(value, number)
                    for value, number in zip(row, integer, strict=False)
                ]
                for row in rows
            ),
        )
    connection.commit()
    return connection


def _is_integer_column(name: str) -> bool:
    return name.endswith("ID") or name.startswith(("Is", "Has")) or name == "Order"


def _access_value(value: str, integer: bool) -> object:
    if value == "":
        return None
    if integer:
        try:
            return int(value)
        except ValueError:
            return value
    return value


def _quote(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _valid(start: int | None, end: int | None, release: int) -> bool:
    """Tell whether a window holds a release; both ends are included.

    Returns:
        bool: Whether ``start <= release <= end``, a missing end being open.
    """
    return (start is None or start <= release) and (end is None or end >= release)


def _latest(
    rows: Iterable[Sequence[Any]],
    key: Callable[[Sequence[Any]], object],
    release: int,
    *,
    start: int,
    end: int,
    tie: int,
) -> dict[Any, Sequence[Any]]:
    """Pick the row of each key that is valid in a release.

    Where two windows hold the release, as at a replacement boundary, the
    later starting row wins, and on equal starts the higher ``tie`` column.

    Returns:
        dict: The row of each key that has a valid one.
    """
    chosen: dict[Any, Sequence[Any]] = {}
    for row in rows:
        if not _valid(row[start], row[end], release):
            continue
        found = chosen.get(key(row))
        if found is None or (row[start] or 0, row[tie] or 0) > (
            found[start] or 0,
            found[tie] or 0,
        ):
            chosen[key(row)] = row
    return chosen


class DpmRelease:
    """An open EBA DPM 2.0 database; see [`open_release`][dpmxl.dpm.open_release].

    Attributes:
        path: The file it was opened from, or ``None``.
    """

    def __init__(self, connection: sqlite3.Connection, path: Path | None = None):
        """Wrap a connection to a DPM 2.0 database.

        Args:
            connection: An open connection; closed by
                [`close`][dpmxl.dpm.DpmRelease.close].
            path: The file it was opened from.

        Raises:
            DpmError: If a table or column that an export reads is missing.
        """
        self._connection = connection
        self.path = path
        self._cache: dict[str, Any] = {}
        try:
            names = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type IN ('table', 'view')"
                )
            }
        except sqlite3.DatabaseError as error:
            raise DpmError(f"not a SQLite database: {error}") from error
        for table, columns in TABLES.items():
            if table not in names:
                raise DpmError(f"not an EBA DPM 2.0 database: it has no {table} table")
            found = {
                row[1]
                for row in connection.execute(f"PRAGMA table_info({_quote(table)})")
            }
            missing = [column for column in columns if column not in found]
            if missing:
                raise DpmError(
                    f"not an EBA DPM 2.0 database: table {table} has no column "
                    + ", ".join(missing)
                )

    def __enter__(self) -> Self:
        """Return the database, for a ``with`` block.

        Returns:
            Self: The database.
        """
        return self

    def __exit__(self, *exc_info: object) -> None:
        """Close the database at the end of a ``with`` block."""
        self.close()

    def close(self) -> None:
        """Close the database."""
        self._connection.close()

    def _rows(self, table: str) -> list[tuple[Any, ...]]:
        """Return a table's rows, with the columns of `TABLES`, cached.

        Returns:
            list: The rows.
        """
        cached = self._cache.get(table)
        if cached is None:
            columns = ", ".join(_quote(column) for column in TABLES[table])
            cached = self._connection.execute(
                f"SELECT {columns} FROM {_quote(table)}"  # ruff: ignore[hardcoded-sql-expression] - names are constants
            ).fetchall()
            self._cache[table] = cached
        return cached

    def _memo(self, key: str, build: Callable[[], Any]) -> Any:
        if key not in self._cache:
            self._cache[key] = build()
        return self._cache[key]

    def releases(self) -> tuple[Release, ...]:
        """Return the releases the database holds, oldest first.

        Returns:
            tuple[Release, ...]: The releases, ordered by ``ReleaseID``.
        """
        return tuple(
            Release(int(row[0]), str(row[1]), _date(row[2]), row[3] or None)
            for row in sorted(self._rows("Release"), key=lambda row: row[0])
            if row[0] is not None and row[1]
        )

    def release(self, code: str | None = None) -> Release:
        """Return a release by its code, or the latest.

        Args:
            code: The release code, such as ``4.3``; ``None`` for the latest
                release of the database.

        Returns:
            Release: The release.

        Raises:
            DpmError: If the database has no such release.
        """
        releases = self.releases()
        if not releases:
            raise DpmError("the database has no releases")
        if code is None:
            return releases[-1]
        for release in releases:
            if release.code == code:
                return release
        known = ", ".join(release.code for release in releases)
        raise DpmError(f"no release {code!r} in the database; it has {known}")

    def modules(self, release: str | None = None) -> tuple[ModuleInfo, ...]:
        """Return the modules of a release, ordered by code.

        Args:
            release: The release code; ``None`` for the latest release.

        Returns:
            tuple[ModuleInfo, ...]: One per module with a version in the
            release.

        Raises:
            DpmError: If the database has no such release.
        """
        chosen = self.release(release)
        frameworks = dict(self._rows("Framework"))
        module_frameworks = dict(self._rows("Module"))
        codes = {row[0]: row[1] for row in self._rows("Release")}
        return tuple(
            sorted(
                (
                    ModuleInfo(
                        code=row[2],
                        name=row[3] or None,
                        version=row[4] or None,
                        framework=frameworks.get(module_frameworks.get(row[1])),
                        release=codes.get(row[5]),
                        from_date=_date(row[7]),
                        to_date=_date(row[8]),
                    )
                    for row in self._module_versions(chosen.id).values()
                    if row[2]
                ),
                key=lambda module: module.code,
            )
        )

    def _module_versions(self, release: int) -> dict[Any, Sequence[Any]]:
        return _latest(
            self._rows("ModuleVersion"),
            lambda row: row[1],
            release,
            start=5,
            end=6,
            tie=0,
        )

    def _variables(self) -> dict[int, Sequence[Any]]:
        """Return the variable versions by ``VariableVID``.

        Returns:
            dict: The ``VariableVersion`` rows.
        """
        return self._memo(
            "variables", lambda: {row[0]: row for row in self._rows("VariableVersion")}
        )

    def _bindings(self, release: int) -> dict[int, dict[int, Sequence[Any]]]:
        """Return the item bindings of each category in a release.

        Returns:
            dict: ``CategoryID`` to ``ItemID`` to its ``ItemCategory`` row,
            which has a code.
        """

        def build() -> dict[int, dict[int, Sequence[Any]]]:
            chosen = _latest(
                self._rows("ItemCategory"),
                lambda row: (row[1], row[0]),
                release,
                start=3,
                end=4,
                tie=0,
            )
            bindings: dict[int, dict[int, Sequence[Any]]] = defaultdict(dict)
            for (category, item), row in chosen.items():
                if row[2]:
                    bindings[category][item] = row
            return bindings

        return self._memo(f"bindings:{release}", build)

    def _ended_binding(self, category: int, item: int, release: int) -> str | None:
        """Return an item's code in its latest binding to a category before a release.

        Returns:
            str | None: The code, or ``None`` if it was never bound there.
        """
        bindings = self._memo(
            "all bindings",
            lambda: _group(self._rows("ItemCategory"), lambda row: (row[1], row[0])),
        )
        rows = [
            row
            for row in bindings.get((category, item), ())
            if row[2] and (row[3] is None or row[3] <= release)
        ]
        if not rows:
            return None
        return max(rows, key=lambda row: (row[3] or 0, row[4] or 0))[2]

    def _categories(self) -> dict[int, Sequence[Any]]:
        return self._memo(
            "categories", lambda: {row[0]: row for row in self._rows("Category")}
        )

    def _prefix(self, category: int) -> str:
        """Return the namespace prefix of a category's items, such as ``eba_GA``.

        Returns:
            str: The owner's acronym in lower case, ``_`` and the category code.
        """
        owners = self._memo(
            "owners",
            lambda: {
                row[0]: (row[1] or "").lower() for row in self._rows("Organisation")
            },
        )
        row = self._categories()[category]
        return f"{owners.get(row[2]) or 'eba'}_{row[1]}"

    def _category_items(self, category: int, release: int) -> dict[int, list[str]]:
        """Return the item qnames of a category in a release.

        Items of the categories composed into it (``SuperCategoryComposition``)
        are included under their own category's prefix. An item that moves
        from one composed category to another in the release has both
        qnames, as the EBA's taxonomy of the release mostly lists both; the
        binding that starts later comes first.

        Returns:
            dict: ``ItemID`` to its qnames, such as ``eba_GA:LU``.
        """

        def build() -> dict[int, list[str]]:
            compositions = _latest(
                self._rows("SuperCategoryComposition"),
                lambda row: (row[0], row[1]),
                release,
                start=2,
                end=3,
                tie=1,
            )
            children: dict[int, list[int]] = defaultdict(list)
            for super_category, child in sorted(compositions):
                children[super_category].append(child)
            found: dict[int, list[tuple[int, str]]] = defaultdict(list)
            seen: set[int] = set()
            pending = [category]
            while pending:
                current = pending.pop(0)
                if current in seen or current not in self._categories():
                    continue
                seen.add(current)
                prefix = self._prefix(current)
                for item, row in self._bindings(release).get(current, {}).items():
                    found[item].append((row[3] or 0, f"{prefix}:{row[2]}"))
                pending.extend(children.get(current, ()))
            return {
                item: [
                    qname
                    for _, qname in sorted(
                        bindings, key=lambda binding: binding[0], reverse=True
                    )
                ]
                for item, bindings in found.items()
            }

        return self._memo(f"items:{category}:{release}", build)

    def _active_items(self) -> set[int]:
        return self._memo(
            "active items",
            lambda: {row[0] for row in self._rows("Item") if row[1] == 1},
        )

    def _property_category(self, prop: int, release: int) -> int | None:
        chosen = self._memo(
            f"property categories:{release}",
            lambda: _latest(
                self._rows("PropertyCategory"),
                lambda row: row[0],
                release,
                start=2,
                end=3,
                tie=1,
            ),
        )
        row = chosen.get(prop)
        return row[1] if row else None

    def _property_code(self, prop: int, release: int) -> str | None:
        """Return a property's code: its item's code in the ``_PR`` category.

        Returns:
            str | None: The code, such as ``qEBB``.
        """
        properties = next(
            (row[0] for row in self._rows("Category") if row[1] == "_PR"), None
        )
        if properties is None:
            return None
        row = self._bindings(release).get(properties, {}).get(prop)
        return row[2] if row else self._ended_binding(properties, prop, release)

    def _unit_contexts(self) -> set[Any]:
        """Return the contexts of values in their currency of denomination.

        They set property ``qAEA`` to item ``qx2000`` of category ``qCA``,
        found by these codes.

        Returns:
            set: The ``ContextID`` values.
        """

        def build() -> set[Any]:
            codes = {row[0]: row[1] for row in self._rows("Category")}
            bound = {
                (codes.get(row[1]), row[2]): row[0]
                for row in self._rows("ItemCategory")
                if row[2]
            }
            prop = bound.get(("_PR", "qAEA"))
            item = bound.get(("qCA", "qx2000"))
            if prop is None or item is None:
                return set()
            return {
                row[0]
                for row in self._rows("ContextComposition")
                if row[1] == prop and row[2] == item
            }

        return self._memo("unit contexts", build)

    def _data_type(self, prop: int | None) -> str | None:
        types = self._memo(
            "data types",
            lambda: {row[0]: row[1] or row[2] for row in self._rows("DataType")},
        )
        properties = self._memo("properties", lambda: dict(self._rows("Property")))
        return types.get(properties.get(prop)) if prop is not None else None

    def _items(
        self, prop: int, restriction: int | None, release: int, where: str
    ) -> list[str] | None:
        """Return the items a property's value may take.

        Args:
            prop: The ``PropertyID``.
            restriction: A ``SubCategoryVID`` that restricts the items, or
                ``None`` for every active item of the property's category.
            release: The ``ReleaseID``.
            where: Names the property in a warning.

        Returns:
            list[str] | None: The item qnames; ``None`` for a property whose
            category is not enumerated.
        """
        category = self._property_category(prop, release)
        if category is None or category not in self._categories():
            return None
        if restriction is None:
            if not self._categories()[category][3]:
                return None
            active = self._active_items()
            return sorted(
                qname
                for item, qnames in self._category_items(category, release).items()
                if item in active
                for qname in qnames
            )
        return self._subcategory_items(restriction, category, release, where)

    def _subcategory_items(
        self, vid: int, category: int, release: int, where: str
    ) -> list[str]:
        """Return the item qnames of a subcategory, in its order.

        Each item takes its code from the property's category, failing that
        from its latest binding there before the release, which the EBA can
        end before it moves the subcategory. An item that is not in the
        property's category, as when the subcategory belongs to another
        category, has no qname there and is left out. The first use of a
        subcategory reports such items.

        Returns:
            list[str]: The qnames.
        """
        key = f"subcategory:{vid}:{category}:{release}"
        if key in self._cache:
            return self._cache[key]
        versions = self._memo(
            "subcategory versions",
            lambda: {row[0]: row for row in self._rows("SubCategoryVersion")},
        )
        referenced = versions.get(vid)
        own = None
        if referenced is not None:
            own = dict(self._rows("SubCategory")).get(referenced[1])
        if own not in self._categories():
            own = None
        members = self._memo(
            "subcategory items",
            lambda: _group(self._rows("SubCategoryItem"), lambda row: row[0]),
        )
        found = self._category_items(category, release)
        items: list[str] = []
        carried: list[str] = []
        foreign: list[str] = []
        missing: list[str] = []
        for row in sorted(members.get(vid, ()), key=lambda row: (row[2] or 0, row[1])):
            item = row[1]
            qnames = found.get(item, [])
            if not qnames:
                code = self._ended_binding(category, item, release)
                if code is not None:
                    qnames = [f"{self._prefix(category)}:{code}"]
                    carried.extend(qnames)
            if not qnames:
                elsewhere = None
                if own is not None and own != category:
                    elsewhere = self._category_items(own, release).get(item)
                if elsewhere:
                    foreign.extend(elsewhere)
                else:
                    missing.append(str(item))
            items.extend(qname for qname in qnames if qname not in items)
        if carried:
            logger.warning(
                "%s: %s a binding that ended before the release, such as %s",
                where,
                _count(len(carried), "item keeps", "items keep"),
                carried[0],
            )
        if foreign:
            logger.warning(
                "%s: %s not in category %s of the property and left out: %s",
                where,
                _count(len(foreign), "item is", "items are"),
                self._categories()[category][1],
                ", ".join(foreign),
            )
        if missing:
            logger.warning(
                "%s: %s no code and left out: ItemID %s",
                where,
                _count(len(missing), "item has", "items have"),
                ", ".join(missing),
            )
        self._cache[key] = items
        return items


def _group(
    rows: Iterable[Sequence[Any]], key: Callable[[Sequence[Any]], Any]
) -> dict[Any, list[Sequence[Any]]]:
    grouped: dict[Any, list[Sequence[Any]]] = defaultdict(list)
    for row in rows:
        grouped[key(row)].append(row)
    return grouped


def _count(count: int, one: str, many: str) -> str:
    return f"{count} {one if count == 1 else many}"


def _date(value: object) -> str | None:
    """Return the ``YYYY-MM-DD`` part of a date value.

    Returns:
        str | None: The date, or ``None``.
    """
    if value is None or value == "":
        return None
    text = str(value)
    match = re.match(r"\d{4}-\d{2}-\d{2}", text)
    return match.group() if match else text


_COORDINATE = re.compile(r"^\s*([rcs])(\S+)\s*$")


def _coordinates(cell_code: str) -> dict[str, str | None]:
    """Return the row, column and sheet of a cell code.

    A cell code reads ``{C_01.00, r0010, c0010}``, with ``*`` for an open
    axis.

    Returns:
        dict: ``row``, ``column`` and ``sheet``; ``None`` for a missing axis.
    """
    parts = cell_code.strip().strip("{}").split(",")[1:]
    found: dict[str, str | None] = {"row": None, "column": None, "sheet": None}
    names = {"r": "row", "c": "column", "s": "sheet"}
    for part in parts:
        match = _COORDINATE.match(part)
        if match:
            found[names[match[1]]] = match[2]
    return found


def entry_point(framework: str, release: str, module: str) -> str:
    """Return the EBA's xBRL-CSV entry point of a module version.

    Args:
        framework: The framework code, such as ``COREP``.
        release: The code of the release that introduced the version.
        module: The module code.

    Returns:
        str: The entry point URL.

    Examples:
        >>> entry_point("COREP", "4.2", "COREP_OF")
        'http://www.eba.europa.eu/eu/fr/xbrl/crr/fws/corep/4.2/mod/corep_of.json'
    """
    return ENTRY_POINT.format(
        framework=framework.lower(), release=release, module=module.lower()
    )


def export_module(
    db: DpmRelease,
    module_code: str,
    release: str | None = None,
    *,
    format: str = MODULE_FORMAT,
    taxonomy_packages: Sequence[str | Path] = (),
) -> dict[str, Any]:
    """Export one module of a release as a ``dpm-module/1`` document.

    The document has the module's concrete tables (an abstract table gives
    the filing indicator of the tables it groups), their open keys and
    reportable cells, the module's filing indicators, its entry point and
    first reference date, [`DEFAULT_DECIMALS`][dpmxl.dpm.DEFAULT_DECIMALS],
    and the rules whose scope is this module alone, with their precondition,
    severity and whether the EBA deactivated them. A rule whose scope spans
    several modules is left out: one module's report cannot satisfy it.

    Args:
        db: The database, from [`open_release`][dpmxl.dpm.open_release].
        module_code: The module code, such as ``COREP_OF``; case is ignored.
        release: The release code, such as ``4.3``; ``None`` for the latest
            release of the database.
        format: The document's ``format``: ``dpm-module/1``, or
            ``dpm-synth-template/1``, which dpm-synth 1.0 needs and dpm-xl
            reads too.
        taxonomy_packages: The EBA's taxonomy packages (ZIP files) that hold
            the module version's entry point. Each enumerated cell and key
            then takes its items from the taxonomy's allowed values, which
            reports are validated against, and from the database where the
            taxonomy lists none.

    Returns:
        dict[str, Any]: The document; write it with ``json.dump``.

    Raises:
        DpmError: If the database has no such release, the module has no
            version or no tables in it, or ``format`` is not one of
            [`FORMATS`][dpmxl.module.FORMATS].
    """
    if format not in FORMATS:
        raise DpmError(f"format: expected one of {', '.join(FORMATS)}, got {format!r}")
    chosen = db.release(release)
    versions = db._module_versions(chosen.id)
    folded = module_code.casefold()
    found = [row for row in versions.values() if (row[2] or "").casefold() == folded]
    if not found:
        known = [
            module.code
            for module in db.modules(chosen.code)
            if module.code.casefold() != folded
        ]
        hint = f"; it has {', '.join(known)}" if len(known) <= 80 else ""
        raise DpmError(f"no module {module_code!r} in release {chosen.code}{hint}")
    version = found[0]
    taxonomy = _Taxonomy(taxonomy_packages) if taxonomy_packages else None
    try:
        document = _Export(db, chosen, version, versions, taxonomy).document()
    finally:
        if taxonomy is not None:
            taxonomy.close()
    document["format"] = format
    return document


_PACKAGE_MEMBER_BYTES = 256 * 1024**2
"""The largest metadata file read from a taxonomy package."""

_REWRITE = re.compile(r"<(?:\w+:)?rewriteURI\b[^>]*>")
_ATTRIBUTE = re.compile(r"""(\w+)\s*=\s*["']([^"']*)["']""")


@dataclass(slots=True)
class _Allowed:
    """The allowed items a taxonomy lists for one module.

    Attributes:
        cells: Datapoint code, such as ``dp12345``, to item qnames.
        keys: Table code and ``PropertyID`` of an open key to item qnames.
    """

    cells: dict[str, list[str]] = field(default_factory=dict)
    keys: dict[tuple[str, int], list[str]] = field(default_factory=dict)


class _Taxonomy:
    """The xBRL-CSV metadata of EBA taxonomy packages, read with ``zipfile``.

    A package maps URLs to its files in ``META-INF/catalog.xml``; each
    table's JSON metadata lists the allowed values of its enumerated
    datapoints and open keys (``AllowedValue`` in ``eba:documentation``).
    """

    def __init__(self, paths: Sequence[str | Path]):
        self.archives: dict[Path, zipfile.ZipFile] = {}
        self.prefixes: list[tuple[str, Path, str]] = []
        try:
            for path in map(Path, paths):
                try:
                    archive = zipfile.ZipFile(path)
                except FileNotFoundError as error:
                    raise DpmError(f"{path}: no such file") from error
                except (OSError, zipfile.BadZipFile) as error:
                    raise DpmError(
                        f"{path}: not a taxonomy package: {error}"
                    ) from error
                self.archives[path] = archive
                for name in archive.namelist():
                    if name.casefold().endswith("meta-inf/catalog.xml"):
                        self._catalog(path, name, archive.read(name))
        except BaseException:
            self.close()
            raise
        self.prefixes.sort(key=lambda prefix: len(prefix[0]), reverse=True)

    def close(self) -> None:
        """Close the packages."""
        for archive in self.archives.values():
            archive.close()

    def _catalog(self, path: Path, catalog: str, text: bytes) -> None:
        base = posixpath.dirname(catalog)
        for element in _REWRITE.finditer(text.decode("utf-8", "replace")):
            attributes = dict(_ATTRIBUTE.findall(element[0]))
            start = html.unescape(attributes.get("uriStartString", ""))
            prefix = html.unescape(attributes.get("rewritePrefix", ""))
            if start:
                member = posixpath.normpath(posixpath.join(base, prefix))
                self.prefixes.append((start, path, member))

    def read(self, url: str) -> Any:
        """Return the JSON document at a URL, or ``None`` if no package has it.

        Returns:
            Any: The parsed document, or ``None``.

        Raises:
            DpmError: If the file is too large or not JSON.
        """
        for start, path, member in self.prefixes:
            if not url.startswith(start):
                continue
            name = posixpath.join(member, url[len(start) :])
            archive = self.archives[path]
            try:
                info = archive.getinfo(name)
            except KeyError:
                continue
            if info.file_size > _PACKAGE_MEMBER_BYTES:
                raise DpmError(f"{path}: {name} is too large")
            try:
                return json.loads(archive.read(info))
            except (ValueError, zipfile.BadZipFile) as error:
                raise DpmError(f"{path}: {name}: not JSON: {error}") from error
        return None

    def allowed(self, url: str | None, module: str) -> _Allowed:
        """Return the allowed items of a module's tables.

        Returns:
            _Allowed: Those the taxonomy lists; empty, with a warning, when
            no package has the entry point.
        """
        found = _Allowed()
        document = self.read(url) if url else None
        if url is None or not isinstance(document, dict):
            logger.warning(
                "%s: no taxonomy package has entry point %s; items from the database",
                module,
                url,
            )
            return found
        extends = (document.get("documentInfo") or {}).get("extends") or []
        for reference in extends:
            table = self.read(urllib.parse.urljoin(url, reference))
            if not isinstance(table, dict):
                continue
            for name, template in (table.get("tableTemplates") or {}).items():
                code = name.replace("-", ".")
                for column in (template.get("columns") or {}).values():
                    documentation = column.get("eba:documentation") or {}
                    values = documentation.get("AllowedValue")
                    prop = documentation.get("PropertyID")
                    if isinstance(values, dict) and prop is not None:
                        with contextlib.suppress(ValueError):
                            found.keys[code, int(prop)] = list(values)
                    for point, group in (column.get("propertyGroups") or {}).items():
                        values = (group.get("eba:documentation") or {}).get(
                            "AllowedValue"
                        )
                        if isinstance(values, dict):
                            found.cells[point] = list(values)
        return found


class _Export:
    """The export of one module version in one release.

    The release selects the module version and the rules. The version's
    tables, headers, cells and variables are the versions its composition
    names, and its items those bound in the release that introduced it:
    the EBA builds the version's taxonomy from these, and does not change
    it in later releases.
    """

    def __init__(
        self,
        db: DpmRelease,
        release: Release,
        version: Sequence[Any],
        versions: Mapping[Any, Sequence[Any]],
        taxonomy: _Taxonomy | None = None,
    ):
        self.db = db
        self.taxonomy = taxonomy
        self.allowed = _Allowed()
        self.release = release
        self.version = version
        self.vid = version[0]
        self.code = version[2]
        self.module_codes = {row[0]: row[2] for row in versions.values()}
        self.basis = version[5] if version[5] is not None else release.id

    def document(self) -> dict[str, Any]:
        db, version = self.db, self.version
        frameworks = dict(db._rows("Framework"))
        module_frameworks = dict(db._rows("Module"))
        framework = frameworks.get(module_frameworks.get(version[1]))
        introduced = {row[0]: row[1] for row in db._rows("Release")}.get(version[5])
        point = (
            entry_point(framework, introduced, self.code)
            if framework and introduced
            else None
        )
        if self.taxonomy is not None:
            self.allowed = self.taxonomy.allowed(point, self.code)
        tables, filing_indicators = self.tables()
        if not tables:
            raise DpmError(
                f"module {self.code} has no tables with reportable cells in "
                f"release {self.release.code}"
            )
        document: dict[str, Any] = {
            "format": MODULE_FORMAT,
            "release": self.release.code,
            "module": self.code,
            "entry_point": point,
            "reference_date": _date(version[7]),
            "decimals": dict(DEFAULT_DECIMALS),
            "filing_indicators": filing_indicators,
            "tables": tables,
            "rules": self.rules(),
        }
        return document

    def tables(self) -> tuple[list[dict[str, Any]], list[str]]:
        db = self.db
        abstract = {row[0] for row in db._rows("Table") if row[1] == 1}
        by_vid = db._memo(
            "table versions", lambda: {row[0]: row for row in db._rows("TableVersion")}
        )
        effective = _latest(
            db._rows("TableVersion"),
            lambda row: row[1],
            self.basis,
            start=4,
            end=5,
            tie=0,
        )
        composed: dict[int, Sequence[Any]] = {}
        for row in db._rows("ModuleVersionComposition"):
            if row[0] != self.vid:
                continue
            current = by_vid.get(row[2]) or effective.get(row[1])
            if current is None:
                logger.warning(
                    "%s: table %s has no version; left out", self.code, row[1]
                )
                continue
            composed[current[1]] = current
        table_versions = {**effective, **composed}
        by_code: dict[str, Sequence[Any]] = {}
        for table_id, current in composed.items():
            if table_id in abstract or not current[2]:
                continue
            other = by_code.get(current[2])
            if other is None or (current[4] or 0) > (other[4] or 0):
                by_code[current[2]] = current
        declared = self.filing_indicators()
        filing_indicators = list(declared)
        tables = []
        for code in sorted(by_code):
            row = by_code[code]
            indicator = self.filing_indicator(row, table_versions, abstract, declared)
            if indicator not in filing_indicators:
                logger.warning(
                    "%s: filing indicator %s of table %s is not a module parameter; "
                    "added",
                    self.code,
                    indicator,
                    code,
                )
                filing_indicators.append(indicator)
            table: dict[str, Any] = {"code": code}
            if indicator != code:
                table["filing_indicator"] = indicator
            keys = self.open_keys(row[0], code)
            if keys:
                table["open_keys"] = keys
            table["cells"] = self.cells(row[0], code)
            if not table["cells"]:
                logger.warning("%s: table %s has no cells; left out", self.code, code)
                continue
            tables.append(table)
        return tables, sorted(filing_indicators)

    def filing_indicators(self) -> list[str]:
        """Return the module's filing indicators, from its parameters.

        Returns:
            list[str]: The codes, sorted.
        """
        by_vid = self.db._variables()
        codes = {
            by_vid[row[1]][4]
            for row in self.db._rows("ModuleParameters")
            if row[0] == self.vid and row[1] in by_vid and by_vid[row[1]][4]
        }
        return sorted(codes)

    def filing_indicator(
        self,
        row: Sequence[Any],
        table_versions: Mapping[Any, Sequence[Any]],
        abstract: set[int],
        declared: Sequence[str],
    ) -> str:
        """Return the filing indicator of a concrete table.

        It is the code of the abstract table that groups the table
        (``AbstractTableID``), when that table is abstract and has a
        version, else the table's own code.

        Returns:
            str: The filing indicator.
        """
        parent = row[3]
        if parent is not None and parent in abstract:
            parent_version = table_versions.get(parent)
            if parent_version is not None and parent_version[2]:
                return parent_version[2]
        elif parent is not None:
            logger.warning(
                "%s: table %s names %s as its abstract table, which is not "
                "abstract; ungrouped",
                self.code,
                row[2],
                parent,
            )
        return row[2]

    def open_keys(self, table_vid: int, table: str) -> list[dict[str, Any]]:
        db, basis = self.db, self.basis
        keys_by_header = {row[0] for row in db._rows("Header") if row[1] == 1}
        bound = db._memo(
            "table headers",
            lambda: _group(db._rows("TableVersionHeader"), lambda row: row[0]),
        )
        keys: list[dict[str, Any]] = []
        for link in sorted(
            bound.get(table_vid, ()), key=lambda row: (row[3] or 0, row[1])
        ):
            if link[1] not in keys_by_header:
                continue
            header = self.header(link[1], table_vid)
            if header is None or header[4] is None:
                continue
            variable = db._variables().get(header[4])
            prop = (variable[2] if variable else None) or header[2]
            if prop is None:
                continue
            code = db._property_code(prop, basis)
            where = f"{self.code}: open key {code or prop} of {table}"
            if code is None:
                logger.warning("%s has no property code; left out", where)
                continue
            if any(key["code"] == code for key in keys):
                continue
            restriction = header[3]
            if restriction is None and variable is not None:
                restriction = variable[3]
            items = db._items(prop, restriction, basis, where)
            if items is not None:
                items = self.allowed.keys.get((table, prop), items)
            key: dict[str, Any] = {"code": code, "column": code}
            if items is not None:
                key["items"] = items
            else:
                key["data_type"] = db._data_type(prop) or None
            keys.append(key)
        return keys

    def cells(self, table_vid: int, table: str) -> list[dict[str, Any]]:
        db = self.db
        rows = db._memo(
            "cells", lambda: _group(db._rows("TableVersionCell"), lambda row: row[0])
        )
        cells: list[dict[str, Any]] = []
        ids: set[str] = set()
        for row in sorted(rows.get(table_vid, ()), key=lambda row: row[3] or ""):
            if row[4] == 1 or row[5] == 1 or row[2] is None:
                continue
            variable = db._variables().get(row[2])
            if variable is None:
                logger.warning(
                    "%s: cell %s of %s names an unknown variable; left out",
                    self.code,
                    row[3],
                    table,
                )
                continue
            place = _coordinates(row[3] or "")
            identity = "/".join(
                [table]
                + [
                    f"{axis[0]}{value}"
                    for axis, value in place.items()
                    if value not in {None, "*"}
                ]
            )
            if identity in ids:
                identity = f"{identity}/{row[1]}"
            ids.add(identity)
            data_type = db._data_type(variable[2])
            cell: dict[str, Any] = {"id": identity, **place}
            cell["datapoint"] = f"dp{variable[1]}"
            cell["data_type"] = data_type
            if (
                data_type == "m"
                and variable[7] is not None
                and (variable[7] in db._unit_contexts())
            ):
                cell["unit"] = True
            if data_type == "e" and variable[2] is not None:
                restriction = self.cell_restriction(row[1], variable[2], table_vid)
                items = db._items(
                    variable[2],
                    variable[3] if restriction is None else restriction,
                    self.basis,
                    f"{self.code}: cell {row[3]}",
                )
                items = self.allowed.cells.get(cell["datapoint"], items)
                if items is not None:
                    cell["items"] = items
            cells.append(cell)
        return cells

    def cell_restriction(self, cell: int, prop: int, table_vid: int) -> int | None:
        """Return the subcategory that a cell's header sets for its value.

        A row, column or sheet header of the cell whose property is the
        value's property can restrict its items with a subcategory.

        Returns:
            int | None: The ``SubCategoryVID``, or ``None``.
        """
        db = self.db
        places = db._memo(
            "cell headers", lambda: {row[0]: row[1:] for row in db._rows("Cell")}
        )
        for header in places.get(cell, ()):
            if header is None:
                continue
            version = self.header(header, table_vid)
            if version is not None and version[2] == prop and version[3] is not None:
                return version[3]
        return None

    def header(self, header: int, table_vid: int) -> Sequence[Any] | None:
        """Return the version of a header that a table version names.

        Returns:
            Sequence | None: The ``HeaderVersion`` row the table version binds
            (``TableVersionHeader``), else the one valid in the release that
            introduced the module version.
        """
        db = self.db
        by_vid = db._memo(
            "header versions by vid",
            lambda: {row[0]: row for row in db._rows("HeaderVersion")},
        )
        bound = db._memo(
            "bound headers",
            lambda: {
                (row[0], row[1]): row[2] for row in db._rows("TableVersionHeader")
            },
        )
        found = by_vid.get(bound.get((table_vid, header)))
        if found is not None:
            return found
        headers = db._memo(
            "header versions",
            lambda: _group(db._rows("HeaderVersion"), lambda row: row[1]),
        )
        return _latest(
            headers.get(header, ()),
            lambda row: row[1],
            self.basis,
            start=5,
            end=6,
            tie=0,
        ).get(header)

    def rules(self) -> list[dict[str, Any]]:
        db, release = self.db, self.release.id
        operations = _latest(
            db._rows("OperationVersion"),
            lambda row: row[1],
            release,
            start=4,
            end=5,
            tie=0,
        )
        current = {row[0] for row in operations.values()}
        by_vid = db._memo(
            "operation versions",
            lambda: {row[0]: row for row in db._rows("OperationVersion")},
        )
        codes = dict(db._rows("Operation"))
        members = _group(db._rows("OperationScopeComposition"), lambda row: row[0])
        single: dict[int, list[Sequence[Any]]] = defaultdict(list)
        modules: dict[int, set[str]] = defaultdict(set)
        joint: set[int] = set()
        for scope in db._rows("OperationScope"):
            if scope[1] not in current:
                continue
            scoped = {row[1] for row in members.get(scope[0], ())}
            if self.vid not in scoped:
                if len(scoped) == 1:
                    (other,) = scoped
                    if other in self.module_codes:
                        modules[scope[1]].add(self.module_codes[other])
                continue
            if len(scoped) == 1:
                single[scope[1]].append(scope)
            else:
                joint.add(scope[1])
        left_out = sorted(
            codes.get(by_vid[vid][1], str(vid)) for vid in joint - set(single)
        )
        if left_out:
            logger.warning(
                "%s: left out %s whose scope spans several modules: %s",
                self.code,
                _count(len(left_out), "rule", "rules"),
                ", ".join(left_out),
            )
        rules: dict[str, dict[str, Any]] = {}
        for vid, scopes in single.items():
            row = by_vid[vid]
            code = codes.get(row[1])
            expression = (row[3] or "").strip()
            if not code or not expression:
                logger.warning(
                    "%s: rule %s has no code or expression; left out",
                    self.code,
                    code or vid,
                )
                continue
            expression = self.fix(code, expression)
            precondition = None
            if row[2] is not None:
                found = by_vid.get(row[2])
                precondition = (found[3] or "").strip() or None if found else None
                if precondition is None:
                    logger.warning(
                        "%s: precondition of rule %s not found; left out",
                        self.code,
                        code,
                    )
            live = [scope for scope in scopes if self.active(scope)]
            active = bool(live)
            chosen = live[0] if live else scopes[0]
            severity = (chosen[3] or "error").lower()
            rule: dict[str, Any] = {"code": code, "expression": expression}
            if precondition is not None:
                rule["precondition"] = precondition
            rule["severity"] = severity if severity in {"error", "warning"} else "error"
            rule["active"] = active
            rule["modules"] = sorted(modules[vid] | {self.code})
            if code in rules:
                logger.warning(
                    "%s: rule code %s repeats; the later version is kept",
                    self.code,
                    code,
                )
            rules[code] = rule
        return [rules[code] for code in sorted(rules)]

    def active(self, scope: Sequence[Any]) -> bool:
        """Tell whether a rule's scope is active in the release.

        A deactivated scope (``IsActive`` 0) stays active in the releases
        before its ``FromSubmissionDate``, from which the EBA deactivated it.

        Returns:
            bool: Whether the scope is active.
        """
        if scope[2] == 1:
            return True
        since, date = _date(scope[4]), self.release.date
        return since is not None and date is not None and date < since

    def fix(self, code: str, expression: str) -> str:
        for fix in KNOWN_ERRORS:
            if fix.rule == code and fix.wrong in expression:
                logger.warning(
                    "%s: rule %s: corrected %r to %r (%s)",
                    self.code,
                    code,
                    fix.wrong,
                    fix.right,
                    fix.reason,
                )
                return expression.replace(fix.wrong, fix.right, 1)
        return expression


__all__ = [
    "DEFAULT_DECIMALS",
    "ENTRY_POINT",
    "KNOWN_ERRORS",
    "TABLES",
    "DpmError",
    "DpmRelease",
    "ExpressionFix",
    "ModuleInfo",
    "Release",
    "entry_point",
    "export_module",
    "open_release",
]
