# Azure OpenAI Resource Configuration

This document covers the recommended Azure OpenAI deployment settings for the Excel Ingestion Portal.

## Model Deployments

| Deployment Name | Model | Purpose |
|---|---|---|
| `gpt-4o` | GPT-4o | Column mapping inference |
| `gpt-4o-mini` | GPT-4o-mini | Extraction validation |

## Recommended TPM/RPM Limits

Set these on each deployment in the Azure OpenAI resource under **Deployments > Quotas**:

### gpt-4o (Mapper)
- **Tokens Per Minute (TPM)**: 80,000–150,000
  - Each mapping call sends a column summary (typically 2,000–8,000 tokens input)
  - Response is ~500–1,500 tokens
  - Multi-sheet files generate one call per sheet
- **Requests Per Minute (RPM)**: 30–60
  - Scales with concurrent users x sheets per file

### gpt-4o-mini (Validator)
- **Tokens Per Minute (TPM)**: 40,000–80,000
  - Validation sends 10 sample rows (~1,000–3,000 tokens)
  - Response is ~200–500 tokens
- **Requests Per Minute (RPM)**: 30–60

## Content Filtering

Use the default content filter policy. The data being processed is structured business data (Excel spreadsheets), so aggressive filtering is unnecessary but should remain enabled for compliance.

## ADLS Gen2 Lifecycle Management

Configure a lifecycle management policy on the ADLS Gen2 storage account to automatically delete uploaded files after 7 days:

```json
{
  "rules": [
    {
      "name": "delete-uploads-after-7-days",
      "enabled": true,
      "type": "Lifecycle",
      "definition": {
        "filters": {
          "blobTypes": ["blockBlob"],
          "prefixMatch": ["excel-uploads/"]
        },
        "actions": {
          "baseBlob": {
            "delete": {
              "daysAfterModificationGreaterThan": 7
            }
          }
        }
      }
    }
  ]
}
```

Apply this via: **Storage Account > Lifecycle Management > Add a rule**, or via Azure CLI:

```bash
az storage account management-policy create \
  --account-name <storage-account> \
  --resource-group <resource-group> \
  --policy @lifecycle-policy.json
```

## Networking

For production deployments:
- Enable **Private Endpoints** for the Azure OpenAI resource
- Restrict the OpenAI resource to the Container Apps VNet
- Use **Managed Identity** instead of API keys where possible (requires code changes to use `DefaultAzureCredential`)
