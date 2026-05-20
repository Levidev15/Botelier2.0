---
id: account-settings
title: Account Settings
sidebar_label: Account Settings
---

# Account Settings

Account Settings let you configure your organization's name, timezone, notification preferences, and Twilio sub-account details.

## Accessing Account Settings

Navigate to **Settings** → **Account** in the left sidebar.

## General Settings

| Setting | Description |
|---|---|
| **Account Name** | Display name for your organization. Shown in the admin panel and billing emails. |
| **Timezone** | Your primary timezone. Used to display timestamps in analytics and call logs. |
| **Support Email** | Contact email for your team. Appears in platform-generated notifications. |

Click **Save** to apply changes.

## Twilio Sub-Account Status

The Twilio configuration panel shows:

| Field | Description |
|---|---|
| **Sub-Account SID** | Your Twilio sub-account identifier (managed by your Botelier admin) |
| **Sub-Account Status** | Active / Suspended / Closed |
| **Phone Numbers** | Count of numbers provisioned under this sub-account |
| **Webhook Base URL** | The Botelier URL configured as the Twilio webhook base |

If the sub-account status is **Suspended** or missing credentials, calls and SMS will fail. Contact your platform administrator.

## Notification Preferences

Configure which system events trigger email notifications:

| Notification | Description |
|---|---|
| **Billing Threshold Alert** | Receive an email when MTD spend crosses the configured threshold |
| **Weekly Usage Summary** | Receive a weekly email with usage and cost summary |
| **Call Failure Alerts** | Receive alerts when calls fail due to configuration errors |

## Secrets

Account Secrets store encrypted API keys and tokens used by flow API Request nodes and tools.

- Navigate to **Settings** → **Secrets** to manage secrets.
- See [Custom API via Flow](../integrations/custom-api-via-flow) for usage examples.

## Danger Zone

The danger zone contains irreversible actions. Proceed with caution.

### Deactivate Account

Deactivating your account:
- Suspends all active phone numbers
- Prevents new calls and SMS from being processed
- Retains all data for 90 days
- Can be reactivated by a platform administrator within the retention window

To deactivate, click **Deactivate Account**, type your account name to confirm, and click **Confirm Deactivation**.

:::danger
Account deactivation affects all team members immediately. All ongoing calls will be terminated.
:::
