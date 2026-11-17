"""Backend authorization and typing for trusted native MCP grants."""

from types import SimpleNamespace
from copy import deepcopy
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


ACCOUNT_ID = str(uuid4())
PROPERTY_ID = str(uuid4())
CONNECTION_ID = str(uuid4())


class _Membership:
    is_active = True

    def __init__(self, account_id, permissions):
        self.account_id = account_id
        self.permissions = set(permissions)

    def has_permission(self, permission):
        return permission in self.permissions


class _Query:
    def __init__(self, db, model):
        self.db = db
        self.model = model

    def filter(self, *criteria):
        return self

    def first(self):
        model_name = self.model.__name__
        if model_name == "AccountMembership":
            return self.db.membership
        if model_name == "Property":
            return self.db.property
        if model_name == "MCPConnection":
            return self.db.connection
        return None


class _DB:
    def __init__(self, permissions, *, connection=None, property_row=None):
        self.membership = _Membership(ACCOUNT_ID, permissions)
        self.property = property_row or SimpleNamespace(
            id=PROPERTY_ID, account_id=ACCOUNT_ID, is_active=True,
        )
        self.connection = connection
        self.added = []
        self.commits = 0

    def query(self, model):
        return _Query(self, model)

    def add(self, row):
        self.added.append(row)

    def commit(self):
        self.commits += 1

    def refresh(self, row):
        row.id = getattr(row, "id", None) or CONNECTION_ID


def _user(permissions=("integrations.view",)):
    return SimpleNamespace(
        id=uuid4(), is_platform_admin=False,
        account_memberships=[_Membership(ACCOUNT_ID, permissions)],
    )


def _client(monkeypatch, db, user):
    from botelier.api import mcp_connections
    from botelier.auth.middleware import get_current_user
    from botelier.database import get_db

    monkeypatch.setattr(
        mcp_connections, "_validate_mcp_server_url", lambda _url: None,
    )
    app = FastAPI()
    app.include_router(mcp_connections.router)
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_db] = lambda: db
    return TestClient(app, raise_server_exceptions=False)


def _connection_config():
    return {
        "property_id": PROPERTY_ID,
        "native_enabled_tools": ["search"],
        "native_read_only_tools": ["search"],
    }


def _stored_connection(config, *, connection_id=CONNECTION_ID):
    from botelier.models.mcp_connection import (
        MCPAuthType, MCPConnection, MCPConnectionStatus, MCPTransportType,
    )

    connection = MCPConnection(
        id=connection_id,
        account_id=ACCOUNT_ID,
        name="Managed fixture",
        description="Synthetic connection",
        transport_type=MCPTransportType.SSE,
        server_url="https://mcp.example/mcp",
        auth_type=MCPAuthType.API_KEY,
        status=MCPConnectionStatus.CONNECTED,
        last_connected_at=None,
        last_error=None,
        is_active=True,
        connection_config=config,
        created_at=None,
        updated_at=None,
        discovered_tools=[{"name": "search"}],
    )
    connection.get_connection_config = lambda: connection.connection_config
    connection.get_discovered_tools = lambda: connection.discovered_tools
    connection.set_connection_config = lambda value: setattr(
        connection, "connection_config", value,
    )
    connection.set_credentials = lambda _value: None
    connection.get_credentials = lambda: {}
    connection.credentials_encrypted = "synthetic-credential-marker"
    return connection


def _seal_config(config=None):
    from botelier.services.native_mcp_policy import protect_connection_config

    return protect_connection_config(
        config or _connection_config(),
        account_id=ACCOUNT_ID,
        connection_id=CONNECTION_ID,
        db=_DB({"integrations.manage"}),
    )


def test_management_guard_database_namespace_is_mapped_but_cannot_connect():
    import sys

    from botelier.database import Base, get_db
    from botelier.models.mcp_connection import MCPConnection

    database = sys.modules["botelier.database"]
    assert MCPConnection.metadata is Base.metadata
    assert not hasattr(database, "engine")
    assert not hasattr(database, "SessionLocal")
    with pytest.raises(RuntimeError, match="synthetic get_db dependency override"):
        get_db()


def test_non_manager_cannot_create_or_rebind_server_under_native_grant(monkeypatch):
    existing = _stored_connection(_seal_config())
    db = _DB({"integrations.view"}, connection=existing)
    response = _client(monkeypatch, db, _user()).post(
        "/api/mcp-connections",
        json={
            "account_id": ACCOUNT_ID,
            "name": "Self-granted",
            "server_url": "https://new.example/mcp",
            "connection_config": _connection_config(),
        },
    )
    assert response.status_code == 403
    assert db.added == []

    client = _client(monkeypatch, db, _user())
    response = client.put(
        f"/api/mcp-connections/{CONNECTION_ID}",
        json={
            "server_url": "https://attacker.example/mcp",
            "connection_config": {
                **_connection_config(), "account_global": True,
            },
        },
    )
    assert response.status_code == 403
    assert existing.server_url == "https://mcp.example/mcp"
    assert db.commits == 0
    original_token = existing.get_connection_config()["_native_policy_v1"]
    response = client.put(
        f"/api/mcp-connections/{CONNECTION_ID}",
        json={"name": "Renamed without management permission"},
    )
    assert response.status_code == 200, response.text
    assert existing.name == "Renamed without management permission"
    assert existing.get_connection_config()["_native_policy_v1"] == original_token
    assert response.json()["native_flow_policy"]["configured"] is True


