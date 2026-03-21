"""Match scoring system for the chemical resolution pipeline.

Quantifies confidence when matching seed data to EPA products.

Scoring factors
---------------
- Exact EPA reg no match       → highest   (1.0)
- Exact product name match     → very high (name_similarity_score = 1.0)
- Normalized name match        → high      (name_similarity_score = 0.95)
- Fuzzy name similarity        → medium    (Jaccard token overlap)
- Ingredient + manufacturer    → medium-low

Confidence thresholds
---------------------
- overall_score >= 0.9  → "high"
- overall_score >= 0.7  → "medium"
- overall_score <  0.7  → "low"
"""

from __future__ import annotations

import logging
import operator
import re
from pathlib import Path
from typing import Any

from .normalize import normalize_product_name
from .schema import get_connection

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Confidence thresholds
# ---------------------------------------------------------------------------

CONFIDENCE_HIGH: float = 0.9
CONFIDENCE_MEDIUM: float = 0.7

# Score weights for the overall_score composite
_W_NAME: float = 0.60
_W_INGREDIENT: float = 0.25
_W_MANUFACTURER: float = 0.15


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _tokenise(text: str) -> set[str]:
    """Return a set of lower-case word tokens from *text*."""
    return set(re.findall(r"[a-z0-9]+", text.lower()))


