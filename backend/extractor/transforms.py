"""Pure transform functions — one per Transform enum value.

Each function takes a single cell value and returns the transformed value.
No LLM calls, no side effects, no imports beyond stdlib.
"""

from __future__ import annotations

import re
from datetime import datetime, date
from typing import Any, Callable


def identity(value: Any) -> Any:
    """Return the value unchanged."""
    return value


def strip(value: Any) -> str:
    """Convert to string and strip leading/trailing whitespace."""
    if value is None:
        return ""
    return str(value).strip()


def to_date(value: Any) -> str | None:
    """Convert to an ISO-8601 date string (YYYY-MM-DD).

    Handles:
    - datetime / date objects (from openpyxl)
    - Strings in common formats: YYYY-MM-DD, DD/MM/YYYY, DD-MM-YYYY, MM/DD/YYYY
    - Excel serial date numbers
    """
    if value is None:
        return None

    # Already a date/datetime object
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()

    # Excel serial date number
    if isinstance(value, (int, float)):
        try:
            serial = int(value)
            if 1 <= serial <= 2958465:  # valid Excel date range
                # Excel epoch is 1899-12-30 (accounting for the 1900 leap year bug)
                from datetime import timedelta

                base = date(1899, 12, 30)
                return (base + timedelta(days=serial)).isoformat()
        except (ValueError, OverflowError):
            pass

    # String parsing
    s = str(value).strip()
    formats = [
        "%Y-%m-%d",
        "%d/%m/%Y",
        "%d-%m-%Y",
        "%m/%d/%Y",
        "%Y/%m/%d",
        "%d %b %Y",
        "%d %B %Y",
        "%Y-%m-%dT%H:%M:%S",
    ]
    for fmt in formats:
        try:
            return datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            continue

    # Last resort — return the string as-is
    return s


def to_number(value: Any) -> float | None:
    """Convert to a float.

    Handles: numeric types, strings with commas/currency symbols.
    """
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)

    s = str(value).strip()
    # Remove common currency symbols and thousands separators
    s = re.sub(r"[£$€¥,\s]", "", s)
    # Handle parentheses as negative: (123.45) → -123.45
    if s.startswith("(") and s.endswith(")"):
        s = "-" + s[1:-1]

    try:
        return float(s)
    except ValueError:
        return None


def to_integer(value: Any) -> int | None:
    """Convert to an integer.

    Rounds floats. Parses strings after cleaning.
    """
    num = to_number(value)
    if num is None:
        return None
    return round(num)


def to_boolean(value: Any) -> bool | None:
    """Convert to a boolean.

    Truthy: True, 1, "true", "yes", "y", "1"
    Falsy:  False, 0, "false", "no", "n", "0"
    """
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)

    s = str(value).strip().lower()
    if s in ("true", "yes", "y", "1"):
        return True
    if s in ("false", "no", "n", "0"):
        return False
    return None


def to_string(value: Any) -> str:
    """Convert any value to its string representation."""
    if value is None:
        return ""
    return str(value)


def split_comma(value: Any) -> list[str]:
    """Split a string by commas and strip each element."""
    if value is None:
        return []
    return [part.strip() for part in str(value).split(",") if part.strip()]


def regex_extract(value: Any, params: dict | None = None) -> str | None:
    """Extract a substring using a regex pattern.

    Params:
        pattern (str): The regex pattern. Must contain at least one group.
        group (int): Which capture group to return (default 1).
    """
    if value is None:
        return None
    params = params or {}
    pattern = params.get("pattern", "")
    group = params.get("group", 1)
    if not pattern:
        return str(value)
    match = re.search(pattern, str(value))
    if match:
        try:
            return match.group(group)
        except IndexError:
            return match.group(0)
    return None


