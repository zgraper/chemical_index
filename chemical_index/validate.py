"""Database integrity checks for the chemical label metadata index."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from .schema import create_schema, get_connection


def check_single_latest_per_reg_no(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """
    Return a list of EPA reg nos that have more than one ``is_latest = 1`` row.

    An empty list means the constraint is satisfied.
    """
    rows = conn.execute(
        """
        SELECT epa_reg_no, COUNT(*) AS cnt
        FROM product_versions
        WHERE is_latest = 1
        GROUP BY epa_reg_no
        HAVING cnt > 1
        """
    ).fetchall()
    return [{"epa_reg_no": r["epa_reg_no"], "count": r["cnt"]} for r in rows]


def check_no_orphan_run_ids(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """
    Return ``product_versions`` run IDs that have no matching ``index_runs`` row.

    An empty list means every version row references a known run.
    """
    rows = conn.execute(
        """
        SELECT DISTINCT pv.run_id
        FROM product_versions pv
        LEFT JOIN index_runs ir ON pv.run_id = ir.run_id
        WHERE ir.run_id IS NULL
        """
    ).fetchall()
    return [{"run_id": r["run_id"]} for r in rows]


def check_duplicate_hashes_on_latest(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """
    Return source hashes that appear on more than one ``is_latest = 1`` row.

    Duplicate hashes on latest rows suggest two distinct EPA reg nos share
    identical content, which may indicate a data-quality issue.

    An empty list means all latest rows have unique hashes.
    """
    rows = conn.execute(
        """
        SELECT source_hash, COUNT(*) AS cnt, GROUP_CONCAT(epa_reg_no) AS epa_reg_nos
        FROM product_versions
        WHERE is_latest = 1
        GROUP BY source_hash
        HAVING cnt > 1
        """
    ).fetchall()
    return [
        {
            "source_hash": r["source_hash"],
            "count": r["cnt"],
            "epa_reg_nos": r["epa_reg_nos"],
        }
        for r in rows
    ]


def validate_database(db_path: str | Path) -> dict[str, Any]:
    """
    Run all integrity checks against *db_path* and return a validation report.

    The report has the shape::

        {
            "valid": bool,          # True when no issues were found
            "issues": [             # flat list of all violations
                {"type": "...", ...},
                ...
            ],
            "checks": {             # per-check detail
                "single_latest_per_reg_no": {"violations": [...]},
                "no_orphan_run_ids":        {"violations": [...]},
                "duplicate_hashes_on_latest": {"violations": [...]},
            },
        }
    """
    create_schema(db_path)
    conn = get_connection(db_path)

    multi_latest = check_single_latest_per_reg_no(conn)
    orphan_run_ids = check_no_orphan_run_ids(conn)
    dup_hashes = check_duplicate_hashes_on_latest(conn)

    conn.close()

    issues: list[dict[str, Any]] = []
    for v in multi_latest:
        issues.append(
            {
                "type": "multiple_latest",
                "epa_reg_no": v["epa_reg_no"],
                "count": v["count"],
            }
        )
    for o in orphan_run_ids:
        issues.append({"type": "orphan_run_id", "run_id": o["run_id"]})
    for d in dup_hashes:
        issues.append(
            {
                "type": "duplicate_hash_on_latest",
                "source_hash": d["source_hash"],
                "count": d["count"],
                "epa_reg_nos": d["epa_reg_nos"],
            }
        )

    return {
        "valid": len(issues) == 0,
        "issues": issues,
        "checks": {
            "single_latest_per_reg_no": {"violations": multi_latest},
            "no_orphan_run_ids": {"violations": orphan_run_ids},
            "duplicate_hashes_on_latest": {"violations": dup_hashes},
        },
    }
