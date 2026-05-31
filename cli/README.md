# Excel Ingestion CLI

Alternative frontend for the backend API. The backend remains the source of
truth for workbook parsing, mapping, extraction, validation, and caching.

## Prereqs
- Python 3.12+
- Backend running and reachable
  - set `BACKEND_URL` or pass `--backend-url`
- Install CLI deps:
  - `python3 -m pip install -r cli/requirements.txt`

## Commands
```bash
# health
python3 cli/excel_ingest_cli.py health

# schemas
python3 cli/excel_ingest_cli.py schemas list
python3 cli/excel_ingest_cli.py schemas create --schema-file ./schema.json
python3 cli/excel_ingest_cli.py schemas update --schema-id scm_123 --schema-file ./schema.json
python3 cli/excel_ingest_cli.py schemas delete --schema-id scm_123

# workbook schema summary from backend
python3 cli/excel_ingest_cli.py excel-schema \
  --excel-file ./myfile.xlsx \
  --out ./artifacts/excel_schema.json

# ingest (writes JSON artifacts + replay script)
python3 cli/excel_ingest_cli.py ingest \
  --schema-file ./schema.json \
  --excel-file ./myfile.xlsx \
  --out-dir ./artifacts

# optional extras
python3 cli/excel_ingest_cli.py ingest \
  --schema-file ./schema.json \
  --excel-file ./myfile.xlsx \
  --out-dir ./artifacts \
  --save-ingest-output \
  --save-manifest
```

## Ingest Artifacts
`ingest` writes these files by default:
- `excel_schema.json` - backend `/excel-schema` response
- `run_ingest.py` - backend-provided replay code (falls back to local template if absent)

Optional flags:
- `--save-ingest-output` -> also writes `ingest_output.json`
- `--save-manifest` -> also writes `ingest_manifest.json`

## Schema JSON shape
This file is sent directly to the backend.

```json
{
  "name": "Acme Q1 Report",
  "fields": [
    {
      "name": "supplier_name",
      "field_type": "string",
      "description": "Legal supplier name"
    },
    {
      "name": "weight_tonnes",
      "field_type": "number",
      "description": "Shipment weight"
    }
  ]
}
```
