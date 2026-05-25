
# The Build

**What it does:** A web portal for flexible Excel ingestion. Users define exactly what data
they want extracted — field names, types, and plain-English instructions to the LLM — then
upload any Excel file. GPT-4o infers how the Excel maps to that schema, the data is extracted
deterministically, and GPT-4o-mini sense-checks the output. Schemas are saved and reusable.
Results are cached by file hash so the same Excel never hits the LLM twice.

---

## Stack

| Layer | Technology | Why |
|---|---|---|
| Backend | FastAPI on Azure Container Apps | Ecosurety's exact infra |
| LLM (mapping) | Azure OpenAI GPT-4o | Best structural reasoning |
| LLM (validation) | Azure OpenAI GPT-4o-mini | Cheap sense-check on a sample |
| Cache + Schemas | Azure Cosmos DB | Hash-keyed results + saved schema library |
| Auth | Azure AD App Registration + MSAL | Free, personal tenant, ~15min setup |
| CI/CD | Azure DevOps Pipelines | Ecosurety's exact tooling |
| Frontend | React + Vite | No framework overhead |

---

## Key Design Decisions

**LLM fills config, your code does the work.**
GPT-4o returns a constrained mapping JSON — which sheet, which header row, which column maps
to which field, which transform to apply. It cannot invent a transform, pick a library, or
write code. Your deterministic engine interprets the config.

**Transform enum is fixed.**
The LLM picks from: `identity | strip | to_date | to_number | to_boolean | to_string |
split_comma | to_integer`. Pydantic rejects anything else before it reaches the extractor.

**The field description is the LLM instruction.**
Users write plain English in each field's description — "full legal name of the company,
may appear as 'client', 'buyer' or 'account name'". This is what GPT-4o acts on. The UI
makes this explicit: descriptions are labelled "Instruction to the AI" and the placeholder
text coaches users to be specific and list alternative column names.

**Schemas are saved and reusable.**
A user who defines a schema for a supplier's format saves it by name ("Acme Q1 Report").
Next month, they load it from their schema library, upload the new file, and run. Schema
definitions are stored in Cosmos DB, scoped to the authenticated user by their Azure AD `oid`.

**Manual mapping override before extraction.**
After GPT-4o returns its mapping, users see the inferred config before data is extracted.
They can correct a wrong column assignment inline and re-run extraction without hitting the
LLM again. This handles the case where the model picks the wrong column.

**Two-model validation.**
GPT-4o-mini sees 10 random output rows and returns a confidence score plus typed issues.
If confidence < 0.70 the response is flagged with a warning badge in the portal but still
returned — the user can inspect and decide.

**Caching is the primary cost control.**
Cache key: `sha256(excel_bytes)[:16] + schema_id`. Same file + same schema = free. If the
user edits a saved schema, the cache invalidates for all files linked to it.

**Lineage on every row.**
Each row carries `source_col`, `source_sheet`, `source_row`, `transform_applied` per field.

---

## User Flow

```
1. Open portal → sign in with Microsoft

2. Schema step
   ├── Load a saved schema from library      (returning user)
   └── Build a new schema in the editor      (new user / new format)
         ├── Name the schema
         ├── Add fields: name + type + instruction to AI
         └── Save to library (optional)

3. Upload step
   └── Drag-drop Excel file

4. Review step  ← NEW
   ├── See GPT-4o's inferred mapping + reasoning
   ├── Correct any wrong column assignments inline
   └── Confirm → run extraction (no second LLM call)

5. Results step
   ├── Paginated data table
   ├── Confidence badge + any validation issues
   └── Export as JSON
```

---

## File Structure

