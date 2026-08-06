"""Simulator-path tests: MCP (Model Context Protocol) tool support (Task #459).

These guard the simulator's MCP integration, which must mirror the live
voice/SMS channels: the simulator resolves the assistant's linked MCP
connection, gates it on ownership + active/connected state, discovers the
assistant's *enabled* tools through the existing async ``MCPClient``, merges
those tools into the LLM's exposed tool list (native flow / capability /
dynamic-operation names WIN any collision), executes MCP calls over the open
session, and closes the session on simulation end / start failure.

All tests are pure — no real DB, no real MCP server, no OpenAI. The DB is a
``MagicMock`` returning a stub ``MCPConnection``; the async ``MCPClient`` is
patched so ``connect`` / ``discover_tools`` / ``execute_tool`` / ``disconnect``
are deterministic.
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import botelier.api.simulation as sim_module
from botelier.api.simulation import (
    SimulationState,
    _capability_and_dynamic_names,
    _close_session_mcp,
    _connect_and_discover_mcp_tools,
    _execute_sim_mcp_tool,
    _process_with_llm,
    simulate_message,
    SimulateMessageRequest,
)
from botelier.flow_executor import FlowExecutor, parse_flow_config
from botelier.models.mcp_connection import MCPConnectionStatus

ACCOUNT_ID = "00000000-0000-0000-0000-000000000001"
OTHER_ACCOUNT_ID = "00000000-0000-0000-0000-000000000099"


# ── Helpers ───────────────────────────────────────────────────────────────────


def _simple_flow() -> dict:
    return {
        "initial_node": "start",
        "variables": [
            {"key": "name", "type": "text", "description": "Caller name"},
        ],
        "nodes": [
            {"id": "start", "type": "initial", "data": {}},
            {
                "id": "collect_name",
                "type": "collect_slot",
                "data": {"slot": {"variableKey": "name", "prompt": "Your name?"}},
            },
            {"id": "end", "type": "end", "data": {}},
        ],
        "edges": [
            {"id": "e1", "source": "start", "target": "collect_name"},
            {"id": "e2", "source": "collect_name", "target": "end"},
        ],
    }


def _make_state(mcp_client=None, mcp_schemas=None) -> SimulationState:
    executor = FlowExecutor(
        parse_flow_config(_simple_flow()),
        account_id=ACCOUNT_ID,
        db_session=None,
    )
    return SimulationState(
        tool_id="tool-mcp-test-001",
        executor=executor,
        tool_name="Test Flow",
        account_id=ACCOUNT_ID,
        model="gpt-4o-mini",
        session_id="sess-mcp-001",
        mcp_client=mcp_client,
        mcp_schemas=mcp_schemas or [],
    )


def _stub_assistant(connection_id="conn-1", enabled_tools=None):
    assistant = MagicMock()
    assistant.id = "asst-1"
    assistant.account_id = ACCOUNT_ID
    assistant.mcp_connection_id = connection_id
    assistant.mcp_enabled_tools = (
        enabled_tools if enabled_tools is not None else ["weather", "search"]
    )
    return assistant


def _stub_connection(
    account_id=ACCOUNT_ID,
    is_active=True,
    status=MCPConnectionStatus.CONNECTED,
):
    conn = MagicMock()
    conn.id = "conn-1"
    conn.account_id = account_id
    conn.is_active = is_active
    conn.status = status
    conn.server_url = "https://mcp.example.com/sse"
    conn.credentials_encrypted = None
    conn.transport_type = MagicMock(value="sse")
    conn.auth_type = MagicMock(value="none")
    conn.get_connection_config = MagicMock(return_value={})
    conn.get_credentials = MagicMock(return_value={})
    return conn


def _db_returning(conn):
    """MagicMock DB whose query(...).filter(...).first() returns ``conn``."""
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = conn
    return db


def _patched_mcp_client(discovered, connect_ok=True, connect_error=None):
    """Return a factory patch for ``MCPClient`` that yields a mocked instance."""
    instance = MagicMock()
    instance.connect = AsyncMock(return_value=(connect_ok, connect_error))
    instance.discover_tools = AsyncMock(return_value=discovered)
    instance.disconnect = AsyncMock()
    instance.execute_tool = AsyncMock(
        return_value={"result": "ok", "success": True}
    )
    return instance


def _mcp_tool_def(name, description=None, properties=None):
    """A discovered-tool dict as returned by MCPClient.discover_tools()."""
    return {
        "name": name,
        "description": description or f"Execute {name}",
        "parameters": {
            "type": "object",
            "properties": properties or {},
            "required": [],
        },
        "source": "mcp",
    }


def _openai_tool_call_response(tool_name, arguments=None):
    tool_call = MagicMock()
    tool_call.id = "tc_mcp_001"
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


def _openai_text_response(content="Done."):
    message = MagicMock()
    message.tool_calls = None
    message.content = content
    choice = MagicMock()
    choice.message = message
    response = MagicMock()
    response.choices = [choice]
    return response


# ── _capability_and_dynamic_names ─────────────────────────────────────────────


def test_capability_and_dynamic_names_collects_all():
    caps = [{"type": "function", "function": {"name": "search_availability"}}]
    dyns = [{"type": "function", "function": {"name": "create_ticket"}}]
    names = _capability_and_dynamic_names(caps, dyns)
    assert names == {"search_availability", "create_ticket"}


def test_capability_and_dynamic_names_handles_none():
    assert _capability_and_dynamic_names(None, None) == set()


# ── Connect + discover: happy path ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_connect_discovers_enabled_tools_only():
    """Only tools in the assistant's mcp_enabled_tools are exposed."""
    assistant = _stub_assistant(enabled_tools=["weather"])
    conn = _stub_connection()
    db = _db_returning(conn)
    instance = _patched_mcp_client(
        [_mcp_tool_def("weather"), _mcp_tool_def("search"), _mcp_tool_def("delete")]
    )

    with patch(
        "botelier.services.mcp_client.MCPClient", return_value=instance
    ):
        client, schemas = await _connect_and_discover_mcp_tools(
            db, assistant, ACCOUNT_ID, native_tool_names=set()
        )

    assert client is instance
    names = {s["function"]["name"] for s in schemas}
    assert names == {"weather"}, f"Only enabled tools exposed; got {names}"
    instance.connect.assert_awaited_once()
    instance.discover_tools.assert_awaited_once()
    instance.disconnect.assert_not_awaited()


