"""Regression tests for the 'decline loses the record' bug.

Root cause: while sitting on the final collect node ("anything else?") the LLM
called the global end_call directly on a "No" answer — SAVE_RECORD was never
reached and the record was silently lost.

The existing is_on_required_action_node() gate only blocks end_call when the
flow is ON an action node; it returned False on collect nodes even when SAVE_RECORD
was pending downstream.

Fix: has_pending_side_effect_downstream() performs a BFS that passes THROUGH
unsatisfied collect nodes and returns True if any side-effect node
(SAVE_RECORD / API_REQUEST / CAPABILITY / CONFIRMATION / SET_VARIABLE) is
reachable.  function_mapper.py ORs the two checks; simulation.py applies the
same filter.

All tests are unit-only: no DB, no OpenAI, no network access.
"""

import pytest

from botelier.flow_executor import FlowExecutor, NodeType, _SIDE_EFFECT_NODE_TYPES, parse_flow_config


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fn_names(schemas):
    return {s.get("function", s)["name"] for s in schemas}


def _collect_then_save_flow():
    """start → ask_anything_else (collect_slot) → save_record → end.

    Exact topology of the failing production flow: a final collect node
    with SAVE_RECORD immediately downstream.
    """
    config = {
        "initial_node": "start",
        "variables": [
            {"key": "anything_else", "type": "text", "description": "Anything else?"},
        ],
        "nodes": [
            {"id": "start", "type": "initial", "data": {}},
            {"id": "ask", "type": "collect_slot",
             "data": {"slot": {"variableKey": "anything_else",
                               "prompt": "Is there anything else I can help with?"}}},
            {"id": "save", "type": "save_record",
             "data": {"saveRecord": {"recordTypeId": "abc123",
                                     "recordTypeName": "Housekeeping Request",
                                     "fieldMappings": []}}},
            {"id": "end", "type": "end", "data": {}},
        ],
        "edges": [
            {"id": "e1", "source": "start", "target": "ask"},
            {"id": "e2", "source": "ask", "target": "save"},
            {"id": "e3", "source": "save", "target": "end"},
        ],
    }
    return FlowExecutor(parse_flow_config(config))


def _multi_collect_then_save_flow():
    """start → c_a (collect_slot) → c_b (collect_slot) → save_record → end.

    Two unsatisfied collect nodes separate the current position from SAVE_RECORD.
    The BFS must traverse through both.
    """
    config = {
        "initial_node": "start",
        "variables": [
            {"key": "a", "type": "text", "description": "A"},
            {"key": "b", "type": "text", "description": "B"},
        ],
        "nodes": [
            {"id": "start", "type": "initial", "data": {}},
            {"id": "c_a", "type": "collect_slot",
             "data": {"slot": {"variableKey": "a", "prompt": "A?"}}},
            {"id": "c_b", "type": "collect_slot",
             "data": {"slot": {"variableKey": "b", "prompt": "B?"}}},
            {"id": "save", "type": "save_record",
             "data": {"saveRecord": {"recordTypeId": "xyz", "fieldMappings": []}}},
            {"id": "end", "type": "end", "data": {}},
        ],
        "edges": [
            {"id": "e1", "source": "start", "target": "c_a"},
            {"id": "e2", "source": "c_a", "target": "c_b"},
            {"id": "e3", "source": "c_b", "target": "save"},
            {"id": "e4", "source": "save", "target": "end"},
        ],
    }
    return FlowExecutor(parse_flow_config(config))


def _pure_qa_flow():
    """start → collect_q → end.  No side-effect nodes at all."""
    config = {
        "initial_node": "start",
        "variables": [{"key": "q", "type": "text", "description": "Q"}],
        "nodes": [
            {"id": "start", "type": "initial", "data": {}},
            {"id": "collect_q", "type": "collect_slot",
             "data": {"slot": {"variableKey": "q", "prompt": "Q?"}}},
            {"id": "end", "type": "end", "data": {}},
        ],
        "edges": [
            {"id": "e1", "source": "start", "target": "collect_q"},
            {"id": "e2", "source": "collect_q", "target": "end"},
        ],
    }
    return FlowExecutor(parse_flow_config(config))


# ---------------------------------------------------------------------------
# _SIDE_EFFECT_NODE_TYPES invariants
# ---------------------------------------------------------------------------

def test_side_effect_types_do_not_include_end_or_transfer():
    """END and TRANSFER must never be in the side-effect set."""
    assert NodeType.END not in _SIDE_EFFECT_NODE_TYPES
    assert NodeType.TRANSFER not in _SIDE_EFFECT_NODE_TYPES