```
excel-ingestion/
│
├── azure-pipelines.yml
├── .env.example
│
├── backend/
│   ├── main.py                      # FastAPI routes only — no business logic
│   ├── config.py                    # All env vars via pydantic-settings
│   ├── models.py                    # Every input/output type + ExcelMapping schema
│   ├── excel_processor.py           # openpyxl: hash, cell extraction, sheet sampling
│   ├── cache.py                     # Cosmos DB: results cache + schema library
│   ├── requirements.txt
│   ├── Dockerfile
│   │
│   ├── llm/
│   │   ├── __init__.py
│   │   ├── prompts.py               # All prompt strings — single source of truth
│   │   ├── mapper.py                # GPT-4o call → validated ExcelMapping
│   │   └── validator.py             # GPT-4o-mini call → confidence score + issues
│   │
│   └── extractor/
│       ├── __init__.py
│       ├── transforms.py            # Pure functions: strip(), to_date(), to_number()…
│       └── engine.py                # Mapping + workbook → rows + lineage. No LLM.
│
└── frontend/
    ├── package.json
    ├── vite.config.js
    ├── .env.example
    └── src/
        ├── App.jsx                  # MSAL auth wrapper + 4-step flow
        └── components/
            ├── FileUpload.jsx       # Drag-drop Excel upload
            ├── SchemaEditor.jsx     # Build/edit fields with AI instruction guidance
            ├── SchemaLibrary.jsx    # Load / save / delete named schemas  ← NEW
            ├── MappingView.jsx      # Show inferred mapping + inline override  ← UPDATED
            └── ResultsView.jsx      # Paginated table, confidence badge, JSON export
```

---

## API

```
# Ingestion
POST   /ingest                         # Map + extract + validate
GET    /result/{excel_hash}            # Fetch cached result
                ?schema_id=<id>

# Schema library
GET    /schemas                        # List current user's saved schemas
POST   /schemas                        # Save a new schema → { id, name, structure }
PUT    /schemas/{id}                   # Update a schema (invalidates related cache entries)
DELETE /schemas/{id}                   # Delete a schema

GET    /health
```

All routes except `/health` require `Authorization: Bearer <Azure AD JWT>`.
Schema routes are scoped to the requesting user via the `oid` claim in the JWT —
users cannot see or load each other's schemas.

---

## IngestResponse Shape

```json
{
  "success": true,
  "excel_hash": "a3f9...",
  "schema_id": "scm_abc123",
  "mapping": {
    "sheet_name": "Orders",
    "header_row": 3,
    "data_start_row": 4,
    "mappings": [
      {
        "source_col": "B",
        "target_field": "supplier_name",
        "transform": "strip",
        "notes": "Column header 'Client Name' matched supplier_name description"
      }
    ],
    "reasoning": "Headers found at row 3, data rows 4–247..."
  },
  "validation": {
    "confidence": 0.94,
    "passed": true,
    "issues": [],
    "rows_sampled": 10,
    "summary": "All fields look correct."
  },
  "data": [{ "supplier_name": "Tesco PLC", "weight_tonnes": 12.4 }],
  "lineage": [{
    "source_file_hash": "a3f9...",
    "source_sheet": "Orders",
    "source_row": 4,
    "fields": [
      { "target_field": "supplier_name", "source_col": "B", "source_sheet": "Orders", "transform_applied": "strip" }
    ]
  }],
  "row_count": 247,
  "cached": false,
  "created_at": "2026-05-16T10:00:00Z"
}
```

---

## Extraction-Only Endpoint

Supports the manual override flow — user corrects the mapping in the UI
and re-runs extraction without a second LLM call:

```
POST /extract
  body: { excel_hash, schema_id, mapping: ExcelMapping }
  auth: Bearer <Azure AD JWT>
  → IngestResponse (skips LLM, runs engine directly on provided mapping)
```

---

## CI/CD Pipeline (Azure DevOps)

```
PR opened    →  Stage 1: pytest — blocks merge on failure

Merge to main →  Stage 1: pytest
                 Stage 2: az acr build → push image:{buildId} + image:latest
                 Stage 3: az containerapp update → GET /health → done
```

---

## Build Status

| File | Status |
|---|---|
| `models.py` | ✅ Done |
| `config.py` | ✅ Done |
| `excel_processor.py` | ✅ Done |
| `llm/prompts.py` | ✅ Done |
| `llm/mapper.py` | ✅ Done |
| `llm/validator.py` | ✅ Done |
| `extractor/transforms.py` | ✅ Done |
| `extractor/engine.py` | ✅ Done |
| `cache.py` | ✅ Done |
| `main.py` | ✅ Done |
| `Dockerfile` | ✅ Done |
| `azure-pipelines.yml` | ✅ Done |
| `App.jsx` | ✅ Done |
| `FileUpload.jsx` | ✅ Done |
| `SchemaEditor.jsx` | ✅ Done |
| `SchemaLibrary.jsx` | ✅ Done |
| `MappingView.jsx` | ✅ Done |
| `ResultsView.jsx` | ✅ Done |
| `tests/` | ✅ Done |
| `README.md` | ❌ Not yet written |
| `DEPLOY.md` | ✅ Done |# Azure Deployment Guide

