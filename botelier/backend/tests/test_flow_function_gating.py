"""Regression tests for flow-order gating of LLM function schemas.

These cover the two production bugs fixed together:

* BUG 1 — ``get_function_schemas()`` exposed *every* action function
  (end_call_*, transfer_*, execute_*, set_var_*, confirm_*, save_record_*) on
  every turn, so the LLM could end/branch a call mid-collection (premature
  hang-up). Action functions must now be gated to the reachable flow position,
  exactly like slot functions.

* BUG 2 — the simulator built its tool list once and then, after the flow
  advanced, force-selected a ``tool_choice`` that was no longer in that stale
  list (OpenAI 400, swallowed into a generic apology). The contract asserted
  here is the invariant the fix relies on: whatever function the simulator
  would force at a given node is always present in the *freshly rebuilt*
  ``get_function_schemas()`` for that same node.

No OpenAI or DB access — the flow position is advanced by setting the two state
fields (``current_node_id`` / ``collected_slots``) that the real handlers write.
"""

from botelier.flow_executor import FlowExecutor, NodeType, parse_flow_config


def _fn_names(schemas):
    return {s.get("function", s)["name"] for s in schemas}


def _linear_flow():
    """start → collect_a → collect_b → sync(set_var) → api → confirm → end."""
    config = {
        "initial_node": "start",
        "variables": [
            {"key": "a", "type": "text", "description": "A"},
            {"key": "b", "type": "text", "description": "B"},
        ],
        "nodes": [
            {"id": "start", "type": "initial", "data": {}},
            {"id": "collect_a", "type": "collect_slot",
             "data": {"slot": {"variableKey": "a", "prompt": "A?"}}},
            {"id": "collect_b", "type": "collect_slot",
             "data": {"slot": {"variableKey": "b", "prompt": "B?"}}},
            {"id": "sync", "type": "set_variable",
             "data": {"setVariable": {"variableKey": "synced", "value": "x"}}},
            {"id": "api", "type": "api_request",
             "data": {"name": "Do API", "api": {"thinkingMessage": ""}}},
            {"id": "confirm", "type": "confirmation",
             "data": {"confirmation": {"variablesToConfirm": ["a", "b"]}}},
            {"id": "end", "type": "end", "data": {}},
        ],
        "edges": [
            {"id": "e1", "source": "start", "target": "collect_a"},
            {"id": "e2", "source": "collect_a", "target": "collect_b"},
            {"id": "e3", "source": "collect_b", "target": "sync"},
            {"id": "e4", "source": "sync", "target": "api"},
            {"id": "e5", "source": "api", "target": "confirm"},
            {"id": "e6", "source": "confirm", "target": "end"},
        ],
    }
    return FlowExecutor(parse_flow_config(config))


# Every action function that exists in the linear flow.
_ALL_ACTION_FNS = {"set_var_sync", "execute_api", "confirm_confirm", "end_call_end"}


def test_bug1_no_action_functions_exposed_at_start():
    """At the start, only the first slot is offered — no action functions."""
    ex = _linear_flow()
    names = _fn_names(ex.get_function_schemas())

    assert names == {"collect_a"}
    # The premature-hangup root cause: end/transfer/api/etc. must NOT be callable.
    assert not (_ALL_ACTION_FNS & names)
    assert ex._get_reachable_action_node_ids() == set()


def test_bug1_no_action_functions_while_collecting_second_slot():
    """After the first slot, still collecting — action functions stay hidden."""
    ex = _linear_flow()
    ex.state.collected_slots["a"] = "yes"
    ex.state.current_node_id = "collect_b"

    names = _fn_names(ex.get_function_schemas())
    assert names == {"collect_b"}
    assert not (_ALL_ACTION_FNS & names)
    assert ex._get_reachable_action_node_ids() == set()


def test_action_functions_exposed_one_at_a_time_in_order():
    """Once collection is done, each action node is exposed only when current."""
    ex = _linear_flow()
    ex.state.collected_slots.update({"a": "yes", "b": "no"})

    # Sitting on the set_variable node → only its function, nothing downstream.
    ex.state.current_node_id = "sync"
    names = _fn_names(ex.get_function_schemas())
    assert "set_var_sync" in names
    assert not ({"execute_api", "confirm_confirm", "end_call_end"} & names)
    assert ex._get_reachable_action_node_ids() == {"sync"}

    # Advance to the API node.
    ex.state.current_node_id = "api"
    names = _fn_names(ex.get_function_schemas())
    assert "execute_api" in names
    assert not ({"set_var_sync", "confirm_confirm", "end_call_end"} & names)
    assert ex._get_reachable_action_node_ids() == {"api"}

    # Advance to the confirmation node.
    ex.state.current_node_id = "confirm"
    names = _fn_names(ex.get_function_schemas())
    assert "confirm_confirm" in names
    assert "end_call_end" not in names
    assert ex._get_reachable_action_node_ids() == {"confirm"}

    # Finally the end node — now, and only now, end_call is offered.
    ex.state.current_node_id = "end"
    names = _fn_names(ex.get_function_schemas())
    assert "end_call_end" in names
    assert ex._get_reachable_action_node_ids() == {"end"}


