"""Build the expression corpus from one or more DPM databases.

Usage: ``python benchmarks/build_corpus.py OUT.txt DB.sqlite [DB.sqlite ...]``

Each database is an EBA DPM 2.0 database (published by the EBA as a Microsoft
Access file) migrated to SQLite, for example with ``pydpm migrate-access``
or ``dpmcore migrate``. The corpus holds every distinct rule and
precondition expression of the ``OperationVersion`` table, one per line,
sorted. A few expressions span several lines; their line breaks become spaces,
so that each expression is one line.

The corpus is derived from EBA data, so it is not committed to this
repository.
"""

import sqlite3
import sys
from pathlib import Path


def main(out: str, *databases: str) -> int:
    """Write the corpus.

    Returns:
        int: The exit status.
    """
    expressions: set[str] = set()
    for database in databases:
        connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
        try:
            rows = connection.execute(
                "SELECT Expression FROM OperationVersion WHERE Expression IS NOT NULL"
            )
            expressions.update(" ".join(row[0].strip().splitlines()) for row in rows)
        finally:
            connection.close()
    expressions.discard("")
    Path(out).write_text("\n".join(sorted(expressions)) + "\n", encoding="utf-8")
    print(f"{len(expressions)} expressions written to {out}")
    return 0


if __name__ == "__main__":
    if len(sys.argv) < 3:
        raise SystemExit(__doc__.splitlines()[2])
    raise SystemExit(main(*sys.argv[1:]))
