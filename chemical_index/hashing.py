"""Source hashing utilities."""

from __future__ import annotations

import hashlib
import json
from typing import Any


def _stable_serialise(obj: Any) -> str:
    """
    Return a deterministic JSON string for *obj*.

    Keys are sorted recursively so that field-order differences in source data
    do not produce different hashes.
    """
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, default=str)


def hash_record(normalised: dict) -> str:
    """
    Return a SHA-256 hex digest of a normalised product record.

    Only the content fields (not timestamps or run metadata) are included so
    that the hash reflects *what the data says*, not *when we saw it*.
    """
    content_fields = (
        "epa_reg_no",
        "product_name",
        "alternate_names",
        "registrant",
        "active_ingredients",
        "label_stamped_date",
        "source_url",
        "pdf_url",
        "federal_status",
        "state_status_flags",
    )
    content = {k: normalised[k] for k in content_fields if k in normalised}
    serialised = _stable_serialise(content)
    return hashlib.sha256(serialised.encode("utf-8")).hexdigest()


def hash_string(text: str) -> str:
    """Return SHA-256 hex digest of an arbitrary string."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def compare_source_hashes(hash1: str | None, hash2: str | None) -> bool:
    """
    Return ``True`` if both hashes are non-``None`` and equal.

    This is the canonical way to test whether a stored source hash matches a
    freshly-computed one; it guards against ``None`` comparisons that would
    incorrectly signal "unchanged".
    """
    if hash1 is None or hash2 is None:
        return False
    return hash1 == hash2
