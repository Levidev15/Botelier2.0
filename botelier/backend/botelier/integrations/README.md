# `integrations/` — Outbound third-party adapters

## Purpose

Wrappers for outbound calls to external providers. Currently houses Twilio.

## Main files

```
integrations/
├── __init__.py
└── twilio/
    ├── client.py          REST client wrapper
    ├── sub_accounts.py    Per-tenant subaccount provisioning
    └── phone_numbers.py   Number search / purchase / assignment
```

## How it connects

- `api/phone_numbers.py` is the main HTTP-side caller.
- `api/calls.py` and `api/websockets.py` use Twilio for inbound webhook + media-stream wiring.
- Different from `services/integration_client.py` — that one is a *generic* HTTP-tool runner used by the LLM at runtime; this folder is for first-class platform integrations the app itself owns.

## Conventions

- Twilio credentials are per-account (subaccount SID + token), pulled via the `client.py` factory.
- All errors from Twilio are wrapped in app-specific exceptions before bubbling to routes.

## Setup

No global init — clients are constructed on demand from account secrets.

## Gotchas

- Every account gets its own Twilio subaccount; never mix account credentials.
- Number purchase is a real billing event — guard endpoints with permission checks and idempotency.
