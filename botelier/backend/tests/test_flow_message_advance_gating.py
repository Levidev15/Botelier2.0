"""Regression tests for Task #600 — booking flow dead-end fakes a completed
reservation.

Root cause: MESSAGE nodes expose no LLM-callable function of their own. As
long as a COLLECT_SLOT/COLLECT_FORM or action node (SAVE_RECORD, API_REQUEST,
CONFIRMATION, END, TRANSFER, ...) is reachable ahead, that is harmless — the
LLM has something concrete to call once it is done delivering the message,
and calling it implicitly carries the flow state forward.

But a MESSAGE node (or a chain of them) that leads only to more MESSAGE nodes
and nothing the engine can expose leaves the LLM with *no* flow tool to call.
Nothing then ever advances ``current_node_id`` past that point, so the model
is free to improvise — including narrating a fabricated outcome ("your
booking is confirmed") before falling back to the global end_call. This
exactly matches the production incident: a "which room?" MESSAGE node fed
into a dead-end "flow disabled" MESSAGE node with no collect/action node in
between, the LLM invented its own booking questions, then hung up implying a
reservation existed, and ``flow_sessions`` never left ``active`` (it was
later stamped ``abandoned`` by call teardown) despite the caller having been
told the process succeeded.

Fix: a "stuck" waiting MESSAGE node (see
``_get_pending_message_advance_node``) gets an explicit ``continue_flow_<id>``
function, and ``is_on_required_action_node()`` blocks the global end_call
while such a node is pending — mirroring the existing SAVE_RECORD /
API_REQUEST action-node gating pattern (Task #420/#296 lineage) rather than
relying on prompt wording alone.

All tests are unit-only: no DB, no OpenAI, no network access.
"""

import asyncio

from botelier.flow_executor import FlowExecutor, NodeType, parse_flow_config


def _fn_names(schemas):
    return {s.get("function", s)["name"] for s in schemas}


def _dead_end_message_chain_flow():
    """start → ask_room (message, waitForResponse) → disabled (message, dead end).

    Exact topology of the failing production flow (new_booking): after a
    room-selection prompt, the only configured next step is a MESSAGE node
    with no outgoing edge and nothing else reachable — no collect node, no
    action node, no END/TRANSFER.
    """
    config = {
        "initial_node": "start",
        "variables": [],
        "nodes": [
            {"id": "start", "type": "initial", "data": {}},
            {"id": "ask_room", "type": "message",
             "data": {"message": "Which room would you like to book?",
                      "deliveryMode": "static", "waitForResponse": True}},
            {"id": "disabled", "type": "message",
             "data": {"message": "This is the end of the booking flow as the "
                                  "admin disabled the rest of the flow until "
                                  "further notice.",
                      "deliveryMode": "static", "waitForResponse": True}},
        ],
        "edges": [
            {"id": "e1", "source": "start", "target": "ask_room"},
            {"id": "e2", "source": "ask_room", "target": "disabled"},
        ],
    }
    return FlowExecutor(parse_flow_config(config))


def test_stuck_message_node_exposes_a_real_continue_function():
    """Sitting on the room-selection message: nothing else is reachable, so a
    continue_flow_<id> function must be exposed instead of leaving the LLM
    with zero flow tools."""
    ex = _dead_end_message_chain_flow()
    ex.state.current_node_id = "ask_room"

    assert ex._get_pending_message_advance_node() is not None
    assert ex._get_pending_message_advance_node().id == "ask_room"

    names = _fn_names(ex.get_function_schemas())
    assert "continue_flow_ask_room" in names


def test_end_call_is_blocked_while_message_node_is_pending():
    """The root bug: nothing previously blocked end_call here because no
    SAVE_RECORD/API_REQUEST was downstream — only more MESSAGE nodes. Now
    is_on_required_action_node() must gate it, exactly like an action node."""
    ex = _dead_end_message_chain_flow()
    ex.state.current_node_id = "ask_room"

    assert ex.is_on_required_action_node() is True
    # has_pending_side_effect_downstream() legitimately stays False — there is
    # no data-mutating node downstream, only more messages. The new pending-
    # message check is what must catch this case.
    assert ex.has_pending_side_effect_downstream() is False


