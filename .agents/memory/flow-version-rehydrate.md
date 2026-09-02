---
name: flow_sessions version guard
description: rehydrate_from_snapshot checks flow_version_id; _write_snapshot writes it; function_mapper passes tool.published_version_id.
---

## Rule
`rehydrate_from_snapshot()` compares `saved_version_id` (from `flow_sessions.flow_version_id`) against `self.flow_version_id` (set at executor creation time). If both are non-null and they differ, it returns `False` — the caller starts fresh rather than resuming a node that may not exist in the republished flow.

**NULL on either side → allow rehydrate** (backwards compat for pre-feature snapshots and executors without version info).

## How it flows
1. `function_mapper.get_flow_functions(tool)` passes `flow_version_id=str(tool.published_version_id)` to `FlowExecutor.__init__`.
2. `_snapshot_state` includes `"flow_version_id": self.flow_version_id` in the payload dict.
3. `_write_snapshot` writes `CAST(:flow_version_id AS UUID)` in the INSERT and `flow_version_id = EXCLUDED.flow_version_id` in the ON CONFLICT UPDATE.
4. `rehydrate_from_snapshot` SELECTs 4 columns now: `current_node_id, collected_slots, status, flow_version_id`.

**Why:** If an operator publishes a new flow between a caller's dropout and reconnect, the old snapshot may point to a node that was removed, moved, or renamed. Resuming on that node stalls the conversation silently.

**How to apply:** Any test that mocks the `rehydrate_from_snapshot` DB row must return a 4-tuple (not 3-tuple): `(node_id, slots_dict, status, flow_version_id_or_None)`. Existing mocks that returned 3-tuples need a trailing `None` added.
