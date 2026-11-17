"""Backend authorization and typing for trusted native MCP grants."""

from types import SimpleNamespace
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


def test_non_manager_cannot_create_or_rebind_server_under_native_grant(monkeypatch):
    existing = SimpleNamespace(
        id=CONNECTION_ID,
        account_id=ACCOUNT_ID,
        server_url="https://old.example/mcp",
        connection_config=_connection_config(),
        status=None,
        discovered_tools=[],
        last_error=None,
        last_connected_at=None,
        updated_at=None,
        name="Managed fixture",
        description=None,
        transport_type=None,
        auth_type=None,
        is_active=True,
        get_connection_config=lambda: existing.connection_config,
        set_connection_config=lambda config: setattr(
            existing, "connection_config", config,
        ),
        to_dict=lambda include_tools=True: {},
    )
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
    assert existing.server_url == "https://old.example/mcp"
    assert db.commits == 0


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


def test_manager_server_rebind_revokes_old_native_tool_grants(monkeypatch):
    from botelier.models.mcp_connection import MCPConnectionStatus

    existing = SimpleNamespace(
        id=CONNECTION_ID, account_id=ACCOUNT_ID,
        server_url="https://old.example/mcp",
        connection_config=_connection_config(),
        status=None, discovered_tools=[{"name": "search"}],
        last_error=None, last_connected_at=None, updated_at=None,
        name="Managed fixture", description=None, transport_type=None,
        auth_type=None, is_active=True,
        get_connection_config=lambda: existing.connection_config,
        set_connection_config=lambda config: setattr(
            existing, "connection_config", config,
        ),
        to_dict=lambda include_tools=True: {},
    )
    db = _DB(
        {"integrations.manage"}, connection=existing,
    )
    from botelier.services.native_mcp_policy import protect_connection_config

    existing.connection_config = protect_connection_config(
        _connection_config(), account_id=ACCOUNT_ID,
        connection_id=CONNECTION_ID, db=db,
    )
    response = _client(
        monkeypatch, db, _user({"integrations.view", "integrations.manage"}),
    ).put(
        f"/api/mcp-connections/{CONNECTION_ID}",
        json={"server_url": "https://new.example/mcp"},
    )
    assert response.status_code == 200, response.text
    assert existing.server_url == "https://new.example/mcp"
    assert not {
        "native_enabled_tools", "native_read_only_tools",
        "property_id", "account_global",
    } & set(existing.connection_config)
    assert "_native_policy_v1" not in existing.connection_config
    assert existing.status == MCPConnectionStatus.DISCONNECTED
    assert existing.discovered_tools == []
