"""PDF text extraction and normalization for chemical product labels."""

from __future__ import annotations

import re
from pathlib import Path


def extract_text(pdf_path: str | Path) -> str:
    """Extract raw text from a PDF file using pypdf.

    Returns the concatenated text of all pages separated by newlines.
    Raises ``ImportError`` if pypdf is not installed, and
    ``FileNotFoundError`` if *pdf_path* does not exist.
    """
    try:
        from pypdf import PdfReader
    except ImportError as exc:  # pragma: no cover
        raise ImportError(
            "pypdf is required for PDF parsing. Install it with: pip install pypdf"
        ) from exc

    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    reader = PdfReader(str(pdf_path))
    pages: list[str] = []
    for page in reader.pages:
        text = page.extract_text() or ""
        pages.append(text)
    return "\n".join(pages)


def normalize_text(text: str) -> str:
    """Normalize whitespace and remove common PDF extraction artifacts.

    - Collapses runs of spaces/tabs to a single space per line
    - Removes form-feed characters
    - Merges hyphenated line-breaks (e.g. ``chemi-\\ncal`` → ``chemical``)
    - Collapses runs of blank lines to a single blank line
    - Strips leading/trailing whitespace from each line
    """
    # Remove form-feed characters
    text = text.replace("\f", "\n")

    # Rejoin soft-hyphenated line breaks (word- \n continuation)
    text = re.sub(r"-\s*\n\s*", "", text)

    # Strip trailing whitespace from each line and collapse internal spaces
    lines = []
    for line in text.splitlines():
        line = re.sub(r"[ \t]+", " ", line).strip()
        lines.append(line)

    # Collapse consecutive blank lines into one
    collapsed: list[str] = []
    prev_blank = False
    for line in lines:
        is_blank = line == ""
        if is_blank and prev_blank:
            continue
        collapsed.append(line)
        prev_blank = is_blank

    return "\n".join(collapsed).strip()