def test_side_effect_types_include_all_mutating_nodes():
    """All five data-mutating node types must be present."""
    assert NodeType.SAVE_RECORD in _SIDE_EFFECT_NODE_TYPES
    assert NodeType.API_REQUEST in _SIDE_EFFECT_NODE_TYPES
    assert NodeType.CAPABILITY in _SIDE_EFFECT_NODE_TYPES
    assert NodeType.CONFIRMATION in _SIDE_EFFECT_NODE_TYPES
    assert NodeType.SET_VARIABLE in _SIDE_EFFECT_NODE_TYPES


# ---------------------------------------------------------------------------
# has_pending_side_effect_downstream — core behaviour
# ---------------------------------------------------------------------------

def test_pending_side_effect_true_on_collect_before_save_record():
    """The exact failing scenario: collect node with SAVE_RECORD downstream."""
    ex = _collect_then_save_flow()
    ex.state.current_node_id = "ask"

    # is_on_required_action_node is False — this is why the old gate missed it.
    assert ex.is_on_required_action_node() is False
    # The new check catches the downstream SAVE_RECORD.
    assert ex.has_pending_side_effect_downstream() is True


def test_pending_side_effect_true_traverses_multiple_collect_nodes():
    """BFS passes through multiple unsatisfied collect nodes to find SAVE_RECORD."""
    ex = _multi_collect_then_save_flow()
    ex.state.current_node_id = "c_a"
    assert ex.has_pending_side_effect_downstream() is True


def test_pending_side_effect_true_sitting_directly_on_save_record():
    """True when the current node IS a side-effect node."""
    ex = _collect_then_save_flow()
    ex.state.collected_slots["anything_else"] = "No"
    ex.state.current_node_id = "save"

    assert ex.has_pending_side_effect_downstream() is True
    # is_on_required_action_node is also True here (independent gate).
    assert ex.is_on_required_action_node() is True


def test_pending_side_effect_false_after_save_record_fires():
    """False once the flow has advanced past SAVE_RECORD to the END node."""
    ex = _collect_then_save_flow()
    ex.state.collected_slots["anything_else"] = "No"
    ex.state.current_node_id = "end"

    # On END: is_on_required_action_node True (END is an action node),
    # but has_pending_side_effect_downstream False (END is not a side-effect).
    assert ex.is_on_required_action_node() is True
    assert ex.has_pending_side_effect_downstream() is False


def test_pending_side_effect_false_in_pure_qa_flow():
    """False in a flow that contains no side-effect nodes at all."""
    ex = _pure_qa_flow()
    ex.state.current_node_id = "collect_q"

    assert ex.has_pending_side_effect_downstream() is False


def test_pending_side_effect_false_on_initial_node_no_side_effects():
    """False at the initial node of a pure Q&A flow."""
    ex = _pure_qa_flow()
    # current_node_id defaults to initial node ("start")
    assert ex.has_pending_side_effect_downstream() is False


def test_pending_side_effect_covers_all_side_effect_node_types():
    """Every node type in _SIDE_EFFECT_NODE_TYPES triggers a True result."""
    for node_type in _SIDE_EFFECT_NODE_TYPES:
        config = {
            "initial_node": "collect",
            "variables": [{"key": "v", "type": "text", "description": "V"}],
            "nodes": [
                {"id": "collect", "type": "collect_slot",
                 "data": {"slot": {"variableKey": "v", "prompt": "V?"}}},
                {"id": "action", "type": node_type.value,
                 "data": {"saveRecord": {}, "setVariable": {}, "api": {},
                          "confirmation": {}}},
                {"id": "end", "type": "end", "data": {}},
            ],
            "edges": [
                {"id": "e1", "source": "collect", "target": "action"},
                {"id": "e2", "source": "action", "target": "end"},
            ],
        }
        ex = FlowExecutor(parse_flow_config(config))
        ex.state.current_node_id = "collect"
        assert ex.has_pending_side_effect_downstream() is True, (
            f"Expected True for downstream {node_type}"
        )


# ---------------------------------------------------------------------------
# Combined gate: is_on_required_action_node OR has_pending_side_effect_downstream
# ---------------------------------------------------------------------------

def test_combined_gate_blocks_end_call_on_collect_before_save():
    """The combined gate is True at the collect node — end_call must be blocked."""
    ex = _collect_then_save_flow()
    ex.state.current_node_id = "ask"

    gate = ex.is_on_required_action_node() or ex.has_pending_side_effect_downstream()
    assert gate is True


def test_combined_gate_false_in_pure_qa_flow():
    """The combined gate is False in a pure Q&A flow — end_call must stay available."""
    ex = _pure_qa_flow()
    ex.state.current_node_id = "collect_q"

    gate = ex.is_on_required_action_node() or ex.has_pending_side_effect_downstream()
    assert gate is False


