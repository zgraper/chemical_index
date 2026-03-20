"""Tests for schema creation."""

import sqlite3
from pathlib import Path
import pytest

from chemical_index.schema import create_schema, get_connection


def test_create_schema_idempotent(tmp_path):
    db = tmp_path / "test.sqlite"
    create_schema(db)
    create_schema(db)  # calling twice should not raise

    conn = get_connection(db)
    tables = {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    conn.close()
    assert "product_versions" in tables
    assert "index_runs" in tables


def test_product_versions_columns(tmp_path):
    db = tmp_path / "test.sqlite"
    create_schema(db)

    conn = get_connection(db)
    info = conn.execute("PRAGMA table_info(product_versions)").fetchall()
    conn.close()

    col_names = {row[1] for row in info}
    expected = {
        "id", "epa_reg_no", "product_name", "alternate_names", "registrant",
        "active_ingredients", "label_stamped_date", "source_url", "pdf_url",
        "federal_status", "state_status_flags", "source_hash", "raw_source_json",
        "is_latest", "first_seen_at", "last_seen_at", "retrieved_at", "run_id",
    }
    assert expected.issubset(col_names)


def test_index_runs_columns(tmp_path):
    db = tmp_path / "test.sqlite"
    create_schema(db)

    conn = get_connection(db)
    info = conn.execute("PRAGMA table_info(index_runs)").fetchall()
    conn.close()

    col_names = {row[1] for row in info}
    expected = {
        "id", "run_id", "mode", "started_at", "finished_at",
        "records_processed", "records_inserted", "source_path", "notes",
    }
    assert expected.issubset(col_names)
