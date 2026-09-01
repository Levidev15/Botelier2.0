"""Tests for the API_RESPONSE node — rendering, auto-execution, and flow advance.

Covers:
  1. render_text — array iteration with dict items
  2. render_text — empty array → noResultsText
  3. render_text — scalar (non-dict) items
  4. render_text — no arrayVariable (intro + outro only)
  5. render_text — array stored as JSON string
  6. _handle_api_response — advances flow to next node
  7. get_function_schemas — exposes continue_response_<id> when node is current
  8. get_function_schemas — does NOT expose continue_response when node is not current
  9. Backward compat — flows without api_response nodes unaffected
"""

import json
import pytest
from unittest.mock import MagicMock, AsyncMock, patch

from botelier.flow_executor import (
    FlowExecutor,
    NodeType,
    FlowNode,
    FlowConfig,
    FlowVariable,
    FlowState,
)


# ── helpers ──────────────────────────────────────────────────────────────────

def _make_node(node_id: str, node_type: str, data: dict) -> FlowNode:
    node = FlowNode(id=node_id, type=node_type, data=data)
    return node


def _make_executor(nodes: list[FlowNode], variables=None, current_node_id=None) -> FlowExecutor:
    """Build a minimal FlowExecutor for unit-testing node methods."""
    flow_config = FlowConfig(
        nodes=nodes,
        edges=[],
        variables=variables or [],
        initial_node=nodes[0].id if nodes else None,
        global_prompt="",
    )
    # Build index manually (mirrors FlowConfig.__post_init__)
    flow_config._node_index = {n.id: n for n in nodes}

    # FlowState(flow_config) sets current_node_id = flow_config.initial_node.
    # Override it afterwards when we need a specific starting position.
    state = FlowState(flow_config)
    if current_node_id is not None:
        state.current_node_id = current_node_id

    # Stubs for methods tests don't drive through the real graph.
    state.get_current_node = lambda: flow_config._node_index.get(state.current_node_id)
    state.has_outgoing_edge = MagicMock(return_value=False)

    executor = FlowExecutor.__new__(FlowExecutor)
    executor.flow_config = flow_config
    executor.state = state
    executor._details_confirmed = False
    executor.db_session = None
    executor.call_log_id = None
    executor.logger = MagicMock()
    return executor


# ── 1. render_text — array iteration with dict items ─────────────────────────

def test_render_text_dict_items():
    rooms = [
        {"name": "Deluxe King", "price": "250"},
        {"name": "Suite", "price": "400"},
    ]
    node = _make_node("resp1", "api_response", {
        "responsePresentation": {
            "arrayVariable": "rooms",
            "introText": "Here are the options.",
            "itemTemplate": "Option {{index}}: {{name}}, {{price}} per night.",
            "outroText": "Which do you prefer?",
            "noResultsText": "No rooms found.",
        }
    })
    executor = _make_executor([node], current_node_id="resp1")
    executor.state.collected_slots["rooms"] = rooms

    text = executor._render_api_response_text(node)

    assert "Here are the options." in text
    assert "Option 1: Deluxe King, 250 per night." in text
    assert "Option 2: Suite, 400 per night." in text
    assert "Which do you prefer?" in text
    assert "No rooms found." not in text


# ── 2. render_text — empty array → noResultsText ─────────────────────────────

def test_render_text_empty_array():
    node = _make_node("resp2", "api_response", {
        "responsePresentation": {
            "arrayVariable": "rooms",
            "introText": "Here are the options.",
            "itemTemplate": "{{name}}",
            "noResultsText": "Sorry, no availability.",
        }
    })
    executor = _make_executor([node], current_node_id="resp2")
    executor.state.collected_slots["rooms"] = []

    text = executor._render_api_response_text(node)

    assert text == "Sorry, no availability."


# ── 3. render_text — scalar (non-dict) items ─────────────────────────────────

def test_render_text_scalar_items():
    node = _make_node("resp3", "api_response", {
        "responsePresentation": {
            "arrayVariable": "options",
            "itemTemplate": "Option {{index}}: {{item}}.",
            "noResultsText": "None available.",
        }
    })
    executor = _make_executor([node], current_node_id="resp3")
    executor.state.collected_slots["options"] = ["Standard", "Deluxe"]

    text = executor._render_api_response_text(node)

    assert "Option 1: Standard." in text
    assert "Option 2: Deluxe." in text


# ── 4. render_text — no arrayVariable (intro + outro only) ───────────────────