# ---------------------------------------------------------------------------
# Collect-node "decline is an answer" directive in _get_current_node_context
# ---------------------------------------------------------------------------

def test_collect_slot_context_includes_decline_directive():
    """COLLECT_SLOT context tells the LLM that a 'No' is a valid answer."""
    ex = _collect_then_save_flow()
    ex.state.current_node_id = "ask"
    ctx = ex._get_current_node_context()

    assert ctx is not None
    ctx_lower = ctx.lower()
    # The directive must mention recording the answer via the collect function,
    # not calling end_call — we check key concepts, not exact wording.
    assert "no" in ctx_lower or "declining" in ctx_lower
    assert "collect" in ctx_lower
    assert "end_call" in ctx_lower


def test_collect_form_context_includes_decline_directive():
    """COLLECT_FORM context also carries the decline-is-an-answer directive."""
    config = {
        "initial_node": "start",
        "variables": [
            {"key": "item", "type": "text", "description": "Item"},
        ],
        "nodes": [
            {"id": "start", "type": "initial", "data": {}},
            {"id": "form", "type": "collect_form",
             "data": {
                 "introMessage": "Let me get a few details.",
                 "slots": [{"variableKey": "item", "prompt": "Item?", "order": 0}],
             }},
            {"id": "end", "type": "end", "data": {}},
        ],
        "edges": [
            {"id": "e1", "source": "start", "target": "form"},
            {"id": "e2", "source": "form", "target": "end"},
        ],
    }
    ex = FlowExecutor(parse_flow_config(config))
    ex.state.current_node_id = "form"
    ctx = ex._get_current_node_context()

    assert ctx is not None
    ctx_lower = ctx.lower()
    assert "collect" in ctx_lower
    assert "end_call" in ctx_lower


# ---------------------------------------------------------------------------
# SAVE_RECORD node directive in _get_current_node_context
# ---------------------------------------------------------------------------

def test_save_record_context_explicit_call_now_directive():
    """SAVE_RECORD context contains an explicit 'call NOW' instruction with fn name."""
    ex = _collect_then_save_flow()
    ex.state.collected_slots["anything_else"] = "No"
    ex.state.current_node_id = "save"
    ctx = ex._get_current_node_context()

    assert ctx is not None
    # Must name the specific function the LLM should call.
    assert "save_record_save" in ctx
    # Must instruct the LLM to call it NOW, not after saying goodbye.
    assert "NOW" in ctx


def test_save_record_context_includes_record_type_name():
    """SAVE_RECORD context includes the configured record type name."""
    ex = _collect_then_save_flow()
    ex.state.collected_slots["anything_else"] = "No"
    ex.state.current_node_id = "save"
    ctx = ex._get_current_node_context()

    assert ctx is not None
    assert "Housekeeping Request" in ctx


def test_save_record_context_warns_against_ending_first():
    """SAVE_RECORD context explicitly warns not to end the call before calling."""
    ex = _collect_then_save_flow()
    ex.state.collected_slots["anything_else"] = "No"
    ex.state.current_node_id = "save"
    ctx = ex._get_current_node_context()

    assert ctx is not None
    ctx_lower = ctx.lower()
    # Should warn that ending before saving will lose the record.
    assert "end" in ctx_lower or "goodbye" in ctx_lower


# ---------------------------------------------------------------------------
# Existing is_on_required_action_node() tests still pass (no regression)
# ---------------------------------------------------------------------------

def _save_record_flow():
    """start → collect_name → collect_room → save_record → end."""
    config = {
        "initial_node": "start",
        "variables": [
            {"key": "name", "type": "text", "description": "Guest name"},
            {"key": "room", "type": "text", "description": "Room number"},
        ],
        "nodes": [
            {"id": "start", "type": "initial", "data": {}},
            {"id": "collect_name", "type": "collect_slot",
             "data": {"slot": {"variableKey": "name", "prompt": "Name?"}}},
            {"id": "collect_room", "type": "collect_slot",
             "data": {"slot": {"variableKey": "room", "prompt": "Room?"}}},
            {"id": "save", "type": "save_record",
             "data": {"saveRecord": {"recordTypeId": "abc123", "fieldMappings": []}}},
            {"id": "end", "type": "end", "data": {}},
        ],
        "edges": [
            {"id": "e1", "source": "start", "target": "collect_name"},
            {"id": "e2", "source": "collect_name", "target": "collect_room"},
            {"id": "e3", "source": "collect_room", "target": "save"},
            {"id": "e4", "source": "save", "target": "end"},
        ],
    }
    return FlowExecutor(parse_flow_config(config))


