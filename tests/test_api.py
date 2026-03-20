"""Tests for the FastAPI layer (chemical_index/api.py)."""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from chemical_index.api import app, _api_meta
from chemical_index.build_index import build_index
from chemical_index import __version__


# ---------------------------------------------------------------------------
# Shared sample data
# ---------------------------------------------------------------------------

SAMPLE_PRODUCTS = [
    {
        "epa_reg_no": "524-308",
        "product_name": "Roundup Original",
        "alternate_names": ["Roundup", "Roundup Concentrate"],
        "registrant": "Bayer CropScience LP",
        "active_ingredients": [{"name": "Glyphosate", "pct": 41.0}],
        "label_stamped_date": "2022-03-15",
        "source_url": "https://example.com/product/524-308",
        "pdf_url": "https://example.com/labels/524-308.pdf",
        "federal_status": "registered",
    },
    {
        "epa_reg_no": "100-1070",
        "product_name": "Enlist One Herbicide",
        "alternate_names": ["Enlist One"],
        "registrant": "Corteva Agriscience",
        "active_ingredients": [{"name": "2,4-D choline salt", "pct": 59.6}],
        "label_stamped_date": "2021-07-01",
        "source_url": "https://example.com/product/100-1070",
        "federal_status": "registered",
    },
]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def db(tmp_path):
    """Build a small test database and return its path."""
    source = tmp_path / "products.json"
    source.write_text(json.dumps(SAMPLE_PRODUCTS))
    db_path = tmp_path / "index.sqlite"
    build_index(str(source), str(db_path))
    return db_path


@pytest.fixture()
def client(db, monkeypatch):
    """Return a TestClient with CHEMICAL_INDEX_DB pointing at the test db."""
    monkeypatch.setenv("CHEMICAL_INDEX_DB", str(db))
    return TestClient(app)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def test_api_meta_contains_version():
    meta = _api_meta()
    assert meta["api_version"] == __version__


# ---------------------------------------------------------------------------
# GET /search
# ---------------------------------------------------------------------------


def test_search_returns_results(client):
    resp = client.get("/search?q=roundup")
    assert resp.status_code == 200
    data = resp.json()
    assert data["api_version"] == __version__
    assert data["query"] == "roundup"
    assert data["mode"] == "fuzzy"
    assert data["count"] >= 1
    assert len(data["results"]) == data["count"]


def test_search_result_has_source_url(client):
    resp = client.get("/search?q=524-308&mode=epa_reg_no")
    assert resp.status_code == 200
    result = resp.json()["results"][0]
    assert result["source_url"] == "https://example.com/product/524-308"


def test_search_result_has_label_date(client):
    resp = client.get("/search?q=524-308&mode=epa_reg_no")
    assert resp.status_code == 200
    result = resp.json()["results"][0]
    assert result["label_date"] == "2022-03-15"


def test_search_result_has_disclaimer(client):
    resp = client.get("/search?q=roundup")
    assert resp.status_code == 200
    for r in resp.json()["results"]:
        assert "disclaimer" in r


def test_search_mode_epa_reg_no(client):
    resp = client.get("/search?q=524-308&mode=epa_reg_no")
    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] == 1
    assert data["results"][0]["epa_reg_no"] == "524-308"


def test_search_mode_active_ingredient(client):
    resp = client.get("/search?q=Glyphosate&mode=active_ingredient")
    assert resp.status_code == 200
    results = resp.json()["results"]
    assert any(r["epa_reg_no"] == "524-308" for r in results)


def test_search_top_parameter(client):
    resp = client.get("/search?q=herbicide&top=1")
    assert resp.status_code == 200
    assert len(resp.json()["results"]) <= 1


def test_search_invalid_mode_returns_422(client):
    resp = client.get("/search?q=roundup&mode=invalid")
    assert resp.status_code == 422


def test_search_missing_q_returns_422(client):
    resp = client.get("/search")
    assert resp.status_code == 422


def test_search_no_db_returns_503(tmp_path, monkeypatch):
    monkeypatch.setenv("CHEMICAL_INDEX_DB", str(tmp_path / "missing.sqlite"))
    c = TestClient(app)
    resp = c.get("/search?q=roundup")
    assert resp.status_code == 503


def test_search_no_results(client):
    resp = client.get("/search?q=999-nonexistent&mode=epa_reg_no")
    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] == 0
    assert data["results"] == []


# ---------------------------------------------------------------------------
# GET /product/{epa_reg_no}
# ---------------------------------------------------------------------------


def test_product_found(client):
    resp = client.get("/product/524-308")
    assert resp.status_code == 200
    data = resp.json()
    assert data["api_version"] == __version__
    assert data["epa_reg_no"] == "524-308"
    assert data["product_name"] == "Roundup Original"


def test_product_has_source_url(client):
    resp = client.get("/product/524-308")
    assert resp.status_code == 200
    assert resp.json()["source_url"] == "https://example.com/product/524-308"


def test_product_has_label_date(client):
    resp = client.get("/product/524-308")
    assert resp.status_code == 200
    assert resp.json()["label_date"] == "2022-03-15"


def test_product_has_disclaimer(client):
    resp = client.get("/product/524-308")
    assert resp.status_code == 200
    assert "disclaimer" in resp.json()


