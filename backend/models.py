"""Pydantic models for every input, output, and internal type.

These are the single source of truth for the data shapes used across the API,
LLM layer, extractor engine, and cache.
"""

from __future__ import annotations

import enum
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


# ── Enums ───────────────────────────────────────────────────────────


class FieldType(str, enum.Enum):
    """Allowed field types in a schema definition."""

    STRING = "string"
    NUMBER = "number"
    INTEGER = "integer"
    BOOLEAN = "boolean"
    DATE = "date"


class Transform(str, enum.Enum):
    """Transform enum — the LLM must pick from this set.

    Pydantic rejects anything else before it reaches the extractor.
    Some transforms accept parameters via ColumnMapping.transform_params.
    """

    IDENTITY = "identity"
    STRIP = "strip"
    TO_DATE = "to_date"
    TO_NUMBER = "to_number"
    TO_BOOLEAN = "to_boolean"
    TO_STRING = "to_string"
    SPLIT_COMMA = "split_comma"
    TO_INTEGER = "to_integer"
    REGEX_EXTRACT = "regex_extract"
    CONCAT = "concat"
    CONDITIONAL = "conditional"
    UPPERCASE = "uppercase"
    LOWERCASE = "lowercase"
    DEFAULT_VALUE = "default_value"
    TRIM_WHITESPACE = "trim_whitespace"
    SUBSTRING = "substring"


# ── Schema Definition (user-created) ───────────────────────────────


class SchemaField(BaseModel):
    """A single field in a user-defined schema."""

    name: str = Field(..., description="Target field name, e.g. 'supplier_name'")
    field_type: FieldType = Field(..., description="Expected data type")
    description: str = Field(
        default="",
        description=(
            "Plain-English instruction to the AI — e.g. "
            "'full legal name of the company, may appear as client, buyer or account name'"
        ),
    )
    required: bool = Field(
        default=True, description="Whether this field must be present"
    )


class SchemaDefinition(BaseModel):
    """A complete user-defined schema (the set of fields to extract)."""

    id: str = Field(default="", description="Schema ID (set by the server on save)")
    name: str = Field(
        ..., description="Human-readable schema name, e.g. 'Acme Q1 Report'"
    )
    fields: list[SchemaField] = Field(
        ..., min_length=1, description="Fields to extract"
    )
    user_id: str = Field(default="", description="Azure AD oid of the owning user")
    version: int = Field(
        default=1, description="Schema version, auto-incremented on update"
    )
    created_at: datetime | None = Field(default=None)
    updated_at: datetime | None = Field(default=None)


# ── Excel Mapping (LLM output) ─────────────────────────────────────


class ColumnMapping(BaseModel):
    """How one schema field maps to a column in the Excel file."""

    source_col: str = Field(..., description="Excel column letter, e.g. 'B'")
    target_field: str = Field(..., description="Schema field name this column maps to")
    transform: Transform = Field(
        default=Transform.IDENTITY,
        description="Transform to apply during extraction",
    )
    transform_params: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Parameters for parameterised transforms. "
            "regex_extract: {pattern: str, group: int}. "
            "concat: {separator: str, other_cols: list[str]}. "
            "conditional: {condition: str, true_value: str, false_value: str}. "
            "default_value: {default: Any}. "
            "substring: {start: int, end: int}."
        ),
    )
    notes: str = Field(
        default="",
        description="LLM reasoning for this mapping choice",
    )


class ExcelMapping(BaseModel):
    """The complete mapping from an Excel file to a schema.

    This is the constrained JSON that GPT-4o returns. It cannot invent
    transforms, pick libraries, or write code — only fill this config.
    """

    sheet_name: str = Field(..., description="Name of the sheet to extract from")
    header_row: int = Field(
        ..., ge=1, description="1-indexed row number containing headers"
    )
    data_start_row: int = Field(..., ge=1, description="1-indexed first row of data")
    mappings: list[ColumnMapping] = Field(
        ..., min_length=1, description="Column-to-field mappings"
    )
    reasoning: str = Field(
        default="",
        description="LLM explanation of how it determined the mapping",
    )


# ── Validation Result ───────────────────────────────────────────────