def test_transparent_nodes_are_traversed_to_next_action_gate():
    """INITIAL / MESSAGE nodes are transparent; the next action gate is reachable."""
    config = {
        "initial_node": "start",
        "variables": [],
        "nodes": [
            {"id": "start", "type": "initial", "data": {}},
            {"id": "msg", "type": "message", "data": {"message": "hi"}},
            {"id": "end", "type": "end", "data": {}},
        ],
        "edges": [
            {"id": "e1", "source": "start", "target": "msg"},
            {"id": "e2", "source": "msg", "target": "end"},
        ],
    }
    ex = FlowExecutor(parse_flow_config(config))
    # No collect gate in between, so the end node is reachable from the start.
    assert ex._get_reachable_action_node_ids() == {"end"}
    assert "end_call_end" in _fn_names(ex.get_function_schemas())


def test_bug2_forced_tool_choice_always_present_in_fresh_schemas():
    """The function the simulator would force is always in the fresh schema list.

    This is the invariant the simulator fix depends on: because tools are rebuilt
    each loop iteration from ``get_function_schemas()``, a forced ``tool_choice``
    can never name a function absent from the tool list (the OpenAI-400 cause).
    """
    ex = _linear_flow()

    def forced_name_for_current():
        node = ex.state.get_current_node()
        if node and node.type == NodeType.API_REQUEST:
            return f"execute_{node.id}"
        if node and node.type == NodeType.COLLECT_SLOT:
            var_key = node.data.get("slot", {}).get("variableKey")
            if var_key and var_key not in ex.state.collected_slots:
                return f"collect_{var_key}"
        return None

    # Collecting slot a.
    ex.state.current_node_id = "collect_a"
    forced = forced_name_for_current()
    assert forced == "collect_a"
    assert forced in _fn_names(ex.get_function_schemas())

    # Advance to slot b (the exact stale-list scenario that produced the 400).
    ex.state.collected_slots["a"] = "yes"
    ex.state.current_node_id = "collect_b"
    forced = forced_name_for_current()
    assert forced == "collect_b"
    assert forced in _fn_names(ex.get_function_schemas())

    # Advance to the API node — forced execute_api must be present too.
    ex.state.collected_slots["b"] = "no"
    ex.state.current_node_id = "api"
    forced = forced_name_for_current()
    assert forced == "execute_api"
    assert forced in _fn_names(ex.get_function_schemas())


def _capability_flow():
    """start → collect_a → capability → end.

    A CAPABILITY node is an action node aliased to API_REQUEST: it emits an
    ``execute_<id>`` function and is gated to the reachable flow position exactly
    like an api_request node.
    """
    config = {
        "initial_node": "start",
        "variables": [
            {"key": "a", "type": "text", "description": "A"},
        ],
        "nodes": [
            {"id": "start", "type": "initial", "data": {}},
            {"id": "collect_a", "type": "collect_slot",
             "data": {"slot": {"variableKey": "a", "prompt": "A?"}}},
            {"id": "cap", "type": "capability",
             "data": {"name": "Search",
                      "api": {"apiSource": "capability",
                              "capability": "search_availability"}}},
            {"id": "end", "type": "end", "data": {}},
        ],
        "edges": [
            {"id": "e1", "source": "start", "target": "collect_a"},
            {"id": "e2", "source": "collect_a", "target": "cap"},
            {"id": "e3", "source": "cap", "target": "end"},
        ],
    }
    return FlowExecutor(parse_flow_config(config))


def test_capability_node_gated_like_api_request():
    """A capability node is hidden while collecting and exposed only when current.

    (``confirm_details`` is an always-on built-in appended whenever the flow has
    no confirmation node, so we assert the specific gating property rather than
    exact set equality.)
    """
    ex = _capability_flow()

    # At the start, only the first slot is offered — the capability is hidden.
    names = _fn_names(ex.get_function_schemas())
    assert "collect_a" in names
    assert "execute_cap" not in names
    assert "end_call_end" not in names
    assert ex._get_reachable_action_node_ids() == set()

    # Once the slot is collected and we sit on the capability node, it's exposed
    # as execute_<id> — and nothing downstream (end) leaks.
    ex.state.collected_slots["a"] = "yes"
    ex.state.current_node_id = "cap"
    names = _fn_names(ex.get_function_schemas())
    assert "execute_cap" in names
    assert "end_call_end" not in names
    assert ex._get_reachable_action_node_ids() == {"cap"}


def test_capability_node_is_action_node_type():
    """CAPABILITY resolves to a real NodeType and counts as an action node."""
    ex = _capability_flow()
    ex.state.current_node_id = "cap"
    node = ex.state.get_current_node()
    assert node is not None
    assert node.type == NodeType.CAPABILITY
    # Parity with the simulator's forced-tool-choice rule: a capability node,
    # like API_REQUEST, forces execute_<id>, which must be in the fresh schemas.
    ex.state.collected_slots["a"] = "yes"
    forced = f"execute_{node.id}"
    assert forced in _fn_names(ex.get_function_schemas())