def test_product_has_active_ingredients(client):
    resp = client.get("/product/524-308")
    assert resp.status_code == 200
    ais = resp.json()["active_ingredients"]
    assert isinstance(ais, list)
    assert any(ai["name"] == "Glyphosate" for ai in ais)


def test_product_not_found_returns_404(client):
    resp = client.get("/product/999-9999")
    assert resp.status_code == 404


def test_product_no_db_returns_503(tmp_path, monkeypatch):
    monkeypatch.setenv("CHEMICAL_INDEX_DB", str(tmp_path / "missing.sqlite"))
    c = TestClient(app)
    resp = c.get("/product/524-308")
    assert resp.status_code == 503


# ---------------------------------------------------------------------------
# GET /label/{epa_reg_no}  (mocked PDF extraction)
# ---------------------------------------------------------------------------


def _make_label_result(epa_reg_no: str) -> dict:
    return {
        "epa_reg_no": epa_reg_no,
        "product_name": "Roundup Original",
        "label_date": "2022-03-15",
        "sections": {
            "directions_for_use": "Apply to foliage.",
            "restrictions": "Do not use near water.",
            "ppe": "Wear gloves.",
            "rei": "4 hours",
            "phi": None,
            "environmental_hazards": None,
            "spray_drift": None,
            "agricultural_use": None,
        },
        "disclaimer": "This is label information for reference only. "
                      "Always follow the full product label and local regulations.",
    }


def test_label_returns_full_label(client):
    with patch("chemical_index.api.extract_label", return_value=_make_label_result("524-308")):
        resp = client.get("/label/524-308")
    assert resp.status_code == 200
    data = resp.json()
    assert data["api_version"] == __version__
    assert data["epa_reg_no"] == "524-308"
    assert data["product_name"] == "Roundup Original"
    assert data["label_date"] == "2022-03-15"
    assert "sections" in data
    assert "disclaimer" in data


def test_label_has_source_url(client):
    with patch("chemical_index.api.extract_label", return_value=_make_label_result("524-308")):
        resp = client.get("/label/524-308")
    assert resp.status_code == 200
    assert resp.json()["source_url"] == "https://example.com/product/524-308"


def test_label_not_found_returns_404(client):
    with patch(
        "chemical_index.api.extract_label",
        return_value={
            "epa_reg_no": "999-9999",
            "product_name": None,
            "label_date": None,
            "sections": {},
            "error": "Product not found in database.",
        },
    ):
        resp = client.get("/label/999-9999")
    assert resp.status_code == 404


def test_label_no_pdf_url_returns_503(client):
    with patch(
        "chemical_index.api.extract_label",
        return_value={
            "epa_reg_no": "100-1070",
            "product_name": "Enlist One Herbicide",
            "label_date": None,
            "sections": {},
            "error": "No pdf_url stored for this product.",
        },
    ):
        resp = client.get("/label/100-1070")
    assert resp.status_code == 503


def test_label_no_db_returns_503(tmp_path, monkeypatch):
    monkeypatch.setenv("CHEMICAL_INDEX_DB", str(tmp_path / "missing.sqlite"))
    c = TestClient(app)
    resp = c.get("/label/524-308")
    assert resp.status_code == 503


# ---------------------------------------------------------------------------
# GET /label/{epa_reg_no}/sections
# ---------------------------------------------------------------------------


def test_label_sections_returns_sections(client):
    with patch("chemical_index.api.extract_label", return_value=_make_label_result("524-308")):
        resp = client.get("/label/524-308/sections")
    assert resp.status_code == 200
    data = resp.json()
    assert data["api_version"] == __version__
    assert data["epa_reg_no"] == "524-308"
    assert data["label_date"] == "2022-03-15"
    assert "sections" in data
    assert data["sections"]["directions_for_use"] == "Apply to foliage."
    assert "disclaimer" in data


def test_label_sections_has_source_url(client):
    with patch("chemical_index.api.extract_label", return_value=_make_label_result("524-308")):
        resp = client.get("/label/524-308/sections")
    assert resp.status_code == 200
    assert resp.json()["source_url"] == "https://example.com/product/524-308"


def test_label_sections_not_found_returns_404(client):
    with patch(
        "chemical_index.api.extract_label",
        return_value={
            "epa_reg_no": "999-9999",
            "product_name": None,
            "label_date": None,
            "sections": {},
            "error": "Product not found in database.",
        },
    ):
        resp = client.get("/label/999-9999/sections")
    assert resp.status_code == 404


def test_label_sections_no_db_returns_503(tmp_path, monkeypatch):
    monkeypatch.setenv("CHEMICAL_INDEX_DB", str(tmp_path / "missing.sqlite"))
    c = TestClient(app)
    resp = c.get("/label/524-308/sections")
    assert resp.status_code == 503


# ---------------------------------------------------------------------------
# Routing: /label/{epa_reg_no}/sections must not be swallowed by /label/{epa_reg_no}
# ---------------------------------------------------------------------------


def test_sections_route_is_distinct_from_label_route(client):
    """Ensure /label/{id}/sections is not matched by the /label/{id} pattern."""
    with patch("chemical_index.api.extract_label", return_value=_make_label_result("524-308")):
        label_resp = client.get("/label/524-308")
        sections_resp = client.get("/label/524-308/sections")
    assert label_resp.status_code == 200
    assert sections_resp.status_code == 200
    # /label/{id} returns product_name; /label/{id}/sections does not require it
    assert "product_name" in label_resp.json()
