"""Retrieval testing harness.

Golden test case JSON format (data/tests/retrieval_goldens.json)::

    [
      {
        "query": "Roundup",
        "expected_epa_reg_no": "524-308",
        "expected_product_name": "Roundup Original",
        "match_type": "fuzzy"
      },
      ...
    ]

Fields:
  - query                 (required) – the search string
  - expected_epa_reg_no   (required) – the EPA reg no that should appear in results
  - expected_product_name (optional) – used in terminal summary for context
  - match_type            (optional) – search mode to use; falls back to ``mode``
                          then ``'fuzzy'``

Metrics computed:
  - total_cases     – number of test cases run
  - top_1_accuracy  – fraction of queries where correct answer is rank 1
  - top_3_accuracy  – fraction of queries where correct answer is in top 3
  - mrr             – mean reciprocal rank (1/rank of first correct answer, or 0)
  - failure_count   – queries where the expected EPA reg no was not found at all
  - ambiguity_count – queries where the top-2 scores are within the ambiguity
                      threshold (default 0.05), making rank 1 uncertain
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from .search import search

# Scores within this delta are considered ambiguous at the top position.
AMBIGUITY_THRESHOLD = 0.05


def _reciprocal_rank(results: list[dict], expected_epa_reg_no: str) -> float:
    """Return 1/rank of the first result matching *expected_epa_reg_no*, or 0."""
    for rank, result in enumerate(results, start=1):
        if result.get("epa_reg_no") == expected_epa_reg_no:
            return 1.0 / rank
    return 0.0


def _in_top_k(results: list[dict], expected_epa_reg_no: str, k: int) -> bool:
    for result in results[:k]:
        if result.get("epa_reg_no") == expected_epa_reg_no:
            return True
    return False


def _is_ambiguous(results: list[dict]) -> bool:
    """Return True if the top-2 scores are within AMBIGUITY_THRESHOLD."""
    if len(results) < 2:
        return False
    score_0 = results[0].get("score", 0.0)
    score_1 = results[1].get("score", 0.0)
    return abs(score_0 - score_1) <= AMBIGUITY_THRESHOLD


def run_evaluation(
    test_cases_path: str | Path,
    db_path: str | Path,
    *,
    top: int = 10,
) -> dict[str, Any]:
    """
    Run all test cases and return a result dict.

    The returned dict contains:
    - ``metrics``: total_cases, top_1_accuracy, top_3_accuracy, mrr,
      failure_count, ambiguity_count
    - ``cases``: per-query details (query, mode, expected, top results, rr,
      match_source of the winning result)
    """
    path = Path(test_cases_path)
    with path.open("r", encoding="utf-8") as fh:
        cases_raw: list[dict] = json.load(fh)

    case_results = []
    rr_values = []
    top1_hits = 0
    top3_hits = 0
    failure_count = 0
    ambiguity_count = 0

    for case in cases_raw:
        query = case.get("query", "")
        # Support both 'match_type' (new golden format) and 'mode' (legacy)
        mode = case.get("match_type") or case.get("mode", "fuzzy")
        expected = case.get("expected_epa_reg_no", "")
        expected_product_name = case.get("expected_product_name")

        results = search(query, db_path, mode=mode, top=top)

        rr = _reciprocal_rank(results, expected)
        t1 = _in_top_k(results, expected, 1)
        t3 = _in_top_k(results, expected, 3)
        ambiguous = _is_ambiguous(results)

        rr_values.append(rr)
        if t1:
            top1_hits += 1
        if t3:
            top3_hits += 1
        if rr == 0.0:
            failure_count += 1
        if ambiguous:
            ambiguity_count += 1

        # Determine rank of expected result
        rank_of_expected = None
        for i, r in enumerate(results, start=1):
            if r.get("epa_reg_no") == expected:
                rank_of_expected = i
                break

        case_results.append(
            {
                "query": query,
                "mode": mode,
                "expected_epa_reg_no": expected,
                "expected_product_name": expected_product_name,
                "reciprocal_rank": round(rr, 4),
                "top_1_hit": t1,
                "top_3_hit": t3,
                "found": rr > 0.0,
                "rank_of_expected": rank_of_expected,
                "ambiguous": ambiguous,
                "top_results": [
                    {
                        "rank": i + 1,
                        "epa_reg_no": r.get("epa_reg_no"),
                        "product_name": r.get("product_name"),
                        "score": r.get("score"),
                        "match_source": r.get("match_source", ""),
                        "explain": r.get("explain"),
                    }
                    for i, r in enumerate(results[:5])
                ],
            }
        )

    n = len(cases_raw)
    metrics = {
        "total_cases": n,
        "top_1_accuracy": round(top1_hits / n, 4) if n else 0.0,
        "top_3_accuracy": round(top3_hits / n, 4) if n else 0.0,
        "mrr": round(sum(rr_values) / n, 4) if n else 0.0,
        "failure_count": failure_count,
        "ambiguity_count": ambiguity_count,
    }

    return {"metrics": metrics, "cases": case_results}


def format_terminal_summary(evaluation: dict[str, Any]) -> str:
    """Return a multi-line terminal summary of an evaluation run."""
    metrics = evaluation.get("metrics", {})
    cases = evaluation.get("cases", [])

    lines = [
        "=" * 60,
        "RETRIEVAL EVALUATION SUMMARY",
        "=" * 60,
        f"  Total cases    : {metrics.get('total_cases', 0)}",
        f"  Top-1 accuracy : {metrics.get('top_1_accuracy', 0.0):.2%}",
        f"  Top-3 accuracy : {metrics.get('top_3_accuracy', 0.0):.2%}",
        f"  MRR            : {metrics.get('mrr', 0.0):.4f}",
        f"  Failures       : {metrics.get('failure_count', 0)}",
        f"  Ambiguous      : {metrics.get('ambiguity_count', 0)}",
        "-" * 60,
    ]

    for case in cases:
        rank_label = "FAIL"
        if case.get("top_1_hit"):
            rank_label = "rank=1"
        elif case.get("top_3_hit"):
            rk = case.get("rank_of_expected")
            rank_label = f"rank={rk}" if rk else "top-3"

        ambig_marker = " [ambiguous]" if case.get("ambiguous") else ""
        lines.append(
            f"  [{rank_label:6s}]{ambig_marker} "
            f"query={case['query']!r}  "
            f"expected={case['expected_epa_reg_no']!r}"
        )
        top = case.get("top_results", [])
        if top:
            r1 = top[0]
            lines.append(
                f"           rank-1: epa={r1.get('epa_reg_no')}  "
                f"score={r1.get('score')}  "
                f"source={r1.get('match_source', '')}  "
                f"explain: {r1.get('explain', '')}"
            )

    lines.append("=" * 60)
    return "\n".join(lines)


def export_json(evaluation: dict[str, Any], output_path: str | Path) -> None:
    """Write the full evaluation dict to a JSON file."""
    with open(output_path, "w", encoding="utf-8") as fh:
        json.dump(evaluation, fh, indent=2, ensure_ascii=False)


def export_csv(evaluation: dict[str, Any], output_path: str | Path) -> None:
    """Write per-case results to a CSV file."""
    cases = evaluation.get("cases", [])
    if not cases:
        return

    fieldnames = [
        "query",
        "mode",
        "expected_epa_reg_no",
        "expected_product_name",
        "reciprocal_rank",
        "top_1_hit",
        "top_3_hit",
        "found",
        "rank_of_expected",
        "ambiguous",
    ]
    with open(output_path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(cases)
