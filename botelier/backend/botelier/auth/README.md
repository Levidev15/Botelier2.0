# `auth/` — Authentication & authorization

## Purpose

JWT verification, role-based permissions, account scoping middleware, and feature flag gating.

## Main files

| File | Role |
|---|---|
| `middleware.py` | FastAPI dependencies: extract user + account from JWT, enforce auth. |
| `permissions.py` | RBAC permission checks (per-route `require_permission(...)`). |
| `features.py` | Account-level feature flag evaluation (consumed by frontend `AccountFeaturesContext`). |

## How it connects

- Used by every `api/*.py` route via `Depends(...)` from `middleware.py`.
- `permissions.py` is read by the frontend through `api/account.py` to render `PermissionGate` UI.
- `features.py` powers `api/account.py` feature endpoints + `frontend/contexts/AccountFeaturesContext.tsx`.

## Conventions

- Routes never read JWTs directly — always go through the middleware dependency.
- Permission enums and the `require_permission` decorator-style dependency are the only sanctioned way to gate an endpoint; ad-hoc `if user.role == ...` checks in route handlers are forbidden.

## Setup

Imported as `botelier.auth.*`. Configure JWT secrets via env vars (consumed by `middleware.py`).

## Gotchas

- Missing `account_id` filter on a tenant-owned query is the #1 way to leak data between hotels — every route must use the auth dependency to scope queries.
- NextAuth on the frontend issues a session cookie; the backend's email/password endpoints (`/api/auth/login`, `/register`, `/validate`, `/verify-invitation`) are routed directly to FastAPI by `frontend/server.js:126-135`, bypassing NextAuth.
