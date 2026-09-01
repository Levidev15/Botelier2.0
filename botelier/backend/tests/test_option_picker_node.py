"""Tests for the OPTION_PICKER node — universal "bind the caller's choice" step.

Covers:
  1. _resolve_option_picker_items — list / JSON-string / missing source
  2. _resolve_option_picker_choice — ordinal, exact label, substring label,
     ambiguous exact, ambiguous substring, no match
  3. _handle_option_picker — atomic writes, re-selection clears stale fields,
     out-of-order rejection, empty-source failure (no retry charge),
     ambiguous/no-match retry flow, retry exhaustion (fallback edge,
     escalation transfer, graceful end), advancing via "selected" handle vs.
     unlabelled fallback, and landing straight on an END node
  4. get_function_schemas — exposes/suppresses select_option_<id>, ordinal bounds
  5. _dispatch_function_call — routes select_option_ prefix
  6. validate_flow_config — publish-time validation for option_picker nodes
"""

import asyncio
import pytest
from unittest.mock import MagicMock

from botelier.flow_executor import (
    FlowExecutor,
    NodeType,
    FlowNode,
    FlowEdge,
    FlowConfig,
    FlowState,
)
from botelier.api.flow_versions import validate_flow_config


# ── helpers ──────────────────────────────────────────────────────────────────

def _make_node(node_id: str, node_type: str, data: dict) -> FlowNode:
    return FlowNode(id=node_id, type=node_type, data=data)


def _make_executor(
    nodes: list[FlowNode], variables=None, current_node_id=None, edges=None
) -> FlowExecutor:
    """Build a minimal FlowExecutor for unit-testing node methods."""
    flow_config = FlowConfig(
        nodes=nodes,
        edges=edges or [],
        variables=variables or [],
        initial_node=nodes[0].id if nodes else None,
        global_prompt="",
    )
    flow_config._node_index = {n.id: n for n in nodes}

    state = FlowState(flow_config)
    if current_node_id is not None:
        state.current_node_id = current_node_id

    state.get_current_node = lambda: flow_config._node_index.get(state.current_node_id)
    state.has_outgoing_edge = MagicMock(return_value=False)

    executor = FlowExecutor.__new__(FlowExecutor)
    executor.flow_config = flow_config
    executor.state = state
    executor._details_confirmed = False
    executor.db_session = None
    executor.call_log_id = None
    executor.logger = MagicMock()
    executor.escalation_target = None
    executor.end_call_callback = None
    executor.transfer_callback = None
    executor._turn_lock = asyncio.Lock()
    return executor


RATES = [
    {"name": "Standard King", "rate": {"code": "STD1", "price": 150}},
    {"name": "Deluxe King", "rate": {"code": "DLX1", "price": 220}},
    {"name": "Deluxe Suite", "rate": {"code": "DLX1", "price": 350}},  # duplicate rate code, distinct name
]

PICKER_CONFIG = {
    "sourceVariable": "rates",
    "labelPath": "name",
    "prompt": "Which room would you like?",
    "retryPrompt": "Sorry, which one?",
    "maxRetries": 2,
    "writes": [
        {"variableKey": "room_type", "path": "name"},
        {"variableKey": "rate_code", "path": "rate.code"},
        {"variableKey": "price", "path": "rate.price"},
    ],
}


def _picker_node(node_id="pick1", config=None):
    return _make_node(node_id, "option_picker", {"name": "Room Picker", "optionPicker": config or PICKER_CONFIG})


# ── 1. _resolve_option_picker_items ───────────────────────────────────────────

def test_resolve_items_from_real_list():
    node = _picker_node()
    executor = _make_executor([node], current_node_id="pick1")
    executor.state.collected_slots["rates"] = RATES

    items = executor._resolve_option_picker_items(PICKER_CONFIG)

    assert items == RATES


def test_resolve_items_from_json_string():
    import json
    node = _picker_node()
    executor = _make_executor([node], current_node_id="pick1")
    executor.state.collected_slots["rates"] = json.dumps(RATES)

    items = executor._resolve_option_picker_items(PICKER_CONFIG)

    assert items == RATES


