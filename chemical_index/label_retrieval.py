"""Label retrieval: fetch product metadata, download PDF, and extract sections."""

from __future__ import annotations

import json
import urllib.request
from pathlib import Path
from typing import Any

from .schema import get_connection
from .pdf_parser import extract_text, normalize_text
from .section_extractor import extract_sections


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------


def get_latest_product(epa_reg_no: str, db_path: str | Path) -> dict[str, Any] | None:
    """Return the latest product version row for *epa_reg_no*, or ``None``.

    Queries the ``product_versions`` table for rows with ``is_latest = 1``
    and returns the one with the most recent ``retrieved_at`` timestamp.
    """
    conn = get_connection(db_path)
    try:
        row = conn.execute(
            """
            SELECT id, epa_reg_no, product_name, label_stamped_date,
                   pdf_url, registrant, active_ingredients,
                   source_url, federal_status, retrieved_at
            FROM product_versions
            WHERE epa_reg_no = ? AND is_latest = 1
            ORDER BY retrieved_at DESC
            LIMIT 1
            """,
            (epa_reg_no,),
        ).fetchone()
    finally:
        conn.close()

    if row is None:
        return None
    return dict(row)


# ---------------------------------------------------------------------------
# PDF download / cache
# ---------------------------------------------------------------------------

_DEFAULT_CACHE_DIR = Path("data") / "labels"


def _pdf_cache_path(
    epa_reg_no: str,
    version_id: int,
    cache_dir: str | Path = _DEFAULT_CACHE_DIR,
) -> Path:
    """Return the local cache path for a label PDF."""
    safe_reg = epa_reg_no.replace("/", "_")
    return Path(cache_dir) / safe_reg / f"{version_id}.pdf"


def download_label(
    pdf_url: str,
    epa_reg_no: str,
    version_id: int,
    cache_dir: str | Path = _DEFAULT_CACHE_DIR,
) -> Path:
    """Download *pdf_url* to the local cache and return the path.

    If the file already exists it is returned immediately without downloading.
    The cache directory is created automatically when needed.

    Uses ``urllib.request`` from the standard library; no extra packages
    required for download.
    """
    dest = _pdf_cache_path(epa_reg_no, version_id, cache_dir)
    if dest.exists():
        return dest

    dest.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(
        pdf_url,
        headers={"User-Agent": "CornbeltAI-LabelRetrieval/1.0"},
    )
    with urllib.request.urlopen(req, timeout=30) as response, open(dest, "wb") as fh:  # noqa: S310
        fh.write(response.read())
    return dest


# ---------------------------------------------------------------------------
# Structured label extraction
# ---------------------------------------------------------------------------


def extract_label(
    epa_reg_no: str,
    db_path: str | Path,
    *,
    cache_dir: str | Path = _DEFAULT_CACHE_DIR,
    pdf_path: str | Path | None = None,
) -> dict[str, Any]:
    """Retrieve a label for *epa_reg_no* and return structured section data.

    Workflow:
    1. Look up the latest product version in the database.
    2. If *pdf_path* is not provided, download the PDF from ``pdf_url`` (or
       return it from cache if already present).
    3. Extract raw text from the PDF, normalise it, and apply rule-based
       section extraction.

    Parameters
    ----------
    epa_reg_no:
        The EPA registration number to look up.
    db_path:
        Path to the SQLite database file.
    cache_dir:
        Root directory for cached PDFs (``data/labels`` by default).
    pdf_path:
        Optional explicit path to a PDF file, bypassing the database look-up
        and download step.  Useful for testing.

    Returns
    -------
    dict
        Structured output with keys ``epa_reg_no``, ``product_name``,
        ``label_date``, and ``sections``.
    """
    product: dict[str, Any] | None = None
    resolved_pdf_path: Path | None = None

    if pdf_path is not None:
        # Caller supplied a PDF directly – still try to get metadata
        resolved_pdf_path = Path(pdf_path)
        if db_path:
            try:
                product = get_latest_product(epa_reg_no, db_path)
            except Exception:
                product = None
    else:
        try:
            product = get_latest_product(epa_reg_no, db_path)
        except Exception:
            return _empty_result(epa_reg_no, error="Unable to open database.")
        if product is None:
            return _empty_result(epa_reg_no, error="Product not found in database.")

        stored_pdf_url = product.get("pdf_url")
        if not stored_pdf_url:
            return _empty_result(
                epa_reg_no,
                product_name=product.get("product_name"),
                label_date=product.get("label_stamped_date"),
                error="No pdf_url stored for this product.",
            )

        version_id: int = product["id"]
        resolved_pdf_path = download_label(
            stored_pdf_url, epa_reg_no, version_id, cache_dir
        )

    raw_text = extract_text(resolved_pdf_path)
    clean_text = normalize_text(raw_text)
    sections = extract_sections(clean_text)

    return {
        "epa_reg_no": epa_reg_no,
        "product_name": product.get("product_name") if product else None,
        "label_date": product.get("label_stamped_date") if product else None,
        "sections": sections,
    }


def _empty_result(
    epa_reg_no: str,
    *,
    product_name: str | None = None,
    label_date: str | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    """Return an empty structured result, optionally with an error message."""
    result: dict[str, Any] = {
        "epa_reg_no": epa_reg_no,
        "product_name": product_name,
        "label_date": label_date,
        "sections": {
            "directions_for_use": None,
            "restrictions": None,
            "ppe": None,
            "rei": None,
            "phi": None,
            "environmental_hazards": None,
            "spray_drift": None,
            "agricultural_use": None,
        },
    }
    if error:
        result["error"] = error
    return result
