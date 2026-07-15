"""Simulator-path regression tests: CAPABILITY node in the flow simulator.

These guard the two untested failure modes in the simulator's
``_process_with_llm`` loop that would only show up on a real call:

  BUG 1 — per-iteration schema rebuild:
    If ``get_function_schemas()`` does not include the capability node's
    ``execute_<id>`` at the point the capability is current, the forced
    tool_choice names a function absent from the tool list → OpenAI 400,
    previously swallowed into a generic "I apologize" apology / stall.

  BUG 2 — forced-choice routing for CAPABILITY nodes:
    If CAPABILITY is not in the forced-choice node-type set in simulation.py,
    the LLM returns plain text instead of firing ``execute_<id>`` → the
    capability never runs and the flow never advances (stall).

Each test drives ``_process_with_llm`` directly (the same code path that
``POST /api/simulate/message`` calls) with:
  - A mocked OpenAI client whose first response returns the expected
    forced tool call and whose second response returns plain text to
    terminate the loop.
  - A mocked ``_handle_capability_request`` on the executor to avoid
    DB / network calls (those code paths are already covered by
    ``test_flow_capability_e2e.py``).

The assertions confirm the capability function was actually *called*
(``function_called == "execute_<id>"``), that no error field is set, and
that the result is not a generic apology — meaning the simulator correctly
forced the tool, dispatched through the executor, and surfaced the result.
"""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from botelier.api.simulation import SimulationState, _process_with_llm
from botelier.flow_executor import FlowExecutor, parse_flow_config


# ── Helpers ───────────────────────────────────────────────────────────────────


def _flow_with_capability(capability_name: str, node_id: str = "cap") -> dict:
    """Minimal flow: start → collect_slot → CAPABILITY → end."""
    return {
        "initial_node": "start",
        "variables": [
            {"key": "check_in_date", "type": "text", "description": "Check-in date"},
        ],
        "nodes": [
            {"id": "start", "type": "initial", "data": {}},
            {
                "id": "collect_checkin",
                "type": "collect_slot",
                "data": {
                    "slot": {
                        "variableKey": "check_in_date",
                        "prompt": "What date would you like to check in?",
                    }
                },
            },
            {
                "id": node_id,
                "type": "capability",
                "data": {
                    "name": "Search Availability",
                    "api": {
                        "apiSource": "capability",
                        "capability": capability_name,
                    },
                },
            },
            {"id": "end", "type": "end", "data": {}},
        ],
        "edges": [
            {"id": "e1", "source": "start", "target": "collect_checkin"},
            {"id": "e2", "source": "collect_checkin", "target": node_id},
            {"id": "e3", "source": node_id, "target": "end"},
        ],
    }


def _make_simulation_state(
    capability_name: str, node_id: str = "cap"
) -> SimulationState:
    """Build a ``SimulationState`` with the executor positioned at the
    capability node (slot already pre-filled to skip collection)."""
    config = _flow_with_capability(capability_name, node_id=node_id)
    executor = FlowExecutor(
        parse_flow_config(config),
        account_id="00000000-0000-0000-0000-000000000001",
        db_session=None,
    )
    executor.state.collected_slots["check_in_date"] = "2026-08-01"
    executor.state.current_node_id = node_id

    state = SimulationState(
        tool_id="tool-sim-test-001",
        executor=executor,
        tool_name="Test Flow",
        account_id="00000000-0000-0000-0000-000000000001",
        model="gpt-4o-mini",
    )
    return state


def _openai_tool_call_response(tool_name: str, arguments: dict | None = None) -> MagicMock:
    """Return a mock ``openai.chat.completions.create`` response containing
    one tool call.  Mirrors the shape the simulator's loop unpacks:
    ``response.choices[0].message.tool_calls[0].function.{name,arguments}``.
    """
    tool_call = MagicMock()
    tool_call.id = "tc_sim_test_001"
    tool_call.function.name = tool_name
    tool_call.function.arguments = json.dumps(arguments or {})

    message = MagicMock()
    message.tool_calls = [tool_call]
    message.content = None

    choice = MagicMock()
    choice.message = message

    response = MagicMock()
    response.choices = [choice]
    return response


def _openai_text_response(content: str = "The search is complete.") -> MagicMock:
    """Return a mock OpenAI response with plain text content (no tool calls).
    Used as the second LLM response in the loop to terminate iteration.
    """
    message = MagicMock()
    message.tool_calls = None
    message.content = content

    choice = MagicMock()
    choice.message = message

    response = MagicMock()
    response.choices = [choice]
    return response