def test_regression_is_on_required_action_false_during_collection():
    """is_on_required_action_node() still returns False while collecting slots."""
    ex = _save_record_flow()

    assert ex.is_on_required_action_node() is False

    ex.state.current_node_id = "collect_name"
    assert ex.is_on_required_action_node() is False

    ex.state.collected_slots["name"] = "Corey"
    ex.state.current_node_id = "collect_room"
    assert ex.is_on_required_action_node() is False


def test_regression_is_on_required_action_true_on_save_record():
    """is_on_required_action_node() still returns True when sitting on SAVE_RECORD."""
    ex = _save_record_flow()
    ex.state.collected_slots.update({"name": "Corey", "room": "2302"})
    ex.state.current_node_id = "save"

    assert ex.is_on_required_action_node() is True
    names = _fn_names(ex.get_function_schemas())
    assert "save_record_save" in names
    assert "end_call_end" not in names


def test_regression_pending_side_effect_true_during_earlier_collection():
    """has_pending_side_effect_downstream() True even from the first collect node."""
    ex = _save_record_flow()
    # On the first collect node — SAVE_RECORD is two nodes away through
    # an unsatisfied collect node.
    ex.state.current_node_id = "collect_name"
    assert ex.has_pending_side_effect_downstream() is True

    # After first slot collected, still on second collect node.
    ex.state.collected_slots["name"] = "Corey"
    ex.state.current_node_id = "collect_room"
    assert ex.has_pending_side_effect_downstream() is True


# ---------------------------------------------------------------------------
# Simulator parity: end_call_<node_id> must NOT be stripped at END node
# ---------------------------------------------------------------------------
# The simulator filter in _process_with_llm uses ONLY has_pending_side_effect_
# downstream() — NOT is_on_required_action_node().  This section verifies the
# exact guard that prevents the regression:
#   • END is in _ACTION_NODE_TYPES → is_on_required_action_node() is True there
#   • But END is NOT in _SIDE_EFFECT_NODE_TYPES → has_pending_side_effect_downstream()
#     is False → the simulator filter does NOT fire → end_call_<id> stays.
# ---------------------------------------------------------------------------

def test_simulator_gate_does_not_fire_on_end_node():
    """has_pending_side_effect_downstream() is False on END node.

    This is the critical invariant: the simulator only gates on this method,
    not on is_on_required_action_node().  At END node, the flow's own
    end_call_<id> must survive so the simulated session can terminate.
    """
    ex = _collect_then_save_flow()
    ex.state.collected_slots["anything_else"] = "No"
    # Simulate: SAVE_RECORD fired, flow advanced to END.
    ex.state.current_node_id = "end"

    # This is what the simulator uses as its filter condition.
    sim_gate = ex.has_pending_side_effect_downstream()
    assert sim_gate is False, (
        "Simulator gate must be False at END node so end_call_<id> is not stripped"
    )

    # Confirm is_on_required_action_node() is True at END node, showing why
    # we cannot OR it into the simulator condition.
    assert ex.is_on_required_action_node() is True


def test_simulator_gate_fires_on_collect_before_save_record():
    """Simulator gate True on collect node → end_call_* would be stripped."""
    ex = _collect_then_save_flow()
    ex.state.current_node_id = "ask"

    assert ex.has_pending_side_effect_downstream() is True
    # Confirm end_call_end is NOT in the flow schemas at this position
    # (get_reachable_action_node_ids stops at uncollected current node).
    names = _fn_names(ex.get_function_schemas())
    assert "end_call_end" not in names


def test_end_call_node_id_present_in_schemas_at_end_node():
    """At the END node, end_call_<node_id> appears in flow schemas.

    This is the tool the simulator needs to terminate; stripping it would
    leave the simulated session with no termination path.
    """
    ex = _collect_then_save_flow()
    ex.state.collected_slots["anything_else"] = "No"
    ex.state.current_node_id = "end"

    names = _fn_names(ex.get_function_schemas())
    assert "end_call_end" in names
    # has_pending_side_effect_downstream() is False here, so the simulator
    # filter would NOT strip it.
    assert ex.has_pending_side_effect_downstream() is False


def test_simulator_gate_fires_on_save_record_node_strips_end_call():
    """Sitting on SAVE_RECORD: gate fires; end_call_* correctly stripped.

    At SAVE_RECORD the flow schemas don't include end_call_end anyway
    (action node gating stops downstream exposure), so this is defense-in-depth.
    """
    ex = _collect_then_save_flow()
    ex.state.collected_slots["anything_else"] = "No"
    ex.state.current_node_id = "save"

    assert ex.has_pending_side_effect_downstream() is True
    # Flow schemas at SAVE_RECORD node: only save_record_save exposed.
    names = _fn_names(ex.get_function_schemas())
    assert "save_record_save" in names
    assert "end_call_end" not in names
