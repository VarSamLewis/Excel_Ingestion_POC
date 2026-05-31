"""FastAPI application — routes only, no business logic.

All routes except /health require Azure AD JWT authentication (when enabled).
Schema routes are scoped to the requesting user via the `oid` claim.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from fastapi import Depends, FastAPI, File, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware

from backend.config import settings
from backend.models import (
    ExcelSchemaResponse,
    ExcelMapping,
    IngestResponse,
    SchemaDefinition,
    SheetResult,
)
from backend.excel_processor import (
    compute_file_hash,
    compute_schema_hash,
    get_sheet_names,
    summarise_sheet,
)
from backend.llm.mapper import infer_mapping
from backend.llm.validator import validate_extraction
from backend.extractor.engine import extract
from backend.cache import get_store
from backend.file_store import get_file_store
from backend.observability import configure_logging, OperationTimer, log_event

# Configure structured logging (JSON to stdout + optional Log Analytics)
configure_logging()
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Excel Ingestion API",
    version="1.0.0",
    description="Flexible Excel ingestion powered by GPT-4o mapping and deterministic extraction.",
)

# ── CORS ────────────────────────────────────────────────────────────

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Shared state ────────────────────────────────────────────────────

_jwks_client = None
_store = None
_file_store = None


def _build_replay_code(
    *,
    backend_base_url: str,
    schema_name: str,
    schema_json: dict,
    selected_sheets: str,
) -> str:
    """Build runnable Python code that replays the ingest request."""
    script = f"""#!/usr/bin/env python3
import json
from pathlib import Path

import httpx

BACKEND_URL = {backend_base_url!r}
SCHEMA_NAME = {schema_name!r}
SCHEMA_JSON = {json.dumps(schema_json, indent=2)}
SELECTED_SHEETS = {selected_sheets!r}
EXCEL_PATH = Path("input.xlsx")
OUT_PATH = Path("ingest_output.json")


