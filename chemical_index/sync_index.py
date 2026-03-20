"""Sync index – compare current metadata to latest records, only insert on change."""

from __future__ import annotations

import json
import sqlite3
import uuid
from pathlib import Path
from typing import Any

from .schema import create_schema, get_connection
from .normalize import normalize_record
from .hashing import hash_record, compare_source_hashes
from .build_index import _load_source, _utcnow


def demote_latest(conn: sqlite3.Connection, epa_reg_no: str, now: str) -> None:
    """Set ``is_latest = 0`` for all current latest rows for *epa_reg_no*."""
    conn.execute(
        "UPDATE product_versions SET is_latest = 0, last_seen_at = ? WHERE epa_reg_no = ? AND is_latest = 1",
        (now, epa_reg_no),
    )


def promote_latest(
    conn: sqlite3.Connection,
    normalised: dict,
    raw: dict,
    source_hash: str,
    first_seen_at: str,
    now: str,
    run_id: str,
) -> None:
    """Insert a new ``is_latest = 1`` row for the given normalised record."""
    conn.execute(
        """
        INSERT INTO product_versions (
            epa_reg_no, product_name, alternate_names, registrant,
            active_ingredients, label_stamped_date, source_url, pdf_url,
            federal_status, state_status_flags, source_hash, raw_source_json,
            is_latest, first_seen_at, last_seen_at, retrieved_at, run_id,
            absent_since
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?, NULL)
        """,
        (
            normalised["epa_reg_no"],
            normalised["product_name"],
            json.dumps(normalised["alternate_names"]),
            normalised["registrant"],
            json.dumps(normalised["active_ingredients"]),
            normalised["label_stamped_date"],
            normalised["source_url"],
            normalised["pdf_url"],
            normalised["federal_status"],
            json.dumps(normalised["state_status_flags"]),
            source_hash,
            json.dumps(raw, default=str),
            first_seen_at,
            now,
            now,
            run_id,
        ),
    )


def sync_index(
    source: str | Path | list[dict],
    db_path: str | Path,
    *,
    notes: str | None = None,
) -> dict[str, Any]:
    """
    Incrementally sync the index from *source*.

    For each record in *source*:

    - Compute its source hash.
    - If a latest row with the same hash already exists → update ``last_seen_at``
      only (no new version row).
    - If the hash differs from the latest row, or no row exists → insert a new
      version row and mark old latest rows as not-latest.

    Products that are currently marked ``is_latest = 1`` in the database but
    are **not present** in *source* are marked as absent (``absent_since`` is
    set) rather than deleted.  If an absent product reappears in a later run
    its ``absent_since`` is cleared.

    Returns a sync-report dict with run statistics.
    """
    run_id = str(uuid.uuid4())
    started_at = _utcnow()
    source_path = str(source) if not isinstance(source, list) else "<in-memory>"

    create_schema(db_path)
    conn = get_connection(db_path)

    conn.execute(
        """
        INSERT INTO index_runs (run_id, mode, started_at, source_path, notes)
        VALUES (?, 'sync', ?, ?, ?)
        """,
        (run_id, started_at, source_path, notes),
    )
    conn.commit()

    # Snapshot the set of EPA reg nos that are currently latest before we start.
    existing_latest: set[str] = {
        row["epa_reg_no"]
        for row in conn.execute(
            "SELECT epa_reg_no FROM product_versions WHERE is_latest = 1"
        ).fetchall()
    }

    records = _load_source(source)
    records_processed = 0
    records_inserted = 0

    seen_reg_nos: set[str] = set()
    new_products: list[str] = []
    changed_products: list[str] = []
    unchanged_products: list[str] = []

    for raw in records:
        records_processed += 1
        normalised = normalize_record(raw)

        epa_reg_no = normalised["epa_reg_no"]
        if not epa_reg_no:
            continue

        seen_reg_nos.add(epa_reg_no)
        source_hash = hash_record(normalised)
        now = _utcnow()

        # Look up the current latest row
        latest = conn.execute(
            """
            SELECT id, source_hash, first_seen_at
            FROM product_versions
            WHERE epa_reg_no = ? AND is_latest = 1
            ORDER BY id DESC LIMIT 1
            """,
            (epa_reg_no,),
        ).fetchone()

        if latest and compare_source_hashes(latest["source_hash"], source_hash):
            # Data unchanged – touch last_seen_at and clear any absent flag.
            unchanged_products.append(epa_reg_no)
            conn.execute(
                "UPDATE product_versions SET last_seen_at = ?, retrieved_at = ?, absent_since = NULL WHERE id = ?",
                (now, now, latest["id"]),
            )
        else:
            # Data changed or brand-new – insert a new version.
            first_seen_at = latest["first_seen_at"] if latest else now

            if latest is None:
                new_products.append(epa_reg_no)
            else:
                changed_products.append(epa_reg_no)

            demote_latest(conn, epa_reg_no, now)
            promote_latest(conn, normalised, raw, source_hash, first_seen_at, now, run_id)
            records_inserted += 1

    # Products previously latest but absent from this source run.
    missing_reg_nos = sorted(existing_latest - seen_reg_nos)
    for reg_no in missing_reg_nos:
        now = _utcnow()
        conn.execute(
            """
            UPDATE product_versions
            SET absent_since = ?
            WHERE epa_reg_no = ? AND is_latest = 1 AND absent_since IS NULL
            """,
            (now, reg_no),
        )

    finished_at = _utcnow()
    conn.execute(
        """
        UPDATE index_runs
        SET finished_at = ?, records_processed = ?, records_inserted = ?
        WHERE run_id = ?
        """,
        (finished_at, records_processed, records_inserted, run_id),
    )
    conn.commit()
    conn.close()

    return {
        "run_id": run_id,
        "mode": "sync",
        "started_at": started_at,
        "finished_at": finished_at,
        "records_processed": records_processed,
        "records_inserted": records_inserted,
        "total_records_seen": len(seen_reg_nos),
        "new_products": len(new_products),
        "changed_products": len(changed_products),
        "unchanged_products": len(unchanged_products),
        "missing_products": len(missing_reg_nos),
        "missing_epa_reg_nos": missing_reg_nos,
    }
