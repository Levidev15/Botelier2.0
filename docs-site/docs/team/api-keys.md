---
id: api-keys
title: API Keys
sidebar_label: API Keys
---

# API Keys

**API Keys** allow programmatic access to Botelier's REST API on behalf of your account. Use them when integrating Botelier with external systems, CI/CD pipelines, or custom dashboards.

## Creating an API Key

1. Navigate to **Settings** → **API Keys**.
2. Click **+ New API Key**.
3. Enter:
   - **Name** — descriptive label (e.g. "Zapier Integration", "Analytics Exporter")
   - **Permissions** — select which permissions this key should have (subset of your own permissions)
4. Click **Generate**.
5. **Copy the key immediately** — it is shown in full only once. After closing the dialog, only the last 4 characters are visible.

## Using an API Key

Include the key in the `Authorization` header on every request:

```bash
curl -H "Authorization: Bearer bte_your_key_here" \
  https://your-botelier-domain.com/api/assistants?account_id=YOUR_ACCOUNT_ID
```

API keys carry the permissions you assigned at creation and are scoped to the account you created them in.

## Key Scopes

When creating a key, you select which permissions it carries. Best practice: grant only the minimum permissions needed for the integration.

**Examples:**
- Read-only analytics integration: `usage.view`, `assistants.view`
- Full automation key: all Staff-level permissions

## Rotating API Keys

To rotate a key:
1. Click **+ New API Key** and generate a new one.
2. Update your integration to use the new key.
3. Return to **API Keys** and delete the old key.

There is no "regenerate" action — you must create a new key and delete the old one.

## Revoking an API Key

1. Click the **...** menu on the key row.
2. Select **Delete**.
3. Confirm.

The key is immediately invalid. Any requests using it will receive a `401 Unauthorized` response.

## Audit Log

All API requests authenticated with an API key are logged with the key name (not the key value) in the platform audit log. Platform administrators can view these logs to investigate suspicious activity.

## Security Best Practices

- Never commit API keys to version control
- Use environment variables or a secrets manager (AWS Secrets Manager, HashiCorp Vault, etc.) to store keys
- Grant minimum required permissions per key
- Rotate keys quarterly or after suspected exposure
- Use separate keys per integration so you can revoke one without affecting others
