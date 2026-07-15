"""HTTP integration tests for GET /api/accounts/{account_id}/team/permission-schema.

These tests use FastAPI's TestClient so the full HTTP routing, middleware wiring,
and dependency resolution stack is exercised (not just the handler function).

Covered scenarios
-----------------
- 401  No Authorization header → unauthenticated user rejected before reaching handler
- 403  Authenticated user without team.manage_roles → Permission denied
- 200  Platform admin → returns full schema (bypasses membership check)
- 200  Regular user with team.manage_roles → returns full schema
- Payload contract  all catalog features / actions / fields in 200 response

Dependency overrides used
-------------------------
- ``get_current_user_optional``  controls who is (or isn't) authenticated;
  overriding this root dependency feeds through ``get_current_user`` and on to
  the ``_get_account_context`` closure without touching JWT machinery.
- ``get_db``  returns a mock SQLAlchemy session; the mock answers Account and
  AccountMembership queries in the order the context resolver issues them.
"""

import os
import uuid
from datetime import datetime
from unittest.mock import MagicMock

os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost/test")
os.environ.setdefault("NEXTAUTH_SECRET", "test-secret-for-testing-only")

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from botelier.auth.middleware import (
    AccountContext,
    get_current_user_optional,
)
from botelier.auth.permissions import PERMISSIONS
from botelier.database import get_db
from botelier.models.account import Account
from botelier.models.role import AccountMembership, Role
from botelier.models.user import User, UserType

# ---------------------------------------------------------------------------
# The router under test
# ---------------------------------------------------------------------------
from botelier.api.team import router as team_router

ACCOUNT_ID = str(uuid.uuid4())

# ---------------------------------------------------------------------------
# Factory helpers
# ---------------------------------------------------------------------------


def _make_account() -> Account:
    account = MagicMock(spec=Account)
    account.id = ACCOUNT_ID
    return account


def _make_platform_admin() -> User:
    user = MagicMock(spec=User)
    user.id = uuid.uuid4()
    user.user_type = UserType.PLATFORM_ADMIN
    user.is_platform_admin = True
    user.is_active = True
    return user


def _make_regular_user(has_role_manage: bool = True) -> User:
    user = MagicMock(spec=User)
    user.id = uuid.uuid4()
    user.user_type = UserType.ACCOUNT_USER
    user.is_platform_admin = False
    user.is_active = True
    return user


def _make_membership(has_role_manage: bool) -> AccountMembership:
    membership = MagicMock(spec=AccountMembership)
    membership.is_active = True

    def _has_permission(perm: str) -> bool:
        if has_role_manage and perm == "team.manage_roles":
            return True
        # Grant team.view so the context can be built; only manage_roles matters here
        return perm == "team.view"

    membership.has_permission.side_effect = _has_permission
    return membership


def _db_for_account(membership=None) -> MagicMock:
    """Return a DB mock that yields an Account, then optionally a Membership."""
    db = MagicMock()
    account = _make_account()

    def _query(model):
        q = MagicMock()
        if model is Account:
            q.filter.return_value.first.return_value = account
        elif model is AccountMembership:
            q.filter.return_value.first.return_value = membership
        else:
            q.filter.return_value.first.return_value = None
            q.filter.return_value.count.return_value = 0
        return q

    db.query.side_effect = _query
    db.commit.return_value = None
    return db


# ---------------------------------------------------------------------------
# TestClient factory
# ---------------------------------------------------------------------------


def _build_client(user_override, db_override) -> TestClient:
    """Build a TestClient for the team router with the given dependency overrides.

    The team router already carries the full prefix
    ``/api/accounts/{account_id}/team`` internally (see team.py line 28),
    so we mount it with no additional prefix.
    """
    app = FastAPI()
    app.include_router(team_router)
    app.dependency_overrides[get_current_user_optional] = user_override
    app.dependency_overrides[get_db] = db_override
    return TestClient(app, raise_server_exceptions=False)


