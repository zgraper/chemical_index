"""Build index from source files or API responses."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .schema import create_schema, get_connection
from .normalize import normalize_record
from .hashing import hash_record


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_source(source: str | Path | list[dict]) -> list[dict]:
    """Load source data from a file path or an already-parsed list."""
    if isinstance(source, list):
        return source
    path = Path(source)
    with path.open("r", encoding="utf-8") as fh:
        data = json.load(fh)
    if isinstance(data, list):
        return data
    # Support a single dict
    return [data]


def build_index(
    source: str | Path | list[dict],
    db_path: str | Path,
    *,
    notes: str | None = None,
) -> dict[str, Any]:
    """
    Build (or rebuild) the index from *source*.

    This is a **non-destructive** build: existing rows are kept.  Each record
    in *source* is inserted as the latest version for its EPA reg no, and any
    previous ``is_latest`` rows for that reg no are flipped to 0.

    Returns a summary dict with run statistics.
    """
    run_id = str(uuid.uuid4())
    started_at = _utcnow()
    source_path = str(source) if not isinstance(source, list) else "<in-memory>"

    create_schema(db_path)
    conn = get_connection(db_path)

    # Open the run record
    conn.execute(
        """
        INSERT INTO index_runs (run_id, mode, started_at, source_path, notes)
        VALUES (?, 'build', ?, ?, ?)
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

        # Determine first_seen_at – reuse oldest existing row if present
        row = conn.execute(
            "SELECT first_seen_at FROM product_versions WHERE epa_reg_no = ? ORDER BY id ASC LIMIT 1",
            (epa_reg_no,),
        ).fetchone()
        first_seen_at = row["first_seen_at"] if row else now

        # Mark all existing latest rows as not-latest
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
        "mode": "build",
        "started_at": started_at,
        "finished_at": finished_at,
        "records_processed": records_processed,
        "records_inserted": records_inserted,
    }