def test_resolve_items_missing_or_malformed_is_empty():
    node = _picker_node()
    executor = _make_executor([node], current_node_id="pick1")

    assert executor._resolve_option_picker_items(PICKER_CONFIG) == []

    executor.state.collected_slots["rates"] = "not json"
    assert executor._resolve_option_picker_items(PICKER_CONFIG) == []

    executor.state.collected_slots["rates"] = {"not": "a list"}
    assert executor._resolve_option_picker_items(PICKER_CONFIG) == []


# ── 2. _resolve_option_picker_choice ──────────────────────────────────────────

def test_choice_by_ordinal():
    node = _picker_node()
    executor = _make_executor([node], current_node_id="pick1")

    match, ambiguous = executor._resolve_option_picker_choice(RATES, PICKER_CONFIG, {"ordinal": 2})

    assert ambiguous is False
    assert match == (1, RATES[1])


def test_choice_by_ordinal_out_of_range_falls_through_to_no_match():
    node = _picker_node()
    executor = _make_executor([node], current_node_id="pick1")

    match, ambiguous = executor._resolve_option_picker_choice(RATES, PICKER_CONFIG, {"ordinal": 99})

    assert match is None
    assert ambiguous is False


def test_choice_by_exact_label():
    node = _picker_node()
    executor = _make_executor([node], current_node_id="pick1")

    match, ambiguous = executor._resolve_option_picker_choice(
        RATES, PICKER_CONFIG, {"label": "deluxe king"}
    )

    assert ambiguous is False
    assert match == (1, RATES[1])


def test_choice_by_substring_label():
    node = _picker_node()
    executor = _make_executor([node], current_node_id="pick1")

    match, ambiguous = executor._resolve_option_picker_choice(
        RATES, PICKER_CONFIG, {"label": "suite"}
    )

    assert ambiguous is False
    assert match == (2, RATES[2])


def test_choice_ambiguous_substring_label_never_guesses():
    node = _picker_node()
    executor = _make_executor([node], current_node_id="pick1")

    # "king" substring-matches both "Standard King" and "Deluxe King"
    match, ambiguous = executor._resolve_option_picker_choice(
        RATES, PICKER_CONFIG, {"label": "king"}
    )

    assert match is None
    assert ambiguous is True


def test_choice_no_match_at_all():
    node = _picker_node()
    executor = _make_executor([node], current_node_id="pick1")

    match, ambiguous = executor._resolve_option_picker_choice(
        RATES, PICKER_CONFIG, {"label": "penthouse"}
    )

    assert match is None
    assert ambiguous is False


def test_choice_ignores_boolean_ordinal():
    """bool is an int subclass in Python — must not be treated as a valid ordinal."""
    node = _picker_node()
    executor = _make_executor([node], current_node_id="pick1")

    match, ambiguous = executor._resolve_option_picker_choice(RATES, PICKER_CONFIG, {"ordinal": True})

    assert match is None
    assert ambiguous is False


# ── 3. _handle_option_picker ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_handle_option_picker_binds_all_fields_atomically():
    picker = _picker_node()
    next_node = _make_node("next1", "message", {"message": "Great choice."})
    executor = _make_executor(
        [picker, next_node],
        current_node_id="pick1",
        edges=[FlowEdge("e1", "pick1", "next1", source_handle="selected")],
    )
    executor.state.collected_slots["rates"] = RATES

    result = await executor._handle_option_picker("select_option_pick1", {"ordinal": 2})

    assert result["success"] is True
    assert result["bound"] == {"room_type": "Deluxe King", "rate_code": "DLX1", "price": 220}
    assert executor.state.collected_slots["room_type"] == "Deluxe King"
    assert executor.state.collected_slots["rate_code"] == "DLX1"
    assert executor.state.collected_slots["price"] == 220
    assert executor.state.current_node_id == "next1"


