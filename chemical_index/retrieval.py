"""Retrieval testing harness.

Test case JSON format::

    [
      {
        "query": "Roundup",
        "mode": "fuzzy",
        "expected_epa_reg_no": "524-308"
      },
      ...
    ]

Metrics computed:
  - top_1_accuracy  – fraction of queries where correct answer is rank 1
  - top_3_accuracy  – fraction of queries where correct answer is in top 3
  - mrr             – mean reciprocal rank (1/rank of first correct answer, or 0)
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from .search import search


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


def run_evaluation(
    test_cases_path: str | Path,
    db_path: str | Path,
    *,
    top: int = 10,
) -> dict[str, Any]:
    """
    Run all test cases and return a result dict.

    The returned dict contains:
    - ``metrics``: top_1_accuracy, top_3_accuracy, mrr
    - ``cases``: per-query details (query, mode, expected, top results, rr)
    """
    path = Path(test_cases_path)
    with path.open("r", encoding="utf-8") as fh:
        cases_raw: list[dict] = json.load(fh)

    case_results = []
    rr_values = []
    top1_hits = 0
    top3_hits = 0

    for case in cases_raw:
        query = case.get("query", "")
        mode = case.get("mode", "fuzzy")
        expected = case.get("expected_epa_reg_no", "")

        results = search(query, db_path, mode=mode, top=top)

        rr = _reciprocal_rank(results, expected)
        t1 = _in_top_k(results, expected, 1)
        t3 = _in_top_k(results, expected, 3)

        rr_values.append(rr)
        if t1:
            top1_hits += 1
        if t3:
            top3_hits += 1

        case_results.append(
            {
                "query": query,
                "mode": mode,
                "expected_epa_reg_no": expected,
                "reciprocal_rank": round(rr, 4),
                "top_1_hit": t1,
                "top_3_hit": t3,
                "top_results": [
                    {
                        "rank": i + 1,
                        "epa_reg_no": r.get("epa_reg_no"),
                        "product_name": r.get("product_name"),
                        "score": r.get("score"),
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
    }

    return {"metrics": metrics, "cases": case_results}


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
        "reciprocal_rank",
        "top_1_hit",
        "top_3_hit",
    ]
    with open(output_path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(cases)
