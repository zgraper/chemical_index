"""Tests for build_index and sync_index."""

import json
import pytest

from chemical_index.build_index import build_index
from chemical_index.sync_index import sync_index
from chemical_index.schema import get_connection


SAMPLE = [
    {
        "epa_reg_no": "524-308",
        "product_name": "Roundup Original",
        "alternate_names": ["Roundup"],
        "registrant": "Bayer CropScience LP",
        "active_ingredients": [{"name": "Glyphosate", "pct": 41.0}],
        "federal_status": "registered",
        "state_status_flags": {"CA": "registered"},
    },
    {
        "epa_reg_no": "100-1070",
        "product_name": "Enlist One Herbicide",
        "registrant": "Corteva Agriscience",
        "active_ingredients": [{"name": "2,4-D choline salt", "pct": 59.6}],
        "federal_status": "registered",
    },
]


def test_build_index_inserts_records(tmp_path):
    db = tmp_path / "test.sqlite"
    summary = build_index(SAMPLE, db)

    assert summary["records_processed"] == 2
    assert summary["records_inserted"] == 2
    assert summary["mode"] == "build"

    conn = get_connection(db)
    rows = conn.execute(
        "SELECT * FROM product_versions WHERE is_latest = 1"
    ).fetchall()
    conn.close()
    assert len(rows) == 2


def test_build_index_creates_run_record(tmp_path):
    db = tmp_path / "test.sqlite"
    summary = build_index(SAMPLE, db)

    conn = get_connection(db)
    run = conn.execute(
        "SELECT * FROM index_runs WHERE run_id = ?", (summary["run_id"],)
    ).fetchone()
    conn.close()

    assert run is not None
    assert run["mode"] == "build"
    assert run["records_processed"] == 2
    assert run["records_inserted"] == 2


def test_build_index_is_non_destructive(tmp_path):
    db = tmp_path / "test.sqlite"
    build_index(SAMPLE, db)
    build_index(SAMPLE, db)  # second build

    conn = get_connection(db)
    # Only 2 latest rows (one per EPA reg no)
    latest = conn.execute(
        "SELECT COUNT(*) FROM product_versions WHERE is_latest = 1"
    ).fetchone()[0]
    # Total rows = 4 (2 old retired + 2 new)
    total = conn.execute(
        "SELECT COUNT(*) FROM product_versions"
    ).fetchone()[0]
    conn.close()

    assert latest == 2
    assert total == 4  # each build creates new versions


def test_sync_index_no_insert_on_unchanged(tmp_path):
    db = tmp_path / "test.sqlite"
    build_index(SAMPLE, db)
    result = sync_index(SAMPLE, db)

    # Data unchanged – no new rows should be inserted
    assert result["records_inserted"] == 0

    conn = get_connection(db)
    total = conn.execute("SELECT COUNT(*) FROM product_versions").fetchone()[0]
    conn.close()
    assert total == 2


def test_sync_index_inserts_on_change(tmp_path):
    db = tmp_path / "test.sqlite"
    build_index(SAMPLE, db)

    modified = [
        {
            "epa_reg_no": "524-308",
            "product_name": "Roundup Original",
            "registrant": "Bayer CropScience LP",
            "active_ingredients": [{"name": "Glyphosate", "pct": 41.0}],
            "federal_status": "cancelled",  # changed!
        }
    ]
    result = sync_index(modified, db)
    assert result["records_inserted"] == 1

    conn = get_connection(db)
    latest = conn.execute(
        "SELECT federal_status FROM product_versions WHERE epa_reg_no = '524-308' AND is_latest = 1"
    ).fetchone()
    conn.close()
    assert latest["federal_status"] == "cancelled"


def test_build_index_from_file(tmp_path):
    import json
    source_file = tmp_path / "products.json"
    source_file.write_text(json.dumps(SAMPLE))

    db = tmp_path / "test.sqlite"
    summary = build_index(str(source_file), db)
    assert summary["records_inserted"] == 2


def test_build_index_skips_missing_epa_reg_no(tmp_path):
    db = tmp_path / "test.sqlite"
    data = [{"product_name": "No EPA number"}]
    summary = build_index(data, db)
    assert summary["records_processed"] == 1
    assert summary["records_inserted"] == 0
