# Threat Model

## Project Overview

Botelier is a multi-tenant SaaS platform for hotel and service-business voice and SMS automation. The production system consists of a Next.js frontend (`botelier/frontend`) and a FastAPI backend (`botelier/backend`) backed by PostgreSQL, with Twilio for voice/SMS, OpenAI and other AI providers for message/call processing, and optional third-party hotel/PMS integrations plus MCP servers.

The core security goal is strict tenant isolation by `account_id` across calls, SMS, assistants, analytics, integrations, uploads, and admin support tooling. The browser is untrusted. Public webhook-style routes exist for Twilio and invitation/auth flows. Production assumptions for this scan: mockup sandboxes are out of scope, `NODE_ENV=production`, and platform TLS terminates correctly at the edge.

## Assets

- **User accounts and sessions** — email/password accounts, JWTs, support-session tokens, and admin impersonation context. Compromise enables takeover of tenant and admin workflows.
- **Tenant business data** — SMS conversations, phone numbers, call logs, analytics, assistant configs, knowledge bases, templates, and notification settings. This data is customer-facing, often sensitive, and must remain isolated per account.
- **Customer communications and attachments** — call transcripts, recordings, SMS/MMS content, uploaded files, and phone numbers. Exposure leaks personal data and business communications.
- **Provider and integration secrets** — Twilio sub-account credentials, AI provider keys, integration credentials, MCP credentials, database URLs, and encryption keys. Compromise enables spoofing, outbound abuse, and cross-system access.
- **Outbound network capability** — server-side HTTP clients used for API testing, integrations, MCP connections, and other external calls. Abuse can turn the backend into an SSRF pivot.
- **Flow execution state** — visual flow definitions, variables, tool invocations, and runtime interpreter behavior in `flow_executor.py`. Unsafe evaluation here can become code execution or privilege escalation inside the backend.

## Trust Boundaries

- **Browser ↔ FastAPI API** — all dashboard and auth traffic crosses this boundary. The client is untrusted; every account/role check must be enforced server-side.
- **Public internet ↔ webhook/media endpoints** — Twilio-facing call, SMS, simulation, and WebSocket routes are reachable without JWTs in several places and therefore require strict origin/authenticity validation.
- **FastAPI ↔ PostgreSQL** — the backend has broad authority over all tenant records. Broken auth or unsafe query scoping at the API layer directly exposes cross-tenant data.
- **FastAPI ↔ third-party services** — the backend makes authenticated outbound requests to Twilio, AI providers, hotel/PMS APIs, and MCP servers. User-controlled destinations or credential mishandling create SSRF and secret-exposure risk.
- **Authenticated user ↔ platform admin / support session** — support-session headers and account-switch context cross a privilege boundary and must be validated server-side.
- **Private uploaded files ↔ public web root** — user-uploaded MMS content is written to `backend/uploads` and served from `/uploads`; this boundary determines whether attachments are effectively public or can become active content on the app origin.
- **Configured flows ↔ backend execution engine** — non-code users can influence runtime flow behavior; unsafe interpreters or templating can convert configuration into execution.

## Scan Anchors

- **Production entry points:** `botelier/backend/main.py`, `botelier/backend/botelier/api/`, `botelier/frontend/app/`, `botelier/frontend/lib/auth/`.
- **Highest-risk areas:** `auth/middleware.py`, `api/sms_pkg/`, `api/calls.py`, `api/websockets.py`, `api/api_tester.py`, `api/mcp_connections.py`, `api/integrations.py`, `services/integration_client.py`, `services/mcp_client.py`, `api/simulation.py`, `flow_executor.py`, upload/static file handling in `main.py` and `api/sms_pkg/settings.py`.
- **Public surfaces:** `/api/auth/*`, `/api/calls/*`, `/api/ws/call`, `/api/sms/webhook`, `/api/sms/upload`, `/api/api-tester/test`, `/api/mcp-connections*`, `/api/simulate/*`, invitation endpoints, `/uploads/*`.
- **Authenticated/admin surfaces:** most dashboard CRUD APIs, `/api/admin/*`, `/api/integrations*`, account/team management, feature/admin support flows.
- **Usually dev-only / lower priority:** `.agents/`, `.local/skills/`, tests, docs, and scaffolding unless a production path proves otherwise.

## Threat Categories

### Spoofing

Botelier relies on JWTs for dashboard access and Twilio signatures for public messaging/call callbacks. The system must reject forged or weakly-signed tokens, must not accept fallback secrets in production, and must verify the authenticity of every public Twilio-triggered HTTP or WebSocket entry point before trusting caller identity, phone numbers, or call metadata.

### Tampering

Users and external services can supply account IDs, conversation IDs, uploaded files, flow variables, MCP/integration endpoints, and webhook payloads. The backend must treat all of these as untrusted, bind them to the authenticated tenant or validated webhook source, and prevent user-controlled configuration from becoming executable logic or unauthorized state changes.

### Information Disclosure

The platform stores customer phone numbers, SMS content, call transcripts, recordings, and attachments. API responses, exports, analytics, uploads, and logs must be scoped to the correct tenant and role. Secrets, provider tokens, and support-session context must never be exposed to browsers, logs, or unrelated tenants.

### Denial of Service

Several public routes can trigger network calls, media handling, file uploads, simulation, and LLM-related processing. Public-facing endpoints must authenticate origin where appropriate, constrain payload size and execution time, and avoid letting unauthenticated callers create expensive backend work or unbounded outbound traffic.

### Elevation of Privilege

This application has meaningful privilege layers: unauthenticated internet users, regular tenant users, privileged tenant users, support-session admins, and platform admins. Every route that touches tenant data or account configuration must require the correct authenticated context and permission check. Cross-tenant access by manipulating `account_id`, impersonation by forged tokens, and code execution from flow configuration are all in-scope elevation-of-privilege threats.
