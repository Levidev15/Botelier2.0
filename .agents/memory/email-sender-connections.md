---
name: Email Sender Connections (Task #655)
description: Architecture for connecting Gmail/Microsoft accounts as outbound email senders via OAuth2.
---

## Architecture overview

- `IntegrationType` has a new `category VARCHAR(32)` column (`email_sender` | NULL for legacy)
- Slug prefix convention: `email-sender-gmail`, `email-sender-microsoft`
- Seeds: `seeds/gmail_sender_integration.py`, `seeds/microsoft_sender_integration.py`
  - Registered in `seeds/__init__.py` WITHOUT calling `verify_seed` (no meaningful endpoints to validate)
- API router: `api/email_senders.py` at `/api/settings/email-senders`
  - `email_senders_router` registered BEFORE `integration_builder_router` and `integrations_router` in `main.py`

## OAuth flow

- Platform credentials from env vars: `GMAIL_CLIENT_ID`, `GMAIL_CLIENT_SECRET`, `MICROSOFT_CLIENT_ID`, `MICROSOFT_CLIENT_SECRET`
- Injected server-side at `/api/settings/email-senders/connect/{provider}` — users just click "Connect"
- Authorization URL uses `extra_authorize_params` from auth_config (needed for Gmail's `access_type=offline&prompt=consent`)
- `_build_authorization_url` in `integrations.py` now merges `auth_config["extra_authorize_params"]` into params

## Circular import guard

- `_fetch_email_sender_email()` is defined in `api/integrations.py` (NOT in `api/email_senders.py`)
- Reason: `email_senders.py` imports helpers from `integrations.py`; defining it there would be circular
- `oauth_complete` calls `_fetch_email_sender_email` and stores result in `conn_config["email"]`; also auto-names the connection with the actual email address

## Sending via connected account

- `email_service.py` has `send_email_via_gmail()`, `send_email_via_microsoft()`, and `send_email_via_connection()`
- `send_email_via_connection()` dispatches on `connection.integration_type.slug`; requires `integration_type` eagerly loaded
- Uses synchronous `requests` (not httpx) since called from `run_in_executor`
- `function_mapper.py` SEND_EMAIL handler: checks `cfg["connection_id"]` first; if set, loads `AccountIntegration` with `joinedload(integration_type)` and calls `send_email_via_connection()`; falls through to SendGrid if no connection_id

## Frontend

- Settings page: `/dashboard/settings` with General and Email tabs (URL param `?tab=email`)
- OAuth complete page: if `data.integration_slug.startsWith("email-sender-")` → redirect to `/dashboard/settings?tab=email&connected=1`
- `SendEmailForm.tsx`: "Send From" dropdown (fetches `/api/settings/email-senders`); platform sender is default; typed from_name/from_email only shown when no connected account selected

**Why platform credentials, not user credentials:**
Gmail/Microsoft require an OAuth app registered with them. Botelier registers one app per provider; all customers share it. This is standard SaaS practice (same as how HubSpot, Salesforce etc. connect Gmail).

**How to apply:**
Any new send-from-mailbox integration follows the same pattern: add a seed with `category="email_sender"`, add send function to `email_service.py`, dispatch in `send_email_via_connection`.
