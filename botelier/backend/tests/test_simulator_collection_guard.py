"""Regression coverage for reliable Test Lab collection of direct answers."""

import json
from unittest.mock import MagicMock

import pytest

from botelier.api.simulation import SimulationState, _process_with_llm
from botelier.flow_executor import FlowExecutor, parse_flow_config


def _tool_call_response(tool_name: str, arguments: dict) -> MagicMock:
    tool_call = MagicMock()
    tool_call.id = "tc_collection_guard"
    tool_call.function.name = tool_name
    tool_call.function.arguments = json.dumps(arguments)

    message = MagicMock()
    message.tool_calls = [tool_call]
    message.content = None
    response = MagicMock()
    response.choices[0].message = message
    return response


def _multiple_tool_calls_response(calls: list[tuple[str, dict]]) -> MagicMock:
    """Build one LLM response that submits several form fields together."""
    tool_calls = []
    for index, (tool_name, arguments) in enumerate(calls):
        tool_call = MagicMock()
        tool_call.id = f"tc_collection_guard_{index}"
        tool_call.function.name = tool_name
        tool_call.function.arguments = json.dumps(arguments)
        tool_calls.append(tool_call)

    message = MagicMock()
    message.tool_calls = tool_calls
    message.content = None
    response = MagicMock()
    response.choices[0].message = message
    return response


def _text_response(content: str) -> MagicMock:
    message = MagicMock()
    message.tool_calls = []
    message.content = content
    response = MagicMock()
    response.choices[0].message = message
    return response


def _state() -> SimulationState:
    config = {
        "initial_node": "adults",
        "variables": [
            {
                "key": "adults",
                "type": "number",
                "description": "number of adults",
                "required": True,
            }
        ],
        "nodes": [
            {
                "id": "adults",
                "type": "collect_slot",
                "data": {
                    "slot": {
                        "variableKey": "adults",
                        "prompt": "How many adults are staying?",
                        "validation": {"min": 1, "max": 8},
                    }
                },
            },
            {"id": "next", "type": "message", "data": {"message": "Thanks."}},
        ],
        "edges": [{"id": "e", "source": "adults", "target": "next"}],
    }
    return SimulationState(
        tool_id="collection-guard-test",
        tool_name="Booking",
        executor=FlowExecutor(parse_flow_config(config)),
        model="gpt-4o-mini",
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("user_message", "tool_value"),
    [("two", 2), ("2", 2)],
)
async def test_direct_numeric_answer_forces_active_collection(
    monkeypatch, user_message, tool_value
):
    """Word and digit answers must collect the active numeric slot."""
    import botelier.api.simulation as simulation

    state = _state()
    client = MagicMock()
    client.chat.completions.create.side_effect = [
        _tool_call_response("collect_adults", {"adults": tool_value}),
        _text_response("Thanks. I'll check availability now."),
    ]
    monkeypatch.setattr(simulation, "openai_client", client)

    result = await _process_with_llm(state, user_message)

    first_request = client.chat.completions.create.call_args_list[0].kwargs
    assert first_request["tool_choice"] == {
        "type": "function",
        "function": {"name": "collect_adults"},
    }
    assert state.executor.state.get_variable("adults") == tool_value
    assert result["function_called"] == "collect_adults"


@pytest.mark.asyncio
async def test_mid_flow_question_stays_conversational(monkeypatch):
    """A question must not be coerced into the currently requested field."""
    import botelier.api.simulation as simulation

    state = _state()
    client = MagicMock()
    client.chat.completions.create.return_value = _text_response(
        "Yes, the hotel allows pets. How many adults are staying?"
    )
    monkeypatch.setattr(simulation, "openai_client", client)

    result = await _process_with_llm(state, "Do you allow pets?")

    request = client.chat.completions.create.call_args.kwargs
    assert request["tool_choice"] == "auto"
    assert state.executor.state.get_variable("adults") is None
    assert state.executor.state.current_node_id == "adults"
    assert result["function_called"] is None


