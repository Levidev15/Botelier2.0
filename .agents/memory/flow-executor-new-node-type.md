---
name: Wiring a new flow_executor NodeType end-to-end
description: Checklist of every dispatch site a new NodeType must touch, why a missing one fails silently, and the atomic-rewrite convention for selection-style nodes.
---

# Wiring a new flow_executor NodeType end-to-end

Adding a NodeType to the enum and to `_ACTION_NODE_TYPES`/`_SIDE_EFFECT_NODE_TYPES` correctly propagates gating (`is_on_required_action_node`, `has_pending_side_effect_downstream`, `_get_reachable_action_node_ids`, etc.) — but that's only ONE of several independent wiring points that must all be updated by hand, in lockstep:

- Backend: the node's function-schema builder must actually be written AND wired into both `get_function_schemas` and `get_all_function_schemas`; it needs entries in `_get_next_node_configured_message`, `_get_current_node_context`, `_get_node_message`, and any hard break-list in `get_initial_messages`'s auto-walk loop; its function-name prefix needs a case in `_dispatch_function_call`; `simulation.py` needs `tool_choice` forcing for the new function name or the simulator LLM narrates instead of calling it (see simulator-api-node-stall.md); `flow_ai.py` needs the type added to `VALID_NODE_TYPES` + `NODE_SCHEMA_TEXT`; `flow_versions.py`'s `validate_flow_config` needs a branch for the type's config shape.
- Frontend: `store.ts` (type union, data shape, default data, `getNodeStyle`), a node component plus its entry in `nodes/index.ts`'s type map, `NodeInspector.tsx` (accent color, label, panel import, `renderNodePanel` case), an inspector panel component, and a `FlowToolbar.tsx` palette entry.

**Why:** None of these are type-checked against each other. A dispatch site (e.g. a schema-builder call site) can reference a per-type builder function that was never actually written, and nothing raises until that exact code path executes — which usually only happens inside a broad `except Exception` during live/simulated schema building, so the failure is silent (tool just missing) rather than a crash. This was only caught because a dedicated test called `get_function_schemas()` end-to-end for the new type; a unit test that calls the per-type handler directly would have passed regardless.

**How to apply:** When adding a new NodeType, find how the most recently added one is threaded through every function listed above (git blame the `NodeType` enum), replicate each site, and write a test that actually calls `get_function_schemas()`/`get_all_function_schemas()` for the new type and asserts the expected function name is present — don't rely solely on tests that invoke the handler directly.

## Atomic rewrite for "selection" nodes

Any node where a caller picks one item from a dynamically-sized list (e.g. an Option Picker) should rewrite its FULL configured set of output variables on every pick — including writing `None`/absent for fields the newly-chosen item doesn't have — rather than only updating fields present on the new item. This makes re-selection (caller changes their mind) safe by construction: no stale field from a previous pick can survive under a different item, and no separate "clear old values" bookkeeping is needed.
