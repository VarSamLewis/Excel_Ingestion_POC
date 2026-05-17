"""Extraction engine — applies a mapping to an Excel workbook.

This is the deterministic core: Mapping + Workbook → Rows + Lineage.
No LLM calls happen here. The engine interprets the ExcelMapping config
produced by the mapper and uses the transform registry to process cell values.
"""

from __future__ import annotations

import logging
from typing import Any

from backend.models import ExcelMapping, RowLineage, FieldLineage
from backend.excel_processor import read_data_rows
from backend.extractor.transforms import apply_transform

logger = logging.getLogger(__name__)


def extract(
    file_bytes: bytes,
    file_hash: str,
    mapping: ExcelMapping,
) -> tuple[list[dict[str, Any]], list[RowLineage]]:
    """Run the extraction engine on an Excel file using the given mapping.

    Args:
        file_bytes: Raw Excel file bytes.
        file_hash: SHA-256 hash prefix of the file (for lineage).
        mapping: The validated ExcelMapping (from LLM or user override).

    Returns:
        A tuple of (data_rows, lineage_records) where:
        - data_rows: list of dicts, each mapping target_field → transformed value.
        - lineage_records: list of RowLineage objects tracking provenance.
    """
    # Determine which columns we need to read
    source_columns = [m.source_col for m in mapping.mappings]

    # Read raw data rows from Excel
    raw_rows = read_data_rows(
        file_bytes=file_bytes,
        sheet_name=mapping.sheet_name,
        data_start_row=mapping.data_start_row,
        columns=source_columns,
    )

    logger.info(
        "Extracting %d rows from sheet '%s' starting at row %d",
        len(raw_rows),
        mapping.sheet_name,
        mapping.data_start_row,
    )

    data_rows: list[dict[str, Any]] = []
    lineage_records: list[RowLineage] = []

    for raw_row in raw_rows:
        row_num = raw_row.get("__row_num__", 0)
        extracted: dict[str, Any] = {}
        field_lineages: list[FieldLineage] = []

        for col_mapping in mapping.mappings:
            raw_value = raw_row.get(col_mapping.source_col)

            # Apply the transform, passing params and row data for
            # parameterised / row-aware transforms
            try:
                params = (
                    col_mapping.transform_params
                    if col_mapping.transform_params
                    else None
                )
                transformed = apply_transform(
                    col_mapping.transform.value,
                    raw_value,
                    params=params,
                    row_data=raw_row,
                )
            except Exception as e:
                logger.warning(
                    "Transform '%s' failed on row %d, col %s: %s. Using raw value.",
                    col_mapping.transform.value,
                    row_num,
                    col_mapping.source_col,
                    e,
                )
                transformed = raw_value

            extracted[col_mapping.target_field] = transformed

            field_lineages.append(
                FieldLineage(
                    target_field=col_mapping.target_field,
                    source_col=col_mapping.source_col,
                    source_sheet=mapping.sheet_name,
                    transform_applied=col_mapping.transform.value,
                )
            )

        data_rows.append(extracted)
        lineage_records.append(
            RowLineage(
                source_file_hash=file_hash,
                source_sheet=mapping.sheet_name,
                source_row=row_num,
                fields=field_lineages,
            )
        )

    logger.info("Extraction complete: %d rows produced", len(data_rows))
    return data_rows, lineage_records
