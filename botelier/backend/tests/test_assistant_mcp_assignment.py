"""Assistant MCP assignment must be account-owned and runtime-usable."""

from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from botelier.api.assistants import _validate_assistant_mcp_connection
from botelier.models.mcp_connection import MCPConnectionStatus, MCPTransportType


def _db_returning(connection):
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = connection
    return db


def _connection(
    *,
    status=MCPConnectionStatus.CONNECTED,
    transport=MCPTransportType.SSE,
):
    connection = MagicMock()
    connection.status = status
    connection.transport_type = transport
    return connection


def test_assignment_accepts_connected_supported_connection():
    _validate_assistant_mcp_connection(
        _db_returning(_connection()), "account-1", "connection-1"
    )


@pytest.mark.parametrize(
    ("connection", "detail"),
    [
        (None, "not found for this account"),
        (_connection(status=MCPConnectionStatus.ERROR), "must be connected"),
        (_connection(transport=MCPTransportType.WEBSOCKET), "SSE or Streamable HTTP"),
    ],
)
def test_assignment_rejects_unusable_connection(connection, detail):
    with pytest.raises(HTTPException) as exc:
        _validate_assistant_mcp_connection(
            _db_returning(connection), "account-1", "connection-1"
        )
    assert exc.value.status_code == 400
    assert detail in exc.value.detail