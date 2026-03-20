"""CLI for the chemical label metadata index."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import click

from .build_index import build_index
from .sync_index import sync_index
from .search import search, MODES
from .retrieval import run_evaluation, export_json, export_csv


@click.group()
def cli() -> None:
    """Chemical label metadata index – Cornbelt AI."""


@cli.command("build-index")
@click.option(
    "--source",
    required=True,
    type=click.Path(exists=True, dir_okay=False),
    help="Path to a JSON source file (array of product objects).",
)
@click.option(
    "--db",
    default="index.sqlite",
    show_default=True,
    help="Path to the SQLite database file.",
)
@click.option("--notes", default=None, help="Optional notes for this run.")
def cmd_build_index(source: str, db: str, notes: str | None) -> None:
    """Build (or rebuild) the index from SOURCE."""
    summary = build_index(source, db, notes=notes)
    click.echo(json.dumps(summary, indent=2))


@cli.command("sync-index")
@click.option(
    "--source",
    required=True,
    type=click.Path(exists=True, dir_okay=False),
    help="Path to a JSON source file (array of product objects).",
)
@click.option(
    "--db",
    default="index.sqlite",
    show_default=True,
    help="Path to the SQLite database file.",
)
@click.option("--notes", default=None, help="Optional notes for this run.")
def cmd_sync_index(source: str, db: str, notes: str | None) -> None:
    """Sync the index from SOURCE, inserting new versions only when data changed."""
    summary = sync_index(source, db, notes=notes)
    click.echo(json.dumps(summary, indent=2))


@cli.command("search")
@click.argument("query")
@click.option(
    "--db",
    default="index.sqlite",
    show_default=True,
    help="Path to the SQLite database file.",
)
@click.option(
    "--mode",
    default="fuzzy",
    show_default=True,
    type=click.Choice(list(MODES), case_sensitive=False),
    help="Search mode.",
)
@click.option(
    "--top",
    default=10,
    show_default=True,
    type=int,
    help="Maximum number of results to return.",
)
def cmd_search(query: str, db: str, mode: str, top: int) -> None:
    """Search the index for QUERY."""
    db_path = Path(db)
    if not db_path.exists():
        click.echo(f"Database not found: {db}", err=True)
        sys.exit(1)

    results = search(query, db_path, mode=mode, top=top)
    if not results:
        click.echo("No results found.")
        return

    for i, r in enumerate(results, start=1):
        click.echo(
            f"[{i}] EPA={r.get('epa_reg_no')}  "
            f"Name={r.get('product_name')}  "
            f"Score={r.get('score')}  "
            f"Explain: {r.get('explain')}"
        )


@cli.command("evaluate")
@click.option(
    "--test-cases",
    required=True,
    type=click.Path(exists=True, dir_okay=False),
    help="Path to a JSON file of test cases.",
)
@click.option(
    "--db",
    default="index.sqlite",
    show_default=True,
    help="Path to the SQLite database file.",
)
@click.option(
    "--out-json",
    default="evaluation.json",
    show_default=True,
    help="Output JSON report path.",
)
@click.option(
    "--out-csv",
    default="evaluation.csv",
    show_default=True,
    help="Output CSV report path.",
)
@click.option(
    "--top",
    default=10,
    show_default=True,
    type=int,
    help="Retrieve up to TOP results per query.",
)
def cmd_evaluate(
    test_cases: str,
    db: str,
    out_json: str,
    out_csv: str,
    top: int,
) -> None:
    """Evaluate retrieval quality against a test-case file."""
    db_path = Path(db)
    if not db_path.exists():
        click.echo(f"Database not found: {db}", err=True)
        sys.exit(1)

    evaluation = run_evaluation(test_cases, db_path, top=top)
    metrics = evaluation["metrics"]

    click.echo(
        f"Results: total={metrics['total_cases']}  "
        f"top-1={metrics['top_1_accuracy']:.2%}  "
        f"top-3={metrics['top_3_accuracy']:.2%}  "
        f"MRR={metrics['mrr']:.4f}"
    )

    export_json(evaluation, out_json)
    export_csv(evaluation, out_csv)
    click.echo(f"Reports written to {out_json} and {out_csv}")