Step-by-step from a blank personal Azure account to a running system.
Estimated time: ~90 minutes on first run.

---

## Prerequisites

Install these locally before starting:

```bash
# Azure CLI
brew install azure-cli          # macOS
# or: https://learn.microsoft.com/en-us/cli/azure/install-azure-cli

# Node (for frontend build)
brew install node

# Python 3.12
brew install python@3.12

# Verify
az --version
node --version
python3 --version
```

Log in:

```bash
az login
az account show   # confirm you're on the right subscription
```

Set a variable for your subscription ID — you'll use it throughout:

```bash
SUBSCRIPTION_ID=$(az account show --query id -o tsv)
```

---

## 1. Resource Group

Everything goes in one resource group so you can delete it all in one command after the demo.

```bash
az group create \
  --name excel-ingestion-rg \
  --location uksouth
```

> **uksouth** is the closest Azure region to Bristol. Use it for lower latency and to keep data in the UK.

---

## 2. Azure AD App Registration (Auth)

This is what issues JWTs to your frontend users.

### 2a. Create the registration

```bash
APP=$(az ad app create \
  --display-name "Excel Ingestion" \
  --sign-in-audience AzureADMyOrg \
  --query "{appId:appId, objectId:id}" -o json)

CLIENT_ID=$(echo $APP | python3 -c "import sys,json; print(json.load(sys.stdin)['appId'])")
TENANT_ID=$(az account show --query tenantId -o tsv)

echo "CLIENT_ID: $CLIENT_ID"
echo "TENANT_ID: $TENANT_ID"
```

### 2b. Expose an API scope

```bash
az ad app update \
  --id $CLIENT_ID \
  --identifier-uris "api://$CLIENT_ID"

# Add the Ingest.Read scope (do this in the portal — it's faster)
# Portal: App registrations → Excel Ingestion → Expose an API
# → Add scope → name: Ingest.Read → Admins and users → Save
```

### 2c. Add a SPA redirect URI

```bash
# Portal: App registrations → Excel Ingestion
# → Authentication → Add a platform → Single-page application
# Redirect URI: http://localhost:5173   (add your prod URL later)
# Check: Access tokens, ID tokens
# Save
```

### 2d. Add yourself (and the interviewer) as a user

```bash
# Portal: Azure Active Directory → Users → New user → Invite external user
# Enter their email → send invite
# They accept the invite email, then they can log in to your portal
```

---

## 3. Azure OpenAI

### 3a. Create the resource

```bash
az cognitiveservices account create \
  --name excel-ingestion-oai \
  --resource-group excel-ingestion-rg \
  --kind OpenAI \
  --sku S0 \
  --location swedencentral   # GPT-4o is available here on personal accounts
```

> GPT-4o availability varies by region on personal accounts. **swedencentral** and **eastus** are the most reliable. The backend will call it from uksouth — cross-region latency is ~20ms, fine for a demo.

### 3b. Deploy the models

```bash
# GPT-4o for mapping
az cognitiveservices account deployment create \
  --name excel-ingestion-oai \
  --resource-group excel-ingestion-rg \
  --deployment-name gpt-4o \
  --model-name gpt-4o \
  --model-version "2024-08-06" \
  --model-format OpenAI \
  --sku-capacity 10 \
  --sku-name Standard

# GPT-4o-mini for validation
az cognitiveservices account deployment create \
  --name excel-ingestion-oai \
  --resource-group excel-ingestion-rg \
  --deployment-name gpt-4o-mini \
  --model-name gpt-4o-mini \
  --model-version "2024-07-18" \
  --model-format OpenAI \
  --sku-capacity 20 \
  --sku-name Standard
```

### 3c. Get the endpoint and key

```bash
OAI_ENDPOINT=$(az cognitiveservices account show \
  --name excel-ingestion-oai \
  --resource-group excel-ingestion-rg \
  --query properties.endpoint -o tsv)

OAI_KEY=$(az cognitiveservices account keys list \
  --name excel-ingestion-oai \
  --resource-group excel-ingestion-rg \
  --query key1 -o tsv)

echo "OAI_ENDPOINT: $OAI_ENDPOINT"
```

