"""Contract tests for the MCP connection transport validation.

These tests lock in the supported-transport contract for the MCP connections
API (task #459):

  * Only ``sse`` and ``streamable_http`` are accepted for new/updated records.
  * Legacy enum values (``stdio``, ``http``, ``websocket``) still LOAD on the
    model (no destructive migration) but are REJECTED with a 400 on
    create/update.
  * Wrong-transport errors are actionable (name the allowed transports) and
    sanitized (never echo the raw attacker-controlled input verbatim).

The full HTTP stack is exercised via FastAPI's ``TestClient`` so routing,
dependency wiring, and Pydantic validation are all covered.
"""

import os
import ssl
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost/test")
os.environ.setdefault("NEXTAUTH_SECRET", "test-secret-for-testing-only")

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import botelier.api.mcp_connections as mcp_api
import httpx
from sqlalchemy.dialects import postgresql

from botelier.models.mcp_connection import MCPConnection
from botelier.services.mcp_client import MCPClient, _format_mcp_connection_error
from botelier.auth.middleware import get_current_user
from botelier.database import get_db
from botelier.models.mcp_connection import (
    SUPPORTED_MCP_TRANSPORTS,
    MCPConnection,
    MCPTransportType,
)

ACCOUNT_ID = str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _make_user():
    user = MagicMock()
    user.id = uuid.uuid4()
    user.user_type = "platform_admin"  # bypasses membership check
    user.is_active = True
    return user


def _build_client(db_override=None) -> TestClient:
    app = FastAPI()
    app.include_router(mcp_api.router)

    def _user():
        return _make_user()

    def _db():
        return db_override if db_override is not None else MagicMock()

    app.dependency_overrides[get_current_user] = _user
    app.dependency_overrides[get_db] = _db
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture(autouse=True)
def _skip_ssrf_url_validation(monkeypatch):
    """Bypass DNS/SSRF checks so tests don't hit the network."""
    monkeypatch.setattr(mcp_api, "_validate_mcp_server_url", lambda url: None)


# ---------------------------------------------------------------------------
# Model contract — legacy values still load, supported set is exact
# ---------------------------------------------------------------------------


def test_supported_transports_are_exactly_sse_and_streamable_http():
    assert set(SUPPORTED_MCP_TRANSPORTS) == {
        MCPTransportType.SSE,
        MCPTransportType.STREAMABLE_HTTP,
    }


def test_legacy_enum_values_still_load_on_model():
    """Legacy transports remain valid enum members (no destructive migration)."""
    for legacy in ("stdio", "http", "websocket"):
        # Constructing the enum must not raise — old rows must keep loading.
        assert MCPTransportType(legacy).value == legacy


# ---------------------------------------------------------------------------
# Create — supported vs unsupported
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("transport", ["sse", "streamable_http", "STREAMABLE_HTTP", " sse "])
def test_create_accepts_supported_transports(transport):
    db = MagicMock()
    db.add.return_value = None
    db.commit.return_value = None

    captured = {}

    def _refresh(conn):
        captured["conn"] = conn

    db.refresh.side_effect = _refresh

    client = _build_client(db_override=db)
    resp = client.post(
        "/api/mcp-connections",
        json={
            "account_id": ACCOUNT_ID,
            "name": "My Server",
            "server_url": "https://example.com/mcp",
            "transport_type": transport,
            "auth_type": "none",
        },
    )
    assert resp.status_code == 201, resp.text
    conn = captured["conn"]
    assert isinstance(conn, MCPConnection)
    assert conn.transport_type in SUPPORTED_MCP_TRANSPORTS


@pytest.mark.parametrize("legacy", ["stdio", "http", "websocket"])
def test_create_rejects_legacy_transports_with_actionable_error(legacy):
    client = _build_client()
    resp = client.post(
        "/api/mcp-connections",
        json={
            "account_id": ACCOUNT_ID,
            "name": "My Server",
            "server_url": "https://example.com/mcp",
            "transport_type": legacy,
            "auth_type": "none",
        },
    )
    assert resp.status_code == 400
    detail = resp.json()["detail"]
    # Actionable: names both supported transports.
    assert "sse" in detail and "streamable_http" in detail


