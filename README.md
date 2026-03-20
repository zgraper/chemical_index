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
  - Fuzzy product name (trigram-style token overlap)
  - Active ingredient
  - Registrant
- **Ranked results** with a plain-English `explain` field
- **Retrieval testing harness** – reads JSON test cases, computes top-1 accuracy, top-3 accuracy, mean reciprocal rank (MRR), exports JSON and CSV reports

## Installation

```bash
pip install -e .
```

## CLI Usage

```bash
# Build index from a JSON source file
chemical-index build-index --source data/products.json --db index.sqlite

# Sync (incremental update – only inserts new versions when data changed)
chemical-index sync-index --source data/products.json --db index.sqlite

# Search
chemical-index search "glyphosate" --db index.sqlite
chemical-index search "524-308" --db index.sqlite --mode epa_reg_no
chemical-index search "Roundup" --db index.sqlite --mode fuzzy --top 5

# Evaluate retrieval quality
chemical-index evaluate --test-cases tests/data/test_cases.json --db index.sqlite
```

## Source JSON Format

A source file is a JSON array of product objects.  Every field is optional except `epa_reg_no`:

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
