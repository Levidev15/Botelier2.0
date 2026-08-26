---
name: SAVE_RECORD & live-call FlowExecutor sessions
description: Why voice-path flow handlers that need DB access must use session_factory or open their own SessionLocal, never rely on self.db_session.
---

On a live voice call, `FlowExecutor` runs with `db_session=None`. The live path builds
`FunctionMapper(...)` in `voice/call_handler.py` WITHOUT a `db_session`, and the mapper
passes that same `None` into every `FlowExecutor(...)` it constructs. Only the simulator
(`api/simulation.py`) and other request-scoped callers pass a real session.

**Consequence:** any flow handler that guards on `if not self.db_session: return` becomes a
silent no-op in production while still "working" in the simulator — the exact trap that lets a
simulation/screenshot demo pass while real calls persist nothing (this is how the first
SAVE_RECORD implementation shipped broken). The same applies to READ paths: integration-template
API nodes silently fall through to generic custom-HTTP dispatch, `{{secrets.*}}` substitution is
skipped, and connection_config injection does nothing — all because `db_session` is None live.

**Fix (session_factory pattern):** `FlowExecutor` and `FunctionMapper` now accept a
`session_factory` kwarg (callable → Session). `call_handler.py` passes
`session_factory=SessionLocal` to `FunctionMapper`, which threads it into every `FlowExecutor`.
A `_borrow_db_session()` contextmanager on `FlowExecutor` opens a short-lived session from the
factory when `db_session is None`, yields it, and closes it in `finally`. Every DB-touching
method uses this helper: `_resolve_integration_slug`, `_substitute_secrets`,
`_inject_connection_config_to_slots`, ActionExecutor calls in `_handle_*_api_request`,
`_write_custom_call_log`, and `rehydrate_state`. When `db_session` is provided (simulator),
`_borrow_db_session` borrows it as-is (never closes it). `_map_dynamic_operation` in
`function_mapper.py` uses an explicit `(session, owned)` tuple for sync gating + schema loading
and for the async execution handler.

**Loud failure:** integration API nodes with an unresolvable connection return a caller-safe
error dict instead of silently falling through to `_handle_custom_api_request`. The guard
lives in `FlowExecutor._handle_api_request`, immediately after the slug-resolution block.

**Rule:** flow handlers that must write to the DB (e.g. `_handle_save_record`) open their own
short-lived `from botelier.database import SessionLocal` session, do their query+insert+commit,
and `close()` in `finally`. Do NOT plumb a shared session in instead.

**Why:** besides fixing the None case, a shared session would make the handler's
`commit()`/`rollback()` commit or roll back unrelated pending business/observability writes on
that session — violating the project's "decoupled writes from observability" invariant. A
dedicated session fixes both the no-op bug and the coupling hazard. Mirror the existing
`FunctionMapper.track_tool_usage` SessionLocal pattern.

**Related:** REST `<Refer>` cold transfers (both plain and flow transfers in
`voice/function_mapper.py`) never get Twilio's `/connect-complete` callback, so ACW *and*
record auto-extraction must be triggered inline in the transfer worker thread — the normal
`/connect-complete` and call-status webhook paths in `api/calls.py` are skipped for that path.

**Note:** `flow_executor.py` had NO `logger` import for a long time — `logger` was referenced
only in rarely-hit exception handlers (so it never raised at import time, and the module booted
clean), which masked a latent `NameError`. It now imports `from loguru import logger`. Because
loguru is `{}`/f-string style, `%s` printf args do not interpolate and `exc_info=` is ignored
(use `logger.exception(...)` for tracebacks). Any new `logger.*` call on a success path here
must have that import present — a clean boot does NOT prove the logger resolves.
