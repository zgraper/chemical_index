"""Sync index – compare current metadata to latest records, only insert on change."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .schema import create_schema, get_connection
from .normalize import normalize_record
from .hashing import hash_record
from .build_index import _load_source, _utcnow


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

    Returns a summary dict with run statistics.
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

    records = _load_source(source)
    records_processed = 0
    records_inserted = 0

    for raw in records:
        records_processed += 1
        normalised = normalize_record(raw)

        epa_reg_no = normalised["epa_reg_no"]
        if not epa_reg_no:
            continue

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

        if latest and latest["source_hash"] == source_hash:
            # Data unchanged – touch last_seen_at only
            conn.execute(
                "UPDATE product_versions SET last_seen_at = ?, retrieved_at = ? WHERE id = ?",
                (now, now, latest["id"]),
            )
        else:
            # Data changed or brand-new – insert a new version
            first_seen_at = latest["first_seen_at"] if latest else now

            # Retire old latest rows
            conn.execute(
                "UPDATE product_versions SET is_latest = 0, last_seen_at = ? WHERE epa_reg_no = ? AND is_latest = 1",
                (now, epa_reg_no),
            )

            conn.execute(
                """
                INSERT INTO product_versions (
                    epa_reg_no, product_name, alternate_names, registrant,
                    active_ingredients, label_stamped_date, source_url, pdf_url,
                    federal_status, state_status_flags, source_hash, raw_source_json,
                    is_latest, first_seen_at, last_seen_at, retrieved_at, run_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?)
                """,
                (
                    epa_reg_no,
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
            records_inserted += 1

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
    }
