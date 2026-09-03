---
name: Frontend dev-domain only proxies /api/* and /uploads/* to the backend
description: Why a new FastAPI route is invisible on the public Replit dev domain unless its path starts with /api/ or /uploads/ — the custom Next.js server.js proxy rule, not a backend routing bug.
---

Botelier's frontend (`botelier/frontend/server.js`, a custom Next.js
server) only forwards requests whose path starts with `/api/` or
`/uploads/` to the FastAPI backend (`BACKEND_URL`, default
`http://localhost:3001`); Twilio Media Stream WebSockets
(`/api/ws/*`) get a separate raw TCP relay for the same reason (Nagle's
algorithm batching audio frames). Everything else falls through to
Next.js's own `handle()` and 404s if no page matches.

**Why this matters:** the public Replit dev domain
(`$REPLIT_DEV_DOMAIN`) and the production domain both point at the
frontend (port 5000), not the backend (port 3001) directly. A new backend
endpoint registered in `main.py` works fine when curled against
`127.0.0.1:3001` locally, but is completely unreachable from any
external caller (a third-party webhook fetcher, a public agent-profile
consumer, etc.) unless its path is under `/api/` or `/uploads/` — hit
any other prefix and you get Next.js's generic 404 page instead of a
FastAPI 404, which looks like a routing/registration bug in the backend
but isn't one.

**How to apply:** when adding any new backend route that must be
reachable from outside the container (public webhooks, `.well-known`
style discovery documents, health checks meant for third parties), give
it an `/api/...` path — do not use bare top-level paths like
`/.well-known/...` even if a spec conventionally suggests that URL
shape; hosting it at `/api/<same-name>` is fine for any consumer that
just needs a working public URL to fetch by value.
