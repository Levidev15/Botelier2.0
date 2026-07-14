---
id: integrations-overview
title: Integrations Overview
sidebar_label: Integrations Overview
---

# Integrations Overview

The **Integrations** framework lets your AI assistant connect to external systems during calls and SMS conversations. It supports pre-built connectors for hotel PMS/CRS systems, a flexible MCP server connection protocol, and direct API calls via flow nodes.

## Integration Types

| Type | How to Connect | Use in Flows |
|---|---|---|
| **Direct API (pre-built)** | OAuth2 or Basic Auth configured in Botelier UI | Via API Request nodes in flows and tools |
| **MCP Server** | SSE endpoint URL + optional auth | Via discovered MCP tools linked to the assistant |
| **Custom API via Flow** | API Request node + Account Secrets | Any flow or tool — no integration record needed |

## Pre-Built Integrations

Botelier ships with pre-configured integration types:

| Integration | Auth Type | Notes |
|---|---|---|
| **Oracle Opera Cloud (OHIP)** | OAuth2 Client Credentials | Hotel PMS; see [Oracle Opera OHIP](./oracle-opera-ohip) |
| **GuestCentric CRS** | Basic Auth or JWT | Hotel CRS; see [GuestCentric CRS](./guestcentric-crs) |

Adding a new pre-built integration (a new row in this table)? See [Adding a New Integration](./adding-a-new-integration) for the complete, worked-example-driven guide covering the seed definition, auth/runtime behavior, flow-editor wiring, docs, and testing.

Endpoints that model shared PMS concepts (reservations, guests, rooms, rate plans, availability) can additionally emit a **vendor-neutral** shape so a consumer can't tell which vendor produced the data. See [Canonical Domain Schemas](./canonical-domain-schemas).

Your AI can also call **abstract, vendor-neutral capabilities** (`search_availability`, `lookup_reservation`, `book_reservation`, `cancel_reservation`) that resolve at runtime to the caller's property-scoped provider — the AI never sees which vendor serves the request. See [Universal Capability Tools](./universal-capability-tools).

## How Integrations Surface in Flows and Tools

Once connected, an integration's endpoints appear in:

1. **Flow Editor** → API Request nodes → "Integration" dropdown
2. **Tool configuration** → API Request type → "Use Integration" toggle

Selecting an integration auto-populates the URL and headers using the stored credentials — you don't need to manually handle auth tokens.

## MCP (Model Context Protocol) Connections

MCP connections expose dynamic tools from any MCP-compatible server. After connecting and discovering tools, you can link specific MCP tools to an assistant, and the LLM can invoke them during calls like any other tool.

See [MCP Server](./mcp-server) for setup instructions.

## Custom API via Flow

For any API not covered by a pre-built connector or MCP server, you can call it directly:

1. Store credentials in **Account Secrets** (encrypted key-value store)
2. Use an **API Request** node or tool in the Flow Editor
3. Reference secrets with `{{secret.KEY_NAME}}` in headers

See [Custom API via Flow](./custom-api-via-flow) for a worked example.

## Connection Health Monitoring

Each connected integration shows a **status** in the Integrations list:

| Status | Meaning |
|---|---|
| **Connected** | Auth verified; ready to use |
| **Connecting** | Auth in progress |
| **Error** | Auth failed or connection lost |
| **Disconnected** | Not yet connected |

For OAuth2 integrations, Botelier automatically refreshes access tokens before expiry.
