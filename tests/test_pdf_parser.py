"""Tests for pdf_parser module."""

from __future__ import annotations

import io
import struct
import zlib
from pathlib import Path

import pytest

from chemical_index.pdf_parser import normalize_text


# ---------------------------------------------------------------------------
# normalize_text – pure string tests (no PDF file needed)
# ---------------------------------------------------------------------------


def test_normalize_collapses_spaces():
    text = "word1   word2\tword3"
    result = normalize_text(text)
    assert result == "word1 word2 word3"


def test_normalize_removes_form_feed():
    text = "page1\fpage2"
    result = normalize_text(text)
    assert "\f" not in result
    assert "page1" in result
    assert "page2" in result


def test_normalize_rejoin_soft_hyphen():
    text = "chemi-\ncal product"
    result = normalize_text(text)
    assert "chemical product" in result


def test_normalize_collapses_blank_lines():
    text = "line1\n\n\n\nline2"
    result = normalize_text(text)
    lines = result.splitlines()
    # At most one blank line between content lines
    blank_runs = 0
    prev_blank = False
    for line in lines:
        if line.strip() == "":
            if prev_blank:
                blank_runs += 1
            prev_blank = True
        else:
            prev_blank = False
    assert blank_runs == 0


def test_normalize_strips_leading_trailing():
    text = "  hello world  "
    result = normalize_text(text)
    assert result == "hello world"


def test_normalize_empty_string():
    assert normalize_text("") == ""


def test_normalize_preserves_newlines_between_sections():
    text = "SECTION ONE\nsome content\n\nSECTION TWO\nmore content"
    result = normalize_text(text)
    assert "SECTION ONE" in result
    assert "some content" in result
    assert "SECTION TWO" in result
