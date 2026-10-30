"""Build a tiny synthetic EBA DPM 2.0 database, for the docs and tests.

Usage: ``python examples/dpm_demo.py [OUT.sqlite]`` (default
``examples/dpm-demo.sqlite``).

The database has the tables and columns of the EBA's DPM 2.0 database that
``dpmxl.dpm`` reads, with made-up rows: three releases, a module ``DEMO``
in two versions with an abstract table, a closed and an open table, and a
few rules; a module ``OTHER`` that shares a rule; and a module ``DOCS``
without tables. The comments name what each row exercises.
"""

import sqlite3
import sys
from pathlib import Path

from dpmxl.dpm import TABLES

E, PR = 1012, 19  # the EBA's organisation, the _PR category of properties
M, EN, S, ES = 1, 2, 3, 4  # data types: monetary, enumeration, text, es

ROWS: dict[str, list[tuple]] = {
    "Release": [  # ReleaseID, Code, Date, Type
        (1, "1.0", "2025-01-15", "module"),
        (2, "2.0", "2026-01-15", "module"),
        (3, "2.0.1", "2026-04-15", "deactivation"),
    ],
    "Organisation": [(E, "EBA")],
    "Framework": [(1, "DEMO")],
    "Module": [(10, 1), (11, 1), (12, 1)],
    "ModuleVersion": [
        # ModuleVID, ModuleID, Code, Name, VersionNumber, Start, End, From, To
        (100, 10, "DEMO", "Demo module", "1.0.0", 1, 2, "2025-03-31", "2026-03-30"),
        (101, 10, "DEMO", "Demo module", "2.0.0", 2, None, "2026-03-31", None),
        (110, 11, "OTHER", "Other module", "1.0.0", 1, None, "2025-03-31", None),
        (120, 12, "DOCS", "Documents", "1.0.0", 1, None, "2025-03-31", None),
    ],
    "ModuleVersionComposition": [  # ModuleVID, TableID, TableVID
        (100, 1, 11),
        (100, 2, 21),
        (100, 3, 31),
        (101, 1, 11),
        (101, 2, 22),
        (101, 3, 31),
        (110, 4, 41),
    ],
    "ModuleParameters": [(100, 900), (100, 901), (101, 900), (101, 901), (110, 902)],
    "Table": [(1, 1), (2, 0), (3, 0), (4, 0)],  # TableID, IsAbstract
    "TableVersion": [  # TableVID, TableID, Code, AbstractTableID, Start, End
        (11, 1, "T_01.00", None, 1, None),
        (21, 2, "T_01.00.a", 1, 1, 2),
        (22, 2, "T_01.00.a", 1, 2, None),
        (31, 3, "T_02.00", None, 1, None),
        (41, 4, "O_01.00", None, 1, None),
    ],
    "TableVersionCell": [  # TableVID, CellID, VariableVID, CellCode, Excl, Void
        (21, 1, 501, "{T_01.00.a, r0010, c0010}", 0, 0),
        (22, 1, 501, "{T_01.00.a, r0010, c0010}", 0, 0),
        (22, 2, 502, "{T_01.00.a, r0020, c0010}", 0, 0),
        (22, 3, None, "{T_01.00.a, r0030, c0010}", 1, 0),  # excluded
        (22, 4, 504, "{T_01.00.a, r0040, c0010}", 0, 1),  # void
        (22, 5, 505, "{T_01.00.a, r0050, c0010}", 0, 0),  # es, text that may be empty
        (22, 6, 506, "{T_01.00.a, r0060, c0010}", 0, 0),  # no item allowed
        (22, 7, 507, "{T_01.00.a, r0070, c0010}", 0, 0),  # an item of another category
        (31, 10, 510, "{T_02.00, r*, c0010}", 0, 0),
        (31, 11, 511, "{T_02.00, r*, c0020}", 0, 0),
        (41, 20, 520, "{O_01.00, r0010, c0010}", 0, 0),
    ],
    "Cell": [  # CellID, RowID, ColumnID, SheetID (header IDs)
        (1, 62, 61, None),
        (2, 60, 61, None),
        (5, 63, 61, None),
        (6, 66, 61, None),
        (7, 67, 61, None),
        (10, None, 64, None),
        (11, None, 65, None),
        (20, None, None, None),
    ],
    "TableVersionHeader": [  # TableVID, HeaderID, HeaderVID, Order
        (22, 60, 560, 1),
        (22, 61, 561, 2),
        (22, 66, 566, 3),
        (22, 67, 567, 4),
        (31, 50, 550, 1),
        (31, 51, 551, 2),
        (31, 64, 564, 3),
        (31, 65, 565, 4),
    ],
    "Header": [
        (50, 1),
        (51, 1),
        (60, 0),
        (61, 0),
        (62, 0),
        (63, 0),
        (64, 0),
        (65, 0),
        (66, 0),
        (67, 0),
    ],
    "HeaderVersion": [
        # HeaderVID, HeaderID, PropertyID, SubCategoryVID, KeyVariableVID, S, E
        (550, 50, 1003, 700, 600, 1, None),  # key restricted by subcategory 700
        (551, 51, 1004, None, 601, 1, None),  # typed text key
        (560, 60, 1002, 701, None, 1, None),  # restricts cell 2 to x1
        (561, 61, None, None, None, 1, None),
        (564, 64, 1001, None, None, 1, None),
        (565, 65, 1006, None, None, 1, None),
        (566, 66, 1002, 703, None, 1, None),  # an empty subcategory: no item
        (567, 67, 1002, 704, None, 1, None),  # a subcategory of CC for a CA property
    ],
    "VariableVersion": [
        # VariableVID, VariableID, PropertyID, SubCategoryVID, Code, Start, End
        (501, 501, 1001, None, None, 1, None),
        (502, 502, 1002, None, None, 1, None),
        (504, 504, 1001, None, None, 1, None),
        (505, 505, 1005, None, None, 1, None),
        (506, 506, 1002, None, None, 1, None),
        (507, 507, 1002, None, None, 1, None),
        (510, 510, 1001, None, None, 1, None),
        (511, 511, 1006, None, None, 1, None),
        (520, 520, 1001, None, None, 1, None),
        (600, 600, 1003, None, None, 1, None),
        (601, 601, 1004, None, None, 1, None),
        (900, 900, 1009, None, "T_01.00", 1, None),  # filing indicators
        (901, 901, 1009, None, "T_02.00", 1, None),
        (902, 902, 1009, None, "O_01.00", 1, None),
    ],
    "Property": [(1001, M), (1002, EN), (1003, EN), (1004, S), (1005, ES), (1006, EN)],
    "DataType": [
        (M, "m", "monetary"),
        (EN, "e", "enumeration"),
        (S, "s", "string"),
        (ES, "es", "string (including empty string)"),
    ],
    "PropertyCategory": [  # PropertyID, CategoryID, Start, End
        (1002, 20, 1, None),
        (1003, 20, 1, None),
        (1004, 23, 1, None),
        (1006, 21, 1, None),
    ],
    "Category": [  # CategoryID, Code, OwnerID, IsEnumerated
        (PR, "_PR", E, 1),
        (20, "CA", E, 1),
        (21, "CB", E, 1),  # composed of CC and CD
        (22, "CC", E, 1),
        (23, "CN", E, 0),
        (24, "CD", E, 1),
    ],
    "Item": [  # ItemID, IsActive; properties are items too
        *[(item, 1) for item in (1001, 1002, 1003, 1004, 1005, 1006)],
        *[(2001, 1), (2002, 1), (2003, 0), (2004, 1), (2010, 1), (2011, 1)],
    ],
    "ItemCategory": [  # ItemID, CategoryID, Code, Start, End
        (1001, PR, "pM", 1, None),
        (1002, PR, "pE", 1, None),
        (1003, PR, "qKEY", 1, None),
        (1004, PR, "qTXT", 1, None),
        (1005, PR, "pES", 1, None),
        (1006, PR, "pF", 1, None),
        (2001, 20, "x1", 1, None),
        (2002, 20, "x2", 1, None),
        (2003, 20, "x3", 1, None),  # inactive item
        (2004, 20, "x4", 1, 1),  # binding ended in release 1.0
        (2010, 22, "y1", 1, None),
        (2011, 22, "y2", 1, 2),  # moves from CC to CD in release 2.0
        (2011, 24, "z2", 2, None),
    ],
    "SuperCategoryComposition": [(21, 22, 1, None), (21, 24, 1, None)],
    "SubCategory": [
        (70, 20),
        (71, 20),
        (72, 20),
        (73, 22),
    ],  # SubCategoryID, CategoryID
    "SubCategoryVersion": [  # SubCategoryVID, SubCategoryID, Start, End
        (700, 70, 1, None),
        (701, 71, 1, 2),
        (702, 71, 2, None),  # a later version, which DEMO 2.0.0 does not name
        (703, 72, 1, None),  # no items
        (704, 73, 1, None),
    ],
    "SubCategoryItem": [  # SubCategoryVID, ItemID, Order
        (700, 2002, 1),
        (700, 2001, 2),
        (700, 2004, 3),
        (701, 2001, 1),
        (702, 2002, 1),
        (704, 2001, 1),  # x1 is in CA
        (704, 2010, 2),  # y1 is only in CC: left out
    ],
    "Operation": [
        (1, "v1"),
        (2, "v7551_m"),  # a known typo: trueendif
        (3, "v3"),
        (4, "v4"),
        (5, "p1"),
        (6, "v6"),
    ],
    "OperationVersion": [
        # OperationVID, OperationID, PreconditionOperationVID, Expression, S, E
        (801, 1, None, "{tT_01.00.a, r0010, c0010} > 0", 1, 1),
        (802, 1, 850, "{tT_01.00.a, r0010, c0010} >= 0", 2, None),
        (803, 2, None, "if {tT_02.00, c0010} > 0 then true else trueendif", 1, None),
        (
            804,
            3,
            None,
            "{tT_01.00.a, r0010, c0010} = {tO_01.00, r0010, c0010}",
            1,
            None,
        ),
        (805, 4, None, "{tT_02.00, c0010} >= 0", 1, None),
        (806, 6, None, "{tT_01.00.a, r0020, c0010} in {[eba_CA:x1]}", 2, None),
        (850, 5, None, "{v_T_01.00}", 1, None),
    ],
    "OperationScope": [  # OperationScopeID, OperationVID, IsActive, Severity
        (1, 801, 1, "error"),
        (2, 802, 1, "error"),
        (3, 803, 1, "warning"),
        (4, 803, 1, "warning"),
        (5, 804, 1, "error"),
        (6, 805, 1, "error"),
        (7, 806, 0, "warning"),  # deactivated
    ],
    "OperationScopeComposition": [  # OperationScopeID, ModuleVID
        (1, 100),
        (2, 101),
        (3, 101),
        (4, 110),  # the same rule for OTHER
        (5, 101),
        (5, 110),  # one scope for two modules: left out
        (6, 100),
        (7, 101),
    ],
}


def build(path: str | Path) -> Path:
    """Write the database, replacing any file at ``path``.

    Returns:
        Path: The path.
    """
    path = Path(path)
    path.unlink(missing_ok=True)
    connection = sqlite3.connect(path)
    connection.execute("PRAGMA page_size = 512")
    with connection:
        for table, columns in TABLES.items():
            names = ", ".join(f'"{column}"' for column in columns)
            connection.execute(f'CREATE TABLE "{table}" ({names})')
            marks = ", ".join("?" * len(columns))
            connection.executemany(
                f'INSERT INTO "{table}" VALUES ({marks})',  # ruff: ignore[hardcoded-sql-expression] - constant names
                ROWS.get(table, []),
            )
    connection.execute("VACUUM")
    connection.close()
    return path


if __name__ == "__main__":
    target = (
        sys.argv[1]
        if len(sys.argv) > 1
        else Path(__file__).with_name("dpm-demo.sqlite")
    )
    print(build(target))
