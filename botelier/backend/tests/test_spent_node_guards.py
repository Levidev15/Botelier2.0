"""Regression tests for the spent-node guard in flow_executor.py.

The root cause of a real call failure: after the Confirm Details node fired
and advanced the flow to Save Record, the LLM held a stale tool list that
still included set_var_<id>. It called that function instead of save_record_<id>,
re-triggering Set Variable → advancing back to Collect Form → speaking
"May I have your first name?" after the booking was already confirmed. No
booking record was ever created.

The fix adds a ``state.current_node_id != node_id`` guard to both
``_handle_set_variable`` and ``_handle_save_record_locked``, mirroring the
guard that already existed in ``_handle_option_picker``.

These tests verify that a call to a spent node returns ``out_of_order=True``
and does NOT mutate flow state or advance the flow position.
"""

import pytest

from botelier.flow_executor import FlowExecutor, parse_flow_config


# ---------------------------------------------------------------------------
# Shared flow fixture
# ---------------------------------------------------------------------------

def _booking_flow():
    """option_picker → set_var → collect_form → confirmation → save_record → end."""
    config = {
        "initial_node": "start",
        "variables": [
            {"key": "selected_room", "type": "text", "description": "Room"},
            {"key": "first_name", "type": "text", "description": "First name"},
        ],
        "nodes": [
            {"id": "start", "type": "initial", "data": {}},
            {
                "id": "picker",
                "type": "option_picker",
                "data": {
                    "optionPicker": {
                        "prompt": "Which room?",
                        "sourceVariable": "rooms",
                        "labelPath": "",
                        "writes": [{"path": "", "variableKey": "selected_room"}],
                        "maxRetries": 3,
                        "retryPrompt": "",
                    }
                },
            },
            {
                "id": "setvr",
                "type": "set_variable",
                "data": {
                    "setVariable": {
                        "variableKey": "cancellation_id",
                        "value": "1000",
                        "valueType": "static",
                    }
                },
            },
            {
                "id": "form",
                "type": "collect_form",
                "data": {
                    "slots": [
                        {
                            "id": "s1",
                            "variableKey": "first_name",
                            "type": "text",
                            "prompt": "First name?",
                            "maxRetries": 3,
                            "retryPrompt": "",
                            "order": 0,
                        }
                    ]
                },
            },
            {
                "id": "confirm",
                "type": "confirmation",
                "data": {
                    "confirmation": {
                        "variablesToConfirm": ["first_name"],
                        "summaryTemplate": "Name: {{first_name}}",
                        "confirmPrompt": "Correct?",
                        "allowEdit": False,
                    }
                },
            },
            {
                "id": "saverec",
                "type": "save_record",
                "data": {
                    "saveRecord": {
                        "recordTypeId": "00000000-0000-0000-0000-000000000001",
                        "recordTypeName": "Bookings",
                        "mapping": {"first_name": "{{first_name}}"},
                        "status": "",
                    }
                },
            },
            {"id": "endit", "type": "end", "data": {}},
        ],
        "edges": [
            {"id": "e0", "source": "start", "target": "picker"},
            {"id": "e1", "source": "picker", "target": "setvr", "sourceHandle": "selected"},
            {"id": "e2", "source": "setvr", "target": "form"},
            {"id": "e3", "source": "form", "target": "confirm"},
            {"id": "e4", "source": "confirm", "target": "saverec", "sourceHandle": "confirmed"},
            {"id": "e5", "source": "saverec", "target": "endit"},
        ],
    }
    return FlowExecutor(parse_flow_config(config))


# ---------------------------------------------------------------------------
# set_var guard
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_set_var_returns_out_of_order_when_flow_is_past_it():
    """Calling set_var_setvr when the flow is at save_record returns out_of_order."""
    ex = _booking_flow()
    # Simulate flow having advanced past setvr all the way to save_record.
    ex.state.current_node_id = "saverec"
    ex.state.collected_slots["first_name"] = "Corey"

    result = await ex._handle_set_variable("set_var_setvr", {})

    assert result.get("out_of_order") is True
    assert result.get("success") is False
    # Flow position must not have changed.
    assert ex.state.current_node_id == "saverec"
    # The variable must not have been written.
    assert "cancellation_id" not in ex.state.collected_slots


@pytest.mark.asyncio
async def test_set_var_succeeds_when_it_is_the_current_node():
    """Calling set_var_setvr when the flow is genuinely at setvr works normally."""
    ex = _booking_flow()
    ex.state.current_node_id = "setvr"

    result = await ex._handle_set_variable("set_var_setvr", {})

    assert result.get("out_of_order") is not True
    assert result.get("success") is True
    assert ex.state.collected_slots.get("cancellation_id") == "1000"
    # Flow must have advanced to the form node.
    assert ex.state.current_node_id == "form"


@pytest.mark.asyncio
async def test_set_var_returns_out_of_order_when_flow_is_at_confirmation():
    """Calling set_var_setvr after confirmation started also returns out_of_order."""
    ex = _booking_flow()
    ex.state.current_node_id = "confirm"
    ex.state.collected_slots["first_name"] = "Corey"

    result = await ex._handle_set_variable("set_var_setvr", {})

    assert result.get("out_of_order") is True
    assert ex.state.current_node_id == "confirm"


# ---------------------------------------------------------------------------
# save_record guard
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_save_record_returns_out_of_order_when_flow_already_past_it():
    """A duplicate save_record call (flow already at end) returns out_of_order."""
    ex = _booking_flow()
    # Simulate flow having already advanced past save_record to end.
    ex.state.current_node_id = "endit"
    ex.state.collected_slots["first_name"] = "Corey"

    result = await ex._handle_save_record("save_record_saverec", {})

    assert result.get("out_of_order") is True
    assert result.get("success") is False
    assert ex.state.current_node_id == "endit"


@pytest.mark.asyncio
async def test_save_record_succeeds_when_it_is_the_current_node():
    """Calling save_record_saverec when the flow is at saverec proceeds normally."""
    ex = _booking_flow()
    ex.state.current_node_id = "saverec"
    ex.state.collected_slots["first_name"] = "Corey"

    result = await ex._handle_save_record("save_record_saverec", {})

    # The guard must not fire (out_of_order absent / False).
    assert not result.get("out_of_order")
    # Save may fail internally (no DB session in unit test), but guard did not fire.
    assert result.get("out_of_order") is not True
