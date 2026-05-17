"""All prompt strings — single source of truth for LLM interactions.

Prompts are plain strings with {placeholders} for .format() substitution.
No LLM calls happen here.
"""

# ── Mapper (GPT-4o) ────────────────────────────────────────────────

MAPPER_SYSTEM_PROMPT = """\
You are an expert at analysing Excel spreadsheet structures. Your job is to \
examine a column-level summary of an Excel sheet and determine how its columns \
map to a user-defined schema.

You MUST respond with valid JSON matching the ExcelMapping schema exactly. \
Do not include any text outside the JSON object.

Rules:
1. Use the provided header row and data start row from the summary.
2. For each schema field, find the best matching column based on the column \
   header, sample values, data types, and the user's field description.
3. Choose exactly one transform per mapping from this set:
   identity | strip | to_date | to_number | to_boolean | to_string | \
   split_comma | to_integer | regex_extract | concat | conditional | \
   uppercase | lowercase | default_value | trim_whitespace | substring
   You CANNOT invent new transforms.
4. For parameterised transforms (regex_extract, concat, conditional, \
   default_value, substring), include a "transform_params" object with the \
   required parameters (see the schema below).
5. If a required field has no plausible column match, still include a mapping \
   with your best guess and explain in the "notes" field.
6. The "reasoning" field should briefly explain your overall logic.
"""

MAPPER_USER_PROMPT = """\
## Schema to extract

Name: {schema_name}

Fields:
{fields_text}

## Excel sheet summary

Sheet: "{sheet_name}"
Estimated rows: {total_rows}
Header row: {header_row}
Data start row: {data_start_row}

### Column summaries

{column_summaries_text}

---

Return a JSON object with this exact structure:
{{
  "sheet_name": "<sheet name>",
  "header_row": {header_row},
  "data_start_row": {data_start_row},
  "mappings": [
    {{
      "source_col": "<column letter>",
      "target_field": "<schema field name>",
      "transform": "<transform name from the allowed set>",
      "transform_params": {{}},
      "notes": "<why you chose this column>"
    }}
  ],
  "reasoning": "<brief overall explanation>"
}}
"""


# ── Validator (GPT-4o-mini) ─────────────────────────────────────────

VALIDATOR_SYSTEM_PROMPT = """\
You are a data quality reviewer. You will receive a sample of extracted data \
rows and the schema they were extracted against. Your job is to sense-check \
the data and report any issues.

You MUST respond with valid JSON matching the ValidationResult schema exactly. \
Do not include any text outside the JSON object.

Rules:
1. Check that values match the expected field types.
2. Look for obviously wrong mappings (e.g. dates in a "company name" field).
3. Flag empty required fields.
4. Assign a confidence score from 0.0 to 1.0.
5. Set "passed" to true if confidence >= 0.70, false otherwise.
6. List specific issues with field name, description, severity, and example rows.
"""

VALIDATOR_USER_PROMPT = """\
## Schema

Fields:
{fields_text}

## Extracted data sample ({row_count} rows)

{data_text}

---

Return a JSON object with this exact structure:
{{
  "confidence": <float 0.0-1.0>,
  "passed": <true if confidence >= 0.70>,
  "issues": [
    {{
      "field": "<field name>",
      "issue": "<description of the problem>",
      "severity": "<warning or error>",
      "row_examples": [<row numbers>]
    }}
  ],
  "rows_sampled": {row_count},
  "summary": "<one-line summary>"
}}
"""


def format_fields_for_prompt(fields: list[dict]) -> str:
    """Format schema fields into a readable text block for LLM prompts.

    Args:
        fields: List of dicts with keys: name, field_type, description, required.
    """
    lines = []
    for f in fields:
        req = "required" if f.get("required", True) else "optional"
        desc = f.get("description", "")
        desc_part = f' — "{desc}"' if desc else ""
        lines.append(f"- {f['name']} ({f['field_type']}, {req}){desc_part}")
    return "\n".join(lines)


