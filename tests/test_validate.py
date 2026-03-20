"""Tests for database integrity / validation functions."""

from __future__ import annotations

import pytest

from chemical_index.build_index import build_index
from chemical_index.sync_index import sync_index
from chemical_index.schema import get_connection
from chemical_index.validate import (
    check_single_latest_per_reg_no,
    check_no_orphan_run_ids,
    check_duplicate_hashes_on_latest,
    validate_database,
)


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
# check_single_latest_per_reg_no
# ---------------------------------------------------------------------------

def test_check_single_latest_clean(tmp_path):
    """A freshly-built index should have no multiple-latest violations."""
    db = tmp_path / "test.sqlite"
    build_index(SAMPLE, db)
    conn = get_connection(db)
    violations = check_single_latest_per_reg_no(conn)
    conn.close()
    assert violations == []


def test_check_single_latest_detects_violation(tmp_path):
    """Manually inserting a duplicate latest row should be flagged."""
    db = tmp_path / "test.sqlite"
    build_index(SAMPLE, db)
    conn = get_connection(db)
    # Force a second is_latest=1 row for "524-308" bypassing sync logic.
    conn.execute(
        """
        INSERT INTO product_versions
            (epa_reg_no, product_name, alternate_names, registrant,
             active_ingredients, label_stamped_date, source_url, pdf_url,
             federal_status, state_status_flags, source_hash, raw_source_json,
             is_latest, first_seen_at, last_seen_at, retrieved_at, run_id)
        SELECT epa_reg_no, product_name, alternate_names, registrant,
               active_ingredients, label_stamped_date, source_url, pdf_url,
               federal_status, state_status_flags, source_hash || '_dup',
               raw_source_json, 1, first_seen_at, last_seen_at, retrieved_at,
               run_id
        FROM product_versions WHERE epa_reg_no = '524-308' AND is_latest = 1
        """
    )
    conn.commit()
    violations = check_single_latest_per_reg_no(conn)
    conn.close()
    assert len(violations) == 1
    assert violations[0]["epa_reg_no"] == "524-308"
    assert violations[0]["count"] == 2


# ---------------------------------------------------------------------------
# check_no_orphan_run_ids
# ---------------------------------------------------------------------------

def test_check_no_orphan_run_ids_clean(tmp_path):
    """Normal build produces no orphan run IDs."""
    db = tmp_path / "test.sqlite"
    build_index(SAMPLE, db)
    conn = get_connection(db)
    violations = check_no_orphan_run_ids(conn)
    conn.close()
    assert violations == []


def test_check_no_orphan_run_ids_detects_violation(tmp_path):
    """Manually inserting a row with a bogus run_id should be flagged."""
    db = tmp_path / "test.sqlite"
    build_index(SAMPLE, db)
    conn = get_connection(db)
    conn.execute(
        """
        INSERT INTO product_versions
            (epa_reg_no, product_name, alternate_names, registrant,
             active_ingredients, label_stamped_date, source_url, pdf_url,
             federal_status, state_status_flags, source_hash, raw_source_json,
             is_latest, first_seen_at, last_seen_at, retrieved_at, run_id)
        VALUES ('999-999', 'Ghost Product', '[]', NULL, '[]', NULL, NULL, NULL,
                NULL, '{}', 'deadbeef', '{}', 0,
                '2024-01-01T00:00:00+00:00', '2024-01-01T00:00:00+00:00',
                '2024-01-01T00:00:00+00:00', 'no-such-run-id')
        """
    )
    conn.commit()
    violations = check_no_orphan_run_ids(conn)
    conn.close()
    assert len(violations) == 1
    assert violations[0]["run_id"] == "no-such-run-id"


# ---------------------------------------------------------------------------
# check_duplicate_hashes_on_latest
# ---------------------------------------------------------------------------

def test_check_duplicate_hashes_clean(tmp_path):
    """Distinct products with different data should have unique latest hashes."""
    db = tmp_path / "test.sqlite"
    build_index(SAMPLE, db)
    conn = get_connection(db)
    violations = check_duplicate_hashes_on_latest(conn)
    conn.close()
    assert violations == []


def test_check_duplicate_hashes_detects_violation(tmp_path):
    """Two latest rows sharing the same source_hash should be flagged."""
    db = tmp_path / "test.sqlite"
    build_index(SAMPLE, db)
    conn = get_connection(db)
    # Copy 524-308's hash onto a new is_latest=1 row for a different reg no.
    existing = conn.execute(
        "SELECT source_hash, run_id FROM product_versions WHERE epa_reg_no = '524-308'"
    ).fetchone()
    conn.execute(
        """
        INSERT INTO product_versions
            (epa_reg_no, product_name, alternate_names, registrant,
             active_ingredients, label_stamped_date, source_url, pdf_url,
             federal_status, state_status_flags, source_hash, raw_source_json,
             is_latest, first_seen_at, last_seen_at, retrieved_at, run_id)
        VALUES ('999-000', 'Clone Product', '[]', NULL, '[]', NULL, NULL, NULL,
                NULL, '{}', ?, '{}', 1,
                '2024-01-01T00:00:00+00:00', '2024-01-01T00:00:00+00:00',
                '2024-01-01T00:00:00+00:00', ?)
        """,
        (existing["source_hash"], existing["run_id"]),
    )
    conn.commit()
    violations = check_duplicate_hashes_on_latest(conn)
    conn.close()
    assert len(violations) == 1
    assert violations[0]["count"] == 2


# ---------------------------------------------------------------------------
# validate_database
# ---------------------------------------------------------------------------

def test_validate_database_valid(tmp_path):
    """A clean database should pass validation."""
    db = tmp_path / "test.sqlite"
    build_index(SAMPLE, db)
    report = validate_database(db)
    assert report["valid"] is True
    assert report["issues"] == []


def test_validate_database_reports_issues(tmp_path):
    """validate_database should aggregate issues from all checks."""
    db = tmp_path / "test.sqlite"
    build_index(SAMPLE, db)
    conn = get_connection(db)
    # Introduce a multiple-latest violation.
    conn.execute(
        """
        INSERT INTO product_versions
            (epa_reg_no, product_name, alternate_names, registrant,
             active_ingredients, label_stamped_date, source_url, pdf_url,
             federal_status, state_status_flags, source_hash, raw_source_json,
             is_latest, first_seen_at, last_seen_at, retrieved_at, run_id)
        SELECT epa_reg_no, product_name, alternate_names, registrant,
               active_ingredients, label_stamped_date, source_url, pdf_url,
               federal_status, state_status_flags, source_hash || '_v2',
               raw_source_json, 1, first_seen_at, last_seen_at, retrieved_at,
               run_id
        FROM product_versions WHERE epa_reg_no = '524-308' AND is_latest = 1
        """
    )
    conn.commit()
    conn.close()

    report = validate_database(db)
    assert report["valid"] is False
    types = [i["type"] for i in report["issues"]]
    assert "multiple_latest" in types
