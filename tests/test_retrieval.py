"""Tests for retrieval evaluation harness."""

import json
import pytest
from pathlib import Path

from chemical_index.build_index import build_index
from chemical_index.retrieval import (
    run_evaluation,
    export_json,
    export_csv,
    format_terminal_summary,
    AMBIGUITY_THRESHOLD,
)


SAMPLE = [
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
]

TEST_CASES = [
    {
        "query": "524-308",
        "mode": "epa_reg_no",
        "expected_epa_reg_no": "524-308",
    },
    {
        "query": "Roundup Original",
        "mode": "product_name",
        "expected_epa_reg_no": "524-308",
    },
    {
        "query": "roundup",
        "mode": "fuzzy",
        "expected_epa_reg_no": "524-308",
    },
    {
        "query": "Glyphosate",
        "mode": "active_ingredient",
        "expected_epa_reg_no": "524-308",
    },
]

# Golden format: uses match_type + optional expected_product_name
GOLDEN_CASES = [
    {
        "query": "524-308",
        "expected_epa_reg_no": "524-308",
        "expected_product_name": "Roundup Original",
        "match_type": "epa_reg_no",
    },
    {
        "query": "Roundup Original",
        "expected_epa_reg_no": "524-308",
        "expected_product_name": "Roundup Original",
        "match_type": "product_name",
    },
    {
        "query": "roundup",
        "expected_epa_reg_no": "524-308",
        "match_type": "fuzzy",
    },
    {
        "query": "Glyphosate",
        "expected_epa_reg_no": "524-308",
        "match_type": "active_ingredient",
    },
]


@pytest.fixture
def setup(tmp_path):
    db_path = tmp_path / "test.sqlite"
    build_index(SAMPLE, db_path)

    cases_path = tmp_path / "test_cases.json"
    cases_path.write_text(json.dumps(TEST_CASES))

    return db_path, cases_path, tmp_path


@pytest.fixture
def golden_setup(tmp_path):
    db_path = tmp_path / "test.sqlite"
    build_index(SAMPLE, db_path)

    cases_path = tmp_path / "goldens.json"
    cases_path.write_text(json.dumps(GOLDEN_CASES))

    return db_path, cases_path, tmp_path


def test_run_evaluation_metrics(setup):
    db_path, cases_path, _ = setup
    evaluation = run_evaluation(cases_path, db_path)

    metrics = evaluation["metrics"]
    assert metrics["total_cases"] == 4
    assert 0.0 <= metrics["top_1_accuracy"] <= 1.0
    assert 0.0 <= metrics["top_3_accuracy"] <= 1.0
    assert 0.0 <= metrics["mrr"] <= 1.0
    # The first two queries are exact matches – should be perfect
    assert metrics["top_1_accuracy"] >= 0.5


def test_run_evaluation_failure_count(setup):
    db_path, cases_path, tmp_path = setup
    # Add a case that will fail to find anything
    failing_cases = TEST_CASES + [
        {"query": "NONEXISTENT-99999", "mode": "epa_reg_no", "expected_epa_reg_no": "NONEXISTENT"}
    ]
    fail_path = tmp_path / "fail_cases.json"
    fail_path.write_text(json.dumps(failing_cases))

    evaluation = run_evaluation(fail_path, db_path)
    metrics = evaluation["metrics"]
    assert metrics["failure_count"] >= 1


def test_run_evaluation_ambiguity_count(setup):
    db_path, cases_path, _ = setup
    evaluation = run_evaluation(cases_path, db_path)
    metrics = evaluation["metrics"]
    # ambiguity_count must be a non-negative integer
    assert isinstance(metrics["ambiguity_count"], int)
    assert metrics["ambiguity_count"] >= 0


def test_run_evaluation_case_results(setup):
    db_path, cases_path, _ = setup
    evaluation = run_evaluation(cases_path, db_path)

    assert len(evaluation["cases"]) == 4
    first = evaluation["cases"][0]
    assert first["query"] == "524-308"
    assert first["top_1_hit"] is True
    assert first["reciprocal_rank"] == 1.0
    assert first["found"] is True
    assert first["rank_of_expected"] == 1


def test_run_evaluation_case_has_ambiguous_field(setup):
    db_path, cases_path, _ = setup
    evaluation = run_evaluation(cases_path, db_path)
    for case in evaluation["cases"]:
        assert "ambiguous" in case
        assert isinstance(case["ambiguous"], bool)


def test_run_evaluation_top_results_have_match_source(setup):
    db_path, cases_path, _ = setup
    evaluation = run_evaluation(cases_path, db_path)
    first = evaluation["cases"][0]
    assert first["top_results"]
    r1 = first["top_results"][0]
    assert "match_source" in r1
    assert r1["match_source"] == "exact_epa_reg_no"


def test_run_evaluation_golden_format(golden_setup):
    """Test that match_type and expected_product_name are handled."""
    db_path, cases_path, _ = golden_setup
    evaluation = run_evaluation(cases_path, db_path)

    metrics = evaluation["metrics"]
    assert metrics["total_cases"] == 4
    assert metrics["top_1_accuracy"] >= 0.5

    # expected_product_name should be preserved in case results
    first = evaluation["cases"][0]
    assert first["expected_product_name"] == "Roundup Original"
    # mode should be populated from match_type
    assert first["mode"] == "epa_reg_no"


def test_format_terminal_summary(setup):
    db_path, cases_path, _ = setup
    evaluation = run_evaluation(cases_path, db_path)
    summary = format_terminal_summary(evaluation)

    assert "RETRIEVAL EVALUATION SUMMARY" in summary
    assert "Top-1 accuracy" in summary
    assert "Top-3 accuracy" in summary
    assert "MRR" in summary
    assert "Failures" in summary
    assert "Ambiguous" in summary
    # Each query should appear in the summary
    assert "524-308" in summary


def test_export_json(setup):
    db_path, cases_path, tmp_path = setup
    evaluation = run_evaluation(cases_path, db_path)

    out = tmp_path / "eval.json"
    export_json(evaluation, out)
    assert out.exists()

    data = json.loads(out.read_text())
    assert "metrics" in data
    assert "cases" in data
    # New metrics fields present
    assert "failure_count" in data["metrics"]
    assert "ambiguity_count" in data["metrics"]


def test_export_csv(setup):
    db_path, cases_path, tmp_path = setup
    evaluation = run_evaluation(cases_path, db_path)

    out = tmp_path / "eval.csv"
    export_csv(evaluation, out)
    assert out.exists()

    lines = out.read_text().splitlines()
    assert lines[0].startswith("query")
    assert len(lines) == 5  # header + 4 cases
    # New columns present in header
    assert "found" in lines[0]
    assert "ambiguous" in lines[0]
