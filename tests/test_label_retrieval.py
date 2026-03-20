"""Tests for label_retrieval module."""

from __future__ import annotations

import io
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from chemical_index.build_index import build_index
from chemical_index.label_retrieval import (
    extract_label,
    get_latest_product,
    download_label,
    _pdf_cache_path,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SAMPLE_PRODUCTS = [
    {
        "epa_reg_no": "524-659",
        "product_name": "Roundup PowerMAX 3",
        "registrant": "Bayer CropScience LP",
        "active_ingredients": [{"name": "Glyphosate", "pct": 48.7}],
        "label_stamped_date": "2023-05-01",
        "pdf_url": "https://example.com/labels/524-659.pdf",
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


@pytest.fixture()
def db(tmp_path):
    """Build a small test database and return its path."""
    source = tmp_path / "products.json"
    source.write_text(json.dumps(SAMPLE_PRODUCTS))
    db_path = tmp_path / "index.sqlite"
    build_index(str(source), str(db_path))
    return db_path


# ---------------------------------------------------------------------------
# get_latest_product
# ---------------------------------------------------------------------------


def test_get_latest_product_found(db):
    product = get_latest_product("524-659", db)
    assert product is not None
    assert product["epa_reg_no"] == "524-659"
    assert product["product_name"] == "Roundup PowerMAX 3"
    assert product["pdf_url"] == "https://example.com/labels/524-659.pdf"


def test_get_latest_product_not_found(db):
    product = get_latest_product("999-9999", db)
    assert product is None


# ---------------------------------------------------------------------------
# _pdf_cache_path
# ---------------------------------------------------------------------------


def test_pdf_cache_path(tmp_path):
    path = _pdf_cache_path("524-659", 42, tmp_path)
    assert path == tmp_path / "524-659" / "42.pdf"


def test_pdf_cache_path_sanitises_slash(tmp_path):
    path = _pdf_cache_path("524/659", 1, tmp_path)
    assert "/" not in path.name
    assert "524_659" in str(path)


# ---------------------------------------------------------------------------
# download_label
# ---------------------------------------------------------------------------


def test_download_label_caches_file(tmp_path):
    """download_label should save the PDF to the cache path."""
    fake_pdf_content = b"%PDF-1.4 fake pdf content"
    cache_dir = tmp_path / "cache"

    mock_response = MagicMock()
    mock_response.read.return_value = fake_pdf_content
    mock_response.__enter__ = lambda s: s
    mock_response.__exit__ = MagicMock(return_value=False)

    with patch("urllib.request.urlopen", return_value=mock_response):
        path = download_label(
            "https://example.com/label.pdf", "524-659", 1, cache_dir
        )

    assert path.exists()
    assert path.read_bytes() == fake_pdf_content


def test_download_label_skips_if_cached(tmp_path):
    """download_label should not make a network request when file exists."""
    cache_dir = tmp_path / "cache"
    dest = _pdf_cache_path("524-659", 1, cache_dir)
    dest.parent.mkdir(parents=True)
    dest.write_bytes(b"cached")

    with patch("urllib.request.urlopen") as mock_open:
        path = download_label("https://example.com/label.pdf", "524-659", 1, cache_dir)
        mock_open.assert_not_called()

    assert path == dest


# ---------------------------------------------------------------------------
# extract_label with a real (minimal) PDF via pdf_path override
# ---------------------------------------------------------------------------


def _make_minimal_pdf_text() -> str:
    """Return multi-section text that extract_label can parse."""
    return (
        "PRODUCT LABEL\n\n"
        "DIRECTIONS FOR USE\n"
        "Apply to foliage of actively growing weeds.\n\n"
        "RESTRICTIONS\n"
        "Do not use in greenhouses.\n\n"
        "PERSONAL PROTECTIVE EQUIPMENT\n"
        "Wear chemical-resistant gloves.\n\n"
        "ENVIRONMENTAL HAZARDS\n"
        "This product is toxic to aquatic organisms.\n"
    )


def test_extract_label_no_db_no_pdf_path():
    """Without a pdf_path or a real DB, extract_label should return an error result."""
    # Using a non-existent DB path but no pdf_path → error path
    result = extract_label("524-659", "/nonexistent/path.sqlite")
    assert result["epa_reg_no"] == "524-659"
    assert "error" in result


def test_extract_label_no_pdf_url(db):
    """Product without pdf_url should return an error result."""
    result = extract_label("100-1070", db)  # no pdf_url in sample data
    assert result["epa_reg_no"] == "100-1070"
    assert "error" in result


def test_extract_label_unknown_epa_reg_no(db):
    result = extract_label("999-9999", db)
    assert result["epa_reg_no"] == "999-9999"
    assert "error" in result
    assert result["sections"]["directions_for_use"] is None


def test_extract_label_with_pdf_path(db, tmp_path):
    """When pdf_path is supplied, extract_label parses it directly."""
    pytest.importorskip("fpdf", reason="fpdf not installed – skipping PDF generation test")
    from fpdf import FPDF  # type: ignore

    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", size=12)
    for line in _make_minimal_pdf_text().splitlines():
        pdf.cell(0, 10, line, ln=True)

    pdf_path = tmp_path / "test_label.pdf"
    pdf.output(str(pdf_path))

    result = extract_label("524-659", db, pdf_path=pdf_path)
    assert result["epa_reg_no"] == "524-659"
    assert result["product_name"] == "Roundup PowerMAX 3"
    sections = result["sections"]
    assert isinstance(sections, dict)


# ---------------------------------------------------------------------------
# CLI: extract-label command
# ---------------------------------------------------------------------------


def test_cli_extract_label_missing_db(tmp_path):
    from click.testing import CliRunner
    from chemical_index.cli import cli

    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["extract-label", "524-659", "--db", str(tmp_path / "missing.sqlite")],
    )
    assert result.exit_code == 1


def test_cli_extract_label_product_not_found(db):
    from click.testing import CliRunner
    from chemical_index.cli import cli

    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["extract-label", "999-9999", "--db", str(db)],
    )
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert "error" in data


def test_cli_extract_label_no_pdf_url(db):
    from click.testing import CliRunner
    from chemical_index.cli import cli

    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["extract-label", "100-1070", "--db", str(db)],
    )
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert "error" in data
