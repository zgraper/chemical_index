The concept is that Cornbelt AI will be able to pull information from labels and give it to farmers.  We figure the best way to do this is create an index, then pull the label if there is a query regarding it.

## Project Architecture

This is a single Python package (`chemical_index`) installed via `pip install -e .`. All commands are exposed through the `chemical-index` CLI entry point.

### Module Map

| Module | Purpose |
|--------|---------|
| `schema.py` | SQLite schema creation (`product_versions`, `index_runs` tables) and migrations |
| `normalize.py` | Canonicalises raw source dicts into structured product records |
| `hashing.py` | SHA-256 content hashing for change detection in sync runs |
| `build_index.py` | Non-destructive full rebuild of the index from a JSON source |
| `sync_index.py` | Incremental sync – only inserts new version rows when data has changed |
| `search.py` | Five search modes: `epa_reg_no`, `product_name`, `fuzzy`, `active_ingredient`, `registrant` |
| `retrieval.py` | Evaluation harness – runs test cases and reports top-1/top-3 accuracy and MRR |
| `label_retrieval.py` | Fetches PDF labels (with local caching) and extracts structured sections |
| `pdf_parser.py` | `pypdf`-based text extraction and whitespace normalisation |
| `section_extractor.py` | Rule-based extraction of labelled sections (directions for use, PPE, REI, etc.) |
| `validate.py` | Database integrity checks (duplicate `is_latest` rows, orphan run IDs, duplicate hashes) |
| `safety.py` | Strips recommendation-style language and appends a regulatory disclaimer |
| `api.py` | FastAPI app exposing `/search`, `/product/{epa_reg_no}`, `/label/{epa_reg_no}`, `/label/{epa_reg_no}/sections` |
| `cli.py` | Click CLI: `build-index`, `sync-index`, `search`, `evaluate`, `validate`, `serve`, `extract-label`, `demo` |

### Key Data Flows

1. **Ingestion**: `build_index` / `sync_index` → `normalize` → `hash` → SQLite `product_versions`
2. **Search**: CLI/API → `search.py` → SQLite query → ranked result list with `explain` field
3. **Label retrieval**: `label_retrieval.py` → database lookup → PDF download (cached) → `pdf_parser` → `section_extractor` → structured sections dict
4. **Evaluation**: `retrieval.py` reads JSON test cases → runs search → computes MRR/accuracy metrics → exports JSON + CSV reports

### Test Infrastructure

- All tests are under `tests/` and use `pytest` with `tmp_path` fixtures (no external services needed)
- `tests/data/sample_products.json` – five sample EPA-registered products (also copied to `data/products.json` for CLI quickstart)
- `tests/data/test_cases.json` – retrieval golden test cases for those five products
- FastAPI tests use `httpx` via `TestClient` with a monkeypatched `CHEMICAL_INDEX_DB` env var
- PDF-dependent tests are skipped or mocked so the suite runs without real PDF files

### Adding New Source Data

Replace or extend `data/products.json` with real EPA product records, then run:

```bash
chemical-index build-index --source data/products.json --db index.sqlite
```

For ongoing updates use `sync-index` so previous version history is preserved.