@pytest.mark.asyncio
async def test_direct_date_answer_forces_active_collection(monkeypatch):
    """The same guard applies to valid direct answers for non-numeric slots."""
    import botelier.api.simulation as simulation

    config = {
        "initial_node": "checkin",
        "variables": [
            {
                "key": "checkin",
                "type": "date",
                "description": "check-in date",
                "required": True,
            }
        ],
        "nodes": [
            {
                "id": "checkin",
                "type": "collect_slot",
                "data": {"slot": {"variableKey": "checkin", "prompt": "When do you arrive?"}},
            },
            {"id": "next", "type": "message", "data": {}},
        ],
        "edges": [{"id": "e", "source": "checkin", "target": "next"}],
    }
    state = SimulationState(
        tool_id="date-collection-guard-test",
        tool_name="Booking",
        executor=FlowExecutor(parse_flow_config(config)),
        model="gpt-4o-mini",
    )
    client = MagicMock()
    client.chat.completions.create.side_effect = [
        _tool_call_response("collect_checkin", {"checkin": "2026-09-09"}),
        _text_response("Thanks."),
    ]
    monkeypatch.setattr(simulation, "openai_client", client)

    await _process_with_llm(state, "2026-09-09")

    request = client.chat.completions.create.call_args_list[0].kwargs
    assert request["tool_choice"]["function"]["name"] == "collect_checkin"
    assert state.executor.state.get_variable("checkin") == "2026-09-09"


@pytest.mark.asyncio
async def test_natural_language_date_starting_with_may_is_collected(monkeypatch):
    """Month names must not be mistaken for auxiliary-verb questions."""
    import botelier.api.simulation as simulation

    config = {
        "initial_node": "checkin",
        "variables": [{"key": "checkin", "type": "date", "description": "check-in date"}],
        "nodes": [
            {
                "id": "checkin",
                "type": "collect_slot",
                "data": {"slot": {"variableKey": "checkin", "prompt": "When do you arrive?"}},
            },
            {"id": "next", "type": "message", "data": {}},
        ],
        "edges": [{"id": "e", "source": "checkin", "target": "next"}],
    }
    state = SimulationState(
        tool_id="may-date-collection-test",
        tool_name="Booking",
        executor=FlowExecutor(parse_flow_config(config)),
        model="gpt-4o-mini",
    )
    client = MagicMock()
    client.chat.completions.create.side_effect = [
        _tool_call_response("collect_checkin", {"checkin": "2027-05-05"}),
        _text_response("Thanks."),
    ]
    monkeypatch.setattr(simulation, "openai_client", client)

    await _process_with_llm(state, "May 5")

    request = client.chat.completions.create.call_args_list[0].kwargs
    assert request["tool_choice"]["function"]["name"] == "collect_checkin"
    assert state.executor.state.get_variable("checkin") == "2027-05-05"


@pytest.mark.asyncio
async def test_name_starting_with_will_is_collected(monkeypatch):
    """A person's name must not be mistaken for a future-tense question."""
    import botelier.api.simulation as simulation

    config = {
        "initial_node": "guest_name",
        "variables": [{"key": "guest_name", "type": "text", "description": "guest name"}],
        "nodes": [
            {
                "id": "guest_name",
                "type": "collect_slot",
                "data": {"slot": {"variableKey": "guest_name", "prompt": "What is your name?"}},
            },
            {"id": "next", "type": "message", "data": {}},
        ],
        "edges": [{"id": "e", "source": "guest_name", "target": "next"}],
    }
    state = SimulationState(
        tool_id="name-collection-guard-test",
        tool_name="Booking",
        executor=FlowExecutor(parse_flow_config(config)),
        model="gpt-4o-mini",
    )
    client = MagicMock()
    client.chat.completions.create.side_effect = [
        _tool_call_response("collect_guest_name", {"guest_name": "Will Smith"}),
        _text_response("Thanks, Will."),
    ]
    monkeypatch.setattr(simulation, "openai_client", client)

    await _process_with_llm(state, "Will Smith")

    request = client.chat.completions.create.call_args_list[0].kwargs
    assert request["tool_choice"]["function"]["name"] == "collect_guest_name"
    assert state.executor.state.get_variable("guest_name") == "Will Smith"


