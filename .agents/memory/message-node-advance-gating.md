---
name: MESSAGE node advance gating
description: MESSAGE nodes have no LLM-callable function; a dead-end chain of them leaves the LLM free to fabricate outcomes before hanging up.
---

# MESSAGE node advance gating

Unlike COLLECT_SLOT/COLLECT_FORM and every action node type (SAVE_RECORD,
API_REQUEST, CONFIRMATION, SET_VARIABLE, ROUTER, END, TRANSFER), a MESSAGE
node in the flow engine (`botelier/backend/botelier/flow_executor.py`) emits
**no function schema at all**. Its content is delivered purely through
node-context guidance text in the system prompt — the engine trusts the LLM
to say it and then move on once *something else* becomes callable.

That's fine as long as a COLLECT or action node is reachable somewhere ahead
(MESSAGE/CONDITION/INITIAL are transparent to the forward-reachability BFS
used by `_find_next_reachable_collect_slot` / `_get_reachable_action_node_ids`
/ `has_pending_side_effect_downstream`) — calling that downstream function
implicitly advances `current_node_id` past every MESSAGE node in between.

**But** a MESSAGE node (or a chain of them) that leads only to more MESSAGE
nodes and nothing the engine can expose leaves the LLM with zero flow tools.
Nothing ever calls `advance_to()`, so `current_node_id` never moves, and the
model is free to invent its own questions or narrate a fabricated outcome
(e.g. "your booking is confirmed") before reaching for the global `end_call`
— and since no side-effect node was ever downstream, the existing
`has_pending_side_effect_downstream()` gate correctly stays False, so nothing
blocked it. `flow_sessions.status` also stays `active` → gets stamped
`abandoned` at teardown, silently "explaining" the stuck state without
flagging that the caller was lied to.

**Fix pattern** (`FlowExecutor._get_pending_message_advance_node`): detect a
current MESSAGE node with `waitForResponse: true` that HAS an outgoing edge
but nothing else reachable (no collect, no action) — expose an explicit
`continue_flow_<node_id>` function for it via `get_function_schemas()`, and
extend `is_on_required_action_node()` to treat it as blocking (same
mechanism `end_call` gating already uses via `FunctionMapper` in
`voice/function_mapper.py`). A MESSAGE node with **no** outgoing edge needs
no such function — landing there already sets `graph_exhausted = True`
inside `FlowState.advance_to()`, which naturally unblocks `end_call` once
the terminal message has genuinely been reached (not skipped).

**Why:** prompt-only wording had already failed once in production (Task
#600) — the LLM improvised past a "flow disabled" dead-end message and
implied a completed booking. This repo's precedent (see the `end_call`
gating for SAVE_RECORD/API_REQUEST, Task #420/#296 lineage) is to fix this
class of bug structurally — give the LLM a real tool and gate around it —
never by strengthening prompt instructions alone.

**How to apply:** when adding a new node type or a new dead-end reachable
purely through MESSAGE/CONDITION nodes, check whether it lands the LLM in a
position with zero callable flow functions. If so, it needs the same
explicit-advance-function treatment, not just better wording in its
node-context guidance.
