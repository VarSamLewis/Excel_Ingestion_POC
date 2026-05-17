"""Application configuration via pydantic-settings.

All values are read from environment variables (or a .env file in the backend/ directory).
"""

from pydantic_settings import BaseSettings
from pydantic import Field


class Settings(BaseSettings):
    """Central configuration – every env var the app needs."""

    # ── Azure OpenAI ────────────────────────────────────────────────
    azure_openai_endpoint: str = Field(
        default="", description="Azure OpenAI resource endpoint URL"
    )
    azure_openai_api_key: str = Field(default="", description="Azure OpenAI API key")
    azure_openai_mapper_deployment: str = Field(
        default="gpt-4o", description="Deployment name for the mapping model"
    )
    azure_openai_validator_deployment: str = Field(
        default="gpt-4o-mini", description="Deployment name for the validation model"
    )
    azure_openai_api_version: str = Field(
        default="2024-08-01-preview", description="Azure OpenAI API version"
    )

    # ── Azure Cosmos DB ─────────────────────────────────────────────
    cosmos_endpoint: str = Field(default="", description="Cosmos DB endpoint URL")
    cosmos_key: str = Field(default="", description="Cosmos DB primary key")
    cosmos_database: str = Field(
        default="excel_ingestion", description="Cosmos DB database name"
    )
    cosmos_container: str = Field(
        default="results", description="Cosmos DB container name"
    )

    # ── Azure Data Lake Storage Gen2 ────────────────────────────────
    adls_account_name: str = Field(
        default="", description="ADLS Gen2 storage account name"
    )
    adls_account_key: str = Field(
        default="", description="ADLS Gen2 storage account key"
    )
    adls_filesystem: str = Field(
        default="excel-uploads",
        description="ADLS Gen2 filesystem (container) name for uploaded files",
    )
    adls_retention_days: int = Field(
        default=7, description="Number of days to retain uploaded files"
    )

    # ── Azure Log Analytics ─────────────────────────────────────────
    log_analytics_workspace_id: str = Field(
        default="", description="Log Analytics workspace ID for structured logging"
    )
    log_analytics_shared_key: str = Field(
        default="", description="Log Analytics workspace shared key"
    )

    # ── Azure AD / Auth ─────────────────────────────────────────────
    azure_tenant_id: str = Field(default="", description="Azure AD tenant ID")
    azure_client_id: str = Field(
        default="", description="Azure AD app registration client ID"
    )

    # ── CORS ────────────────────────────────────────────────────────
    allowed_origins: str = Field(
        default="http://localhost:5173",
        description="Comma-separated list of allowed CORS origins",
    )

    # ── Misc ────────────────────────────────────────────────────────
    api_key: str = Field(
        default="", description="Optional API key for service-to-service calls"
    )
    log_level: str = Field(default="INFO", description="Logging level")

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "case_sensitive": False,
    }

    @property
    def cors_origins(self) -> list[str]:
        """Parse the comma-separated ALLOWED_ORIGINS string into a list."""
        return [o.strip() for o in self.allowed_origins.split(",") if o.strip()]

    @property
    def openai_available(self) -> bool:
        """True when Azure OpenAI credentials are configured."""
        return bool(self.azure_openai_endpoint and self.azure_openai_api_key)

    @property
    def cosmos_available(self) -> bool:
        """True when Cosmos DB credentials are configured."""
        return bool(self.cosmos_endpoint and self.cosmos_key)

    @property
    def adls_available(self) -> bool:
        """True when ADLS Gen2 credentials are configured."""
        return bool(self.adls_account_name and self.adls_account_key)

    @property
    def log_analytics_available(self) -> bool:
        """True when Log Analytics credentials are configured."""
        return bool(self.log_analytics_workspace_id and self.log_analytics_shared_key)

    @property
    def auth_enabled(self) -> bool:
        """True when Azure AD credentials are configured."""
        return bool(self.azure_tenant_id and self.azure_client_id)


settings = Settings()
