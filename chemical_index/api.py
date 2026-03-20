"""FastAPI layer for the chemical index.

Exposes four endpoints:
    GET /search?q=             – ranked product search
    GET /product/{epa_reg_no}  – single product detail
    GET /label/{epa_reg_no}    – full label (metadata + extracted sections)
    GET /label/{epa_reg_no}/sections – extracted sections only

Configuration (environment variables):
    CHEMICAL_INDEX_DB        – path to the SQLite database (required at runtime)
    CHEMICAL_INDEX_CACHE_DIR – PDF label cache directory (default: data/labels)
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query

from . import __version__
from .label_retrieval import extract_label, get_latest_product
from .safety import DISCLAIMER, enforce_safe_output
from .search import MODES, search as _search

_APP_DESCRIPTION = (
    "Cornbelt AI – Chemical label metadata index and retrieval service. "
    "Provides structured access to EPA-registered pesticide product data."
)

app = FastAPI(
    title="Chemical Index API",
    description=_APP_DESCRIPTION,
    version=__version__,
)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _db_path() -> Path:
    """Return the configured database path, raising HTTP 503 if missing."""
    db = os.environ.get("CHEMICAL_INDEX_DB", "data/index.sqlite")
    p = Path(db)
    if not p.exists():
        raise HTTPException(
            status_code=503,
            detail=(
                "Index database not found. "
                "Set CHEMICAL_INDEX_DB to the path of the SQLite database."
            ),
        )
    return p


def _cache_dir() -> Path:
    return Path(os.environ.get("CHEMICAL_INDEX_CACHE_DIR", "data/labels"))


def _api_meta() -> dict[str, str]:
    return {"api_version": __version__}


def _clean_product(row: dict[str, Any]) -> dict[str, Any]:
    """Return a subset of product fields with a consistent label_date alias."""
    return {
        "epa_reg_no": row.get("epa_reg_no"),
        "product_name": row.get("product_name"),
        "alternate_names": row.get("alternate_names"),
        "registrant": row.get("registrant"),
        "active_ingredients": row.get("active_ingredients"),
        "label_date": row.get("label_stamped_date"),
        "source_url": row.get("source_url"),
        "federal_status": row.get("federal_status"),
        "state_status_flags": row.get("state_status_flags"),
    }


def _get_product_source_url(epa_reg_no: str, db: Path) -> str | None:
    """Return the source_url for a product, or None on any failure."""
    try:
        meta = get_latest_product(epa_reg_no, db)
        return meta.get("source_url") if meta else None
    except Exception:
        return None


def _fetch_label(epa_reg_no: str, db: Path) -> dict[str, Any]:
    """Fetch label data, raising HTTP errors on failure."""
    try:
        result = extract_label(epa_reg_no, db, cache_dir=_cache_dir())
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    if result.get("error"):
        error = result["error"]
        if "not found" in error.lower():
            raise HTTPException(status_code=404, detail=error)
        raise HTTPException(status_code=503, detail=error)
    return result


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@app.get("/search")
def search(
    q: str = Query(..., description="Search query string"),
    mode: str = Query("fuzzy", description=f"Search mode: {', '.join(MODES)}"),
    top: int = Query(10, ge=1, le=100, description="Maximum results to return"),
) -> dict[str, Any]:
    """Search the chemical index for products matching the query."""
    if mode not in MODES:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid mode {mode!r}. Choose from: {list(MODES)}",
        )
    db = _db_path()
    try:
        raw_results = _search(q, db, mode=mode, top=top)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    # Normalise label_stamped_date → label_date in each result
    cleaned: list[dict[str, Any]] = []
    for r in raw_results:
        item = dict(r)
        item.setdefault("label_date", item.get("label_stamped_date"))
        cleaned.append(item)

    safe_results = enforce_safe_output(cleaned)
    # Always include the disclaimer since all results are chemical product data
    for item in safe_results:
        if isinstance(item, dict):
            item.setdefault("disclaimer", DISCLAIMER)
    return {
        **_api_meta(),
        "query": q,
        "mode": mode,
        "count": len(safe_results),
        "results": safe_results,
    }


@app.get("/product/{epa_reg_no}")
def product(epa_reg_no: str) -> dict[str, Any]:
    """Return the latest metadata for a single EPA-registered product."""
    db = _db_path()
    try:
        results = _search(epa_reg_no, db, mode="epa_reg_no", top=1)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    if not results:
        raise HTTPException(
            status_code=404,
            detail=f"Product not found: {epa_reg_no!r}",
        )

    product_data: dict[str, Any] = {
        **_api_meta(),
        **_clean_product(results[0]),
    }
    result = enforce_safe_output(product_data)
    # Always include the disclaimer since all results are chemical product data
    if isinstance(result, dict):
        result.setdefault("disclaimer", DISCLAIMER)
    return result


@app.get("/label/{epa_reg_no}/sections")
def label_sections(epa_reg_no: str) -> dict[str, Any]:
    """Return the extracted sections of a product label."""
    db = _db_path()
    label_data = _fetch_label(epa_reg_no, db)
    source_url = _get_product_source_url(epa_reg_no, db)
    return {
        **_api_meta(),
        "epa_reg_no": epa_reg_no,
        "label_date": label_data.get("label_date"),
        "source_url": source_url,
        "sections": label_data.get("sections"),
        "disclaimer": DISCLAIMER,
    }


@app.get("/label/{epa_reg_no}")
def label(epa_reg_no: str) -> dict[str, Any]:
    """Return full label metadata and extracted sections for a product."""
    db = _db_path()
    label_data = _fetch_label(epa_reg_no, db)
    source_url = _get_product_source_url(epa_reg_no, db)
    return {
        **_api_meta(),
        "epa_reg_no": epa_reg_no,
        "product_name": label_data.get("product_name"),
        "label_date": label_data.get("label_date"),
        "source_url": source_url,
        "sections": label_data.get("sections"),
        "disclaimer": DISCLAIMER,
    }
