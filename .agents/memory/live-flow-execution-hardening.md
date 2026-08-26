---
name: Live flow execution hardening
description: Root causes and fix patterns from auditing "does the LLM follow the flow correctly end-to-end" on a live call — dead air, duplicate tool calls, phantom flow sessions, exhausted-flow narration, and transcript ordering.
---

## parallel_tool_calls defaults to True
Pipecat/OpenAI's `parallel_tool_calls` is `True` unless explicitly disabled in the LLM service's `extra` params (see `create_llm_service` in `botelier/backend/botelier/voice/engine.py`). Left enabled, a single model turn can fire two tool calls at once — this was the root cause behind both a duplicate GET (an availability check firing twice) and a phantom flow_sessions row (a second flow's start trigger firing alongside the active flow's).

**Why:** discovered by reading the installed Pipecat source after seeing both bugs on the same live call; no doc surfaces this default.
**How to apply:** any new LLM service wiring must inherit `parallel_tool_calls=False`; don't assume tool-call fan-out is single unless it's set.

## Direct-speech guarantee for flow node handlers
Flow node handlers that advance silently — SET_VARIABLE, ROUTER, SAVE_RECORD, CONFIRMATION/confirm_details — must not rely on the LLM "continuing on its own" to speak the next thing. A confirm_details → dead-node transition produced ~10s of real dead air on a live call. The fix pattern: handlers set `result["speak_directly"] = True` (plus `result["speak_exactly"]` when the destination node uses static delivery) whenever `message` is genuine caller-facing content; internal/debug-only text (e.g. "Set X to Y", "Routing to: X") is never spoken directly unless it resolves into a real destination node's configured message via a shared resolver (`_get_next_node_configured_message` in `flow_executor.py`). `function_mapper.py`'s function-call handler bridges any `speak_directly` result into a `TTSSpeakFrame` and gates `run_llm=False` accordingly.

**Why:** LLM "continuation" after a function result is not guaranteed to produce audible speech before the next turn; caller-facing content must be pushed directly.
**How to apply:** any new flow node type whose handler can advance to a caller-facing destination without going through a COLLECT/API prompt must follow this same pattern.

## Exhausted-flow guardrail needs its own flag, separate from "terminal action executed"
`FlowState.advance_to` in `flow_executor.py` sets a dedicated `graph_exhausted = True` whenever the landed node has no outgoing edge in `flow_config.edges` — not just on explicit END/TRANSFER nodes. This generically covers MESSAGE dead-ends (a flow authored without an END node) without special-casing node types. Once `graph_exhausted` is true and the current node isn't END/TRANSFER (which already have their own call-to-action instructions), `_get_current_node_context()` injects a "FLOW COMPLETE" instruction telling the LLM not to claim it booked/saved/transferred anything unless a function result already confirmed it. `graph_exhausted` is purely structural ("nothing further in the graph from here"); it is intentionally a different field from `is_complete`, which means "a terminal action (end_call/transfer) has actually executed" and is the idempotency guard inside `_handle_end_call`.

**Why:** an earlier version reused `is_complete` for both meanings. The moment any silent handler (SET_VARIABLE/ROUTER/SAVE_RECORD/CONFIRMATION) advanced straight into an END/TRANSFER node, `advance_to` flipped `is_complete` True purely from landing there — before the code that actually fires the end/transfer callback ever ran — so that code's own idempotency guard then swallowed itself as a "duplicate" and returned an empty result. The call never actually ended or transferred; it just went silent after speaking the closing text.
**How to apply:** keep the two flags separate. Only `_handle_end_call`'s own execution (and the retry-exhausted path) may set `is_complete`. Structural dead-ends of any node type should only ever set `graph_exhausted`. On session rehydration, restore `graph_exhausted` from the persisted status but leave `is_complete` at its default `False` — a session with a truly-executed terminal action wouldn't be reconnecting to rehydrate in the first place.

## Silent advances into END/TRANSFER must execute the real terminal action, not just speak its text
Any flow node handler that can silently advance to a next node and surface that destination's configured message via `speak_directly` (SET_VARIABLE, ROUTER, SAVE_RECORD, CONFIRMATION and its `confirm_details` counterpart) must check whether the destination is an END or TRANSFER node *before* falling back to plain message-surfacing. If it is, route through the same handler an explicit `end_call_<id>`/`transfer_<id>` LLM function call would use (a shared `_maybe_execute_terminal_transition` helper dispatches to `_handle_end_call`/`_handle_transfer` with a synthetic function name derived from the destination node's id) so the real callback fires and the result carries `action: "end"`/`"transfer"`. `function_mapper.py` already has dedicated handling for those two action values that pushes the speech and performs the actual hangup/dial — it deliberately bypasses the generic `speak_directly` path.

**Why:** speaking a node's configured text is not the same as executing it. A destination-message resolver that only knows how to read `closingMessage`/`preTransferMessage` text has no way to also invoke the callback that ends or transfers the call — only the dedicated end/transfer handler does that.
**How to apply:** any new flow node type whose handler can silently advance to a caller-facing destination must check the destination's node type for END/TRANSFER first, and delegate to the real terminal handler rather than inventing its own message-only shortcut.

## flow_sessions lifecycle — complete_call is the one convergence point
`CallLogger.complete_call()` (`botelier/backend/botelier/services/call_logger.py`) is reached by every call teardown path — normal pipeline shutdown, the Twilio `/status` safety net, and the stuck-call sweeper/defensive-finalize paths. It's the right (and only) place to mark any still-`"active"` `flow_sessions` row `"abandoned"` (via `_abandon_active_flow_sessions`, raw SQL scoped to `status = 'active'`) so a session that already legitimately reached `"complete"` on its own is never touched.

**Why:** durable flow_sessions snapshots only ever reached "complete" via the in-memory executor's own `is_complete` flag before writing its next snapshot — a call that drops mid-flow left the row stuck "active" forever with no record the flow was cut short.
**How to apply:** any future call-teardown code path should still route through `complete_call()` rather than adding a parallel finalization path, or it will bypass this (and the transcript-save) logic.

## Transcript extra_messages must join the sort, not append after it
`_extract_transcript` (`botelier/backend/botelier/voice/call_handler.py`) does a single global chronological sort of the transcript (interpolating untimed entries between timed neighbours). `extra_messages` — content that bypassed the LLM context entirely, e.g. the pre-transfer `TTSSpeakFrame` message — must be merged into the list *before* that sort runs, tagged with `_elapsed_s` when available (computed from `call_handler.call_start_times`). Appending them after the sort (the original bug) forces them to the tail regardless of when they were actually spoken.

**Why:** any future caller of `_save_call_transcript(..., extra_messages=...)` gets correct chronological placement for free; the interpolation fallback (no anchor) still places an appended-at-list-end entry after the last timed entry, which is usually right for anything spoken near call end.
**How to apply:** always pass new extra/bypass transcript entries through `_extract_transcript`'s `extra_messages` param, never splice them into the return value afterward.