def _schema_url() -> str:
    return f"/api/accounts/{ACCOUNT_ID}/team/permission-schema"


# ---------------------------------------------------------------------------
# 401 — unauthenticated
# ---------------------------------------------------------------------------


def test_permission_schema_unauthenticated_returns_401():
    """No auth token → 401 before handler is called."""

    def no_user():
        return None

    def mock_db():
        return MagicMock()

    client = _build_client(no_user, mock_db)
    resp = client.get(_schema_url())
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# 403 — authenticated but lacking team.manage_roles
# ---------------------------------------------------------------------------


def test_permission_schema_forbidden_without_manage_roles():
    """Authenticated user without team.manage_roles → 403."""
    user = _make_regular_user()
    membership = _make_membership(has_role_manage=False)
    db = _db_for_account(membership=membership)

    def get_user():
        return user

    def get_mock_db():
        return db

    client = _build_client(get_user, get_mock_db)
    resp = client.get(_schema_url())
    assert resp.status_code == 403
    assert "team.manage_roles" in resp.json().get("detail", "")


# ---------------------------------------------------------------------------
# 200 — platform admin (bypasses membership)
# ---------------------------------------------------------------------------


def test_permission_schema_platform_admin_returns_200():
    """Platform admin receives the schema without a membership row."""
    user = _make_platform_admin()
    db = _db_for_account(membership=None)

    def get_user():
        return user

    def get_mock_db():
        return db

    client = _build_client(get_user, get_mock_db)
    resp = client.get(_schema_url())
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# 200 — regular user with team.manage_roles
# ---------------------------------------------------------------------------


def test_permission_schema_authorized_user_returns_200():
    """Regular user with team.manage_roles → 200 with valid schema."""
    user = _make_regular_user()
    membership = _make_membership(has_role_manage=True)
    db = _db_for_account(membership=membership)

    def get_user():
        return user

    def get_mock_db():
        return db

    client = _build_client(get_user, get_mock_db)
    resp = client.get(_schema_url())
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Payload contract tests (all run against an authorized 200 response)
# ---------------------------------------------------------------------------


def _authorized_response():
    user = _make_platform_admin()
    db = _db_for_account(membership=None)

    def get_user():
        return user

    def get_mock_db():
        return db

    client = _build_client(get_user, get_mock_db)
    resp = client.get(_schema_url())
    assert resp.status_code == 200
    return resp.json()


def test_permission_schema_payload_has_features_list():
    data = _authorized_response()
    assert "features" in data
    assert isinstance(data["features"], list)
    assert len(data["features"]) > 0


def test_permission_schema_payload_contains_all_catalog_features():
    data = _authorized_response()
    returned_keys = {f["key"] for f in data["features"]}
    for feature in PERMISSIONS:
        assert feature in returned_keys, f"Feature '{feature}' missing from HTTP response"


def test_permission_schema_payload_contains_all_catalog_actions():
    data = _authorized_response()
    schema_map = {f["key"]: {p["key"] for p in f["permissions"]} for f in data["features"]}
    for feature, actions in PERMISSIONS.items():
        for action in actions:
            assert action in schema_map.get(feature, set()), (
                f"Action '{feature}.{action}' missing from HTTP response"
            )


def test_permission_schema_payload_permission_items_shape():
    """Every permission item has key, full_key, label, description."""
    data = _authorized_response()
    for feature in data["features"]:
        assert "key" in feature
        assert "permissions" in feature
        for perm in feature["permissions"]:
            assert "key" in perm
            assert "full_key" in perm
            assert "label" in perm
            assert "description" in perm
            assert perm["full_key"] == f"{feature['key']}.{perm['key']}"


def test_permission_schema_payload_includes_new_feature_areas():
    """The six areas absent from the old hardcoded schema are in the HTTP response."""
    data = _authorized_response()
    returned_keys = {f["key"] for f in data["features"]}
    for area in ("integrations", "messages", "usage", "billing_rates", "properties", "records"):
        assert area in returned_keys, f"Feature area '{area}' missing from HTTP response"
