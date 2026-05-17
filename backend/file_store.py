"""File storage — ADLS Gen2 with local filesystem fallback.

Stores uploaded Excel files for re-processing and audit purposes.
Files are stored keyed by user ID and file hash.

ADLS Gen2 files should have a 7-day lifecycle management policy configured
on the storage account (see docs/azure-openai-config.md for details).
Local dev fallback stores files in ./uploads/ and cleans up on read if expired.
"""

from __future__ import annotations

import logging
import shutil
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

from backend.config import settings

logger = logging.getLogger(__name__)

LOCAL_UPLOADS_DIR = Path("uploads")


class LocalFileStore:
    """Local filesystem fallback for development."""

    def __init__(self, base_dir: Path = LOCAL_UPLOADS_DIR):
        self._base_dir = base_dir
        self._base_dir.mkdir(parents=True, exist_ok=True)

    def _file_path(self, user_id: str, file_hash: str) -> Path:
        user_dir = self._base_dir / user_id
        user_dir.mkdir(parents=True, exist_ok=True)
        return user_dir / f"{file_hash}.xlsx"

    def store_file(self, user_id: str, file_hash: str, file_bytes: bytes) -> str:
        """Store a file and return the storage path."""
        path = self._file_path(user_id, file_hash)
        if path.exists():
            logger.debug("File already stored locally: %s", path)
            return str(path)
        path.write_bytes(file_bytes)
        logger.info("Stored file locally: %s (%d bytes)", path, len(file_bytes))
        return str(path)

    def retrieve_file(self, user_id: str, file_hash: str) -> bytes | None:
        """Retrieve a file by user ID and hash. Returns None if not found or expired."""
        path = self._file_path(user_id, file_hash)
        if not path.exists():
            return None

        # Check local retention
        mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
        age = datetime.now(timezone.utc) - mtime
        if age > timedelta(days=settings.adls_retention_days):
            logger.info("Local file expired (age=%s): %s", age, path)
            path.unlink(missing_ok=True)
            return None

        return path.read_bytes()

    def file_exists(self, user_id: str, file_hash: str) -> bool:
        """Check if a file exists and is not expired."""
        path = self._file_path(user_id, file_hash)
        if not path.exists():
            return False
        mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
        age = datetime.now(timezone.utc) - mtime
        if age > timedelta(days=settings.adls_retention_days):
            path.unlink(missing_ok=True)
            return False
        return True

    def get_storage_path(self, user_id: str, file_hash: str) -> str:
        """Return the storage path/URI for a file."""
        return str(self._file_path(user_id, file_hash))


class ADLSFileStore:
    """Azure Data Lake Storage Gen2 file store."""

    def __init__(self):
        from azure.storage.filedatalake import DataLakeServiceClient

        self._service_client = DataLakeServiceClient(
            account_url=f"https://{settings.adls_account_name}.dfs.core.windows.net",
            credential=settings.adls_account_key,
        )
        self._filesystem_client = self._service_client.get_file_system_client(
            file_system=settings.adls_filesystem
        )
        # Ensure the filesystem exists
        try:
            self._filesystem_client.get_file_system_properties()
        except Exception:
            self._filesystem_client.create_file_system()
            logger.info("Created ADLS filesystem: %s", settings.adls_filesystem)

        logger.info(
            "Connected to ADLS Gen2: %s/%s",
            settings.adls_account_name,
            settings.adls_filesystem,
        )

    def _blob_path(self, user_id: str, file_hash: str) -> str:
        return f"{user_id}/{file_hash}.xlsx"

    def store_file(self, user_id: str, file_hash: str, file_bytes: bytes) -> str:
        """Store a file in ADLS Gen2. Returns the blob path."""
        blob_path = self._blob_path(user_id, file_hash)

        # Check if already exists
        try:
            file_client = self._filesystem_client.get_file_client(blob_path)
            file_client.get_file_properties()
            logger.debug("File already exists in ADLS: %s", blob_path)
            return blob_path
        except Exception:
            pass

        # Upload
        file_client = self._filesystem_client.create_file(blob_path)
        file_client.append_data(file_bytes, offset=0, length=len(file_bytes))
        file_client.flush_data(len(file_bytes))
        logger.info("Stored file in ADLS: %s (%d bytes)", blob_path, len(file_bytes))
        return blob_path

    def retrieve_file(self, user_id: str, file_hash: str) -> bytes | None:
        """Retrieve a file from ADLS Gen2. Returns None if not found."""
        blob_path = self._blob_path(user_id, file_hash)
        try:
            file_client = self._filesystem_client.get_file_client(blob_path)
            download = file_client.download_file()
            return download.readall()
        except Exception:
            return None

    def file_exists(self, user_id: str, file_hash: str) -> bool:
        """Check if a file exists in ADLS Gen2."""
        blob_path = self._blob_path(user_id, file_hash)
        try:
            file_client = self._filesystem_client.get_file_client(blob_path)
            file_client.get_file_properties()
            return True
        except Exception:
            return False

    def get_storage_path(self, user_id: str, file_hash: str) -> str:
        """Return the ADLS blob path."""
        return self._blob_path(user_id, file_hash)


def get_file_store() -> LocalFileStore | ADLSFileStore:
    """Return the appropriate file store based on configuration."""
    if settings.adls_available:
        try:
            return ADLSFileStore()
        except Exception as e:
            logger.warning(
                "Failed to connect to ADLS Gen2, falling back to local: %s", e
            )
            return LocalFileStore()
    else:
        logger.info("ADLS Gen2 not configured, using local file storage")
        return LocalFileStore()
