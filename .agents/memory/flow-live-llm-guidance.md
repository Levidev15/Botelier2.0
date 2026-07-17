---
name: Live-call flow guidance & post-save record sync
description: How per-node instructions reach the live LLM, why the flow trigger suppresses its completion, and how saved records stay in sync after corrections.
---

# Flow trigger must suppress its post-function completion

**Rule:** The live flow trigger handler speaks the greeting + first question itself via `TTSSpeakFrame`, then must pass `properties=FunctionCallResultProperties(run_llm=False)` to `result_callback`. If nothing was actually spoken (empty initial messages), fall back to the default completion to avoid dead air.

**Why:** Without `run_llm=False`, the post-function LLM completion generates its own greeting/question on top of the spoken one — the caller hears a double greeting at flow start. The result still lands in context; the next caller utterance triggers a normal completion.

**How to apply:** Any handler that speaks directly via TTS frames and then returns a function result must decide whether the completion should run. The universal context aggregator honors `properties.run_llm`.

# Per-node instructions reach the live LLM through function results

**Rule:** The simulator delivers CURRENT NODE guidance via a per-turn system-prompt rebuild; live calls can't do that, so guidance rides in function results instead:
- `handle_function_call` (central chokepoint) attaches `current_node_context` to every non-terminal result (action not transfer/end).
- Slot-collection results carry the collecting node's resolved instructions as `node_instructions` (applied to the value just collected, e.g. "spell the name back").
- The flow trigger payload includes per-variable instructions + a reference-only `current_node_context` (annotated "already spoken — do not repeat" so the LLM doesn't re-ask question 1).
- Behavioral rules 11–12 in `build_flow_behavioral_rules` tell the LLM to honor these keys.

**Why:** Node instructions previously only reached the LLM in the simulator; live calls ignored the editor's per-node guidance (e.g. confirmation phrasing).

# Post-save record sync (stale-record fix)

**Rule:** `FlowState.saved_records` (node_id → record_id) is stamped after each SAVE_RECORD commit. `_sync_saved_records` runs after every function call: recomputes the payload via the shared `_resolve_record_payload` and updates the record only if changed — own short-lived session in a worker thread, account-scoped lookups, errors swallowed.

**Why:** A caller correcting a value via confirm/edit AFTER the save node fired left the stored record silently stale.

**Snapshot trick:** saved record ids persist inside the `flow_sessions.collected_slots` JSON under the reserved `_saved_records` key (stuffed at snapshot, popped at rehydrate) — no schema change, never enters LLM-visible `collected_slots`.
