"""Tests for sync report statistics and absent-product marking."""

from __future__ import annotations

import pytest

from chemical_index.build_index import build_index
from chemical_index.sync_index import sync_index, demote_latest, promote_latest
from chemical_index.schema import get_connection
from chemical_index.hashing import hash_record, compare_source_hashes
from chemical_index.normalize import normalize_record


SAMPLE = [
    {
        "epa_reg_no": "524-308",
        "product_name": "Roundup Original",
        "registrant": "Bayer CropScience LP",
        "active_ingredients": [{"name": "Glyphosate", "pct": 41.0}],
        "federal_status": "registered",
    },
    {
        "epa_reg_no": "100-1070",
        "product_name": "Enlist One Herbicide",
        "registrant": "Corteva Agriscience",
        "active_ingredients": [{"name": "2,4-D choline salt", "pct": 59.6}],
        "federal_status": "registered",
    },
]


# ---------------------------------------------------------------------------
# Sync report counters
# ---------------------------------------------------------------------------

def test_sync_report_all_new(tmp_path):
    """First sync on empty DB → all records are new."""
    db = tmp_path / "test.sqlite"
    report = sync_index(SAMPLE, db)
    assert report["total_records_seen"] == 2
    assert report["new_products"] == 2
    assert report["changed_products"] == 0
    assert report["unchanged_products"] == 0
    assert report["missing_products"] == 0
    assert report["missing_epa_reg_nos"] == []


def test_sync_report_all_unchanged(tmp_path):
    """Second sync with identical data → all records unchanged."""
    db = tmp_path / "test.sqlite"
    build_index(SAMPLE, db)
    report = sync_index(SAMPLE, db)
    assert report["total_records_seen"] == 2
    assert report["new_products"] == 0
    assert report["changed_products"] == 0
    assert report["unchanged_products"] == 2
    assert report["missing_products"] == 0


def test_sync_report_changed(tmp_path):
    """Sync with one modified record → changed_products = 1."""
    db = tmp_path / "test.sqlite"
    build_index(SAMPLE, db)

    modified = [
        {
            "epa_reg_no": "524-308",
            "product_name": "Roundup Original",
            "registrant": "Bayer CropScience LP",
            "active_ingredients": [{"name": "Glyphosate", "pct": 41.0}],
            "federal_status": "cancelled",  # changed
        },
        SAMPLE[1],
    ]
    report = sync_index(modified, db)
    assert report["changed_products"] == 1
    assert report["unchanged_products"] == 1
    assert report["new_products"] == 0


def test_sync_report_missing_products(tmp_path):
    """Products in DB but absent from source are counted as missing."""
    db = tmp_path / "test.sqlite"
    build_index(SAMPLE, db)

    # Sync with only the first product; the second is missing.
    report = sync_index([SAMPLE[0]], db)
    assert report["missing_products"] == 1
    assert report["missing_epa_reg_nos"] == ["100-1070"]


# ---------------------------------------------------------------------------
# Absent-product marking
# ---------------------------------------------------------------------------

def test_absent_since_set_on_missing(tmp_path):
    """Missing products should have absent_since set after sync."""
    db = tmp_path / "test.sqlite"
    build_index(SAMPLE, db)
    sync_index([SAMPLE[0]], db)  # "100-1070" is absent

    conn = get_connection(db)
    row = conn.execute(
        "SELECT absent_since FROM product_versions WHERE epa_reg_no = '100-1070' AND is_latest = 1"
    ).fetchone()
    conn.close()
    assert row is not None
    assert row["absent_since"] is not None


def test_absent_since_cleared_on_reappearance(tmp_path):
    """An absent product whose data reappears should have absent_since cleared."""
    db = tmp_path / "test.sqlite"
    build_index(SAMPLE, db)
    sync_index([SAMPLE[0]], db)  # "100-1070" goes absent

    # Now sync with both products again.
    sync_index(SAMPLE, db)

    conn = get_connection(db)
    row = conn.execute(
        "SELECT absent_since FROM product_versions WHERE epa_reg_no = '100-1070' AND is_latest = 1"
    ).fetchone()
    conn.close()
    assert row is not None
    assert row["absent_since"] is None


def test_absent_since_not_set_for_present_products(tmp_path):
    """Products present in the source should never have absent_since set."""
    db = tmp_path / "test.sqlite"
    build_index(SAMPLE, db)
    sync_index(SAMPLE, db)

    conn = get_connection(db)
    rows = conn.execute(
        "SELECT epa_reg_no, absent_since FROM product_versions WHERE is_latest = 1"
    ).fetchall()
    conn.close()
    for row in rows:
        assert row["absent_since"] is None, f"{row['epa_reg_no']} should not be absent"


def test_missing_products_not_deleted(tmp_path):
    """Missing products must remain in the DB (not deleted)."""
    db = tmp_path / "test.sqlite"
    build_index(SAMPLE, db)
    sync_index([SAMPLE[0]], db)

    conn = get_connection(db)
    row = conn.execute(
        "SELECT * FROM product_versions WHERE epa_reg_no = '100-1070'"
    ).fetchone()
    conn.close()
    assert row is not None


# ---------------------------------------------------------------------------
# demote_latest / promote_latest helpers
# ---------------------------------------------------------------------------

def test_demote_latest(tmp_path):
    """demote_latest should set is_latest=0 for all latest rows of a reg no."""
    db = tmp_path / "test.sqlite"
    build_index(SAMPLE, db)
    conn = get_connection(db)
    from chemical_index.build_index import _utcnow
    demote_latest(conn, "524-308", _utcnow())
    conn.commit()
    count = conn.execute(
        "SELECT COUNT(*) FROM product_versions WHERE epa_reg_no = '524-308' AND is_latest = 1"
    ).fetchone()[0]
    conn.close()
    assert count == 0


def test_promote_latest(tmp_path):
    """promote_latest should insert a new is_latest=1 row."""
    db = tmp_path / "test.sqlite"
    build_index([SAMPLE[0]], db)
    conn = get_connection(db)
    from chemical_index.build_index import _utcnow

    raw = {**SAMPLE[0], "federal_status": "cancelled"}
    normalised = normalize_record(raw)
    source_hash = hash_record(normalised)
    now = _utcnow()

    demote_latest(conn, "524-308", now)
    promote_latest(conn, normalised, raw, source_hash, now, now, "test-run-id")
    conn.commit()

    latest = conn.execute(
        "SELECT federal_status, is_latest FROM product_versions WHERE epa_reg_no = '524-308' AND is_latest = 1"
    ).fetchone()
    conn.close()
    assert latest is not None
    assert latest["federal_status"] == "cancelled"


# ---------------------------------------------------------------------------
# compare_source_hashes
# ---------------------------------------------------------------------------

def test_compare_source_hashes_equal():
    h = "a" * 64
    assert compare_source_hashes(h, h) is True


def test_compare_source_hashes_unequal():
    assert compare_source_hashes("a" * 64, "b" * 64) is False


def test_compare_source_hashes_none():
    assert compare_source_hashes(None, "a" * 64) is False
    assert compare_source_hashes("a" * 64, None) is False
    assert compare_source_hashes(None, None) is False
