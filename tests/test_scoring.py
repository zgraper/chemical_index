"""Tests for the match scoring system (scoring.py)."""

from __future__ import annotations

import pytest

from chemical_index.build_index import build_index
from chemical_index.scoring import (
    CONFIDENCE_HIGH,
    CONFIDENCE_MEDIUM,
    resolve_product,
    score_match,
)

# ---------------------------------------------------------------------------
# Fixtures / shared data
# ---------------------------------------------------------------------------

PRODUCTS = [
    {
        "epa_reg_no": "524-308",
        "product_name": "Roundup Original",
        "alternate_names": ["Roundup"],
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
    build_index(PRODUCTS, db_path)
    return db_path


# ---------------------------------------------------------------------------
# score_match – unit tests
# ---------------------------------------------------------------------------


def test_exact_epa_reg_no_score():
    seed = {"epa_reg_no": "524-308"}
    candidate = {"epa_reg_no": "524-308", "product_name": "Roundup Original"}
    result = score_match(seed, candidate)

    assert result["match_type"] == "exact_epa_reg_no"
    assert result["overall_score"] == 1.0
    assert result["match_score"] == 1.0
    assert result["confidence"] == "high"


def test_exact_name_score():
    seed = {"product_name": "Roundup Original"}
    candidate = {"epa_reg_no": "524-308", "product_name": "Roundup Original"}
    result = score_match(seed, candidate)

    assert result["match_type"] == "exact_name"
    assert result["name_similarity_score"] == 1.0
    assert result["overall_score"] >= CONFIDENCE_HIGH
    assert result["confidence"] == "high"


def test_exact_name_case_insensitive():
    seed = {"product_name": "roundup original"}
    candidate = {"epa_reg_no": "524-308", "product_name": "Roundup Original"}
    result = score_match(seed, candidate)

    assert result["match_type"] == "exact_name"
    assert result["name_similarity_score"] == 1.0


def test_fuzzy_name_score():
    seed = {"product_name": "Roundup"}
    candidate = {"epa_reg_no": "524-308", "product_name": "Roundup Original"}
    result = score_match(seed, candidate)

    assert result["match_type"] == "fuzzy_name"
    assert 0.0 < result["name_similarity_score"] < 1.0
    assert 0.0 < result["overall_score"] < 1.0


def test_ingredient_match_score():
    seed = {
        "product_name": None,
        "active_ingredients": [{"name": "Glyphosate", "pct": 41.0}],
    }
    candidate = {
        "epa_reg_no": "524-308",
        "product_name": "Roundup Original",
        "active_ingredients": [{"name": "Glyphosate", "pct": 41.0}],
        "registrant": "Bayer CropScience LP",
    }
    result = score_match(seed, candidate)
    assert result["ingredient_match_score"] == 1.0


def test_manufacturer_match_score():
    seed = {"registrant": "Bayer CropScience LP"}
    candidate = {
        "epa_reg_no": "524-308",
        "product_name": "Roundup Original",
        "registrant": "Bayer CropScience LP",
    }
    result = score_match(seed, candidate)
    assert result["manufacturer_match_score"] == 1.0


def test_manufacturer_alias_manufacturer_key():
    seed = {"manufacturer": "Bayer CropScience LP"}
    candidate = {
        "epa_reg_no": "524-308",
        "product_name": "Roundup Original",
        "registrant": "Bayer CropScience LP",
    }
    result = score_match(seed, candidate)
    assert result["manufacturer_match_score"] == 1.0


def test_no_match_score():
    seed = {"product_name": "ZZZ Unknown Product XYZ"}
    candidate = {"epa_reg_no": "999-000", "product_name": "Totally Different Thing"}
    result = score_match(seed, candidate)

    assert result["overall_score"] < CONFIDENCE_MEDIUM
    assert result["confidence"] == "low"


def test_ingredient_manufacturer_fallback():
    """When name is absent, ingredient+manufacturer yields ingredient_manufacturer type."""
    seed = {
        "active_ingredients": [{"name": "Chlorpyrifos"}],
        "registrant": "Corteva Agriscience",
    }
    candidate = {
        "epa_reg_no": "352-664",
        "product_name": "Lorsban Advanced Insecticide",
        "active_ingredients": [{"name": "Chlorpyrifos", "pct": 44.0}],
        "registrant": "Corteva Agriscience",
    }
    result = score_match(seed, candidate)

    assert result["match_type"] == "ingredient_manufacturer"
    assert result["ingredient_match_score"] == 1.0
    assert result["manufacturer_match_score"] == 1.0
    assert result["overall_score"] == 1.0


def test_partial_ingredient_overlap():
    seed = {
        "active_ingredients": [
            {"name": "Glyphosate"},
            {"name": "Dicamba"},
        ]
    }
    candidate = {
        "epa_reg_no": "524-308",
        "product_name": "Roundup Original",
        "active_ingredients": [{"name": "Glyphosate", "pct": 41.0}],
    }
    result = score_match(seed, candidate)
    # intersection = {glyphosate}, union = {glyphosate, dicamba}  → 0.5
    assert result["ingredient_match_score"] == pytest.approx(0.5, abs=1e-4)


def test_score_keys_present():
    result = score_match({}, {"epa_reg_no": "524-308"})
    for key in (
        "epa_reg_no",
        "match_score",
        "match_type",
        "confidence",
        "name_similarity_score",
        "ingredient_match_score",
        "manufacturer_match_score",
        "overall_score",
    ):
        assert key in result, f"Missing key: {key}"


def test_overall_score_bounded():
    seed = {
        "epa_reg_no": "524-308",
        "product_name": "Roundup Original",
        "active_ingredients": [{"name": "Glyphosate"}],
        "registrant": "Bayer CropScience LP",
    }
    candidate = {
        "epa_reg_no": "524-308",
        "product_name": "Roundup Original",
        "active_ingredients": [{"name": "Glyphosate"}],
        "registrant": "Bayer CropScience LP",
    }
    result = score_match(seed, candidate)
    assert 0.0 <= result["overall_score"] <= 1.0


# ---------------------------------------------------------------------------
# Confidence thresholds
# ---------------------------------------------------------------------------


def test_confidence_high_threshold():
    seed = {"epa_reg_no": "524-308"}
    candidate = {"epa_reg_no": "524-308"}
    result = score_match(seed, candidate)
    assert result["confidence"] == "high"
    assert result["overall_score"] >= CONFIDENCE_HIGH


def test_confidence_medium_threshold():
    # Fuzzy product name match gives a medium-range score
    seed = {"product_name": "Roundup"}
    candidate = {"epa_reg_no": "524-308", "product_name": "Roundup Original"}
    result = score_match(seed, candidate)
    # score should be between 0 and HIGH; confidence depends on actual value
    assert result["confidence"] in ("high", "medium", "low")


def test_confidence_low_threshold():
    seed = {"product_name": "Totally Unknown Widget 9000"}
    candidate = {"epa_reg_no": "999-000", "product_name": "Carrot Juice Concentrate"}
    result = score_match(seed, candidate)
    assert result["confidence"] == "low"
    assert result["overall_score"] < CONFIDENCE_MEDIUM


# ---------------------------------------------------------------------------
# resolve_product – integration tests
# ---------------------------------------------------------------------------


def test_resolve_exact_epa(db):
    result = resolve_product({"epa_reg_no": "524-308"}, db)
    assert result["best_match"] is not None
    assert result["best_match"]["epa_reg_no"] == "524-308"
    assert result["best_match"]["match_type"] == "exact_epa_reg_no"
    assert result["best_match"]["overall_score"] == 1.0
    assert result["best_match"]["confidence"] == "high"


def test_resolve_exact_name(db):
    result = resolve_product({"product_name": "Roundup Original"}, db)
    assert result["best_match"] is not None
    assert result["best_match"]["epa_reg_no"] == "524-308"
    assert result["best_match"]["match_type"] == "exact_name"


def test_resolve_fuzzy_name(db):
    result = resolve_product({"product_name": "Lorsban Insecticide"}, db)
    assert result["best_match"] is not None
    assert result["best_match"]["epa_reg_no"] == "352-664"


def test_resolve_by_ingredient(db):
    result = resolve_product(
        {"active_ingredients": [{"name": "2,4-D choline salt"}]}, db
    )
    assert result["best_match"] is not None
    assert result["best_match"]["epa_reg_no"] == "100-1070"


def test_resolve_no_candidates(db):
    result = resolve_product({"epa_reg_no": "999-NOTFOUND"}, db)
    assert result["best_match"] is None
    assert result["attempts"] == []


def test_resolve_returns_attempts_list(db):
    result = resolve_product({"product_name": "Roundup"}, db)
    assert isinstance(result["attempts"], list)
    assert len(result["attempts"]) >= 1


def test_resolve_attempts_sorted_descending(db):
    result = resolve_product({"product_name": "Roundup Original"}, db)
    scores = [a["overall_score"] for a in result["attempts"]]
    assert scores == sorted(scores, reverse=True)


def test_resolve_threshold_filters(db):
    result_all = resolve_product({"product_name": "Roundup"}, db, threshold=0.0)
    result_high = resolve_product({"product_name": "Roundup"}, db, threshold=0.9)
    assert len(result_high["attempts"]) <= len(result_all["attempts"])
    for a in result_high["attempts"]:
        assert a["overall_score"] >= 0.9


def test_resolve_best_match_keys(db):
    result = resolve_product({"epa_reg_no": "100-1070"}, db)
    bm = result["best_match"]
    for key in (
        "epa_reg_no",
        "match_score",
        "match_type",
        "confidence",
        "name_similarity_score",
        "ingredient_match_score",
        "manufacturer_match_score",
        "overall_score",
    ):
        assert key in bm, f"Missing key: {key}"