class ValidationIssue(BaseModel):
    """A single issue found during validation."""

    field: str = Field(..., description="Which field the issue relates to")
    issue: str = Field(..., description="Description of the problem")
    severity: str = Field(default="warning", description="'warning' or 'error'")
    row_examples: list[int] = Field(
        default_factory=list, description="Example row numbers exhibiting the issue"
    )


class ValidationResult(BaseModel):
    """Output of the GPT-4o-mini validation step."""

    confidence: float = Field(..., ge=0.0, le=1.0, description="Confidence score 0–1")
    passed: bool = Field(..., description="True if confidence >= 0.70")
    issues: list[ValidationIssue] = Field(default_factory=list)
    rows_sampled: int = Field(default=10)
    summary: str = Field(default="", description="One-line summary from the validator")


# ── Lineage ─────────────────────────────────────────────────────────


class FieldLineage(BaseModel):
    """Lineage for a single field in a single row."""

    target_field: str
    source_col: str
    source_sheet: str
    transform_applied: str


class RowLineage(BaseModel):
    """Lineage record for one extracted row."""

    source_file_hash: str
    source_sheet: str
    source_row: int
    fields: list[FieldLineage]


# ── API Request / Response ──────────────────────────────────────────


class IngestRequest(BaseModel):
    """Body of POST /ingest."""

    schema_definition: SchemaDefinition = Field(
        ..., alias="schema", description="Schema defining the fields to extract"
    )

    model_config = {"populate_by_name": True}


class ExtractRequest(BaseModel):
    """Body of POST /extract — manual override flow."""

    excel_hash: str = Field(
        ..., description="SHA-256 hash (first 16 chars) of the Excel file"
    )
    schema_id: str = Field(..., description="ID of the schema used")
    mapping: ExcelMapping = Field(..., description="User-corrected mapping to apply")


class SheetResult(BaseModel):
    """Extraction result for a single sheet."""

    sheet_name: str = ""
    mapping: ExcelMapping | None = None
    validation: ValidationResult | None = None
    data: list[dict[str, Any]] = Field(default_factory=list)
    lineage: list[RowLineage] = Field(default_factory=list)
    row_count: int = 0


class IngestResponse(BaseModel):
    """Full response from /ingest or /extract."""

    success: bool = True
    excel_hash: str = ""
    schema_id: str = ""
    schema_version: int = Field(
        default=1, description="Schema version used for extraction"
    )
    sheet_names: list[str] = Field(
        default_factory=list, description="All sheet names in the workbook"
    )
    sheets: list[SheetResult] = Field(
        default_factory=list, description="Per-sheet extraction results"
    )
    # Flat accessors kept for backwards compatibility / single-sheet convenience
    mapping: ExcelMapping | None = None
    validation: ValidationResult | None = None
    data: list[dict[str, Any]] = Field(default_factory=list)
    lineage: list[RowLineage] = Field(default_factory=list)
    row_count: int = 0
    cached: bool = False
    file_storage_path: str = Field(
        default="", description="Path to the stored Excel file in ADLS/local storage"
    )
    replay_code: str = Field(
        default="",
        description="Runnable Python code that replays this ingest request and writes JSON output",
    )
    created_at: datetime | None = None


class ErrorResponse(BaseModel):
    """Standard error response body."""

    success: bool = False
    error: str = ""
    detail: str = ""


class ExcelSchemaColumnSummary(BaseModel):
    """Column-level summary for a sheet."""

    column_letter: str
    header: str | None = None
    non_empty_count: int = 0
    first_values: list[str] = Field(default_factory=list)
    last_values: list[str] = Field(default_factory=list)
    dominant_type: str | None = None
    type_inconsistencies: str | None = None
    distinct_values: list[str] | None = None


class ExcelSheetSchema(BaseModel):
    """Normalized schema summary for one worksheet."""

    sheet_name: str
    total_rows: int = 0
    total_cols: int = 0
    header_row: int = 0
    data_start_row: int = 0
    columns: list[ExcelSchemaColumnSummary] = Field(default_factory=list)


class ExcelSchemaResponse(BaseModel):
    """Response body for POST /excel-schema."""

    excel_hash: str
    excel_schema_hash: str
    sheet_names: list[str] = Field(default_factory=list)
    processed_sheet_names: list[str] = Field(default_factory=list)
    sheets: list[ExcelSheetSchema] = Field(default_factory=list)