@pytest.mark.asyncio
async def test_collect_form_keeps_multi_value_reply_behavior(monkeypatch):
    """Form replies can continue to save several supplied values in one turn."""
    import botelier.api.simulation as simulation

    config = {
        "initial_node": "guest_details",
        "variables": [
            {"key": "guest_name", "type": "text", "description": "guest name"},
            {"key": "adults", "type": "number", "description": "number of adults"},
        ],
        "nodes": [
            {
                "id": "guest_details",
                "type": "collect_form",
                "data": {
                    "slots": [
                        {"variableKey": "guest_name", "prompt": "What is your name?", "order": 1},
                        {"variableKey": "adults", "prompt": "How many adults?", "order": 2},
                    ]
                },
            },
            {"id": "next", "type": "message", "data": {}},
        ],
        "edges": [{"id": "e", "source": "guest_details", "target": "next"}],
    }
    state = SimulationState(
        tool_id="form-collection-guard-test",
        tool_name="Booking",
        executor=FlowExecutor(parse_flow_config(config)),
        model="gpt-4o-mini",
    )
    client = MagicMock()
    client.chat.completions.create.side_effect = [
        _multiple_tool_calls_response(
            [
                ("collect_guest_name", {"guest_name": "Will Smith"}),
                ("collect_adults", {"adults": 2}),
            ]
        ),
        _text_response("Thanks, Will."),
    ]
    monkeypatch.setattr(simulation, "openai_client", client)

    await _process_with_llm(state, "Will Smith, two adults")

    request = client.chat.completions.create.call_args_list[0].kwargs
    assert request["tool_choice"] == "auto"
    assert state.executor.state.get_variable("guest_name") == "Will Smith"
    assert state.executor.state.get_variable("adults") == 2


@pytest.mark.asyncio
async def test_direct_answer_does_not_force_the_following_slot(monkeypatch):
    """One reply may collect its active slot, never a later sequential field."""
    import botelier.api.simulation as simulation

    config = {
        "initial_node": "adults",
        "variables": [
            {"key": "adults", "type": "number", "description": "number of adults"},
            {"key": "checkin", "type": "date", "description": "check-in date"},
        ],
        "nodes": [
            {
                "id": "adults",
                "type": "collect_slot",
                "data": {"slot": {"variableKey": "adults", "prompt": "How many adults?"}},
            },
            {
                "id": "checkin",
                "type": "collect_slot",
                "data": {"slot": {"variableKey": "checkin", "prompt": "When do you arrive?"}},
            },
        ],
        "edges": [{"id": "e", "source": "adults", "target": "checkin"}],
    }
    state = SimulationState(
        tool_id="sequential-collection-guard-test",
        tool_name="Booking",
        executor=FlowExecutor(parse_flow_config(config)),
        model="gpt-4o-mini",
    )
    client = MagicMock()
    client.chat.completions.create.side_effect = [
        _tool_call_response("collect_adults", {"adults": 2}),
        _text_response("When do you arrive?"),
    ]
    monkeypatch.setattr(simulation, "openai_client", client)

    await _process_with_llm(state, "two")

    first_request, second_request = [
        call.kwargs for call in client.chat.completions.create.call_args_list
    ]
    assert first_request["tool_choice"]["function"]["name"] == "collect_adults"
    assert second_request["tool_choice"] == "auto"
    assert state.executor.state.get_variable("adults") == 2
    assert state.executor.state.get_variable("checkin") is None
    assert state.executor.state.current_node_id == "checkin"


@pytest.mark.asyncio
async def test_invalid_direct_answer_uses_existing_retry_path(monkeypatch):
    """A non-question numeric reply still reaches validation and retry messaging."""
    import botelier.api.simulation as simulation

    state = _state()
    client = MagicMock()
    client.chat.completions.create.side_effect = [
        _tool_call_response("collect_adults", {"adults": "many"}),
        _text_response("Please provide a valid number."),
    ]
    monkeypatch.setattr(simulation, "openai_client", client)

    await _process_with_llm(state, "many")

    assert state.executor.state.get_variable("adults") is None
    assert state.executor.state.retry_count == 1