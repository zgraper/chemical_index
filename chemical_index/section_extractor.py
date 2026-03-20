"""Rule-based section extraction from pesticide/chemical label text."""

from __future__ import annotations

import re
from typing import NamedTuple

# ---------------------------------------------------------------------------
# Section definitions
# Each entry maps an output key to a list of header patterns (case-insensitive,
# matched against stripped lines).  The first matching pattern wins.
# ---------------------------------------------------------------------------

SECTION_PATTERNS: list[tuple[str, list[str]]] = [
    ("directions_for_use", [r"DIRECTIONS\s+FOR\s+USE"]),
    ("restrictions", [r"RESTRICTIONS?"]),
    ("ppe", [r"PERSONAL\s+PROTECTIVE\s+EQUIPMENT"]),
    ("rei", [r"RESTRICTED[\s-]+ENTRY\s+INTERVAL"]),
    ("phi", [r"PRE[\s-]*HARVEST\s+INTERVAL"]),
    ("environmental_hazards", [r"ENVIRONMENTAL\s+HAZARDS?"]),
    ("spray_drift", [r"SPRAY\s+DRIFT"]),
    ("agricultural_use", [r"AGRICULTURAL\s+USE\s+REQUIREMENTS?"]),
]

# All compiled header regexes (used to detect where a new section starts)
_ALL_HEADER_RES: list[re.Pattern[str]] = [
    re.compile(pat, re.IGNORECASE)
    for _, patterns in SECTION_PATTERNS
    for pat in patterns
]


class _Span(NamedTuple):
    key: str
    start: int  # index into lines list


def _match_section_header(line: str) -> str | None:
    """Return the section key if *line* matches any known section header, else None."""
    stripped = line.strip()
    for key, patterns in SECTION_PATTERNS:
        for pat in patterns:
            if re.fullmatch(pat, stripped, re.IGNORECASE):
                return key
            # Also accept lines where the header is embedded (e.g. "** DIRECTIONS FOR USE **")
            if re.search(pat, stripped, re.IGNORECASE):
                return key
    return None


def _is_any_major_header(line: str) -> bool:
    """Return True if *line* matches ANY known section header."""
    return _match_section_header(line) is not None


def extract_sections(text: str) -> dict[str, str | None]:
    """Extract labelled sections from normalized label text.

    Scans *text* line-by-line looking for known section headers.  The text
    between a header and the next recognised major header is captured as the
    section body.  Verbatim wording is preserved; no summarisation is applied.

    Returns a dict with keys from :data:`SECTION_PATTERNS` plus any additional
    keys discovered.  Values are the raw body text or ``None`` when the section
    was not found.
    """
    lines = text.splitlines()

    spans: list[_Span] = []
    for i, line in enumerate(lines):
        key = _match_section_header(line)
        if key is not None:
            spans.append(_Span(key=key, start=i))

    # Build result dict – default all known keys to None
    result: dict[str, str | None] = {key: None for key, _ in SECTION_PATTERNS}

    for idx, span in enumerate(spans):
        end = spans[idx + 1].start if idx + 1 < len(spans) else len(lines)
        # Body starts on the line after the header
        body_lines = lines[span.start + 1 : end]
        # Strip leading/trailing blank lines from the body
        while body_lines and body_lines[0].strip() == "":
            body_lines = body_lines[1:]
        while body_lines and body_lines[-1].strip() == "":
            body_lines = body_lines[:-1]
        body = "\n".join(body_lines).strip()
        # Only set if we got meaningful content; don't overwrite a longer hit
        if body:
            existing = result.get(span.key)
            if existing is None or len(body) > len(existing):
                result[span.key] = body

    return result
