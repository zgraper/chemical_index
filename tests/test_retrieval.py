"""Tests for retrieval evaluation harness."""

import json
import pytest
from pathlib import Path

from chemical_index.build_index import build_index
from chemical_index.retrieval import run_evaluation, export_json, export_csv


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


@pytest.fixture
def setup(tmp_path):
    db_path = tmp_path / "test.sqlite"
    build_index(SAMPLE, db_path)

    cases_path = tmp_path / "test_cases.json"
    cases_path.write_text(json.dumps(TEST_CASES))

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


def test_run_evaluation_case_results(setup):
    db_path, cases_path, _ = setup
    evaluation = run_evaluation(cases_path, db_path)

    assert len(evaluation["cases"]) == 4
    first = evaluation["cases"][0]
    assert first["query"] == "524-308"
    assert first["top_1_hit"] is True
    assert first["reciprocal_rank"] == 1.0


def test_export_json(setup):
    db_path, cases_path, tmp_path = setup
    evaluation = run_evaluation(cases_path, db_path)

    out = tmp_path / "eval.json"
    export_json(evaluation, out)
    assert out.exists()

    data = json.loads(out.read_text())
    assert "metrics" in data
    assert "cases" in data


def test_export_csv(setup):
    db_path, cases_path, tmp_path = setup
    evaluation = run_evaluation(cases_path, db_path)

    out = tmp_path / "eval.csv"
    export_csv(evaluation, out)
    assert out.exists()

    lines = out.read_text().splitlines()
    assert lines[0].startswith("query")
    assert len(lines) == 5  # header + 4 cases