def test_render_text_no_array_variable():
    """No arrayVariable → speak intro + outro directly (fixed narration mode)."""
    node = _make_node("resp4", "api_response", {
        "responsePresentation": {
            "introText": "Your booking is confirmed.",
            "outroText": "Have a great stay!",
            "noResultsText": "Something went wrong.",
        }
    })
    executor = _make_executor([node], current_node_id="resp4")

    text = executor._render_api_response_text(node)

    # No arrayVariable → fixed narration: intro + outro (no array to iterate).
    # noResultsText is only used when an arrayVariable IS configured but empty.
    assert "Your booking is confirmed." in text
    assert "Have a great stay!" in text
    assert "Something went wrong." not in text


# ── 5. render_text — array stored as JSON string ─────────────────────────────

def test_render_text_json_string_array():
    rooms = [{"name": "Twin", "price": "180"}]
    node = _make_node("resp5", "api_response", {
        "responsePresentation": {
            "arrayVariable": "rooms_json",
            "itemTemplate": "{{name}} at {{price}}.",
            "noResultsText": "None.",
        }
    })
    executor = _make_executor([node], current_node_id="resp5")
    executor.state.collected_slots["rooms_json"] = json.dumps(rooms)

    text = executor._render_api_response_text(node)

    assert "Twin at 180." in text


# ── 6. _handle_api_response — advances flow to next node ─────────────────────

@pytest.mark.asyncio
async def test_handle_api_response_advances_flow():
    resp_node = _make_node("resp6", "api_response", {"responsePresentation": {}})
    next_node = _make_node("end6", "end", {"closingMessage": "Goodbye"})
    executor = _make_executor([resp_node, next_node], current_node_id="resp6")

    # Wire a fake edge
    mock_next = MagicMock()
    mock_next.id = "end6"
    executor.state.get_next_node = MagicMock(return_value=mock_next)
    executor.state.advance_to = MagicMock()

    result = await executor._handle_api_response("continue_response_resp6", {})

    assert result["success"] is True
    executor.state.advance_to.assert_called_once_with("end6")


# ── 7. get_function_schemas — exposes continue_response when current ──────────

def test_get_function_schemas_exposes_response_fn_when_current():
    resp_node = _make_node("resp7", "api_response", {
        "responsePresentation": {"arrayVariable": "rooms"}
    })
    executor = _make_executor([resp_node], current_node_id="resp7")

    # Stub out the parts we don't need for this narrow test
    executor._find_next_reachable_collect_slot = MagicMock(return_value=(None, None))
    executor._get_reachable_action_node_ids = MagicMock(return_value=set())
    executor._should_expose_confirm_details = MagicMock(return_value=False)
    executor.state.has_outgoing_edge = MagicMock(return_value=True)

    schemas = executor.get_function_schemas()
    names = [s["function"]["name"] for s in schemas]

    assert "continue_response_resp7" in names


# ── 8. get_function_schemas — does NOT expose when not current ────────────────

def test_get_function_schemas_suppresses_response_fn_when_not_current():
    resp_node = _make_node("resp8", "api_response", {"responsePresentation": {}})
    collect_node = _make_node("slot8", "collect_slot", {
        "slot": {"variableKey": "name", "prompt": "Your name?", "type": "text"}
    })
    executor = _make_executor([collect_node, resp_node], current_node_id="slot8")

    executor._find_next_reachable_collect_slot = MagicMock(return_value=(None, None))
    executor._get_reachable_action_node_ids = MagicMock(return_value=set())
    executor._should_expose_confirm_details = MagicMock(return_value=False)
    executor.state.has_outgoing_edge = MagicMock(return_value=True)

    schemas = executor.get_function_schemas()
    names = [s["function"]["name"] for s in schemas]

    assert "continue_response_resp8" not in names


# ── 9. Backward compat — flows without api_response nodes unaffected ──────────

def test_flows_without_api_response_unaffected():
    """Existing flows must not expose any continue_response_ functions."""
    slot_node = _make_node("slot9", "collect_slot", {
        "slot": {"variableKey": "guest_name", "prompt": "Name?", "type": "text"}
    })
    end_node = _make_node("end9", "end", {"closingMessage": "Bye"})
    executor = _make_executor([slot_node, end_node], current_node_id="slot9")

    executor._find_next_reachable_collect_slot = MagicMock(return_value=(None, None))
    executor._get_reachable_action_node_ids = MagicMock(return_value=set())
    executor._should_expose_confirm_details = MagicMock(return_value=False)
    executor.state.has_outgoing_edge = MagicMock(return_value=True)

    schemas = executor.get_function_schemas()
    names = [s["function"]["name"] for s in schemas]

    assert not any(n.startswith("continue_response_") for n in names)
