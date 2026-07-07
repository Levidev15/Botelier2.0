---
name: Flow function gating vs. live/simulator tool sync
description: get_function_schemas() feeds BOTH live voice and simulator; changing its exposure requires paired refresh in function_mapper AND per-iteration rebuild in simulation, or calls hang / hit OpenAI 400.
---

# Flow function gating must stay in lockstep across three surfaces

`FlowExecutor.get_function_schemas()` is the single source of the LLM's
*callable* tool set for **both** the live voice path and the flow-editor
simulator. `get_all_function_schemas()` is a **separate, intentionally ungated**
list used only to register handlers (so a stale/hidden name never 500s). Gate the
former, never the latter.

**Rule:** any change to what `get_function_schemas()` exposes (e.g. gating action
functions — end_call/transfer/execute/set_var/confirm/save_record — to the
reachable flow node) MUST be paired with:

1. **Live path** (`voice/function_mapper._create_flow_function_handler`): refresh
   the exposed tools on **any node advance**, not just slot collection. Action
   nodes advance `current_node_id` WITHOUT returning `result["collected"]`, so a
   `collected`-only refresh strands the call on a stale tool list (e.g. after a
   set_variable advances to an api node, `execute_<api>` is never exposed → hang).
   Capture `_prev_node_id` before the call; refresh when
   `action not in (transfer,end)` and `current_node_id != _prev_node_id`.
   transfer/end return before `result_callback`, so skip them.
2. **Simulator** (`api/simulation._process_with_llm`): rebuild
   `function_schemas`/`tools` at the top of **every** loop iteration, and only
   force a `tool_choice` whose name is in the freshly-built set. Building tools
   once before the loop and then forcing the *advanced* node's function →
   OpenAI 400, historically swallowed by a catch-all into a generic apology.

**Why:** the gating BFS mirrors `_find_next_reachable_collect_slot` (INITIAL/
MESSAGE/CONDITION and satisfied collects are transparent; unsatisfied collects
and action nodes are gates; sitting on an action node exposes only itself). All
three surfaces must reflect the same flow position or they diverge into
premature hang-ups (live) or hidden 400s (simulator).

**Gotcha:** `NodeType.CONDITION` is never evaluated at runtime anywhere — it only
exists in the enum. Treating it as transparent (exposing action gates on both
branches) is the only viable choice today. Flag runtime condition evaluation for
the flow-audit work.

**Simulator error surfacing:** the catch-all now returns exception class + first
message line via an optional `error` field on `SimulateMessageResponse` (gated by
`tools.view`); full traceback goes to server logs only. Never surface tracebacks
or request headers — integration API headers carry credentials.
