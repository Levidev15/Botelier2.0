"""SMS MCP (Model Context Protocol) support tests — Task #459.

SMS mirrors the voice + simulator channels: an assistant may link one
account-owned MCP connection whose remote tools are exposed to the LLM for a
single incoming-message turn, then torn down. These tests cover the SMS-specific
wiring in ``botelier.services.sms_service.SMSService``:

  * Enforcement — the connection must be owned by the assistant's account, be
    active, and have status CONNECTED, or no MCP tools are exposed (fail-closed).
  * Enabled-tools filtering — only tools in ``assistant.mcp_enabled_tools`` are
    exposed, using the connection's discovered-tools cache.
  * Native-name collisions — a native platform tool always wins; the colliding
    MCP tool is dropped and never routed.
  * Transport gating — only SSE / streamable_http are used (the shared
    MCPClient's supported transports).
  * Per-turn lifecycle — the async MCPClient is opened and closed within one
    turn, and execution routes through the client.
  * Loop safety — ``_run_async`` never calls ``asyncio.run`` on a thread that
    already owns a running event loop.

These are pure-logic + mock tests (no DB, no network): the DB session and the
async ``MCPClient`` are mocked, so the suite is fast and deterministic.
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from botelier.models.mcp_connection import (
    MCPAuthType,
    MCPConnectionStatus,
    MCPTransportType,
)
from botelier.services.sms_service import SMSService


# ── Helpers ──────────────────────────────────────────────────────────────────


ACCOUNT_ID = "acct-1"


def _make_service() -> SMSService:
    return SMSService(db=MagicMock())


def _make_assistant(
    account_id=ACCOUNT_ID,
    mcp_connection_id="conn-1",
    mcp_enabled_tools=None,
):
    return SimpleNamespace(
        account_id=account_id,
        mcp_connection_id=mcp_connection_id,
        mcp_enabled_tools=mcp_enabled_tools if mcp_enabled_tools is not None else [],
    )


def _make_connection(
    id="conn-1",
    account_id=ACCOUNT_ID,
    is_active=True,
    status=MCPConnectionStatus.CONNECTED,
    transport=MCPTransportType.SSE,
    auth=MCPAuthType.NONE,
    discovered=None,
    server_url="https://mcp.example.invalid/sse",
    credentials=None,
    connection_config=None,
):
    conn = MagicMock()
    conn.id = id
    conn.account_id = account_id
    conn.name = "Test MCP"
    conn.is_active = is_active
    conn.status = status
    conn.transport_type = transport
    conn.auth_type = auth
    conn.server_url = server_url
    conn.get_discovered_tools.return_value = discovered or []
    conn.get_credentials.return_value = credentials or {}
    conn.get_connection_config.return_value = connection_config or {}
    return conn


def _bind_connection(service: SMSService, conn):
    """Wire the mocked db so _load_mcp_connection returns ``conn``."""
    query = service.db.query.return_value
    query.filter.return_value.first.return_value = conn


TWO_TOOLS = [
    {
        "name": "search_docs",
        "description": "Search internal docs",
        "parameters": {
            "type": "object",
            "properties": {"q": {"type": "string"}},
            "required": ["q"],
        },
    },
    {
        "name": "create_ticket",
        "description": "Create a support ticket",
        "parameters": {
            "type": "object",
            "properties": {"title": {"type": "string"}},
            "required": ["title"],
        },
    },
]


# ── Enforcement: ownership + active + connected ──────────────────────────────


def test_no_connection_id_returns_no_schemas():
    svc = _make_service()
    assistant = _make_assistant(mcp_connection_id=None)
    schemas = svc._open_mcp_for_turn(assistant, native_names=set())
    assert schemas == []
    assert svc._mcp_tool_names == set()
    assert svc._mcp_client is None


def test_connection_not_found_returns_none():
    svc = _make_service()
    _bind_connection(svc, None)
    assert svc._load_mcp_connection(_make_assistant()) is None


def test_cross_account_connection_rejected():
    svc = _make_service()
    conn = _make_connection(account_id="OTHER-ACCT")
    _bind_connection(svc, conn)
    # Ownership enforcement: connection belongs to a different account.
    assert svc._load_mcp_connection(_make_assistant(account_id=ACCOUNT_ID)) is None


def test_inactive_connection_rejected():
    svc = _make_service()
    _bind_connection(svc, _make_connection(is_active=False))
    assert svc._load_mcp_connection(_make_assistant()) is None


@pytest.mark.parametrize(
    "status",
    [
        MCPConnectionStatus.DISCONNECTED,
        MCPConnectionStatus.CONNECTING,
        MCPConnectionStatus.ERROR,
    ],
)
def test_non_connected_status_rejected(status):
    svc = _make_service()
    _bind_connection(svc, _make_connection(status=status))
    assert svc._load_mcp_connection(_make_assistant()) is None


def test_connected_owned_active_connection_accepted():
    svc = _make_service()
    conn = _make_connection()
    _bind_connection(svc, conn)
    assert svc._load_mcp_connection(_make_assistant()) is conn


# ── Enabled-tools filtering ──────────────────────────────────────────────────


def test_only_enabled_tools_are_exposed():
    svc = _make_service()
    conn = _make_connection(discovered=TWO_TOOLS)
    # Only "search_docs" is enabled → "create_ticket" must not appear.
    schemas = svc._build_mcp_schemas(conn, ["search_docs"], native_names=set())
    names = {s["function"]["name"] for s in schemas}
    assert names == {"search_docs"}
    assert svc._mcp_tool_names == {"search_docs"}


def test_no_enabled_tools_yields_nothing():
    svc = _make_service()
    conn = _make_connection(discovered=TWO_TOOLS)
    _bind_connection(svc, conn)
    assistant = _make_assistant(mcp_enabled_tools=[])
    assert svc._open_mcp_for_turn(assistant, native_names=set()) == []
    assert svc._mcp_client is None


def test_enabled_tool_missing_from_discovery_is_skipped():
    svc = _make_service()
    conn = _make_connection(discovered=TWO_TOOLS)
    schemas = svc._build_mcp_schemas(conn, ["does_not_exist"], native_names=set())
    assert schemas == []
    assert svc._mcp_tool_names == set()


def test_schema_shape_is_openai_function():
    svc = _make_service()
    conn = _make_connection(discovered=TWO_TOOLS)
    schemas = svc._build_mcp_schemas(conn, ["search_docs"], native_names=set())
    fn = schemas[0]
    assert fn["type"] == "function"
    assert fn["function"]["name"] == "search_docs"
    assert fn["function"]["parameters"]["required"] == ["q"]


# ── Native-name collisions: native wins ──────────────────────────────────────


def test_native_tool_wins_name_collision():
    svc = _make_service()
    conn = _make_connection(discovered=TWO_TOOLS)
    # "search_docs" collides with a native platform tool → MCP one is dropped.
    schemas = svc._build_mcp_schemas(
        conn, ["search_docs", "create_ticket"], native_names={"search_docs"}
    )
    names = {s["function"]["name"] for s in schemas}
    assert names == {"create_ticket"}
    # The colliding name must NOT be routable to MCP.
    assert "search_docs" not in svc._mcp_tool_names
    assert svc._mcp_tool_names == {"create_ticket"}


# ── Transport gating ─────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "transport",
    [MCPTransportType.STDIO, MCPTransportType.WEBSOCKET, MCPTransportType.HTTP],
)
def test_unsupported_transport_skips_mcp(monkeypatch, transport):
    svc = _make_service()
    conn = _make_connection(transport=transport, discovered=TWO_TOOLS)
    _bind_connection(svc, conn)

    # Guard: MCPClient must never even be constructed for unsupported transports.
    import botelier.services.mcp_client as mcp_mod

    monkeypatch.setattr(
        mcp_mod, "MCPClient", MagicMock(side_effect=AssertionError("should not construct"))
    )

    assistant = _make_assistant(mcp_enabled_tools=["search_docs"])
    assert svc._open_mcp_for_turn(assistant, native_names=set()) == []
    assert svc._mcp_client is None
    assert svc._mcp_tool_names == set()


@pytest.mark.parametrize(
    "transport", [MCPTransportType.SSE, MCPTransportType.STREAMABLE_HTTP]
)
def test_supported_transport_opens_client(monkeypatch, transport):
    svc = _make_service()
    conn = _make_connection(transport=transport, discovered=TWO_TOOLS, auth=MCPAuthType.NONE)
    _bind_connection(svc, conn)

    fake_client = MagicMock()

    async def _connect(*a, **k):
        return True, None

    async def _disconnect(*a, **k):
        return None

    fake_client.connect.side_effect = _connect
    fake_client.disconnect.side_effect = _disconnect

    import botelier.services.mcp_client as mcp_mod

    ctor = MagicMock(return_value=fake_client)
    monkeypatch.setattr(mcp_mod, "MCPClient", ctor)

    assistant = _make_assistant(mcp_enabled_tools=["search_docs", "create_ticket"])
    schemas = svc._open_mcp_for_turn(assistant, native_names=set())

    assert {s["function"]["name"] for s in schemas} == {"search_docs", "create_ticket"}
    assert svc._mcp_client is fake_client
    # Constructed with the connection's transport value.
    _, kwargs = ctor.call_args
    assert kwargs["transport_type"] == transport.value


# ── Per-turn lifecycle + execution routing ───────────────────────────────────


def test_execute_mcp_tool_routes_to_client():
    svc = _make_service()
    fake_client = MagicMock()

    async def _exec(name, args):
        return {"result": f"{name}:{args.get('q')}", "success": True}

    fake_client.execute_tool.side_effect = _exec
    svc._mcp_client = fake_client
    svc._mcp_tool_names = {"search_docs"}

    out = svc._execute_mcp_tool("search_docs", {"q": "hi"})
    assert out == {"result": "search_docs:hi", "success": True}


def test_execute_mcp_tool_without_client_errors():
    svc = _make_service()
    svc._mcp_client = None
    out = svc._execute_mcp_tool("search_docs", {})
    assert out["status"] == "failed"


def test_execute_tool_dispatches_mcp_name(monkeypatch):
    svc = _make_service()
    svc._mcp_tool_names = {"search_docs"}
    called = {}

    def _fake(name, args):
        called["name"] = name
        return {"ok": True}

    monkeypatch.setattr(svc, "_execute_mcp_tool", _fake)
    # _execute_tool must route an MCP-owned name straight to the MCP path,
    # never touching the DB tool lookups.
    result = svc._execute_tool(_make_assistant(), "search_docs", {"q": "x"})
    assert result == {"ok": True}
    assert called["name"] == "search_docs"


def test_close_mcp_for_turn_disconnects_and_clears():
    svc = _make_service()
    fake_client = MagicMock()
    disconnected = {"n": 0}

    async def _disconnect():
        disconnected["n"] += 1

    fake_client.disconnect.side_effect = _disconnect
    svc._mcp_client = fake_client
    svc._mcp_tool_names = {"search_docs"}

    svc._close_mcp_for_turn()
    assert disconnected["n"] == 1
    assert svc._mcp_client is None
    assert svc._mcp_tool_names == set()


def test_close_mcp_for_turn_noop_without_client():
    svc = _make_service()
    svc._mcp_client = None
    # Must not raise.
    svc._close_mcp_for_turn()
    assert svc._mcp_client is None


def test_failed_connect_closes_and_exposes_nothing(monkeypatch):
    svc = _make_service()
    conn = _make_connection(discovered=TWO_TOOLS)
    _bind_connection(svc, conn)

    fake_client = MagicMock()
    disconnected = {"n": 0}

    async def _connect(*a, **k):
        return False, "boom"

    async def _disconnect(*a, **k):
        disconnected["n"] += 1

    fake_client.connect.side_effect = _connect
    fake_client.disconnect.side_effect = _disconnect

    import botelier.services.mcp_client as mcp_mod

    monkeypatch.setattr(mcp_mod, "MCPClient", MagicMock(return_value=fake_client))

    assistant = _make_assistant(mcp_enabled_tools=["search_docs"])
    schemas = svc._open_mcp_for_turn(assistant, native_names=set())

    assert schemas == []
    assert svc._mcp_client is None
    assert svc._mcp_tool_names == set()
    assert disconnected["n"] == 1  # a failed connect still cleans up


# ── Loop safety: never asyncio.run on a running loop ─────────────────────────


def test_run_async_no_running_loop():
    svc = _make_service()

    async def _coro():
        return 42

    assert svc._run_async(_coro()) == 42


def test_run_async_inside_running_loop():
    """When a loop is already running on the thread, _run_async must offload to a
    fresh-loop worker thread instead of calling asyncio.run (which would raise
    'asyncio.run() cannot be called from a running event loop')."""
    svc = _make_service()

    async def _outer():
        async def _inner():
            return "ran-safely"

        # We are inside a running loop here; _run_async must not blow up.
        return svc._run_async(_inner())

    assert asyncio.run(_outer()) == "ran-safely"
