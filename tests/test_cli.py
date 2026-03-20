"""Tests for CLI commands."""

import json
import pytest
from pathlib import Path
from click.testing import CliRunner

from chemical_index.cli import cli


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
    }
]


@pytest.fixture
def env(tmp_path):
    runner = CliRunner()
    source_file = tmp_path / "products.json"
    source_file.write_text(json.dumps(SAMPLE))

    db_path = tmp_path / "index.sqlite"

    cases_file = tmp_path / "test_cases.json"
    cases_file.write_text(json.dumps(TEST_CASES))

    return runner, str(source_file), str(db_path), str(cases_file), tmp_path


def test_build_index_command(env):
    runner, source, db, _, _ = env
    result = runner.invoke(cli, ["build-index", "--source", source, "--db", db])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["records_inserted"] == 2
    assert data["mode"] == "build"


def test_sync_index_command(env):
    runner, source, db, _, _ = env
    runner.invoke(cli, ["build-index", "--source", source, "--db", db])
    result = runner.invoke(cli, ["sync-index", "--source", source, "--db", db])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["records_inserted"] == 0  # no changes
    assert data["mode"] == "sync"


def test_search_command(env):
    runner, source, db, _, _ = env
    runner.invoke(cli, ["build-index", "--source", source, "--db", db])
    result = runner.invoke(cli, ["search", "524-308", "--db", db, "--mode", "epa_reg_no"])
    assert result.exit_code == 0, result.output
    assert "524-308" in result.output


def test_search_command_fuzzy(env):
    runner, source, db, _, _ = env
    runner.invoke(cli, ["build-index", "--source", source, "--db", db])
    result = runner.invoke(cli, ["search", "roundup", "--db", db, "--mode", "fuzzy"])
    assert result.exit_code == 0, result.output
    assert "Roundup" in result.output


def test_search_command_no_db(env, tmp_path):
    runner, _, _, _, _ = env
    result = runner.invoke(cli, ["search", "test", "--db", str(tmp_path / "missing.sqlite")])
    assert result.exit_code == 1


def test_evaluate_command(env):
    runner, source, db, cases, tmp_path = env
    runner.invoke(cli, ["build-index", "--source", source, "--db", db])
    out_json = str(tmp_path / "eval.json")
    out_csv = str(tmp_path / "eval.csv")
    result = runner.invoke(
        cli,
        [
            "evaluate",
            "--test-cases", cases,
            "--db", db,
            "--out-json", out_json,
            "--out-csv", out_csv,
        ],
    )
    assert result.exit_code == 0, result.output
    assert "top-1" in result.output
    assert Path(out_json).exists()
    assert Path(out_csv).exists()
