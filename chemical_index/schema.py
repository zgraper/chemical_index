"""SQLite schema creation for the chemical label metadata index."""

import sqlite3
from pathlib import Path


DDL_INDEX_RUNS = """
CREATE TABLE IF NOT EXISTS index_runs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id      TEXT    NOT NULL UNIQUE,
    mode        TEXT    NOT NULL,  -- 'build' or 'sync'
    started_at  TEXT    NOT NULL,
    finished_at TEXT,
    records_processed INTEGER DEFAULT 0,
    records_inserted  INTEGER DEFAULT 0,
    source_path TEXT,
    notes       TEXT
);
"""

DDL_PRODUCT_VERSIONS = """
CREATE TABLE IF NOT EXISTS product_versions (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    epa_reg_no        TEXT    NOT NULL,
    product_name      TEXT,
    alternate_names   TEXT,   -- JSON array of strings
    registrant        TEXT,
    active_ingredients TEXT,  -- JSON array of {name, pct} objects
    label_stamped_date TEXT,
    source_url        TEXT,
    pdf_url           TEXT,
    federal_status    TEXT,
    state_status_flags TEXT,  -- JSON object {state: status}
    source_hash       TEXT    NOT NULL,
    raw_source_json   TEXT    NOT NULL,
    is_latest         INTEGER NOT NULL DEFAULT 1,  -- 1 = true, 0 = false
    first_seen_at     TEXT    NOT NULL,
    last_seen_at      TEXT    NOT NULL,
    retrieved_at      TEXT    NOT NULL,
    run_id            TEXT    NOT NULL
);
"""

DDL_INDEXES = """
CREATE INDEX IF NOT EXISTS idx_pv_epa_reg_no  ON product_versions (epa_reg_no);
CREATE INDEX IF NOT EXISTS idx_pv_is_latest   ON product_versions (is_latest);
CREATE INDEX IF NOT EXISTS idx_pv_product_name ON product_versions (product_name COLLATE NOCASE);
CREATE INDEX IF NOT EXISTS idx_pv_registrant  ON product_versions (registrant COLLATE NOCASE);
"""


def get_connection(db_path: str | Path) -> sqlite3.Connection:
    """Return a sqlite3 connection with row_factory set."""
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn


def create_schema(db_path: str | Path) -> None:
    """Create all tables and indexes if they do not already exist."""
    conn = get_connection(db_path)
    with conn:
        conn.execute(DDL_INDEX_RUNS)
        conn.execute(DDL_PRODUCT_VERSIONS)
        for stmt in DDL_INDEXES.strip().split("\n"):
            stmt = stmt.strip()
            if stmt:
                conn.execute(stmt)
    conn.close()
