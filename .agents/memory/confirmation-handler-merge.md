---
name: Confirmation handler merge
description: How the two confirmation handlers were unified and what the canonical pattern looks like now.
---

# Confirmation handler merge

## The rule
All confirmation logic lives in `_run_confirmation_logic(node, confirmed, arguments)`. Both public entry points are thin dispatchers — never add confirmation behavior to the entry points directly.

**Why:** `_handle_confirm_details` previously duplicated `_handle_confirmation` (~170 lines) and had already diverged: it used `get_next_node(handle="confirmed")` (strict) instead of `_confirmed_branch_next_node()` (which has the edge-fallback guard). Future edits to one would not propagate to the other.

## How to apply
- `_handle_confirmation(function_name, arguments)` — resolves node via `_node_index.get(node_id)`, calls `_run_confirmation_logic`
- `_handle_confirm_details(arguments)` — finds CONFIRMATION node by type scan; if found, calls `_run_confirmation_logic`; if not found, runs the simple no-node fallback tail (sets `_details_confirmed = True`, returns "Great, confirmed.")
- `_run_confirmation_logic(node, confirmed, arguments)` — canonical: reads all templates upfront, uses `_confirmed_branch_next_node()` for confirmed path, consistent result shape (`action: None, confirmed: True/False, speak_directly: True`)

## Edge-fallback guard (the bug this fixed)
`_confirmed_branch_next_node()` falls back to any non-edit outgoing edge when no `sourceHandle="confirmed"` edge exists. Seeded/imported flows often lack this handle, causing the old `_handle_confirm_details` to stall the flow on the confirmation node after the caller says yes.

## Result shape invariant
Both paths produce: `{success, action: None, confirmed, current_node_id, message, speak_directly}`. The no-node fallback tail is the only place that uses `action: "confirmed"` (and `collected_data`) — kept for the simple ack path, not consumed downstream.

## Test file
`botelier/backend/tests/test_flow_executor_hardening.py` → `TestConfirmationHandlerParity` (13 tests). Key tests:
- `test_edge_fallback_guard_via_confirm_details` — regression guard for the stall bug
- `test_correction_path_via_confirm_details_matches` — slot updated + message re-rendered via both paths
- `test_confirmed_summary_message_appears_in_both_entry_points` — same message regardless of entry point

## SlotType note
Variable definitions in tests must use `"type": "text"` (not `"string"`) — `SlotType` enum values are: text, date, number, phone, email, time, choice.

## Test flow design note
When testing the confirmed-path result shape, the flow's confirmed target must NOT be an END or TRANSFER node — `_maybe_execute_terminal_transition` fires and returns early with a different shape. Use a `save_record` or other non-terminal node as the intermediate step after confirmation, then chain to END.
