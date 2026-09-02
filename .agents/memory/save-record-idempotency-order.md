---
name: SAVE_RECORD idempotency order
description: The saved_records check must come before the spent-node guard; the creation lock must be a separate dict from handle_function_call's entry lock.
---

## Rule
`_handle_save_record_locked` must check `node_id in self.state.saved_records` **before** the spent-node guard (`current_node_id != node_id`). A reconnect or concurrent retry may arrive when the flow has advanced past the save node; the spent-node guard would return `out_of_order` (no `record_saved` key) instead of the correct cached result.

`_handle_save_record` acquires `_save_record_creation_locks[node_id]` (a separate dict) to serialise direct callers. It must NOT use `_save_record_locks` — that lock is acquired by `handle_function_call` before `_turn_lock`, and re-acquiring it inside `_handle_save_record` would deadlock.

**Why:** The spent-node guard exists to prevent re-executing a node's side effects; but if the record is already in `saved_records`, there are no side effects to prevent — the correct response is always "Record was already saved" regardless of current node position.

**How to apply:** Any new action-node handler that has both an idempotency cache and a spent-node guard should check the cache first. The two-lock pattern (outer entry lock in `handle_function_call` + inner creation lock in the handler) is the canonical serialisation structure for SAVE_RECORD and should be followed for any handler that can be called concurrently.