### 3d. Set a token quota (cost control)

```bash
# Portal: Azure OpenAI → excel-ingestion-oai → Deployments
# Click gpt-4o → Edit → Tokens per minute: 10,000
# Click gpt-4o-mini → Edit → Tokens per minute: 20,000
# This caps your spend to roughly £5-10 for a demo
```

---

## 4. Azure Cosmos DB

```bash
az cosmosdb create \
  --name excel-ingestion-cosmos \
  --resource-group excel-ingestion-rg \
  --kind GlobalDocumentDB \
  --default-consistency-level Session \
  --locations regionName=uksouth

# Create database and container
az cosmosdb sql database create \
  --account-name excel-ingestion-cosmos \
  --resource-group excel-ingestion-rg \
  --name excel_ingestion

az cosmosdb sql container create \
  --account-name excel-ingestion-cosmos \
  --resource-group excel-ingestion-rg \
  --database-name excel_ingestion \
  --name results \
  --partition-key-path "/id" \
  --throughput 400    # minimum — ~£20/month, fine for demo

# Get connection values
COSMOS_ENDPOINT=$(az cosmosdb show \
  --name excel-ingestion-cosmos \
  --resource-group excel-ingestion-rg \
  --query documentEndpoint -o tsv)

COSMOS_KEY=$(az cosmosdb keys list \
  --name excel-ingestion-cosmos \
  --resource-group excel-ingestion-rg \
  --query primaryMasterKey -o tsv)
```

---

## 5. Azure Container Registry

```bash
az acr create \
  --name excelIngestionAcr \
  --resource-group excel-ingestion-rg \
  --sku Basic \
  --admin-enabled true

ACR_SERVER=$(az acr show \
  --name excelIngestionAcr \
  --query loginServer -o tsv)

ACR_PASSWORD=$(az acr credential show \
  --name excelIngestionAcr \
  --query passwords[0].value -o tsv)
```

---

## 6. Build and Push the Backend Image

```bash
cd excel-ingestion/backend

# Build and push directly via ACR (no local Docker required)
az acr build \
  --registry excelIngestionAcr \
  --image excel-ingestion-api:latest \
  .
```

---

## 7. Azure Container Apps

### 7a. Create the environment

```bash
az containerapp env create \
  --name excel-ingestion-env \
  --resource-group excel-ingestion-rg \
  --location uksouth
```

### 7b. Deploy the container app

Replace the placeholder values with your actual secrets from the steps above.

```bash
az containerapp create \
  --name excel-ingestion-api \
  --resource-group excel-ingestion-rg \
  --environment excel-ingestion-env \
  --image excelIngestionAcr.azurecr.io/excel-ingestion-api:latest \
  --registry-server excelIngestionAcr.azurecr.io \
  --registry-username excelIngestionAcr \
  --registry-password $ACR_PASSWORD \
  --target-port 8000 \
  --ingress external \
  --min-replicas 0 \
  --max-replicas 3 \
  --cpu 0.5 \
  --memory 1.0Gi \
  --env-vars \
    AZURE_OPENAI_ENDPOINT="$OAI_ENDPOINT" \
    AZURE_OPENAI_API_KEY="$OAI_KEY" \
    AZURE_OPENAI_MAPPER_DEPLOYMENT="gpt-4o" \
    AZURE_OPENAI_VALIDATOR_DEPLOYMENT="gpt-4o-mini" \
    AZURE_OPENAI_API_VERSION="2024-08-01-preview" \
    COSMOS_ENDPOINT="$COSMOS_ENDPOINT" \
    COSMOS_KEY="$COSMOS_KEY" \
    COSMOS_DATABASE="excel_ingestion" \
    COSMOS_CONTAINER="results" \
    AZURE_TENANT_ID="$TENANT_ID" \
    AZURE_CLIENT_ID="$CLIENT_ID" \
    ALLOWED_ORIGINS="http://localhost:5173" \
    API_KEY="$(openssl rand -hex 32)"
```

> `--min-replicas 0` means the app scales to zero when idle — no cost when nobody's using it.

### 7c. Get the backend URL

