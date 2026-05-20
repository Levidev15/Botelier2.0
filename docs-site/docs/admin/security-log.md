---
id: security-log
title: Security Log
sidebar_label: Security Log
---

# Security Log

The **Security Log** is an append-only record of security-relevant events across the platform. Platform administrators use it to detect suspicious activity, investigate incidents, and verify compliance.

## Accessing the Security Log

Navigate to **Admin** → **Security Log**.

## Events Recorded

| Event Type | Description | Trigger |
|---|---|---|
| `twilio_webhook_signature_invalid` | An incoming Twilio webhook request had an invalid or missing `X-Twilio-Signature` header | Possible spoofed webhook attempt |
| `call_blocked_missing_twilio_credentials` | An inbound call was rejected because Twilio credentials are not configured for the account | Misconfiguration or attempted call without valid Twilio setup |
| `support_session_started` | A platform admin opened a support session for an account | Admin impersonation |
| `support_session_ended` | A support session was closed | Normal end of impersonation |
| `user_deactivated` | A user account was deactivated by an admin | Account management |
| `platform_admin_granted` | Platform admin access granted to a user | Privilege escalation |
| `api_key_created` | A new API key was created | Access management |
| `api_key_revoked` | An API key was deleted | Access management |

## Log Entry Fields

| Field | Description |
|---|---|
| **Timestamp** | UTC timestamp of the event |
| **Event Type** | Machine-readable event category |
| **Account** | Affected account (if applicable) |
| **User / Source** | Who triggered the event (user ID, IP address, or "system") |
| **Details** | Event-specific metadata (e.g. which webhook URL was called, which call SID was blocked) |

## Filtering the Log

Use the filter bar to narrow by:
- **Event Type** — one or more event categories
- **Account** — filter to a specific account
- **Date Range** — default is last 30 days
- **User** — filter by a specific user's actions

## Responding to Security Events

### `twilio_webhook_signature_invalid`

This event appears when a POST request arrives at a Twilio callback URL (`/api/calls/inbound`, `/api/sms/webhook`, etc.) with an invalid or absent `X-Twilio-Signature` header.

**Possible causes:**
- Automated scanner or bot probing Twilio-looking URLs
- Misconfigured Twilio webhook URL (e.g. wrong domain)
- Replay attack using a stale webhook payload

**Actions:**
1. Check the `source_ip` in the event details. If it's not a Twilio IP range, the request is not from Twilio.
2. If the IP matches Twilio's range, verify that your `TWILIO_AUTH_TOKEN` environment variable is correct.
3. If you see a sustained pattern from a non-Twilio IP, consider blocking it at your infrastructure level.

### `call_blocked_missing_twilio_credentials`

The platform blocked a call because the account's Twilio credentials (Account SID / Auth Token) are not configured. No audio is delivered to the caller.

**Actions:**
1. Go to **Admin** → **Accounts** → the affected account.
2. Verify the Twilio sub-account is provisioned and credentials are present.
3. Contact your Twilio account manager if the sub-account has been suspended.

## Log Retention

Security log entries are retained for **365 days**. After that, they are automatically purged. For longer retention, configure log export to an external SIEM (contact your Botelier administrator).

## Relationship to Threat Model

The security log directly supports several threat categories from the [threat model](https://github.com/botelier/botelier/blob/main/threat_model.md):

- **Spoofing** — `twilio_webhook_signature_invalid` detects forged webhook attempts
- **Denial of Service** — blocked call events surface credential misconfigurations before they impact traffic
- **Elevation of Privilege** — support session and admin grant events create an audit trail for privilege actions
