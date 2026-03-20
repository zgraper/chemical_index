"""Tests for section_extractor module."""

from __future__ import annotations

import pytest

from chemical_index.section_extractor import extract_sections


LABEL_TEXT = """\
PRODUCT LABEL
Some preamble text.

DIRECTIONS FOR USE
It is a violation of Federal law to use this product in a manner
inconsistent with its labeling.
Apply uniformly.

RESTRICTIONS
Do not apply within 50 feet of water bodies.
Do not apply when wind speed exceeds 15 mph.

PERSONAL PROTECTIVE EQUIPMENT
Applicators and other handlers must wear:
- Long-sleeved shirt and long pants
- Chemical-resistant gloves

ENVIRONMENTAL HAZARDS
This product is toxic to fish and aquatic invertebrates.
Do not apply directly to water.

SPRAY DRIFT
Avoid spray drift at the site of application.
Use the largest droplet size consistent with acceptable efficacy.

AGRICULTURAL USE REQUIREMENTS
Use this product only in accordance with its labeling and with the Worker
Protection Standard, 40 CFR Part 170.
"""


def test_extract_sections_returns_all_keys():
    result = extract_sections(LABEL_TEXT)
    assert "directions_for_use" in result
    assert "restrictions" in result
    assert "ppe" in result
    assert "environmental_hazards" in result
    assert "spray_drift" in result
    assert "agricultural_use" in result


def test_directions_for_use_extracted():
    result = extract_sections(LABEL_TEXT)
    dfu = result["directions_for_use"]
    assert dfu is not None
    assert "violation of Federal law" in dfu


def test_restrictions_extracted():
    result = extract_sections(LABEL_TEXT)
    restr = result["restrictions"]
    assert restr is not None
    assert "50 feet" in restr


def test_ppe_extracted():
    result = extract_sections(LABEL_TEXT)
    ppe = result["ppe"]
    assert ppe is not None
    assert "gloves" in ppe


def test_environmental_hazards_extracted():
    result = extract_sections(LABEL_TEXT)
    env = result["environmental_hazards"]
    assert env is not None
    assert "fish and aquatic invertebrates" in env


def test_spray_drift_extracted():
    result = extract_sections(LABEL_TEXT)
    sd = result["spray_drift"]
    assert sd is not None
    assert "droplet size" in sd


def test_agricultural_use_extracted():
    result = extract_sections(LABEL_TEXT)
    ag = result["agricultural_use"]
    assert ag is not None
    assert "Worker" in ag


def test_missing_section_returns_none():
    result = extract_sections("This label has no known sections at all.")
    assert result["directions_for_use"] is None
    assert result["ppe"] is None
    assert result["rei"] is None


def test_section_does_not_include_next_header():
    result = extract_sections(LABEL_TEXT)
    dfu = result["directions_for_use"]
    # The restrictions header should NOT be part of directions_for_use body
    assert "RESTRICTIONS" not in dfu


def test_empty_text():
    result = extract_sections("")
    for v in result.values():
        assert v is None


def test_rei_section():
    text = """\
RESTRICTED-ENTRY INTERVAL
Do not enter treated areas for 12 hours after application.
"""
    result = extract_sections(text)
    assert result["rei"] is not None
    assert "12 hours" in result["rei"]


def test_phi_section():
    text = """\
PRE-HARVEST INTERVAL
Do not apply within 14 days of harvest.
"""
    result = extract_sections(text)
    assert result["phi"] is not None
    assert "14 days" in result["phi"]


def test_verbatim_text_preserved():
    """Section bodies must preserve original wording exactly."""
    text = "DIRECTIONS FOR USE\nApply at a rate of 2 oz/gal. Do NOT exceed label rate.\n"
    result = extract_sections(text)
    assert result["directions_for_use"] == "Apply at a rate of 2 oz/gal. Do NOT exceed label rate."