def _successful_capability_result(node_id: str, next_node: str = "end") -> dict:
    """Fake ``_handle_capability_request`` return value.

    Mirrors what ``_handle_integration_api_request`` returns on success, which
    is the contract ``_handle_api_request`` expects from its delegates.
    """
    return {
        "success": True,
        "message": "Found 3 rooms available on your requested dates.",
        "voice_result": "I found 3 rooms available.",
        "action": None,
        "current_node_id": next_node,
        "thinking_message": "",
    }


# ── Per-iteration schema rebuild contract (pure, no DB) ───────────────────────


def test_capability_node_in_schema_when_current():
    """``get_function_schemas()`` exposes ``execute_<id>`` exactly when the
    capability node is the current node — this is the invariant the
    per-iteration rebuild relies on.
    """
    state = _make_simulation_state("search_availability", node_id="cap")
    schemas = state.executor.get_function_schemas()
    fn_names = {s.get("function", s)["name"] for s in schemas}
    assert "execute_cap" in fn_names, (
        "CAPABILITY node must expose execute_cap when it is the current node; "
        f"got: {fn_names}"
    )


def test_capability_node_not_in_schema_before_reached():
    """Before the capability is the current node, ``execute_<id>`` must not
    appear in the schemas — slot collection cannot be bypassed.
    """
    config = _flow_with_capability("search_availability", node_id="cap")
    executor = FlowExecutor(
        parse_flow_config(config),
        account_id="00000000-0000-0000-0000-000000000001",
        db_session=None,
    )
    schemas = executor.get_function_schemas()
    fn_names = {s.get("function", s)["name"] for s in schemas}
    assert "execute_cap" not in fn_names, (
        "execute_cap must not be exposed before the capability node is reached; "
        f"got: {fn_names}"
    )


# ── Simulator forced tool_choice path (pure, no DB, no OpenAI) ───────────────


@pytest.mark.asyncio
async def test_read_capability_simulator_dispatches_and_returns_result():
    """Full ``_process_with_llm`` round-trip for a read capability
    (``search_availability``).

    Verifies:
    - The mocked LLM receives the forced tool_choice for ``execute_cap``.
    - The function is dispatched through the executor's handler.
    - The result surfaces as ``function_called`` (not a stall / apology).
    - No ``error`` field is set.
    """
    state = _make_simulation_state("search_availability", node_id="cap")
    executor = state.executor

    # Patch _handle_capability_request so no DB or network is needed.
    # A successful result causes _handle_api_request to advance the node.
    cap_result = _successful_capability_result("cap", next_node="end")
    executor._handle_capability_request = AsyncMock(return_value=cap_result)

    # Two LLM responses:
    #   1st iteration: forced tool call → execute_cap fires
    #   2nd iteration: plain text → loop exits
    forced_response = _openai_tool_call_response("execute_cap", {"check_in_date": "2026-08-01"})
    text_response = _openai_text_response("I found 3 rooms available.")

    mock_client = MagicMock()
    mock_client.chat.completions.create.side_effect = [forced_response, text_response]

    import botelier.api.simulation as sim_module

    original_client = sim_module.openai_client
    sim_module.openai_client = mock_client
    try:
        result = await _process_with_llm(state, "I'd like to check availability.")
    finally:
        sim_module.openai_client = original_client

    # The capability must have been called — not a stall / apology.
    assert result.get("function_called") == "execute_cap", (
        f"Expected function_called='execute_cap', got: {result.get('function_called')!r}. "
        "This indicates the simulator did not force the tool_choice for the CAPABILITY node, "
        "or the per-iteration schema rebuild did not expose execute_cap."
    )
    assert result.get("error") is None, (
        f"Unexpected error in simulator result: {result.get('error')}"
    )
    assert result.get("is_ended") is False

    # The forced_response OpenAI call must have been made (not zero calls).
    assert mock_client.chat.completions.create.call_count >= 1, (
        "OpenAI was never called — the simulator loop exited before processing."
    )

    # Verify the executor's handler was actually dispatched.
    assert executor._handle_capability_request.called, (
        "_handle_capability_request was never invoked; the capability node "
        "was not dispatched through the executor."
    )