def test_create_rejects_unknown_transport_sanitized():
    """Unknown/attacker-controlled transport must not be echoed verbatim."""
    payload_transport = "<script>alert(1)</script>"
    client = _build_client()
    resp = client.post(
        "/api/mcp-connections",
        json={
            "account_id": ACCOUNT_ID,
            "name": "My Server",
            "server_url": "https://example.com/mcp",
            "transport_type": payload_transport,
            "auth_type": "none",
        },
    )
    assert resp.status_code == 400
    detail = resp.json()["detail"]
    # Sanitized: the raw input is never reflected back.
    assert payload_transport not in detail
    assert "<script>" not in detail
    # Still actionable.
    assert "streamable_http" in detail and "sse" in detail


# ---------------------------------------------------------------------------
# Update — rejects unsupported transports too
# ---------------------------------------------------------------------------


def test_update_rejects_legacy_transport():
    connection_id = str(uuid.uuid4())
    existing = MagicMock(spec=MCPConnection)
    existing.account_id = ACCOUNT_ID

    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = existing

    client = _build_client(db_override=db)
    resp = client.put(
        f"/api/mcp-connections/{connection_id}",
        json={"transport_type": "websocket"},
    )
    assert resp.status_code == 400
    detail = resp.json()["detail"]
    assert "streamable_http" in detail and "sse" in detail


@pytest.mark.asyncio
@pytest.mark.parametrize("transport", ["stdio", "http", "websocket"])
async def test_direct_client_rejects_unsupported_transport_before_network(transport):
    """Runtime callers cannot bypass API validation and silently get SSE."""
    client = MCPClient(
        server_url="https://example.com/mcp",
        transport_type=transport,
    )
    success, error = await client.connect()
    assert success is False
    assert "Unsupported MCP transport" in error
    assert "streamable_http" in error and "sse" in error


def test_nested_taskgroup_tls_error_is_actionable():
    tls_error = ssl.SSLCertVerificationError(
        1, "certificate verify failed: unable to get local issuer certificate"
    )
    connect_error = httpx.ConnectError(
        "[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed"
    )
    connect_error.__cause__ = tls_error
    wrapped = ExceptionGroup(
        "unhandled errors in a TaskGroup",
        [connect_error],
    )

    message = _format_mcp_connection_error(wrapped)

    assert "TLS certificate verification failed" in message
    assert "Renew/fix" in message
    assert "TaskGroup" not in message


@pytest.mark.asyncio
async def test_streamable_http_preflight_surfaces_tls_error_before_mcp_taskgroup():
    client = MCPClient(
        server_url="https://expired.example/mcp",
        transport_type="streamable_http",
    )
    client._preflight_streamable_http = AsyncMock(
        side_effect=httpx.ConnectError(
            "[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed"
        )
    )
    tls_error = ssl.SSLCertVerificationError(1, "certificate has expired")
    client._preflight_streamable_http.side_effect.__cause__ = tls_error

    with patch(
        "mcp.client.streamable_http.streamablehttp_client"
    ) as transport_factory:
        success, error = await client.connect()

    assert success is False
    assert "TLS certificate verification failed" in error
    assert "TaskGroup" not in error
    transport_factory.assert_not_called()


def test_transport_enum_supports_legacy_labels_and_streamable_http_wire_value():
    transport_enum = MCPConnection.__table__.c.transport_type.type
    bind = transport_enum.bind_processor(postgresql.dialect())

    assert bind(MCPTransportType.SSE) == "SSE"
    assert bind(MCPTransportType.STREAMABLE_HTTP) == "streamable_http"


def test_sse_content_type_mismatch_recommends_streamable_http():
    error = Exception(
        "Expected response header Content-Type to contain 'text/event-stream', "
        "got 'application/json'"
    )

    assert _format_mcp_connection_error(error) == (
        "This server returned Streamable HTTP JSON instead of an SSE stream. "
        "Change the connection transport to 'Streamable HTTP' and test again."
    )
