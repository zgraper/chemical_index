"""Tests for the safety layer (chemical_index.safety)."""

from __future__ import annotations

import pytest

from chemical_index.safety import (
    DISCLAIMER,
    _is_pesticide_query,
    _strip_advice,
    enforce_safe_output,
)


# ---------------------------------------------------------------------------
# _is_pesticide_query
# ---------------------------------------------------------------------------


def test_is_pesticide_query_herbicide():
    assert _is_pesticide_query("This product is a herbicide for broad-leaf weeds.")


def test_is_pesticide_query_pesticide():
    assert _is_pesticide_query("Use this pesticide to control aphids.")


def test_is_pesticide_query_apply():
    assert _is_pesticide_query("Apply at 2 fl oz per acre.")


def test_is_pesticide_query_not_triggered():
    assert not _is_pesticide_query("The weather is nice today.")


def test_is_pesticide_query_case_insensitive():
    assert _is_pesticide_query("HERBICIDE product LABEL")


def test_is_pesticide_query_insecticide():
    assert _is_pesticide_query("This insecticide controls corn rootworm.")


def test_is_pesticide_query_fungicide():
    assert _is_pesticide_query("Fungicide application prevents early blight.")


# ---------------------------------------------------------------------------
# _strip_advice
# ---------------------------------------------------------------------------


def test_strip_advice_removes_you_should():
    text = "You should apply this product in early morning. Wear gloves."
    result = _strip_advice(text)
    assert "You should" not in result
    assert "Wear gloves" in result


def test_strip_advice_removes_i_recommend():
    text = "I recommend applying at 2 fl oz per acre. See full label."
    result = _strip_advice(text)
    assert "I recommend" not in result
    assert "See full label" in result


def test_strip_advice_removes_it_is_recommended():
    text = "It is recommended to spray in the morning. Follow label directions."
    result = _strip_advice(text)
    assert "It is recommended" not in result
    assert "Follow label directions" in result


def test_strip_advice_removes_should_be_applied():
    text = "The product should be applied before rain. Read the label."
    result = _strip_advice(text)
    assert "should be applied" not in result
    assert "Read the label" in result


def test_strip_advice_keeps_clean_text():
    text = "Product is registered for use on corn and soybeans."
    assert _strip_advice(text) == text


# ---------------------------------------------------------------------------
# enforce_safe_output – string input
# ---------------------------------------------------------------------------


def test_enforce_safe_output_string_adds_disclaimer():
    response = "This herbicide label states the active ingredient is glyphosate."
    result = enforce_safe_output(response)
    assert DISCLAIMER in result


def test_enforce_safe_output_string_non_chemical_unchanged():
    response = "The weather forecast shows rain tomorrow."
    result = enforce_safe_output(response)
    assert result == response


def test_enforce_safe_output_string_strips_advice():
    response = "You should apply this pesticide at dawn. Product EPA reg no: 524-308."
    result = enforce_safe_output(response)
    assert "You should" not in result
    assert DISCLAIMER in result


def test_enforce_safe_output_string_keeps_factual_excerpt():
    response = "Label excerpt: apply rate is 2 fl oz per acre per application."
    result = enforce_safe_output(response)
    assert DISCLAIMER in result
    # Factual text that has no advice patterns should survive
    assert "apply rate is 2 fl oz per acre" in result


# ---------------------------------------------------------------------------
# enforce_safe_output – dict input
# ---------------------------------------------------------------------------


def test_enforce_safe_output_dict_adds_disclaimer():
    response = {
        "product_name": "Roundup PowerMAX 3",
        "sections": {"directions_for_use": "Apply to foliage of actively growing weeds."},
    }
    result = enforce_safe_output(response)
    assert result.get("disclaimer") == DISCLAIMER


def test_enforce_safe_output_dict_strips_advice_in_sections():
    response = {
        "product_name": "Roundup PowerMAX 3",
        "sections": {
            "directions_for_use": "You should apply at 2 fl oz per acre. See restrictions."
        },
    }
    result = enforce_safe_output(response)
    assert "You should" not in result["sections"]["directions_for_use"]
    assert "See restrictions" in result["sections"]["directions_for_use"]


def test_enforce_safe_output_dict_non_chemical_unchanged():
    response = {"title": "Annual Report", "year": 2024}
    result = enforce_safe_output(response)
    assert "disclaimer" not in result
    assert result == {"title": "Annual Report", "year": 2024}


def test_enforce_safe_output_dict_preserves_non_string_values():
    response = {
        "epa_reg_no": "524-659",
        "active_ingredients": [{"name": "Glyphosate", "pct": 48.7}],
        "sections": {"ppe": "Wear chemical-resistant gloves."},
    }
    result = enforce_safe_output(response)
    assert result["active_ingredients"] == [{"name": "Glyphosate", "pct": 48.7}]
    assert result["disclaimer"] == DISCLAIMER


def test_enforce_safe_output_dict_triggered_by_product_name():
    response = {
        "product_name": "Warrior II Insecticide",
        "registrant": "Syngenta",
    }
    result = enforce_safe_output(response)
    assert result.get("disclaimer") == DISCLAIMER


# ---------------------------------------------------------------------------
# enforce_safe_output – list input
# ---------------------------------------------------------------------------


def test_enforce_safe_output_list_adds_disclaimer_to_all():
    items = [
        {"product_name": "Herbicide A", "score": 0.9},
        {"product_name": "Herbicide B", "score": 0.8},
    ]
    result = enforce_safe_output(items)
    for item in result:
        assert item.get("disclaimer") == DISCLAIMER


def test_enforce_safe_output_list_non_chemical_unchanged():
    items = [{"title": "Article"}, {"title": "Book"}]
    result = enforce_safe_output(items)
    assert all("disclaimer" not in item for item in result)


def test_enforce_safe_output_list_strips_advice():
    items = [
        {
            "product_name": "Herbicide A",
            "explain": "You should apply at dawn for best results.",
        }
    ]
    result = enforce_safe_output(items)
    assert "You should" not in result[0]["explain"]
    assert result[0]["disclaimer"] == DISCLAIMER


def test_enforce_safe_output_list_preserves_length():
    items = [
        {"product_name": "Herbicide A", "score": 0.9},
        {"product_name": "Herbicide B", "score": 0.8},
        {"product_name": "Herbicide C", "score": 0.7},
    ]
    result = enforce_safe_output(items)
    assert len(result) == 3


# ---------------------------------------------------------------------------
# enforce_safe_output – passthrough for unknown types
# ---------------------------------------------------------------------------


def test_enforce_safe_output_int_passthrough():
    assert enforce_safe_output(42) == 42


def test_enforce_safe_output_none_passthrough():
    assert enforce_safe_output(None) is None


# ---------------------------------------------------------------------------
# DISCLAIMER constant
# ---------------------------------------------------------------------------


def test_disclaimer_content():
    assert "label information for reference only" in DISCLAIMER
    assert "full product label" in DISCLAIMER
    assert "local regulations" in DISCLAIMER