@pytest.mark.asyncio
async def test_reselection_replaces_and_clears_stale_fields():
    """A field the second pick doesn't have must not keep the first pick's value."""
    config = {
        **PICKER_CONFIG,
        "writes": [
            {"variableKey": "room_type", "path": "name"},
            {"variableKey": "breakfast_included", "path": "rate.breakfastIncluded"},
        ],
    }
    items = [
        {"name": "Deluxe King", "rate": {"breakfastIncluded": True}},
        {"name": "Standard King", "rate": {}},  # no breakfastIncluded field at all
    ]
    picker = _picker_node(config=config)
    executor = _make_executor([picker], current_node_id="pick1")
    executor.state.collected_slots["rates"] = items

    first = await executor._handle_option_picker("select_option_pick1", {"ordinal": 1})
    assert first["bound"]["breakfast_included"] is True
    assert executor.state.collected_slots["breakfast_included"] is True

    # Caller changes their mind — return to the picker and choose again.
    executor.state.current_node_id = "pick1"
    second = await executor._handle_option_picker("select_option_pick1", {"ordinal": 2})

    assert second["bound"]["room_type"] == "Standard King"
    assert second["bound"]["breakfast_included"] is None
    assert executor.state.collected_slots["breakfast_included"] is None


@pytest.mark.asyncio
async def test_rejects_stale_node():
    picker = _picker_node()
    other = _make_node("other1", "message", {})
    executor = _make_executor([picker, other], current_node_id="other1")

    result = await executor._handle_option_picker("select_option_pick1", {"ordinal": 1})

    assert result["success"] is False
    assert result["out_of_order"] is True
    assert executor.state.current_node_id == "other1"


@pytest.mark.asyncio
async def test_empty_source_fails_without_charging_retry_budget():
    picker = _picker_node()
    executor = _make_executor([picker], current_node_id="pick1")
    # No "rates" in collected_slots at all.

    result = await executor._handle_option_picker("select_option_pick1", {"ordinal": 1})

    assert result["success"] is False
    assert executor.state.retry_count == 0
    assert executor.state.current_node_id == "pick1"


@pytest.mark.asyncio
async def test_ambiguous_choice_retries_without_binding():
    picker = _picker_node()
    executor = _make_executor([picker], current_node_id="pick1")
    executor.state.collected_slots["rates"] = RATES

    result = await executor._handle_option_picker("select_option_pick1", {"label": "king"})

    assert result["success"] is False
    assert executor.state.retry_count == 1
    assert "room_type" not in executor.state.collected_slots
    assert executor.state.current_node_id == "pick1"


@pytest.mark.asyncio
async def test_retry_exhaustion_routes_fallback_edge():
    picker = _picker_node()  # maxRetries = 2
    fallback_node = _make_node("fb1", "message", {"message": "Let's move on."})
    executor = _make_executor(
        [picker, fallback_node],
        current_node_id="pick1",
        edges=[FlowEdge("e1", "pick1", "fb1", source_handle="fallback")],
    )
    executor.state.collected_slots["rates"] = RATES

    await executor._handle_option_picker("select_option_pick1", {"label": "nope"})
    result = await executor._handle_option_picker("select_option_pick1", {"label": "nope"})

    assert result["retry_exhausted"] is True
    assert executor.state.current_node_id == "fb1"


@pytest.mark.asyncio
async def test_retry_exhaustion_escalates_when_no_fallback_edge():
    picker = _picker_node()
    executor = _make_executor([picker], current_node_id="pick1")
    executor.state.collected_slots["rates"] = RATES
    executor.escalation_target = "+15551234567"

    await executor._handle_option_picker("select_option_pick1", {"label": "nope"})
    result = await executor._handle_option_picker("select_option_pick1", {"label": "nope"})

    assert result["retry_exhausted"] is True
    assert result["action"] == "transfer"
    assert result["target"] == "+15551234567"
    assert executor.state.transfer_requested is True