def test_continue_flow_advances_to_the_dead_end_and_exhausts_the_graph():
    """Calling continue_flow_<id> on the room-selection message moves the
    flow to the configured dead-end message and marks the graph exhausted —
    so flow_sessions ends up 'complete', not silently stuck 'active' (Task
    #600 done-criterion #3) — instead of leaving current_node_id stuck while
    the LLM fabricates a booking.

    The dead-end node itself has no outgoing edge, so no further tool call
    is required to "unstick" it: FlowState.advance_to() already marks the
    flow exhausted the moment it is reached, and — critically — it can only
    be reached by way of the explicit continue_flow_ask_room call, not by
    the LLM silently talking past it.
    """
    ex = _dead_end_message_chain_flow()
    ex.state.current_node_id = "ask_room"

    result = asyncio.run(ex._dispatch_function_call("continue_flow_ask_room", {}))
    assert result["success"] is True
    assert ex.state.current_node_id == "disabled"
    assert ex.state.graph_exhausted is True

    # The dead-end message has no outgoing edge, so it needs no further
    # explicit advance function — but the flow must still surface its text
    # (via node-context guidance) before anything else happens.
    assert ex._get_pending_message_advance_node() is None
    names = _fn_names(ex.get_function_schemas())
    assert not any(n.startswith("continue_flow_") for n in names)

    # Once genuinely exhausted, nothing is pending any more — the LLM (or the
    # global end_call) may now end the call normally, only AFTER the
    # configured message was actually reached via a real flow tool call
    # rather than skipped over.
    assert ex.is_on_required_action_node() is False


def test_out_of_order_continue_flow_call_is_rejected():
    """A continue_flow_<id> call for a node that isn't the pending one must be
    rejected like every other out-of-order action call."""
    ex = _dead_end_message_chain_flow()
    ex.state.current_node_id = "ask_room"

    result = asyncio.run(ex._dispatch_function_call("continue_flow_disabled", {}))
    assert result["success"] is False
    assert result.get("out_of_order") is True
    # State must not have moved.
    assert ex.state.current_node_id == "ask_room"


def test_message_node_with_reachable_collect_ahead_is_not_gated():
    """Existing behaviour must be preserved: a MESSAGE node that leads to a
    real collect node is NOT "stuck" — the collect function is already a
    real tool, so no continue_flow_<id> function should be added and
    end_call must stay ungated by this new check."""
    config = {
        "initial_node": "start",
        "variables": [{"key": "room", "type": "text", "description": "Room"}],
        "nodes": [
            {"id": "start", "type": "initial", "data": {}},
            {"id": "ask_room", "type": "message",
             "data": {"message": "Which room?", "waitForResponse": True}},
            {"id": "collect_room", "type": "collect_slot",
             "data": {"slot": {"variableKey": "room", "prompt": "Room?"}}},
            {"id": "end", "type": "end", "data": {}},
        ],
        "edges": [
            {"id": "e1", "source": "start", "target": "ask_room"},
            {"id": "e2", "source": "ask_room", "target": "collect_room"},
            {"id": "e3", "source": "collect_room", "target": "end"},
        ],
    }
    ex = FlowExecutor(parse_flow_config(config))
    ex.state.current_node_id = "ask_room"

    assert ex._get_pending_message_advance_node() is None
    assert ex.is_on_required_action_node() is False
    names = _fn_names(ex.get_function_schemas())
    assert "collect_room" in names
    assert not any(n.startswith("continue_flow_") for n in names)


def test_message_node_with_waitforresponse_false_is_not_gated():
    """A MESSAGE node NOT explicitly waiting for a reply is handled by the
    existing auto-walk path, not this new gate."""
    config = {
        "initial_node": "start",
        "variables": [],
        "nodes": [
            {"id": "start", "type": "initial", "data": {}},
            {"id": "notice", "type": "message",
             "data": {"message": "One moment.", "waitForResponse": False}},
        ],
        "edges": [
            {"id": "e1", "source": "start", "target": "notice"},
        ],
    }
    ex = FlowExecutor(parse_flow_config(config))
    ex.state.current_node_id = "notice"

    assert ex._get_pending_message_advance_node() is None
    assert ex.is_on_required_action_node() is False