def _jaccard(a: str | None, b: str | None) -> float:
    """Jaccard token-overlap coefficient; returns 0–1."""
    if not a or not b:
        return 0.0
    ta = _tokenise(a)
    tb = _tokenise(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def _ingredient_set(ingredients: list[Any] | None) -> set[str]:
    """Return a set of lower-cased ingredient names from a list of dicts or strings."""
    result: set[str] = set()
    for item in ingredients or []:
        if isinstance(item, dict):
            name = item.get("name") or ""
        else:
            name = str(item)
        name = name.strip().lower()
        if name:
            result.add(name)
    return result


def _confidence_label(score: float) -> str:
    """Map a numeric score to a confidence label."""
    if score >= CONFIDENCE_HIGH:
        return "high"
    if score >= CONFIDENCE_MEDIUM:
        return "medium"
    return "low"


# ---------------------------------------------------------------------------
# Public scoring API
# ---------------------------------------------------------------------------


def score_match(seed: dict, candidate: dict) -> dict:
    """Score *seed* against an EPA product *candidate*.

    Parameters
    ----------
    seed:
        Incoming product data.  Recognised keys: ``epa_reg_no``,
        ``product_name``, ``active_ingredients``, ``registrant``
        (or ``manufacturer``).  All are optional.
    candidate:
        An EPA product record dict (e.g. from the database or a search result).

    Returns
    -------
    dict with the following keys:

    ``epa_reg_no``
        EPA registration number of the candidate.
    ``match_score``
        Alias of ``overall_score`` (provided for API convenience).
    ``match_type``
        One of ``exact_epa_reg_no``, ``exact_name``, ``normalized_name``,
        ``fuzzy_name``, ``ingredient_manufacturer``, ``no_match``.
    ``confidence``
        ``"high"``, ``"medium"``, or ``"low"``.
    ``name_similarity_score``
        Float 0–1 reflecting how closely the product names match.
    ``ingredient_match_score``
        Float 0–1 Jaccard similarity over active-ingredient sets.
    ``manufacturer_match_score``
        Float 0–1 reflecting registrant / manufacturer similarity.
    ``overall_score``
        Weighted composite of the three sub-scores (or 1.0 for exact EPA
        reg no matches).
    """
    seed_epa = (seed.get("epa_reg_no") or "").strip()
    cand_epa = (candidate.get("epa_reg_no") or "").strip()

    seed_name_norm = normalize_product_name(seed.get("product_name"))
    cand_name_norm = normalize_product_name(candidate.get("product_name"))

    seed_registrant = (
        seed.get("registrant") or seed.get("manufacturer") or ""
    ).strip()
    cand_registrant = (candidate.get("registrant") or "").strip()

    seed_ais = _ingredient_set(seed.get("active_ingredients"))
    cand_ais = _ingredient_set(candidate.get("active_ingredients"))

    # ------------------------------------------------------------------
    # Name / identifier similarity
    # ------------------------------------------------------------------
    exact_epa = bool(seed_epa and cand_epa and seed_epa == cand_epa)

    name_similarity_score: float = 0.0
    match_type: str = "no_match"

    if exact_epa:
        name_similarity_score = 1.0
        match_type = "exact_epa_reg_no"
    elif (
        seed_name_norm
        and cand_name_norm
        and seed_name_norm.lower() == cand_name_norm.lower()
    ):
        name_similarity_score = 1.0
        match_type = "exact_name"
    elif seed_name_norm and cand_name_norm:
        # Normalized-name match already happened above (normalize_product_name
        # collapses internal whitespace).  A second normalization pass would be
        # a no-op, so we go straight to Jaccard for remaining cases.
        js = _jaccard(seed_name_norm, cand_name_norm)
        if js > 0:
            name_similarity_score = round(js, 4)
            match_type = "fuzzy_name"

    # ------------------------------------------------------------------
    # Ingredient similarity (Jaccard over name sets)
    # ------------------------------------------------------------------
    ingredient_match_score: float = 0.0
    if seed_ais and cand_ais:
        union = seed_ais | cand_ais
        ingredient_match_score = round(len(seed_ais & cand_ais) / len(union), 4)

    # ------------------------------------------------------------------
    # Manufacturer / registrant similarity
    # ------------------------------------------------------------------
    manufacturer_match_score: float = 0.0
    if seed_registrant and cand_registrant:
        if seed_registrant.lower() == cand_registrant.lower():
            manufacturer_match_score = 1.0
        else:
            manufacturer_match_score = round(
                _jaccard(seed_registrant, cand_registrant), 4
            )

    # ------------------------------------------------------------------
    # Overall score
    # ------------------------------------------------------------------
    if exact_epa:
        overall_score: float = 1.0
    elif match_type == "exact_name":
        # Exact name match is "very high" – base of 0.9 boosted by
        # ingredient / manufacturer agreement, capped at 1.0.
        overall_score = min(
            1.0,
            0.9
            + 0.05 * ingredient_match_score
            + 0.05 * manufacturer_match_score,
        )
    else:
        overall_score = (
            _W_NAME * name_similarity_score
            + _W_INGREDIENT * ingredient_match_score
            + _W_MANUFACTURER * manufacturer_match_score
        )
        # If there's no name signal at all, fall back to ingredient+manufacturer
        if match_type == "no_match" and (
            ingredient_match_score > 0 or manufacturer_match_score > 0
        ):
            match_type = "ingredient_manufacturer"
            overall_score = (
                0.5 * ingredient_match_score + 0.5 * manufacturer_match_score
            )

    overall_score = round(min(overall_score, 1.0), 4)
    confidence = _confidence_label(overall_score)

    result: dict[str, Any] = {
        "epa_reg_no": cand_epa,
        "match_score": overall_score,
        "match_type": match_type,
        "confidence": confidence,
        "name_similarity_score": name_similarity_score,
        "ingredient_match_score": ingredient_match_score,
        "manufacturer_match_score": manufacturer_match_score,
        "overall_score": overall_score,
    }

    logger.debug(
        "score_match: seed=%r candidate=%r → %r",
        seed.get("product_name") or seed.get("epa_reg_no"),
        candidate.get("product_name") or candidate.get("epa_reg_no"),
        result,
    )

    return result


def resolve_product(
    seed: dict,
    db_path: str | Path,
    *,
    top: int = 10,
    threshold: float = 0.0,
) -> dict:
    """Resolve *seed* data to the best matching EPA product in the index.

    Searches the database using every available seed field (EPA reg no,
    product name, active ingredients, registrant) and scores each unique
    candidate.  All match attempts are logged for debugging.

    Parameters
    ----------
    seed:
        Incoming product data.  Recognised keys: ``epa_reg_no``,
        ``product_name``, ``active_ingredients``, ``registrant``
        (or ``manufacturer``).  All are optional.
    db_path:
        Path to the SQLite database.
    top:
        Maximum candidates fetched per search strategy.
    threshold:
        Minimum ``overall_score`` required for a result to appear in
        ``attempts``.  Defaults to ``0.0`` (include everything).

    Returns
    -------
    dict with keys:

    ``best_match``
        The highest-scoring scored result dict (see :func:`score_match`),
        or ``None`` if no candidates were found.
    ``attempts``
        List of all scored match dicts, sorted by ``overall_score``
        descending, filtered by *threshold*.
    """
    from .search import (
        search_by_active_ingredient,
        search_by_epa_reg_no,
        search_by_fuzzy,
        search_by_product_name,
        search_by_registrant,
    )

    conn = get_connection(db_path)
    try:
        candidates: list[dict] = []
        seen: set[str] = set()

        def _add(rows: list[dict]) -> None:
            for r in rows:
                epa = r.get("epa_reg_no", "")
                if epa not in seen:
                    seen.add(epa)
                    candidates.append(r)

        # Strategy 1: exact EPA reg no
        if seed.get("epa_reg_no"):
            _add(search_by_epa_reg_no(seed["epa_reg_no"], conn, top=top))

        # Strategy 2: exact product name
        if seed.get("product_name"):
            _add(search_by_product_name(seed["product_name"], conn, top=top))

        # Strategy 3: fuzzy product name
        if seed.get("product_name"):
            _add(search_by_fuzzy(seed["product_name"], conn, top=top))

        # Strategy 4: active ingredient(s)
        for ai in seed.get("active_ingredients") or []:
            ai_name = ai.get("name") if isinstance(ai, dict) else str(ai)
            if ai_name:
                _add(search_by_active_ingredient(ai_name, conn, top=top))

        # Strategy 5: registrant / manufacturer
        registrant = seed.get("registrant") or seed.get("manufacturer")
        if registrant:
            _add(search_by_registrant(registrant, conn, top=top))

    finally:
        conn.close()

    # Score every unique candidate
    attempts: list[dict] = []
    for candidate in candidates:
        scored = score_match(seed, candidate)
        scored["product_name"] = candidate.get("product_name")
        if scored["overall_score"] >= threshold:
            attempts.append(scored)

    attempts.sort(key=operator.itemgetter("overall_score"), reverse=True)

    logger.info(
        "resolve_product: seed=%r → %d candidates, %d attempts above threshold=%.2f; "
        "best_match=%r (score=%.4f)",
        seed.get("product_name") or seed.get("epa_reg_no"),
        len(candidates),
        len(attempts),
        threshold,
        attempts[0].get("epa_reg_no") if attempts else None,
        attempts[0].get("overall_score", 0.0) if attempts else 0.0,
    )

    return {
        "best_match": attempts[0] if attempts else None,
        "attempts": attempts,
    }
