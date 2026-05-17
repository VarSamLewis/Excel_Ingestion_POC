"""GPT-4o-mini validation call — sense-checks extracted data against the schema.

Takes a sample of extracted rows and returns a confidence score + typed issues.
Includes retry logic: 1 initial attempt + 2 retries with exponential backoff.
"""

from __future__ import annotations

import json
import logging
import random

from openai import AzureOpenAI

from backend.config import settings
from backend.models import SchemaDefinition, ValidationResult
from backend.llm.prompts import build_validator_prompt
from backend.llm.mapper import _call_with_retry

logger = logging.getLogger(__name__)

SAMPLE_SIZE = 10


def _get_client() -> AzureOpenAI:
    return AzureOpenAI(
        azure_endpoint=settings.azure_openai_endpoint,
        api_key=settings.azure_openai_api_key,
        api_version=settings.azure_openai_api_version,
    )


def validate_extraction(
    schema: SchemaDefinition,
    extracted_data: list[dict],
    sample_size: int = SAMPLE_SIZE,
) -> ValidationResult:
    """Call GPT-4o-mini to validate a sample of extracted data.

    Args:
        schema: The schema the data was extracted against.
        extracted_data: All extracted rows.
        sample_size: Number of random rows to send to the validator.

    Returns:
        A validated ValidationResult object.

    Raises:
        ValueError: If the LLM response cannot be parsed.
    """
    # 1. Sample rows
    if len(extracted_data) <= sample_size:
        sample = extracted_data
    else:
        sample = random.sample(extracted_data, sample_size)

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
    system_prompt, user_prompt = build_validator_prompt(
        fields=fields_dicts,
        data_sample=sample,
    )

    # 3. Call GPT-4o-mini with retry
    client = _get_client()
    logger.info(
        "Calling GPT-4o-mini validator with %d sample rows",
        len(sample),
    )

    raw_content = _call_with_retry(
        client,
        model=settings.azure_openai_validator_deployment,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.0,
        response_format={"type": "json_object"},
    )

    logger.debug("Validator raw response: %s", raw_content)

    # 4. Parse and validate
    try:
        raw_json = json.loads(raw_content)
    except json.JSONDecodeError as e:
        raise ValueError(f"Validator returned invalid JSON: {e}") from e

    try:
        result = ValidationResult.model_validate(raw_json)
    except Exception as e:
        raise ValueError(f"Validator response failed schema validation: {e}") from e

    # Ensure passed flag is consistent with threshold
    result.passed = result.confidence >= 0.70

    logger.info(
        "Validation complete: confidence=%.2f, passed=%s, issues=%d",
        result.confidence,
        result.passed,
        len(result.issues),
    )
    return result
