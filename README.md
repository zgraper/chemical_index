# Chemical Index

A Python proof-of-concept for indexing and retrieving chemical product label metadata for Cornbelt AI.

## Overview

The system ingests EPA-registered pesticide/chemical product metadata, stores it in a versioned SQLite index, and provides ranked search retrieval so farmers can quickly find label information.

## Features

- **Versioned metadata index** – never overwrites; every change creates a new version row
- **Products tracked by EPA registration number**
- **Comprehensive product fields**: EPA reg no, product name, alternate names, registrant, active ingredients, label stamped date, source URL, PDF URL, federal/state status flags, source hash, and more
- **`index_runs` table** tracks every build/sync job for auditability
- **Search modes**:
  - Exact EPA registration number
  - Exact product name
  - Fuzzy product name (token-overlap scoring)
  - Active ingredient
  - Registrant
- **Ranked results** with a plain-English `explain` field
- **Retrieval evaluation harness** – reads JSON test cases, computes top-1 accuracy, top-3 accuracy, mean reciprocal rank (MRR), exports JSON and CSV reports
- **FastAPI HTTP server** for programmatic access
- **Safety layer** – strips recommendation-style language and appends a regulatory disclaimer to all chemical-related output

---

## Setup

### Requirements

- Python 3.9 or later
- pip

### Install the package

```bash
# Clone the repo (if you haven't already)
git clone https://github.com/zgraper/chemical_index.git
cd chemical_index

# Create and activate a virtual environment (recommended)
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate

# Install the package in editable mode
pip install -e .
```

---

## Running the Tests

### Install test dependencies

```bash
pip install -e ".[test]"
```

This installs both `pytest` and `httpx` (required for the FastAPI test client).

### Run the full test suite

```bash
python -m pytest
```

All tests are discovered automatically from the `tests/` directory (configured in `pyproject.toml`).

### Run a specific test file

```bash
python -m pytest tests/test_search.py
python -m pytest tests/test_api.py
python -m pytest tests/test_cli.py
```

### Run with verbose output

```bash
python -m pytest -v
```

### Expected output

```
tests/test_api.py ............................
tests/test_cli.py ............
tests/test_hashing.py ...
tests/test_index.py .......
tests/test_label_retrieval.py .........s...........
tests/test_normalize.py .............
tests/test_pdf_parser.py .......
tests/test_retrieval.py ..........
tests/test_safety.py ............................
tests/test_schema.py ...
tests/test_search.py ............
tests/test_section_extractor.py .............
tests/test_sync_report.py .............
tests/test_validate.py ........
```

All tests use isolated `tmp_path` fixtures or mocks – no external services or real PDFs are required.

---

## CLI Usage

### 1. Build the index

```bash
# Build from the included sample data
chemical-index build-index --source data/products.json --db index.sqlite
```

### 2. Sync (incremental update)

Only inserts new version rows when source data has changed:

```bash
chemical-index sync-index --source data/products.json --db index.sqlite
```

### 3. Search

```bash
# Fuzzy search (default)
chemical-index search "glyphosate" --db index.sqlite

# Exact EPA registration number
chemical-index search "524-308" --db index.sqlite --mode epa_reg_no

# Fuzzy product name, top 5
chemical-index search "Roundup" --db index.sqlite --mode fuzzy --top 5

# Active ingredient
chemical-index search "Chlorpyrifos" --db index.sqlite --mode active_ingredient

# Registrant
chemical-index search "Corteva" --db index.sqlite --mode registrant
```

### 4. End-to-end demo

Runs a full search → select top match → display label info flow:

```bash
chemical-index demo "Roundup" --db index.sqlite
chemical-index demo "Roundup" --db index.sqlite --json-output
```

### 5. Evaluate retrieval quality

```bash
chemical-index evaluate \
  --test-cases tests/data/test_cases.json \
  --db index.sqlite \
  --out-json evaluation.json \
  --out-csv evaluation.csv
```

### 6. Validate the database

```bash
chemical-index validate --db index.sqlite
```

### 7. Extract label sections from a PDF

```bash
# Fetch PDF from the stored pdf_url and extract sections
chemical-index extract-label 524-308 --db index.sqlite

# Use a local PDF file instead
chemical-index extract-label 524-308 --db index.sqlite --pdf /path/to/label.pdf
```

---

## API Server

Start the FastAPI server:

```bash
chemical-index serve --db index.sqlite --host 127.0.0.1 --port 8000
```

Interactive API docs are available at `http://127.0.0.1:8000/docs` once the server is running.

### Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/search?q=<query>` | Ranked product search |
| `GET` | `/product/{epa_reg_no}` | Single product metadata |
| `GET` | `/label/{epa_reg_no}` | Full label (metadata + extracted sections) |
| `GET` | `/label/{epa_reg_no}/sections` | Extracted sections only |

Query parameters for `/search`:
- `q` – search string (required)
- `mode` – one of `fuzzy`, `epa_reg_no`, `product_name`, `active_ingredient`, `registrant` (default: `fuzzy`)
- `top` – max results to return, 1–100 (default: `10`)

---

## Source JSON Format

A source file is a JSON array of product objects. Every field is optional except `epa_reg_no`:

```json
[
  {
    "epa_reg_no": "524-308",
    "product_name": "Roundup Original",
    "alternate_names": ["Roundup", "Roundup Conc"],
    "registrant": "Bayer CropScience",
    "active_ingredients": [{"name": "Glyphosate", "pct": 41.0}],
    "label_stamped_date": "2022-03-15",
    "source_url": "https://example.com/product/524-308",
    "pdf_url": "https://example.com/labels/524-308.pdf",
    "federal_status": "registered",
    "state_status_flags": {"CA": "registered", "WA": "registered"}
  }
]
```

A five-product sample is included at `data/products.json`.

## Test Cases JSON Format

```json
[
  {
    "query": "Roundup",
    "mode": "fuzzy",
    "expected_epa_reg_no": "524-308"
  }
]
```

A complete set of test cases for the sample data is at `tests/data/test_cases.json`.
