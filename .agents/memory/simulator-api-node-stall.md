---
name: Simulator node stall (forced tool_choice)
description: Why flow nodes stall in the simulator and the correct forced tool_choice pattern for each node type.
---

## Rule
In `_process_with_llm` (simulation.py), the `tool_choice` passed to the LLM must be constrained
based on the current flow node type. With `"auto"`, the LLM may return plain text instead of
calling the required function, stalling the flow until the next user message.

## Forced tool_choice by node type

| Node type        | tool_choice value                                                                 |
|------------------|-----------------------------------------------------------------------------------|
| `API_REQUEST`    | `{"type":"function","function":{"name":"execute_{node_id}"}}` (once per turn)    |
| `COLLECT_SLOT`   | `{"type":"function","function":{"name":"collect_{var_key}"}}` (once per turn)    |
| `COLLECT_FORM`   | `"required"` — LLM must call *one* of the exposed collect_* functions            |
| Everything else  | `"auto"` (or `None` when no tools are available)                                 |

## Why
With `"auto"`, the LLM sees the question/thinking context, returns it as plain text, and the
conversation stalls waiting for the next user turn. The collect_* or execute_* function is never
called. This affects the simulator only — on live calls, Pipecat handles tool enforcement itself.

## How to apply
In `_process_with_llm`, before `openai_client.chat.completions.create(...)` each iteration:

```python
current_node = state.executor.state.get_current_node()
if tools and current_node and current_node.type == NodeType.API_REQUEST and f"execute_{current_node.id}" not in all_functions_called:
    tool_choice = {"type": "function", "function": {"name": f"execute_{current_node.id}"}}
elif tools and current_node and current_node.type == NodeType.COLLECT_SLOT:
    slot = current_node.data.get("slot", {})
    var_key = slot.get("variableKey")
    if var_key and f"collect_{var_key}" not in all_functions_called:
        tool_choice = {"type": "function", "function": {"name": f"collect_{var_key}"}}
    else:
        tool_choice = "auto"
elif tools and current_node and current_node.type == NodeType.COLLECT_FORM:
    tool_choice = "required"
else:
    tool_choice = "auto" if tools else None
```

The `not in all_functions_called` guard ensures forcing applies only on the first call; subsequent
iterations after the function has returned fall back to `"auto"` naturally.

## Companion note
`get_function_schemas()` in `flow_executor.py` only exposes the current/next pending slot
function — so `"required"` on COLLECT_FORM is safe (the only exposed tools are collect_* slots).
