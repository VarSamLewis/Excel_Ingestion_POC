"""Structured logging and metrics for Azure Log Analytics.

Provides:
1. A JSON formatter for structured log output.
2. An Azure Log Analytics handler that ships logs to a Log Analytics workspace.
3. A metrics helper for recording key operational data points.

When Log Analytics credentials are not configured, falls back to stdout JSON logging.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import time
from datetime import datetime, timezone
from typing import Any
from urllib import request as urllib_request

from backend.config import settings

logger = logging.getLogger(__name__)

LOG_TYPE = "ExcelIngestion"  # Log Analytics custom log table name


# ── JSON Formatter ──────────────────────────────────────────────────


class StructuredJsonFormatter(logging.Formatter):
    """Format log records as single-line JSON for structured logging."""

    def format(self, record: logging.LogRecord) -> str:
        log_entry = {
            "timestamp": datetime.fromtimestamp(
                record.created, tz=timezone.utc
            ).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }

        # Include exception info if present
        if record.exc_info and record.exc_info[1]:
            log_entry["exception"] = self.formatException(record.exc_info)

        # Include any extra fields added via logger.info("msg", extra={...})
        for key in (
            "event",
            "metrics",
            "duration_ms",
            "user_id",
            "schema_id",
            "file_hash",
            "sheet_name",
            "row_count",
            "confidence",
            "cache_hit",
            "transform",
            "error_type",
        ):
            if hasattr(record, key):
                log_entry[key] = getattr(record, key)

        return json.dumps(log_entry, default=str)


# ── Azure Log Analytics Handler ─────────────────────────────────────


class LogAnalyticsHandler(logging.Handler):
    """Send log records to Azure Log Analytics via the HTTP Data Collector API."""

    def __init__(
        self,
        workspace_id: str,
        shared_key: str,
        log_type: str = LOG_TYPE,
    ):
        super().__init__()
        self._workspace_id = workspace_id
        self._shared_key = shared_key
        self._log_type = log_type
        self._url = (
            f"https://{workspace_id}.ods.opinsights.azure.com"
            f"/api/logs?api-version=2016-04-01"
        )

    def _build_signature(self, date: str, content_length: int) -> str:
        """Build the authorization signature for Log Analytics."""
        string_to_sign = (
            f"POST\n{content_length}\napplication/json\nx-ms-date:{date}\n/api/logs"
        )
        decoded_key = base64.b64decode(self._shared_key)
        encoded_hash = base64.b64encode(
            hmac.new(
                decoded_key, string_to_sign.encode("utf-8"), digestmod=hashlib.sha256
            ).digest()
        ).decode("utf-8")
        return f"SharedKey {self._workspace_id}:{encoded_hash}"

    def emit(self, record: logging.LogRecord):
        """Send a log record to Log Analytics."""
        try:
            log_entry = {
                "Timestamp": datetime.fromtimestamp(
                    record.created, tz=timezone.utc
                ).isoformat(),
                "Level": record.levelname,
                "Logger": record.name,
                "Message": record.getMessage(),
                "Module": record.module,
                "Function": record.funcName,
            }

            # Add structured fields
            for key in (
                "event",
                "metrics",
                "duration_ms",
                "user_id",
                "schema_id",
                "file_hash",
                "sheet_name",
                "row_count",
                "confidence",
                "cache_hit",
                "transform",
                "error_type",
            ):
                if hasattr(record, key):
                    val = getattr(record, key)
                    # Log Analytics doesn't accept nested dicts in all cases
                    if isinstance(val, dict):
                        log_entry[key] = json.dumps(val, default=str)
                    else:
                        log_entry[key] = val

            if record.exc_info and record.exc_info[1]:
                log_entry["Exception"] = self.format(record)

            body = json.dumps([log_entry], default=str)
            rfc1123_date = datetime.now(timezone.utc).strftime(
                "%a, %d %b %Y %H:%M:%S GMT"
            )
            signature = self._build_signature(rfc1123_date, len(body))

            req = urllib_request.Request(self._url, data=body.encode("utf-8"))
            req.add_header("Content-Type", "application/json")
            req.add_header("Authorization", signature)
            req.add_header("Log-Type", self._log_type)
            req.add_header("x-ms-date", rfc1123_date)
            req.add_header("time-generated-field", "Timestamp")

            urllib_request.urlopen(req, timeout=5)
        except Exception:
            # Never let logging failure crash the application
            self.handleError(record)


# ── Setup ───────────────────────────────────────────────────────────


def configure_logging():
    """Configure structured logging for the application.

    - Always uses JSON format to stdout.
    - Additionally ships to Azure Log Analytics when credentials are configured.
    """
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, settings.log_level.upper(), logging.INFO))

    # Clear any existing handlers to avoid duplicates on reload
    root_logger.handlers.clear()

    # Stdout handler with JSON formatting
    stdout_handler = logging.StreamHandler()
    stdout_handler.setFormatter(StructuredJsonFormatter())
    root_logger.addHandler(stdout_handler)

    # Azure Log Analytics handler (if configured)
    if settings.log_analytics_available:
        try:
            la_handler = LogAnalyticsHandler(
                workspace_id=settings.log_analytics_workspace_id,
                shared_key=settings.log_analytics_shared_key,
            )
            la_handler.setLevel(logging.INFO)
            root_logger.addHandler(la_handler)
            logger.info("Azure Log Analytics handler configured")
        except Exception as e:
            logger.warning("Failed to configure Log Analytics handler: %s", e)
    else:
        logger.info("Log Analytics not configured, using stdout JSON logging only")


# ── Metrics helpers ─────────────────────────────────────────────────


class OperationTimer:
    """Context manager for timing operations and logging the duration."""

    def __init__(self, operation: str, log: logging.Logger | None = None, **extra):
        self._operation = operation
        self._log = log or logger
        self._extra = extra
        self._start: float = 0

    def __enter__(self):
        self._start = time.perf_counter()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        duration_ms = (time.perf_counter() - self._start) * 1000
        extra = {
            "event": self._operation,
            "duration_ms": round(duration_ms, 2),
            **self._extra,
        }
        if exc_type:
            extra["error_type"] = exc_type.__name__
            self._log.error(
                "%s failed after %.1fms: %s",
                self._operation,
                duration_ms,
                exc_val,
                extra=extra,
            )
        else:
            self._log.info(
                "%s completed in %.1fms",
                self._operation,
                duration_ms,
                extra=extra,
            )
        return False  # Don't suppress exceptions


def log_event(
    event: str,
    log: logging.Logger | None = None,
    level: int = logging.INFO,
    **kwargs: Any,
):
    """Log a structured event with arbitrary key-value metadata."""
    log = log or logger
    extra = {"event": event, **kwargs}
    log.log(level, event, extra=extra)
