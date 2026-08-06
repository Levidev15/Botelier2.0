---
id: mcp-server
title: MCP Server
sidebar_label: MCP Server
---

# MCP Server Connections

**MCP (Model Context Protocol)** is an open protocol for connecting AI models to external data sources and tools. Botelier connects to any MCP-compatible server and exposes its tools to your AI assistants.

## Supported Transports

Botelier supports **two** MCP transports for new and updated connections:

| Transport | Value | When to use |
|---|---|---|
| **Streamable HTTP** | `streamable_http` | Recommended for newer/hosted MCP servers |
| **SSE (Server-Sent Events)** | `sse` | Servers that expose a Server-Sent Events endpoint |

Both transports run over `http://`/`https://`. Other transports (`stdio`, `http`, `websocket`) are **not supported** — attempting to create or update a connection with one of these returns a `400` error telling you to pick `streamable_http` or `sse`. Older connections that still reference a legacy transport keep loading, but you must switch them to a supported transport before they can be re-saved or tested.

## What MCP Is

MCP servers expose a list of **tools** — named functions with input schemas and descriptions — that the AI model can discover and invoke. This is similar to Botelier's built-in tool types, but with MCP you can connect to any server that implements the protocol.

Common MCP server use cases:
- Custom CRM lookup
- Inventory management system
- Ticketing and helpdesk systems
- Internal databases
- Any service with an MCP adapter

## Where MCP Tools Are Available

Once discovered tools are linked to an assistant, they are available across Botelier's assistant surfaces:

- **Voice** — the LLM includes MCP tools in its function-calling schema during live phone calls.
- **SMS** — the same assistant tool set is offered on inbound/outbound SMS conversations.
- **Simulator** — you can exercise MCP tools in the in-app simulator before going live, without placing a real call or sending a real message.

:::danger Arbitrary MCP servers do not get certified-integration protections
Botelier's **certified integrations** ship with per-property data isolation, rate limiting, and circuit-breaker protection. Arbitrary MCP servers you connect here **do not** get these guarantees:

- **No property isolation** — an MCP server sees whatever data you send it; it is not automatically scoped per property/tenant.
- **No rate limiting** — Botelier does not throttle calls to your MCP server on your behalf; a busy assistant can hammer it.
- **No circuit breaker** — a slow or failing MCP server is not automatically tripped/quarantined; failures surface as tool errors to the LLM instead.

Only connect MCP servers you trust and control, and enforce isolation, rate limits, and failure handling on the server side.
:::

## Adding an MCP Connection

1. Navigate to **Integrations** → **MCP Connections**.
2. Click **New MCP Connection**.
3. Fill in:

| Field | Description |
|---|---|
| **Name** | Internal label for this connection |
| **Description** | Optional notes |
| **Transport** | `streamable_http` (newer servers) or `sse` (Server-Sent Events endpoints) |
| **Server URL** | Your MCP server endpoint for the chosen transport (must be `http://` or `https://`) |
| **Auth Type** | `none`, `api_key`, `bearer_token`, or `basic` |
| **Credentials** | Auth credentials matching the selected type |

4. Click **Create**.

:::warning Security Note
MCP server URLs are validated on creation — localhost, private IP ranges, and link-local addresses are blocked to prevent SSRF. Only publicly routable HTTPS endpoints are accepted.
:::

## Discovering Tools

After creating the connection:

1. Open the MCP connection.
2. Click **Discover Tools**.
3. Botelier connects to the MCP server and fetches the tool list.
4. Discovered tools appear in the **Tools** panel with their names and descriptions.

The connection status changes to **Connected** on success.

## Linking Discovered Tools to an Assistant

1. Open the assistant you want to equip with MCP tools.
2. Under **MCP Connection**, select the connected MCP server.
3. In **Enabled Tools**, check the tools you want the assistant to use.
4. Click **Save**.

The LLM will include these tools in its function-calling schema during calls.

## Monitoring Connection Health

The MCP Connections list shows the last connected timestamp and any errors. If a connection fails at call time (the MCP server is unreachable), the tool invocation returns an error to the LLM, which gracefully handles it.

Test the connection proactively by clicking **Test Connection** on the connection detail page.

## Re-Discovering Tools

MCP server tool lists can change when the server is updated. To re-sync:

1. Open the MCP connection.
2. Click **Discover Tools** again.
3. The tool list is refreshed. Previously enabled tools that no longer exist are automatically disabled.

## API Reference

```bash
# Create a connection
POST /api/mcp-connections

# List connections for an account
GET /api/mcp-connections?account_id={account_id}

# Test an existing connection
POST /api/mcp-connections/{id}/test

# Discover tools
POST /api/mcp-connections/{id}/discover-tools

# Test without saving
POST /api/mcp-connections/test
```

**Relevant backend files:**
- `botelier/backend/botelier/api/mcp_connections.py`
- `botelier/backend/botelier/services/mcp_client.py`
