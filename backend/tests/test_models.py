"""Tests for Pydantic models — validation, serialization, edge cases."""

import pytest
from datetime import datetime

from backend.models import (
    FieldType,
    Transform,
    SchemaField,
    SchemaDefinition,
    ColumnMapping,
    ExcelMapping,
    ValidationIssue,
    ValidationResult,
    IngestRequest,
    ExtractRequest,
    IngestResponse,
    SheetResult,
)


class TestFieldType:
    def test_all_values(self):
        assert set(FieldType) == {
            FieldType.STRING,
            FieldType.NUMBER,
            FieldType.INTEGER,
            FieldType.BOOLEAN,
            FieldType.DATE,
        }


class TestTransform:
    def test_all_values(self):
        expected = {
            "identity",
            "strip",
            "to_date",
            "to_number",
            "to_boolean",
            "to_string",
            "split_comma",
            "to_integer",
            "regex_extract",
            "concat",
            "conditional",
            "uppercase",
            "lowercase",
            "default_value",
            "trim_whitespace",
            "substring",
        }
        assert {t.value for t in Transform} == expected

    def test_invalid_transform_rejected(self):
        with pytest.raises(ValueError):
            Transform("invent_new_thing")


class TestSchemaField:
    def test_basic_field(self):
        f = SchemaField(name="company", field_type=FieldType.STRING)
        assert f.name == "company"
        assert f.required is True

    def test_optional_field(self):
        f = SchemaField(
            name="notes",
            field_type=FieldType.STRING,
            required=False,
            description="Any additional notes",
        )
        assert f.required is False
        assert f.description == "Any additional notes"


class TestSchemaDefinition:
    def test_minimum_schema(self):
        s = SchemaDefinition(
            name="Test",
            fields=[SchemaField(name="col1", field_type=FieldType.STRING)],
        )
        assert s.name == "Test"
        assert len(s.fields) == 1
        assert s.version == 1

    def test_empty_fields_rejected(self):
        with pytest.raises(Exception):
            SchemaDefinition(name="Test", fields=[])

    def test_version_default(self):
        s = SchemaDefinition(
            name="Versioned",
            fields=[SchemaField(name="col1", field_type=FieldType.STRING)],
        )
        assert s.version == 1

    def test_version_explicit(self):
        s = SchemaDefinition(
            name="Versioned",
            fields=[SchemaField(name="col1", field_type=FieldType.STRING)],
            version=3,
        )
        assert s.version == 3


class TestColumnMapping:
    def test_default_transform(self):
        m = ColumnMapping(source_col="A", target_field="name")
        assert m.transform == Transform.IDENTITY
        assert m.transform_params == {}

    def test_invalid_transform_rejected(self):
        with pytest.raises(Exception):
            ColumnMapping(
                source_col="A",
                target_field="name",
                transform="invalid",
            )

    def test_with_transform_params(self):
        m = ColumnMapping(
            source_col="A",
            target_field="order_id",
            transform=Transform.REGEX_EXTRACT,
            transform_params={"pattern": r"(\d+)", "group": 1},
        )
        assert m.transform == Transform.REGEX_EXTRACT
        assert m.transform_params["pattern"] == r"(\d+)"

    def test_concat_transform(self):
        m = ColumnMapping(
            source_col="A",
            target_field="full_name",
            transform=Transform.CONCAT,
            transform_params={"separator": " ", "other_cols": ["B"]},
        )
        assert m.transform_params["other_cols"] == ["B"]


class TestExcelMapping:
    def test_valid_mapping(self):
        m = ExcelMapping(
            sheet_name="Sheet1",
            header_row=1,
            data_start_row=2,
            mappings=[
                ColumnMapping(
                    source_col="A", target_field="name", transform=Transform.STRIP
                ),
            ],
        )
        assert m.sheet_name == "Sheet1"
        assert len(m.mappings) == 1

    def test_header_row_must_be_positive(self):
        with pytest.raises(Exception):
            ExcelMapping(
                sheet_name="Sheet1",
                header_row=0,
                data_start_row=1,
                mappings=[
                    ColumnMapping(source_col="A", target_field="name"),
                ],
            )


class TestValidationResult:
    def test_passing(self):
        v = ValidationResult(confidence=0.95, passed=True, summary="Looks good")
        assert v.passed is True
        assert v.issues == []

    def test_confidence_bounds(self):
        with pytest.raises(Exception):
            ValidationResult(confidence=1.5, passed=True)
        with pytest.raises(Exception):
            ValidationResult(confidence=-0.1, passed=False)


class TestSheetResult:
    def test_defaults(self):
        sr = SheetResult(sheet_name="Sheet1")
        assert sr.sheet_name == "Sheet1"
        assert sr.data == []
        assert sr.row_count == 0
        assert sr.mapping is None


class TestIngestResponse:
    def test_defaults(self):
        r = IngestResponse()
        assert r.success is True
        assert r.data == []
        assert r.lineage == []
        assert r.cached is False
        assert r.schema_version == 1
        assert r.sheets == []
        assert r.sheet_names == []
        assert r.file_storage_path == ""
