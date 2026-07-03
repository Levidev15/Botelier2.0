---
name: SAVE_RECORD & live-call FlowExecutor sessions
description: Why voice-path flow handlers that write to the DB must open their own SessionLocal, not use self.db_session.
---

On a live voice call, `FlowExecutor` runs with `db_session=None`. The live path builds
`FunctionMapper(...)` in `voice/call_handler.py` WITHOUT a `db_session`, and the mapper
passes that same `None` into every `FlowExecutor(...)` it constructs. Only the simulator
(`api/simulation.py`) and other request-scoped callers pass a real session.

**Consequence:** any flow handler that guards on `if not self.db_session: return` becomes a
silent no-op in production while still "working" in the simulator — the exact trap that lets a
simulation/screenshot demo pass while real calls persist nothing (this is how the first
SAVE_RECORD implementation shipped broken).

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
