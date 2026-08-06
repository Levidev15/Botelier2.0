---
name: MCP channel lifecycle and Pipecat schemas
description: Non-obvious lifecycle and schema rules for MCP across voice, SMS, and simulator channels.
---

Pipecat's MCP `register_tools_schema()` registers handlers only; it does not add
schemas to an `LLMContext` that already exists. Discover and filter MCP tools
before pipeline creation, merge surviving `FunctionSchema` objects into the
initial tool contract, and bind handlers only for those same names. Native
platform tool names always win collisions.

**Why:** A voice integration can successfully start an MCP session and register
handlers yet expose zero MCP tools to the model if schemas are added after the
pipeline context is created.

**How to apply:** For every voice/Pipecat change, preserve the ordering
`start → discover/filter/merge schemas → create LLMContext/pipeline → execute →
close`. Enforce ownership, active/connected state, supported transport, and the
assistant's enabled-tool allowlist before merging.

AnyIO-backed MCP transport contexts must be opened, used, and closed by the same
async task. A sequence of separate `asyncio.run()` calls is not a valid
session lifecycle even when invoked from the same thread.

**Why:** AnyIO context-manager teardown is task-owned and can raise task-group
errors when a later task attempts to close a session opened by an earlier one.

**How to apply:** Keep an entire short-lived channel turn (such as SMS)
inside one coroutine. If the public service boundary is synchronous, bridge
once around that whole coroutine rather than once per connect/execute/close
operation.