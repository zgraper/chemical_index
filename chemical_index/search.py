"""Search module – ranked retrieval with explain field."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .schema import get_connection

# Search modes exposed via CLI / API
MODES = ("epa_reg_no", "product_name", "fuzzy", "active_ingredient", "registrant")


def _row_to_dict(row) -> dict:
    """Convert a sqlite3.Row to a plain dict, deserialising JSON columns."""
    d = dict(row)
    for col in ("alternate_names", "active_ingredients", "state_status_flags"):
        if d.get(col):
            try:
                d[col] = json.loads(d[col])
            except (json.JSONDecodeError, TypeError):
                pass
    return d


def _tokenise(text: str) -> set[str]:
    """Lower-case word tokens from *text*."""
    return set(re.findall(r"[a-z0-9]+", text.lower()))


def _fuzzy_score(query: str, candidate: str | None) -> float:
    """
    Simple token-overlap Jaccard coefficient between query and candidate.
    Returns a float in [0, 1].
    """
    if not candidate:
        return 0.0
    q_tokens = _tokenise(query)
    c_tokens = _tokenise(candidate)
    if not q_tokens or not c_tokens:
        return 0.0
    intersection = q_tokens & c_tokens
    union = q_tokens | c_tokens
    return len(intersection) / len(union)


def _build_result(
    row: dict,
    score: float,
    explain: str,
    match_source: str = "",
) -> dict:
    return {**row, "score": round(score, 4), "explain": explain, "match_source": match_source}


# ---------------------------------------------------------------------------
# Individual search functions
# ---------------------------------------------------------------------------


def search_by_epa_reg_no(
    query: str,
    conn,
    *,
    top: int = 10,
) -> list[dict]:
    """Exact match on epa_reg_no (latest versions only)."""
    rows = conn.execute(
        """
        SELECT * FROM product_versions
        WHERE epa_reg_no = ? AND is_latest = 1
        ORDER BY last_seen_at DESC
        LIMIT ?
        """,
        (query.strip(), top),
    ).fetchall()
    results = []
    for row in rows:
        d = _row_to_dict(row)
        results.append(
            _build_result(d, 1.0, f"Exact EPA reg no match: {query!r}", "exact_epa_reg_no")
        )
    return results


def search_by_product_name(
    query: str,
    conn,
    *,
    top: int = 10,
) -> list[dict]:
    """Case-insensitive exact match on product_name (latest versions only)."""
    rows = conn.execute(
        """
        SELECT * FROM product_versions
        WHERE product_name = ? COLLATE NOCASE AND is_latest = 1
        ORDER BY last_seen_at DESC
        LIMIT ?
        """,
        (query.strip(), top),
    ).fetchall()
    results = []
    for row in rows:
        d = _row_to_dict(row)
        results.append(
            _build_result(
                d, 1.0, f"Exact product name match: {query!r}", "normalized_exact_name"
            )
        )
    return results


def search_by_fuzzy(
    query: str,
    conn,
    *,
    top: int = 10,
    threshold: float = 0.1,
) -> list[dict]:
    """
    Fuzzy product-name search using token-overlap scoring.

    Scores against product_name and alternate_names; uses the best score.
    Also checks if query tokens appear in active ingredients.
    Results below *threshold* are dropped.
    """
    rows = conn.execute(
        "SELECT * FROM product_versions WHERE is_latest = 1"
    ).fetchall()

    scored: list[tuple[float, str, str, dict]] = []
    q_tokens = _tokenise(query)

    for row in rows:
        d = _row_to_dict(row)
        best_score = 0.0
        best_reason = ""
        best_source = ""

        # Score against product_name
        name_score = _fuzzy_score(query, d.get("product_name"))
        if name_score > best_score:
            best_score = name_score
            best_reason = f"Fuzzy product name match (score={name_score:.3f}): {query!r} ~ {d.get('product_name')!r}"
            best_source = "fuzzy_name_score"

        # Score against each alternate name
        for alt in (d.get("alternate_names") or []):
            s = _fuzzy_score(query, alt)
            if s > best_score:
                best_score = s
                best_reason = f"Fuzzy alternate name match (score={s:.3f}): {query!r} ~ {alt!r}"
                best_source = "alias"

        # Partial credit if query tokens appear in active ingredients
        ais = d.get("active_ingredients") or []
        ai_names = " ".join(ai.get("name", "") for ai in ais if isinstance(ai, dict))
        ai_tokens = _tokenise(ai_names)
        if ai_tokens and q_tokens:
            overlap = len(q_tokens & ai_tokens) / len(q_tokens)
            if overlap > best_score:
                best_score = overlap * 0.8  # discount AI matches
                best_reason = f"Active ingredient token match (score={best_score:.3f}): {query!r}"
                best_source = "ingredient_keyword"

        if best_score >= threshold:
            scored.append((best_score, best_reason, best_source, d))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [
        _build_result(d, score, reason, source)
        for score, reason, source, d in scored[:top]
    ]


def search_by_active_ingredient(
    query: str,
    conn,
    *,
    top: int = 10,
) -> list[dict]:
    """Search latest versions whose active_ingredients contain *query* (case-insensitive substring)."""
    q_lower = query.strip().lower()
    rows = conn.execute(
        "SELECT * FROM product_versions WHERE is_latest = 1"
    ).fetchall()

    results = []
    for row in rows:
        d = _row_to_dict(row)
        ais = d.get("active_ingredients") or []
        for ai in ais:
            if isinstance(ai, dict):
                name = ai.get("name", "")
            else:
                name = str(ai)
            if q_lower in name.lower():
                results.append(
                    _build_result(
                        d,
                        1.0,
                        f"Active ingredient match: {query!r} in {name!r}",
                        "ingredient_keyword",
                    )
                )
                break  # one result per product

    results.sort(key=lambda x: x["score"], reverse=True)
    return results[:top]


def search_by_registrant(
    query: str,
    conn,
    *,
    top: int = 10,
) -> list[dict]:
    """Case-insensitive substring search on registrant (latest versions only)."""
    rows = conn.execute(
        """
        SELECT * FROM product_versions
        WHERE registrant LIKE ? COLLATE NOCASE AND is_latest = 1
        ORDER BY registrant ASC, last_seen_at DESC
        LIMIT ?
        """,
        (f"%{query.strip()}%", top),
    ).fetchall()
    results = []
    for row in rows:
        d = _row_to_dict(row)
        results.append(
            _build_result(
                d,
                1.0,
                f"Registrant match: {query!r} in {d.get('registrant')!r}",
                "registrant_keyword",
            )
        )
    return results


# ---------------------------------------------------------------------------
# Unified search entry point
# ---------------------------------------------------------------------------


def search(
    query: str,
    db_path: str | Path,
    *,
    mode: str = "fuzzy",
    top: int = 10,
) -> list[dict]:
    """
    Run a search against the index.

    Parameters
    ----------
    query:
        The search string.
    db_path:
        Path to the SQLite database.
    mode:
        One of ``'epa_reg_no'``, ``'product_name'``, ``'fuzzy'``,
        ``'active_ingredient'``, ``'registrant'``.
    top:
        Maximum number of results to return.

    Returns
    -------
    list of result dicts, each containing all product_versions columns plus
    ``score`` (float 0-1) and ``explain`` (str).
    """
    if mode not in MODES:
        raise ValueError(f"Unknown search mode {mode!r}. Choose from: {MODES}")

    conn = get_connection(db_path)
    try:
        if mode == "epa_reg_no":
            return search_by_epa_reg_no(query, conn, top=top)
        elif mode == "product_name":
            return search_by_product_name(query, conn, top=top)
        elif mode == "fuzzy":
            return search_by_fuzzy(query, conn, top=top)
        elif mode == "active_ingredient":
            return search_by_active_ingredient(query, conn, top=top)
        elif mode == "registrant":
            return search_by_registrant(query, conn, top=top)
    finally:
        conn.close()

    return []
