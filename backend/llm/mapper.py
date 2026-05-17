"""GPT-4o mapping call — takes an Excel column summary + schema → validated ExcelMapping.

The LLM returns constrained JSON; this module parses and validates it with Pydantic.
Includes retry logic: 1 initial attempt + 2 retries with exponential backoff.
"""

from __future__ import annotations

import json
import logging
import time

from openai import AzureOpenAI

from backend.config import settings
from backend.models import ExcelMapping, SchemaDefinition
from backend.llm.prompts import build_mapper_prompt
from backend.excel_processor import summarise_sheet

logger = logging.getLogger(__name__)

MAX_RETRIES = 2
RETRY_BASE_DELAY = 1.0  # seconds


def _get_client() -> AzureOpenAI:
    return AzureOpenAI(
        azure_endpoint=settings.azure_openai_endpoint,
        api_key=settings.azure_openai_api_key,
        api_version=settings.azure_openai_api_version,
    )


def _call_with_retry(client: AzureOpenAI, **kwargs) -> str:
    """Call the OpenAI API with retry logic for transient errors.

    Retries on:
    - 429 (rate limit)
    - 5xx (server errors)
    - Connection errors

    Returns the raw content string from the response.
    """
    last_exception = None

    for attempt in range(1 + MAX_RETRIES):
        try:
            response = client.chat.completions.create(**kwargs)
            return response.choices[0].message.content
        except Exception as e:
            last_exception = e
            error_str = str(e)
            status_code = getattr(e, "status_code", None)

            is_retryable = (
                status_code in (429, 500, 502, 503, 504)
                or "rate limit" in error_str.lower()
                or "connection" in error_str.lower()
                or "timeout" in error_str.lower()
            )

            if not is_retryable or attempt >= MAX_RETRIES:
                raise

            delay = RETRY_BASE_DELAY * (2**attempt)
            logger.warning(
                "LLM call failed (attempt %d/%d), retrying in %.1fs: %s",
                attempt + 1,
                1 + MAX_RETRIES,
                delay,
                e,
            )
            time.sleep(delay)

    raise last_exception


def infer_mapping(
    file_bytes: bytes,
    schema: SchemaDefinition,
    sheet_name: str | None = None,
) -> ExcelMapping:
    """Call GPT-4o to infer how the Excel file maps to the given schema.

    Uses the smart column summary (not raw row samples) to give the LLM
    better signal about each column's content, types, and patterns.

    Args:
        file_bytes: Raw Excel file bytes.
        schema: The user-defined schema to map against.
        sheet_name: Optional sheet to focus on (uses active sheet if None).

    Returns:
        A validated ExcelMapping object.

    Raises:
        ValueError: If the LLM response cannot be parsed into a valid ExcelMapping.
    """
    # 1. Build column summary for the sheet
    sheet_summary = summarise_sheet(file_bytes, sheet_name=sheet_name)

    # 2. Build prompts
    fields_dicts = [
        {
            "name": f.name,
            "field_type": f.field_type.value,
            "description": f.description,
            "required": f.required,
        }
        for f in schema.fields
    ]
    system_prompt, user_prompt = build_mapper_prompt(
        schema_name=schema.name,
        fields=fields_dicts,
        sheet_summary=sheet_summary,
    )

    # 3. Call GPT-4o with retry
    client = _get_client()
    logger.info(
        "Calling GPT-4o mapper for schema '%s', sheet '%s'",
        schema.name,
        sheet_summary["sheet_name"],
    )

    raw_content = _call_with_retry(
        client,
        model=settings.azure_openai_mapper_deployment,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.0,
        response_format={"type": "json_object"},
    )

    logger.debug("Mapper raw response: %s", raw_content)

    # 4. Parse and validate
    try:
        raw_json = json.loads(raw_content)
    except json.JSONDecodeError as e:
        raise ValueError(f"LLM returned invalid JSON: {e}") from e

    try:
        mapping = ExcelMapping.model_validate(raw_json)
    except Exception as e:
        raise ValueError(f"LLM response failed schema validation: {e}") from e

    logger.info(
        "Mapping inferred: sheet=%s, header_row=%d, %d column mappings",
        mapping.sheet_name,
        mapping.header_row,
        len(mapping.mappings),
    )
    return mapping
