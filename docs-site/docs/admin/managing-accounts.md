---
id: managing-accounts
title: Managing Accounts
sidebar_label: Managing Accounts
---

# Managing Accounts

The **Accounts** section of the Admin Panel is the starting point for all per-account operations: creating accounts, viewing usage, configuring billing, managing feature flags, and exporting data.

## Accounts Table

Navigate to **Admin** → **Accounts** to see the cross-account usage table. Each row shows:

| Column | Description |
|---|---|
| **Account Name** | The account's display name |
| **Inbound Calls** | Call count for the selected period |
| **Inbound Minutes** | Total inbound minutes |
| **Inbound Cost** | Customer-facing inbound cost |
| **Outbound Transfers** | Transfer leg count |
| **Outbound Cost** | Customer-facing outbound cost |
| **SMS** | In/Out message counts |
| **Billable Total** | Total customer-facing cost |
| **Twilio Cost** | Internal Twilio carrier cost (admin-only) |
| **Internal Cost** | LLM + TTS + STT + Twilio cost total |
| **Margin** | Billable Total − Internal Cost |

Use the **Period** selector to change the date range. Sort by any column by clicking its header.

## Creating a New Account

1. Click **+ New Account** in the top-right.
2. Fill in:
   - **Account Name** — display name
   - **Owner Email** — must be an existing Botelier user
   - **Twilio Sub-Account** — Botelier automatically provisions a Twilio sub-account
3. Click **Create Account**.

The account is created with default platform billing rates applied.

## Account Detail Page

Click any account row to open the detail page. It includes:

### Billing Summary Card Strip

A row of cards showing the current period's:
- MTD spend by channel (inbound, outbound, SMS)
- Total billable amount
- Internal cost and margin
- Last billing alert sent (date + amount threshold)

### Call Log Table

A paginated, sortable call log for this specific account. Columns match the main [Call Logs](../analytics/call-logs) view. Sort by:
- **Time** — most recent first (default)
- **Duration** — longest calls first
- **Cost** — most expensive first

### Export Call Log as CSV

Click **Export CSV** from the account detail page to download the full call log. Admin exports are not subject to the account-level `usage.export` permission.

### Billing Configuration

In the **Billing** tab:

| Setting | Description |
|---|---|
| **Inbound Rate (USD/min)** | Per-minute rate charged for inbound calls |
| **Outbound Rate (USD/min)** | Per-minute rate charged for transfer legs |
| **SMS Inbound Rate (USD/msg)** | Per-message rate for inbound SMS |
| **SMS Outbound Rate (USD/msg)** | Per-message rate for outbound SMS |
| **Monthly Alert Threshold (USD)** | Send a billing alert email when MTD spend crosses this amount |
| **Effective From** | Date the rate takes effect (defaults to now) |

Leaving a field blank applies the platform default rate.

### Feature Flags

In the **Features** tab, enable or disable specific features for this account:

| Feature | Description |
|---|---|
| `flow_editor` | Access to the Visual Flow Editor |
| `mcp_connections` | MCP server connections |
| `sms_ai` | SMS AI responses |
| `a2p_compliance` | A2P 10DLC compliance tools |
| `call_recording` | Call recording capability |
| `acw` | After-Call Work / QA |

Toggle features on/off and click **Save**. Changes take effect immediately.

## Enabling and Disabling Accounts

- **Suspend:** Click **Suspend Account** — all calls are blocked; existing data is preserved
- **Reactivate:** Click **Activate Account** — restores call routing and SMS
- **Delete:** Permanently removes the account and all data (requires confirmation). This is irreversible.
