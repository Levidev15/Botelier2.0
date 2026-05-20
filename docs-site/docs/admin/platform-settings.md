---
id: platform-settings
title: Platform Settings
sidebar_label: Platform Settings
---

# Platform Settings

Platform Settings control system-wide configuration: SMTP for alert emails, default feature entitlements, and diagnostic tools.

## Accessing Platform Settings

Navigate to **Admin** → **Settings**.

---

## SMTP Configuration

Billing threshold alerts and invitation emails are delivered via SMTP. Configure the SMTP server here.

| Setting | Environment Variable | Description |
|---|---|---|
| **SMTP Host** | `SMTP_HOST` | Mail server hostname (e.g. `smtp.sendgrid.net`) |
| **SMTP Port** | `SMTP_PORT` | Port number (587 for STARTTLS, 465 for SSL) |
| **SMTP Username** | `SMTP_USER` | Authentication username |
| **SMTP Password** | `SMTP_PASSWORD` | Authentication password (stored in environment, not DB) |
| **From Address** | `ALERT_EMAIL_FROM` | Sender address for alert emails |

:::note Environment Variables
SMTP credentials are configured as environment variables, not in the database. Changes require a restart of the backend service. Contact your Botelier system administrator if you need to update SMTP credentials.
:::

## Test Billing Alert Email

Verify that SMTP is working correctly by sending a test alert:

1. Click **Send Test Alert Email**.
2. Enter a recipient email address.
3. Click **Send**.

A test email is sent immediately. If delivery fails, an error message shows the SMTP error. The test does not affect the billing alert suppression state for any account.

---

## Feature Catalog Defaults

The Feature Catalog defines which features are available platform-wide and what the default state is for new accounts.

| Feature | Default | Description |
|---|---|---|
| `flow_editor` | Enabled | Visual Flow Editor |
| `mcp_connections` | Enabled | MCP server connections |
| `sms_ai` | Enabled | SMS AI responses |
| `a2p_compliance` | Enabled | A2P 10DLC compliance tools |
| `call_recording` | Disabled | Call recording (may require legal review per jurisdiction) |
| `acw` | Enabled | After-Call Work / QA scoring |

Toggle the default for any feature and click **Save Defaults**. This affects **new accounts only**. Existing accounts retain their current feature state.

---

## Per-Account Entitlement Overrides

To enable or disable a feature for a specific account regardless of the catalog default:

1. Go to **Admin** → **Accounts** → select the account → **Features** tab.
2. Toggle the feature.
3. Click **Save**.

Per-account overrides take precedence over catalog defaults.