def test_manager_native_grant_is_typed_and_property_bound(monkeypatch):
    db = _DB({"integrations.view", "integrations.manage"})
    client = _client(
        monkeypatch, db, _user({"integrations.view", "integrations.manage"}),
    )
    response = client.post(
        "/api/mcp-connections",
        json={
            "account_id": ACCOUNT_ID,
            "name": "Managed fixture",
            "server_url": "https://mcp.example/mcp",
            "connection_config": _connection_config(),
        },
    )
    assert response.status_code == 201, response.text
    from botelier.services.native_mcp_policy import resolve_connection_policy

    stored_config = db.added[0].get_connection_config()
    assert "native_enabled_tools" not in stored_config
    assert "property_id" not in stored_config
    policy = resolve_connection_policy(db.added[0])
    assert policy.property_id == PROPERTY_ID
    assert policy.enabled_tools == ["search"]
    assert policy.read_only_tools == ["search"]

    account_global = {
        "account_global": True,
        "native_enabled_tools": ["search"],
        "native_read_only_tools": ["search"],
    }
    response = client.post(
        "/api/mcp-connections",
        json={
            "account_id": ACCOUNT_ID,
            "name": "Managed account-global fixture",
            "server_url": "https://mcp.example/mcp",
            "connection_config": account_global,
        },
    )
    assert response.status_code == 201, response.text
    global_policy = resolve_connection_policy(db.added[1])
    assert global_policy.account_global is True
    assert global_policy.property_id is None

    invalid = {
        **_connection_config(),
        "native_read_only_tools": ["not-enabled"],
    }
    response = client.post(
        "/api/mcp-connections",
        json={
            "account_id": ACCOUNT_ID,
            "name": "Invalid grant",
            "server_url": "https://mcp.example/mcp",
            "connection_config": invalid,
        },
    )
    assert response.status_code in {400, 422}
    assert len(db.added) == 2

    invalid_global = {
        **account_global,
        "account_global": "true",
    }
    response = client.post(
        "/api/mcp-connections",
        json={
            "account_id": ACCOUNT_ID,
            "name": "Invalid typed global grant",
            "server_url": "https://mcp.example/mcp",
            "connection_config": invalid_global,
        },
    )
    assert response.status_code in {400, 422}
    assert len(db.added) == 2


@pytest.mark.parametrize(("field", "value"), [
    ("server_url", "https://new.example/mcp"),
    ("transport_type", "streamable_http"),
    ("auth_type", "bearer"),
    ("credentials", {"token": "synthetic-rebind-token"}),
])
def test_manager_sensitive_rebind_revokes_old_native_tool_grants(
    monkeypatch, field, value,
):
    from botelier.models.mcp_connection import MCPConnectionStatus

    existing = _stored_connection(_seal_config())
    db = _DB(
        {"integrations.manage"}, connection=existing,
    )
    response = _client(
        monkeypatch, db, _user({"integrations.view", "integrations.manage"}),
    ).put(
        f"/api/mcp-connections/{CONNECTION_ID}",
        json={field: value},
    )
    assert response.status_code == 200, response.text
    if field == "server_url":
        assert existing.server_url == value
    assert not {
        "native_enabled_tools", "native_read_only_tools",
        "property_id", "account_global",
    } & set(existing.connection_config)
    assert "_native_policy_v1" not in existing.connection_config
    assert existing.status == MCPConnectionStatus.DISCONNECTED
    assert existing.discovered_tools == []


def test_public_connection_dto_hides_seal_and_summarizes_valid_policy():
    stored = _seal_config({
        **_connection_config(),
        "timeout_seconds": 12,
        "display": {"label": "Fixture", "compact": True},
    })
    internal_before = deepcopy(stored)
    connection = _stored_connection(stored)

    public = connection.to_dict()

    assert public["connection_config"] == {
        "timeout_seconds": 12,
        "display": {"label": "Fixture", "compact": True},
    }
    assert public["native_flow_policy"] == {
        "configured": True,
        "scope": "property",
        "property_id": PROPERTY_ID,
        "enabled_tools": ["search"],
        "read_only_tools": ["search"],
    }
    assert "_native_policy_v1" not in repr(public)
    assert "synthetic-credential-marker" not in repr(public)
    assert connection.get_connection_config() == internal_before
    public["connection_config"]["display"]["label"] = "Changed only in DTO"
    assert connection.get_connection_config() == internal_before

    account_config = _seal_config({
        "account_global": True,
        "native_enabled_tools": ["search"],
        "native_read_only_tools": ["search"],
        "timeout_seconds": 8,
    })
    account_public = _stored_connection(account_config).to_dict()
    assert account_public["native_flow_policy"] == {
        "configured": True,
        "scope": "account",
        "property_id": None,
        "enabled_tools": ["search"],
        "read_only_tools": ["search"],
    }
    assert account_public["connection_config"] == {"timeout_seconds": 8}