```bash
BACKEND_URL=$(az containerapp show \
  --name excel-ingestion-api \
  --resource-group excel-ingestion-rg \
  --query "properties.configuration.ingress.fqdn" -o tsv)

echo "Backend: https://$BACKEND_URL"

# Smoke test
curl https://$BACKEND_URL/health
# → {"status":"ok"}
```

---

## 8. Frontend — Azure Static Web Apps

### 8a. Build the frontend

```bash
cd excel-ingestion/frontend

# Create .env with real values
cat > .env << EOF
VITE_AZURE_CLIENT_ID=$CLIENT_ID
VITE_AZURE_TENANT_ID=$TENANT_ID
VITE_API_URL=https://$BACKEND_URL
EOF

npm install
npm run build
```

### 8b. Deploy

```bash
npm install -g @azure/static-web-apps-cli

swa deploy ./dist \
  --app-name excel-ingestion-frontend \
  --resource-group excel-ingestion-rg \
  --subscription-id $SUBSCRIPTION_ID
```

The CLI will print a URL like `https://orange-tree-0a1b2c3d.azurestaticapps.net`.

### 8c. Add the production URL to the App Registration

```bash
# Portal: App registrations → Excel Ingestion → Authentication
# Add redirect URI: https://your-swa-url.azurestaticapps.net
# Save

# Also update ALLOWED_ORIGINS on the container app:
az containerapp update \
  --name excel-ingestion-api \
  --resource-group excel-ingestion-rg \
  --set-env-vars ALLOWED_ORIGINS="http://localhost:5173,https://your-swa-url.azurestaticapps.net"
```

---

## 9. Azure DevOps CI/CD

### 9a. Create an ADO project and push the repo

```bash
# Portal: dev.azure.com → New project → excel-ingestion → Create

# Push your code
cd excel-ingestion
git init
git remote add origin https://dev.azure.com/YOUR_ORG/excel-ingestion/_git/excel-ingestion
git add .
git commit -m "initial commit"
git push -u origin main
```

### 9b. Create a service connection

```bash
# Portal: ADO Project → Project settings → Service connections
# → New service connection → Azure Resource Manager
# → Service principal (automatic)
# → Subscription: your subscription
# → Resource group: excel-ingestion-rg
# → Name: azure-service-connection
# Save
```

### 9c. Create the pipeline

```bash
# Portal: ADO → Pipelines → New pipeline
# → Azure Repos Git → excel-ingestion repo
# → Existing Azure Pipelines YAML file
# → Branch: main, Path: /azure-pipelines.yml
# → Save and run
```

The `AZURE_SERVICE_CONNECTION` variable in `azure-pipelines.yml` must match the service connection name you set in 9b.

---

## 10. Budget Alert (Cost Control)

```bash
# Portal: Cost Management + Billing → Budgets → Add
# Scope: your subscription
# Amount: £30
# Alert at: 80% (£24) → email notification
# This takes 5 minutes and protects against runaway usage
```

---

## Local Development (no Azure needed)

The cache falls back to a local JSON file when Cosmos credentials are absent.
The auth middleware can be bypassed by commenting out `Depends(require_user)` in `main.py` during local dev.

```bash
# Backend
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp ../.env.example .env   # fill in real OpenAI values only
uvicorn main:app --reload

# Frontend (separate terminal)
cd frontend
cp .env.example .env      # set VITE_API_URL=http://localhost:8000
npm install
npm run dev
# → http://localhost:5173
```

---

## Tear Down After the Demo

```bash
az group delete --name excel-ingestion-rg --yes
# Deletes everything: Container App, Cosmos, ACR, OpenAI, Static Web App env
# The App Registration needs manual deletion:
az ad app delete --id $CLIENT_ID
```

---

## Cost Estimate (demo usage, ~1 week)

| Service | Tier | Est. cost |
|---|---|---|
| Container Apps | Scale to zero, ~1hr active | < £1 |
| Azure OpenAI GPT-4o | ~20 ingestions | < £2 |
| Azure OpenAI GPT-4o-mini | ~20 validations | < £0.10 |
| Cosmos DB | 400 RU/s manual | ~£5 |
| Container Registry | Basic | ~£1 |
| Static Web Apps | Free tier | £0 |
| **Total** | | **~£9** |
