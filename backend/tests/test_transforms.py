"""Tests for the transform functions — pure unit tests, no external deps."""

import pytest
from datetime import datetime, date

from backend.extractor.transforms import (
    identity,
    strip,
    to_date,
    to_number,
    to_integer,
    to_boolean,
    to_string,
    split_comma,
    regex_extract,
    concat,
    conditional,
    uppercase,
    lowercase,
    default_value,
    trim_whitespace,
    substring,
    apply_transform,
    TRANSFORM_REGISTRY,
    PARAMETERISED_TRANSFORMS,
    ROW_AWARE_TRANSFORMS,
)


# ── identity ────────────────────────────────────────────────────


class TestIdentity:
    def test_passthrough(self):
        assert identity(42) == 42
        assert identity("hello") == "hello"
        assert identity(None) is None


# ── strip ───────────────────────────────────────────────────────


class TestStrip:
    def test_strips_whitespace(self):
        assert strip("  hello  ") == "hello"

    def test_none_returns_empty(self):
        assert strip(None) == ""

    def test_number_to_string(self):
        assert strip(42) == "42"


# ── to_date ─────────────────────────────────────────────────────


class TestToDate:
    def test_datetime_object(self):
        dt = datetime(2024, 3, 15, 10, 30)
        assert to_date(dt) == "2024-03-15"

    def test_date_object(self):
        d = date(2024, 3, 15)
        assert to_date(d) == "2024-03-15"

    def test_iso_string(self):
        assert to_date("2024-03-15") == "2024-03-15"

    def test_uk_format(self):
        assert to_date("15/03/2024") == "2024-03-15"

    def test_excel_serial(self):
        # 45366 = 2024-03-15 in Excel serial dates
        result = to_date(45366)
        assert result == "2024-03-15"

    def test_none(self):
        assert to_date(None) is None


# ── to_number ───────────────────────────────────────────────────


class TestToNumber:
    def test_int(self):
        assert to_number(42) == 42.0

    def test_float(self):
        assert to_number(3.14) == 3.14

    def test_string(self):
        assert to_number("123.45") == 123.45

    def test_currency(self):
        assert to_number("£1,234.56") == 1234.56

    def test_negative_parens(self):
        assert to_number("(100)") == -100.0

    def test_none(self):
        assert to_number(None) is None

    def test_invalid(self):
        assert to_number("not a number") is None


# ── to_integer ──────────────────────────────────────────────────


class TestToInteger:
    def test_int(self):
        assert to_integer(42) == 42

    def test_float_rounds(self):
        assert to_integer(42.7) == 43

    def test_string(self):
        assert to_integer("100") == 100

    def test_none(self):
        assert to_integer(None) is None


# ── to_boolean ──────────────────────────────────────────────────


class TestToBoolean:
    def test_true_values(self):
        assert to_boolean(True) is True
        assert to_boolean("yes") is True
        assert to_boolean("Y") is True
        assert to_boolean("1") is True
        assert to_boolean(1) is True

    def test_false_values(self):
        assert to_boolean(False) is False
        assert to_boolean("no") is False
        assert to_boolean("N") is False
        assert to_boolean("0") is False
        assert to_boolean(0) is False

    def test_none(self):
        assert to_boolean(None) is None

    def test_unknown(self):
        assert to_boolean("maybe") is None


# ── to_string ───────────────────────────────────────────────────


class TestToString:
    def test_number(self):
        assert to_string(42) == "42"

    def test_none(self):
        assert to_string(None) == ""


# ── split_comma ─────────────────────────────────────────────────


class TestSplitComma:
    def test_basic(self):
        assert split_comma("a, b, c") == ["a", "b", "c"]

    def test_none(self):
        assert split_comma(None) == []

    def test_empty_parts(self):
        assert split_comma("a,,b") == ["a", "b"]


# ── regex_extract ───────────────────────────────────────────────


class TestRegexExtract:
    def test_basic_group(self):
        result = regex_extract(
            "Order #12345", params={"pattern": r"#(\d+)", "group": 1}
        )
        assert result == "12345"

    def test_no_match(self):
        result = regex_extract("no numbers", params={"pattern": r"(\d+)"})
        assert result is None

    def test_none(self):
        assert regex_extract(None) is None

    def test_no_pattern(self):
        assert regex_extract("hello") == "hello"

    def test_default_group(self):
        result = regex_extract("abc123def", params={"pattern": r"(\d+)"})
        assert result == "123"


# ── concat ──────────────────────────────────────────────────────