def test_public_connection_dto_marks_legacy_corrupt_and_copied_grants_unconfigured():
    from botelier.services.native_mcp_policy import protect_connection_config

    valid = protect_connection_config(
        _connection_config(), account_id=ACCOUNT_ID,
        connection_id=CONNECTION_ID, db=_DB({"integrations.manage"}),
    )
    copied = deepcopy(valid)
    cases = (
        {
            "timeout_seconds": 5,
            **_connection_config(),
        },
        {"timeout_seconds": 5, "_native_policy_v1": "not-a-valid-seal"},
        {"timeout_seconds": 5, **{
            key: value for key, value in valid.items()
            if key == "_native_policy_v1"
        }},
    )
    for index, config in enumerate(cases):
        connection_id = CONNECTION_ID if index < 2 else str(uuid4())
        if index == 2:
            config = deepcopy(copied)
        connection = _stored_connection(config, connection_id=connection_id)

        public = connection.to_dict()

        assert public["native_flow_policy"] == {
            "configured": False,
            "scope": None,
            "property_id": None,
            "enabled_tools": [],
            "read_only_tools": [],
        }
        assert "_native_policy_v1" not in public["connection_config"]
        assert "native_enabled_tools" not in public["connection_config"]


def test_manager_name_and_ordinary_config_edits_preserve_seal_but_reject_submitted_seal(
    monkeypatch,
):
    stored = _seal_config({
        **_connection_config(),
        "timeout_seconds": 10,
    })
    existing = _stored_connection(stored)
    db = _DB(
        {"integrations.view", "integrations.manage"},
        connection=existing,
    )
    client = _client(
        monkeypatch, db,
        _user({"integrations.view", "integrations.manage"}),
    )
    old_token = existing.get_connection_config()["_native_policy_v1"]

    renamed = client.put(
        f"/api/mcp-connections/{CONNECTION_ID}",
        json={"name": "Renamed fixture"},
    )
    assert renamed.status_code == 200, renamed.text
    assert existing.get_connection_config()["_native_policy_v1"] == old_token

    edited = client.put(
        f"/api/mcp-connections/{CONNECTION_ID}",
        json={"connection_config": {
            "timeout_seconds": 20,
            "display": {"compact": True},
        }},
    )
    assert edited.status_code == 200, edited.text
    assert existing.get_connection_config()["_native_policy_v1"] == old_token
    assert edited.json()["connection_config"] == {
        "timeout_seconds": 20,
        "display": {"compact": True},
    }
    assert edited.json()["native_flow_policy"]["configured"] is True

    before_invalid_update = deepcopy(existing.get_connection_config())
    response = client.put(
        f"/api/mcp-connections/{CONNECTION_ID}",
        json={"connection_config": {
            "timeout_seconds": 30,
            "_native_policy_v1": old_token,
        }},
    )
    assert response.status_code == 400
    assert existing.get_connection_config() == before_invalid_update


def test_manager_can_rebind_with_a_fresh_typed_grant(monkeypatch):
    from botelier.models.mcp_connection import MCPConnectionStatus
    from botelier.services.native_mcp_policy import resolve_connection_policy

    existing = _stored_connection(_seal_config({
        **_connection_config(),
        "timeout_seconds": 10,
    }))
    db = _DB(
        {"integrations.view", "integrations.manage"},
        connection=existing,
    )
    client = _client(
        monkeypatch,
        db,
        _user({"integrations.view", "integrations.manage"}),
    )
    old_token = existing.get_connection_config()["_native_policy_v1"]

    response = client.put(
        f"/api/mcp-connections/{CONNECTION_ID}",
        json={
            "server_url": "https://new.example/mcp",
            "connection_config": {
                "account_global": True,
                "native_enabled_tools": ["search"],
                "native_read_only_tools": ["search"],
                "timeout_seconds": 15,
            },
        },
    )

    assert response.status_code == 200, response.text
    new_token = existing.get_connection_config()["_native_policy_v1"]
    assert new_token != old_token
    assert resolve_connection_policy(existing).account_global is True
    assert response.json()["native_flow_policy"] == {
        "configured": True,
        "scope": "account",
        "property_id": None,
        "enabled_tools": ["search"],
        "read_only_tools": ["search"],
    }
    assert existing.status == MCPConnectionStatus.DISCONNECTED
