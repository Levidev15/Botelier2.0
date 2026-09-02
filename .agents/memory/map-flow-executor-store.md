---
name: _map_flow executor store vs get_flow_functions
description: _map_flow creates a temporary executor for schema building only; it must NOT be stored in _flow_executors or it corrupts the rehydrated executor from get_flow_functions().
---

## Rule
`_map_flow()` must NOT store its executor in `self._flow_executors`. The executor it creates is ephemeral — used only to build the trigger function schema via `_create_slot_function`.

## Why
Two ordering bugs arise when `_map_flow` stores its executor:

**A. map_tool_to_function() runs before get_flow_functions()**
`get_flow_functions()` finds a pre-stored executor and reuses it (line ~2039), skipping `rehydrate_from_snapshot()`. Reconnected callers lose their flow progress.

**B. get_flow_functions() runs before map_tool_to_function()**
`_map_flow()` overwrites the rehydrated executor with a fresh unhydrated one. Same result.

## How to apply
- `_flow_executors` is initialized in `FunctionMapper.__init__` (line 152); the lazy `hasattr` check in `_map_flow` was redundant and removed.
- `_llm_override` is already stamped by `get_flow_functions()` at line ~2071 for every executor it creates — no need to duplicate in `_map_flow`.
- The `flow_trigger_handler` returned by `_map_flow` for non-empty flows is now a loud stub (logs `logger.error`) that should never fire in production. `get_flow_functions()` always registers the correct `_create_flow_trigger_handler()` closure.

## Test coverage
Pre-existing: `tests/test_flow_shared_context.py::test_map_flow_trigger_locks_immediate_start_wording` still passes — it only checks the returned schema, not the handler or executor storage.
Pre-existing: `tests/test_live_flow_parity.py::test_flow_executor_receives_session_factory` still passes — it creates an executor manually and never calls `_map_flow`.
