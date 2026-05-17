"""Cache and schema library — Cosmos DB with local JSON file fallback.

Two concerns live here:
1. Results cache: keyed by sha256(excel_bytes)[:16] + schema_id.
2. Schema library: CRUD for user-scoped schema definitions.

When Cosmos credentials are absent (local dev), everything falls back to
a JSON file at ./local_cache.json.
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.config import settings
from backend.models import IngestResponse, SchemaDefinition

logger = logging.getLogger(__name__)

LOCAL_CACHE_PATH = Path("local_cache.json")


# ── Helpers ─────────────────────────────────────────────────────────


def _cache_key(excel_hash: str, schema_id: str) -> str:
    """Build a cache key from the file hash and schema ID."""
    return f"{excel_hash}_{schema_id}"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Local JSON fallback ────────────────────────────────────────────


class LocalStore:
    """Simple JSON file-backed store for local development."""

    def __init__(self, path: Path = LOCAL_CACHE_PATH):
        self._path = path
        self._data: dict[str, Any] = {
            "results": {},
            "schemas": {},
            "schema_history": {},
        }
        self._load()

    def _load(self):
        if self._path.exists():
            try:
                self._data = json.loads(self._path.read_text())
                # Ensure schema_history key exists for backwards compat
                if "schema_history" not in self._data:
                    self._data["schema_history"] = {}
            except (json.JSONDecodeError, OSError):
                logger.warning("Could not read local cache file, starting fresh")
                self._data = {"results": {}, "schemas": {}, "schema_history": {}}

    def _save(self):
        self._path.write_text(json.dumps(self._data, indent=2, default=str))

    # Results
    def get_result(self, excel_hash: str, schema_id: str) -> dict | None:
        key = _cache_key(excel_hash, schema_id)
        return self._data["results"].get(key)

    def save_result(self, excel_hash: str, schema_id: str, result: dict):
        key = _cache_key(excel_hash, schema_id)
        result["cached"] = True
        result["created_at"] = _now()
        self._data["results"][key] = result
        self._save()

    def invalidate_by_schema(self, schema_id: str):
        """Remove all cached results linked to a schema."""
        to_delete = [k for k in self._data["results"] if k.endswith(f"_{schema_id}")]
        for k in to_delete:
            del self._data["results"][k]
        if to_delete:
            self._save()
            logger.info(
                "Invalidated %d cached results for schema %s", len(to_delete), schema_id
            )

    # Schemas
    def list_schemas(self, user_id: str) -> list[dict]:
        return [
            s for s in self._data["schemas"].values() if s.get("user_id") == user_id
        ]

    def get_schema(self, schema_id: str) -> dict | None:
        return self._data["schemas"].get(schema_id)

    def get_schema_version(self, schema_id: str, version: int) -> dict | None:
        """Retrieve a specific historical version of a schema."""
        history = self._data["schema_history"].get(schema_id, [])
        for entry in history:
            if entry.get("version") == version:
                return entry
        return None

    def get_schema_history(self, schema_id: str) -> list[dict]:
        """Return all historical versions of a schema."""
        return self._data["schema_history"].get(schema_id, [])

    def _archive_schema_version(self, schema: dict):
        """Store a snapshot of the schema in version history."""
        schema_id = schema["id"]
        if schema_id not in self._data["schema_history"]:
            self._data["schema_history"][schema_id] = []
        self._data["schema_history"][schema_id].append(dict(schema))

    def save_schema(self, schema: dict) -> dict:
        if not schema.get("id"):
            schema["id"] = f"scm_{uuid.uuid4().hex[:12]}"
        schema["version"] = schema.get("version", 1)
        schema["created_at"] = schema.get("created_at") or _now()
        schema["updated_at"] = _now()
        self._data["schemas"][schema["id"]] = schema
        self._archive_schema_version(schema)
        self._save()
        return schema

    def update_schema(self, schema_id: str, schema: dict) -> dict | None:
        if schema_id not in self._data["schemas"]:
            return None
        existing = self._data["schemas"][schema_id]
        schema["id"] = schema_id
        schema["user_id"] = existing["user_id"]
        schema["version"] = existing.get("version", 1) + 1
        schema["created_at"] = existing.get("created_at", _now())
        schema["updated_at"] = _now()
        self._data["schemas"][schema_id] = schema
        self._archive_schema_version(schema)
        self._save()
        # Invalidate cached results for this schema
        self.invalidate_by_schema(schema_id)
        return schema

    def delete_schema(self, schema_id: str) -> bool:
        if schema_id in self._data["schemas"]:
            del self._data["schemas"][schema_id]
            self.invalidate_by_schema(schema_id)
            self._save()
            return True
        return False


# ── Cosmos DB store ─────────────────────────────────────────────────


class CosmosStore:
    """Azure Cosmos DB-backed store."""

    def __init__(self):
        from azure.cosmos import CosmosClient, PartitionKey

        self._client = CosmosClient(settings.cosmos_endpoint, settings.cosmos_key)
        self._database = self._client.get_database_client(settings.cosmos_database)
        self._container = self._database.get_container_client(settings.cosmos_container)
        logger.info(
            "Connected to Cosmos DB: %s/%s",
            settings.cosmos_database,
            settings.cosmos_container,
        )

    # Results
    def get_result(self, excel_hash: str, schema_id: str) -> dict | None:
        key = _cache_key(excel_hash, schema_id)
        try:
            item = self._container.read_item(item=key, partition_key=key)
            return item.get("data")
        except Exception:
            return None

    def save_result(self, excel_hash: str, schema_id: str, result: dict):
        key = _cache_key(excel_hash, schema_id)
        result["cached"] = True
        result["created_at"] = _now()
        self._container.upsert_item(
            {
                "id": key,
                "type": "result",
                "excel_hash": excel_hash,
                "schema_id": schema_id,
                "data": result,
            }
        )

    def invalidate_by_schema(self, schema_id: str):
        """Remove all cached results linked to a schema."""
        query = "SELECT * FROM c WHERE c.type = 'result' AND c.schema_id = @sid"
        items = list(
            self._container.query_items(
                query=query,
                parameters=[{"name": "@sid", "value": schema_id}],
                enable_cross_partition_query=True,
            )
        )
        for item in items:
            self._container.delete_item(item=item["id"], partition_key=item["id"])
        if items:
            logger.info(
                "Invalidated %d cached results for schema %s", len(items), schema_id
            )

    # Schemas
    def list_schemas(self, user_id: str) -> list[dict]:
        query = "SELECT * FROM c WHERE c.type = 'schema' AND c.data.user_id = @uid"
        items = list(
            self._container.query_items(
                query=query,
                parameters=[{"name": "@uid", "value": user_id}],
                enable_cross_partition_query=True,
            )
        )
        return [item["data"] for item in items]

    def get_schema(self, schema_id: str) -> dict | None:
        try:
            item = self._container.read_item(
                item=f"schema_{schema_id}", partition_key=f"schema_{schema_id}"
            )
            return item.get("data")
        except Exception:
            return None

    def get_schema_version(self, schema_id: str, version: int) -> dict | None:
        """Retrieve a specific historical version of a schema."""
        try:
            item = self._container.read_item(
                item=f"schema_history_{schema_id}_v{version}",
                partition_key=f"schema_history_{schema_id}_v{version}",
            )
            return item.get("data")
        except Exception:
            return None

    def get_schema_history(self, schema_id: str) -> list[dict]:
        """Return all historical versions of a schema."""
        query = (
            "SELECT * FROM c WHERE c.type = 'schema_history' "
            "AND c.schema_id = @sid ORDER BY c.data.version ASC"
        )
        items = list(
            self._container.query_items(
                query=query,
                parameters=[{"name": "@sid", "value": schema_id}],
                enable_cross_partition_query=True,
            )
        )
        return [item["data"] for item in items]

    def _archive_schema_version(self, schema: dict):
        """Store a snapshot of the schema in version history."""
        schema_id = schema["id"]
        version = schema.get("version", 1)
        self._container.upsert_item(
            {
                "id": f"schema_history_{schema_id}_v{version}",
                "type": "schema_history",
                "schema_id": schema_id,
                "data": schema,
            }
        )

    def save_schema(self, schema: dict) -> dict:
        if not schema.get("id"):
            schema["id"] = f"scm_{uuid.uuid4().hex[:12]}"
        schema["version"] = schema.get("version", 1)
        schema["created_at"] = schema.get("created_at") or _now()
        schema["updated_at"] = _now()
        self._container.upsert_item(
            {
                "id": f"schema_{schema['id']}",
                "type": "schema",
                "data": schema,
            }
        )
        self._archive_schema_version(schema)
        return schema

    def update_schema(self, schema_id: str, schema: dict) -> dict | None:
        existing = self.get_schema(schema_id)
        if existing is None:
            return None
        schema["id"] = schema_id
        schema["user_id"] = existing["user_id"]
        schema["version"] = existing.get("version", 1) + 1
        schema["created_at"] = existing.get("created_at", _now())
        schema["updated_at"] = _now()
        self._container.upsert_item(
            {
                "id": f"schema_{schema_id}",
                "type": "schema",
                "data": schema,
            }
        )
        self._archive_schema_version(schema)
        # Invalidate cached results for this schema
        self.invalidate_by_schema(schema_id)
        return schema

    def delete_schema(self, schema_id: str) -> bool:
        try:
            self._container.delete_item(
                item=f"schema_{schema_id}",
                partition_key=f"schema_{schema_id}",
            )
            self.invalidate_by_schema(schema_id)
            return True
        except Exception:
            return False


# ── Factory ─────────────────────────────────────────────────────────


def get_store() -> LocalStore | CosmosStore:
    """Return the appropriate store based on configuration."""
    if settings.cosmos_available:
        try:
            return CosmosStore()
        except Exception as e:
            logger.warning(
                "Failed to connect to Cosmos DB, falling back to local: %s", e
            )
            return LocalStore()
    else:
        logger.info("Cosmos DB not configured, using local JSON cache")
        return LocalStore()
