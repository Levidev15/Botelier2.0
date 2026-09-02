---
name: Spent-node dispatch guard
description: Why flow handlers need a current_node_id equality check and which ones have it.
---

## The rule
Every action-node handler in flow_executor.py must check
`self.state.current_node_id != node_id` and return `{"out_of_order": True, ...}`
before doing any work. Without it, a stale LLM tool list can re-invoke a handler
for a node the flow already advanced past.

## Why
On a live call the LLM's tool context is rebuilt lazily (not after every single
frame). If the LLM holds a context from the previous node advance it can call
e.g. `set_var_<id>` while the flow is already sitting at `save_record_<id>`.
This re-fired the set_var handler, advanced the flow back to Collect Form, and
spoke "May I have your first name?" *after* the booking was already confirmed —
the root cause of a production call failure observed on CA9d7f…c.

## How to apply
- `_handle_option_picker` — guard present (original).
- `_handle_set_variable` — guard added.
- `_handle_save_record` / `_handle_save_record_locked` — guard added.
- `_handle_confirmation` — add if this re-fires.
- Any new action-node handler added in future must include the guard.
- Return shape: `{"success": False, "message": "That step is no longer active.", "action": None, "out_of_order": True, "current_node_id": self.state.current_node_id}`.
- Tests live in `tests/test_spent_node_guards.py`.