def format_sample_rows(rows: list[list], column_letters: list[str]) -> str:
    """Format sample rows into a text table for the LLM.

    Each row is prefixed with its 1-indexed row number.
    """
    lines = []
    # Header line with column letters
    header = "Row | " + " | ".join(column_letters)
    lines.append(header)
    lines.append("-" * len(header))

    for i, row in enumerate(rows):
        cells = []
        for j, val in enumerate(row):
            if j >= len(column_letters):
                break
            cells.append(str(val) if val is not None else "")
        lines.append(f"  {i + 1} | " + " | ".join(cells))

    return "\n".join(lines)


def format_column_summary(column: dict) -> str:
    """Format a single column summary into a readable text block for the LLM."""
    lines = [
        f"**Column {column['column_letter']}** — Header: {column['header'] or '(none)'}"
    ]
    lines.append(f"  Non-empty cells: {column['non_empty_count']}")

    if column.get("dominant_type"):
        lines.append(f"  Dominant type: {column['dominant_type']}")

    if column.get("type_inconsistencies"):
        lines.append(f"  Type issues: {column['type_inconsistencies']}")

    if column.get("first_values"):
        lines.append(f"  First values: {column['first_values']}")

    if column.get("last_values"):
        lines.append(f"  Last values: {column['last_values']}")

    if column.get("distinct_values"):
        lines.append(f"  Distinct values (categorical): {column['distinct_values']}")

    return "\n".join(lines)


def format_column_summaries(columns: list[dict]) -> str:
    """Format all column summaries into a single text block."""
    return "\n\n".join(format_column_summary(col) for col in columns)


def build_mapper_prompt(
    schema_name: str,
    fields: list[dict],
    sheet_summary: dict,
) -> tuple[str, str]:
    """Build the system and user prompts for the mapper LLM call.

    Accepts either a legacy sheet_sample (with sample_rows) or a new
    sheet_summary (with columns) dict.

    Returns:
        (system_prompt, user_prompt)
    """
    fields_text = format_fields_for_prompt(fields)

    # New column-summary format
    if "columns" in sheet_summary:
        column_summaries_text = format_column_summaries(sheet_summary["columns"])
        user_prompt = MAPPER_USER_PROMPT.format(
            schema_name=schema_name,
            fields_text=fields_text,
            sheet_name=sheet_summary["sheet_name"],
            total_rows=sheet_summary["total_rows"],
            header_row=sheet_summary.get("header_row", 1),
            data_start_row=sheet_summary.get("data_start_row", 2),
            column_summaries_text=column_summaries_text,
        )
    else:
        # Legacy fallback: sample_rows format
        sample_text = format_sample_rows(
            sheet_summary["sample_rows"],
            sheet_summary["column_letters"],
        )
        # Use the old-style prompt with inline formatting
        user_prompt = (
            f"## Schema to extract\n\n"
            f"Name: {schema_name}\n\n"
            f"Fields:\n{fields_text}\n\n"
            f"## Excel file sample\n\n"
            f'Sheet: "{sheet_summary["sheet_name"]}"\n'
            f"Estimated rows: {sheet_summary['total_rows']}\n"
            f"Column letters: {', '.join(sheet_summary['column_letters'])}\n\n"
            f"Sample data (first {len(sheet_summary['sample_rows'])} rows):\n"
            f"{sample_text}\n"
        )

    return MAPPER_SYSTEM_PROMPT, user_prompt


def build_validator_prompt(
    fields: list[dict],
    data_sample: list[dict],
) -> tuple[str, str]:
    """Build the system and user prompts for the validator LLM call.

    Returns:
        (system_prompt, user_prompt)
    """
    fields_text = format_fields_for_prompt(fields)

    # Format data rows as readable text
    data_lines = []
    for i, row in enumerate(data_sample):
        row_parts = [f"{k}: {v}" for k, v in row.items() if not k.startswith("_")]
        data_lines.append(f"Row {i + 1}: {{ {', '.join(row_parts)} }}")
    data_text = "\n".join(data_lines)

    user_prompt = VALIDATOR_USER_PROMPT.format(
        fields_text=fields_text,
        row_count=len(data_sample),
        data_text=data_text,
    )

    return VALIDATOR_SYSTEM_PROMPT, user_prompt
