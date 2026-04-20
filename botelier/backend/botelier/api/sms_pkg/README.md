# `api/sms_pkg/` — SMS conversation API

## Purpose

Sub-package grouping all SMS-side endpoints (separate from the voice path). Exposes a single `router` that `main.py` mounts as `sms_router`.

## Main files

| File | Role |
|---|---|
| `__init__.py` | Re-exports the combined `router` |
| `webhook.py` | Inbound SMS webhook (Twilio) |
| `conversations.py` | List / read SMS threads, send replies |
| `analytics.py` | Per-account SMS metrics |
| `settings.py` | Per-account SMS configuration |

## How it connects

- Registered by `main.py` as `app.include_router(sms_router)`.
- Backed by `services/sms_service.py` and `services/sms_compliance_service.py`.
- ORM: `models/sms_conversation.py`, `models/sms_template.py`, `models/sms_compliance.py`.
- A2P 10DLC compliance routes live separately in `api/sms_compliance.py` (sibling, not in this package).

## Conventions

- All endpoints under this package share the SMS prefix wiring done in `__init__.py`.
- Inbound webhook validates Twilio signatures before doing any DB work.

## Setup

Auto-mounted by `main.py`.

## Gotchas

- SMS compliance state can block outbound sends; the service layer is the source of truth, not the webhook handler.
