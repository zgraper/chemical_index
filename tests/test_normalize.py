"""Tests for metadata normalization."""

import pytest
from chemical_index.normalize import (
    normalize_epa_reg_no,
    normalize_string,
    normalize_list,
    normalize_dict,
    normalize_active_ingredients,
    normalize_record,
)


def test_normalize_epa_reg_no():
    assert normalize_epa_reg_no("  524-308 ") == "524-308"
    assert normalize_epa_reg_no(None) == ""
    assert normalize_epa_reg_no(524) == "524"


def test_normalize_string():
    assert normalize_string("  hello ") == "hello"
    assert normalize_string(None) is None
    assert normalize_string("") is None


def test_normalize_list():
    assert normalize_list(None) == []
    assert normalize_list([1, 2]) == [1, 2]
    assert normalize_list('["a","b"]') == ["a", "b"]
    assert normalize_list("single") == ["single"]


def test_normalize_dict():
    assert normalize_dict(None) == {}
    assert normalize_dict({"CA": "registered"}) == {"CA": "registered"}
    assert normalize_dict('{"CA": "registered"}') == {"CA": "registered"}
    assert normalize_dict("not-json") == {}


def test_normalize_active_ingredients_list_of_dicts():
    ai = [{"name": "Glyphosate", "pct": 41.0}]
    result = normalize_active_ingredients(ai)
    assert result == [{"name": "Glyphosate", "pct": 41.0}]


def test_normalize_active_ingredients_list_of_strings():
    result = normalize_active_ingredients(["Glyphosate", "Atrazine"])
    assert len(result) == 2
    assert result[0]["name"] == "Glyphosate"
    assert result[0]["pct"] is None


def test_normalize_active_ingredients_none():
    assert normalize_active_ingredients(None) == []


def test_normalize_record_minimal():
    raw = {"epa_reg_no": "524-308", "product_name": "Roundup Original"}
    rec = normalize_record(raw)
    assert rec["epa_reg_no"] == "524-308"
    assert rec["product_name"] == "Roundup Original"
    assert rec["alternate_names"] == []
    assert rec["active_ingredients"] == []
    assert rec["state_status_flags"] == {}


def test_normalize_record_full():
    raw = {
        "epa_reg_no": " 524-308 ",
        "product_name": " Roundup Original ",
        "alternate_names": ["Roundup"],
        "registrant": "Bayer",
        "active_ingredients": [{"name": "Glyphosate", "pct": 41.0}],
        "label_stamped_date": "2022-03-15",
        "source_url": "https://example.com",
        "pdf_url": "https://example.com/label.pdf",
        "federal_status": "registered",
        "state_status_flags": {"CA": "registered"},
    }
    rec = normalize_record(raw)
    assert rec["epa_reg_no"] == "524-308"
    assert rec["product_name"] == "Roundup Original"
    assert rec["registrant"] == "Bayer"
    assert rec["active_ingredients"] == [{"name": "Glyphosate", "pct": 41.0}]
    assert rec["state_status_flags"] == {"CA": "registered"}
