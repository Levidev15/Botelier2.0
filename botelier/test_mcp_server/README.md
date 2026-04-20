# `test_mcp_server/` — Dev-only sample MCP server

## Purpose

Tiny standalone MCP server used during development to exercise the end-to-end MCP-tool path (discovery → invocation) without depending on a real third-party MCP host.

## Main files

| File | Role |
|---|---|
| `server.py` | Starlette app exposing a single MCP server over SSE. Declares sample tools (e.g. `get_current_time`). Auth via the `TEST_MCP_API_KEY` env var (default `test-api-key-12345`). |

## How it connects

- Configured as an MCP connection on a test account in the dashboard (`api/mcp_connections.py`).
- Discovered + invoked at call time by `services/mcp_client.py`.
- Has no production role — purely for development verification.

## Conventions

- Tools are added by extending the `@mcp_server.list_tools()` and `@mcp_server.call_tool()` handlers in `server.py`. Keep them trivial — anything more than illustrative belongs in a real backing service.

## Setup

Workflow `test-mcp-server`:

```
cd botelier/test_mcp_server && python server.py
```

Override the API key via `TEST_MCP_API_KEY` env var.

## Gotchas

- Not multi-tenant. Don't point production accounts at this server.
- The file header notes "It can be removed once MCP integration is verified" — leaving it in place is convenient for regression testing but it should never be deployed.
