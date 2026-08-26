"""Tests for the flow editor's account-scoped connection catalog."""

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from botelier.api import integrations
from botelier.models.assistant import Assistant as AssistantModel
from botelier.models.integration import (
    AccountIntegration,
    IntegrationStatus,
)
from botelier.models.operation_policy import ConnectionOperationPolicy


ACCOUNT_ID = "00000000-0000-0000-0000-000000000001"


class _Query:
    def __init__(self, rows):
        self.rows = rows

    def filter(self, *_args):
        return self

    def all(self):
        return self.rows

    def first(self):
        return self.rows[0] if self.rows else None


class _Db:
    def __init__(self, connection, policies, assistant=None):
        self.connection = connection
        self.policies = policies
        self.assistant = assistant

    def query(self, model):
        if model is AccountIntegration:
            return _Query([self.connection])
        if model is ConnectionOperationPolicy:
            return _Query(self.policies)
        if model is AssistantModel:
            return _Query([self.assistant] if self.assistant is not None else [])
        raise AssertionError(f"Unexpected model query: {model}")


@pytest.mark.asyncio
async def test_connections_catalog_uses_explicit_account_and_marks_imported_operations(
    monkeypatch,
):
    checked_accounts = []

    def allow_account(user, account_id, db, permission="integrations.view"):
        checked_accounts.append((account_id, permission))

    integration_type = SimpleNamespace(
        id="type-id",
        name="Imported PMS API",
        slug="imported-pms-api",
        origin="customer_imported",
        get_endpoints=lambda: [
            {
                "id": "search_rooms",
                "name": "Search Rooms",
                "method": "GET",
                "path": "/rooms",
                "response_mapping": {"legacy_name": "$.legacy"},
            }
        ],
    )
    connection = SimpleNamespace(
        id="connection-id",
        integration_type_id="type-id",
        integration_type=integration_type,
        connection_name="Sandbox",
        status=IntegrationStatus.CONNECTED,
        connected_at=None,
    )
    policy = SimpleNamespace(
        account_integration_id="connection-id",
        operation_id="search_rooms",
        response_mapping={"room_name": "$.rooms[*].name"},
    )

    monkeypatch.setattr(integrations, "_assert_account_access", allow_account)
    result = await integrations.get_my_connections(
        account_id=ACCOUNT_ID,
        assistant_id=None,
        current_user=object(),
        db=_Db(connection, [policy]),
    )

    assert checked_accounts == [(ACCOUNT_ID, "integrations.view")]
    assert len(result) == 1
    assert result[0].integration_type.origin == "customer_imported"
    endpoint = result[0].integration_type.endpoints[0]
    assert endpoint.source == "imported"
    # The per-connection API Builder projection supersedes the type-level seed.
    assert endpoint.response_mapping == {"room_name": "$.rooms[*].name"}


@pytest.mark.asyncio
async def test_connections_catalog_marks_platform_endpoints_as_seeded(monkeypatch):
    integration_type = SimpleNamespace(
        id="type-id",
        name="Certified PMS",
        slug="certified-pms",
        origin="platform_certified",
        get_endpoints=lambda: [
            {"id": "availability", "name": "Availability", "method": "GET", "path": "/availability"}
        ],
    )
    connection = SimpleNamespace(
        id="connection-id",
        integration_type_id="type-id",
        integration_type=integration_type,
        connection_name=None,
        status=IntegrationStatus.CONNECTED,
        connected_at=None,
    )

    monkeypatch.setattr(integrations, "_assert_account_access", lambda *_args: None)
    result = await integrations.get_my_connections(
        account_id=ACCOUNT_ID,
        assistant_id=None,
        current_user=object(),
        db=_Db(connection, []),
    )

    assert result[0].integration_type.endpoints[0].source == "seeded"


@pytest.mark.asyncio
async def test_connections_catalog_does_not_guess_first_active_membership():
    """An absent dashboard account must never leak the first membership's data."""
    result = await integrations.get_my_connections(
        account_id=None,
        current_user=SimpleNamespace(
            account_memberships=[
                SimpleNamespace(
                    account_id="00000000-0000-0000-0000-000000000002",
                    is_active=True,
                )
            ]
        ),
        db=object(),
    )

    assert result == []


@pytest.mark.asyncio
async def test_connections_catalog_rejects_unpermitted_selected_account(monkeypatch):
    def deny_account(*_args, **_kwargs):
        raise HTTPException(status_code=403, detail="Forbidden")

    monkeypatch.setattr(integrations, "_assert_account_access", deny_account)

    with pytest.raises(HTTPException) as exc:
        await integrations.get_my_connections(
            account_id=ACCOUNT_ID,
            current_user=object(),
            db=object(),
        )

    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_connections_catalog_filters_by_assistant_allowed_ids(monkeypatch):
    """When assistant_id is supplied, only connections in allowed_connection_ids are returned."""
    integration_type = SimpleNamespace(
        id="type-id",
        name="Certified PMS",
        slug="certified-pms",
        origin="platform_certified",
        get_endpoints=lambda: [
            {"id": "availability", "name": "Availability", "method": "GET", "path": "/availability"}
        ],
    )
    allowed_conn = SimpleNamespace(
        id="allowed-connection-id",
        integration_type_id="type-id",
        integration_type=integration_type,
        connection_name="Allowed",
        status=IntegrationStatus.CONNECTED,
        connected_at=None,
    )

    # Assistant explicitly allows only "allowed-connection-id"
    assistant_obj = SimpleNamespace(
        id="assistant-id",
        account_id=ACCOUNT_ID,
        allowed_connection_ids=["allowed-connection-id"],
    )

    monkeypatch.setattr(integrations, "_assert_account_access", lambda *_args: None)
    result = await integrations.get_my_connections(
        account_id=ACCOUNT_ID,
        assistant_id="assistant-id",
        current_user=object(),
        db=_Db(allowed_conn, [], assistant=assistant_obj),
    )

    assert len(result) == 1
    assert result[0].connection_name == "Allowed"


@pytest.mark.asyncio
async def test_connections_catalog_returns_all_when_assistant_has_empty_allowlist(monkeypatch):
    """An assistant with an empty allowed_connection_ids list sees all connections."""
    integration_type = SimpleNamespace(
        id="type-id",
        name="Certified PMS",
        slug="certified-pms",
        origin="platform_certified",
        get_endpoints=lambda: [
            {"id": "availability", "name": "Availability", "method": "GET", "path": "/availability"}
        ],
    )
    connection = SimpleNamespace(
        id="connection-id",
        integration_type_id="type-id",
        integration_type=integration_type,
        connection_name="Any",
        status=IntegrationStatus.CONNECTED,
        connected_at=None,
    )

    # Empty list = no restriction
    assistant_obj = SimpleNamespace(
        id="assistant-id",
        account_id=ACCOUNT_ID,
        allowed_connection_ids=[],
    )

    monkeypatch.setattr(integrations, "_assert_account_access", lambda *_args: None)
    result = await integrations.get_my_connections(
        account_id=ACCOUNT_ID,
        assistant_id="assistant-id",
        current_user=object(),
        db=_Db(connection, [], assistant=assistant_obj),
    )

    # All connections returned — empty allow-list means no restriction
    assert len(result) == 1