@pytest.mark.asyncio
async def test_retry_exhaustion_ends_gracefully_with_no_fallback_or_escalation():
    picker = _picker_node()
    executor = _make_executor([picker], current_node_id="pick1")
    executor.state.collected_slots["rates"] = RATES

    await executor._handle_option_picker("select_option_pick1", {"label": "nope"})
    result = await executor._handle_option_picker("select_option_pick1", {"label": "nope"})

    assert result["retry_exhausted"] is True
    assert result["action"] == "end"
    assert executor.state.is_complete is True


@pytest.mark.asyncio
async def test_falls_back_to_unlabelled_edge_when_no_selected_handle():
    picker = _picker_node()
    next_node = _make_node("next2", "message", {"message": "ok"})
    executor = _make_executor(
        [picker, next_node],
        current_node_id="pick1",
        edges=[FlowEdge("e1", "pick1", "next2")],  # no sourceHandle at all
    )
    executor.state.collected_slots["rates"] = RATES

    result = await executor._handle_option_picker("select_option_pick1", {"ordinal": 1})

    assert result["success"] is True
    assert executor.state.current_node_id == "next2"


@pytest.mark.asyncio
async def test_landing_on_end_node_actually_ends_the_call():
    picker = _picker_node()
    end_node = _make_node("end1", "end", {"closingMessage": "Thanks, goodbye!"})
    executor = _make_executor(
        [picker, end_node],
        current_node_id="pick1",
        edges=[FlowEdge("e1", "pick1", "end1", source_handle="selected")],
    )
    executor.state.collected_slots["rates"] = RATES

    result = await executor._handle_option_picker("select_option_pick1", {"ordinal": 1})

    assert result["action"] == "end"
    assert executor.state.is_complete is True


# ── 4. get_function_schemas — exposure and ordinal bounds ────────────────────

def test_get_function_schemas_exposes_picker_fn_when_current():
    picker = _picker_node()
    executor = _make_executor([picker], current_node_id="pick1")
    executor.state.collected_slots["rates"] = RATES

    executor._find_next_reachable_collect_slot = MagicMock(return_value=(None, None))
    executor._get_reachable_action_node_ids = MagicMock(return_value={"pick1"})
    executor._should_expose_confirm_details = MagicMock(return_value=False)
    executor.state.has_outgoing_edge = MagicMock(return_value=True)

    schemas = executor.get_function_schemas()
    names = [s["function"]["name"] for s in schemas]
    assert "select_option_pick1" in names

    picker_fn = next(s for s in schemas if s["function"]["name"] == "select_option_pick1")
    ordinal_schema = picker_fn["function"]["parameters"]["properties"]["ordinal"]
    assert ordinal_schema["minimum"] == 1
    assert ordinal_schema["maximum"] == len(RATES)


def test_get_function_schemas_suppresses_picker_fn_when_not_current():
    picker = _picker_node()
    collect_node = _make_node("slot1", "collect_slot", {
        "slot": {"variableKey": "name", "prompt": "Your name?", "type": "text"}
    })
    executor = _make_executor([collect_node, picker], current_node_id="slot1")

    executor._find_next_reachable_collect_slot = MagicMock(return_value=(None, None))
    executor._get_reachable_action_node_ids = MagicMock(return_value=set())
    executor._should_expose_confirm_details = MagicMock(return_value=False)
    executor.state.has_outgoing_edge = MagicMock(return_value=True)

    schemas = executor.get_function_schemas()
    names = [s["function"]["name"] for s in schemas]
    assert "select_option_pick1" not in names


# ── 5. _dispatch_function_call routes select_option_ prefix ──────────────────

@pytest.mark.asyncio
async def test_dispatch_gates_option_picker_like_other_actions():
    picker = _picker_node()
    executor = _make_executor([picker], current_node_id="pick1")
    executor.get_function_schemas = MagicMock(return_value=[])

    result = await executor._dispatch_function_call("select_option_pick1", {"ordinal": 1})

    assert result["success"] is False
    assert result["out_of_order"] is True


# ── 6. validate_flow_config — publish-time validation ─────────────────────────