def main() -> int:
    params = {{
        "schema_name": SCHEMA_NAME,
        "schema_json": json.dumps(SCHEMA_JSON),
    }}
    if SELECTED_SHEETS:
        params["selected_sheets"] = SELECTED_SHEETS

    files = {{
        "file": (
            EXCEL_PATH.name,
            EXCEL_PATH.read_bytes(),
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
    }}

    with httpx.Client(timeout=600.0) as client:
        resp = client.post(f"{{BACKEND_URL}}/ingest", params=params, files=files)
        resp.raise_for_status()
        payload = resp.json()

    OUT_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"Wrote {{OUT_PATH}}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
"""
    return script


def _get_store():
    """Lazy-initialise the store singleton."""
    global _store
    if _store is None:
        _store = get_store()
    return _store


def _get_file_store():
    """Lazy-initialise the file store singleton."""
    global _file_store
    if _file_store is None:
        _file_store = get_file_store()
    return _file_store


# ── Auth dependency ─────────────────────────────────────────────────


async def get_user(request: Request) -> dict:
    """FastAPI dependency: validate the Azure AD JWT and return claims.

    When auth is disabled (local dev with no tenant/client ID configured),
    returns a stub user so all routes work without Azure AD.
    """
    if not settings.auth_enabled:
        return {"oid": "local-dev-user", "name": "Local Developer"}

    import jwt
    from jwt import PyJWKClient

    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(
            status_code=401, detail="Missing or invalid Authorization header"
        )

    token = auth_header[7:]

    global _jwks_client
    if _jwks_client is None:
        jwks_url = (
            f"https://login.microsoftonline.com/{settings.azure_tenant_id}"
            f"/discovery/v2.0/keys"
        )
        _jwks_client = PyJWKClient(jwks_url)

    try:
        signing_key = _jwks_client.get_signing_key_from_jwt(token)
        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            audience=settings.azure_client_id,
            issuer=f"https://login.microsoftonline.com/{settings.azure_tenant_id}/v2.0",
        )
        return claims
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid or expired token")


# ── Health ──────────────────────────────────────────────────────────


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/excel-schema", response_model=ExcelSchemaResponse)
async def excel_schema(
    file: UploadFile = File(...),
    selected_sheets: str = Query(
        default="", description="Comma-separated sheet names to process (empty = all)"
    ),
    user: dict = Depends(get_user),
):
    """Return a normalized workbook schema summary for caching/replay workflows."""
    _ = user  # Keep auth dependency behaviour consistent with other routes.
    file_bytes = await file.read()
    file_hash = compute_file_hash(file_bytes)

    all_sheet_names = get_sheet_names(file_bytes)
    if selected_sheets:
        sheets_to_process = [s.strip() for s in selected_sheets.split(",") if s.strip()]
        invalid = [s for s in sheets_to_process if s not in all_sheet_names]
        if invalid:
            raise HTTPException(
                status_code=422,
                detail=f"Sheets not found: {invalid}. Available: {all_sheet_names}",
            )
    else:
        sheets_to_process = all_sheet_names

    summaries = [summarise_sheet(file_bytes, sheet_name=s) for s in sheets_to_process]
    schema_payload = {
        "sheet_names": all_sheet_names,
        "processed_sheet_names": sheets_to_process,
        "sheets": summaries,
    }
    schema_hash = compute_schema_hash(schema_payload)

    return ExcelSchemaResponse(
        excel_hash=file_hash,
        excel_schema_hash=schema_hash,
        sheet_names=all_sheet_names,
        processed_sheet_names=sheets_to_process,
        sheets=summaries,
    )


# ── Ingestion ───────────────────────────────────────────────────────


@app.post("/ingest", response_model=IngestResponse)
async def ingest(
    request: Request,
    file: UploadFile = File(...),
    schema_name: str = Query(..., description="Schema name"),
    schema_json: str = Query(..., description="JSON-encoded schema definition"),
    selected_sheets: str = Query(
        default="", description="Comma-separated sheet names to process (empty = all)"
    ),
    user: dict = Depends(get_user),
):
    """Map + extract + validate an Excel file against a schema.

    Processes each sheet independently with its own mapping call.

    Flow:
    1. Hash the file -> store file -> check cache
    2. Discover sheets (filter by selected_sheets if provided)
    3. For each sheet: infer mapping, extract, validate
    4. Aggregate results, cache and return
    """
    store = _get_store()
    fstore = _get_file_store()
    file_bytes = await file.read()
    file_hash = compute_file_hash(file_bytes)
    user_id = user.get("oid", "local-dev-user")

    log_event("ingest_started", logger, file_hash=file_hash, user_id=user_id)

    # Parse schema from query param
    try:
        schema_data = json.loads(schema_json)
        schema = SchemaDefinition.model_validate(schema_data)
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Invalid schema: {e}")

    schema_id = schema.id or "ephemeral"
    schema_version = getattr(schema, "version", 1)
    replay_code = _build_replay_code(
        backend_base_url=str(request.base_url).rstrip("/"),
        schema_name=schema_name,
        schema_json=schema.model_dump(mode="json"),
        selected_sheets=selected_sheets,
    )

    # 1. Store the uploaded file
    try:
        storage_path = fstore.store_file(user_id, file_hash, file_bytes)
        log_event("file_stored", logger, file_hash=file_hash, user_id=user_id)
    except Exception as e:
        logger.warning("File storage failed (non-fatal): %s", e)
        storage_path = ""

    # 2. Check cache
    cached = store.get_result(file_hash, schema_id)
    if cached:
        log_event(
            "cache_hit",
            logger,
            file_hash=file_hash,
            schema_id=schema_id,
            cache_hit=True,
        )
        if isinstance(cached, dict) and not cached.get("replay_code"):
            cached["replay_code"] = replay_code
        return IngestResponse.model_validate(cached)

    log_event(
        "cache_miss", logger, file_hash=file_hash, schema_id=schema_id, cache_hit=False
    )

    # 3. Check OpenAI is configured
    if not settings.openai_available:
        raise HTTPException(
            status_code=503,
            detail="Azure OpenAI is not configured. Set AZURE_OPENAI_ENDPOINT and AZURE_OPENAI_API_KEY.",
        )

    # 4. Discover sheets
    all_sheet_names = get_sheet_names(file_bytes)
    if selected_sheets:
        sheets_to_process = [s.strip() for s in selected_sheets.split(",") if s.strip()]
        # Validate sheet names
        invalid = [s for s in sheets_to_process if s not in all_sheet_names]
        if invalid:
            raise HTTPException(
                status_code=422,
                detail=f"Sheets not found: {invalid}. Available: {all_sheet_names}",
            )
    else:
        sheets_to_process = all_sheet_names

    log_event(
        "sheets_discovered",
        logger,
        file_hash=file_hash,
        sheet_count=len(sheets_to_process),
    )

    # 5. Process each sheet independently
    sheet_results: list[SheetResult] = []
    all_data: list[dict] = []
    all_lineage = []
    first_mapping = None

    for sheet_name in sheets_to_process:
        log_event(
            "sheet_processing_started",
            logger,
            sheet_name=sheet_name,
            file_hash=file_hash,
        )

        # 5a. Infer mapping for this sheet
        with OperationTimer(
            "llm_mapping", logger, sheet_name=sheet_name, schema_id=schema_id
        ):
            try:
                mapping = infer_mapping(file_bytes, schema, sheet_name=sheet_name)
            except Exception as e:
                logger.error("Mapping failed for sheet '%s': %s", sheet_name, e)
                sheet_results.append(
                    SheetResult(
                        sheet_name=sheet_name,
                        mapping=None,
                        data=[],
                        row_count=0,
                    )
                )
                continue

        if first_mapping is None:
            first_mapping = mapping

        # 5b. Extract data from this sheet
        with OperationTimer("extraction", logger, sheet_name=sheet_name):
            try:
                data_rows, lineage = extract(file_bytes, file_hash, mapping)
            except Exception as e:
                logger.error("Extraction failed for sheet '%s': %s", sheet_name, e)
                sheet_results.append(
                    SheetResult(
                        sheet_name=sheet_name,
                        mapping=mapping,
                        data=[],
                        row_count=0,
                    )
                )
                continue

        # 5c. Validate this sheet's extraction
        with OperationTimer("llm_validation", logger, sheet_name=sheet_name):
            try:
                validation = validate_extraction(schema, data_rows)
            except Exception as e:
                logger.warning(
                    "Validation failed for sheet '%s' (non-fatal): %s", sheet_name, e
                )
                validation = None

        log_event(
            "sheet_processing_completed",
            logger,
            sheet_name=sheet_name,
            row_count=len(data_rows),
            confidence=validation.confidence if validation else None,
        )

        sheet_results.append(
            SheetResult(
                sheet_name=sheet_name,
                mapping=mapping,
                validation=validation,
                data=data_rows,
                lineage=lineage,
                row_count=len(data_rows),
            )
        )
        all_data.extend(data_rows)
        all_lineage.extend(lineage)

    # 6. Build aggregate response
    # For backwards compatibility, the top-level fields reflect the first sheet
    first_validation = next(
        (sr.validation for sr in sheet_results if sr.validation), None
    )

    response = IngestResponse(
        success=True,
        excel_hash=file_hash,
        schema_id=schema_id,
        schema_version=schema_version,
        sheet_names=all_sheet_names,
        sheets=sheet_results,
        mapping=first_mapping,
        validation=first_validation,
        data=all_data,
        lineage=all_lineage,
        row_count=len(all_data),
        cached=False,
        file_storage_path=storage_path,
        replay_code=replay_code,
        created_at=datetime.now(timezone.utc),
    )

    # 7. Cache the result
    store.save_result(file_hash, schema_id, response.model_dump(mode="json"))

    log_event(
        "ingest_completed",
        logger,
        file_hash=file_hash,
        schema_id=schema_id,
        schema_version=schema_version,
        row_count=len(all_data),
        sheet_count=len(sheet_results),
    )

    return response


# ── Cached result retrieval ─────────────────────────────────────────


@app.get("/result/{excel_hash}", response_model=IngestResponse)
async def get_result(
    excel_hash: str,
    schema_id: str = Query(..., description="Schema ID"),
    user: dict = Depends(get_user),
):
    """Fetch a cached result by file hash + schema ID."""
    store = _get_store()
    cached = store.get_result(excel_hash, schema_id)
    if not cached:
        raise HTTPException(status_code=404, detail="Result not found in cache")
    return IngestResponse.model_validate(cached)


# ── Extraction-only (manual override) ──────────────────────────────


@app.post("/extract", response_model=IngestResponse)
async def extract_with_file(
    file: UploadFile | None = File(default=None),
    excel_hash: str = Query(
        default="",
        description="File hash to retrieve from storage (if no file uploaded)",
    ),
    mapping_json: str = Query(..., description="JSON-encoded ExcelMapping"),
    schema_id: str = Query(default="ephemeral", description="Schema ID"),
    user: dict = Depends(get_user),
):
    """Re-run extraction with a user-provided mapping — no LLM call.

    The user corrects the inferred mapping in the UI and either re-uploads the file
    or provides the excel_hash to retrieve it from storage, skipping the LLM step.
    """
    fstore = _get_file_store()
    user_id = user.get("oid", "local-dev-user")

    # Get file bytes: from upload or from storage
    if file is not None:
        file_bytes = await file.read()
        file_hash = compute_file_hash(file_bytes)
    elif excel_hash:
        file_bytes = fstore.retrieve_file(user_id, excel_hash)
        if file_bytes is None:
            raise HTTPException(
                status_code=404,
                detail="File not found in storage. Please re-upload.",
            )
        file_hash = excel_hash
    else:
        raise HTTPException(
            status_code=400,
            detail="Either upload a file or provide excel_hash to retrieve from storage.",
        )

    try:
        mapping_data = json.loads(mapping_json)
        mapping = ExcelMapping.model_validate(mapping_data)
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Invalid mapping: {e}")

    # Extract data
    try:
        data_rows, lineage = extract(file_bytes, file_hash, mapping)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Extraction failed: {e}")

    response = IngestResponse(
        success=True,
        excel_hash=file_hash,
        schema_id=schema_id,
        mapping=mapping,
        validation=None,
        data=data_rows,
        lineage=lineage,
        row_count=len(data_rows),
        cached=False,
        created_at=datetime.now(timezone.utc),
    )

    return response


# ── Schema Library ──────────────────────────────────────────────────


@app.get("/schemas")
async def list_schemas(user: dict = Depends(get_user)):
    """List all saved schemas for the current user."""
    store = _get_store()
    user_id = user.get("oid", "")
    schemas = store.list_schemas(user_id)
    return {"schemas": schemas}


@app.post("/schemas")
async def create_schema(
    schema: SchemaDefinition,
    user: dict = Depends(get_user),
):
    """Save a new schema to the library."""
    store = _get_store()
    schema_dict = schema.model_dump(mode="json")
    schema_dict["user_id"] = user.get("oid", "")
    saved = store.save_schema(schema_dict)
    return saved


@app.put("/schemas/{schema_id}")
async def update_schema(
    schema_id: str,
    schema: SchemaDefinition,
    user: dict = Depends(get_user),
):
    """Update an existing schema (invalidates related cache entries)."""
    store = _get_store()
    # Verify ownership
    existing = store.get_schema(schema_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Schema not found")
    if existing.get("user_id") != user.get("oid", ""):
        raise HTTPException(status_code=403, detail="Not your schema")

    schema_dict = schema.model_dump(mode="json")
    updated = store.update_schema(schema_id, schema_dict)
    if not updated:
        raise HTTPException(status_code=404, detail="Schema not found")
    return updated


@app.get("/schemas/{schema_id}/history")
async def get_schema_history(
    schema_id: str,
    user: dict = Depends(get_user),
):
    """Get all historical versions of a schema."""
    store = _get_store()
    existing = store.get_schema(schema_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Schema not found")
    if existing.get("user_id") != user.get("oid", ""):
        raise HTTPException(status_code=403, detail="Not your schema")

    history = store.get_schema_history(schema_id)
    return {"schema_id": schema_id, "versions": history}


@app.delete("/schemas/{schema_id}")
async def delete_schema(
    schema_id: str,
    user: dict = Depends(get_user),
):
    """Delete a schema and invalidate related cache entries."""
    store = _get_store()
    existing = store.get_schema(schema_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Schema not found")
    if existing.get("user_id") != user.get("oid", ""):
        raise HTTPException(status_code=403, detail="Not your schema")

    deleted = store.delete_schema(schema_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Schema not found")
    return {"deleted": True}