@pytest.mark.asyncio
async def test_connect_native_names_win_collision():
    """A discovered MCP tool colliding with a native name is dropped."""
    assistant = _stub_assistant(enabled_tools=["weather", "collect_name"])
    conn = _stub_connection()
    db = _db_returning(conn)
    instance = _patched_mcp_client(
        [_mcp_tool_def("weather"), _mcp_tool_def("collect_name")]
    )

    with patch(
        "botelier.services.mcp_client.MCPClient", return_value=instance
    ):
        client, schemas = await _connect_and_discover_mcp_tools(
            db,
            assistant,
            ACCOUNT_ID,
            native_tool_names={"collect_name"},
        )

    names = {s["function"]["name"] for s in schemas}
    assert "collect_name" not in names, "Native name must win the collision"
    assert names == {"weather"}


@pytest.mark.asyncio
async def test_connect_schema_shape_is_openai_function():
    assistant = _stub_assistant(enabled_tools=["weather"])
    conn = _stub_connection()
    db = _db_returning(conn)
    instance = _patched_mcp_client(
        [_mcp_tool_def("weather", "Get weather", {"city": {"type": "string"}})]
    )

    with patch(
        "botelier.services.mcp_client.MCPClient", return_value=instance
    ):
        _client, schemas = await _connect_and_discover_mcp_tools(
            db, assistant, ACCOUNT_ID, native_tool_names=set()
        )

    assert len(schemas) == 1
    s = schemas[0]
    assert s["type"] == "function"
    assert s["function"]["name"] == "weather"
    assert s["function"]["description"] == "Get weather"
    assert s["function"]["parameters"]["properties"] == {"city": {"type": "string"}}


# ── Gating: ownership + active + connected + no-connection ─────────────────────


@pytest.mark.asyncio
async def test_connect_no_assistant_returns_none():
    client, schemas = await _connect_and_discover_mcp_tools(
        MagicMock(), None, ACCOUNT_ID, native_tool_names=set()
    )
    assert client is None and schemas == []