def _base_flow(picker_data: dict, extra_edges=None, variables=None):
    return {
        "initial_node": "start",
        "nodes": [
            {"id": "start", "type": "initial", "data": {"name": "Start", "systemPrompt": "", "greeting": "hi"}},
            {"id": "pick1", "type": "option_picker", "data": picker_data},
            {"id": "next1", "type": "end", "data": {"closingMessage": "Bye"}},
        ],
        "edges": [
            {"id": "e0", "source": "start", "target": "pick1"},
            {"id": "e1", "source": "pick1", "target": "next1", "sourceHandle": "selected"},
            *(extra_edges or []),
        ],
        "variables": variables if variables is not None else [
            {"key": "rates", "type": "text"},
            {"key": "room_type", "type": "text"},
            {"key": "rate_code", "type": "text"},
            {"key": "price", "type": "number"},
        ],
    }


def test_validate_accepts_well_formed_option_picker():
    flow = _base_flow({"name": "Pick", "optionPicker": PICKER_CONFIG})
    is_valid, errors, _ = validate_flow_config(flow)
    assert is_valid, errors


def test_validate_rejects_missing_source_variable():
    config = {**PICKER_CONFIG, "sourceVariable": ""}
    flow = _base_flow({"name": "Pick", "optionPicker": config})
    is_valid, errors, _ = validate_flow_config(flow)
    assert not is_valid
    assert any("source array variable" in e for e in errors)


def test_validate_rejects_missing_label_path():
    config = {**PICKER_CONFIG, "labelPath": ""}
    flow = _base_flow({"name": "Pick", "optionPicker": config})
    is_valid, errors, _ = validate_flow_config(flow)
    assert not is_valid
    assert any("label field" in e for e in errors)


def test_validate_rejects_empty_writes():
    config = {**PICKER_CONFIG, "writes": []}
    flow = _base_flow({"name": "Pick", "optionPicker": config})
    is_valid, errors, _ = validate_flow_config(flow)
    assert not is_valid
    assert any("writes no flow variables" in e for e in errors)


def test_validate_rejects_duplicate_write_keys():
    config = {
        **PICKER_CONFIG,
        "writes": [
            {"variableKey": "room_type", "path": "name"},
            {"variableKey": "room_type", "path": "rate.code"},
        ],
    }
    flow = _base_flow({"name": "Pick", "optionPicker": config})
    is_valid, errors, _ = validate_flow_config(flow)
    assert not is_valid
    assert any("more than once" in e for e in errors)


def test_validate_rejects_undeclared_write_target():
    config = {
        **PICKER_CONFIG,
        "writes": [{"variableKey": "undeclared_var", "path": "name"}],
    }
    flow = _base_flow(
        {"name": "Pick", "optionPicker": config},
        variables=[{"key": "rates", "type": "text"}],
    )
    is_valid, errors, _ = validate_flow_config(flow)
    assert not is_valid
    assert any("undeclared_var" in e for e in errors)


def test_validate_requires_selected_branch():
    flow = _base_flow({"name": "Pick", "optionPicker": PICKER_CONFIG})
    # Replace the "selected" edge with an unrelated handle.
    flow["edges"][1]["sourceHandle"] = "weird"
    is_valid, errors, _ = validate_flow_config(flow)
    assert not is_valid
    assert any("'selected' branch" in e for e in errors)


def test_validate_accepts_legacy_unlabelled_single_edge_as_selected():
    flow = _base_flow({"name": "Pick", "optionPicker": PICKER_CONFIG})
    del flow["edges"][1]["sourceHandle"]
    is_valid, errors, _ = validate_flow_config(flow)
    assert is_valid, errors


def test_validate_rejects_more_than_one_fallback_branch():
    flow = _base_flow(
        {"name": "Pick", "optionPicker": PICKER_CONFIG},
        extra_edges=[
            {"id": "e2", "source": "pick1", "target": "next1", "sourceHandle": "fallback"},
            {"id": "e3", "source": "pick1", "target": "next1", "sourceHandle": "fallback"},
        ],
    )
    is_valid, errors, _ = validate_flow_config(flow)
    assert not is_valid
    assert any("more than one 'fallback'" in e for e in errors)