@pytest.mark.asyncio
async def test_mutating_capability_simulator_dispatches_and_returns_result():
    """Full ``_process_with_llm`` round-trip for a mutating capability
    (``book_reservation``).

    The ``mutating`` flag on the capability spec means the non-GET idempotency
    guard applies at the executor level. The simulator path must reach that
    guard — which means ``execute_book_cap`` must be forced and dispatched,
    not stalled.
    """
    state = _make_simulation_state("book_reservation", node_id="book_cap")
    executor = state.executor

    book_result = _successful_capability_result("book_cap", next_node="end")
    book_result["message"] = "Your reservation has been booked."
    executor._handle_capability_request = AsyncMock(return_value=book_result)

    forced_response = _openai_tool_call_response(
        "execute_book_cap",
        {"check_in_date": "2026-08-01", "guest_count": 2},
    )
    text_response = _openai_text_response("Your booking is confirmed.")

    mock_client = MagicMock()
    mock_client.chat.completions.create.side_effect = [forced_response, text_response]

    import botelier.api.simulation as sim_module

    original_client = sim_module.openai_client
    sim_module.openai_client = mock_client
    try:
        result = await _process_with_llm(state, "Please book the room.")
    finally:
        sim_module.openai_client = original_client

    assert result.get("function_called") == "execute_book_cap", (
        f"Expected function_called='execute_book_cap', got: {result.get('function_called')!r}. "
        "This indicates the simulator did not force the tool_choice for the mutating CAPABILITY "
        "node, or the per-iteration schema rebuild did not expose execute_book_cap."
    )
    assert result.get("error") is None, (
        f"Unexpected error in simulator result: {result.get('error')}"
    )
    assert executor._handle_capability_request.called


@pytest.mark.asyncio
async def test_capability_tool_choice_is_forced_in_llm_call():
    """Assert that the OpenAI call includes a forced ``tool_choice`` for the
    capability node's function name.

    This directly guards BUG 2: if CAPABILITY is absent from the forced-choice
    node-type set in simulation.py, ``tool_choice`` is ``"auto"`` and the LLM
    may return text instead of firing the capability.
    """
    state = _make_simulation_state("search_availability", node_id="cap")
    executor = state.executor

    cap_result = _successful_capability_result("cap")
    executor._handle_capability_request = AsyncMock(return_value=cap_result)

    forced_response = _openai_tool_call_response("execute_cap")
    text_response = _openai_text_response("Done.")

    mock_client = MagicMock()
    mock_client.chat.completions.create.side_effect = [forced_response, text_response]

    import botelier.api.simulation as sim_module

    original_client = sim_module.openai_client
    sim_module.openai_client = mock_client
    try:
        await _process_with_llm(state, "Check for availability.")
    finally:
        sim_module.openai_client = original_client

    # Inspect the first OpenAI call's tool_choice argument.
    first_call_kwargs = mock_client.chat.completions.create.call_args_list[0].kwargs
    tool_choice = first_call_kwargs.get("tool_choice")
    assert tool_choice == {"type": "function", "function": {"name": "execute_cap"}}, (
        f"Expected forced tool_choice={{'type': 'function', 'function': {{'name': 'execute_cap'}}}}, "
        f"got: {tool_choice!r}. "
        "The CAPABILITY node type must be in the forced-choice set in simulation.py, "
        "otherwise the LLM will return text instead of calling the capability."
    )


@pytest.mark.asyncio
async def test_schema_rebuild_exposes_capability_fn_when_forced():
    """Guard against the stale tool-list bug (BUG 1): the forced function name
    must appear in the tool list built for that same iteration.

    If the schema rebuild at the top of each iteration did not include the
    capability's ``execute_<id>``, the simulator would emit a forced
    ``tool_choice`` for a function not in ``tools`` → OpenAI 400.
    """
    state = _make_simulation_state("search_availability", node_id="cap")
    executor = state.executor

    # Record the ``tools`` list the simulator sends to OpenAI.
    recorded_tools: list = []

    cap_result = _successful_capability_result("cap")
    executor._handle_capability_request = AsyncMock(return_value=cap_result)

    forced_response = _openai_tool_call_response("execute_cap")
    text_response = _openai_text_response("Done.")

    def _capture_and_return(*args, **kwargs):
        recorded_tools.extend(kwargs.get("tools") or [])
        # Return tool_call on first call, text on subsequent.
        return forced_response if not recorded_tools[1:] else text_response

    mock_client = MagicMock()
    mock_client.chat.completions.create.side_effect = [forced_response, text_response]

    import botelier.api.simulation as sim_module

    original_client = sim_module.openai_client
    sim_module.openai_client = mock_client
    try:
        await _process_with_llm(state, "Check availability.")
    finally:
        sim_module.openai_client = original_client

    # Extract the tool names from the first OpenAI call.
    first_call_kwargs = mock_client.chat.completions.create.call_args_list[0].kwargs
    tools_sent = first_call_kwargs.get("tools") or []
    tool_names_sent = {t["function"]["name"] for t in tools_sent if t.get("function")}

    assert "execute_cap" in tool_names_sent, (
        f"execute_cap was not in the tool list sent to OpenAI (got: {tool_names_sent}). "
        "The per-iteration schema rebuild must include the capability node's execute_<id> "
        "so the forced tool_choice is always valid and does not produce an OpenAI 400."
    )
