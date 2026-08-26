"""Tests for the flow editor's account-scoped connection catalog."""

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from botelier.api import integrations
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


class _Db:
    def __init__(self, connection, policies):
        self.connection = connection
        self.policies = policies

    def query(self, model):
        if model is AccountIntegration:
            return _Query([self.connection])
        if model is ConnectionOperationPolicy:
            return _Query(self.policies)
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