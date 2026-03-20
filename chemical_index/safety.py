"""Safety layer for chemical queries.

Exposes :func:`enforce_safe_output` which detects pesticide / herbicide
content, strips recommendation-style text, and appends the required
regulatory disclaimer.
"""

from __future__ import annotations

import re
from typing import Any

# ---------------------------------------------------------------------------
# Public constant
# ---------------------------------------------------------------------------

DISCLAIMER = (
    "This is label information for reference only. "
    "Always follow the full product label and local regulations."
)

# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

# Keywords that identify a response as pesticide / herbicide related.
_TRIGGER_RE = re.compile(
    r"\b(pesticide|herbicide|insecticide|fungicide|acaricide|rodenticide|"
    r"nematicide|apply|application|spray|spraying|treatment|dose|dosage|"
    r"rate|weed|pest|fungus|insect|control|kill|chemical|label|"
    r"active\s+ingredient)\b",
    re.IGNORECASE,
)

# Sentence-level patterns that constitute recommendation / advice output.
_ADVICE_PATTERNS = [
    re.compile(r"\byou\s+should\b", re.IGNORECASE),
    re.compile(r"\bI\s+recommend\b", re.IGNORECASE),
    re.compile(r"\bwe\s+recommend\b", re.IGNORECASE),
    re.compile(
        r"\brecommend\s+(apply|applying|using|spraying|treating)\b", re.IGNORECASE
    ),
    re.compile(r"\byou\s+can\s+(apply|use|spray|treat)\b", re.IGNORECASE),
    re.compile(r"\byou\s+must\s+(apply|use|spray|treat)\b", re.IGNORECASE),
    re.compile(r"\bwe\s+suggest\b", re.IGNORECASE),
    re.compile(r"\bbest\s+practice\s+is\b", re.IGNORECASE),
    re.compile(r"\bit\s+is\s+recommended\b", re.IGNORECASE),
    re.compile(r"\bshould\s+be\s+applied\b", re.IGNORECASE),
]

# Split on sentence-ending punctuation followed by whitespace.
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")


def _is_pesticide_query(text: str) -> bool:
    """Return ``True`` if *text* contains pesticide / herbicide related keywords."""
    return bool(_TRIGGER_RE.search(text))


def _strip_advice(text: str) -> str:
    """Remove sentences that contain recommendation-style language from *text*."""
    sentences = _SENTENCE_SPLIT_RE.split(text)
    clean = [s for s in sentences if not any(p.search(s) for p in _ADVICE_PATTERNS)]
    return " ".join(clean).strip()


def _dict_to_flat_text(d: dict) -> str:
    """Flatten *d* values to a single string for keyword scanning."""
    parts: list[str] = []
    for v in d.values():
        if isinstance(v, str):
            parts.append(v)
        elif isinstance(v, (list, tuple)):
            parts.extend(str(x) for x in v)
        elif isinstance(v, dict):
            parts.append(_dict_to_flat_text(v))
    return " ".join(parts)


def _sanitise_dict(d: dict) -> dict:
    """Return a copy of *d* with advice stripped from all string values."""
    result: dict[str, Any] = {}
    for k, v in d.items():
        if isinstance(v, str):
            result[k] = _strip_advice(v)
        elif isinstance(v, dict):
            result[k] = _sanitise_dict(v)
        else:
            result[k] = v
    return result


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def enforce_safe_output(response: Any) -> Any:
    """Apply the chemical-safety layer to *response*.

    When the response relates to pesticide or herbicide use this function:

    * Removes recommendation-style sentences ("you should apply", etc.).
    * Strips inferred application decisions.
    * Appends the required regulatory disclaimer.

    *response* may be a :class:`str`, a :class:`dict` (single result), or a
    :class:`list` of dicts.  The function returns the same type that was
    passed in.
    """
    if isinstance(response, str):
        if _is_pesticide_query(response):
            cleaned = _strip_advice(response)
            return f"{cleaned}\n\n{DISCLAIMER}" if cleaned else DISCLAIMER
        return response

    if isinstance(response, dict):
        if _is_pesticide_query(_dict_to_flat_text(response)):
            result = _sanitise_dict(response)
            result["disclaimer"] = DISCLAIMER
            return result
        return response

    if isinstance(response, list):
        triggered = any(
            isinstance(item, dict) and _is_pesticide_query(_dict_to_flat_text(item))
            for item in response
        )
        if triggered:
            sanitised: list[Any] = []
            for item in response:
                if isinstance(item, dict):
                    clean_item = _sanitise_dict(item)
                    clean_item["disclaimer"] = DISCLAIMER
                    sanitised.append(clean_item)
                else:
                    sanitised.append(item)
            return sanitised
        return response

    return response
