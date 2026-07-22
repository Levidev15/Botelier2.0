---
name: FastAPI router ordering — static vs wildcard conflicts
description: Static path segments in later-registered routers lose to wildcard segments in earlier routers; integration_builder_router must precede integrations_router.
---

## Rule
In FastAPI, routes are matched in the order routers are registered with `app.include_router()`. A static path segment in a **later** router loses to a parameterised wildcard in an **earlier** router if they share a common prefix.

## The incident
`GET /api/integrations/types/importable` (static, in `integration_builder_router`) was being absorbed by `GET /api/integrations/types/{type_id}` (wildcard UUID param, in `integrations_router`) because `integrations_router` was registered first. PostgreSQL then tried to cast the string `"importable"` to UUID → 500.

## Fix
Register `integration_builder_router` **before** `integrations_router` in `main.py`. The static path wins over the wildcard when it comes first.

**Why:** FastAPI's internal Starlette router walks routes in registration order and returns the first match; it does NOT globally prefer static segments over wildcards across separately-registered routers.

**How to apply:** Any time you add a new router that has a static path whose prefix overlaps a wildcard in an existing router, register the new router first in `main.py`. Document the ordering requirement with a comment.
