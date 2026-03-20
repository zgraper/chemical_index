"""Tests for search module."""

import json
import pytest

from chemical_index.build_index import build_index
from chemical_index.search import search


SAMPLE = [
    {
        "epa_reg_no": "524-308",
        "product_name": "Roundup Original",
        "alternate_names": ["Roundup", "Roundup Concentrate"],
        "registrant": "Bayer CropScience LP",
        "active_ingredients": [{"name": "Glyphosate", "pct": 41.0}],
        "federal_status": "registered",
    },
    {
        "epa_reg_no": "100-1070",
        "product_name": "Enlist One Herbicide",
        "alternate_names": ["Enlist One"],
        "registrant": "Corteva Agriscience",
        "active_ingredients": [{"name": "2,4-D choline salt", "pct": 59.6}],
        "federal_status": "registered",
    },
    {
        "epa_reg_no": "352-664",
        "product_name": "Lorsban Advanced Insecticide",
        "alternate_names": ["Lorsban Advanced"],
        "registrant": "Corteva Agriscience",
        "active_ingredients": [{"name": "Chlorpyrifos", "pct": 44.0}],
        "federal_status": "cancelled",
    },
]


@pytest.fixture
def db(tmp_path):
    db_path = tmp_path / "test.sqlite"
    build_index(SAMPLE, db_path)
    return db_path


def test_search_by_epa_reg_no(db):
    results = search("524-308", db, mode="epa_reg_no")
    assert len(results) == 1
    assert results[0]["epa_reg_no"] == "524-308"
    assert results[0]["score"] == 1.0
    assert "Exact EPA reg no" in results[0]["explain"]


def test_search_by_epa_reg_no_no_match(db):
    results = search("999-999", db, mode="epa_reg_no")
    assert results == []


def test_search_by_product_name_exact(db):
    results = search("Roundup Original", db, mode="product_name")
    assert len(results) == 1
    assert results[0]["epa_reg_no"] == "524-308"


def test_search_by_product_name_case_insensitive(db):
    results = search("roundup original", db, mode="product_name")
    assert len(results) == 1


def test_search_by_fuzzy(db):
    results = search("roundup", db, mode="fuzzy")
    assert len(results) >= 1
    assert results[0]["epa_reg_no"] == "524-308"
    assert "score" in results[0]
    assert "explain" in results[0]


def test_search_by_fuzzy_alternate_name(db):
    results = search("Enlist One", db, mode="fuzzy")
    assert any(r["epa_reg_no"] == "100-1070" for r in results)


def test_search_by_active_ingredient(db):
    results = search("Glyphosate", db, mode="active_ingredient")
    assert len(results) >= 1
    assert results[0]["epa_reg_no"] == "524-308"
    assert "Glyphosate" in results[0]["explain"]


def test_search_by_active_ingredient_partial(db):
    results = search("chlorpyrifos", db, mode="active_ingredient")
    assert any(r["epa_reg_no"] == "352-664" for r in results)


def test_search_by_registrant(db):
    results = search("Corteva", db, mode="registrant")
    epa_nos = {r["epa_reg_no"] for r in results}
    assert "100-1070" in epa_nos
    assert "352-664" in epa_nos


def test_search_invalid_mode(db):
    with pytest.raises(ValueError):
        search("test", db, mode="invalid_mode")


def test_search_results_have_explain(db):
    results = search("Lorsban", db, mode="fuzzy")
    assert len(results) >= 1
    for r in results:
        assert "explain" in r
        assert isinstance(r["explain"], str)
        assert len(r["explain"]) > 0


def test_search_top_limit(db):
    results = search("a", db, mode="fuzzy", top=1)
    assert len(results) <= 1