@pytest.mark.asyncio
async def test_connect_no_mcp_connection_id_returns_none():
    assistant = _stub_assistant(connection_id=None)
    client, schemas = await _connect_and_discover_mcp_tools(
        MagicMock(), assistant, ACCOUNT_ID, native_tool_names=set()
    )
    assert client is None and schemas == []


@pytest.mark.asyncio
async def test_connect_cross_tenant_connection_rejected():
    """A connection owned by another account must not be used (ownership)."""
    assistant = _stub_assistant()
    conn = _stub_connection(account_id=OTHER_ACCOUNT_ID)
    db = _db_returning(conn)
    instance = _patched_mcp_client([_mcp_tool_def("weather")])

    with patch(
        "botelier.services.mcp_client.MCPClient", return_value=instance
    ):
        client, schemas = await _connect_and_discover_mcp_tools(
            db, assistant, ACCOUNT_ID, native_tool_names=set()
        )

    assert client is None and schemas == []
    instance.connect.assert_not_awaited()


@pytest.mark.asyncio
async def test_connect_inactive_connection_rejected():
    """is_active=False filters at the query level → no connection found."""
    assistant = _stub_assistant()
    db = _db_returning(None)  # filter includes is_active == True → returns None

    client, schemas = await _connect_and_discover_mcp_tools(
        db, assistant, ACCOUNT_ID, native_tool_names=set()
    )
    assert client is None and schemas == []


@pytest.mark.asyncio
async def test_connect_not_connected_status_rejected():
    assistant = _stub_assistant()
    conn = _stub_connection(status=MCPConnectionStatus.ERROR)
    db = _db_returning(conn)
    instance = _patched_mcp_client([_mcp_tool_def("weather")])

    with patch(
        "botelier.services.mcp_client.MCPClient", return_value=instance
    ):
        client, schemas = await _connect_and_discover_mcp_tools(
            db, assistant, ACCOUNT_ID, native_tool_names=set()
        )

    assert client is None and schemas == []
    instance.connect.assert_not_awaited()


@pytest.mark.asyncio
async def test_connect_no_enabled_tools_returns_none():
    assistant = _stub_assistant(enabled_tools=[])
    conn = _stub_connection()
    db = _db_returning(conn)

    client, schemas = await _connect_and_discover_mcp_tools(
        db, assistant, ACCOUNT_ID, native_tool_names=set()
    )
    assert client is None and schemas == []


# ── Failure handling: connect / discover failures close the client ─────────────


@pytest.mark.asyncio
async def test_connect_failure_closes_client_and_degrades():
    assistant = _stub_assistant()
    conn = _stub_connection()
    db = _db_returning(conn)
    instance = _patched_mcp_client(
        [], connect_ok=False, connect_error="handshake failed"
    )

    with patch(
        "botelier.services.mcp_client.MCPClient", return_value=instance
    ):
        client, schemas = await _connect_and_discover_mcp_tools(
            db, assistant, ACCOUNT_ID, native_tool_names=set()
        )

    assert client is None and schemas == []
    instance.disconnect.assert_awaited()


@pytest.mark.asyncio
async def test_discovery_exception_closes_client_and_degrades():
    assistant = _stub_assistant()
    conn = _stub_connection()
    db = _db_returning(conn)
    instance = _patched_mcp_client([_mcp_tool_def("weather")])
    instance.discover_tools = AsyncMock(side_effect=RuntimeError("boom"))

    with patch(
        "botelier.services.mcp_client.MCPClient", return_value=instance
    ):
        client, schemas = await _connect_and_discover_mcp_tools(
            db, assistant, ACCOUNT_ID, native_tool_names=set()
        )

    assert client is None and schemas == []
    instance.disconnect.assert_awaited()


@pytest.mark.asyncio
async def test_no_enabled_tool_matches_closes_client():
    """Connection is valid but no enabled tool is discovered → close session."""
    assistant = _stub_assistant(enabled_tools=["weather"])
    conn = _stub_connection()
    db = _db_returning(conn)
    instance = _patched_mcp_client([_mcp_tool_def("something_else")])

    with patch(
        "botelier.services.mcp_client.MCPClient", return_value=instance
    ):
        client, schemas = await _connect_and_discover_mcp_tools(
            db, assistant, ACCOUNT_ID, native_tool_names=set()
        )

    assert client is None and schemas == []
    instance.disconnect.assert_awaited()


