---
name: Flow terminal-node & fallback-confirmation behavior
description: Why flows loop or never end — confirm_details gating, choice enums from slot.validation, END-node forcing, tools.account_id NULL
---

## Choice slot enums live on the node, not the variable
The flow editor stores choice options at `slot.validation.choices` on the collecting node; the flow-level variables array (`var.choices`) is usually empty. The slot-function builder must fall back to the node's validation choices or the LLM sees a free-text parameter and never constrains answers like yes/no.

## confirm_details fallback must be gated
The built-in `confirm_details` (flows WITHOUT a CONFIRMATION node) must only be exposed when all required variables are collected, the current node is not an action/END node, and no successful confirmation has happened yet (executor-level flag). Ungated, the LLM calls it after "no thank you" and the no-op handler ("Great, confirmed." without advancing state) loops the bot back into re-summarizing. `get_all_function_schemas` (handler registration) keeps it unconditionally; only the exposure path (`get_function_schemas`) gates.

## END nodes need an explicit "call the function" instruction
The current-node context for END nodes must instruct the model to CALL `end_call_<node_id>` — merely quoting the goodbye text makes the LLM speak it as plain text and the call/session never ends (voice, SMS, and simulator all share this prompt path). The simulator additionally forces `tool_choice` for END nodes, same pattern as API_REQUEST (live voice never forces tool_choice).

## tools.account_id is NULL for most tools
Tools are tenant-scoped through `ToolSet.account_id`; the tool-create endpoint never stamps `tools.account_id`. Anything needing the tool's account (e.g. simulator FlowExecutor for SAVE_RECORD) must resolve through the ToolSet when the direct column is NULL.

**Why:** all three user-reported bugs (record-not-saved, "no thank you" loop, calls never hanging up) traced to these gaps.

## Test-harness gotcha
`parse_flow_config` reads `initial_node` (snake_case). Omitting it leaves `current_node_id=None` and no flow functions are ever exposed — a scripted sim silently degenerates into free chat.