class TestConcat:
    def test_basic(self):
        result = concat(
            "John",
            params={"separator": " ", "other_cols": ["B"]},
            row_data={"A": "John", "B": "Doe"},
        )
        assert result == "John Doe"

    def test_no_row_data(self):
        result = concat("hello", params={"separator": "-", "other_cols": ["B"]})
        assert result == "hello"

    def test_none_value(self):
        result = concat(None, params={"separator": " "})
        assert result == ""

    def test_custom_separator(self):
        result = concat(
            "a",
            params={"separator": ", ", "other_cols": ["B", "C"]},
            row_data={"B": "b", "C": "c"},
        )
        assert result == "a, b, c"


# ── conditional ─────────────────────────────────────────────────


class TestConditional:
    def test_is_empty_true(self):
        result = conditional(
            None,
            params={"condition": "is_empty", "true_value": "YES", "false_value": "NO"},
        )
        assert result == "YES"

    def test_is_empty_false(self):
        result = conditional(
            "data",
            params={"condition": "is_empty", "true_value": "YES", "false_value": "NO"},
        )
        assert result == "NO"

    def test_is_not_empty(self):
        result = conditional(
            "data",
            params={
                "condition": "is_not_empty",
                "true_value": "YES",
                "false_value": "NO",
            },
        )
        assert result == "YES"

    def test_equals(self):
        result = conditional(
            "Active",
            params={
                "condition": "equals",
                "compare_value": "active",
                "true_value": "1",
                "false_value": "0",
            },
        )
        assert result == "1"

    def test_equals_no_match(self):
        result = conditional(
            "Inactive",
            params={
                "condition": "equals",
                "compare_value": "active",
                "true_value": "1",
                "false_value": "0",
            },
        )
        assert result == "0"


# ── uppercase / lowercase ──────────────────────────────────────


class TestUppercase:
    def test_basic(self):
        assert uppercase("hello") == "HELLO"

    def test_none(self):
        assert uppercase(None) == ""


class TestLowercase:
    def test_basic(self):
        assert lowercase("HELLO") == "hello"

    def test_none(self):
        assert lowercase(None) == ""


# ── default_value ───────────────────────────────────────────────


class TestDefaultValue:
    def test_with_value(self):
        assert default_value("actual", params={"default": "fallback"}) == "actual"

    def test_none_uses_default(self):
        assert default_value(None, params={"default": "fallback"}) == "fallback"

    def test_empty_uses_default(self):
        assert default_value("  ", params={"default": "fallback"}) == "fallback"


# ── trim_whitespace ─────────────────────────────────────────────


class TestTrimWhitespace:
    def test_basic(self):
        assert trim_whitespace("  hello   world  ") == "hello world"

    def test_none(self):
        assert trim_whitespace(None) == ""

    def test_tabs_newlines(self):
        assert trim_whitespace("hello\t\n  world") == "hello world"


# ── substring ───────────────────────────────────────────────────


class TestSubstring:
    def test_basic(self):
        assert substring("hello world", params={"start": 0, "end": 5}) == "hello"

    def test_none(self):
        assert substring(None) == ""

    def test_no_end(self):
        assert substring("hello world", params={"start": 6}) == "world"


# ── apply_transform ─────────────────────────────────────────────


class TestApplyTransform:
    def test_all_simple_transforms_in_registry(self):
        expected = {
            "identity",
            "strip",
            "to_date",
            "to_number",
            "to_boolean",
            "to_string",
            "split_comma",
            "to_integer",
            "uppercase",
            "lowercase",
            "trim_whitespace",
        }
        assert set(TRANSFORM_REGISTRY.keys()) == expected

    def test_all_parameterised_transforms(self):
        expected = {"regex_extract", "default_value", "substring", "conditional"}
        assert set(PARAMETERISED_TRANSFORMS.keys()) == expected

    def test_all_row_aware_transforms(self):
        expected = {"concat"}
        assert set(ROW_AWARE_TRANSFORMS.keys()) == expected

    def test_apply_strip(self):
        assert apply_transform("strip", "  hello  ") == "hello"

    def test_apply_regex_extract(self):
        result = apply_transform("regex_extract", "ID-42", params={"pattern": r"(\d+)"})
        assert result == "42"

    def test_apply_concat_with_row(self):
        result = apply_transform(
            "concat",
            "a",
            params={"separator": "-", "other_cols": ["B"]},
            row_data={"A": "a", "B": "b"},
        )
        assert result == "a-b"

    def test_unknown_transform_raises(self):
        with pytest.raises(KeyError):
            apply_transform("nonexistent", "value")
