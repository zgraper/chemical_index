"""Metadata normalization helpers."""

from __future__ import annotations

import json
from typing import Any


def normalize_epa_reg_no(value: Any) -> str:
    """Normalize an EPA registration number to a canonical string (stripped)."""
    if value is None:
        return ""
    return str(value).strip()


def normalize_string(value: Any) -> str | None:
    """Return a stripped string or None."""
    if value is None:
        return None
    s = str(value).strip()
    return s if s else None


def normalize_list(value: Any) -> list:
    """Ensure value is a list; wrap scalars in a list."""
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            if isinstance(parsed, list):
                return parsed
        except (json.JSONDecodeError, ValueError):
            pass
        return [value]
    return [value]


def normalize_dict(value: Any) -> dict:
    """Ensure value is a dict."""
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            if isinstance(parsed, dict):
                return parsed
        except (json.JSONDecodeError, ValueError):
            pass
    return {}


def normalize_active_ingredients(value: Any) -> list[dict]:
    """
    Normalize active_ingredients to a list of dicts with 'name' and 'pct' keys.

    Accepts:
      - List of dicts with 'name' and/or 'pct'
      - List of strings (name only)
      - A single string
      - JSON-encoded string of the above
    """
    raw = normalize_list(value)
    result = []
    for item in raw:
        if isinstance(item, dict):
            name = normalize_string(item.get("name") or item.get("ingredient") or "")
            pct = item.get("pct") or item.get("percent") or item.get("percentage")
            try:
                pct = float(pct) if pct is not None else None
            except (TypeError, ValueError):
                pct = None
            result.append({"name": name, "pct": pct})
        elif isinstance(item, str):
            result.append({"name": item.strip(), "pct": None})
    return result


def normalize_record(raw: dict) -> dict:
    """
    Normalize a raw source dict into a canonical product metadata dict.

    All JSON-serializable fields are returned as Python objects; callers are
    responsible for serialising them before storage.
    """
    return {
        "epa_reg_no": normalize_epa_reg_no(raw.get("epa_reg_no")),
        "product_name": normalize_string(raw.get("product_name")),
        "alternate_names": normalize_list(raw.get("alternate_names")),
        "registrant": normalize_string(raw.get("registrant")),
        "active_ingredients": normalize_active_ingredients(
            raw.get("active_ingredients")
        ),
        "label_stamped_date": normalize_string(raw.get("label_stamped_date")),
        "source_url": normalize_string(raw.get("source_url")),
        "pdf_url": normalize_string(raw.get("pdf_url")),
        "federal_status": normalize_string(raw.get("federal_status")),
        "state_status_flags": normalize_dict(raw.get("state_status_flags")),
    }
