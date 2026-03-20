"""CLI for the chemical label metadata index."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import click

from .build_index import build_index
from .sync_index import sync_index
from .search import search, MODES
from .retrieval import run_evaluation, export_json, export_csv, format_terminal_summary
from .validate import validate_database
from .label_retrieval import extract_label
from .safety import DISCLAIMER


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

    click.echo(format_terminal_summary(evaluation))

    export_json(evaluation, out_json)
    export_csv(evaluation, out_csv)
    click.echo(f"Reports written to {out_json} and {out_csv}")


@cli.command("validate")
@click.option(
    "--db",
    default="index.sqlite",
    show_default=True,
    help="Path to the SQLite database file.",
)
def cmd_validate(db: str) -> None:
    """Check database integrity and print a validation report."""
    db_path = Path(db)
    if not db_path.exists():
        click.echo(f"Database not found: {db}", err=True)
        sys.exit(1)

    report = validate_database(db_path)
    click.echo(json.dumps(report, indent=2))
    if not report["valid"]:
        sys.exit(1)


@cli.command("serve")
@click.option(
    "--db",
    default="index.sqlite",
    show_default=True,
    help="Path to the SQLite database file.",
)
@click.option("--host", default="127.0.0.1", show_default=True, help="Bind host.")
@click.option("--port", default=8000, show_default=True, type=int, help="Bind port.")
@click.option(
    "--cache-dir",
    default="data/labels",
    show_default=True,
    help="Directory for cached label PDFs.",
)
def cmd_serve(db: str, host: str, port: int, cache_dir: str) -> None:
    """Start the FastAPI HTTP server."""
    import os

    try:
        import uvicorn
    except ImportError:
        click.echo("uvicorn is required to run the server. Install it with: pip install uvicorn", err=True)
        sys.exit(1)

    db_path = Path(db)
    if not db_path.exists():
        click.echo(f"Database not found: {db}", err=True)
        sys.exit(1)

    os.environ["CHEMICAL_INDEX_DB"] = str(db_path.resolve())
    os.environ["CHEMICAL_INDEX_CACHE_DIR"] = str(Path(cache_dir).resolve())
    click.echo(f"Starting API server on http://{host}:{port}  (db={db_path.resolve()})")
    uvicorn.run("chemical_index.api:app", host=host, port=port)


@cli.command("extract-label")
@click.argument("epa_reg_no")
@click.option(
    "--db",
    default="index.sqlite",
    show_default=True,
    help="Path to the SQLite database file.",
)
@click.option(
    "--cache-dir",
    default="data/labels",
    show_default=True,
    help="Directory for cached label PDFs.",
)
@click.option(
    "--pdf",
    default=None,
    type=click.Path(exists=True, dir_okay=False),
    help="Use a local PDF file instead of downloading from the database.",
)
def cmd_extract_label(
    epa_reg_no: str,
    db: str,
    cache_dir: str,
    pdf: str | None,
) -> None:
    """Extract sections from the label PDF for EPA_REG_NO."""
    db_path = Path(db)
    if pdf is None and not db_path.exists():
        click.echo(f"Database not found: {db}", err=True)
        sys.exit(1)

    result = extract_label(
        epa_reg_no,
        db_path,
        cache_dir=cache_dir,
        pdf_path=pdf,
    )
    click.echo(json.dumps(result, indent=2, ensure_ascii=False))


# ---------------------------------------------------------------------------
# Demo command helpers
# ---------------------------------------------------------------------------

_SECTION_LABELS: dict[str, str] = {
    "directions_for_use": "Directions for Use",
    "restrictions": "Restrictions",
    "ppe": "Personal Protective Equipment",
    "rei": "Restricted-Entry Interval",
    "phi": "Pre-Harvest Interval",
    "environmental_hazards": "Environmental Hazards",
    "spray_drift": "Spray Drift",
    "agricultural_use": "Agricultural Use Requirements",
}

_BAR = "=" * 62
_SEP = "-" * 62


def _fmt_terminal(query: str, results: list[dict], label_data: dict) -> str:
    """Build a clean terminal display string for the demo output."""
    lines: list[str] = []

    lines.append(_BAR)
    lines.append("  CHEMICAL LABEL DEMO – Cornbelt AI")
    lines.append(_BAR)
    lines.append(f'\nSearching for: "{query}"\n')

    # --- Top results table ---
    lines.append("  Top Matches")
    lines.append("  " + _SEP)
    lines.append(f"  {'#':<4} {'Score':<8} {'EPA Reg No':<16} Product Name")
    lines.append("  " + _SEP)
    for i, r in enumerate(results, start=1):
        lines.append(
            f"  {i:<4} {r.get('score', 0):<8.4f} {r.get('epa_reg_no', ''):<16} {r.get('product_name', '')}"
        )
    lines.append("")

    # --- Selected match ---
    top = results[0]
    lines.append(
        f"  Using top match: #{1} – {top.get('product_name')} (EPA {top.get('epa_reg_no')})"
    )
    lines.append("")

    # --- Product metadata ---
    lines.append("  Product Metadata")
    lines.append("  " + _SEP)
    lines.append(f"  EPA Reg No:   {top.get('epa_reg_no', 'N/A')}")
    lines.append(f"  Product Name: {top.get('product_name', 'N/A')}")
    lines.append(f"  Registrant:   {top.get('registrant', 'N/A')}")
    lines.append(f"  Status:       {top.get('federal_status', 'N/A')}")
    lines.append(f"  Label Date:   {label_data.get('label_date') or 'N/A'}")
    ais = top.get("active_ingredients") or []
    if ais:
        lines.append("  Active Ingredients:")
        for ai in ais:
            if isinstance(ai, dict):
                pct = ai.get("pct")
                pct_str = f"  {pct}%" if pct is not None else ""
                lines.append(f"    • {ai.get('name', '')}{pct_str}")
            else:
                lines.append(f"    • {ai}")
    lines.append("")

    # --- Label sections ---
    sections: dict[str, Any] = label_data.get("sections") or {}
    if any(v for v in sections.values()):
        lines.append("  Label Sections")
        lines.append("  " + _SEP)
        for key, heading in _SECTION_LABELS.items():
            body = sections.get(key)
            if body:
                lines.append(f"\n  [{heading}]")
                # Indent each line of the section body
                for ln in body.splitlines():
                    lines.append(f"    {ln}")
        lines.append("")

    label_error = label_data.get("error")
    if label_error:
        lines.append(f"  Note: {label_error}")
        lines.append("")

    # --- Disclaimer ---
    lines.append("  ⚠  DISCLAIMER")
    lines.append("  " + _SEP)
    disclaimer = label_data.get("disclaimer") or DISCLAIMER
    lines.append(f"  {disclaimer}")
    lines.append("")
    lines.append(_BAR)

    return "\n".join(lines)


def _fmt_json(query: str, results: list[dict], label_data: dict) -> str:
    """Return structured JSON for the demo output."""
    output: dict[str, Any] = {
        "query": query,
        "top_results": [
            {
                "rank": i + 1,
                "epa_reg_no": r.get("epa_reg_no"),
                "product_name": r.get("product_name"),
                "score": r.get("score"),
                "explain": r.get("explain"),
            }
            for i, r in enumerate(results)
        ],
        "selected": {
            "epa_reg_no": results[0].get("epa_reg_no"),
            "product_name": results[0].get("product_name"),
            "registrant": results[0].get("registrant"),
            "federal_status": results[0].get("federal_status"),
            "active_ingredients": results[0].get("active_ingredients"),
            "label_date": label_data.get("label_date"),
            "sections": label_data.get("sections"),
        },
        "disclaimer": label_data.get("disclaimer") or DISCLAIMER,
    }
    if label_data.get("error"):
        output["error"] = label_data["error"]
    return json.dumps(output, indent=2, ensure_ascii=False)


@cli.command("demo")
@click.argument("query")
@click.option(
    "--db",
    default="index.sqlite",
    show_default=True,
    help="Path to the SQLite database file.",
)
@click.option(
    "--cache-dir",
    default="data/labels",
    show_default=True,
    help="Directory for cached label PDFs.",
)
@click.option(
    "--top",
    default=5,
    show_default=True,
    type=int,
    help="Maximum number of search results to display.",
)
@click.option(
    "--json-output",
    "as_json",
    is_flag=True,
    default=False,
    help="Output structured JSON instead of a terminal display.",
)
def cmd_demo(query: str, db: str, cache_dir: str, top: int, as_json: bool) -> None:
    """Run an end-to-end demo: search → select top match → show label info.

    QUERY is the product name to search for (e.g. "Roundup PowerMAX").
    """
    db_path = Path(db)
    if not db_path.exists():
        click.echo(f"Database not found: {db}", err=True)
        sys.exit(1)

    # Step 1 & 2: search and show results
    results = search(query, db_path, mode="fuzzy", top=top)
    if not results:
        click.echo(f'No products found for query: "{query}"', err=True)
        sys.exit(1)

    # Step 3: select top match
    top_match = results[0]
    epa_reg_no: str = top_match.get("epa_reg_no", "")

    # Step 4 & 5: retrieve label metadata and sections
    label_data = extract_label(epa_reg_no, db_path, cache_dir=cache_dir)

    # Step 6: output
    if as_json:
        click.echo(_fmt_json(query, results, label_data))
    else:
        click.echo(_fmt_terminal(query, results, label_data))
