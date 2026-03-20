"""Tests for source hashing."""

import pytest
from chemical_index.hashing import hash_record, hash_string


def test_hash_record_deterministic():
    record = {
        "epa_reg_no": "524-308",
        "product_name": "Roundup Original",
        "alternate_names": [],
        "registrant": "Bayer",
        "active_ingredients": [{"name": "Glyphosate", "pct": 41.0}],
        "label_stamped_date": "2022-03-15",
        "source_url": None,
        "pdf_url": None,
        "federal_status": "registered",
        "state_status_flags": {},
    }
    h1 = hash_record(record)
    h2 = hash_record(record)
    assert h1 == h2
    assert len(h1) == 64  # SHA-256 hex


def test_hash_record_changes_on_data_change():
    record = {
        "epa_reg_no": "524-308",
        "product_name": "Roundup Original",
        "alternate_names": [],
        "registrant": "Bayer",
        "active_ingredients": [],
        "label_stamped_date": None,
        "source_url": None,
        "pdf_url": None,
        "federal_status": "registered",
        "state_status_flags": {},
    }
    h1 = hash_record(record)
    record2 = dict(record)
    record2["federal_status"] = "cancelled"
    h2 = hash_record(record2)
    assert h1 != h2


def test_hash_string():
    h = hash_string("hello")
    assert len(h) == 64
    assert hash_string("hello") == h  # deterministic
    assert hash_string("world") != h
