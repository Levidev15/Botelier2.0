---
name: MCP tool calls that opaquely cancel instead of erroring, and Shopify UCP profile negotiation
description: Why an MCP tool call can surface as a bare asyncio.CancelledError instead of a real error, and why Shopify (and other UCP-compliant) commerce MCP tools need a self-hosted agent profile the LLM can never supply itself.
---

## Non-2xx MCP responses surface as opaque CancelledError, not a catchable error

The `mcp` Python SDK's streamable-http transport calls
`httpx.Response.raise_for_status()` inside a child task of an AnyIO
`TaskGroup`. When the MCP server responds with a non-2xx status, that
raise cancels the *whole* TaskGroup — including whatever task is blocked
in `call_tool()` — so the caller only ever observes a bare
`asyncio.CancelledError`. The real status code/body is not attached to
that exception; it is only reachable from the `ExceptionGroup` that
`client.close()` re-raises while tearing down the same already-failed
transport in the `finally` block.

**Why this matters:** any fix that only guards `client.close()` with a
blanket `except (Exception, CancelledError): pass` (to stop a real
successful result from being discarded on cleanup) will also silently
swallow the one place the real error detail lives, making every failure
mode — auth errors, rate limits, malformed requests — look identical and
undiagnosable in logs.

**How to apply:** capture the close()-time exception in a small mutable
dict closed over by the isolated-call coroutine, and walk it recursively
(`BaseExceptionGroup.exceptions`, Python 3.11+ builtin) looking for an
`httpx.HTTPStatusError` to extract `status_code` + response body; fall
back to describing the first exception found. Surface that detail in the
existing cancellation log line instead of a generic "transport close"
message. See `_describe_mcp_transport_error` /
`_mcp_isolated_tool_call` in `botelier/voice/call_handler.py`.

## Shopify UCP-shaped MCP tools require a self-hosted agent profile

Shopify's Universal Commerce Protocol (UCP) tools — `search_catalog`,
`get_cart`/`create_checkout`, `get_order`, etc. — all require a
`meta.ucp-agent.profile` field in every `tools/call` request: an HTTPS URL
to a JSON document declaring the calling agent's protocol version and
supported capabilities. The merchant server fetches, validates (strict
`Content-Type: application/json` + a valid `Cache-Control` header — a
missing/invalid one fails with `profile_malformed`), and negotiates
against it before executing the tool.

**Why this matters:** no LLM can invent a valid, fetchable profile URL
from a voice conversation. Leaving `meta` in the tool schema just invites
the model to hallucinate a value, which fails identically to omitting it
— a placeholder/fake URL was confirmed to fail the same way as no URL at
all. This is a systemic requirement across every UCP-shaped tool (detected
generically by schema shape: `properties.meta.properties["ucp-agent"]
.properties.profile`), not specific to one tool name.

**How to apply:** (1) host a real, static profile document at a public,
unauthenticated endpoint declaring only the capabilities actually
implemented (`botelier/api/ucp_profile.py`, served at
`/api/ucp/agent-profile.json` — see the proxy-routing note below for why
it must live under `/api/`), with `Cache-Control` set; (2) strip `meta`
from the LLM-facing schema for any tool matching that shape
(`_detect_and_strip_ucp_meta`) so the model never sees or has to fill it;
(3) inject `meta.ucp-agent.profile` server-side into the call arguments at
call time for exactly those tools, only when the arguments don't already
carry a `meta` key. Cart/checkout capability extensions (fulfillment,
discount, buyer_consent) beyond the base set are unverified — a
negotiation failure there will now show the real error via the
diagnostics above instead of an opaque cancellation.

## Three independent MCP tool-calling implementations — a fix to one does not cover the others

This codebase does not have a single shared MCP client. Voice
(`botelier/voice/call_handler.py`, per-call isolated task), the Test Lab
simulator (`botelier/api/simulation.py`), and SMS
(`botelier/services/sms_service.py`) each call MCP tools through their own
code path. Simulator and SMS both go through the persistent-session
`services/mcp_client.py::MCPClient` — a different class from voice's
per-call `_mcp_isolated_tool_call`.

**Why this matters:** the UCP detection/stripping/injection fix above was
applied only to the voice path. As of the fix, `MCPClient` has zero UCP
awareness, so a Shopify UCP tool (e.g. `search_catalog`) invoked from a
Test Lab simulation or an SMS conversation still fails with the
opaque/fallback error the voice path used to have. This was a deliberate
scope decision (user declined to extend it), not an oversight — confirmed
still unfixed as of 2026-09-03.

**How to apply:** before assuming any MCP-related fix (UCP or otherwise)
is complete, grep for all three call sites, not just the one you were
pointed at. If UCP support is ever extended to simulator/SMS, the
detect/strip/inject logic will need a `MCPClient`-shaped equivalent (its
`discover_tools()`/`execute_tool()` lifecycle differs from voice's
per-call isolation).
