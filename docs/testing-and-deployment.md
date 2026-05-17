# Testing & Deployment Guide

## Prerequisites

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) (Python package manager)
- Node.js 18+
- Docker (for container builds)
- Azure CLI (`az`) with an active subscription

---

## Local Development

### Backend

```bash
cd backend
uv venv
source .venv/bin/activate
uv pip install -r requirements.txt

# Copy and edit env
cp ../.env.example .env
# At minimum set AZURE_OPENAI_ENDPOINT and AZURE_OPENAI_API_KEY

# Run
uv run uvicorn backend.main:app --reload --port 8000
```

### Frontend

```bash
cd frontend
npm install

# Copy and edit env
cp .env.example .env.local
# Set VITE_API_URL=http://localhost:8000

# Run
npm run dev
```

---

## Running Tests

```bash
cd backend
uv pip install pytest
uv run pytest tests/ -v
```

Tests run with auth and Cosmos disabled (local JSON fallback). The LLM calls are mocked in API tests; transform and model tests are pure unit tests.

---

## Azure Deployment

The repo includes `azure-pipelines.yml` which handles the full CI/CD pipeline:

```
push to main → test (pytest) → build & push to ACR → deploy to Container Apps → health check
```

### One-time Infrastructure Setup

Before the pipeline can run, you need to provision the Azure resources. These are one-time setup steps:

```bash
# Resource group
az group create --name excel-ingestion-rg --location uksouth

# Azure Container Registry
az acr create --name excelIngestionAcr --resource-group excel-ingestion-rg --sku Basic

# Azure OpenAI
az cognitiveservices account create \
  --name <openai-resource> \
  --resource-group excel-ingestion-rg \
  --location uksouth \
  --kind OpenAI \
  --sku S0

# Deploy models
az cognitiveservices account deployment create \
  --name <openai-resource> \
  --resource-group excel-ingestion-rg \
  --deployment-name gpt-4o \
  --model-name gpt-4o \
  --model-version "2024-08-06" \
  --model-format OpenAI \
  --sku-capacity 1 --sku-name "Standard"

az cognitiveservices account deployment create \
  --name <openai-resource> \
  --resource-group excel-ingestion-rg \
  --deployment-name gpt-4o-mini \
  --model-name gpt-4o-mini \
  --model-version "2024-07-18" \
  --model-format OpenAI \
  --sku-capacity 1 --sku-name "Standard"

# Cosmos DB
az cosmosdb create --name <cosmos-account> --resource-group excel-ingestion-rg --kind GlobalDocumentDB
az cosmosdb sql database create --account-name <cosmos-account> --resource-group excel-ingestion-rg --name excel_ingestion
az cosmosdb sql container create \
  --account-name <cosmos-account> --resource-group excel-ingestion-rg \
  --database-name excel_ingestion --name results \
  --partition-key-path "/id"

# ADLS Gen2
az storage account create \
  --name <storageaccount> \
  --resource-group excel-ingestion-rg \
  --kind StorageV2 \
  --sku Standard_LRS \
  --allow-blob-public-access false

az storage fs create \
  --name excel-uploads \
  --account-name <storageaccount> \
  --auth-mode login

# Container Apps environment
az containerapp env create \
  --name excel-ingestion-env \
  --resource-group excel-ingestion-rg \
  --location uksouth

# Container App (initial deploy — pipeline handles updates)
az containerapp create \
  --name excel-ingestion-api \
  --resource-group excel-ingestion-rg \
  --environment excel-ingestion-env \
  --image mcr.microsoft.com/azuredocs/containerapps-helloworld:latest \
  --target-port 8000 \
  --ingress external \
  --min-replicas 1
```

Configure the ADLS 7-day lifecycle policy (see `docs/azure-openai-config.md`).

### CI/CD Setup

1. Connect your repo to Azure DevOps
2. Create a pipeline from `azure-pipelines.yml`
3. Set the following secret variables in the pipeline:

| Variable | Value |
|---|---|
| `AZURE_OPENAI_API_KEY` | OpenAI resource key |
| `COSMOS_KEY` | Cosmos DB primary key |
| `ADLS_ACCOUNT_KEY` | Storage account key |
| `LOG_ANALYTICS_WORKSPACE_ID` | Log Analytics workspace ID |
| `LOG_ANALYTICS_SHARED_KEY` | Log Analytics workspace primary key |

4. Ensure the Azure service connection named `azure-service-connection` exists in your Azure DevOps project settings

### Frontend

Deploy the frontend to Azure Static Web Apps:

```bash
az staticwebapp create \
  --name ingest-frontend \
  --resource-group excel-ingestion-rg \
  --source <github-repo-url> \
  --branch main \
  --app-location frontend \
  --app-artifact-location dist

az staticwebapp appsettings set \
  --name ingest-frontend \
  --resource-group excel-ingestion-rg \
  --setting-names VITE_API_URL=https://<backend-fqdn>
```

---

## Verification

1. **Health check**: `curl https://<backend-fqdn>/health` → `{"status":"ok"}`
2. **Create a schema**: `POST /schemas` with a test schema
3. **Upload a file**: `POST /ingest` with a small `.xlsx` file
4. **Check logs**: Query the Log Analytics workspace:
   ```kql
   ExcelIngestion_CL
   | order TimeGenerated desc
   | take 50
   ```
5. **Verify file storage**: Check the ADLS filesystem for uploaded files (they should auto-delete after 7 days).