def concat(value: Any, params: dict | None = None, row_data: dict | None = None) -> str:
    """Concatenate this column's value with values from other columns.

    Params:
        separator (str): Separator between values (default " ").
        other_cols (list[str]): Column letters to concatenate with.
    """
    params = params or {}
    separator = params.get("separator", " ")
    other_cols = params.get("other_cols", [])

    parts = [str(value) if value is not None else ""]
    if row_data:
        for col in other_cols:
            other_val = row_data.get(col)
            parts.append(str(other_val) if other_val is not None else "")

    return separator.join(parts)


def conditional(value: Any, params: dict | None = None) -> Any:
    """Apply a simple conditional transform.

    Params:
        condition (str): One of "is_empty", "is_not_empty", "equals".
        compare_value (str): Value to compare against (for "equals").
        true_value (str): Value to return if condition is true.
        false_value (str): Value to return if condition is false.
    """
    params = params or {}
    condition = params.get("condition", "is_empty")
    compare_value = params.get("compare_value", "")
    true_value = params.get("true_value", "")
    false_value = params.get("false_value", "")

    if condition == "is_empty":
        result = value is None or str(value).strip() == ""
    elif condition == "is_not_empty":
        result = value is not None and str(value).strip() != ""
    elif condition == "equals":
        result = str(value).strip().lower() == str(compare_value).strip().lower()
    else:
        result = False

    return true_value if result else false_value


def uppercase(value: Any) -> str:
    """Convert to uppercase string."""
    if value is None:
        return ""
    return str(value).upper()


def lowercase(value: Any) -> str:
    """Convert to lowercase string."""
    if value is None:
        return ""
    return str(value).lower()


def default_value(value: Any, params: dict | None = None) -> Any:
    """Return the value, or a default if the value is None or empty.

    Params:
        default (Any): The default value to use.
    """
    params = params or {}
    default_val = params.get("default", "")
    if value is None or str(value).strip() == "":
        return default_val
    return value


def trim_whitespace(value: Any) -> str:
    """Strip whitespace and collapse internal whitespace to single spaces."""
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def substring(value: Any, params: dict | None = None) -> str:
    """Extract a substring by start and end index.

    Params:
        start (int): Start index (default 0).
        end (int): End index (default: end of string).
    """
    if value is None:
        return ""
    params = params or {}
    s = str(value)
    start = params.get("start", 0)
    end = params.get("end", len(s))
    return s[start:end]


# ── Registry ────────────────────────────────────────────────────

# Simple transforms (value only)
TRANSFORM_REGISTRY: dict[str, Callable] = {
    "identity": identity,
    "strip": strip,
    "to_date": to_date,
    "to_number": to_number,
    "to_boolean": to_boolean,
    "to_string": to_string,
    "split_comma": split_comma,
    "to_integer": to_integer,
    "uppercase": uppercase,
    "lowercase": lowercase,
    "trim_whitespace": trim_whitespace,
}

# Parameterised transforms (value + params)
PARAMETERISED_TRANSFORMS: dict[str, Callable] = {
    "regex_extract": regex_extract,
    "default_value": default_value,
    "substring": substring,
    "conditional": conditional,
}

# Row-aware transforms (value + params + full row data)
ROW_AWARE_TRANSFORMS: dict[str, Callable] = {
    "concat": concat,
}


def apply_transform(
    transform_name: str,
    value: Any,
    params: dict | None = None,
    row_data: dict | None = None,
) -> Any:
    """Look up and apply a transform by name.

    Args:
        transform_name: Name of the transform.
        value: The cell value to transform.
        params: Optional parameters for parameterised transforms.
        row_data: Optional full row data for row-aware transforms (e.g. concat).

    Raises KeyError if the transform name is not in any registry.
    """
    if transform_name in TRANSFORM_REGISTRY:
        return TRANSFORM_REGISTRY[transform_name](value)
    elif transform_name in PARAMETERISED_TRANSFORMS:
        return PARAMETERISED_TRANSFORMS[transform_name](value, params=params)
    elif transform_name in ROW_AWARE_TRANSFORMS:
        return ROW_AWARE_TRANSFORMS[transform_name](
            value, params=params, row_data=row_data
        )
    else:
        raise KeyError(f"Unknown transform: {transform_name}")
