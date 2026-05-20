---
id: mcp-server
title: MCP Server
sidebar_label: MCP Server
---

# MCP Server Connections

**MCP (Model Context Protocol)** is an open protocol for connecting AI models to external data sources and tools. Botelier supports MCP via SSE (Server-Sent Events) transport, allowing you to connect any MCP-compatible server and expose its tools to your AI assistants.

## What MCP Is

MCP servers expose a list of **tools** — named functions with input schemas and descriptions — that the AI model can discover and invoke. This is similar to Botelier's built-in tool types, but with MCP you can connect to any server that implements the protocol.

Common MCP server use cases:
- Custom CRM lookup
- Inventory management system
- Ticketing and helpdesk systems
- Internal databases
- Any service with an MCP adapter

## Adding an MCP Connection

1. Navigate to **Integrations** → **MCP Connections**.
2. Click **New MCP Connection**.
3. Fill in:

| Field | Description |
|---|---|
| **Name** | Internal label for this connection |
| **Description** | Optional notes |
| **Server URL** | The SSE endpoint of your MCP server (must be `http://` or `https://`) |
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
