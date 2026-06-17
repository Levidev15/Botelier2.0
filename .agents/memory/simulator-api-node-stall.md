---
name: Simulator API node stall
description: Why API_REQUEST nodes stall in the simulator and the correct fix pattern.
---

## Rule
When the current flow node is `NodeType.API_REQUEST`, the simulator's `_process_with_llm`
must force `tool_choice` to `{"type":"function","function":{"name":"execute_{node_id}"}}`.

## Why
With `tool_choice="auto"`, the LLM sees the thinkingMessage in context, returns it as a
plain text response, and the conversation stalls waiting for the next user message.
The execute_ function is never called.

## How to apply
In `botelier/backend/botelier/api/simulation.py` → `_process_with_llm`, before the
`openai_client.chat.completions.create(...)` call each iteration:

```python
current_node = state.executor.state.get_current_node()
if (
    tools
    and current_node
    and current_node.type == NodeType.API_REQUEST
    and f"execute_{current_node.id}" not in all_functions_called
):
    tool_choice = {"type": "function", "function": {"name": f"execute_{current_node.id}"}}
else:
    tool_choice = "auto" if tools else None
```

The guard `not in all_functions_called` ensures we only force the call once; subsequent
iterations after the API has returned use `"auto"` again.

## Companion fix
`_get_current_node_context` in `flow_executor.py` must also have a `NodeType.API_REQUEST`
case that surfaces the thinkingMessage, responseInstructions, and node instructions so
the LLM knows what to say and do with the result.