# ── Execution + dispatch through _process_with_llm ─────────────────────────────


@pytest.mark.asyncio
async def test_execute_sim_mcp_tool_dispatches_to_client():
    instance = _patched_mcp_client([])
    state = _make_state(mcp_client=instance, mcp_schemas=[])
    result = await _execute_sim_mcp_tool(state, "weather", {"city": "NYC"})
    assert result == {"result": "ok", "success": True}
    instance.execute_tool.assert_awaited_once_with("weather", {"city": "NYC"})


@pytest.mark.asyncio
async def test_execute_sim_mcp_tool_without_client_fails_closed():
    state = _make_state(mcp_client=None, mcp_schemas=[])
    result = await _execute_sim_mcp_tool(state, "weather", {})
    assert result["success"] is False
    assert "weather" in result["error"]


@pytest.mark.asyncio
async def test_process_with_llm_dispatches_mcp_tool():
    """The LLM calling an MCP tool routes to the MCP client, not the executor."""
    mcp_schemas = [
        {
            "type": "function",
            "function": {
                "name": "weather",
                "description": "Get weather",
                "parameters": {"type": "object", "properties": {}, "required": []},
            },
        }
    ]
    instance = _patched_mcp_client([])
    instance.execute_tool = AsyncMock(
        return_value={"result": "Sunny, 25C", "success": True}
    )
    state = _make_state(mcp_client=instance, mcp_schemas=mcp_schemas)

    # Executor should NOT be used for an MCP tool call.
    state.executor.handle_function_call = AsyncMock(
        side_effect=AssertionError("MCP tool must not hit the executor")
    )

    forced = _openai_tool_call_response("weather", {"city": "NYC"})
    text = _openai_text_response("It's sunny.")
    mock_client = MagicMock()
    mock_client.chat.completions.create.side_effect = [forced, text]

    original = sim_module.openai_client
    sim_module.openai_client = mock_client
    try:
        result = await _process_with_llm(state, "What's the weather in NYC?")
    finally:
        sim_module.openai_client = original

    assert result.get("function_called") == "weather"
    assert result.get("error") is None
    instance.execute_tool.assert_awaited_once_with("weather", {"city": "NYC"})

    # MCP schema must have been included in the tool list sent to OpenAI.
    first_kwargs = mock_client.chat.completions.create.call_args_list[0].kwargs
    tool_names = {
        t["function"]["name"] for t in (first_kwargs.get("tools") or []) if t.get("function")
    }
    assert "weather" in tool_names


# ── Teardown: close on simulation end ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_close_session_mcp_disconnects_and_clears():
    instance = _patched_mcp_client([])
    state = _make_state(mcp_client=instance)
    await _close_session_mcp(state)
    instance.disconnect.assert_awaited_once()
    assert state.mcp_client is None


@pytest.mark.asyncio
async def test_close_session_mcp_noop_without_client():
    state = _make_state(mcp_client=None)
    await _close_session_mcp(state)  # must not raise
    assert state.mcp_client is None


@pytest.mark.asyncio
async def test_close_session_mcp_swallows_disconnect_error():
    instance = _patched_mcp_client([])
    instance.disconnect = AsyncMock(side_effect=RuntimeError("already closed"))
    state = _make_state(mcp_client=instance)
    await _close_session_mcp(state)  # must not raise
    assert state.mcp_client is None


@pytest.mark.asyncio
async def test_natural_flow_end_closes_mcp_without_delete_request():
    """END/transfer responses release MCP even if the UI never deletes session."""
    instance = _patched_mcp_client([])
    state = _make_state(mcp_client=instance)
    state.executor.handle_function_call = AsyncMock(
        return_value={"action": "end", "message": "Goodbye"}
    )

    with patch.object(
        sim_module, "_get_session_and_check_access", return_value=state
    ):
        response = await simulate_message(
            request=SimulateMessageRequest(
                session_id=state.session_id,
                message="done",
                function_call="end_call_end",
                function_args={},
            ),
            db=MagicMock(),
            user=MagicMock(),
        )

    assert response.state["is_ended"] is True
    instance.disconnect.assert_awaited_once()
    assert state.mcp_client is None
