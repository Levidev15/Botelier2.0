---
name: Simulator↔live parity
description: What the flow simulator must mirror from a real call — model, tool_choice, KB/escalation, and account-scoped assistant resolution.
---

# Simulator↔live parity

The flow simulator (`botelier/backend/botelier/api/simulation.py`) is a preview of a
real voice/SMS call. If it diverges from live, users tune a flow that then behaves
differently in production. Keep these in lockstep with the live path
(`voice/call_handler.py`, `voice/function_mapper.py`, `flow_executor.py`).

## Model must match the assistant, never a hardcoded stronger model
Run the **resolved assistant's `llm_model`** per session (stored on
`SimulationState.model`), falling back to `DEFAULT_SIM_MODEL="gpt-4o-mini"` (the
new-assistant default) only when no assistant resolves. Live uses
`config.llm_model` (from `assistant.llm_model`).

**Why:** A previous version hardcoded `gpt-4o` "so the mid-flow KB demo works."
But production default is `gpt-4o-mini`, so the preview looked *better* than the
real call and hid production behavior — a parity bug. An honest preview on the
mini model is correct; if a user wants stronger mid-flow answers they upgrade the
assistant model, which also improves live.

**How to apply:** Do not bump the sim model to make a demo look good. If mid-flow
KB answers are weak, that is real; fix it via the KB prompt block or by the user
choosing a stronger `llm_model` (which changes both sim and live together).

## tool_choice parity by node type
COLLECT_SLOT / COLLECT_FORM nodes must **not** force `tool_choice` (live never
does). API_REQUEST nodes **do** force it (see `simulator-api-node-stall.md`) —
without forcing, the LLM returns text and the API node stalls.

## Account-scoped assistant resolution (fail closed)
`_resolve_flow_assistant` injects the backing assistant's KB block + escalation
number. Explicit `assistant_id` is permission-checked and bound to
`tool.account_id`. The fallback-by-`tool_set_id` query **must also filter
`Assistant.account_id == tool.account_id`** and return `None` when the tool has no
account.

**Why:** `tool_set_id` ownership is **not** validated on assistant create/update
(`api/assistants.py` assigns `tool_set_id` raw), so a foreign-tenant assistant can
reference this tool's `tool_set`. An unscoped fallback would leak another tenant's
KB content, escalation number, and model into this tenant's simulation.

**How to apply:** Any assistant lookup keyed by `tool_set_id` (not just the
simulator) must also scope by `account_id` until tool_set ownership is validated.
